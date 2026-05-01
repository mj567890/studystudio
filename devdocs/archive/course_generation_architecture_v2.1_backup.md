# 课程生成平台 — 架构重构方案 v2.1（专家审阅修订版）

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

## 核心设计原则

```
                 AI 出选项，教师做选择
                         ↓
上传材料 → AI 分析+生成提案 → 教师选择 → Course Map → AI 生成课程 → 教师选择→审阅精调 → 学生使用 → 反馈优化
              [选择题]       [填空题]    [全自动]                  [选择题+填空题]
```

**教师永远只做选择题和填空题，不做论述题。**

- **选择题：** AI 生成 3-4 个具体、有差异的选项，教师选一个
- **填空题：** 选中的选项有少量可编辑字段（课时数、难度等），教师可微调数字/文本
- **论述题（逃生舱）：** 始终提供自由文本输入，但作为次要入口，不是主路径

### AI 角色定义（专家修订版）

> AI 的角色是"在教学框架、企业材料证据、教师选择、Course Map 约束下，生成可学习、可练习、可评估的课程体验"。

不是"在框架内填充内容"，而是在多重约束下创造完整的教学体验。

### 为什么这样设计

1. 大部分教师不具备写出优质教学目标/策略的专业能力
2. AI 比教师更擅长从材料中提炼和生成——但 AI 不知道教师的实际场景
3. 教师的核心价值是"我知道我的学生需要什么"——只需要在选择中体现
4. 选择题保证了质量下限（所有选项都是 AI 精心生成的），教师判断保证适配性
5. 课程生成平台的本质不是 prompt 平台，而是**教学决策采集平台 + 课程生成系统**

---

## 新架构：5 个阶段，2 个教师触点

```
阶段 1           阶段 2              阶段 3           阶段 4            阶段 5
材料分析      →  课程设计对话      →  Course Map    →  课程生成      →  章节审阅 + 反馈闭环
(全自动)        (教师选择题+填空题)   (全自动校验)     (全自动)         (教师选择题 + 全自动)
```

---

## 阶段 1：材料分析与课程提案（全自动）

### 做什么
上传完成后，AI 自动分析所有材料，生成一份"课程设计提案"。这份提案包含 3 套**具体、不同的**课程设计方案，供教师在阶段 2 中选择。

### 关键设计
不是生成一份"分析报告"然后让教师填表，而是直接生成**可选择的方案**。

### 方案类型：动态选择（专家修正）

不再固定为"入门/进阶/实战"，AI 根据材料类型从 5 种方案维度中自动选择最合适的 3 种：

| 方案类型 | 适合场景 | 典型材料 |
|----------|----------|----------|
| 新手入门型 | 新员工、零基础 | 培训手册、教材 |
| 岗位任务型 | 要快速上岗、按流程做事 | SOP、操作手册、工作流程 |
| 风险合规型 | 制度、规范、红线、审计 | 管理制度、合规文件 |
| 案例复盘型 | 管理、销售、客服、事故复盘 | 案例集、事故报告 |
| 能力进阶型 | 骨干、主管、专家 | 高级文档、设计规范 |

### Prompt：COURSE_DESIGN_PROPOSAL_PROMPT（修订版）

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

## 材料分类（决定方案方向）
根据材料特征，该内容最适合的方案维度为：{suggested_dimensions}

请你设计 3 套不同的课程方案。每套方案必须在「目标受众」「教学风格」「内容组织」上有实质性区别。
方案之间要像不同出版社为同一主题出的不同教材——覆盖相同的知识，但面向不同的人群、采用不同的教法。
不要总是使用"入门/进阶/实战"三种固定分类，要根据材料特征灵活选择最合适的维度。

严格按 JSON 输出：
{
  "proposals": [
    {
      "id": "A",
      "tagline": "一句话卖点（如：「从攻防实战出发，学完就能上手」）",
      "target_audience": {
        "label": "面向谁（如：零基础运维转安全）",
        "level": "beginner|intermediate|advanced",
        "why_this_audience": "为什么这个方案适合这类人（30字）",
        "pain_points": ["这类学员最常遇到的 2-3 个真实痛点"]
      },
      "teaching_style": {
        "label": "教学风格标签（如：案例驱动+动手优先）",
        "approach": "具体怎么教（如：每章从一个真实安全事件开始，引出技术点，最后回到防御方案）",
        "theory_practice_ratio": "比如 3:7（三分讲七分练）",
        "andragogy_anchor": "成人学习锚点：这个课程如何直接解决学员当前岗位的痛点？"
      },
      "course_structure": {
        "total_chapters": 章节数,
        "estimated_hours": 总学时,
        "stage_breakdown": "如：基础认知(4章) → 工具实战(5章) → 综合攻防(3章)",
        "pacing": "紧凑（每天1小时，2周完成）| 标准（每周3次，1个月完成）| 宽松（自主学习节奏）"
      },
      "bloom_levels": {
        "primary": "主要认知层级（如 Apply+Analyze）",
        "distribution": "各层级占比（如 Remember 10%, Understand 20%, Apply 40%, Analyze 20%, Evaluate 10%）"
      },
      "key_differentiator": "这个方案最独特的地方（20字）"
    },
    { "id": "B", ... },
    { "id": "C", ... }
  ]
}

