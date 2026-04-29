"""
apps/api/tasks/blueprint_tasks.py
技能蓝图异步生成任务 — 三段式架构：读取 / LLM / 写入分离

V2 (2026-04-14):
- embedding 聚类 + 每簇命名 + 动态章节数
- 多文档增量 merge 模式（Phase 7）
- V1 旧逻辑已于 2026-04-27 清理（D1-D5）
"""
from __future__ import annotations
import asyncio, json, math, os, re
from collections import defaultdict
import structlog
from apps.api.tasks.tutorial_tasks import celery_app
from apps.api.tasks.task_tracker import task_tracker

logger = structlog.get_logger()

# ══════════════════════════════════════════
# Shared Prompts（V2 及 merge 共用）
# ══════════════════════════════════════════

CHAPTER_CONTENT_PROMPT = """为职业技能课程撰写章节正文，严格按结构输出 JSON。

本章：{chapter_title}
目标：{objective}
任务：{task_description}
{teacher_instruction}

【代码格式规则 - 必须严格遵守】
1. full_content 中的代码使用三个反引号围栏标记（```），换行后写代码，再换行写三个反引号关闭。格式：
```python
def example():
    pass
```
2. 代码围栏必须指定语言标识（python/sql/bash/javascript/java/xml/html/json/yaml/dockerfile）
3. 禁止在代码围栏内写注释标记之外的伪代码或描述文本
4. 行内代码（如变量名、文件名、命令名）使用单个反引号包裹，如 `web.xml`、`nginx -t`
5. 禁止输出原始 ⏸ 字符——互动标记必须使用 <!--CHECKPOINT:问题|解析提示--> 格式，前端会自动渲染为 ⏸ 图标
6. code_example 字段中的代码同样使用三个反引号围栏，外围不要添加 HTML 标签

【负面清单 - 以下格式判定为不合格】
❌ 裸 SQL：SELECT * FROM users WHERE ...
❌ 裸代码没有围栏：filter_rules = [r'[^a-zA-Z0-9_]']
❌ 裸 ⏸ 字符出现在正文中
❌ `...` 形式的围栏（仅限单行行内代码使用）
❌ 代码与中文描述混在同一行（如：使用 curl http://api 命令获取数据 —— 错误，应分行写）

只输出以下 JSON：
{{
  "scene_hook": "100字以内，真实职场情境，以'你'开头，引出本章核心问题",
  "skim_summary": "用分号分隔的3条要点，每条不超过20字",
  "full_content": "正文600-900字。含概念/原理/步骤/示例。术语用【名称】标注。在适当位置插入1-2个<!--CHECKPOINT:问题|解析提示-->标记。代码必须用三个反引号围栏包裹",
  "code_example": "如本章涉及编程或命令行操作，提供1个完整可运行示例（含行内注释），用三个反引号围栏包裹。不涉及编程则填空字符串",
  "misconception_block": "⚠️ 很多人误认为……，实际上……（针对本章常见误解）",
  "prereq_adaptive": {{
    "if_high": "必填。针对已掌握基础的学员，补充更深层技术细节、边界案例或进阶应用场景，100字以内"
  }}
}}"""

# ══════════════════════════════════════════
# V2 Prompts（新逻辑使用）
# ══════════════════════════════════════════

CLUSTER_CHAPTER_PROMPT = """你是课程设计师。以下是同一主题簇的知识点：
{teacher_instruction}
知识点列表：
{entities_json}

为这组知识点设计一个教学章节，同时判定章节的课型（chapter_type），严格按 JSON 输出，不含其他内容：

课型判定规则：
- theory（原理课）：知识点以概念定义、术语辨析、底层机制解释为主。例如：SQL注入原理、加密算法机制、OSI模型层次
- task（任务课）：知识点以具体操作、工具使用、分步流程为主。例如：配置防火墙规则、使用nmap扫描、编写SQL查询
- project（实战课）：知识点需要综合运用多项技能解决真实问题。例如：完整渗透测试、搭建安全监控系统、灾备方案设计

{{
  "title": "章节标题（动词短语，如'识别常见注入攻击'）",
  "objective": "学完能够……（一句话）",
  "task_description": "练习任务",
  "pass_criteria": "通过标准",
  "common_mistakes": "常见误区",
  "chapter_type": "theory 或 task 或 project"
}}"""

COURSE_TITLE_PROMPT = """你是课程设计师。以下是一门安全课程的所有章节标题：
{teacher_instruction}
{chapter_titles_json}

为这门课程起一个简洁的标题和一句话技能目标，严格按 JSON 输出：
{{
  "title": "课程标题",
  "skill_goal": "学完后能做到什么（一句话）"
}}"""

STAGE_PLANNING_PROMPT = """你是课程设计师。以下是一门课程的所有章节（index 为原始编号，不可修改）：
{teacher_instruction}
{chapters_json}

请完成两项任务：
1. 按学习难度从易到难重新分组，形成若干阶段
2. 检查动词多样性——同一动词开头的章节超过 15% 时，为多余的章节重命名

分组规则：
- 第一阶段（foundation）：基础概念、术语、原理（入门）
- 中间阶段（practice）：工具操作、技能实践（进阶）
- 最后阶段（assessment）：综合应用、防御对抗、评估分析（高阶）
- 每阶段 3~6 章，阶段数 = ceil(总章节数 / 5)，最少 2 个

动词多样性规则（可用动词）：
识别、理解、应用、分析、评估、构建、设计、防御、检测、配置、实施、调试、优化、比较、解释、演示

严格按 JSON 输出，不含其他内容：
{{
  "stages": [
    {{
      "title": "阶段名（如：基础认知、工具实践、综合防御）",
      "type": "foundation",
      "chapter_indices": [2, 0, 5]
    }}
  ],
  "renamed_chapters": {{
    "1": "新标题（如因动词重复需重命名才填写）"
  }}
}}

要求：type 只选 foundation、practice、assessment 之一；所有 chapter_indices 必须恰好覆盖 0~{total_minus_one} 各一次。"""


# ══════════════════════════════════════════
# Layer 1/2/3: 教师引导式迭代 — 前缀 + 精调 + 讨论种子
# ══════════════════════════════════════════

TEACHER_INSTRUCTION_PREFIX = """
【教师教学要求 — 优先级最高，必须严格遵守】
{instruction}

如果教师要求与默认规则冲突，以教师要求为准。
"""

CHAPTER_REFINEMENT_PROMPT = """你是课程编辑助手。教师要求修改以下章节的教学内容。

## 章节当前信息
- 标题：{chapter_title}
- 教学目标：{objective}
- 练习任务：{task_description}
- 当前内容摘要：{current_content_summary}

## 教师修改指令（优先级最高）
{teacher_instruction}

## 全局教学约束
{global_instruction}

请根据教师指令重写本章完整内容，同时遵循全局教学约束。
严格按以下 JSON 输出（与章节内容原始格式一致）：
{{
  "scene_hook": "100字以内，真实职场情境，以'你'开头",
  "skim_summary": "用分号分隔的3条要点，每条不超过20字",
  "full_content": "正文600-900字，含概念/原理/步骤/示例，术语用【名称】标注",
  "code_example": "完整可运行代码示例（如适用），否则为空字符串",
  "misconception_block": "常见误解与纠正",
  "prereq_adaptive": {{"if_high": "进阶补充内容，100字以内"}}
}}"""

DISCUSSION_SEED_PROMPT = """基于以下章节内容，生成 2 个课堂讨论问题：

章节标题：{chapter_title}
内容摘要：{content_summary}

讨论问题应鼓励学习者思考实际应用、探讨边界情况或分享经验。
严格按 JSON 数组输出：
[{{"title": "讨论主题（15字以内）", "content": "问题详细描述（50-100字）"}}]"""


# ══════════════════════════════════════════
# 章节内容后处理标准化
# ══════════════════════════════════════════

def _repair_json_text(text: str) -> str | None:
    """修复 LLM 输出中常见的 JSON 格式问题。返回修复后的字符串，无法修复返回 None。"""
    fixed = text
    # 移除尾随逗号（最常见）：",  }" → "  }", ", ]" → " ]"
    fixed = re.sub(r',(\s*[}\]])', r'\1', fixed)
    if fixed != text:
        try:
            json.loads(fixed)
            return fixed
        except json.JSONDecodeError:
            pass
    return None


def _text_only_cleanup(raw_text: str) -> str:
    """JSON 解析失败时的降级处理：从 JSON 字符串中智能提取 full_content 值。

    核心问题：LLM 输出的 JSON 中，full_content 字段可能包含未转义的双引号
    （如 bash 命令中的 "http://..."），导致 json.loads 失败。
    此函数通过 JSON 键定位 + 闭合引号扫描，正确提取字段值。
    """
    cleaned = raw_text
    # 移除 ⏸ 暂停标记
    cleaned = cleaned.replace("\u23f8", "").replace("⏸", "")

    # 转换 markdown 围栏 ```lang\ncode\n``` → <pre><code>
    fence_pattern = re.compile(r'```(\w*)\s*\n(.*?)```', re.DOTALL)
    def _replace_fence(m: re.Match) -> str:
        lang = m.group(1) or "text"
        code = m.group(2).rstrip()
        if not code.strip():
            return ""
        code = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<pre><code class="language-{lang}">{code}</code></pre>'

    # 尝试从 JSON 字符串中提取 full_content 值
    fc_key = '"full_content"'
    fc_pos = cleaned.find(fc_key)
    if fc_pos != -1:
        # 找到 key 后的冒号和值起始引号
        colon_pos = cleaned.find(':', fc_pos + len(fc_key))
        if colon_pos != -1:
            val_start = cleaned.find('"', colon_pos + 1)
            if val_start != -1:
                val_start += 1  # 跳过值的起始引号
                # 从值起始处向后扫描，跟踪反斜杠转义，找到闭合引号
                i = val_start
                while i < len(cleaned):
                    ch = cleaned[i]
                    if ch == '\\':
                        i += 2  # 跳过转义字符（如 \n, \", \\）
                        continue
                    if ch == '"':
                        # 检查引号后是否紧跟 JSON 结构字符（, 或 }）
                        after = cleaned[i + 1:].lstrip() if i + 1 < len(cleaned) else ""
                        if not after or after[0] in (',', '}'):
                            # 找到闭合引号 → 提取值内容
                            extracted = cleaned[val_start:i]
                            # 反转义 JSON 字符串
                            extracted = extracted.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\').replace('\\t', '\t')
                            # 转换 markdown 围栏
                            extracted = fence_pattern.sub(_replace_fence, extracted)
                            logger.info("text_only_cleanup: full_content extracted",
                                       length=len(extracted))
                            return extracted
                    i += 1

    # 无法提取 full_content → 清理全文并去掉 JSON 包装
    logger.warning("text_only_cleanup: full_content extraction failed, cleaning raw text")
    cleaned = fence_pattern.sub(_replace_fence, cleaned)
    # 去掉 JSON 对象包装字符（{ 和 }）
    cleaned = cleaned.strip()
    if cleaned.startswith('{'):
        cleaned = cleaned[1:]
    if cleaned.endswith('}'):
        cleaned = cleaned[:-1]
    return cleaned.strip()


