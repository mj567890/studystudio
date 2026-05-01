# 课程生成平台 — 架构重构方案 v2.2（第三轮工程补丁修订版）

## 版本演进

| 版本 | 日期 | 变更 |
|------|------|------|
| v2 | 2026-04-30 | 初始重构方案，5 阶段，选择题+填空题模型 |
| v2.1 | 2026-05-01 | 第一轮专家修订：5 种方案维度、Course Map、5 种课型、9 维质检 |
| v2.2 | 2026-05-01 | 第二轮专家修订：经验校准层、Course Map 预览、MVP 范围收敛 |
| v2.2-p3 | 2026-05-01 | 第三轮工程补丁：经验校准路由分发（防 Context Bleed）、confidence_score、重新规划行为明确、经验校准题质检、材料版本冲突占位 |

详细变更记录见 `course_generation_architecture_changelog.md`。

---

## 问题诊断

当前系统做的是"格式转换"而非"教学设计"：
- AI 抽取知识点 → 聚类 → 命名章节 → 生成内容，中间缺少**教学分析**和**教学策略设计**
- 模板只是中文文本指令，不是结构化的教学策略
- 教师交互是**被动的**（出问题后精调/重新生成），而非**主动的**（前期定义目标）
- 生成的课程本质是"格式化参考材料"，不比看原书更易学

**v1 方案的问题（7 阶段版本）：**
- 7 个阶段层层堆叠 LLM 调用，但底层的生成能力没有根本改变
- CourseDesignWizard 本质是让教师"写论述题"——大部分教师写不出比 AI 更好的教学目标
- 学生端体验提升排到第三轮，见效太慢
- 质量检查让 AI 审查自己的输出，盲区共享，意义有限

**v2.1 的遗留问题（产品定位层面）：**
- 精巧的工程（5 种维度、Course Map、9 维质检）掩盖了一个空心的内核
- 教师在整个流程中贡献的真实信息量 < 10 bit，且全部是 AI 也能推测的显性维度
- 材料里没有的真实事故、隐性经验、老员工才知道的坑——AI 永远不会知道
- 而这些恰恰是企业付费做内训的真正理由

---

## 核心设计原则

```
                 AI 出选项，教师做选择，隐性知识结构化
                                      ↓
上传材料 → AI 分析+提案 → 教师选择+经验校准 → Course Map 确认 → AI 生成 → 审阅精调 → 反馈优化
              [选择题]     [选择题+填空题]      [轻量预览]     [全自动]   [选择题]   [全自动]
```

**教师永远只做选择题和填空题，不做论述题。**

- **选择题：** AI 生成具体、有差异的选项，教师选一个
- **填空题：** 选中的选项有少量可编辑字段（课时数、难度等），教师可微调
- **论述题（逃生舱）：** 始终提供自由文本输入，但作为次要入口，不是主路径
- **经验校准（新增）：** 通过 5 道动态选择题，将教师脑中的隐性知识结构化，注入生成流程

### AI 角色定义

> AI 的角色是"在教学框架、企业材料证据、教师选择、教师隐性经验、Course Map 约束下，生成可学习、可练习、可评估的课程体验"。

### 为什么这样设计

1. 大部分教师不具备写出优质教学目标/策略的专业能力
2. AI 比教师更擅长从材料中提炼和生成——但 AI 不知道教师的实际场景
3. 教师的核心价值是"我知道我的学生需要什么、哪里容易出错、什么案例真实发生"——需要在选择中体现
4. 选择题保证了质量下限（所有选项都是 AI 精心生成的），教师判断保证适配性
5. **教师脑中的隐性知识是 AI 永远拿不到的，必须通过结构化访谈抽取**
6. 课程生成平台的本质不是 prompt 平台，而是**教学决策采集平台 + 课程生成系统**

---

## 新架构：5 个阶段，阶段 2 拆为 3 个子步骤

```
阶段 1              阶段 2                              阶段 3           阶段 4         阶段 5
材料分析      →   课程设计对话                        →  Course Map   →  课程生成   →  审阅+反馈
(全自动)          ┌ 2a: 方案选择（选择题+填空题）        (自动校验)      (全自动)       (选择题+全自动)
                  ├ 2b: 经验校准（5 道选择题）★新增
                  └ 2c: Course Map 预览确认 ★新增
```

**2 个教师触点，总共 5-8 分钟：**
- 触点 1（阶段 2a+2b+2c）：选方案（3 次点击）→ 答 5 道题（3 分钟）→ 确认课程地图（1 分钟）
- 触点 2（阶段 5）：审阅章节，选改进方向（选择题）

---

## 阶段 1：材料分析与课程提案（全自动）

### 做什么
上传完成后，AI 自动分析所有材料，生成一份"课程设计提案"。这份提案包含 3 套**具体、不同的**课程设计方案，供教师在阶段 2a 中选择。

### 方案类型：动态选择

不再固定为"入门/进阶/实战"，AI 根据材料类型从 5 种方案维度中自动选择最合适的 3 种：

| 方案类型 | 适合场景 | 典型材料 |
|----------|----------|----------|
| 新手入门型 | 新员工、零基础 | 培训手册、教材 |
| 岗位任务型 | 要快速上岗、按流程做事 | SOP、操作手册、工作流程 |
| 风险合规型 | 制度、规范、红线、审计 | 管理制度、合规文件 |
| 案例复盘型 | 管理、销售、客服、事故复盘 | 案例集、事故报告 |
| 能力进阶型 | 骨干、主管、专家 | 高级文档、设计规范 |

### Prompt：COURSE_DESIGN_PROPOSAL_PROMPT

```
你是一位资深课程设计师。以下是待设计课程的全部知识体系和材料信息：

## 知识体系
核心概念（共 {entity_count} 个）：{core_entities}
知识点类型分布：概念 {concept_pct}%、要素 {element_pct}%、流程 {flow_pct}%、案例 {case_pct}%
学习依赖关系：{dependencies}

## 材料特征
材料类型：{material_types}
难度分布：{difficulty_distribution}
知识密度：{density}

请你设计 3 套不同的课程方案。每套方案必须在「目标受众」「教学风格」「内容组织」上有实质性区别。
方案之间要像不同出版社为同一主题出的不同教材——覆盖相同的知识，但面向不同的人群、采用不同的教法。
从以下 5 种方案维度中选择最合适的 3 种（根据材料特征灵活选择，不要总是入门/进阶/实战）：

- 新手入门型：面向"入门/转行"人群，强调从零构建理解，多用类比和可视化
- 岗位任务型：面向"要快速上岗"人群，强调步骤分解+易错点标注+实操验证
- 风险合规型：面向"需要确保合规"人群，强调制度原文+违规后果+正确做法对比
- 案例复盘型：面向"需要通过反思提升"人群，强调真实案例+冲突分析+策略迁移
- 能力进阶型：面向"有基础/进阶"人群，强调深度和系统性

严格按 JSON 输出：
{
  "proposals": [
    {
      "id": "A",
      "tagline": "一句话卖点",
      "target_audience": {
        "label": "面向谁",
        "level": "beginner|intermediate|advanced",
        "why_this_audience": "为什么适合这类人（30字）",
        "pain_points": ["学员最常遇到的 2-3 个真实痛点"]
      },
      "teaching_style": {
        "label": "教学风格标签",
        "approach": "具体怎么教",
        "theory_practice_ratio": "如 3:7",
        "andragogy_anchor": "成人学习锚点：课程如何直接解决学员当前岗位痛点？"
      },
      "course_structure": {
        "total_chapters": 章节数,
        "estimated_hours": 总学时,
        "stage_breakdown": "阶段划分",
        "pacing": "紧凑|标准|宽松"
      },
      "bloom_levels": {
        "primary": "主要认知层级（如 Apply+Analyze）",
        "distribution": "各层级占比"
      },
      "key_differentiator": "最独特的地方（20字）"
    }
  ]
}
```