方案差异化要求（AI 根据材料类型从以下 5 维中选择最合适的 3 个）：
- 新手入门型：面向"入门/转行"人群，强调从零构建理解，多用类比和可视化
- 岗位任务型：面向"要快速上岗"人群，强调步骤分解+易错点标注+实操验证
- 风险合规型：面向"需要确保合规"人群，强调制度原文+违规后果+正确做法对比
- 案例复盘型：面向"需要通过反思提升"人群，强调真实案例+冲突分析+策略迁移
- 能力进阶型：面向"有基础/进阶"人群，强调深度和系统性，多用源码和底层机制

每个方案必须包含 Bloom 认知层级分布（Remember/Understand/Apply/Analyze/Evaluate/Create）。
```

### 数据变更
- `knowledge_spaces.course_proposals` JSONB — 存储 3 套课程方案
- `skill_blueprints.selected_proposal` JSONB — 教师选中的方案 + 填空修改
- `documents.material_summary` JSONB — 材料特征摘要（含 material_dimensions 字段）

### 迁移
`migrations/034_course_proposals.sql`

### 验收
- 上传任意材料后，knowledge_spaces.course_proposals 有 3 套有明显差异的方案
- 人工检查 3 套方案的差异是否实质性的（不只是措辞变化）
- 技术类材料和技术类方案维度匹配，制度类材料和合规型方案维度匹配

---

## 阶段 2：课程设计对话（教师触点 1 — 选择题 + 填空题）

### 做什么
教师看到 AI 生成的 3 套方案，选一套，对关键参数做填空式微调，然后确认生成。

### 前端：CourseDesignView（单页，非多步向导）

**文件：** `apps/web/src/views/learner/CourseDesignView.vue`

**布局：**

```
┌─────────────────────────────────────────────────┐
│  为「{材料名称}」选择课程设计方案                │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────┐ │
│  │ 方案 A       │ │ 方案 B       │ │ 方案 C    │ │
│  │              │ │              │ │           │ │
│  │ 从零入门     │ │ 深度进阶     │ │ 实战速成  │ │
│  │              │ │              │ │           │ │
│  │ 面向：零基础 │ │ 面向：有基础 │ │ 面向：快  │ │
│  │ 运维转安全   │ │ 开发者       │ │ 速上手者  │ │
│  │              │ │              │ │           │ │
│  │ 风格：案例   │ │ 风格：系统   │ │ 风格：项  │ │
│  │ 驱动+动手    │ │ 深入+源码   │ │ 目驱动     │ │
│  │              │ │              │ │           │ │
│  │ 12章·30学时  │ │ 15章·45学时  │ │ 8章·12学时 │ │
│  │ Bloom: Apply │ │ Bloom: Ana   │ │ Bloom: App │ │
│  │              │ │              │ │           │ │
│  │   [选择]     │ │   [选择]     │ │  [选择]   │ │
│  └──────────────┘ └──────────────┘ └──────────┘ │
│                                                  │
│  ▼ 选中的方案展开为填空题                         │
│  ┌─────────────────────────────────────────────┐ │
│  │ 课时数：[30] 小时   难度：[初级 ▼]           │ │
│  │ 理论/实操比：理论 [30]% / 实操 [70]%         │ │
│  │ 额外要求（选填）：                            │ │
│  │ ┌──────────────────────────────────────┐    │ │
│  │ │ 例如：弱化数学推导，多给直觉解释...    │    │ │
│  │ └──────────────────────────────────────┘    │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│            [← 返回]    [🎯 开始生成课程]         │
└─────────────────────────────────────────────────┘
```

三种方案用卡片横向排列，每张卡片展示：
- 一句话标签
- 目标受众 + 痛点
- 教学风格 + Andragogy 锚点
- 章节数和学时
- 主要 Bloom 认知层级
- 最独特的卖点

### 填空题（而非论述题）

| 字段 | 类型 | 预填 | 说明 |
|------|------|------|------|
| 总课时 | 数字 | 方案建议值 | 影响章节详略程度 |
| 难度等级 | 下拉 | 方案建议值 | beginner/intermediate/advanced |
| 理论/实操比例 | 滑块 | 方案建议值 | 影响例子和练习的密度 |
| 额外要求 | 文本（选填） | 空 | 逃生舱，可以写任意要求 |

### API

```
POST /api/blueprints/{topic_key}/proposals
  — 触发 AI 生成课程方案
  Body: { space_id }
  Returns: { proposals: [...] }

POST /api/blueprints/{topic_key}/start-generation
  — 基于选中的方案 + 填空启动 Course Map 生成 + 课程生成
  Body: {
    space_id,
    selected_proposal_id: "A",
    adjustments: { total_hours: 30, difficulty: "beginner", theory_ratio: 0.3, extra_notes: "弱化数学推导" }
  }