def _normalize_chapter_content(raw_json_str: str) -> str:
    """
    标准化 LLM 生成的章节内容 JSON，修复代码格式和交互标记问题。

    处理项：
    1. 移除裸 ⏸ 字符（应由 <!--CHECKPOINT:...--> 替代）
    2. 将 markdown 代码围栏（```）转换为 <pre><code> 格式（兼容 v-html 渲染）
    3. 自动检测裸代码行（无围栏包裹的 SQL/Python/Shell 代码）并包裹
    4. 确保 code_example 字段有正确的语言标识
    5. 容忍 JSON 边界空白（前导/尾随的非 JSON 内容）
    6. JSON 解析失败时降级为文本清理，不暴露原始 JSON 结构
    """
    # Step 0: JSON 提取（尝试解析，失败则返回原文）
    raw_str = raw_json_str.strip()
    if not raw_str:
        return raw_str

    # 尝试找到 JSON 对象的起止位置（容忍 LLM 在前后添加 markdown/文本）
    json_start = raw_str.find("{")
    json_end = raw_str.rfind("}")
    if json_start == -1 or json_end <= json_start:
        return raw_str
    json_candidate = raw_str[json_start:json_end + 1]

    try:
        data = json.loads(json_candidate)
    except json.JSONDecodeError:
        # JSON 解析失败：尝试修复常见 LLM 问题（尾随逗号等）
        repaired = _repair_json_text(json_candidate)
        if repaired:
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                repaired = None
        if not repaired:
            # 无法修复：对原始文本做清理后封装为合法 JSON，避免前端渲染原始 JSON
            logger.warning("normalize_chapter_content: JSON parse failed, falling back to text-only")
            cleaned = _text_only_cleanup(raw_str)
            return json.dumps({"full_content": cleaned}, ensure_ascii=False)
        else:
            data = json.loads(repaired)
            logger.info("normalize_chapter_content: JSON repaired successfully")

    if not isinstance(data, dict):
        # 解析结果不是 dict，做文本清理
        cleaned = _text_only_cleanup(raw_str)
        return json.dumps({"full_content": cleaned}, ensure_ascii=False)

    # Step 1: 移除裸 ⏸ 字符（全字段）
    def _strip_pause(s: str) -> str:
        return s.replace("\u23f8", "").replace("⏸", "")

    # Step 2: 代码围栏转换 + 裸代码检测
    def _normalize_code_blocks(text: str) -> str:
        """将 markdown ```fences``` 转为 <pre><code>，并检测未围栏的代码行"""
        if not text:
            return text

        # 2a: 转换已围栏的代码块 ```lang\ncode\n```
        fence_pattern = re.compile(
            r'```(\w*)\s*\n(.*?)```', re.DOTALL
        )

        def _replace_fence(m: re.Match) -> str:
            lang = m.group(1) or "text"
            code = m.group(2).rstrip()
            if not code.strip():
                return ""
            # 转义 HTML 实体（防止 v-html 误解析）
            code = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return f'<pre><code class="language-{lang}">{code}</code></pre>'

        text = fence_pattern.sub(_replace_fence, text)

        # 2b: 检测未围栏的裸代码段
        # 将非中文、含代码特征的连续行包裹为 <pre><code>
        import re as _re2

        def _is_code_line(line: str) -> bool:
            """判断单行是否为代码行（非中文、含代码特征符号）"""
            stripped = line.strip()
            if not stripped:
                return False
            # 排除已包裹的 <pre><code> 标签（避免双重包裹）
            if '<pre>' in stripped or '<code>' in stripped or '</pre>' in stripped or '</code>' in stripped:
                return False
            # 排除纯中文行
            chinese_chars = len(_re2.findall(r'[\u4e00-\u9fff]', stripped))
            if chinese_chars > len(stripped) * 0.3:
                return False
            # 排除 Markdown 标题、列表、分隔线
            if _re2.match(r'^(#{1,6}\s|[-*+]\s|\d+\.\s|[>|]|[-*_]{3,}\s*$)', stripped):
                return False
            # 排除纯标点/箭头/emoji 行
            if _re2.match(r'^[→↓↑←▶▼▲►●○✓✅❌⚠️📖🔗⭐⏸\s]+$', stripped):
                return False
            # SQL 关键字开头 → 代码行
            if _re2.match(
                r'^(SELECT|INSERT|UPDATE|DELETE|CREATE\s+TABLE|ALTER\s+TABLE|'
                r'DROP\s+TABLE|GRANT|REVOKE|EXEC|EXECUTE|PREPARE|DEALLOCATE\s+PREPARE|'
                r'BEGIN|COMMIT|ROLLBACK|TRUNCATE|MERGE|REPLACE|UPSERT)\s',
                stripped, _re2.IGNORECASE
            ):
                return True
            # 含代码特征符号
            code_indicators = [
                r'(def\s+\w+\s*\(|class\s+\w+\s*[:\(])',           # Python
                r'(function\s+\w+\s*\(|const\s+\w+\s*=|let\s+\w+\s*=|=>)',  # JS
                r'(public\s+(class|void|static|int|String|boolean)\s)',  # Java
                r'^(import\s+|from\s+\w+\s+import|package\s+)',      # imports
                r'^(#include|#define|#ifndef|#endif)',               # C/C++
                r'^[{}();]$',                                         # 单行括号
                r'^\s{2,}(?![-*]\s)',                                # 缩进行（非列表）
                r'[{}();]\s*$',                                      # 行尾代码符号
                r'^\s*(print|console\.log|System\.out)\s*[.(]',      # 打印语句
                r'^\s*(try|catch|finally|except|raise|throw|return|yield|await|async)\s',  # 控制流
                r'^\s*(pip|npm|docker|curl|wget|git|apt|yum)\s',     # CLI
                r'^\s*<\?xml|<context-param|<filter>|<servlet|<bean\s', # XML
            ]
            for pattern in code_indicators:
                if _re2.search(pattern, stripped):
                    return True
            return False

        def _wrap_bare_code(text: str) -> str:
            """将连续代码行包裹为 <pre><code>"""
            lines = text.split('\n')
            result: list[str] = []
            code_buffer: list[str] = []
            in_code = False

            for i, line in enumerate(lines):
                is_code = _is_code_line(line)
                stripped = line.strip()

                if is_code:
                    if not in_code:
                        # 开始新代码块
                        in_code = True
                        code_buffer = [line]
                    else:
                        code_buffer.append(line)
                else:
                    if in_code:
                        # 结束代码块：至少 2 行才包裹（单行可能是误判）
                        if len(code_buffer) >= 2:
                            code_text = '\n'.join(code_buffer)
                            lang = _detect_code_language(code_text)
                            escaped = code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                            result.append(f'<pre><code class="language-{lang}">{escaped}</code></pre>')
                            logger.debug("bare_code_wrapped", lines=len(code_buffer), lang=lang,
                                        preview=code_text[:80])
                        else:
                            # 单行放回原文
                            result.extend(code_buffer)
                        in_code = False
                        code_buffer = []
                    result.append(line)

            # 处理文件末尾的代码块
            if in_code and len(code_buffer) >= 2:
                code_text = '\n'.join(code_buffer)
                lang = _detect_code_language(code_text)
                escaped = code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                result.append(f'<pre><code class="language-{lang}">{escaped}</code></pre>')
                logger.debug("bare_code_wrapped", lines=len(code_buffer), lang=lang,
                            preview=code_text[:80])
            elif in_code:
                result.extend(code_buffer)

            return '\n'.join(result)

        text = _wrap_bare_code(text)
        return text

    # Step 3: code_example 标准化
    def _normalize_code_example(code: str) -> str:
        """确保 code_example 用 <pre><code> 包裹"""
        if not code or not code.strip():
            return ""
        code = code.strip()

        # 如果已经是 HTML 包裹格式，直接返回
        if re.match(r'^\s*<pre><code', code):
            return code

        # 如果使用 markdown 围栏，提取内部代码
        fence_match = re.match(r'^```(\w*)\s*\n(.*?)```\s*$', code, re.DOTALL)
        if fence_match:
            lang = fence_match.group(1) or _detect_code_language(fence_match.group(2))
            inner = fence_match.group(2).strip()
            inner = inner.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return f'<pre><code class="language-{lang}">{inner}</code></pre>'

        # 自动检测语言并包裹
        lang = _detect_code_language(code)
        code_escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f'<pre><code class="language-{lang}">{code_escaped}</code></pre>'

    def _detect_code_language(code: str) -> str:
        """根据代码内容推断编程语言"""
        if re.search(
            r'(def\s+\w+\s*\(|import\s+\w+|from\s+\w+\s+import|'
            r'print\s*\(|class\s+\w+.*:|\.append\(|\.format\()',
            code
        ):
            return "python"
        if re.search(
            r'(SELECT\s+|INSERT\s+INTO\s+|UPDATE\s+\w+\s+SET\s+|'
            r'DELETE\s+FROM\s+|CREATE\s+TABLE\s+)',
            code, re.IGNORECASE
        ):
            return "sql"
        if re.search(
            r'(#!/bin/(bash|sh)|apt-get|apt\s|npm\s|pip\s|docker\s|'
            r'curl\s|wget\s|grep\s|sed\s|awk\s|chmod\s|chown\s|'
            r'systemctl\s|psql\s|mysql\s)',
            code
        ):
            return "bash"
        if re.search(
            r'(function\s+\w+|const\s+\w+\s*=|let\s+\w+\s*=|'
            r'var\s+\w+\s*=|=>|console\.log|document\.querySelector)',
            code
        ):
            return "javascript"
        if re.search(r'(<\?xml|<context-param|<filter>|<servlet>)', code):
            return "xml"
        if re.search(
            r'(public\s+class\s+|private\s+\w+\s+\w+|protected\s+\w+\s+'
            r'|System\.out\.print|@Override|@Bean)',
            code
        ):
            return "java"
        return "text"

    # 应用所有标准化
    if "full_content" in data and isinstance(data["full_content"], str):
        fc = data["full_content"]
        fc = _strip_pause(fc)
        fc = _normalize_code_blocks(fc)
        data["full_content"] = fc

    if "code_example" in data and isinstance(data["code_example"], str):
        ce = _strip_pause(data["code_example"])
        data["code_example"] = _normalize_code_example(ce)

    if "scene_hook" in data and isinstance(data["scene_hook"], str):
        data["scene_hook"] = _strip_pause(data["scene_hook"])

    if "misconception_block" in data and isinstance(data["misconception_block"], str):
        data["misconception_block"] = _strip_pause(data["misconception_block"])

    if "skim_summary" in data and isinstance(data["skim_summary"], str):
        data["skim_summary"] = _strip_pause(data["skim_summary"])

    return json.dumps(data, ensure_ascii=False)


