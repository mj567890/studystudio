# 课程生成平台 v2.2-final — 开发执行计划

## 状态概览

| 模块 | 状态 | 说明 |
|------|------|------|
| 阶段 1：课程方案生成 | ✅ 已实现 | COURSE_DESIGN_PROPOSAL_PROMPT + 3 套方案 + 5 分钟缓存 |
| 阶段 2a：方案选择 | ✅ 已实现 | CourseDesignView.vue 3 卡片 + 4 参数填空 |
| 阶段 2b：经验校准 | ✅ 已实现 | 5 道选择题动态访谈 + API + 前端三步向导 |
| 阶段 2c：Course Map 预览 | ✅ 已实现 | 生成确认页含配置摘要 + 置信度提示 |
| 阶段 3：Course Map 生成 | ✅ 已实现 | COURSE_MAP_PROMPT + 7 项自动校验 + 路由分发 + Zero-Loss |
| 阶段 4：内容生成 | ✅ 已实现 | 4 种模板（theory/task/compliance/project）+ 章节级校准路由注入 + confidence-driven behavior |
| 阶段 4：质量检查 | ✅ 已实现 | 6 维（+原文依据 +任务闭环） |
| 阶段 5a：章节审阅 | ⏳ 第二轮 | 选择题式精调 |

**v2.2 所有核心模块已实现。** 2026-05-01 完成实施。

---

## 实施顺序（按依赖关系）

```
Task 1: 数据库迁移（3 个新 migration）
   ↓
Task 2: 后端 Prompt + 函数（5 个新 prompt/函数）
   ↓
Task 3: 后端 API 端点（3 个新/改端点）
   ↓
Task 4: 前端 API 层（TypeScript 类型 + 接口）
   ↓
Task 5: 前端 CourseDesignView（三步流程改造）
   ↓
Task 6: 后端章节生成改造（calibration routing 注入 + 6 维检查）
   ↓
Task 7: 集成测试
```

---

## Task 1：数据库迁移

### 1.1 `migrations/038_course_map.sql`

```sql
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS course_map JSONB;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS course_map_validated BOOLEAN DEFAULT FALSE;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS course_map_issues JSONB;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS calibration_routing JSONB;
```

### 1.2 `migrations/039_experience_calibration.sql`

```sql
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS experience_calibration JSONB;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS calibration_quality_issues JSONB;
ALTER TABLE skill_blueprints ADD COLUMN IF NOT EXISTS calibration_confidence_score FLOAT;
```

### 1.3 `migrations/036_chapter_quality_checks.sql`（更新已有 migration）

```sql
-- 新增字段（如果 036 已执行，单独跑这条）
ALTER TABLE skill_chapters ADD COLUMN IF NOT EXISTS teaching_template_used VARCHAR(30);
ALTER TABLE skill_chapters ADD COLUMN IF NOT EXISTS auto_check_issues JSONB;
ALTER TABLE skill_chapters ADD COLUMN IF NOT EXISTS auto_check_passed BOOLEAN DEFAULT FALSE;
ALTER TABLE skill_chapters ADD COLUMN IF NOT EXISTS source_citation_count INTEGER DEFAULT 0;
```

---

## Task 2：后端新增 Prompt 和函数

### 2.1 新增文件或追加到 `blueprint_tasks.py`

| 函数/Prompt | 用途 | 行数估算 |
|-------------|------|----------|
| `COMPLIANCE_TEMPLATE` | 合规课硬编码模板（8 段） | ~25 行 |
| `EXPERIENCE_CALIBRATION_PROMPT` | 生成 5 道动态选择题 | ~60 行 |
| `generate_calibration_questions()` | 调用 LLM 生成校准题 | ~40 行 |
| `validate_calibration_questions()` | 5 条自动质检规则 | ~35 行 |
| `COURSE_MAP_PROMPT` | 生成课程地图+路由分发 | ~70 行 |
| `generate_course_map()` | 调用 LLM 生成 Course Map | ~50 行 |
| `validate_course_map()` | 7 项校验（含 Zero-Loss） | ~50 行 |
| `validate_calibration_coverage()` | 路由完整性检查 | ~35 行 |

### 2.2 修改已有函数

| 函数 | 修改内容 |
|------|----------|
| `TEACHING_TEMPLATES` 字典 | 增加 `"compliance": COMPLIANCE_TEMPLATE` |
| `_build_chapter_prompt()` | 支持 `chapter_calibration` 参数和 `confidence_score` 注入 |
| `CHAPTER_CONTENT_PROMPT` | 全局经验校准替换为章节级 `{chapter_calibration}` + confidence-driven behavior |
| `validate_chapter_content()` | 从 4 维扩展到 6 维（+原文依据检查 +任务闭环检查） |
| `_synthesize_blueprint_v2_async()` | 生成前先调用 `generate_course_map()`，获取 `calibration_routing`，内容生成时传入章节级校准数据 |
| `generate_course_proposals()` | 更新 prompt 中的方案维度为 5 种（当前固定为入门/进阶/实战） |

---

## Task 3：后端 API 端点