```

### 数据变更
- `skill_blueprints.selected_proposal_id` VARCHAR
- `skill_blueprints.proposal_adjustments` JSONB — 教师的填空修改
- `skill_blueprints.extra_notes` TEXT — 教师额外要求
- `skill_blueprints.bloom_target` JSONB — 目标 Bloom 层级分布

### 迁移
`migrations/035_blueprint_proposal_fields.sql`

### 验收
- 3 张方案卡片内容有实质性差异
- 选中方案后填空字段预填正确
- 教师只需 3 次点击（选方案 + 点生成）即可完成极简流程
- 5 分钟内可走完（极简档）

---

## 阶段 3：Course Map 生成与自动校验（全自动 — 新增）

### 核心思路

在"方案选择"和"内容生成"之间加入一个轻量级的**课程地图 Course Map**。这不是多一步复杂流程，而是生成前的结构校验——确保章节之间有教学叙事上的递进，而非知识点聚类。

### 为什么需要这一层

- 没有 Course Map，章节之间可能仍然是"知识点聚类"，缺乏学习路径
- Course Map 强制 AI 在生成内容前先思考：先教什么、后教什么、每章是什么课型、是否覆盖所有必要知识点
- 全自动生成，不增加教师负担，但能显著提升课程结构的合理性

### Course Map 结构

```json
{
  "course_map": {
    "course_title": "课程标题",
    "overall_narrative": "从 A 到 B 到 C 的学习旅程描述（2-3句话）",
    "chapters": [
      {
        "order": 1,
        "title": "章节标题",
        "chapter_type": "theory|task|project|compliance|case",
        "learning_objectives": [
          {
            "verb": "Analyze|Apply|Evaluate|Create|...",
            "object": "具体可观测的学习成果",
            "bloom_level": "Analyze"
          }
        ],
        "knowledge_entities": ["entity_id_1", "entity_id_2"],
        "real_world_context": "对应的真实岗位任务/场景/制度",
        "assessment_method": "quiz|coding|case_analysis|judgment|simulation",
        "estimated_minutes": 45,
        "prerequisites": ["前置章节或知识点"],
        "transition_from_previous": "如何承接上一章"
      }
    ],
    "coverage_check": {
      "total_entities": 150,
      "covered_entities": 148,
      "uncovered_entities": ["entity_id_x", "entity_id_y"],
      "entity_coverage_rate": 0.987
    },
    "bloom_distribution": {
      "Remember": "10%",
      "Understand": "20%",
      "Apply": "35%",
      "Analyze": "20%",
      "Evaluate": "10%",
      "Create": "5%"
    }
  }
}
```

### 自动校验规则（Course Map 生成后立即执行）

1. **知识点覆盖率** ≥ 90%（未覆盖的知识点标注警告）
2. **Bloom 分布合理**：Apply 及以上层级 ≥ 40%（防止低阶罗列）
3. **课型多样性**：单门课至少包含 2 种课型
4. **学习路径连贯性**：每章有明确的 transition_from_previous
5. **评估方式多样性**：assessment_method 至少包含 2 种不同方式

校验不通过 → 自动重试（最多 2 次）→ 仍不通过 → 标记警告，让教师在第 5 阶段审阅时看到。

### Prompt：COURSE_MAP_PROMPT

```
你是一位课程架构师。以下是课程设计决策和材料分析结果：

## 课程全局
- 课程标题：{course_title}
- 目标受众：{target_audience_label}
- 教学风格：{teaching_style_label}
- 总课时约束：{total_hours}h
- 目标 Bloom 分布：{bloom_target}
- 教师额外要求：{extra_notes}

## 知识点清单
{entities_with_dependencies}

## 材料来源
{source_materials_summary}

请生成完整的课程地图（Course Map）。要求：
1. 章节顺序必须有教学叙事上的递进（不是知识点聚类）
2. 每章指定一种课型（theory/task/project/compliance/case）
3. 每个学习目标必须包含 Bloom 动词（至少 40% 为 Apply 或以上层级）
4. 每章必须关联真实岗位场景或制度依据
5. 知识点覆盖率 ≥ 90%

输出 JSON 格式（见 Course Map 结构）。
```

### 数据变更
- `skill_blueprints.course_map` JSONB — 课程地图
- `skill_blueprints.course_map_validated` BOOLEAN — 是否通过自动校验
- `skill_blueprints.course_map_issues` JSONB — 校验发现的问题

### 迁移
`migrations/038_course_map.sql`

### 变更文件
- `apps/api/tasks/blueprint_tasks.py` — 新增 `generate_course_map()` 函数
- `apps/api/tasks/blueprint_tasks.py` — 新增 `validate_course_map()` 函数

### 验收
- 任意课程生成的 Course Map 覆盖率 ≥ 90%
- Bloom 分布 Apply+ 层级 ≥ 40%
- 人工检查章节之间是否有教学上的递进关系

---

## 阶段 4：课程内容生成（全自动 — 核心改造）

### 核心思路

不再让 AI "自己设计教学策略"，而是把经过验证的教学模式**硬编码到生成 prompt 中**。AI 的角色是"在 Course Map、教学框架、企业材料证据的多重约束下填充内容"，而不是"发明教学方法"。

每个章节的生成输入包括：
- Course Map 中该章的完整定义（目标、课型、知识点、场景、评估方式）
- 对应课型的硬编码教学模板
- 材料中的原始知识点定义（不可改写）

### 4a. 按课型的硬编码教学模板（扩展到 5 种）

**理论课（theory）— 概念建构模式：**
```
【概念建构模式 — 严格遵循此结构】

1. [现象/问题] — 从学生熟悉的场景出发，引出困惑或反直觉现象（2-3句）
2. [现有理解的局限] — 指出直觉/已有知识的不足（1-2句）
3. [核心概念引入] — 精确引入本章核心概念（从 knowledge_entities 中提取定义，不可改写）
4. [拆解说明] — 用类比或分层方式解释概念的内在结构（3-5句）
5. [正例+反例] — 至少1个正例和1个反例，帮助学生精确理解边界
6. [与已知概念的关联] — 连接到学生已学过的相关概念
7. [检查点] — 1个选择题或判断题，确认核心理解
8. [一句话总结] — 如果你只记住一件事，记住这个
```

**任务课（task）— 技能习得模式：**
```
【技能习得模式 — 严格遵循此结构】