### 数据变更
- `knowledge_spaces.course_proposals` JSONB — 存储 3 套课程方案
- `documents.material_summary` JSONB — 材料特征摘要

### 迁移
`migrations/034_course_proposals.sql`

### 验收
- 上传任意材料后，有 3 套有明显差异的方案
- 方案维度与材料类型匹配（制度类→合规型，流程类→任务型）

---

## 阶段 2a：方案选择（教师触点 — 选择题 + 填空题）

### 做什么
教师看到 AI 生成的 3 套方案，选一套，对关键参数做填空式微调。

### 前端：CourseDesignView

每张方案卡片展示：
- 一句话标签
- 目标受众 + 痛点
- 教学风格 + Andragogy 锚点
- 章节数和学时
- 主要 Bloom 认知层级
- 最独特的卖点

选中方案后展开填空题：

| 字段 | 类型 | 预填 | 说明 |
|------|------|------|------|
| 总课时 | 数字 | 方案建议值 | 影响章节详略程度 |
| 难度等级 | 下拉 | 方案建议值 | beginner/intermediate/advanced |
| 理论/实操比例 | 滑块 | 方案建议值 | 影响例子和练习的密度 |
| 额外要求 | 文本（选填） | 空 | 逃生舱 |

### API

```
POST /api/blueprints/{topic_key}/proposals
  Body: { space_id }
  Returns: { proposals: [...] }

POST /api/blueprints/{topic_key}/calibration-questions
  Body: { space_id, selected_proposal_id, adjustments }
  Returns: { questions: [...] }  ← 触发阶段 2b

POST /api/blueprints/{topic_key}/start-generation
  Body: { space_id, selected_proposal_id, adjustments, calibration_answers, course_map_confirmed }
```

### 数据变更
- `skill_blueprints.selected_proposal_id` VARCHAR
- `skill_blueprints.proposal_adjustments` JSONB
- `skill_blueprints.extra_notes` TEXT

---

## 阶段 2b：经验校准（教师触点续 — 5 道选择题）★新增

### 为什么需要这一层

v2.1 中教师贡献的真实信息量 < 10 bit，且全部是 AI 也能推测的显性维度。材料里没有的真实事故、隐性经验、老员工才知道的坑——AI 永远不会知道。而这些恰恰是企业付费做内训的真正理由。

经验校准是**产品差异化的核心**——通过结构化选择题，将教师脑中的隐性知识变成 AI 可读取的输入，注入到 Course Map、内容生成、精调的全流程。

### 核心设计原则

```
教师脑中有什么？                    如何抽取（选择题形态）？
─────────────────────           ──────────────────────────
哪些知识点实际容易出问题？    →   题1：勾选真痛点（多选）
什么案例真实发生过？          →   题2：选最贴近实际的场景
学员常犯什么错误？            →   题3：勾选学员真会犯的误解
哪些内容最重要？              →   题4：拖拽排序优先级
绝对不能做什么？              →   题5：勾选红线/禁忌
```

### 入口承诺

页面顶部明确告知：

> 接下来 5 道题，3 分钟搞定。每题都直接影响课程内容质量——AI 会根据你的选择，给真痛点更多笔墨、用真实案例作为教学主线、标注学员最容易犯的错误。

### 5 道必答题设计

**题 1（识别真痛点 — 多选）：**

```
AI 提问：从你上传的材料里，我识别出以下 6 个关键节点。
请勾选学员在实际工作中真的容易出问题的（可多选）：

☐ 设备启动前的安全检查清单核对
☐ 异常压力值的判断标准
☐ 交接班记录的完整性核对
☐ 紧急停机流程的执行顺序
☐ 常规巡检中的参数记录规范
☐ 设备维护后的验收标准

○ 以上都不太常见 / 我不太清楚

[为什么问这个] 你的勾选会让 AI 在课程里给这些节点更多笔墨、更多案例、更多练习。
```

**题 2（识别真案例 — 单选）：**

```
AI 提问：我准备了 3 个候选场景案例用于课程，哪个更贴近你们实际工作？

○ 场景A：新员工因为没核对交接班记录，导致下一班发现设备参数异常但找不到上一班的操作记录……
○ 场景B：老员工凭经验判断某个异常"问题不大"没有上报，两周后设备故障导致全线停产……
○ 场景C：两个班组对"异常压力值"的判断标准不一致，A班频繁停机检查，B班几乎不检查……

○ 都不太对，让我说一个 [展开输入框]

[为什么问这个] 选中的场景会成为整个模块的主线案例，贯穿多章。
```

**题 3（识别误区 — 多选）：**

```
AI 提问：学员在学这部分内容时，最容易产生以下哪些误解？

☐ "只要按规定操作就行，不需要理解原理"
☐ "设备没报警就是正常的"
☐ "交接班记录是走形式，口头说一下就行"
☐ "紧急情况可以跳过某些安全步骤"
☐ "老员工的做法肯定是对的"

○ 以上都不太对 / 我不太清楚
```

**题 4（优先级排序 — 拖拽）：**

```
AI 提问：如果学员只能记住 5 件事，你希望是哪 5 件？
（拖拽下方卡片到上方，按重要性排序）

[已选] 1. ________  2. ________  3. ________  4. ________  5. ________

[候选] ▸ 安全检查清单的完整执行    ▸ 异常状态的判断标准
       ▸ 交接班记录规范           ▸ 紧急停机流程
       ▸ 常规巡检参数记录         ▸ 设备维护验收标准
       ▸ 事故报告撰写规范         ▸ 应急预案启动条件
```

**题 5（红线/禁忌 — 多选）：**

```
AI 提问：哪些是"绝对不能做"的事，做了可能出安全事故或严重违规？

☐ 未确认设备状态就进行操作
☐ 在未授权情况下旁路安全装置
☐ 发现隐患不上报、不记录
☐ 不按 SOP 顺序执行关键步骤
☐ 代替他人签署安全确认文件

○ 以上都不太对 / 让我补充 [展开输入框]
```

### 可选追问（根据回答动态出现）

如果教师在题 1 勾选了"异常压力值的判断标准"是真痛点，AI 追问：

```
你刚才勾选了「异常压力值的判断标准」是真痛点。
能不能从下面选一个最贴近你印象中真实情况的事故描述？

○ 新员工误把正常波动当作异常，频繁停机影响生产
○ 老员工凭经验放过了真正的异常，导致设备损坏
○ 不同班组对"异常"的判断标准不一致，A班报B班不报
○ 让我描述 [展开输入框]
```

### 关键体验设计

| 设计要素 | 做法 |
|----------|------|
| 进度可视 | 每答 1 题，左侧"经验摘要卡"实时填充 |
| 可跳过 | 每题都有"不清楚/不适用"选项 |
| 承诺时间 | 3 分钟内完成，超时自动收尾 |
| 逃生舱 | 每题末尾有"让我说"，点击展开输入框 |
| 数据飞轮 | 如果某题大部分人选"不清楚"，AI 以后不再问这类问题 |