def _extract_chapter_fields(normalized_json: str) -> dict[str, str | None]:
    """
    Phase 8：从 _normalize_chapter_content 输出的 JSON 中提取各字段值。
    返回 None 表示该字段不存在或为空。
    用于写入 skill_chapters 的结构化列。
    """
    try:
        data = json.loads(normalized_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}

    def _val(key: str) -> str | None:
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        return None

    return {
        "full_content":        _val("full_content") or normalized_json,
        "scene_hook":          _val("scene_hook"),
        "code_example":        _val("code_example"),
        "misconception_block": _val("misconception_block"),
        "skim_summary":        _val("skim_summary"),
        "prereq_adaptive":     _val("prereq_adaptive"),
    }


def _build_chapter_response(row, include_content: bool = True) -> dict:
    """
    Phase 8：从 skill_chapters 查询行构建 API 响应 dict。
    优先取结构化列值，列值为 NULL 时 fallback 到 content_text JSON 解析。
    旧数据无缝兼容。
    """
    import json as _j8
    result = {
        "chapter_id":       str(row.chapter_id),
        "title":            row.title,
        "objective":        row.objective,
        "task_description": row.task_description,
        "pass_criteria":    row.pass_criteria,
        "common_mistakes":  row.common_mistakes,
        "content_text":     getattr(row, "content_text", ""),  # 向后兼容
        "chapter_order":    row.chapter_order,
        "status":           row.status,
    }

    if not include_content:
        return result

    # 优先使用结构化列
    scene_hook          = getattr(row, "scene_hook", None)
    code_example        = getattr(row, "code_example", None)
    misconception_block = getattr(row, "misconception_block", None)
    skim_summary        = getattr(row, "skim_summary", None)
    prereq_adaptive     = getattr(row, "prereq_adaptive", None)
    content_text        = getattr(row, "content_text", "")

    # 如果结构化列全为空，从 content_text JSON fallback
    if not any([scene_hook, code_example, misconception_block, skim_summary]):
        try:
            data = _j8.loads(content_text) if content_text else {}
            if isinstance(data, dict):
                result["full_content"]        = data.get("full_content", "")
                result["scene_hook"]          = data.get("scene_hook", "") or ""
                result["code_example"]        = data.get("code_example", "") or ""
                result["misconception_block"] = data.get("misconception_block", "") or ""
                result["skim_summary"]        = data.get("skim_summary", "") or ""
                result["prereq_adaptive"]     = data.get("prereq_adaptive", "") or ""
                return result
        except (_j8.JSONDecodeError, TypeError):
            pass
        # 极旧数据：content_text 不是 JSON
        result["full_content"] = content_text or ""
        result["scene_hook"]          = ""
        result["code_example"]        = ""
        result["misconception_block"] = ""
        result["skim_summary"]        = ""
        result["prereq_adaptive"]     = ""
    else:
        # 结构化列存在：从 content_text JSON 提取 full_content（兼容 JSON 和纯文本）
        full = content_text or ""
        try:
            data = _j8.loads(content_text) if content_text else {}
            if isinstance(data, dict):
                full = data.get("full_content", content_text) or content_text
        except (_j8.JSONDecodeError, TypeError):
            pass
        result["full_content"]        = full
        result["scene_hook"]          = scene_hook or ""
        result["code_example"]        = code_example or ""
        result["misconception_block"] = misconception_block or ""
        result["skim_summary"]        = skim_summary or ""
        result["prereq_adaptive"]     = prereq_adaptive or ""

    return result


# ══════════════════════════════════════════
# V2 过滤规则
# ══════════════════════════════════════════

def _is_non_teaching_entity(name: str, definition: str) -> bool:
    """判断实体是否为非教学内容（CVE/版本号/厂商产品），应从蓝图生成中排除。"""
    if re.match(r'CVE-\d{4}-\d+', name):
        return True
    if name.startswith("GHSA-"):
        return True
    if re.match(r'Windows (Server |10 |11 )', name):
        return True
    if name.startswith("NetScaler "):
        return True
    if "深信服" in name:
        return True
    if re.match(r'\d+\.\d+', name) or name in ("7900端口", "8000/tcp"):
        return True
    defn = (definition or "").lower()
    if any(kw in defn for kw in ("受此漏洞影响", "受影响的", "受此powershell")):
        return True
    return False


# ══════════════════════════════════════════
# V2 工具函数：聚类后处理 + Stage 规划
# ══════════════════════════════════════════

def _rebalance_clusters(
    clusters: "dict[int, list[dict]]",
    MIN_SIZE: int = 3,
    MAX_SIZE: int = 12,
    target_size: int = 7,
) -> "dict[int, list[dict]]":
    """
    P3 fix: 合并过小的簇（< MIN_SIZE），拆分过大的簇（> MAX_SIZE）。
    每个 entity dict 须含 '_vec' 字段（np.ndarray）。
    """
    import numpy as np
    from sklearn.cluster import KMeans as _KMeans
    from collections import defaultdict as _dd

    def _centroid(members):
        return np.mean([m["_vec"] for m in members], axis=0)

    result: dict[int, list[dict]] = dict(clusters)

    # 1. 拆分超大簇
    next_id = max(result.keys()) + 1 if result else 0
    for cid in [c for c, m in result.items() if len(m) > MAX_SIZE]:
        members = result.pop(cid)
        k = math.ceil(len(members) / target_size)
        vecs = np.array([m["_vec"] for m in members])
        sub_labels = _KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(vecs)
        sub: dict[int, list] = _dd(list)
        for m, sl in zip(members, sub_labels):
            sub[int(sl)].append(m)
        for sc in sub.values():
            result[next_id] = sc
            next_id += 1
    logger.info("[V2] After split", clusters=len(result),
                sizes=sorted([len(v) for v in result.values()], reverse=True))

    # 2. 合并过小簇（可能多轮）
    changed = True
    while changed:
        changed = False
        small_ids = [cid for cid, m in result.items() if len(m) < MIN_SIZE]
        if not small_ids or len(result) <= 1:
            break
        for scid in small_ids:
            if scid not in result or len(result) <= 1:
                continue
            sc_center = _centroid(result[scid])
            best_cid = min(
                (cid for cid in result if cid != scid),
                key=lambda cid: np.linalg.norm(sc_center - _centroid(result[cid]))
            )
            result[best_cid].extend(result.pop(scid))
            changed = True
    logger.info("[V2] After merge", clusters=len(result),
                sizes=sorted([len(v) for v in result.values()], reverse=True))

    return result


async def _plan_stages_with_llm(
    llm,
    chapters_info: "list[dict]",
    total_chapters: int,
    instruction_block: str = "",
) -> dict:
    """
    P1+P2 fix: 用 LLM 按难度分组章节，同时修复动词重复。
    返回 {"stages": [...], "renamed_chapters": {...}} 格式。
    降级时返回简单均等分组。
    """
    prompt = STAGE_PLANNING_PROMPT.format(
        chapters_json=json.dumps(chapters_info, ensure_ascii=False, indent=2),
        total_minus_one=total_chapters - 1,
        teacher_instruction=instruction_block,
    )
    try:
        raw = await asyncio.wait_for(
            llm.generate(prompt, model_route="knowledge_extraction"),
            timeout=120,
        )
        plan = _parse_json(raw)
        if plan and "stages" in plan:
            seen: set[int] = set()
            valid = True
            for stage in plan["stages"]:
                for idx in stage.get("chapter_indices", []):
                    if not isinstance(idx, int) or idx < 0 or idx >= total_chapters or idx in seen:
                        valid = False
                        break
                    seen.add(idx)
                if not valid:
                    break
            if valid and seen == set(range(total_chapters)):
                logger.info("[V2] Stage planning done via LLM",
                            stages=len(plan["stages"]),
                            renames=len(plan.get("renamed_chapters") or {}))
                return plan
        logger.warning("[V2] Stage planning output invalid, falling back")
    except Exception as exc:
        logger.warning("[V2] Stage planning LLM failed", error=str(exc))

    # 降级：按字母序均等分组
    sorted_indices = sorted(range(total_chapters), key=lambda i: chapters_info[i]["title"])
    FALLBACK_PER_STAGE = 5
    total_stages = math.ceil(total_chapters / FALLBACK_PER_STAGE)
    stages = []
    for s in range(total_stages):
        chunk = sorted_indices[s * FALLBACK_PER_STAGE:(s + 1) * FALLBACK_PER_STAGE]
        st = "foundation" if s == 0 else ("assessment" if s == total_stages - 1 else "practice")
        stages.append({"title": f"阶段 {s + 1}", "type": st, "chapter_indices": chunk})
    return {"stages": stages, "renamed_chapters": {}}


# ══════════════════════════════════════════
# Phase 7：多文档融合（课程工厂核心）
# ══════════════════════════════════════════

async def _get_blueprint_updated_at(space_id: str) -> str:
    """获取 blueprint 最后更新时间（锁获取前调用，避免被锁的 updated_at=NOW() 覆盖）。"""
    from sqlalchemy import text as _text
    SF = _make_session()
    async with SF() as session:
        row = await session.execute(
            _text("SELECT updated_at FROM skill_blueprints WHERE space_id = CAST(:sid AS uuid) ORDER BY updated_at DESC LIMIT 1"),
            {"sid": space_id}
        )
        r = row.fetchone()
        return r.updated_at.isoformat() if r else "1970-01-01T00:00:00+00:00"