1. [场景] — 真实场景描述：在什么情况下你需要这个技能？（2-3句）
   Andragogy 锚点：这个任务在你当前岗位的 KPI/风险中意味着什么？
2. [目标] — 完成这个任务后的效果预览
3. [分解演示] — 分步骤演示完整过程，每步配说明（不可跳步）
4. [关键细节] — 标注最容易出错的 2-3 个细节
5. [变式练习] — 给出1个微调过的场景，让学生尝试
6. [专家对比] — 展示专家做法 vs 新手常犯错误的对比
7. [检查点] — 1个实操性验证问题
8. [一句话总结]
```

**实战课（project）— 问题解决模式：**
```
【问题解决模式 — 严格遵循此结构】

1. [挑战陈述] — 清晰描述要解决的完整问题
   Andragogy 锚点：如果不按 SOP/最佳实践做，真实业务后果是什么？
2. [约束条件] — 现实中的限制（时间、工具、信息不完整等）
3. [思路引导] — 给予方向性提示，但不直接给答案（苏格拉底式提问）
4. [关键决策点] — 标注需要做出选择的关键节点及其权衡
5. [参考方案] — 展示一种可行方案及其推理过程
6. [方案评估] — 引导评估方案的优劣和适用范围
7. [延伸思考] — 如果条件改变怎么办？
8. [一句话总结]
```

**合规课（compliance）— 制度内化模式（新增）：**
```
【制度内化模式 — 严格遵循此结构】

1. [违规场景] — 一个看似合理但实际违规的真实场景描述（2-3句）
2. [制度原文] — 精确引用相关制度/规范的原文条款（不可改写）
3. [为什么这样规定] — 解释制度背后的逻辑：风险、教训、保护目的（3-5句）
4. [正确做法] — 分步骤展示合规操作流程
5. [错误做法] — 展示常见违规行为及其表面上的"合理性"
6. [后果与风险] — 违规的真实后果：处罚、事故、审计发现
7. [判断练习] — 2-3个场景判断题："这种情况是否合规？为什么？"
8. [一句话红线] — 这条制度的底线是什么，永远不要越过
```

**案例复盘课（case）— 经验迁移模式（新增）：**
```
【经验迁移模式 — 严格遵循此结构】

1. [案例背景] — 完整还原案例的真实背景：时间、角色、环境、前置条件
2. [关键冲突] — 案例中的核心矛盾或决策困境是什么
3. [当事人选择] — 案例中当事人当时做了什么选择，为什么
4. [后果] — 选择导致的实际后果（正面或负面）
5. [复盘分析] — 结构化分析：什么做对了、什么做错了、关键转折点在哪
6. [正确策略] — 基于分析提炼的正确应对策略或决策框架
7. [类似情境练习] — 给出一个变体情境，让学员应用策略
8. [迁移总结] — 这类情境的通用原则，可迁移到其他场景
```

### 4b. 整合的教学设计+内容生成 Prompt

**文件：** `apps/api/tasks/blueprint_tasks.py` — 重写 `CHAPTER_CONTENT_PROMPT`

```
你是一位执行严格教学设计的课程内容生成专家。

## 课程全局信息（来自 Course Map + 教师选择）
- 课程目标受众：{target_audience}
- 教学风格：{teaching_style}
- 总课时约束：{total_hours}h，本章约占 {chapter_hours}h
- 教师额外要求：{extra_notes}
- Andragogy 锚点：{andragogy_anchor}

## 本章 Course Map 定义
- 标题：{chapter_title}
- 在课程叙事中的位置：{transition_from_previous}
- 课型：{chapter_type}（决定使用哪种教学模板）
- 学习目标（必须包含 Bloom 动词）：{learning_objectives}
- 本章涉及的核心知识点（从原始材料提取，定义不可改写）：
{entities_with_definitions}
- 真实岗位场景/制度依据：{real_world_context}
- 评估方式：{assessment_method}
- 前置知识（学生应该已经掌握的）：{prerequisites}

## 内容生成模板 — 必须严格遵循
{teaching_template}  ← 根据 chapter_type 从 5 套模板中选择

## 格式要求
- 全文 {target_word_count} 字左右
- 代码用 <pre><code class="language-xxx"> 包裹
- 图表用 <!--DIAGRAM:N--> 标记位置，同时在 diagrams 字段提供 Mermaid 代码
- CHECKPOINT 嵌入在正文中对应位置，格式：<!--CHECKPOINT:type|question|answer-->
- 术语首次出现时用 **粗体** 标注
- 涉及制度、参数、流程、红线时，必须用 <!--SOURCE:entity_id--> 标注来源知识点
- 每 800-1200 字至少有 1 个检查点