### 产出：experience_calibration JSONB（含质量评分）

```json
{
  "confidence_score": 0.8,
  "confidence_details": {
    "questions_answered": 5,
    "questions_skipped": 0,
    "let_me_say_used": 1,
    "warning": null
  },
  "real_pain_points": [
    {"entity_id": "ent_003", "label": "异常压力值判断标准", "severity": "high"}
  ],
  "selected_cases": [
    {"scenario": "老员工凭经验放过异常...", "relevance": "primary", "source": "teacher_selected"}
  ],
  "real_misconceptions": [
    {"misconception": "设备没报警就是正常的", "frequency": "common"}
  ],
  "priority_ranking": ["ent_007", "ent_003", "ent_012", "ent_001", "ent_009"],
  "red_lines": [
    {"action": "未确认设备状态就进行操作", "consequence": "安全事故/严重违规"}
  ],
  "expert_corrections": [
    {"original": "...", "correction": "教师补充的内容", "source": "let_me_say"}
  ]
}
```

**confidence_score 计算规则：**
- 5 道题全部有效回答（非"不清楚"）：1.0
- 4 道有效回答：0.8
- 3 道有效回答：0.6
- 2 道有效回答：0.4（触发预警）
- ≤1 道有效回答：0.2（触发强预警，Course Map 预览页提示"建议邀请一线主管补答"）

### 注入点：路由分发模式（防 Context Bleed）★第三轮补丁

**核心问题**：不能把所有经验校准数据全局广播给每个章节。例如"绝对不能在未泄压的情况下打开舱门"这条红线，只应出现在合规课/任务课中涉及该操作的章节，不应强行塞入第 1 章基础理论课。

**解决方案**：Course Map 生成时，AI 同时完成**校准数据路由分配**——把教师的 5 类隐性经验精确挂载到对应的章节节点上。内容生成时，每章只接收属于本章的校准数据。

```
阶段 3 Course Map 生成的 Prompt 中增加路由任务：

"除了生成章节结构外，请将教师的隐性经验分配到具体章节：
- real_pain_points → 分配到涉及该知识点的章节（标记为本章重点）
- selected_cases → 分配到案例最适合出现的章节（1 个案例可分配 1-2 章，但不同章应使用案例的**不同切面**：任务课/合规课用"事件描述+后果"，复盘分析章节用"决策点+复盘结论"，在 calibration_routing 的 cases 中增加 `facet` 字段标明切面类型）
- real_misconceptions → 分配到涉及对应概念的章节
- red_lines → 分配到涉及对应操作的章节
- priority_ranking → 影响章节排序和课时分配

在 Course Map JSON 中增加 calibration_routing 字段。"
```

Course Map 增加 `calibration_routing` 字段：

```json
{
  "chapters": [
    {
      "order": 1,
      "title": "压力系统基本原理",
      "chapter_type": "theory",
      "calibration_routing": {
        "pain_points": [],
        "cases": [
          {"case_id": "case_001", "facet": "consequence", "usage": "作为违规后果的实例"}
        ],
        "misconceptions": ["设备没报警就是正常的"],
        "red_lines": []
      }
    },
    {
      "order": 3,
      "title": "压力容器安全操作",
      "chapter_type": "compliance",
      "calibration_routing": {
        "pain_points": ["异常压力值判断标准"],
        "cases": ["老员工凭经验放过异常导致设备损坏"],
        "misconceptions": [],
        "red_lines": ["未确认设备状态就进行操作"]
      }
    }
  ]
}
```

**阶段 4 内容生成 Prompt 改为接收章节级校准数据**：`{chapter_calibration}` 取代全局 `{experience_calibration}`，只包含 Course Map 分配给本章的痛点/案例/误区/红线。

| 注入位置 | 数据范围 |
|----------|----------|
| `COURSE_MAP_PROMPT` | 全局经验校准（用于路由分配） |
| `CHAPTER_CONTENT_PROMPT` | **仅本章的 calibration_routing**（精确挂载） |
| `REFINE_OPTIONS_PROMPT` | 全局经验校准（用于审阅判断） |

### Prompt：EXPERIENCE_CALIBRATION_PROMPT

```
你是一位经验丰富的企业培训师，正在和一位一线教师/主管进行课前访谈。
这位教师刚刚为以下课程选择了一套设计方案：

## 课程信息
- 材料主题：{topic_key}
- 选中的方案：{selected_proposal_summary}
- 教师设置：{adjustments}
- 核心知识点：{core_entities}

## 你的任务
生成 5 道选择题，用于抽取教师脑中的隐性知识。每道题需要：

1. **题干**：自然、像对话，不像考试
2. **候选项**：基于材料内容推测，但又需要教师的真实经验才能答对
3. **"为什么问这个"**：告诉教师这道题如何影响课程质量
4. **"不清楚/不适用"选项**：每题都要有

5 道题覆盖以下维度：
- 题1（真痛点）：从知识点中抽 5-8 个，让教师勾选实际出过问题的
- 题2（真案例）：基于材料推测 3 个真实场景，让教师选最贴近的
- 题3（真误区）：列 5 个常见误解候选，让教师勾选学员真会犯的
- 题4（优先级）：抽 8 个知识点，让教师拖拽排序前 5
- 题5（红线）：列 4-5 条"绝对不能做"的事，让教师勾选

## 输出 JSON
{
  "questions": [
    {
      "id": "q1_pain_points",
      "type": "multi_select",
      "title": "请勾选学员在实际工作中真的容易出问题的",
      "options": [
        {"id": "opt_1", "label": "...", "entity_id": "ent_xxx"},
        ...
      ],
      "why_ask": "你的勾选会让 AI 给这些节点更多笔墨、更多案例、更多练习",
      "skip_option": "以上都不太常见 / 我不太清楚"
    },
    ...
  ],
  "estimated_time_seconds": 180
}

## 原则
- 每题 4-8 个选项，不多不少
- **选项必须让教师犹豫 2-3 秒、需要真实一线经验才能选对**，不能是显而易见的
- 至少 2 个选项必须是"容易混淆但不明显错误"的情境
- 选项不能全是材料原句的复述
- 每题必须绑定至少 3 个 entity_id
- 避免术语堆砌，用教师能听懂的语言
- 题 2 和题 5 至少包含一个"让我补充"入口
- 追问（follow_up）在教师选中某选项后动态触发，格式同上但更聚焦
```

### 经验校准题自动质检（生成后立即执行）

在生成校准题后、展示给教师前，运行轻量规则检查：

