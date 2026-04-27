# StudyStudio 测试体系文档

**生成日期：** 2026-04-27
**测试总数：** 144（全部通过）

---

## 一、测试结构

```
tests/
├── unit/
│   ├── test_core_modules.py      # 核心模块单元测试（35）
│   └── test_auth_security.py     # 认证/安全单元测试（43）
└── integration/
    ├── test_main_pipeline.py     # 主链路集成测试（11）
    └── test_document_pipeline.py # 文档管线集成测试（46）
```

---

## 二、各测试套件详情

### 2.1 核心模块单元测试（35 tests）

**文件：** `tests/unit/test_core_modules.py`

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| `TestEnums` | 4 | 枚举值/CERTAINTY映射/PLACEMENT排序/GapType |
| `TestNormalizeRrfScore` | 5 | RRF归一化（零值/负值/最大值/边界截断） |
| `TestTopologicalSortSafe` | 6 | 拓扑排序（线性链/无依赖/环检测/全量返回/字符串操作） |
| `TestPathStep` | 3 | 依赖深度默认值/序列化/按深度排序 |
| `TestClassifyQueryComplexity` | 6 | 查询复杂度分类（simple/complex/首轮/长消息/多问/关键词） |
| `TestExtractEntityRefs` | 6 | 实体引用提取（已知/未知/UUID/空内容/空白trim） |
| `TestMasteryDecay` | 5 | 掌握度衰减（零天/一周/下限/衰减率/负天数） |
| `TestVectorUtils` | 4 | 余弦相似度/编辑距离 |

### 2.2 认证/安全单元测试（43 tests）

**文件：** `tests/unit/test_auth_security.py`

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| `TestPasswordHashing` | 5 | bcrypt哈希/验证/错误密码/格式/Unicode |
| `TestPasswordTruncation` | 5 | bcrypt 72字节截断（短/等/超/多字节/截断兼容） |
| `TestJWT` | 5 | 签发/解码/过期/无效令牌/空令牌 |
| `TestNormalizeUUID` | 4 | 有效UUID/无效/SQL注入拒绝/UUID对象 |
| `TestPasswordStrength` | 8 | 强密码/太短/单类型/双类型/三类型/常见拒绝/全部常见/边界 |
| `TestRateLimiter` | 8 | 滑动窗口（首允许/限额内/超限/独立key/重置/无记录/清理/过期） |
| `TestRequireRole` | 5 | RBAC（admin通过/learner拒绝/多角色/空角色/无角色键） |
| `TestJWTSecretValidation` | 3 | JWT密钥验证（dev容错/production强制/缓存） |

### 2.3 主链路集成测试（11 tests）

**文件：** `tests/integration/test_main_pipeline.py`

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| `TestRepairPathTruncation` | 3 | 补洞路径截断（超限/未超限/低深度优先） |
| `TestConfidenceCalculation` | 3 | 置信度计算（高确定性/低确定性/范围[0,1]） |
| `TestPlacementScoreMapping` | 3 | 冷启动分数（四组合/排序/最小正值） |
| `TestDiagnosisMerge` | 2 | 乐观锁合并（小差异并集/大差异取高） |

### 2.4 文档管线集成测试（46 tests）

**文件：** `tests/integration/test_document_pipeline.py`

| 测试类 | 测试数 | 覆盖内容 |
|--------|--------|---------|
| `TestDocumentStateMachine` | 7 | 八状态正向流转/失败转换/重试/终态/提取锁/过渡态 |
| `TestExtractionLock` | 2 | 原子锁rowcount防御/可锁定状态范围 |
| `TestEmbeddingCompletion` | 2 | embedding完成→reviewed提升/未完成保持 |
| `TestBuildEmbedText` | 5 | 文本构造（含定义/无定义/空/截断512/trim） |
| `TestKnowledgeExtractionFlow` | 9 | JSON解析/修复非法转义/实体归一化（字符串/字典/非list）/分类回退 |
| `TestAutoReviewFlow` | 4 | JSON数组解析/fence包裹/无效回退/pending恢复逻辑 |
| `TestBlueprintSynthesis` | 8 | CVE/CVE编号过滤/GHSA/版本号/端口号/正常实体不误杀/⏸清除/fence转换/非JSON降级 |
| `TestEndToEndPipeline` | 3 | 六阶段顺序/触发链/状态流转完整性 |
| `TestErrorRecovery` | 5 | 全状态可失败/重试/锁安全/celery retry枯竭/published跳过 |
| `TestDocumentIngestLimits` | 3 | Chunk截断500/文件大小100MB/批处理50 |