## 输出 JSON
{
  "full_content": "完整的 HTML-safe 正文（包含 CHECKPOINT、DIAGRAM、SOURCE 标记）",
  "scene_hook": "1 节的现象/场景/挑战描述",
  "skim_summary": "3-5 个要点，用于快速浏览模式",
  "code_example": "代码示例（如适用）",
  "misconception_block": "1-2 个常见误解及纠正",
  "prereq_adaptive": {"if_high": "已掌握前置知识时的补充内容", "if_low": "前置知识点快速回顾"},
  "diagrams": [{"type": "mermaid", "description": "图表说明", "code": "mermaid代码"}],
  "checkpoints": [{"position": "在正文中的位置描述", "type": "choice|judge|coding", "question": "...", "answer": "...", "explanation": "解释"}],
  "source_citations": [{"entity_id": "...", "context": "引用的上下文"}]
}
```

### 4c. 移除的内容

- ~~INSTRUCTIONAL_STRATEGY_PROMPT~~ — 不再需要单独的 AI 策略设计步骤
- ~~CHAPTER_OUTLINE_PROMPT~~ — 大纲被 Course Map 替代
- ~~QUALITY_CHECK_PROMPT~~ — 改为增强的自动化检查（见 4d）

### 4d. 增强的自动化质量检查（专家修订版 — 9 维检查）

替代 LLM 自我审查 + 原 4 维检查的增强版：

```python
def validate_chapter_content(content: dict, entities: list, chapter_type: str, course_map_entry: dict) -> list[str]:
    """增强的自动化质量检查，返回问题列表"""
    issues = []

    # === 层 1：事实准确性（原检查，保留） ===
    # 1a. 知识点覆盖
    for e in entities:
        if e['canonical_name'] not in content['full_content']:
            issues.append(f"缺失知识点: {e['canonical_name']}")

    # 1b. 定义一致性（修正：仅检查定义段落，不检查全文）
    for e in entities:
        if e.get('short_definition'):
            definition_paragraph = extract_definition_section(content['full_content'], e['canonical_name'])
            match_rate = keyword_overlap(e['short_definition'], definition_paragraph)
            if match_rate < 0.3:
                issues.append(f"定义偏差: {e['canonical_name']}（原文定义与生成内容差异过大）")

    # === 层 2：结构完整性（原检查，适配 5 种课型） ===
    required_sections_map = {
        "theory": ["[现象/问题]", "[核心概念引入]", "[检查点]", "[一句话总结]"],
        "task": ["[场景]", "[分解演示]", "[检查点]", "[一句话总结]"],
        "project": ["[挑战陈述]", "[参考方案]", "[延伸思考]", "[一句话总结]"],
        "compliance": ["[违规场景]", "[制度原文]", "[判断练习]", "[一句话红线]"],
        "case": ["[案例背景]", "[复盘分析]", "[类似情境练习]", "[迁移总结]"],
    }
    required = required_sections_map.get(chapter_type, [])
    for s in required:
        if s not in content['full_content']:
            issues.append(f"缺失教学结构: {s}")

    # === 层 3：可读性（原检查，保留） ===
    sentences = split_sentences(content['full_content'])
    avg_len = mean([len(s) for s in sentences])
    if avg_len > 40:
        issues.append(f"平均句长过长: {avg_len:.0f}字（建议<40字）")

    # === 层 4：练习密度检查（新增） ===
    word_count = len(content['full_content'])
    checkpoint_count = content['full_content'].count('<!--CHECKPOINT:')
    if word_count / max(checkpoint_count, 1) > 1200:
        issues.append(f"练习密度过低: 每{word_count/max(checkpoint_count,1):.0f}字1个检查点（建议每800-1200字1个）")

    # === 层 5：场景密度检查（新增） ===
    scene_markers = ['[现象/问题]', '[场景]', '[挑战陈述]', '[违规场景]', '[案例背景]',
                     '场景', '案例', '例如', '假设', '比如', '真实']
    scene_count = sum(1 for m in scene_markers if m in content['full_content'])
    if scene_count < 2:
        issues.append(f"场景密度过低: 全文仅{scene_count}个场景/案例标记（建议≥2个）")

    # === 层 6：Bloom 动词层级检查（新增） ===
    low_bloom = ['了解', '熟悉', '掌握', '知道', '认识', '理解']
    high_bloom = ['判断', '执行', '分析', '处理', '设计', '改进', '创建',
                  '评估', '比较', '诊断', '预测', '优化', '重构', '制定']
    objectives = course_map_entry.get('learning_objectives', [])
    obj_text = ' '.join([o.get('object', '') for o in objectives])
    has_high = any(v in obj_text for v in high_bloom)
    only_low = all(v not in obj_text for v in high_bloom)
    if only_low:
        issues.append(f"Bloom层级过低: 学习目标仅含低阶动词（了解/熟悉/掌握），需包含高阶动词（{', '.join(high_bloom[:5])}...）")

    # === 层 7：任务闭环检查（新增 — 仅 task/compliance 课型） ===
    if chapter_type in ('task', 'compliance'):
        closure_chain = {
            'task': ['[场景]', '[分解演示]', '[关键细节]', '[变式练习]', '[检查点]'],
            'compliance': ['[违规场景]', '[制度原文]', '[正确做法]', '[错误做法]', '[判断练习]'],
        }
        chain = closure_chain.get(chapter_type, [])
        missing = [s for s in chain if s not in content['full_content']]
        if missing:
            issues.append(f"任务闭环不完整: 缺失 {missing}")

    # === 层 8：原文依据检查（新增 — 关键） ===
    if chapter_type in ('compliance', 'task'):
        source_count = content['full_content'].count('<!--SOURCE:')
        if source_count == 0:
            issues.append(f"缺少原文依据: 涉及制度/流程的内容必须标注原材料来源（<!--SOURCE:entity_id-->）")

    # === 层 9：Andragogy 锚点检查（新增） ===
    if chapter_type == 'task':
        if 'KPI' not in content['full_content'] and '风险' not in content['full_content'] and '岗位' not in content['full_content']:
            issues.append("缺少成人学习锚点: 任务课应在开头说明与岗位KPI/风险的关系")
    if chapter_type == 'project':
        if '业务后果' not in content['full_content'] and 'SOP' not in content['full_content']:
            issues.append("缺少成人学习锚点: 实战课应说明不按最佳实践的真实业务后果")

    return issues