```python
def validate_calibration_questions(questions: list, entities: list) -> list[str]:
    issues = []
    for q in questions:
        # 每题必须绑定 ≥ 3 个 entity_id
        entity_ids = [o.get('entity_id') for o in q.get('options', []) if o.get('entity_id')]
        if len(entity_ids) < 3:
            issues.append(f"{q['id']}: 绑定知识点不足 ({len(entity_ids)} < 3)")
        # 必须有 skip_option
        if not q.get('skip_option'):
            issues.append(f"{q['id']}: 缺少跳过选项")
        # 至少 50% 的选项需要二次加工/经验判断（与 entity 原文相似度 < 0.6）
        # 原检查（max > 0.9）太宽松——只要 1 个选项不是原文复述就过关
        total_entity_options = len([o for o in q.get('options', []) if o.get('entity_id')])
        non_trivial = sum(
            1 for o in q.get('options', [])
            if o.get('entity_id')
            and keyword_overlap(o['label'], get_entity_definition(o['entity_id'])) < 0.6
        )
        if total_entity_options > 0 and non_trivial / total_entity_options < 0.5:
            issues.append(f"{q['id']}: 非平凡选项仅 {non_trivial}/{total_entity_options}（<50%），题目流于材料复述")
        # 选项多样性检查：避免所有选项一边倒（如全是"正确做法"或全是"错误做法"）
        sentiment_dist = classify_option_sentiments(q.get('options', []))
        if len(set(sentiment_dist.values())) < 2:
            issues.append(f"{q['id']}: 选项缺乏多样性（全是同一倾向），需包含正确/错误/中性至少 2 类")
    # 题2 和 题5 必须有"让我补充"
    for qid in ['q2_cases', 'q5_red_lines']:
        q = next((x for x in questions if x['id'] == qid), None)
        if q and not any('让我' in o.get('label', '') for o in q.get('options', [])):
            issues.append(f"{qid}: 缺少'让我补充'选项")
    return issues
```

质检不通过 → 自动重试（最多 1 次）→ 仍不通过 → 降级：减少题目数量至 3 道核心题。

### 数据变更
- `skill_blueprints.experience_calibration` JSONB — 含 confidence_score
- `skill_blueprints.calibration_quality_issues` JSONB — 校准题质检问题

### 迁移
`migrations/039_experience_calibration.sql`

### 验收
- 5 道题的候选项与材料内容相关，但需要真实经验才能判断（人工判读：每题至少 2 个选项"看了会犹豫"）
- 每题都能在 30 秒内答完
- 产出 JSON 包含所有 5 个维度的教师选择 + confidence_score
- 考前承诺时间 ≤ 3 分钟
- **confidence_score < 0.4 时，Course Map 预览页显示温和提示**

---

## 阶段 2c：Course Map 预览确认（教师触点续 — 轻量拦截）★新增

### 为什么需要这一层

两位专家独立提出了同一个风险：Course Map 全自动生成后直接进入内容生成，如果方向错了（如"设备开机"排在了"安全检查"后面），整门课程的 Token 成本白费。

解决方案不是让教师编辑 Course Map 细节（违反"不做论述题"原则），而是给一次**轻量拦截机会**——可以看、可以确认、可以要求重新规划，但不需要编辑。

### 前端设计

```
┌─────────────────────────────────────────────────┐
│  课程地图预览                                    │
│                                                  │
│  AI 规划了以下学习路径：                          │
│  认知负荷分布：前段 Understand/Apply → 后段       │
│              Analyze/Evaluate（合理递进 ✓）       │
│                                                  │
│  ┌─────────────────────────────────────────┐    │
│  │                                         │    │
│  │  第1章：设备安全基础 — 理论课（45分钟）  │    │
│  │    ├ ●○○○○○  Understand               │    │
│  │    ├ 目标：理解设备安全的三道防线        │    │
│  │    └ 前置：无                           │    │
│  │        ↓                                 │    │
│  │  第2章：开机前安全检查 — 任务课（60分钟）│    │
│  │    ├ ●●○○○○  Apply                    │    │
│  │    ├ 目标：执行完整的开机前安全检查清单  │    │
│  │    ├ 案例：老员工凭经验放过异常...       │    │
│  │    └ 前置：第1章安全基础概念             │    │
│  │        ↓                                 │    │
│  │  第3章：压力容器安全操作 — 合规课(45分钟)│    │
│  │    ├ ●●●○○○  Analyze                  │    │
│  │    ├ 目标：判断操作合规性并识别红线      │    │
│  │    ├ 红线：未确认状态就进行操作          │    │
│  │    └ 前置：第2章安全检查                 │    │
│  │        ↓                                 │    │
│  │  ...（共8章，总12学时）                  │    │
│  │                                         │    │
│  └─────────────────────────────────────────┘    │
│                                                  │
│  覆盖率：47/50 知识点（94%）                      │
│  Bloom 分布：Understand 25% / Apply 50% /        │
│             Analyze 15% / Evaluate 10%           │
│  经验校准：4/5 题有效（质量良好）                 │
│  ⚠ 经验校准质量较低，AI 会基于材料推测            │
│     真实场景。建议邀请一线主管补答。              │
│     [稍后补答]  [继续生成]                       │
│                                                  │
│  [🔄 重新规划]    [✅ 确认生成]                   │
└─────────────────────────────────────────────────┘
```

### 交互逻辑

| 教师操作 | 系统行为 |
|----------|----------|
| 点"确认生成" | 锁定 Course Map + calibration_routing，进入阶段 4 生成内容 |
| 点"重新规划" | 弹出原因选择（仍是选择题），将上一版作为反例重新生成 |
| 调"章节数" | 调大/调小后自动重新规划 |

### 重新规划行为规范（★第三轮补丁）

**问题**：如果"重新规划"只是重跑同一个 prompt，AI 可能给出几乎一样的大纲，教师会觉得"重新规划没用"。

**修正**：

1. **原因选择（选择题，不增加负担）— 每个原因映射不同策略**：
   - ○ 章节顺序不合理 → **"保留章节内容，重新排序"**（不动章节内部，只调顺序）
   - ○ 章节太少/太多 → **"保留主题划分，调整粒度"**（合并或拆分，不换主题）
   - ○ 重点不对 → **"保留章节，重新分配课时和详略"**（核心内容扩容，边缘内容缩编）
   - ○ 大部分还行，但有几章想挪/换 → **进入"标记模式"**（教师在大纲树上点击章节，打标签"挪到这里/换成另一类/删掉"——仍是选择题，选项是动态章节列表）
   - ○ 说不上来哪里不对 → **"完整重新生成"**（换一种章节切分逻辑）

2. **上一版作为反例**：重新规划时将上一版 Course Map 和教师选的原因注入 prompt：
   `"上一版方案是：[...]，教师认为 [原因]。请根据原因对应的策略调整，避免重复上一版的问题。"`

3. **上限 3 次**：超过 3 次后强制教师在已有版本中选择一个确认，避免无限循环。"标记模式"不计入重新规划次数。

不提供拖拽排序或章节编辑——那会陷入"论述题"陷阱。如果教师对具体章节顺序不满意，可以在阶段 5 审阅时通过选择题式精调来修正。

### 经验校准质量提示（★第三轮补丁）

当 `confidence_score < 0.4` 时（5 题中 ≥ 3 题选了"不清楚"），Course Map 预览页顶部显示温和提示，但**不阻止教师继续**：

> "经验校准内容较少（你只回答了 2/5 道题），AI 会基于材料推测真实场景。如果你不是这块业务的专家，建议邀请一线主管补答这部分。"

并提供"稍后补答"按钮（邀请链接可分享）。这是防止"校准层流于形式"的关键机制。

### 验收
- Course Map 大纲树清晰可读，教师 1 分钟内能判断"方向对不对"
- 点"重新规划"后得到不同的章节组织（不是同样的结构）
- 确认后锁定的 Course Map 被阶段 4 严格使用

---

## 阶段 3：Course Map 生成与自动校验（全自动）

### 核心思路

Course Map 不仅生成章节结构，还同时完成**校准数据路由分配**——将教师的 5 类隐性经验精确挂载到对应的章节节点上。这确保阶段 4 内容生成时每章只接收属于本章的校准数据，防止 Context Bleed。

