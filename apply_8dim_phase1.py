#!/usr/bin/env python3
"""
apply_8dim_phase1.py
八维度系统 Phase 1：后端代码部署

执行内容：
  1. 部署 eight_dim_endpoints.py  → apps/api/modules/learner/
  2. 部署 eight_dim_tasks.py      → apps/api/tasks/
  3. 替换 CHAPTER_CONTENT_PROMPT  → blueprint_tasks.py
  4. 升级 QUIZ_GENERATION_PROMPT  → routers.py
  5. 升级 TEACHING_SYSTEM_PROMPT  → teaching_service.py
  6. 注册新路由                    → main.py
  7. 配置 Celery Beat              → tutorial_tasks.py

运行方式（项目根目录）：
  python3 apply_8dim_phase1.py
"""
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent  # ~/studystudio

def ok(msg):   print(f"  \033[32m✓\033[0m  {msg}")
def info(msg): print(f"  \033[34m→\033[0m  {msg}")
def warn(msg): print(f"  \033[33m⚠\033[0m  {msg}")
def fail(msg): print(f"  \033[31m✗\033[0m  {msg}"); sys.exit(1)

def backup(path: Path):
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".bak.8dim.{ts}")
    shutil.copy2(path, bak)
    info(f"备份 → {bak.name}")
    return bak