async def _diff_new_entities(space_id: str, blueprint_id: str, session, since_timestamp: str = None) -> dict:
    """
    7.1 实体差异分析：用 embedding 余弦相似度比对新增实体与已有章节实体。

    分类逻辑：
    - already_covered: 余弦相似度 > 0.92 → 已有章节已覆盖，跳过
    - supplement:      0.75 ~ 0.92 → 追加到对应章节
    - new_topic:       < 0.75 且无匹配章节 → 后续生成新章节
    - conflict:        > 0.85 但定义文本有明显矛盾 → 暂跳过（人工审核）
    """
    import numpy as np
    from sqlalchemy import text as _txt

    # 1. 使用传入的 since_timestamp，否则从 blueprint 查询
    if since_timestamp is None:
        bp_row = await session.execute(
            _txt("SELECT updated_at FROM skill_blueprints WHERE blueprint_id = CAST(:bid AS uuid)"),
            {"bid": blueprint_id},
        )
        bp = bp_row.fetchone()
        if not bp:
            return {"already_covered": [], "supplement": [], "new_topic": [], "conflict": []}
        since_timestamp = bp.updated_at
    else:
        # 字符串 → datetime 转换，确保 SQL 参数类型正确
        from datetime import datetime as _dt
        since_timestamp = _dt.fromisoformat(since_timestamp)

    # 2. 取已有章节关联的实体（含 embedding）
    existing_rows = await session.execute(
        _txt("""
            SELECT DISTINCT ke.entity_id::text, ke.canonical_name,
                   ke.short_definition, ke.embedding::text
            FROM chapter_entity_links cel
            JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id
            WHERE ke.embedding IS NOT NULL
              AND cel.chapter_id IN (
                  SELECT chapter_id FROM skill_chapters
                  WHERE blueprint_id = CAST(:bid AS uuid)
              )
        """),
        {"bid": blueprint_id},
    )
    existing_entities = [dict(r._mapping) for r in existing_rows.fetchall()]

    # 3. 取新增的已审核实体（created_at > since，排除已链接到章节的实体）
    new_rows = await session.execute(
        _txt("""
            SELECT ke.entity_id::text, ke.canonical_name,
                   ke.short_definition, ke.embedding::text
            FROM knowledge_entities ke
            WHERE ke.space_id = CAST(:sid AS uuid)
              AND ke.review_status = 'approved'
              AND ke.embedding IS NOT NULL
              AND ke.created_at > :since
              AND ke.entity_id NOT IN (
                  SELECT cel.entity_id FROM chapter_entity_links cel
                  JOIN skill_chapters sc ON sc.chapter_id = cel.chapter_id
                  WHERE sc.blueprint_id = CAST(:bid AS uuid)
              )
        """),
        {"sid": space_id, "since": since_timestamp, "bid": blueprint_id},
    )
    new_entities = [dict(r._mapping) for r in new_rows.fetchall()]

    if not new_entities:
        logger.info("[merge] No new entities since last blueprint update",
                    blueprint_id=blueprint_id)
        return {"already_covered": [], "supplement": [], "new_topic": [], "conflict": []}

    logger.info("[merge] Diffing entities",
                existing=len(existing_entities), new=len(new_entities))

    # 4. 解析 embedding 并计算余弦相似度
    def _parse_embedding(emb_str: str) -> np.ndarray:
        return np.array([float(x) for x in emb_str.strip("[]").split(",")])

    existing_vecs = [_parse_embedding(e["embedding"]) for e in existing_entities] if existing_entities else []

    SIMILARITY_HIGH = 0.92
    SIMILARITY_MEDIUM = 0.75

    already_covered: list[dict] = []
    supplement: list[dict] = []
    new_topic: list[dict] = []
    conflict: list[dict] = []

    for new_ent in new_entities:
        new_vec = _parse_embedding(new_ent["embedding"])

        if not existing_vecs:
            new_topic.append(new_ent)
            continue

        # 计算与所有已有实体的最大余弦相似度
        max_sim = 0.0
        best_match = None
        for i, ev in enumerate(existing_vecs):
            sim = float(np.dot(new_vec, ev) / (np.linalg.norm(new_vec) * np.linalg.norm(ev) + 1e-10))
            if sim > max_sim:
                max_sim = sim
                best_match = existing_entities[i]

        if max_sim > SIMILARITY_HIGH:
            already_covered.append({
                **new_ent, "similarity": round(max_sim, 4),
                "matched_to": best_match["canonical_name"] if best_match else "",
            })
        elif max_sim > SIMILARITY_MEDIUM:
            supplement.append({
                **new_ent, "similarity": round(max_sim, 4),
                "matched_to": best_match["canonical_name"] if best_match else "",
            })
        else:
            new_topic.append({**new_ent, "similarity": round(max_sim, 4)})

    logger.info("[merge] Entity diff complete",
                already_covered=len(already_covered),
                supplement=len(supplement),
                new_topic=len(new_topic),
                conflict=len(conflict))

    return {
        "already_covered": already_covered,
        "supplement": supplement,
        "new_topic": new_topic,
        "conflict": conflict,
    }


async def _enhance_existing_chapters(
    repo, llm, supplement_entities: list[dict], blueprint_id: str, session
) -> int:
    """
    7.2 章节增量增强：为每个 supplement 实体找到最相似的已有章节，
    用 LLM 生成补充段落追加到 full_content 末尾。不删除、不替换原内容。
    """
    import numpy as np
    from sqlalchemy import text as _txt

    if not supplement_entities:
        return 0

    # 1. 取所有章节及其关联实体 embedding
    chapters_rows = await session.execute(
        _txt("""
            SELECT sc.chapter_id::text, sc.title, sc.content_text, sc.chapter_order
            FROM skill_chapters sc
            WHERE sc.blueprint_id = CAST(:bid AS uuid)
            ORDER BY sc.chapter_order
        """),
        {"bid": blueprint_id},
    )
    chapters = [dict(r._mapping) for r in chapters_rows.fetchall()]
    if not chapters:
        return 0

    # 取每个章节关联的实体 embedding
    chapter_entities_map: dict[str, list[dict]] = {}
    for ch in chapters:
        ents = await session.execute(
            _txt("""
                SELECT ke.entity_id::text, ke.canonical_name, ke.embedding::text
                FROM chapter_entity_links cel
                JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id
                WHERE cel.chapter_id = CAST(:cid AS uuid) AND ke.embedding IS NOT NULL
            """),
            {"cid": ch["chapter_id"]},
        )
        chapter_entities_map[ch["chapter_id"]] = [dict(r._mapping) for r in ents.fetchall()]

    def _parse_emb(emb_str: str) -> np.ndarray:
        return np.array([float(x) for x in emb_str.strip("[]").split(",")])

    enhanced_count = 0

    for supp_ent in supplement_entities:
        supp_vec = _parse_emb(supp_ent["embedding"])

        # 找到最相似的已有章节
        best_chapter_id = None
        best_sim = 0.0
        for ch_id, ch_ents in chapter_entities_map.items():
            for ce in ch_ents:
                ce_vec = _parse_emb(ce["embedding"])
                sim = float(np.dot(supp_vec, ce_vec) / (np.linalg.norm(supp_vec) * np.linalg.norm(ce_vec) + 1e-10))
                if sim > best_sim:
                    best_sim = sim
                    best_chapter_id = ch_id

        if not best_chapter_id:
            logger.warning("[merge] No matching chapter for supplement entity",
                          entity=supp_ent["canonical_name"])
            continue

        target_ch = next((c for c in chapters if c["chapter_id"] == best_chapter_id), None)
        if not target_ch:
            continue

        # 解析已有内容
        try:
            existing_content = json.loads(target_ch["content_text"] or "{}")
        except json.JSONDecodeError:
            existing_content = {"full_content": target_ch["content_text"] or ""}

        # 用 LLM 生成补充段落
        enhancement_prompt = (
            f"你是课程内容编辑。以下是一个已有章节的内容摘要，以及一段新的补充资料。\n\n"
            f"已有章节标题：{target_ch['title']}\n"
            f"新知识点名称：{supp_ent['canonical_name']}\n"
            f"新知识点定义：{supp_ent.get('short_definition', '')}\n\n"
            f"请生成一段 100-200 字的\"补充说明\"段落，以【补充说明】（来源：新资料）开头，"
            f"对 {supp_ent['canonical_name']} 提供新的解释视角或补充示例。"
            f"如果涉及代码，使用三个反引号围栏包裹。\n\n"
            f"只输出补充说明段落，不含其他内容。"
        )

        try:
            enhancement = await asyncio.wait_for(
                llm.generate(enhancement_prompt, model_route="tutorial_content"),
                timeout=60,
            )
        except Exception as e:
            logger.warning("[merge] Enhancement generation failed",
                          entity=supp_ent["canonical_name"], error=str(e))
            continue

        if not enhancement or not enhancement.strip():
            continue

        # 追加到 full_content 末尾
        fc = existing_content.get("full_content", "") or ""
        existing_content["full_content"] = fc + "\n\n" + enhancement.strip()

        # 更新章节内容
        await repo.update_chapter_content(
            best_chapter_id,
            json.dumps(existing_content, ensure_ascii=False),
        )

        # 链接新实体到章节
        await repo.link_entity_to_chapter(best_chapter_id, supp_ent["entity_id"], "supplement")

        enhanced_count += 1
        logger.info("[merge] Chapter enhanced",
                    chapter=target_ch["title"],
                    entity=supp_ent["canonical_name"],
                    similarity=round(best_sim, 4))

    return enhanced_count


async def _insert_new_chapters(
    repo, llm, new_topic_entities: list[dict], blueprint_id: str, session, instruction_block: str = ""
) -> int:
    """
    7.3 新章节插入：对新主题实体聚类（≥3 个形成主题），生成新章节，
    插入到已有课程中最相似的阶段末尾。更新 chapter_order。
    """
    import numpy as np
    from sqlalchemy import text as _txt

    if len(new_topic_entities) < 3:
        logger.info("[merge] Too few new_topic entities for new chapters",
                   count=len(new_topic_entities))
        return 0

    def _parse_emb(emb_str: str) -> np.ndarray:
        return np.array([float(x) for x in emb_str.strip("[]").split(",")])

    # 1. 简单聚类：将 pairwise 相似度 > 0.7 的实体分为一组
    entity_groups: list[list[dict]] = []
    used: set[int] = set()
    for i, ent in enumerate(new_topic_entities):
        if i in used:
            continue
        group = [ent]
        used.add(i)
        vi = _parse_emb(ent["embedding"])
        for j, other in enumerate(new_topic_entities):
            if j in used:
                continue
            vj = _parse_emb(other["embedding"])
            sim = float(np.dot(vi, vj) / (np.linalg.norm(vi) * np.linalg.norm(vj) + 1e-10))
            if sim > 0.7:
                group.append(other)
                used.add(j)
        if len(group) >= 3:
            entity_groups.append(group)
        else:
            logger.info("[merge] Small entity group skipped",
                       entities=[e["canonical_name"] for e in group])

    if not entity_groups:
        logger.info("[merge] No entity groups large enough for new chapters")
        return 0

    # 2. 取已有阶段列表（用于确定插入位置）
    stages_rows = await session.execute(
        _txt("""
            SELECT ss.stage_id::text, ss.title, ss.stage_order, ss.stage_type,
                   MAX(sc.chapter_order) AS max_chapter_order
            FROM skill_stages ss
            LEFT JOIN skill_chapters sc ON sc.stage_id = ss.stage_id
            WHERE ss.blueprint_id = CAST(:bid AS uuid)
            GROUP BY ss.stage_id, ss.title, ss.stage_order, ss.stage_type
            ORDER BY ss.stage_order
        """),
        {"bid": blueprint_id},
    )
    stages = [dict(r._mapping) for r in stages_rows.fetchall()]

    # 选择最后一个阶段作为插入目标
    if not stages:
        # 创建新阶段
        target_stage_id = await repo.create_stage(
            blueprint_id=blueprint_id,
            title="补充内容",
            description="新资料融入的补充章节",
            stage_order=1,
            stage_type="practice",
        )
        max_chapter_order = 0
    else:
        target_stage = stages[-1]
        target_stage_id = target_stage["stage_id"]
        max_chapter_order = target_stage["max_chapter_order"] or 0

    # 3. 为每组生成章节
    inserted_count = 0
    for group_idx, group in enumerate(entity_groups):
        entity_names = "、".join(e["canonical_name"] for e in group)
        definitions = "\n".join(
            f"- {e['canonical_name']}: {(e.get('short_definition') or '')[:100]}"
            for e in group
        )

        prompt = CHAPTER_CONTENT_PROMPT.format(
            chapter_title=f"补充：{group[0]['canonical_name']}及相关主题",
            objective=f"理解{entity_names}等知识点",
            task_description=f"学习以下补充知识点：\n{definitions}",
            teacher_instruction=instruction_block,
        )

        try:
            content = await asyncio.wait_for(
                llm.generate(prompt, model_route="tutorial_content"),
                timeout=150,
            )
            normalized = _normalize_chapter_content(content)
        except Exception as e:
            logger.warning("[merge] New chapter content generation failed",
                          entities=entity_names, error=str(e))
            continue

        # 尝试从生成内容中提取标题
        chapter_title = f"{group[0]['canonical_name']}及相关主题"
        try:
            content_data = json.loads(normalized)
            # 标题保留默认值，内容已标准化
        except json.JSONDecodeError:
            pass

        chapter_order = max_chapter_order + group_idx + 1
        chapter_id = await repo.create_chapter(
            stage_id=target_stage_id,
            blueprint_id=blueprint_id,
            title=chapter_title,
            objective=f"补充学习{', '.join(e['canonical_name'] for e in group[:3])}",
            task_description="阅读补充材料并完成相关练习",
            pass_criteria="理解新知识点并能应用到实际场景",
            common_mistakes="",
            chapter_order=chapter_order,
        )

        if normalized:
            await repo.update_chapter_content(chapter_id, normalized)

        for entity in group:
            await repo.link_entity_to_chapter(chapter_id, entity["entity_id"], "core_term")

        inserted_count += 1
        logger.info("[merge] New chapter inserted",
                    title=chapter_title, order=chapter_order, entity_count=len(group))

    return inserted_count