### Course Map 结构（增加 calibration_routing）

```json
{
  "course_map": {
    "course_title": "课程标题",
    "overall_narrative": "从 A 到 B 到 C 的学习旅程描述",
    "bloom_progression": {"early": "Understand/Apply", "late": "Analyze/Evaluate"},
    "chapters": [
      {
        "order": 1,
        "title": "章节标题",
        "chapter_type": "theory|task|compliance",
        "bloom_level": "Understand",
        "learning_objectives": [
          {"verb": "Explain", "object": "...", "bloom_level": "Understand"}
        ],
        "knowledge_entities": ["entity_id_1"],
        "real_world_context": "对应的真实岗位任务/场景",
        "assessment_method": "quiz|judgment|simulation",
        "estimated_minutes": 45,
        "prerequisites": [],
        "transition_from_previous": "如何承接上一章",
        "calibration_routing": {
          "pain_points": [],
          "cases": [],
          "misconceptions": ["设备没报警就是正常的"],
          "red_lines": []
        }
      }
    ],
    "coverage_check": {
      "total_entities": 50,
      "covered_entities": 47,
      "coverage_rate": 0.94
    },
    "bloom_distribution": {
      "Understand": "25%", "Apply": "50%", "Analyze": "15%", "Evaluate": "10%"
    }
  }
}

| # | 校验项 | 阈值 | 不通过动作 |
|---|--------|------|-----------|
| 1 | 知识点覆盖率 | ≥ 90% | 重试（最多 2 次） |
| 2 | Bloom Apply+ 占比 | ≥ 40% | 重试 |
| 3 | 课型多样性 | ≥ 2 种课型 | 重试 |
| 4 | 学习路径连贯性 | 每章有 transition | 重试 |
| 5 | 评估方式多样性 | ≥ 2 种方式 | 警告 |
| 6 | **认知负荷递进** | 前 1/3 章节 Bloom ≤ Apply，后 1/3 ≥ Analyze | 警告 |
| **7** | **隐性经验零丢失（Zero-Loss Check）★新增** | **每项校准数据（痛点/案例/误区/红线）都被路由到 ≥1 章** | **重试路由分配** |

校验不通过 → 自动重试（最多 2 次）→ 仍不通过 → 标记警告，在阶段 2c 预览中展示。

**第 7 项（Zero-Loss Check）的特殊处理**：该检查不通过时**不重试整个 Course Map 生成**（那会改变章节结构），而是单独发一个轻量 LLM 调用："以下校准项未被分配：[...]，请将它们重新分配到合适的已有章节"。这样保证了路由完整性，又不会让 Course Map 在重试中变形。

```python
def validate_calibration_coverage(course_map: dict, calibration: dict) -> list[str]:
    """每个 calibration 项都应该被路由到至少一章，或显式标记为 unused"""
    routed_pain = set()
    routed_cases = set()
    routed_miscon = set()
    routed_redlines = set()

    for ch in course_map['chapters']:
        r = ch.get('calibration_routing', {})
        routed_pain.update(p.get('label', '') for p in r.get('pain_points', []))
        routed_cases.update(c.get('id', '') for c in r.get('cases', []))
        routed_miscon.update(m.get('label', '') for m in r.get('misconceptions', []))
        routed_redlines.update(rl.get('label', '') for rl in r.get('red_lines', []))

    issues = []
    for category, expected, routed in [
        ('真痛点', calibration.get('real_pain_points', []), routed_pain),
        ('真实案例', calibration.get('selected_cases', []), routed_cases),
        ('常见误区', calibration.get('real_misconceptions', []), routed_miscon),
        ('红线', calibration.get('red_lines', []), routed_redlines),
    ]:
        expected_labels = {item.get('label', str(item)) for item in expected}
        missing = expected_labels - routed
        if missing:
            issues.append(f"未路由的{category}: {missing}")

    return issues
```

### 数据变更
- `skill_blueprints.course_map` JSONB
- `skill_blueprints.course_map_validated` BOOLEAN
- `skill_blueprints.course_map_issues` JSONB

### 迁移
`migrations/038_course_map.sql`

---

## 阶段 4：课程内容生成（全自动 — 核心改造）

### 核心思路

AI 的角色是"在 5 重约束下填充内容"：硬编码教学模板 + Course Map + 原始材料定义 + 教师选择 + 教师隐性经验。

### MVP 课型（第一轮 3 种）

按企业场景优先级排序：

| 课型 | 优先级 | 适用场景 |
|------|--------|----------|
| **task（任务课）** | 最高 | SOP、操作手册、工作流程 |
| **compliance（合规课）** | 最高 | 管理制度、红线规范、审批流程 |
| **theory（理论课）** | 高 | 概念、原理、基础认知 |
| case（案例复盘课） | 第二轮 | 管理、销售、客服、事故复盘 |
| project（实战课） | 第二轮 | 综合项目、实战演练 |

### 4a. 硬编码教学模板（3 种 MVP 版本）

**任务课（task）— 技能习得模式：**
```
【技能习得模式 — 严格遵循此结构】

1. [场景] — 真实场景描述：在什么情况下你需要这个技能？
   Andragogy 锚点：这个任务在你当前岗位的 KPI/风险中意味着什么？
   本章路由的教师真实案例（如有）：{chapter_cases}
2. [目标] — 完成这个任务后的效果预览
3. [分解演示] — 分步骤演示完整过程，每步配说明（不可跳步）
4. [关键细节] — 标注最容易出错的 2-3 个细节
   本章路由的教师勾选误区（如有）：{chapter_misconceptions}
5. [变式练习] — 给出1个微调过的场景，让学生尝试
6. [专家对比] — 展示专家做法 vs 新手常犯错误的对比
7. [检查点] — 1个实操性验证问题
8. [一句话总结]
```

**合规课（compliance）— 制度内化模式：**
```
【制度内化模式 — 严格遵循此结构】

1. [违规场景] — 一个看似合理但实际违规的真实场景描述
   本章路由的教师红线场景（如有）：{chapter_red_lines}
2. [制度原文] — 精确引用相关制度/规范的原文条款（不可改写）
   <!--SOURCE:entity_id:chunk_id-->
3. [为什么这样规定] — 解释制度背后的逻辑：风险、教训、保护目的
4. [正确做法] — 分步骤展示合规操作流程
5. [错误做法] — 展示常见违规行为及其表面上的"合理性"
6. [后果与风险] — 违规的真实后果：处罚、事故、审计发现
7. [判断练习] — 2-3个场景判断题："这种情况是否合规？为什么？"
8. [一句话红线] — 这条制度的底线是什么
   本章路由的教师红线（如有）：{chapter_red_lines}
```

**理论课（theory）— 概念建构模式：**
```
【概念建构模式 — 严格遵循此结构】

1. [现象/问题] — 从学生熟悉的场景出发，引出困惑或反直觉现象
   本章路由的教师痛点（如有）：{chapter_pain_points}
2. [现有理解的局限] — 指出直觉/已有知识的不足
3. [核心概念引入] — 精确引入本章核心概念（从 knowledge_entities 中提取定义，不可改写）
4. [拆解说明] — 用类比或分层方式解释概念的内在结构
5. [正例+反例] — 至少1个正例和1个反例
   本章路由的教师勾选误区（如有）：{chapter_misconceptions}