### 3.1 `apps/api/modules/skill_blueprint/router.py`

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/blueprints/{topic_key}/calibration-questions` | POST | **新增**：生成 5 道经验校准题 |
| `/api/blueprints/{topic_key}/start-generation` | POST | **修改**：接收 `calibration_answers` 和 `course_map_confirmed` |
| `/api/blueprints/{topic_key}/course-map` | GET | **新增**：获取 Course Map 预览 |
| `/api/blueprints/{topic_key}/course-map/regenerate` | POST | **新增**：重新规划 Course Map（含原因） |

### 3.2 `apps/api/modules/skill_blueprint/schema.py`

```python
class CalibrationAnswers(BaseModel):
    answers: dict  # {q1_pain_points: [...], q2_cases: "...", ...}

class StartGenerationRequest(BaseModel):  # 扩展已有
    space_id: str
    selected_proposal_id: str
    adjustments: Optional[dict] = None
    extra_notes: Optional[str] = None
    calibration_answers: Optional[dict] = None  # 新增
    course_map_confirmed: bool = False  # 新增

class CourseMapRegenerateRequest(BaseModel):
    reason: str  # "order" | "granularity" | "priority" | "mark_mode" | "not_sure"
    marked_chapters: Optional[dict] = None  # mark_mode 时使用
```

---

## Task 4：前端 API 层

### 4.1 `apps/web/src/api/index.ts`

新增 TypeScript 类型：

```typescript
interface CalibrationQuestion {
  id: string
  type: 'multi_select' | 'single_select' | 'ranking'
  title: string
  options: CalibrationOption[]
  why_ask: string
  skip_option: string
}

interface CalibrationOption {
  id: string
  label: string
  entity_id?: string
}

interface CourseMapChapter {
  order: number
  title: string
  chapter_type: 'theory' | 'task' | 'compliance'
  bloom_level: string
  learning_objectives: Array<{ verb: string; object: string; bloom_level: string }>
  estimated_minutes: number
  calibration_routing: {
    pain_points: string[]
    cases: Array<{ case_id: string; facet: string; usage: string }>
    misconceptions: string[]
    red_lines: string[]
  }
}

interface CourseMapData {
  course_title: string
  overall_narrative: string
  bloom_progression: { early: string; late: string }
  chapters: CourseMapChapter[]
  coverage_check: { total_entities: number; covered_entities: number; coverage_rate: number }
  bloom_distribution: Record<string, string>
  calibration_coverage: { total_items: number; routed_items: number; missing: string[] }
}
```

新增 API 方法：

```typescript
blueprintApi: {
  // ... 已有方法
  getCalibrationQuestions(topic: string, data: { space_id: string; selected_proposal_id: string; adjustments: any }): Promise<{ questions: CalibrationQuestion[] }>
  submitCalibration(topic: string, data: { space_id: string; answers: any }): Promise<{ calibration: any; confidence_score: number }>
  getCourseMap(topic: string): Promise<CourseMapData>
  regenerateCourseMap(topic: string, data: { reason: string; marked_chapters?: any }): Promise<CourseMapData>
}
```

---

## Task 5：前端 CourseDesignView 改造

### 5.1 从单页改为三步流程

**文件**：`apps/web/src/views/learner/CourseDesignView.vue`

使用步骤条（`el-steps`）组织：

```
Step 1/3: 选择方案（已有，保留）
  → 教师选 A/B/C，填 4 个参数，点"下一步"

Step 2/3: 经验校准（新增）
  → 5 道选择题，左侧实时摘要卡
  → 进度条 "3 分钟搞定"
  → 每题都有"不清楚"选项
  → 完成后点"下一步"

Step 3/3: 课程地图预览（新增）
  → 大纲树展示（每章：标题 + 课型标签 + Bloom 渐变 + 目标）
  → 覆盖率 + Bloom 分布
  → 经验校准置信度提示
  → [重新规划] / [确认生成]
```

### 5.2 状态管理

```typescript
const step = ref(1)
const calibrationQuestions = ref<CalibrationQuestion[]>([])
const calibrationAnswers = ref<Record<string, any>>({})
const confidenceScore = ref(0)
const courseMap = ref<CourseMapData | null>(null)
const courseMapConfirmed = ref(false)
```

---

## Task 6：后端章节生成改造

### 6.1 `_synthesize_blueprint_v2_async` 流程更新

```
当前流程:
  embedding 聚类 → 命名章节 → _gen_content() 生成内容

新流程:
  embedding 聚类 → 命名章节
    → generate_course_map()（含 calibration_routing）
    → validate_course_map()（7 项校验，含 Zero-Loss）
    → _gen_content()（使用章节级 calibration，非全局）
```

### 6.2 `_gen_content()` 修改

- 从 Course Map 的 `calibration_routing` 中提取本章的校准数据
- `_build_chapter_prompt()` 接收 `chapter_calibration` 参数
- 注入 `confidence_score` 驱动保守/正常生成模式

### 6.3 `validate_chapter_content()` 扩展

```python
# 新增 2 维（已有 4 维基础上）：
# 5. 原文依据检查
if chapter_type in ('compliance', 'task'):
    if '<!--SOURCE:' not in content['full_content']:
        issues.append("缺少原文依据标记")