async def _synthesize_blueprint_merge_async(
    topic_key: str, space_id: str, existing_blueprint_id: str, prior_updated_at: str = None,
    teacher_instruction: str | None = None, type_instructions: dict | None = None
) -> None:
    """
    Phase 7 主流程：对已有 published 蓝图进行增量融合。

    流程：
    1. _diff_new_entities() — 实体差异分析
    2. _enhance_existing_chapters() — supplement 实体增强已有章节
    3. _insert_new_chapters() — new_topic 实体生成新章节
    4. 更新 blueprint version+1，状态回 published
    """
    from apps.api.core.llm_gateway import get_llm_gateway
    instruction_block = TEACHER_INSTRUCTION_PREFIX.format(instruction=teacher_instruction) if teacher_instruction else ""
    # 新增章节默认用 theory 模板（补充的新概念），增强已有章节用全局模板
    merge_new_instruction = ""
    if type_instructions and type_instructions.get("theory"):
        merge_new_instruction = TEACHER_INSTRUCTION_PREFIX.format(instruction=type_instructions["theory"])
    if not merge_new_instruction:
        merge_new_instruction = instruction_block
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository
    from sqlalchemy import text as _txt

    llm = get_llm_gateway()
    SF = _make_session()

    async with SF() as session:
        async with session.begin():
            repo = BlueprintRepository(session)

            # Step 1: 实体差异分析（使用锁获取前的时间戳，避免找不到新实体）
            diff = await _diff_new_entities(space_id, existing_blueprint_id, session, prior_updated_at)

            if not diff["supplement"] and not diff["new_topic"]:
                logger.info("[merge] No new entities to merge, restoring published status",
                           blueprint_id=existing_blueprint_id)
                await repo.update_blueprint_status(existing_blueprint_id, "published")
                return

            # Step 2: 增强已有章节
            enhanced = await _enhance_existing_chapters(
                repo, llm, diff["supplement"], existing_blueprint_id, session
            )

            # Step 3: 插入新章节
            inserted = await _insert_new_chapters(
                repo, llm, diff["new_topic"], existing_blueprint_id, session, merge_new_instruction
            )

            # Step 4: 更新 blueprint 状态和版本
            await session.execute(
                _txt("""
                    UPDATE skill_blueprints
                    SET status = 'published',
                        version = version + 1,
                        updated_at = now()
                    WHERE blueprint_id = CAST(:bid AS uuid)
                """),
                {"bid": existing_blueprint_id},
            )

            # 推进空间所有 reviewed 文档至 published
            await session.execute(
                _txt("""
                    UPDATE documents
                    SET document_status = 'published', updated_at = now()
                    WHERE space_id = CAST(:sid AS uuid)
                      AND document_status = 'reviewed'
                """),
                {"sid": space_id},
            )

            new_chapter_titles = []
            logger.info("[merge] Blueprint merge complete",
                       blueprint_id=existing_blueprint_id,
                       enhanced_chapters=enhanced,
                       new_chapters=inserted,
                       already_covered=len(diff["already_covered"]))

    # 重映射历史进度（新增章节对已有用户）
    if inserted > 0:
        try:
            async with _make_session()() as remap_session:
                async with remap_session.begin():
                    await _remap_progress_after_regenerate(
                        remap_session, existing_blueprint_id, topic_key
                    )
        except Exception as e:
            logger.warning("[merge] Progress remap failed", error=str(e))

    # 发送课程更新通知
    try:
        from apps.api.core.events import get_event_bus
        event_bus = get_event_bus()
        if event_bus._connection is None or event_bus._connection.is_closed:
            await event_bus.connect()
        await event_bus.publish("blueprint_merged", {
            "blueprint_id": existing_blueprint_id,
            "space_id": space_id,
            "enhanced_chapters": enhanced,
            "new_chapters": inserted,
            "topic_key": topic_key,
        })
        logger.info("[merge] blueprint_merged event published",
                   blueprint_id=existing_blueprint_id)
    except Exception as e:
        logger.warning("[merge] blueprint_merged event publish failed", error=str(e))

    # 为新章节预生成测验题
    if inserted > 0:
        try:
            pregen_chapter_quizzes.apply_async(
                args=[existing_blueprint_id], queue="knowledge", countdown=10
            )
            logger.info("[merge] quiz_pregen triggered", blueprint_id=existing_blueprint_id)
        except Exception as e:
            logger.warning("[merge] quiz_pregen trigger failed", error=str(e))


# ══════════════════════════════════════════
# Celery 任务入口（V2: feature flag 切换）
# ══════════════════════════════════════════

@celery_app.task(bind=True, max_retries=2, default_retry_delay=60,
               on_failure=task_tracker.on_failure, on_success=task_tracker.on_success)
def synthesize_blueprint(self, topic_key: str, space_id, teacher_instruction: str | None = None,
                         type_instructions: dict | None = None):
    """type_instructions: {"theory": "...", "task": "...", "project": "..."} 按课型分别指定模板内容"""
    logger.info("synthesize_blueprint start", topic_key=topic_key, has_instruction=bool(teacher_instruction))

    # Phase 7: 优先检查是否已有 published 蓝图 → 走 merge 模式
    if space_id:
        try:
            existing_bp_id = asyncio.run(_has_published_blueprint(str(space_id)))
            if existing_bp_id:
                # 已有 published 蓝图 → 先保存旧 updated_at 再获取 merge 锁
                prior_updated_at = asyncio.run(
                    _get_blueprint_updated_at(str(space_id))
                )
                should_run = asyncio.run(
                    _check_blueprint_lock(str(space_id), topic_key, mode="merge")
                )
                if not should_run:
                    logger.warning(
                        "synthesize_blueprint: merge in progress, skipping",
                        topic_key=topic_key, space_id=space_id,
                    )
                    return
                # 运行 merge 流程
                import apps.api.core.llm_gateway as _gw_mod_merge
                _gw_mod_merge._llm_gateway = None
                try:
                    asyncio.run(_synthesize_blueprint_merge_async(
                        topic_key, str(space_id), existing_bp_id, prior_updated_at,
                        teacher_instruction, type_instructions
                    ))
                except Exception as exc:
                    logger.error("synthesize_blueprint merge failed",
                               error=str(exc), topic_key=topic_key)
                    raise self.retry(exc=exc)
                return

            # 无 published 蓝图 → 走 full 模式锁（原行为）
            should_run = asyncio.run(_check_blueprint_lock(str(space_id), topic_key))
            if not should_run:
                logger.warning(
                    "synthesize_blueprint: duplicate in progress, skipping",
                    topic_key=topic_key, space_id=space_id,
                )
                return
        except Exception as _lock_err:
            # 锁检查失败不阻断任务，记录后继续
            logger.warning("synthesize_blueprint: lock check failed, proceeding",
                           error=str(_lock_err))

    # FIX(gwloop): 每次 task 重置 LLMGateway 单例，避免 asyncio.Lock / 连接池绑旧 loop
    import apps.api.core.llm_gateway as _gw_mod
    _gw_mod._llm_gateway = None
    try:
        asyncio.run(_synthesize_blueprint_v2_async(topic_key, space_id, teacher_instruction, type_instructions))
    except Exception as exc:
        logger.error("synthesize_blueprint failed", error=str(exc), topic_key=topic_key)
        raise self.retry(exc=exc)

def on_failure(self, exc, task_id, args, kwargs, einfo):
    """所有 retry 耗尽后将 blueprint 标记为 failed，管理员可在后台看到并手动重触发。"""
    try:
        topic_key = args[0] if args else "unknown"
        space_id  = str(args[1]) if len(args) > 1 and args[1] else None
        if space_id:
            asyncio.run(_mark_blueprint_failed(space_id, topic_key, str(exc)))
            logger.error(
                "synthesize_blueprint: all retries exhausted, marked as failed",
                topic_key=topic_key, space_id=space_id, error=str(exc),
            )
    except Exception as _fe:
        logger.error("synthesize_blueprint: on_failure hook error", error=str(_fe))


# ══════════════════════════════════════════
# 共用工具函数
# ══════════════════════════════════════════


# ══════════════════════════════════════════
# blueprint 幂等锁 / 失败标记（blueprint_lock_check_v1）
# ══════════════════════════════════════════