# ════════════════════════════════════════════════════════════════
# 步骤 1：拷贝新文件到正确位置
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 1：部署新文件\033[0m")

def deploy(src_name: str, dest: Path):
    src = ROOT / src_name
    if not src.exists():
        fail(f"找不到 {src_name}，请确保它在项目根目录 {ROOT}")
    if dest.exists():
        backup(dest)
    shutil.copy2(src, dest)
    ok(f"{src_name} → {dest.relative_to(ROOT)}")

deploy("eight_dim_endpoints.py", ROOT / "apps/api/modules/learner/eight_dim_endpoints.py")
deploy("eight_dim_tasks.py",     ROOT / "apps/api/tasks/eight_dim_tasks.py")

# ════════════════════════════════════════════════════════════════
# 步骤 2：替换 CHAPTER_CONTENT_PROMPT
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 2：升级 CHAPTER_CONTENT_PROMPT（blueprint_tasks.py）\033[0m")

BP_PATH = ROOT / "apps/api/tasks/blueprint_tasks.py"
if not BP_PATH.exists():
    fail(f"找不到 {BP_PATH}")

backup(BP_PATH)
src = BP_PATH.read_text(encoding="utf-8")

NEW_CHAPTER_PROMPT = '''CHAPTER_CONTENT_PROMPT = """为职业技能课程撰写章节正文，严格按四段式结构输出 JSON。

本章：{chapter_title}
目标：{objective}
任务：{task_description}
常见误区：{common_mistakes}

严格输出合法 JSON（不含 markdown 代码块，不含注释）：
{{
  "scene_hook": "100字以内，以\'你\'开头的真实职场情境，引出本章核心问题",
  "skim_summary": ["要点1（不超过20字）", "要点2（不超过20字）", "要点3（不超过20字）"],
  "full_content": "正文400-600字，含概念/原理/示例。重要术语用【术语名】标注。每隔2-3个自然段插入一个<!--CHECKPOINT:思考问题|答案提示-->标记（共2-3个检查点）。",
  "misconception_block": "若有常见误区则写：⚠️ 很多人误认为……，实际上……；若无则输出空字符串",
  "prereq_adaptive": {{
    "if_low":  "前置知识薄弱时补充的类比或简化解释（50字以内）",
    "if_high": "面向已有基础者的进阶拓展内容（50字以内）"
  }}
}}

只输出 JSON："""
'''

pattern = r'CHAPTER_CONTENT_PROMPT\s*=\s*""".*?"""'
if re.search(pattern, src, re.DOTALL):
    new_src = re.sub(pattern, NEW_CHAPTER_PROMPT.strip(), src, flags=re.DOTALL)
    ok("CHAPTER_CONTENT_PROMPT 定义替换完成")
else:
    warn("未找到现有 CHAPTER_CONTENT_PROMPT，追加到文件末尾")
    new_src = src + "\n\n" + NEW_CHAPTER_PROMPT

BP_PATH.write_text(new_src, encoding="utf-8")

# 注入 common_mistakes 参数到 format() 调用
src = BP_PATH.read_text(encoding="utf-8")

# 精确匹配
OLD_CALL = 'CHAPTER_CONTENT_PROMPT.format(\n                        chapter_title=ch.get("title",""),\n                        objective=ch.get("objective",""),\n                        task_description=ch.get("task_description",""))'
NEW_CALL = 'CHAPTER_CONTENT_PROMPT.format(\n                        chapter_title=ch.get("title",""),\n                        objective=ch.get("objective",""),\n                        task_description=ch.get("task_description",""),\n                        common_mistakes=ch.get("common_mistakes",""))'

if OLD_CALL in src:
    BP_PATH.write_text(src.replace(OLD_CALL, NEW_CALL), encoding="utf-8")
    ok("common_mistakes 参数注入成功（精确匹配）")
else:
    # 宽松正则替换
    new_src2 = re.sub(
        r'(CHAPTER_CONTENT_PROMPT\.format\s*\(\s*\n?\s*chapter_title[^)]*?task_description\s*=\s*ch\.get\("task_description",""\))\s*\)',
        lambda m: m.group(1) + ',\n                        common_mistakes=ch.get("common_mistakes",""))',
        src,
        flags=re.DOTALL
    )
    if 'common_mistakes' in new_src2 and new_src2 != src:
        BP_PATH.write_text(new_src2, encoding="utf-8")
        ok("common_mistakes 参数注入成功（宽松模式）")
    else:
        warn("未能自动注入 common_mistakes，请手动在 CHAPTER_CONTENT_PROMPT.format() 中添加：\n      common_mistakes=ch.get('common_mistakes','')")

# ════════════════════════════════════════════════════════════════
# 步骤 3：升级 QUIZ_GENERATION_PROMPT（routers.py）
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 3：升级 QUIZ_GENERATION_PROMPT（routers.py）\033[0m")

ROUTER_PATH = ROOT / "apps/api/modules/routers.py"
if not ROUTER_PATH.exists():
    fail(f"找不到 {ROUTER_PATH}")

backup(ROUTER_PATH)
src = ROUTER_PATH.read_text(encoding="utf-8")

NEW_QUIZ_PROMPT = '''QUIZ_GENERATION_PROMPT = """你是一位出题专家。根据以下知识点，生成 {count} 道多样化测验题。

知识点列表（含 entity_id，出题时必须使用对应 entity_id）：
{entities_json}

【题型比例要求】（按数量四舍五入分配）
- single_choice（单选题）  40%：4选项 A/B/C/D，answer 为正确选项字母
- true_false（判断题）     20%：answer 为字符串 "true" 或 "false"
- scenario（场景判断题）   20%：scenario 字段描述80-120字工作场景，options 为4个处理方案，answer 为字母
- generative（生成式题）   20%：要求学员用自己的话解释或举例，ai_rubric 列出3-4条评分要点（中文分号分隔）

【每题必须字段】
question_id（新生成的UUID）, entity_id（使用知识点列表中的id）, type, question

单选/场景：options（dict A-D）, answer（字母）, explanation（解析，可选）
判断题：answer（"true"/"false"）, explanation（可选）
场景题：scenario（情境描述）
生成式：ai_rubric（评分标准字符串）

严格输出 JSON 数组，不含 markdown 代码块：
[
  {{"question_id":"uuid","entity_id":"eid","type":"single_choice","question":"...","options":{{"A":"...","B":"...","C":"...","D":"..."}},"answer":"A","explanation":"..."}},
  {{"question_id":"uuid","entity_id":"eid","type":"true_false","question":"...","answer":"true","explanation":"..."}},
  {{"question_id":"uuid","entity_id":"eid","type":"scenario","question":"在以下场景中，最合适的处理方式是？","scenario":"...","options":{{"A":"...","B":"...","C":"...","D":"..."}},"answer":"B","explanation":"..."}},
  {{"question_id":"uuid","entity_id":"eid","type":"generative","question":"请用自己的话解释【知识点名称】，并举一个工作中的实际例子。","ai_rubric":"包含核心定义；例子与工作场景相关；说明实际应用价值；体现深层理解"}}
]

只输出 JSON 数组："""
'''

pattern_q = r'QUIZ_GENERATION_PROMPT\s*=\s*""".*?"""'
if re.search(pattern_q, src, re.DOTALL):
    new_src = re.sub(pattern_q, NEW_QUIZ_PROMPT.strip(), src, flags=re.DOTALL)
    ROUTER_PATH.write_text(new_src, encoding="utf-8")
    ok("QUIZ_GENERATION_PROMPT 替换完成")
else:
    warn("未找到 QUIZ_GENERATION_PROMPT，该 Prompt 可能在其他文件（如 learner_service.py），请手动替换")

# ════════════════════════════════════════════════════════════════
# 步骤 4：升级 TEACHING_SYSTEM_PROMPT（teaching_service.py）
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 4：升级 TEACHING_SYSTEM_PROMPT（teaching_service.py）\033[0m")

TS_PATH = ROOT / "apps/api/modules/teaching/teaching_service.py"
if not TS_PATH.exists():
    fail(f"找不到 {TS_PATH}")

backup(TS_PATH)
src = TS_PATH.read_text(encoding="utf-8")

NEW_TEACHING_PROMPT = '''TEACHING_SYSTEM_PROMPT = """你是一位专业的自适应学习辅导教师。
学习者当前知识掌握情况摘要：{mastery_summary}
当前学习主题：{topic}
对话模式：{mode}

【standard 模式（默认）】
正常解答问题，语言清晰易懂，必要时举例说明。发现知识误解时温和纠正并解释正确概念。

【socratic 模式（苏格拉底式追问）】
目标：通过反问引导学员自己得出答案，不直接给出结论。
流程：先问"你对这个问题有什么初步想法？"→ 聆听 → 追问薄弱点 → 给提示 → 最多3轮后给完整解释。
语气：好奇而友善，避免让学员感到被刁难。

【scenario 模式（角色扮演沙盘）】
扮演 context.scenario_role 指定的角色（如"客户"/"甲方"/"同事"）。
对话中保持角色，自然推进情境。
当学员说"结束"或"总结"时，退出角色，依次给出：
  ① 情境处理点评（优点/不足）
  ② 涉及知识点的掌握度判断（高/中/低）
  ③ 一条具体改进建议

不要在回复中说明自己在使用哪种模式。
"""
'''

pattern_t = r'TEACHING_SYSTEM_PROMPT\s*=\s*""".*?"""'
if re.search(pattern_t, src, re.DOTALL):
    new_src = re.sub(pattern_t, NEW_TEACHING_PROMPT.strip(), src, flags=re.DOTALL)
    TS_PATH.write_text(new_src, encoding="utf-8")
    ok("TEACHING_SYSTEM_PROMPT 替换完成")
else:
    warn("未找到 TEACHING_SYSTEM_PROMPT，追加到末尾")
    TS_PATH.write_text(src + "\n\n" + NEW_TEACHING_PROMPT, encoding="utf-8")

# 注入 mode 参数
src = TS_PATH.read_text(encoding="utf-8")

def inject_mode(text: str) -> tuple:
    pattern = r'(TEACHING_SYSTEM_PROMPT\.format\s*\()([^)]*?)(\))'
    count = [0]
    def replacer(m):
        args = m.group(2)
        if "mode=" in args:
            return m.group(0)
        count[0] += 1
        return m.group(1) + '\n        mode=context.get("mode", "standard"),\n        ' + args.lstrip() + m.group(3)
    new_text = re.sub(pattern, replacer, text, flags=re.DOTALL)
    return new_text, count[0]

new_src, injected = inject_mode(src)
if injected:
    TS_PATH.write_text(new_src, encoding="utf-8")
    ok(f"mode 参数注入成功（{injected} 处 format() 调用）")
else:
    warn("未能自动注入 mode，请手动在 TEACHING_SYSTEM_PROMPT.format() 中加入：\n      mode=context.get('mode', 'standard')")

# ════════════════════════════════════════════════════════════════
# 步骤 5：注册新路由（main.py）
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 5：注册 eight_dim_router（main.py）\033[0m")

MAIN_PATH = ROOT / "apps/api/main.py"
if not MAIN_PATH.exists():
    fail(f"找不到 {MAIN_PATH}")

backup(MAIN_PATH)
src = MAIN_PATH.read_text(encoding="utf-8")

IMPORT_LINE  = "from apps.api.modules.learner.eight_dim_endpoints import eight_dim_router"
INCLUDE_LINE = 'app.include_router(eight_dim_router, prefix="/api")'

if "eight_dim_router" in src:
    ok("eight_dim_router 已注册，跳过")
else:
    last_include = src.rfind("app.include_router")
    if last_include != -1:
        line_end = src.find("\n", last_include) + 1
        insert = f"\n# ── 八维度学习增强\n{IMPORT_LINE}\n{INCLUDE_LINE}\n"
        src = src[:line_end] + insert + src[line_end:]
        MAIN_PATH.write_text(src, encoding="utf-8")
        ok("eight_dim_router 注册到 main.py")
    else:
        # 追加到文件末尾
        src = src.rstrip() + f"\n\n# ── 八维度学习增强\n{IMPORT_LINE}\n{INCLUDE_LINE}\n"
        MAIN_PATH.write_text(src, encoding="utf-8")
        ok("eight_dim_router 追加到 main.py 末尾")

# ════════════════════════════════════════════════════════════════
# 步骤 6：Celery Beat 定时任务
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 6：配置 Celery Beat 定时任务\033[0m")

TT_PATH = ROOT / "apps/api/tasks/tutorial_tasks.py"
if TT_PATH.exists():
    src = TT_PATH.read_text(encoding="utf-8")
    BEAT_KEY   = '"aggregate-social-notes-daily"'
    BEAT_ENTRY = '''\n    "aggregate-social-notes-daily": {
        "task": "apps.api.tasks.eight_dim_tasks.aggregate_social_notes_task",
        "schedule": 86400,
    },'''
    if BEAT_KEY in src:
        ok("Celery Beat 条目已存在，跳过")
    else:
        new_src = re.sub(r'(beat_schedule\s*=\s*\{)', r'\1' + BEAT_ENTRY, src)
        if BEAT_KEY in new_src:
            backup(TT_PATH)
            TT_PATH.write_text(new_src, encoding="utf-8")
            ok("Celery Beat 定时任务写入 tutorial_tasks.py")
        else:
            warn("未找到 beat_schedule，请手动添加定时任务")
else:
    warn("未找到 tutorial_tasks.py，跳过 Beat 配置")

# ════════════════════════════════════════════════════════════════
# 完成摘要
# ════════════════════════════════════════════════════════════════
print("""
\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m
\033[32m  Phase 1 后端改造完成 ✅\033[0m
\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m

  已完成：
  ✓ eight_dim_endpoints.py  → modules/learner/
  ✓ eight_dim_tasks.py      → tasks/
  ✓ CHAPTER_CONTENT_PROMPT  四段式 JSON + 检查点标记
  ✓ QUIZ_GENERATION_PROMPT  新增 scenario + generative 题型
  ✓ TEACHING_SYSTEM_PROMPT  standard / socratic / scenario 三模式
  ✓ main.py                 注册 eight_dim_router
  ✓ Celery Beat             social notes 每日聚合

  下一步：

  1. 构建 API 镜像并重启：
\033[1m       docker compose build api celery_worker celery_worker_knowledge\033[0m
\033[1m       docker compose up -d\033[0m

  2. 验证新接口（替换 TOKEN）：
\033[1m       curl http://localhost:8000/api/learners/me/learning-mode \\
            -H "Authorization: Bearer <TOKEN>"\033[0m

  3. 构建并部署前端：
\033[1m       python3 apply_8dim_phase2.py\033[0m
""")