# 6. 任务闭环检查
if chapter_type == 'task':
    for s in ['[场景]', '[分解演示]', '[关键细节]', '[变式练习]', '[检查点]']:
        if s not in content['full_content']:
            issues.append(f"任务闭环不完整: 缺失 {s}")
```

---

## Task 7：集成验证

### 验证清单

| # | 验证项 | 方法 |
|---|--------|------|
| 1 | 5 种方案维度是否根据材料类型自动选择 | 上传制度类+技术类材料，对比方案差异 |
| 2 | 5 道校准题候选项是否"需要真实经验才能选" | 人工判读每题至少 2 个选项让人犹豫 |
| 3 | confidence_score 计算是否正确 | 全选"不清楚"→ 0.2；全答 → 1.0 |
| 4 | Zero-Loss Check 是否捕获路由遗漏 | 人工从 calibration JSON 删一项，检查能否检测 |
| 5 | 低置信度时 AI 是否进入保守模式 | 检查 prompt 中是否出现"据该企业经验"等表述 |
| 6 | 同一案例在多章是否使用不同 facet | 检查 2 章引同一案例时的文字差异 |
| 7 | 6 维质量检查是否生效 | 故意制造缺失 SOURCE 标记的内容 |
| 8 | 完整流程：上传→选方案→校准→CM预览→生成 | 端到端计时，目标 <8 分钟 |

---

## 文件变更汇总

| 文件 | 操作 | 行数变化 |
|------|------|----------|
| `apps/api/tasks/blueprint_tasks.py` | **重写**（+450 行） | 当前 ~3000 行 → ~3450 行 |
| `apps/api/modules/skill_blueprint/router.py` | **修改**（+3 端点） | +80 行 |
| `apps/api/modules/skill_blueprint/schema.py` | **修改**（+3 类） | +30 行 |
| `apps/web/src/views/learner/CourseDesignView.vue` | **重写**（三步流程） | 当前 ~350 行 → ~650 行 |
| `apps/web/src/api/index.ts` | **修改**（+8 类型 +4 方法） | +80 行 |
| `migrations/038_course_map.sql` | **新建** | 4 列 |
| `migrations/039_experience_calibration.sql` | **新建** | 3 列 |
| `migrations/036_chapter_quality_checks.sql` | 已存在，可能需要补充 ALTER | — |

---

## 预计工时

| Task | 预估 | 依赖 |
|------|------|------|
| Task 1: Migration | 0.5h | — |
| Task 2: Prompt + 函数 | 6h | Task 1 |
| Task 3: API 端点 | 3h | Task 2 |
| Task 4: 前端 API 层 | 1.5h | Task 3 |
| Task 5: 前端 CourseDesignView | 6h | Task 4 |
| Task 6: 章节生成改造 | 4h | Task 2 |
| Task 7: 集成测试 | 3h | Task 5+6 |
| **合计** | **24h（3 个工作日）** | |

---

## 核心验证指标

> **教师经验是否被正确路由、正确使用，并且明显提升课程真实感与可学性。**

验收方式：盲评 v2 旧版课程 vs v2.2 新版课程，重点看：
1. 教师勾选的真痛点是否在新版课程对应章节中获得更多笔墨
2. 教师选中的真实案例是否被合理嵌入（不重复、不过度）
3. 教师划的红线是否在合规课中构成醒目的"一句话红线"
4. 学生是否能感受到"这门课讲的是真东西"而非"AI 编的通用教材"

---

## 实施完成记录（2026-05-01）

### 变更文件统计

| 文件 | 操作 | 变更 |
|------|------|------|
| `apps/api/tasks/blueprint_tasks.py` | 修改 | 3102 → 4053 行（+951） |
| `apps/api/modules/skill_blueprint/router.py` | 修改 | 208 → 369 行（+161） |
| `apps/api/modules/skill_blueprint/schema.py` | 修改 | 67 → 84 行（+17） |
| `apps/web/src/api/index.ts` | 修改 | +80 行（类型 + API 方法） |
| `apps/web/src/views/learner/CourseDesignView.vue` | 重写 | 348 → 633 行（+285） |
| `migrations/038_course_map.sql` | 新建 | 已执行 |
| `migrations/039_experience_calibration.sql` | 新建 | 已执行 |

### 关键架构决策落地

| 决策 | 实现位置 |
|------|----------|
| **路由分发（防 Context Bleed）** | `generate_course_map()` → Course Map `calibration_routing` → `_gen_content()` 只收章节级数据 |
| **Zero-Loss Check** | `validate_calibration_coverage()` — Course Map 校验第 7 项 |
| **confidence_score + 保守模式** | `CHAPTER_CONTENT_PROMPT` 中 confidence-driven behavior（<0.4 不编造案例） |
| **Case facet 分配** | `calibration_routing.cases[].facet` 字段（scenario/consequence/analysis/transfer） |
| **6 维质量检查** | `validate_chapter_content()` — +原文依据检查 +任务闭环检查 |
| **三步向导** | `CourseDesignView.vue` — el-steps + 经验校准题 + 置信度摘要 |