async def _check_blueprint_lock(space_id: str, topic_key: str, mode: str = "full") -> bool:
    """
    原子性声明生成锁，彻底消除竞态条件。

    旧方案（blueprint_lock_check_v1）是先 SELECT 检查，再在写入阶段才 INSERT：
    7 个任务同时 SELECT 时全看到"无 generating 记录"，全部冲进来。

    新方案（blueprint_lock_fix_v2）：任务开始即原子 UPSERT 声明锁：
    - 全新 space → INSERT 成功，返回 blueprint_id → 获锁 → 继续
    - 已有 published/failed/超时 → UPDATE SET generating → 返回行 → 获锁 → 继续
    - 已有 generating 且 2h 内 → WHERE 条件为 false → UPDATE 被跳过 → 无 RETURNING → 跳过

    mode="merge" 时放开 published 状态限制，允许对已发布蓝图进行增量融合。

    使用 ON CONFLICT DO UPDATE ... WHERE 保证原子性，无竞态。
    """
    from sqlalchemy import text as _text
    SF = _make_session()
    async with SF() as session:
        if mode == "merge":
            # merge 模式：允许 published 状态获取锁（只阻拦正在 generating 的任务）
            where_clause = """
                  WHERE skill_blueprints.status NOT IN ('generating')
                     OR (skill_blueprints.status = 'generating'
                         AND skill_blueprints.updated_at < now() - INTERVAL '2 hours')
            """
        else:
            # full 模式：阻拦 generating 和 published（原行为）
            where_clause = """
                  WHERE skill_blueprints.status NOT IN ('generating', 'published')
                     OR (skill_blueprints.status = 'generating'
                         AND skill_blueprints.updated_at < now() - INTERVAL '2 hours')
            """
        result = await session.execute(
            _text(f"""
                INSERT INTO skill_blueprints
                  (blueprint_id, topic_key, space_id, title, skill_goal, status)
                VALUES
                  (gen_random_uuid(), :tk, CAST(:sid AS uuid), :title, :goal, 'generating')
                ON CONFLICT (space_id, topic_key) DO UPDATE
                  SET status = 'generating',
                      updated_at = now()
                  {where_clause}
                RETURNING blueprint_id::text
            """),
            {"tk": topic_key, "sid": str(space_id), "title": topic_key, "goal": topic_key},
        )
        row = result.fetchone()
        await session.commit()
        # row is None → 已有另一任务持有锁 → 跳过
        return row is not None


async def _mark_blueprint_failed(space_id: str, topic_key: str, error_msg: str) -> None:
    """所有 retry 耗尽后，将 blueprint 标记为 failed 并记录错误摘要。"""
    from sqlalchemy import text as _text
    SF = _make_session()
    async with SF() as session:
        await session.execute(
            _text("""
                UPDATE skill_blueprints
                SET status = 'failed',
                    error_message = LEFT(:err, 500),
                    updated_at = now()
                WHERE space_id = CAST(:sid AS uuid)
                  AND topic_key = :tk
                  AND status = 'generating'
            """),
            {"sid": str(space_id), "tk": topic_key, "err": f"[生成失败] {error_msg}"},
        )
        await session.commit()


async def _has_published_blueprint(space_id: str) -> str | None:
    """检查空间是否已有已发布的蓝图，返回 blueprint_id 或 None。"""
    from sqlalchemy import text as _text
    SF = _make_session()
    async with SF() as session:
        row = await session.execute(
            _text("""
                SELECT blueprint_id::text FROM skill_blueprints
                WHERE space_id = CAST(:sid AS uuid)
                  AND status = 'published'
                ORDER BY version DESC LIMIT 1
            """),
            {"sid": str(space_id)},
        )
        r = row.fetchone()
        return r[0] if r else None