```

只有当自动化检查发现 critical issues 时才触发 LLM 修订，修订 prompt 精确描述问题：
```
以下章节内容存在具体问题：
{issue_list}

请只修复上述问题，不要重写全部内容。保持其他部分不变。
原内容：
{original_content}
```

### 数据变更
- `skill_chapters.teaching_template_used` VARCHAR(30) — 使用了哪个模板
- `skill_chapters.auto_check_issues` JSONB — 自动化检查发现的问题（9 维）
- `skill_chapters.auto_check_passed` BOOLEAN — 是否通过自动化检查
- `skill_chapters.bloom_level` VARCHAR(20) — 本章实际 Bloom 层级
- `skill_chapters.source_citation_count` INTEGER — 原文引用次数

### 迁移
`migrations/036_chapter_quality_checks.sql`（更新）

### 变更文件
- `apps/api/tasks/blueprint_tasks.py` — 重写 CHAPTER_CONTENT_PROMPT，新增 compliance/case 模板
- `apps/api/tasks/blueprint_tasks.py` — 重写 `validate_chapter_content()` 为 9 维检查

### 验收
- 5 种课型生成的内容结构不同（人工对比各 1 章）
- 知识点定义与原始材料一致（抽查 5 个定义）
- 自动化检查能捕获缺失知识点、结构不完整、Bloom 层级过低
- 合规课和案例复盘课的结构合理可用
- 生成时间不显著增加（相比当前）

---

## 阶段 5：章节审阅 + 反馈闭环（教师触点 2 — 选择题 + 全自动）

### 做什么
课程生成完成后，教师可以审阅各章节。对于不满意的章节，AI 提供 3-4 个具体的改进方向（选择题），教师选择后 AI 执行精调。学生端数据自动收集，识别问题内容，反馈到生成流程。

### 5a. 章节审阅（选择题模式）

#### 核心变化
从"教师写指令 → AI 执行"变为"AI 提议改进方向 → 教师选择 → AI 执行"。

#### 前端：重构 RefineChapterDialog

**文件：** `apps/web/src/components/RefineChapterDialog.vue`（重写）

```
┌──────────────────────────────────────────────┐
│  精调章节：{chapter_title}                    │
├──────────────────────────────────────────────┤
│                                               │
│  当前内容摘要：                                │
│  ┌──────────────────────────────────────┐    │
│  │ （前 200 字预览...）                  │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  选择改进方向（可多选）：                      │
│                                               │
│  ☑ 增加真实案例                               │
│     补充 1-2 个来自实际场景的例子              │
│                                               │
│  ☐ 降低难度                                   │
│     减少理论推导，增加直觉解释和类比           │
│                                               │
│  ☐ 增加图表                                   │
│     为关键概念添加流程图/架构图                │
│                                               │
│  ☐ 增强实操指导                               │
│     补充具体操作步骤和命令示例                 │
│                                               │
│  ☐ 补充前置知识回顾                           │
│     开头增加简短的前置知识点温习               │
│                                               │
│  ☐ 增加练习/检查点                            │
│     添加更多理解和应用验证问题                 │
│                                               │
│  ── 或者自定义指令 ──                         │
│  ┌──────────────────────────────────────┐    │
│  │ （选填）更具体的修改要求...            │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  ☐ 同时重新生成测验题                         │
│  ☐ 同时重新生成讨论问题                       │
│                                               │
│            [取消]    [执行精调]               │
└──────────────────────────────────────────────┘
```

#### 改进方向选项（动态生成 + 外部信号注入）

改进选项不是固定的，而是 AI 根据**本章内容 + 质量检查结果 + 学生数据（如有）**动态生成的。

**Prompt：REFINE_OPTIONS_PROMPT**（增强版）：

```
以下是章节内容、质量检查结果和学生数据的摘要：

章节标题：{title}
课型：{chapter_type}
教学目标：{objective}
内容长度：{word_count} 字
已有图表：{diagram_count} 个
已有检查点：{checkpoint_count} 个
质量检查问题：{auto_check_issues}
Bloom 层级：{bloom_level}
学生数据（如有）：{student_effectiveness_data}

请分析内容，提出 4-6 个具体的改进方向。每个方向必须是「具体可执行的」，而非泛泛而谈。
格式：
[
  {"id": "add_cases", "label": "增加真实案例", "description": "补充1-2个来自实际场景的例子", "reason": "当前内容偏理论，缺少应用场景"},
  {"id": "lower_difficulty", "label": "降低难度", "description": "减少理论推导，增加直觉解释", "reason": "当前推导步骤较多，初学者可能跟不上"},
  ...
]

要求：
- 每个方向基于内容实际缺失的部分 + 质量检查发现的问题 + 学生数据信号
- 不要无中生有；如果内容已经很好，可以返回空数组（无需改进）
- 描述要具体，label 是面向教师的一句话标签，description 是面向 AI 的执行指令
```

#### 执行精调

教师选择改进方向后（可多选），AI 执行精调。选中的方向描述被注入 `CHAPTER_REFINEMENT_PROMPT`：

```
【教师选择的改进方向 — 必须执行】
{selected_options_descriptions}

【原内容保持】
除了上述改进方向涉及的部分，其他内容保持原样，不要重写。

原内容：
{original_content}
```

#### API 变更

```
POST /api/admin/courses/chapters/{chapter_id}/refine-options
  — 获取 AI 改进建议
  Returns: { options: [...] }