6. [与已知概念的关联] — 连接到学生已学过的相关概念
7. [检查点] — 1个选择题或判断题，确认核心理解
8. [一句话总结]
```

### 4b. 整合生成 Prompt

```
你是一位执行严格教学设计的课程内容生成专家。

## 课程全局（来自教师选择 + 经验校准）
- 目标受众：{target_audience_label}
- 教学风格：{teaching_style_label}
- 总课时约束：{total_hours}h，本章约占 {chapter_hours}h
- Andragogy 锚点：{andragogy_anchor}
- 教师额外要求：{extra_notes}

## 教师隐性经验（来自阶段 3 Course Map 的 calibration_routing — 仅本章相关）
- 经验校准全局置信度：{confidence_score}/1.0（{confidence_label}）
- 本章真痛点（如有）：{chapter_pain_points}
- 本章真实案例/场景（如有）：{chapter_cases}
- 本章学员常见误区（如有）：{chapter_misconceptions}
- 本章红线（如有）：{chapter_red_lines}

**重要**：以上数据已经由 Course Map 精确路由到本章。不要将不属于本章的隐性经验强行编入。

**置信度驱动的生成行为（★第四轮补丁）**：
当 confidence_score < 0.4 时，进入保守生成模式：
- 不要编造"真实案例"假装是教师提供的
- `[场景]` 段使用通用场景而非具体公司事件
- 不要使用"据该企业经验……""在贵公司……"等暗示教师确认过的表述
- `[一句话红线]` 引用材料原文，不要补充教师未确认的内容
当 confidence_score ≥ 0.4 时，正常使用教师提供的经验数据。

## 本章 Course Map 定义
- 标题：{chapter_title}
- 在课程叙事中的位置：{transition_from_previous}
- 课型：{chapter_type}
- 学习目标（含 Bloom 动词）：{learning_objectives}
- 核心知识点（定义不可改写）：{entities_with_definitions}
- 真实岗位场景：{real_world_context}
- 评估方式：{assessment_method}
- 前置知识：{prerequisites}

## 内容生成模板 — 必须严格遵循
{teaching_template}

## 格式要求
- 全文 {target_word_count} 字左右
- 代码用 <pre><code class="language-xxx"> 包裹
- 图表用 <!--DIAGRAM:N--> 标记，diagrams 字段提供 Mermaid 代码
- CHECKPOINT 嵌入正文：<!--CHECKPOINT:type|question|answer-->
- 术语首次出现用 **粗体** 标注
- 制度/参数/流程必须标注来源：<!--SOURCE:entity_id:chunk_id-->
- 每 800-1200 字至少 1 个检查点

## 输出 JSON
{
  "full_content": "完整 HTML-safe 正文",
  "scene_hook": "第1节的现象/场景描述",
  "skim_summary": "3-5个要点",
  "code_example": "代码示例（如适用）",
  "misconception_block": "1-2个常见误解及纠正",
  "prereq_adaptive": {"if_high": "...", "if_low": "..."},
  "diagrams": [{"type": "mermaid", "description": "...", "code": "..."}],
  "checkpoints": [{"position": "...", "type": "choice|judge|coding", "question": "...", "answer": "...", "explanation": "..."}],
  "source_citations": [{"entity_id": "...", "chunk_id": "...", "quote": "原文短句", "usage": "制度原文|流程依据|参数依据"}]
}
```

### 4c. MVP 质量检查（6 维）

第一轮只做以下 6 维（第 7-9 维待第二轮补全）：

```python
def validate_chapter_content(content: dict, entities: list, chapter_type: str,
                             course_map_entry: dict, calibration: dict = None) -> list[str]:
    issues = []

    # 1. 知识点覆盖
    for e in entities:
        if e['canonical_name'] not in content['full_content']:
            issues.append(f"缺失知识点: {e['canonical_name']}")

    # 2. 定义一致性（限定在定义段落）
    for e in entities:
        if e.get('short_definition'):
            definition_section = extract_definition_section(content['full_content'], e['canonical_name'])
            if keyword_overlap(e['short_definition'], definition_section) < 0.3:
                issues.append(f"定义偏差: {e['canonical_name']}")

    # 3. 结构完整性（按课型不同）
    required_map = {
        "theory": ["[现象/问题]", "[核心概念引入]", "[检查点]", "[一句话总结]"],
        "task": ["[场景]", "[分解演示]", "[检查点]", "[一句话总结]"],
        "compliance": ["[违规场景]", "[制度原文]", "[判断练习]", "[一句话红线]"],
    }
    for s in required_map.get(chapter_type, []):
        if s not in content['full_content']:
            issues.append(f"缺失教学结构: {s}")

    # 4. 可读性
    avg_len = mean([len(s) for s in split_sentences(content['full_content'])])
    if avg_len > 40:
        issues.append(f"平均句长过长: {avg_len:.0f}字")

    # 5. 原文依据检查（task/compliance 强制）
    if chapter_type in ('compliance', 'task'):
        if '<!--SOURCE:' not in content['full_content']:
            issues.append("缺少原文依据标记")

    # 6. 任务闭环检查（task/compliance）
    if chapter_type == 'task':
        for s in ['[场景]', '[分解演示]', '[关键细节]', '[变式练习]', '[检查点]']:
            if s not in content['full_content']:
                issues.append(f"任务闭环不完整: 缺失 {s}")
    if chapter_type == 'compliance':
        for s in ['[违规场景]', '[制度原文]', '[正确做法]', '[错误做法]', '[判断练习]']:
            if s not in content['full_content']:
                issues.append(f"合规闭环不完整: 缺失 {s}")

    return issues