def _make_session():
    """每次调用都创建全新引擎+会话，彻底避免连接池状态污染。"""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy.pool import NullPool
    _db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(_db_url, poolclass=NullPool, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# -- PROGRESS_REMAP_INJECTED --
async def _remap_progress_after_regenerate(
    session, blueprint_id: str, topic_key: str
) -> None:
    """
    Blueprint 重新生成后，为已有学习记录的用户自动补标章节完成。
    判断标准：新章节的所有 core_term 实体，用户 mastery_score >= 0.6 则视为已掌握。
    """
    from sqlalchemy import text as _t
    import uuid as _uuid

    # 1. 找出曾学过本 blueprint（通过 chapter_progress.tutorial_id）的所有用户
    users_r = await session.execute(_t("""
        SELECT DISTINCT user_id::text
        FROM chapter_progress
        WHERE tutorial_id = :bid
    """), {"bid": blueprint_id})
    user_ids = [r[0] for r in users_r.fetchall()]

    if not user_ids:
        logger.info("[remap] No historical learners, skip", blueprint_id=blueprint_id)
        return

    logger.info("[remap] Remapping progress", blueprint_id=blueprint_id,
                topic_key=topic_key, user_count=len(user_ids))

    # 2. 取新章节及其 core_term 实体
    chapters_r = await session.execute(_t("""
        SELECT sc.chapter_id::text, sc.blueprint_id::text
        FROM skill_chapters sc
        WHERE sc.blueprint_id = CAST(:bid AS uuid)
    """), {"bid": blueprint_id})
    chapter_ids = [r[0] for r in chapters_r.fetchall()]

    if not chapter_ids:
        return

    # 取每个章节的 core_term 实体集合
    chapter_entities: dict[str, list[str]] = {}
    for cid in chapter_ids:
        ents_r = await session.execute(_t("""
            SELECT entity_id::text FROM chapter_entity_links
            WHERE chapter_id = CAST(:cid AS uuid)
              AND link_type = 'core_term'
        """), {"cid": cid})
        chapter_entities[cid] = [r[0] for r in ents_r.fetchall()]

    remapped = 0
    for uid in user_ids:
        # 3. 取该用户已掌握的实体集合（mastery >= 0.6）
        mastered_r = await session.execute(_t("""
            SELECT entity_id::text FROM learner_knowledge_states
            WHERE user_id = CAST(:uid AS uuid)
              AND mastery_score >= 0.6
        """), {"uid": uid})
        mastered = {r[0] for r in mastered_r.fetchall()}

        for cid, core_entities in chapter_entities.items():
            if not core_entities:
                continue
            # 全部 core_term 已掌握才补标完成
            if not all(eid in mastered for eid in core_entities):
                continue
            # 幂等插入 chapter_progress
            await session.execute(_t("""
                INSERT INTO chapter_progress
                  (id, user_id, tutorial_id, chapter_id,
                   completed, completed_at, duration_seconds, status)
                VALUES (
                  CAST(:id AS uuid),
                  CAST(:uid AS uuid),
                  :tid,
                  :chid,
                  true, NOW(), 0, 'read'
                )
                ON CONFLICT (user_id, tutorial_id, chapter_id) DO NOTHING
            """), {
                "id":   str(_uuid.uuid4()),
                "uid":  uid,
                "tid":  blueprint_id,
                "chid": cid,
            })
            remapped += 1

    logger.info("[remap] Done", blueprint_id=blueprint_id, remapped_chapters=remapped)



def _parse_json(raw: str):
    clean = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


# ══════════════════════════════════════════════════════════════════
# V2: 新逻辑（embedding 聚类 + 每簇命名 + 动态章节数）
# ══════════════════════════════════════════════════════════════════

async def _synthesize_blueprint_v2_async(topic_key: str, space_id, teacher_instruction: str | None = None,
                                          type_instructions: dict | None = None) -> None:
    """
    type_instructions: {"theory": "理论基础模板内容", "task": "实操导向模板内容", "project": "系统默认模板内容"}
    每种课型对应一个完整独立的模板。若不指定，三种课型共用 teacher_instruction。
    """
    import numpy as np
    from sklearn.cluster import KMeans
    from apps.api.core.llm_gateway import get_llm_gateway
    from apps.api.modules.skill_blueprint.repository import BlueprintRepository
    from sqlalchemy import text

    TARGET_PER_CHAPTER = 7
    MAX_CHAPTERS = 30          # 防止海量实体生成过多章节
    MAX_CONCURRENT_LLM = 5

    # Layer 1: 将教师指令格式化为 prompt 前缀块
    instruction_block = TEACHER_INSTRUCTION_PREFIX.format(instruction=teacher_instruction) if teacher_instruction else ""
    # 预构建分课型模板指令（type_instructions 可选）
    type_instruction_blocks: dict[str, str] = {}
    if type_instructions:
        for ct in ("theory", "task", "project"):
            content = type_instructions.get(ct, "")
            type_instruction_blocks[ct] = TEACHER_INSTRUCTION_PREFIX.format(instruction=content) if content else ""

    llm = get_llm_gateway()
    SessionFactory = _make_session()

    # ══════════════════════════════════════════
    # 第一段：读取数据 + 过滤 + 聚类（不持有长连接）
    # ══════════════════════════════════════════
    async with SessionFactory() as session:
        if not space_id:
            # 优先从已有蓝图记录取 space_id，降级再按 name 查
            row = await session.execute(
                text("SELECT space_id::text FROM skill_blueprints WHERE topic_key=:tk LIMIT 1"),
                {"tk": topic_key}
            )
            r = row.fetchone()
            if r and r[0]:
                space_id = r[0]
            else:
                row = await session.execute(
                    text("SELECT space_id::text FROM knowledge_spaces "
                         "WHERE name=:n ORDER BY CASE space_type WHEN 'global' THEN 0 ELSE 1 END, created_at ASC LIMIT 1"),
                    {"n": topic_key}
                )
                r = row.fetchone()
                space_id = r[0] if r else None

        if not space_id:
            logger.warning("[V2] No space found for topic", topic_key=topic_key)
            return

        ents = await session.execute(
            text("""SELECT entity_id::text, canonical_name, entity_type,
                           short_definition, embedding::text
                    FROM knowledge_entities
                    WHERE space_id = CAST(:sid AS uuid)
                      AND review_status = 'approved'
                      AND embedding IS NOT NULL
                    ORDER BY canonical_name"""),
            {"sid": space_id}
        )
        raw_entities = [dict(r._mapping) for r in ents.fetchall()]

    if not raw_entities:
        logger.warning("[V2] No approved entities with embeddings", topic_key=topic_key)
        return

    # 过滤非教学实体
    entities = []
    filtered_count = 0
    for e in raw_entities:
        if _is_non_teaching_entity(e["canonical_name"], e.get("short_definition", "")):
            filtered_count += 1
        else:
            entities.append(e)

    logger.info("[V2] Entity filtering done",
                total=len(raw_entities), kept=len(entities), filtered=filtered_count)

    if len(entities) < 4:
        logger.warning("[V2] Too few teaching entities after filtering", count=len(entities))
        return

    # 解析 embedding 向量并聚类
    embeddings = []
    for e in entities:
        vec = [float(x) for x in e["embedding"].strip("[]").split(",")]
        embeddings.append(vec)

    X = np.array(embeddings)
    K = max(4, round(len(X) / TARGET_PER_CHAPTER))
    K = min(K, MAX_CHAPTERS)   # 上限 30 章

    kmeans = KMeans(n_clusters=K, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X)

    clusters: dict[int, list[dict]] = defaultdict(list)
    for i, (entity, label) in enumerate(zip(entities, labels)):
        entity["_vec"] = embeddings[i]          # 附加向量供重平衡使用
        clusters[int(label)].append(entity)

    logger.info("[V2] Clustering done", K=K, entity_count=len(entities),
                cluster_sizes=sorted([len(v) for v in clusters.values()], reverse=True))

    # P3: 簇大小后处理（MIN=3 / MAX=12）
    clusters = _rebalance_clusters(clusters, MIN_SIZE=3, MAX_SIZE=12)

    # ══════════════════════════════════════════
    # 第二段：LLM 调用（不持有 DB 连接）
    # ══════════════════════════════════════════

    # Step B: 为每个簇命名
    async def _name_cluster(cluster_id: int, members: list[dict]) -> dict:
        ej = json.dumps(
            [{"name": m["canonical_name"],
              "definition": (m.get("short_definition") or "")[:100]}
             for m in members],
            ensure_ascii=False
        )
        raw = await asyncio.wait_for(
            llm.generate(
                CLUSTER_CHAPTER_PROMPT.format(entities_json=ej, teacher_instruction=instruction_block),
                model_route="knowledge_extraction"),
            timeout=90
        )
        meta = _parse_json(raw)
        if not meta or "title" not in meta:
            # 兜底：用第一个实体名做章节标题
            meta = {
                "title": f"理解{members[0]['canonical_name']}",
                "objective": "", "task_description": "",
                "pass_criteria": "", "common_mistakes": "",
            }
            logger.warning("[V2] Cluster naming fallback", cluster_id=cluster_id)
        return {"cluster_id": cluster_id, "entities": members, "meta": meta}

    cluster_chapters = []
    for cid, members in clusters.items():
        cluster_chapters.append(await _name_cluster(cid, members))
    logger.info("[V2] Cluster naming done", chapters=len(cluster_chapters))

    # Step C: LLM stage 规划（P1 难度排序 + P2 动词多样性）
    chapters_for_planning = [
        {
            "index": i,
            "title": c["meta"]["title"],
            "entities": [e["canonical_name"] for e in c["entities"][:5]],
        }
        for i, c in enumerate(cluster_chapters)
    ]
    stage_plan = await _plan_stages_with_llm(llm, chapters_for_planning, len(cluster_chapters), instruction_block)

    # 应用章节重命名（P2 动词多样性）
    for idx_str, new_title in (stage_plan.get("renamed_chapters") or {}).items():
        try:
            idx = int(idx_str)
            if 0 <= idx < len(cluster_chapters):
                cluster_chapters[idx]["meta"]["title"] = new_title
                logger.info("[V2] Chapter renamed", index=idx, new_title=new_title)
        except (ValueError, TypeError):
            pass

    # Step B2: 生成课程标题
    chapter_titles = [c["meta"]["title"] for c in cluster_chapters]
    try:
        title_raw = await asyncio.wait_for(
            llm.generate(
                COURSE_TITLE_PROMPT.format(
                    chapter_titles_json=json.dumps(chapter_titles, ensure_ascii=False),
                    teacher_instruction=instruction_block),
                model_route="knowledge_extraction"),
            timeout=60
        )
        title_data = _parse_json(title_raw) or {}
    except Exception:
        title_data = {}
    course_title = title_data.get("title", f"{topic_key} 技能课程")
    skill_goal = title_data.get("skill_goal", f"掌握 {topic_key} 核心技能")

    # Step E: 逐章生成内容（用 cluster_id 做 key，避免同名标题覆盖）
    chapter_contents: dict[int, str] = {}

    async def _gen_content(ch: dict):
        meta = ch["meta"]
        entity_names = "、".join(e["canonical_name"] for e in ch["entities"])

        # 根据 LLM 判定的课型选择对应模板：theory→理论基础, task→实操导向, project→系统默认
        chapter_type = meta.get("chapter_type", "task")
        selected_instruction = type_instruction_blocks.get(chapter_type) or instruction_block

        prompt = CHAPTER_CONTENT_PROMPT.format(
            chapter_title=meta.get("title", ""),
            objective=meta.get("objective", "") + f"\n涉及知识点：{entity_names}",
            task_description=meta.get("task_description", ""),
            teacher_instruction=selected_instruction,
        )
        try:
            content = await asyncio.wait_for(
                llm.generate(prompt, model_route="tutorial_content"),
                timeout=150
            )
            chapter_contents[ch["cluster_id"]] = _normalize_chapter_content(content)
            logger.info("[V2] Chapter content generated",
                        title=meta["title"], chapter_type=chapter_type)
        except Exception as e:
            logger.warning("[V2] Chapter content failed",
                           title=meta["title"], error=str(e))
            chapter_contents[ch["cluster_id"]] = ""

    for ch in cluster_chapters:
        await _gen_content(ch)
    logger.info("[V2] Content generation done", total=len(chapter_contents))

    # ══════════════════════════════════════════
    # 第三段：一次性写入（按 LLM stage plan 顺序）
    # ══════════════════════════════════════════
    SessionFactory2 = _make_session()
    async with SessionFactory2() as session:
        async with session.begin():
            repo = BlueprintRepository(session)

            blueprint_id = await repo.create_blueprint(
                topic_key=topic_key,
                title=course_title,
                skill_goal=skill_goal,
                space_id=space_id,
            )
            logger.info("[V2] Blueprint record created", blueprint_id=blueprint_id)

            # Layer 1: 持久化教师指令到蓝图
            if teacher_instruction:
                await repo.set_teacher_instruction(blueprint_id, teacher_instruction)

            # 清空旧数据
            await session.execute(
                text("DELETE FROM skill_stages WHERE blueprint_id = CAST(:bid AS uuid)"),
                {"bid": blueprint_id}
            )

            chapter_idx = 0
            stages_from_plan = stage_plan.get("stages", [])

            for stage_order, stage_data in enumerate(stages_from_plan, start=1):
                chapter_indices = stage_data.get("chapter_indices", [])
                if not chapter_indices:
                    continue

                stage_id = await repo.create_stage(
                    blueprint_id=blueprint_id,
                    title=stage_data.get("title", f"阶段 {stage_order}"),
                    description=None,
                    stage_order=stage_order,
                    stage_type=stage_data.get("type", "practice"),
                )

                for ch_idx in chapter_indices:
                    ch = cluster_chapters[ch_idx]
                    meta = ch["meta"]
                    chapter_idx += 1
                    chapter_id = await repo.create_chapter(
                        stage_id=stage_id,
                        blueprint_id=blueprint_id,
                        title=meta.get("title", f"章节{chapter_idx}"),
                        objective=meta.get("objective"),
                        task_description=meta.get("task_description"),
                        pass_criteria=meta.get("pass_criteria"),
                        common_mistakes=meta.get("common_mistakes"),
                        chapter_order=chapter_idx,
                    )

                    # 写入内容
                    ct = chapter_contents.get(ch["cluster_id"], "")
                    if ct:
                        await repo.update_chapter_content(chapter_id, ct)

                    # 链接本簇实体（真实语义关联）
                    for entity in ch["entities"]:
                        await repo.link_entity_to_chapter(
                            chapter_id, entity["entity_id"], "core_term")

                logger.info("[V2] Stage written",
                            order=stage_order, title=stage_data.get("title"),
                            chapters=len(chapter_indices))

            # 防御：全部章节内容为空时标记失败，不发布假课程
            filled = sum(1 for ct in chapter_contents.values() if ct and ct.strip())
            if filled == 0:
                logger.error("[V2] All chapter contents empty, marking failed",
                            topic_key=topic_key, blueprint_id=blueprint_id)
                await repo.update_blueprint_status(blueprint_id, "failed")
                await session.execute(
                    text("UPDATE skill_blueprints SET error_message=:err, updated_at=now() "
                         "WHERE blueprint_id=CAST(:bid AS uuid)"),
                    {"err": "[生成失败] 所有章节内容生成失败，请检查 tutorial_content 模型可用性", "bid": blueprint_id}
                )
            else:
                await repo.update_blueprint_status(blueprint_id, "published")
                # 推进空间所有 reviewed 文档至 published
                await repo.db.execute(
                    text("UPDATE documents SET document_status = 'published', updated_at = now() "
                         "WHERE space_id = CAST(:sid AS uuid) AND document_status = 'reviewed'"),
                    {"sid": space_id}
                )
                logger.info("[V2] Blueprint synthesis complete",
                        topic_key=topic_key, blueprint_id=blueprint_id,
                        total_chapters=len(cluster_chapters), filled_chapters=filled)


# ══════════════════════════════════════════
# Quiz 预生成任务（quiz_pregen_v1）
# blueprint 发布后异步为所有章节预生成题目
# ══════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="apps.api.tasks.blueprint_tasks.pregen_chapter_quizzes",
    max_retries=2,
    on_failure=task_tracker.on_failure,
    on_success=task_tracker.on_success,
)
def pregen_chapter_quizzes(self, blueprint_id: str) -> None:
    # quiz_pregen_v1
    try:
        asyncio.run(_pregen_quizzes_async(blueprint_id))
    except Exception as exc:
        logger.error("pregen_chapter_quizzes failed", blueprint_id=blueprint_id, error=str(exc))


async def _pregen_quizzes_async(blueprint_id: str) -> None:
    from apps.api.core.llm_gateway import get_llm_gateway
    from sqlalchemy import text

    SessionFactory = _make_session()
    llm = get_llm_gateway()

    async with SessionFactory() as session:
        # 取所有章节
        rows = await session.execute(
            text("""
                SELECT sc.chapter_id::text
                FROM skill_chapters sc
                WHERE sc.blueprint_id = CAST(:bid AS uuid)
                ORDER BY sc.chapter_order
            """),
            {"bid": blueprint_id}
        )
        chapter_ids = [r[0] for r in rows.fetchall()]

    logger.info("[quiz_pregen] start", blueprint_id=blueprint_id, chapters=len(chapter_ids))

    for cid in chapter_ids:
        try:
            await _pregen_one_chapter(session_factory=_make_session, llm=llm, chapter_id=cid)
        except Exception as e:
            logger.warning("[quiz_pregen] chapter failed", chapter_id=cid, error=str(e))

    logger.info("[quiz_pregen] done", blueprint_id=blueprint_id)