POST /api/admin/courses/chapters/{chapter_id}/refine
  — 执行精调（与现有接口兼容，增加 option_ids）
  Body: { option_ids: ["add_cases", "add_diagrams"], custom_instruction?: string }
```

### 5b. 学生反馈闭环（全自动）

#### 做什么
收集学生学习数据，识别问题内容，反馈到生成流程中优化后续课程。问题章节的改进建议也走"选择题"模式——AI 分析学习数据，生成改进选项，教师选择后执行。

#### 数据收集
- `content_effectiveness` 表：追踪每章的学习效果数据
- 指标对齐 Kirkpatrick 四级评估：
  1. **反应（Reaction）**：学生评分、完成率、跳出率
  2. **学习（Learning）**：检查点正确率、测验成绩
  3. **行为（Behavior）**：技能应用次数、返工率变化
  4. **结果（Results）**：绩效变化、合规率提升

#### 自动问题检测
- `detect_content_issues` Celery Beat 任务：自动识别问题章节
- 检测信号：低完成率、高错误率、低评分、高跳出率
- 教师在 Admin 界面看到效果报告和改进建议

### 数据变更
- `content_effectiveness` 表（迁移 `migrations/037_content_effectiveness.sql`）
- 反馈数据注入 REFINE_OPTIONS_PROMPT，形成闭环

### 变更文件
- `apps/web/src/components/RefineChapterDialog.vue` — 重写为选择题模式
- `apps/api/modules/admin/router.py` — 新增 refine-options 端点，修改 refine 端点
- `apps/api/tasks/analytics_tasks.py`（新文件）— 效果计算和问题检测

### 验收
- 对于需要改进的章节，AI 提出的选项是内容实际缺失的
- 对于已经很好的章节，AI 返回空数组
- 选中 2 个方向执行后，内容只改对应部分，其他不变
- 教师仍可通过"自定义指令"使用论述题模式（逃生舱）
- content_effectiveness 数据正确汇总，检测准确

---

## 与 v1 方案的关键差异

| 维度 | v1（7 阶段） | v2.1（5 阶段） |
|------|-------------|-------------|
| 教师交互模式 | 写论述题（填表、自定义指令） | 做选择题（从 AI 选项中选） |
| 教学策略来源 | AI 动态生成（INSTRUCTIONAL_STRATEGY_PROMPT） | 硬编码 5 套教学模板 + AI 选择课型 |
| 课程结构 | 直接聚类→章节 | Course Map 中间层确保结构合理 |
| LLM 调用次数 | 7+ 次 | 方案提案 + Course Map + 内容生成 + （可选）精调选项 + （可选）精调执行 = 3-5 次 |
| 质量检查方式 | AI 自评分数 | 9 维自动化规则检查 + 仅 critical 时触发 AI 修订 |
| 课型种类 | 不区分 | 5 种（theory/task/project/compliance/case） |
| 方案差异化 | 无 | 5 种方案维度，AI 根据材料自动选 3 |
| Bloom 动词 | 不关注 | 提案 + Course Map + 内容检查三层注入 |
| 企业材料适配 | 无 | Andragogy 锚点 + 原文依据检查 + 合规/案例课型 |
| 反馈闭环 | 无 | Kirkpatrick 四级 + 学生数据注入精调 |
| 核心创新点 | 流程完整性 | 交互模式 + 教学模板硬编码 + Course Map 校验 + 9 维质量检查 |

---

## 分阶段实施

### 第一轮（核心 — 2-3 周）
**阶段 1 + 2 + 3 + 4 完整版**

1. 阶段 1：COURSE_DESIGN_PROPOSAL_PROMPT + course_proposals 表 + 5 维方案类型
2. 阶段 2：CourseDesignView（3 卡片 + 填空 + Bloom 展示）
3. 阶段 3：COURSE_MAP_PROMPT + Course Map 生成 + 自动校验
4. 阶段 4：重写 CHAPTER_CONTENT_PROMPT（5 套教学模板）+ 9 维自动化质量检查

**交付物：** 教师上传材料 → 选方案（3 次点击）→ 自动 Course Map 校验 → AI 按 5 种课型生成结构化课程

### 第二轮（审阅体验 — 1-2 周）
**阶段 5a 完整版**

1. REFINE_OPTIONS_PROMPT（注入质量检查结果 + 学生数据）+ AI 动态生成改进选项
2. RefineChapterDialog 重写为选择题模式
3. refine 端点增加 option_ids 支持

**交付物：** 教师审阅章节时做选择题而非写指令，改进精准高效

### 第三轮（反馈闭环 — 长期迭代）
**阶段 5b**

1. content_effectiveness 表 + Kirkpatrick 四级数据收集
2. 自动问题检测 + 改进建议（选择题）
3. Admin 效果报告

**交付物：** 数据驱动的持续优化

---

## 涉及文件

| 文件 | 操作 | 轮次 |
|------|------|------|
| `apps/api/tasks/blueprint_tasks.py` | **重写** | 第一轮 |
| `apps/api/modules/skill_blueprint/router.py` | 修改 | 第一轮 |
| `apps/api/modules/skill_blueprint/schema.py` | 修改 | 第一轮 |
| `apps/api/modules/skill_blueprint/service.py` | 修改 | 第一轮 |
| `apps/api/modules/skill_blueprint/repository.py` | 修改 | 第一轮 |
| `apps/web/src/views/learner/CourseDesignView.vue` | **新建** | 第一轮 |
| `apps/web/src/components/RefineChapterDialog.vue` | **重写** | 第二轮 |
| `apps/web/src/views/tutorial/TutorialView.vue` | 修改 | 第一轮 |
| `apps/web/src/api/index.ts` | 修改 | 第一轮+第二轮 |
| `apps/web/src/router/index.ts` | 修改 | 第一轮 |
| `apps/api/main.py` | 修改 | 第一轮 |
| `apps/api/modules/admin/router.py` | 修改 | 第二轮+第三轮 |
| `apps/api/tasks/analytics_tasks.py` | **新建** | 第三轮 |
| `migrations/034_course_proposals.sql` | **新建** | 第一轮 |
| `migrations/035_blueprint_proposal_fields.sql` | **新建** | 第一轮 |
| `migrations/036_chapter_quality_checks.sql` | **更新** | 第一轮 |
| `migrations/037_content_effectiveness.sql` | **新建** | 第三轮 |
| `migrations/038_course_map.sql` | **新建** | 第一轮 |

---

## 工程挑战与对策

### 1. 教学模板的适应性
- **问题：** 硬编码 5 套模板可能不适用所有领域
- **对策：** 模板是"默认推荐"，教师可在阶段 2 的"额外要求"填空题中覆盖；后续可从阶段 5 的学习数据中优化模板

### 2. 课程方案的差异化质量
- **问题：** AI 生成的 3 套方案可能只是措辞不同，缺乏实质差异
- **对策：** Prompt 中提供 5 种差异化维度，AI 根据材料特征自动选择最合适的 3 种；阶段 5 收集教师选择偏好，优化默认方案

### 3. Course Map 生成的可靠性
- **问题：** AI 生成的 Course Map 可能不够合理，章节顺序仍为聚类
- **对策：** 自动校验规则（覆盖率、Bloom 分布、课型多样性、连贯性）捕获问题；不通过则自动重试 2 次

### 4. 生成时间
- **问题：** 增加 Course Map 步骤会增加一次 LLM 调用
- **对策：** Course Map 是一次轻量调用（仅生成结构，不含内容），总 token 消耗可控

### 5. 向后兼容
- **问题：** 已有课程没有 course_proposals、course_map、teaching_template_used
- **对策：** 新列 DEFAULT NULL；已有课程可通过"用新模板重新生成"按钮升级

### 6. 自动化检查的局限性
- **问题：** 9 维规则检查只能发现结构化问题，无法判断内容的教学质量
- **对策：** 规则检查是"安全网"（防止最差情况），教学质量依赖硬编码模板保证下限；阶段 5 的学习数据（Kirkpatrick 四级）提供真正的质量信号

### 7. 企业材料的特殊风险
- **问题：** AI 可能生成"合理但不符合公司制度"的内容
- **对策：** 原文依据检查（第 8 维）强制关联材料来源；合规课模板嵌入制度原文对比

---

## 验证方案

### 第一轮验证（核心价值验证）
1. 上传 3 个不同领域的材料（如网络安全技术文档 + 企业管理制度 + 销售案例集）
2. 检查 AI 生成的 3 套方案是否根据材料类型选择了不同的方案维度
3. 检查 Course Map 的覆盖率、Bloom 分布、课型多样性
4. 教师走完「选方案 → 点生成」流程（计时，目标 <3 分钟）
5. 生成 3 门完整课程，每门抽查 5 章——检查：
   - 是否严格按 5 种教学模板之一的结构组织
   - 知识点定义是否与原始材料一致
   - 章节之间是否有教学叙事上的递进感
   - 合规课和案例复盘课的结构是否合理
   - 9 维质量检查是否有效发现真实问题
6. 请 2-3 人对比新旧版课程的教学质量（盲评）

### 第二轮验证
1. 对不同章节调用 refine-options API，检查选项是否基于质量检查结果+内容特征
2. 选中选项执行精调，检查是否只改对应部分
3. 精调前后对比——改进应该有针对性而非全面重写

### 第三轮验证
1. content_effectiveness 数据是否正确汇总（Kirkpatrick 四级）
2. 问题检测是否准确（与人工判断对比）
3. 学生反馈数据是否被正确注入 REFINE_OPTIONS_PROMPT

---

## 附录：专家反馈与采纳情况

| 专家建议 | 采纳 | 对应修改 |
|----------|------|----------|
| 方案类型不应固定为入门/进阶/实战 | 全部采纳 | 5 种方案维度，AI 自动选 3 |
| 增加 Course Map 层 | 全部采纳 | 新增阶段 3 |
| 课型扩展到 5 种 | 全部采纳 | 新增 compliance + case 模板 |
| 质量检查太弱 | 全部采纳 | 从 4 维扩展到 9 维 |
| 注入 Bloom 层级 | 全部采纳 | 提案 + Course Map + 检查三层注入 |
| Andragogy 锚点 | 全部采纳 | 任务课/实战课模板 + 质量检查第 9 维 |
| 原文依据检查 | 全部采纳 | 质量检查第 8 维 + SOURCE 标记 |
| 定义一致性检查限定在定义段落 | 全部采纳 | 修正 extract_definition_section |
| 精调选项注入外部信号 | 全部采纳 | REFINE_OPTIONS_PROMPT 注入质量结果 + 学生数据 |
| Kirkpatrick 四级评估 | 全部采纳 | 阶段 5b 数据收集对齐 |
| AI 角色定义修正 | 全部采纳 | 更新核心设计原则 |