```

待第二轮补全的 3 维：
- 练习密度检查（需结构化 checkpoint 字段）
- Bloom 动词层级检查（需 Course Map 已有结构化 verb/bloom_level 字段）
- Andragogy 锚点检查（依赖经验校准数据积累）

### 数据变更
- `skill_chapters.teaching_template_used` VARCHAR(30)
- `skill_chapters.auto_check_issues` JSONB
- `skill_chapters.auto_check_passed` BOOLEAN
- `skill_chapters.source_citation_count` INTEGER

---

## 阶段 5：章节审阅 + 反馈闭环

### 5a. 章节审阅（教师触点 2 — 选择题）

课程生成完成后，教师审阅各章节。对于不满意的章节，AI 提供 3-4 个具体的改进方向（动态生成 + 质量检查结果 + 经验校准结果），教师选择后 AI 执行精调。

改进方向由 `REFINE_OPTIONS_PROMPT` 动态生成，输入包括：
- 章节内容摘要
- 质量检查发现的问题
- **教师经验校准中勾选的真痛点和误区**
- 学生数据（如有，来自阶段 5b）

精调执行时，选中方向的描述被注入 `CHAPTER_REFINEMENT_PROMPT`，要求只改对应部分不重写全部。

### 5b. 学生反馈闭环（全自动，第二轮+）

- `content_effectiveness` 表：追踪每章学习效果
- 指标对齐 **Kirkpatrick 四级**：Reaction（评分/完成率）、Learning（检查点正确率）、Behavior（技能应用）、Results（绩效变化）
- `detect_content_issues` Celery Beat 任务：自动识别问题章节
- 反馈数据注入 `REFINE_OPTIONS_PROMPT`，形成闭环

---

## MVP 第一轮范围（v2.2）

| 阶段 | 组件 | 范围 |
|------|------|------|
| 1 | 课程方案生成 | 5 种维度，AI 选 3 |
| 2a | 方案选择 | 3 卡片 + 4 参数填空 |
| **2b** | **经验校准** | **5 道选择题 + 动态追问** |
| **2c** | **Course Map 预览** | **大纲树 + 确认/重新规划** |
| 3 | Course Map 校验 | 6 项规则（含认知负荷递进） |
| 4 | 内容生成 | **3 种课型（theory/task/compliance）** |
| 4 | 质量检查 | **6 维** |
| 4 | SOURCE 标记 | entity_id:chunk_id |
| 5a | 章节审阅 | 选择题式精调（含经验校准注入） |
| — | case + project 课型 | 推迟至第二轮 |
| — | 9 维检查剩余 3 维 | 推迟至第二轮 |
| — | 5b 反馈闭环 | 推迟至第三轮 |

### MVP 已知限制

| 限制 | 说明 |
|------|------|
| 第二轮精调智能度受限 | 学生反馈数据要等第三轮才接入；第二轮主要靠质量检查 + 经验校准做改进建议，精调选项的智能度有上限 |
| 移动端拖拽体验 | 题 4 优先级排序在移动端可用"勾选+编号"替代拖拽 |
| 材料版本冲突 | 多版本文档的矛盾值由 confidence_score + 教师补答缓解，正式解决方案推迟至 v2.3 |

### 涉及文件

| 文件 | 操作 | 轮次 |
|------|------|------|
| `apps/api/tasks/blueprint_tasks.py` | 重写 | 第一轮 |
| `apps/api/modules/skill_blueprint/router.py` | 修改 | 第一轮 |
| `apps/api/modules/skill_blueprint/schema.py` | 修改 | 第一轮 |
| `apps/web/src/views/learner/CourseDesignView.vue` | 重写（三步流程） | 第一轮 |
| `apps/web/src/components/RefineChapterDialog.vue` | 重写 | 第二轮 |
| `apps/web/src/api/index.ts` | 修改 | 第一轮+第二轮 |
| `apps/api/modules/admin/router.py` | 修改 | 第二轮+第三轮 |
| `apps/api/tasks/analytics_tasks.py` | 新建 | 第三轮 |
| `migrations/034_course_proposals.sql` | 新建 | 第一轮 |
| `migrations/035_blueprint_proposal_fields.sql` | 新建 | 第一轮 |
| `migrations/036_chapter_quality_checks.sql` | 更新 | 第一轮 |
| `migrations/037_content_effectiveness.sql` | 新建 | 第三轮 |
| `migrations/038_course_map.sql` | 新建 | 第一轮 |
| `migrations/039_experience_calibration.sql` | 新建 | 第一轮 |

---

## 与 v1 的关键差异

| 维度 | v1（7 阶段） | v2.2（5 阶段 + 3 子步骤） |
|------|-------------|-------------|
| 教师交互模式 | 写论述题 | 做选择题+填空题，含隐性知识抽取 |
| 教师贡献信息量 | ~5 bit（一段文本） | **~200+ bit**（方案+5 题+确认） |
| 教学策略来源 | AI 动态生成 | 硬编码教学模板 + AI 选择课型 |
| 课程结构保证 | 聚类→章节 | Course Map 中间层 + 认知负荷递进校验 |
| LLM 调用次数 | 7+ 次 | 方案 + 校准题 + Course Map + 内容 + (可选)精调 = 4-6 次 |
| 质量检查 | AI 自评分数 | 6 维自动化规则检查 |
| 课型 | 不区分 | 3 种 MVP（theory/task/compliance） |
| 企业材料适配 | 无 | Andragogy 锚点 + 原文依据 + 经验校准 |
| 核心护城河 | 无 | 经验校准数据飞轮（用得越多提问越准） |

---

## 工程挑战与对策

### 1. 经验校准题的生成质量
- **问题：** AI 生成的候选项可能太泛、太明显，不需要真实经验就能答
- **对策：** Prompt 中明确要求"看了会犹豫、需要真实经验才能选"；数据飞轮机制收集教师的"不清楚"率，优化提问策略

### 2. 教师可能跳过经验校准
- **问题：** 3 分钟仍然是阻力，部分教师直接点"跳过全部"
- **对策：** 每道题都有"不清楚"选项；入口处明确展示"这对课程质量的影响"；后续如果数据显示跳过率 >50%，缩短为 3 道必答题

### 3. Course Map 预览的覆盖度
- **问题：** 教师 1 分钟内能否判断方向对不对？
- **对策：** 大纲树只展示标题+课型+目标，不展示细节；方向不对时"重新规划"能产生不同结果

### 4. 生成时间
- **问题：** 增加了经验校准题生成和 Course Map 预览两步
- **对策：** 经验校准题和 Course Map 可以并行生成（都依赖方案选择结果）；校准题一次生成缓存 24h

### 5. 旧方案兼容
- **问题：** 已部署的 v2 第一轮代码（无经验校准、无 Course Map 预览）
- **对策：** 新字段 DEFAULT NULL；旧课程可跳过经验校准直接使用 Course Map；已有章节通过"用新模板重新生成"升级

### 6. 材料版本冲突（v2.3 待补 — ★第三轮占位）
- **问题：** 教师上传的多份文档可能存在矛盾（如 2022 版手册说"1.2MPa 报警"，2024 版说"1.0MPa 报警"）。AI 在阶段 1 抽取 entity 时会随机选一个或两个都抽，导致课程内容自相矛盾——这是企业培训最不能容忍的错误
- **对策（v2.3）：** 阶段 1 entity 抽取后，对同一 canonical_name 下的多个不同 short_definition 做相似度对比，低于阈值时标记为"冲突 entity"，在阶段 2c 预览页顶部作为"待澄清问题"展示给教师（又是一道选择题：选哪个版本作准）
- **当前缓解：** confidence_score 机制鼓励教师邀请了解版本变更的一线主管参与校准

### 7. 成本估算与关键指标（★第三轮补丁）

**单门课程 LLM Token 估算**（按材料规模）：

| 材料规模 | 知识点数 | 章节数 | 预估 Token | 预估成本（GPT-4o） |
|----------|----------|--------|-----------|-------------------|
| 小（<50 页） | <100 | 5-8 | ~80K | ~$0.40 |
| 中（50-200 页） | 100-300 | 8-15 | ~200K | ~$1.00 |
| 大（200-500 页） | 300-800 | 15-25 | ~500K | ~$2.50 |

**关键观察指标**（第一轮验证时埋点）：

| 指标 | 预期范围 | 警戒线 |
|------|----------|--------|
| Course Map 重新规划率 | 10-30% | >50% |
| 经验校准跳过率（"不清楚"≥3 题） | 15-25% | >40% |
| 校准题平均完成时间 | 2-3 分钟 | >5 分钟 |
| 6 维质检首次通过率 | 60-80% | <40% |

跳过率阈值建议先观察 4 周，按实际分布的 P75 确定，不硬编码 50%。

---

## 验证方案

### 第一轮验证
1. 上传 3 个不同领域材料（技术文档 + 管理制度 + 操作手册）
2. 检查方案是否匹配材料类型
3. **实测 5 道经验校准题：候选项是否"看了会犹豫"？教师 3 分钟内能否完成？**
4. Course Map 大纲树是否合理？点"重新规划"是否产生不同结构？
5. 生成 3 门课程，抽查章节：
   - 是否严格按对应课型模板组织？
   - **经验校准中的案例/误区/红线是否被正确路由到对应章节？（每门课至少查 5 个位置——这是判断 v2.2 是否真正起作用的关键验收项）**
   - **同一案例是否被多章重复使用？（应只出现在 Course Map 路由分配的章节）**
   - 知识点定义是否与材料一致？
   - 章节之间有教学递进感吗？
6. 盲评：v1 vs v2.2 课程的教学质量对比

### 第二轮验证
1. 精调选项是否基于质量检查+经验校准结果？
2. 精调后内容是否只改对应部分？

### 第三轮验证
1. Kirkpatrick 四级数据收集是否准确？
2. 学生反馈是否被正确注入精调选项？

---

## 附录 A：专家反馈采纳情况

| # | 专家建议 | 采纳 | 对应修改 |
|----|----------|------|----------|
| 1 | 方案类型不应固定为入门/进阶/实战 | 采纳 | 5 种维度，AI 自动选 3 |
| 2 | 增加 Course Map 层 | 采纳 | 新增阶段 3 |
| 3 | 课型扩展到 5 种 | 部分采纳 | MVP 3 种，case/project 第二轮 |
| 4 | 质量检查扩充 | 采纳 | 4→6 维 MVP，另 3 维第二轮 |
| 5 | 注入 Bloom 层级 | 采纳 | 提案+Course Map+质检三层 |
| 6 | Andragogy 锚点 | 采纳 | 任务课/合规课模板嵌入 |
| 7 | 原文依据检查 | 采纳 | SOURCE:entity_id:chunk_id |
| 8 | 定义检查限定段落 | 采纳 | extract_definition_section() |
| 9 | 精调选项注入外部信号 | 采纳 | 注入质量结果+经验校准+学生数据 |
| 10 | Kirkpatrick 四级 | 采纳 | 阶段 5b |
| 11 | AI 角色定义修正 | 采纳 | 增加"教师隐性经验"约束 |
| **12** | **加入经验校准（动态访谈）层** | **采纳** | **新增阶段 2b：5 道选择题** |
| 13 | Course Map 教师预览 | 采纳 | 新增阶段 2c |
| 14 | 第一轮范围缩减 | 采纳 | MVP 3 课型 + 6 维检查 |
| 15 | SOURCE 绑定 chunk_id | 采纳 | 改为 entity_id:chunk_id |
| 16 | 场景密度检查改为结构化字段 | 采纳 | 结构化字段为主，关键词 fallback |
| 17 | Bloom 检查直接用结构化字段 | 采纳 | 读 verb/bloom_level，不匹配中文 |
| 18 | 认知负荷递进检查 | 采纳 | Course Map 校验第 6 项 |
| 19 | 分层生成（Pipeline Generation） | 暂缓 | YAGNI，先验证核心闭环 |
| 20 | Safe Hallucination 机制 | 暂缓 | 正确解法是经验校准拿真实案例 |
| **21** | **经验校准路由分发（防 Context Bleed）** | **采纳** | **Course Map 增加 calibration_routing，内容生成只收章节级数据** |
| 22 | 重新规划行为规范（反例注入 + 上限） | 采纳 | 阶段 2c 增加原因选择 + 3 次上限 |
| 23 | 经验校准 confidence_score | 采纳 | 产出 JSON 增加质量评分 + 低分预警 |
| 24 | 经验校准题自动质检 | 采纳 | 生成后立即运行 5 条规则检查 |
| 25 | 重新规划原因选择 | 采纳 | 4 个选项（仍是选择题） |
| 26 | Course Map Bloom 标签 | 采纳 | 大纲树每章增加 Bloom 层级 |
| 27 | 成本估算 + 关键指标 | 采纳 | Token 估算表 + 埋点指标 |
| 28 | 材料版本冲突检测 | 占位 | v2.3 待补，当前用 confidence_score 缓解 |
| 29 | 移动端拖拽交互 | 记录 | Web 优先，移动端改为勾选+编号 |
| 30 | 精调智能度限制标注 | 采纳 | MVP 范围表增加已知限制说明 |

## 附录 C：第三轮专家反馈决策日志（v2.2 工程补丁）

### 反馈来源

四位专家在 v2.2 完成后给出了最后一批反馈。一位给了整体肯定 + 小建议，一位指出了 Context Bleed 工程风险，一位给了 7 条细节建议，一位给了 3 条补丁。

### 决策框架

每条反馈按"必须改 / 建议改 / 暂不改"三档判断：

**必须改（4 项）— 不改会出工程事故或产品退化：**

| # | 反馈 | 风险 | 修改 |
|---|------|------|------|
| 1 | Context Bleed：全局校准数据广播到每章 | 第 1 章理论课强行插入操作红线，内容逻辑割裂 | 路由分发：Course Map 做 calibration_routing，内容生成只收章节级数据 |
| 2 | 经验校准流于形式 | 教师全选"不清楚"，30 秒答完但 calibration 全空，系统以为"已校准" | confidence_score + 低分预警 |
| 3 | 重新规划行为不明确 | 教师点"重新规划"得到几乎一样的大纲 | 反例注入 + 原因选择 + 3 次上限 |
| 4 | 经验校准题质量无检查 | AI 可能生成太泛的题 | 5 条自动质检规则 |

**建议改（4 项）：**

| # | 反馈 | 修改 |
|---|------|------|
| 5 | Course Map 重新规划无原因 | 4 个选项（仍是选择题） |
| 6 | Course Map 预览缺 Bloom 标签 | 每章增加 Bloom 层级显示 |
| 7 | 缺成本估算 | Token 估算表 + 关键指标埋点 |
| 8 | 第二轮精调智能度无说明 | MVP 范围表增加已知限制 |

**暂不改/记录（3 项）：**

| # | 反馈 | 理由 |
|---|------|------|
| 9 | 材料版本冲突检测 | 正确但工程量大，v2.3 待补，当前用 confidence_score 缓解 |
| 10 | 移动端拖拽交互 | Web 优先产品，移动端改为"勾选+编号" |
| 11 | 跳过率阈值硬编码 50% | 改为"观察 4 周，按 P75 确定" |

### 最关键的设计变更：路由分发

这是本轮最重要的工程修正。原始 v2.2 设计中有个隐蔽的假设：把教师所有经验校准数据全局注入到每个章节的生成 prompt 中。这会导致 LLM "讨好型人格"——看到红线就想用，不管当前章节是否需要。

修正后的数据流：

```
教师 5 道题
    ↓
experience_calibration (全局) + confidence_score
    ↓
COURSE_MAP_PROMPT 收到全局校准数据
    ├ 生成章节结构
    └ 做路由分配 → calibration_routing（每章的校准子集）
         ↓
CHAPTER_CONTENT_PROMPT 只收到本章的 {chapter_calibration}
    ├ 理论课 → 只收到误区
    ├ 任务课 → 收到真案例 + 痛点
    └ 合规课 → 收到红线 + 真案例
```

这个改动不影响前端，不影响 API schema，只影响后端 prompt 拼接逻辑。实施成本约半天。

| 文件 | 说明 |
|------|------|
| `course_generation_architecture_v2.md` | **当前最新版本（v2.2-p3）** |
| `course_generation_architecture_v2.2_backup.md` | v2.2 备份（第二轮专家修订后） |
| `course_generation_architecture_v2.1_backup.md` | v2.1 备份（第一轮专家修订后） |
| `course_generation_architecture_changelog.md` | 版本演进记录与决策逻辑 |
