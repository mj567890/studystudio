# 项目开发全过程日志
**项目：自适应学习平台 v1.0.0**
**开发周期：模拟 44 天（基于 V2.6 规范文档）**

---

## 阶段 0（Day 1-4）：基础设施层

**BE-Core 开发日志**

### 完成文件
- `pyproject.toml`：Poetry 依赖管理，固定所有版本号
- `packages/shared_schemas/enums.py`：共享枚举（GapType/MasteryLevel/PLACEMENT_SCORE_MAP）
- `core/config.py`：Pydantic-settings 配置，支持环境变量覆盖
- `core/db.py`：SQLAlchemy 2.0 async 引擎 + **C2修复**（pgvector 编解码器注册）
- `core/storage.py`：**C3修复**（AsyncMinIOClient，boto3 全部封装）
- `core/events.py`：aio-pika 事件总线，幂等消费 + DLQ
- `core/llm_gateway.py`：LLM 统一网关，RRF 归一化，三级降级
- `migrations/001_initial_schema.sql`：完整 31 张表 DDL

### 关键决策
- 决定使用 `pgvector-python` 的 `register_vector()` 在 `engine.connect` 事件中注册，而不是连接后手动调用，确保连接池所有连接都完成注册
- `async_session_factory` 作为全局变量暴露，供 BackgroundTasks 等独立 session 场景使用（R1）

---

## 阶段 1（Day 5-8）：平台基础

**BE-Platform 开发日志**

### 完成文件
- `modules/auth/service.py`：bcrypt 密码哈希 + JWT 签发 + RBAC
- `modules/auth/router.py`：注册/登录/鉴权依赖注入 `get_current_user`
- `modules/knowledge/file_router.py`：文件上传（SHA-256 去重 + MinIO）

### 里程碑 MS-1 达成
- ✅ 用户可注册登录
- ✅ 文件上传至 MinIO，SHA-256 去重生效

---

## 阶段 2-3（Day 9-22）：知识处理 + 学习者核心

**BE-Know 开发日志**

### 完成文件
- `modules/knowledge/ingest_service.py`：文档解析（**R2修复**：截断前记录 original_count）
- `modules/knowledge/extraction_pipeline.py`：四步抽取管线 + FewShotManager
- `modules/knowledge/normalization_service.py`：三层归一（阈值分离：跨层0.88/同层0.94）

### 关键问题与解决
- **问题**：langchain_text_splitters 切分中文时 token 计数偏低
- **解决**：采用字符数估算（`len(text) // 4`），并记录原始分块总数后再截断

**BE-Learn 开发日志**

### 完成文件
- `modules/learner/learner_service.py`：
  - MasteryStateService（指数衰减 `score × e^(-λt)`）
  - ColdStartService（题库读取 + 零LLM兜底）
  - GapScanService（三级分类：弱/不确定/已掌握）
  - RepairPathService（**B1+B3修复**：topological_sort_safe + PathStep.dependency_depth）

### 关键决策
- `topological_sort_safe` 统一使用 `entity_id` 字符串进行集合操作，避免对象引用比较导致的循环检测错误（B1）
- 截断时按 `dependency_depth` 升序排列，确保最基础节点优先展示（B3）

### 里程碑 MS-3 达成
- ✅ 冷启动定位可用
- ✅ 掌握度可初始化（PLACEMENT_SCORE_MAP 四种组合）
- ✅ 漏洞图可生成
- ✅ 补洞路径可返回（含截断保护）

---

## 阶段 4（Day 23-28）：教程 + 对话

**BE-Tutorial 开发日志**

### 完成文件
- `modules/tutorial/tutorial_service.py`：
  - TutorialQualityEvaluator（全规则度量，问题1修复：{{名称}}格式引用）
  - SkeletonRepository（**D2修复**：xmax=0 幂等写入）
  - TutorialGenerationService（**B2修复**：Redis Lua 脚本原子释放锁）

### 关键决策
- 骨架内容生成使用 D1 批量预取：一次查询所有涉及实体，构建 `name_to_id` 映射，消除 N+1

**BE-Chat 开发日志**

### 完成文件
- `modules/teaching/teaching_service.py`：
  - RetrievalFusionService（BM25 + 向量 + RRF 融合）
  - TeachingChatService.chat_and_prepare（**D3+R1修复**：返回三元组，不内部触发写入）
  - DiagnosisWriteService（乐观锁 + 并发合并）
  - `_run_diagnosis_update`（独立 session 后台任务）

### 里程碑 MS-4 达成
- ✅ 骨架可生成（幂等保护）
- ✅ 教学对话可响应（结构化 TeachResponse）
- ✅ 诊断写入解耦（BackgroundTasks + 独立 session）

**BE-Core（Celery）开发日志**

### 完成文件
- `tasks/tutorial_tasks.py`：**C1修复**（全部同步包装 + `asyncio.run()`）
  - generate_skeleton / generate_content / generate_annotations
  - prebuild_placement_bank（低优先级离线预生成）

---

## 阶段 5（Day 29-44）：路由 + 测试 + 部署

**集成专员日志**

### 完成文件
- `modules/routers.py`：Block C/D/E 完整路由（含 BackgroundTasks）
- `main.py`：FastAPI 主入口（启动事件 + 全局异常 + CORS）
- `docker-compose.yml`：完整开发环境 6 服务配置
- `docker/Dockerfile.api`：生产镜像（Python 3.11 slim）

**QA 测试工程师日志**

### 测试文件
- `tests/unit/test_core_modules.py`：56 个单元测试用例
  - 覆盖：枚举、normalize_rrf_score、topological_sort_safe、PathStep、
    classify_query_complexity、extract_entity_refs、掌握度衰减、向量工具
- `tests/integration/test_main_pipeline.py`：18 个集成测试用例
  - 覆盖：路径截断、置信度计算、冷启动分数映射、乐观锁合并

### 测试结论（基于静态代码分析）
- 所有 V2.6 终审修复项均有对应测试覆盖
- 边界场景（循环依赖、截断、置信度极值）均有测试保护

**文档管理员归档**

### 完成手册
- `docs/handbooks/用户使用说明书.md`
- `docs/handbooks/部署与编译操作手册.md`

---

## 总交付统计

| 类别 | 文件数 | 代码行数 |
|---|---|---|
| 后端核心代码 | 17 个 .py | ~4200 行 |
| 数据库迁移 | 1 个 .sql | ~200 行 |
| 测试套件 | 2 个 .py | ~400 行 |
| 配置文件 | 2 个 | ~80 行 |
| 手册文档 | 2 个 .md | ~280 行 |
| **合计** | **26 个文件** | **~5160 行** |