---

## 三、测试覆盖矩阵

```
功能域                    │ 单元测试 │ 集成测试 │ 合计
─────────────────────────────────────────────────
枚举与常量                │     4    │    3    │   7
RRF归一化                 │     5    │    -    │   5
拓扑排序                  │     6    │    -    │   6
PathStep                 │     3    │    -    │   3
查询复杂度分类            │     6    │    -    │   6
实体引用提取              │     6    │    -    │   6
掌握度衰减                │     5    │    -    │   5
向量工具                  │     4    │    -    │   4
─────────────────────────────────────────────────
密码哈希与验证            │     5    │    -    │   5
72字节截断                │     5    │    -    │   5
JWT签发/解码/过期         │     5    │    -    │   5
UUID规范化/防注入         │     4    │    -    │   4
密码强度校验              │     8    │    -    │   8
IP速率限制                │     8    │    -    │   8
RBAC权限检查              │     5    │    -    │   5
JWT密钥配置验证           │     3    │    -    │   3
─────────────────────────────────────────────────
补洞路径截断              │     -    │    3    │   3
置信度计算                │     -    │    3    │   3
冷启动分数映射            │     -    │    3    │   3
诊断合并                  │     -    │    2    │   2
─────────────────────────────────────────────────
文档状态机                │     -    │    7    │   7
提取锁机制                │     -    │    2    │   2
Embedding→状态提升        │     -    │    2    │   2
Embedding文本构造         │     -    │    5    │   5
知识提取管线              │     -    │    9    │   9
自动审核管线              │     -    │    4    │   4
蓝图合成管线              │     -    │    8    │   8
端到端流程                │     -    │    3    │   3
错误恢复路径              │     -    │    5    │   5
文档解析参数              │     -    │    3    │   3
─────────────────────────────────────────────────
总计                      │    87     │   57    │ 144
```

---

## 四、运行方式

```bash
# 全量运行
python -m pytest tests/ -v

# 单元测试
python -m pytest tests/unit/ -v

# 集成测试
python -m pytest tests/integration/ -v

# 按关键词筛选
python -m pytest tests/ -v -k "state_machine or extraction"

# 含覆盖率报告
python -m pytest tests/ -v --cov=apps/api --cov-report=term-missing
```

---

## 五、测试设计原则

### 5.1 单元测试

- **纯函数优先：** 所有测试对象无外部依赖（DB/网络/文件系统）
- **边界全覆盖：** 零值、负值、极大值、空值、None
- **中文原生支持：** SQL注入/密码测试使用中文输入，验证非ASCII路径
- **安全优先：** SQL注入防护/UUID验证/速率限制/RBAC 均在单元层面验证

### 5.2 集成测试

- **Mock DB 交互：** 使用 `AsyncMock(spec=AsyncSession)` 模拟数据库调用
- **真实函数调用：** 不 mock 被测函数本身，验证实际管线逻辑
- **状态机完整性：** 穷举所有状态转换路径，含失败恢复
- **管线全链路：** 从 uploaded 到 published 的六阶段正向流转 + 错误路径

### 5.3 已知局限

| 局限 | 原因 | 缓解 |
|------|------|------|
| 不使用真实 PostgreSQL | 需要 pgvector 扩展，测试环境不可用 | mock DB 层验证 SQL 查询结构 |
| 不启动 Celery workers | 需要 RabbitMQ/Redis 基础设施 | 对纯函数和编排逻辑直接测试 |
| 不调用真实 LLM | 需要 API Key + 网络 | LLM 调用处均有超时/重试/失败保护 |

---

*文档版本：v1.0*
*生成时间：2026-04-27*
*下次更新触发：新增测试套件或重大测试重构*