async def _pregen_one_chapter(session_factory, llm, chapter_id: str) -> None:
    from sqlalchemy import text
    import json, re as _re

    async with session_factory()() as session:
        # 已有缓存则跳过
        cached = await session.execute(
            text("SELECT 1 FROM chapter_quizzes WHERE chapter_id = :cid"),
            {"cid": chapter_id}
        )
        if cached.fetchone():
            return

        # 取关联知识点
        ents = await session.execute(
            text("""
                SELECT ke.entity_id::text, ke.canonical_name, ke.short_definition
                FROM chapter_entity_links cel
                JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id
                WHERE cel.chapter_id = CAST(:cid AS uuid)
                  AND ke.review_status = 'approved'
            """),
            {"cid": chapter_id}
        )
        entities = [dict(r._mapping) for r in ents.fetchall()]
        if not entities:
            return

        entities_json = json.dumps(
            [{"entity_id": e["entity_id"],
              "name": e["canonical_name"],
              "definition": (e.get("short_definition") or "")[:100]}
             for e in entities],
            ensure_ascii=False
        )

        # 取 QUIZ_GENERATION_PROMPT（从 routers.py 复用同一 prompt）
        from apps.api.modules.routers import QUIZ_GENERATION_PROMPT
        count = len(entities)
        raw = await asyncio.wait_for(
            llm.generate(
                QUIZ_GENERATION_PROMPT.format(count=count, entities_json=entities_json),
                model_route="quiz_generation"
            ),
            timeout=90
        )

        clean = _re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        match = _re.search(r"\[.*\]", clean, _re.DOTALL)
        questions = []
        if match:
            try:
                questions = json.loads(match.group())
            except Exception:
                pass

        if not questions:
            return

        await session.execute(
            text("""
                INSERT INTO chapter_quizzes (chapter_id, questions, question_count)
                VALUES (:cid, CAST(:q AS jsonb), :cnt)
                ON CONFLICT (chapter_id) DO NOTHING
            """),
            {"cid": chapter_id,
             "q": json.dumps(questions, ensure_ascii=False),
             "cnt": len(questions)}
        )
        await session.commit()
        logger.info("[quiz_pregen] chapter done", chapter_id=chapter_id, count=len(questions))


# ══════════════════════════════════════════
# 全量章节内容重生成任务（admin 课程管理触发）
# ══════════════════════════════════════════

@celery_app.task(bind=True, max_retries=1, default_retry_delay=60,
               on_failure=task_tracker.on_failure, on_success=task_tracker.on_success)
def regenerate_all_chapters(self, blueprint_id: str):
    """对一个 blueprint 下所有章节批量重新生成内容，顺序执行避免打爆限速。"""
    import apps.api.core.llm_gateway as _gw_mod
    _gw_mod._llm_gateway = None
    logger.info("[regen_all] start", blueprint_id=blueprint_id)
    try:
        asyncio.run(_regenerate_all_chapters_async(blueprint_id))
    except Exception as exc:
        logger.error("[regen_all] failed", blueprint_id=blueprint_id, error=str(exc))
        raise self.retry(exc=exc)


async def _regenerate_all_chapters_async(blueprint_id: str) -> None:
    from apps.api.core.llm_gateway import get_llm_gateway
    SF = _make_session()

    # 查所有 stage → chapter
    async with SF() as session:
        stages_result = await session.execute(
            text("SELECT stage_id::text FROM skill_stages WHERE blueprint_id=CAST(:bid AS uuid) ORDER BY stage_order"),
            {"bid": blueprint_id}
        )
        stage_ids = [r[0] for r in stages_result.fetchall()]

        chapters = []
        for sid in stage_ids:
            ch_result = await session.execute(
                text("SELECT chapter_id::text, title, objective, task_description FROM skill_chapters WHERE stage_id=CAST(:sid AS uuid) ORDER BY chapter_order"),
                {"sid": sid}
            )
            chapters.extend([dict(r._mapping) for r in ch_result.fetchall()])

    logger.info("[regen_all] chapters to process", total=len(chapters), blueprint_id=blueprint_id)
    llm = get_llm_gateway()

    for idx, ch in enumerate(chapters, start=1):
        chapter_id = ch["chapter_id"]
        try:
            prompt = CHAPTER_CONTENT_PROMPT.format(
                chapter_title=ch["title"] or "",
                objective=ch["objective"] or "",
                task_description=ch["task_description"] or "",
            )
            content = await asyncio.wait_for(
                llm.generate(prompt, model_route="tutorial_content"),
                timeout=150
            )
            async with SF() as session:
                async with session.begin():
                    normalized_ct = _normalize_chapter_content(content)
                    fields = _extract_chapter_fields(normalized_ct)
                    await session.execute(
                        text("""UPDATE skill_chapters SET
                                 content_text=:ct, status='approved',
                                 scene_hook=:sh, code_example=:ce,
                                 misconception_block=:mb, skim_summary=:ss,
                                 prereq_adaptive=:pa, updated_at=now()
                               WHERE chapter_id=CAST(:cid AS uuid)"""),
                        {
                            "ct": normalized_ct, "cid": chapter_id,
                            "sh": fields.get("scene_hook"),
                            "ce": fields.get("code_example"),
                            "mb": fields.get("misconception_block"),
                            "ss": fields.get("skim_summary"),
                            "pa": fields.get("prereq_adaptive"),
                        }
                    )
            logger.info("[regen_all] chapter done", idx=idx, total=len(chapters), title=ch["title"])
        except Exception as e:
            logger.warning("[regen_all] chapter failed", chapter_id=chapter_id, title=ch["title"], error=str(e))

    logger.info("[regen_all] all done", blueprint_id=blueprint_id, total=len(chapters))


# ══════════════════════════════════════════
# Layer 3: 附属内容联动 — 单章测验 + 讨论种子
# ══════════════════════════════════════════

@celery_app.task(bind=True, max_retries=2, default_retry_delay=60,
                 on_failure=task_tracker.on_failure, on_success=task_tracker.on_success)
def regenerate_chapter_quiz(self, chapter_id: str):
    """Layer 3: 单章测验异步重新生成（章节精调后触发）。"""
    import apps.api.core.llm_gateway as _gw_mod
    _gw_mod._llm_gateway = None
    logger.info("[quiz_regen] start", chapter_id=chapter_id)
    try:
        asyncio.run(_regenerate_single_quiz_async(chapter_id))
    except Exception as exc:
        logger.error("[quiz_regen] failed", chapter_id=chapter_id, error=str(exc))
        raise self.retry(exc=exc)


async def _regenerate_single_quiz_async(chapter_id: str) -> None:
    """单章测验重新生成：读取关联知识点 → 调用 QUIZ_GENERATION_PROMPT → 写入 chapter_quizzes。"""
    from apps.api.core.llm_gateway import get_llm_gateway
    from sqlalchemy import text as _text
    import json as _json
    import apps.api.modules.routers as _routers_mod  # for QUIZ_GENERATION_PROMPT

    llm = get_llm_gateway()
    SF = _make_session()

    async with SF() as session:
        # 读取章节关联的知识点
        entities_rows = await session.execute(_text("""
            SELECT ke.entity_id::text, ke.canonical_name,
                   COALESCE(ke.short_definition, '') AS short_definition
            FROM chapter_entity_links cel
            JOIN knowledge_entities ke ON ke.entity_id = cel.entity_id
            WHERE cel.chapter_id = CAST(:cid AS uuid)
              AND ke.review_status = 'approved'
        """), {"cid": chapter_id})
        entities = [dict(r._mapping) for r in entities_rows.fetchall()]

        if not entities:
            logger.warning("[quiz_regen] no entities for chapter", chapter_id=chapter_id)
            return

        # 复用 QUIZ_GENERATION_PROMPT
        count = min(len(entities) + 2, 10)
        entities_json = _json.dumps(
            [{"entity_id": e["entity_id"], "name": e["canonical_name"],
              "definition": (e["short_definition"] or "")[:200]} for e in entities],
            ensure_ascii=False
        )
        prompt = _routers_mod.QUIZ_GENERATION_PROMPT.format(
            count=count, entities_json=entities_json
        )
        raw = await asyncio.wait_for(
            llm.generate(prompt, model_route="quiz_generation"),
            timeout=120
        )
        questions = _json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(questions, dict):
            questions = list(questions.values()) if "questions" in questions else [questions]

        # 写入 chapter_quizzes（覆盖旧数据）
        await session.execute(_text("""
            DELETE FROM chapter_quizzes WHERE chapter_id = CAST(:cid AS uuid)
        """), {"cid": chapter_id})
        await session.execute(_text("""
            INSERT INTO chapter_quizzes (chapter_id, questions, question_count, generated_at)
            VALUES (CAST(:cid AS uuid), :qjson::jsonb, :cnt, now())
        """), {
            "cid": chapter_id,
            "qjson": _json.dumps(questions, ensure_ascii=False),
            "cnt": len(questions),
        })
        await session.commit()
        logger.info("[quiz_regen] done", chapter_id=chapter_id, count=len(questions))


@celery_app.task(bind=True, max_retries=1, default_retry_delay=60)
def generate_discussion_seeds(self, chapter_id: str, space_id: str, user_id: str):
    """Layer 3: 基于章节内容自动生成讨论种子帖。"""
    import apps.api.core.llm_gateway as _gw_mod
    _gw_mod._llm_gateway = None
    logger.info("[discussion_seed] start", chapter_id=chapter_id, space_id=space_id)
    try:
        asyncio.run(_generate_discussion_seeds_async(chapter_id, space_id, user_id))
    except Exception as exc:
        logger.error("[discussion_seed] failed", chapter_id=chapter_id, error=str(exc))


async def _generate_discussion_seeds_async(chapter_id: str, space_id: str, user_id: str) -> None:
    """读取章节内容 → 调用 DISCUSSION_SEED_PROMPT → 写入 course_posts。"""
    from apps.api.core.llm_gateway import get_llm_gateway
    from sqlalchemy import text as _text
    import json as _json
    import uuid as _uuid

    llm = get_llm_gateway()
    SF = _make_session()

    async with SF() as session:
        row = (await session.execute(_text("""
            SELECT title, content_text FROM skill_chapters
            WHERE chapter_id = CAST(:cid AS uuid)
        """), {"cid": chapter_id})).fetchone()
        if not row:
            return

        chapter_title = row.title or ""
        content_json = row.content_text or "{}"
        try:
            data = _json.loads(content_json) if isinstance(content_json, str) else content_json
            summary = (data.get("full_content", "") or "")[:500]
        except (_json.JSONDecodeError, TypeError):
            summary = str(content_json)[:500]

        prompt = DISCUSSION_SEED_PROMPT.format(
            chapter_title=chapter_title,
            content_summary=summary,
        )
        try:
            raw = await asyncio.wait_for(
                llm.generate(prompt, model_route="knowledge_extraction"),
                timeout=60
            )
            topics = _json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            logger.warning("[discussion_seed] LLM failed", chapter_id=chapter_id)
            return

        if not isinstance(topics, list):
            return

        # 写入 course_posts
        for topic in topics[:2]:  # 最多 2 个
            if not isinstance(topic, dict):
                continue
            title = (topic.get("title") or topic.get("topic") or "")[:50]
            content = (topic.get("content") or topic.get("prompt") or "")[:200]
            if not title or not content:
                continue
            await session.execute(_text("""
                INSERT INTO course_posts (post_id, space_id, author_user_id,
                    chapter_id, post_type, title, content, created_at, updated_at)
                VALUES (CAST(:pid AS uuid), CAST(:sid AS uuid), CAST(:uid AS uuid),
                    CAST(:cid AS uuid), 'discussion', :title, :content, now(), now())
            """), {
                "pid": str(_uuid.uuid4()), "sid": space_id, "uid": user_id,
                "cid": chapter_id, "title": title, "content": content,
            })
        await session.commit()
        logger.info("[discussion_seed] done", chapter_id=chapter_id, count=len(topics))
