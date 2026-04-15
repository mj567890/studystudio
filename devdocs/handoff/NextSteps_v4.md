# StudyStudio 后续开发计划

**生成日期**：2026-04-14（Phase 2 会话 2 完成后）
**上一版**：`StudyStudio_NextSteps_20260414_v3.md`
**对应快照**：`StudyStudio_Snapshot_20260413_233256.txt`（已过期，`blueprint_tasks.py` / `ai_capability_bindings` 均已变更，会话 3 开场建议重生成）
**同会话配套产物**：无新文档，所有修改均在代码与 DB 中

---

## §1 当前项目状态（截至 2026-04-14 Phase 2 会话 2 完成）

### §1.1 会话 2 实际做的事

计划中的三件（来自 v3 §2）：
1. 对 `websecret` space 跑一次 V2，验证泛化性
2. 在前端体验 `网络安全` 教程，评估质量
3. 根据体验决定是否调参

实际完成：
- ✅ 任务 1：websecret V2 跑通，13:30 耗时，38 章，10 stage，version 10 → 11
- ✅ 任务 2：网络安全 space 前端体验评估（4 维度评分 + 2 张截图）+ websecret 从 DB 推论评估
- ⬜ 任务 3：调参未动手，问题清单交接到会话 3
- ➕ **计划外**：定位并修复了一个遗留的 LLMGateway event loop bug（v3 §4 当时的"修复"是假修，只是撞大运让网络安全 space 通过）

### §1.2 LLMGateway Loop Bug — 根因与修复

**症状**：第二次触发 V2 时报 `attached to a different loop`，任务卡死；worker 重启后任务被 redeliver 再卡，形成死循环。

**根因**：
- `LLMGateway.__init__` 里 `self._lock = asyncio.Lock()` 在单例首次创建时绑定到创建时的 event loop
- celery prefork worker 每次 task 都 `asyncio.run()` 新建 loop，但单例的 Lock 仍绑旧 loop
- `async with self._lock` 在新 loop 里立刻炸
- v3 §4 那次「顺序调用替代 gather」的修复不碰 Lock 本身，只是掩盖了并发场景下的复现面

**为何网络安全 space 当时能过**：会话 1 是 worker 启动后第一个调 LLM 的任务，Lock 绑定 loop 就是当前 loop。

**修复**：`apps/api/tasks/blueprint_tasks.py` 的 `synthesize_blueprint` 入口在 `asyncio.run` 之前强制重置单例：
```python
import apps.api.core.llm_gateway as _gw_mod
_gw_mod._llm_gateway = None
```
每次 task 都会在新 loop 内重建 Gateway → 新 Lock 绑新 loop → 新 AsyncOpenAI client → 新 DB session。

**验证**：websecret 跑完 13:30 共 ~77 次 DeepSeek 调用，3 次 `LLMGateway routes loaded`（TTL 60s 被动重载），零 loop 错误，task SUCCESS。

**备份**：`apps/api/tasks/blueprint_tasks.py.bak.pre_gwfix`（修复前版本）。

### §1.3 当前生效的数据规模

```
approved entities:
  - 网络安全   228 条（global space）
  - websecret  268 条（personal space）
  - 301灯光    174 条（personal space）
  合计 670（v3 说 496，中间 301灯光 加入了）
embedding 覆盖率：100%

已发布蓝图：
  - 网络安全  V2 生成，v6，24 章，170 实体（过滤 58）
              标题："现代软件安全攻防与漏洞分析实战"
  - websecret V2 生成，v11，38 章，267 实体（过滤 1）
              标题："AI安全与对抗防御实战"
              blueprint_id: 840b9aba-6afa-44ae-8250-2b125c5ab428
  - 301灯光   V1 生成，v1 published（未触碰）
```

### §1.4 相对 v3 的代码/DB 变更清单

| 项 | v3 状态 | v4 状态 |
|---|---|---|
| `apps/api/tasks/blueprint_tasks.py` | V2 重写完（599 行） | + 3 行 gateway reset（line 147-149） |
| `apps/api/tasks/blueprint_tasks.py.bak.pre_gwfix` | 无 | **新增**，v3 版本备份 |
| `apps/api/core/llm_gateway.py` | Lock 单例 bug 未修 | 未改（通过 task 入口重置单例绕过） |
| DB: `skill_blueprints` | 网络安全 v6 / websecret v10 | 网络安全 v6 / websecret **v11** |
| DB: `skill_chapters` (websecret) | V1 旧数据 | V2 新数据 38 章 |

---

## §2 下一步（Phase 2 会话 3）

### §2.1 首要任务（按严重性，P0 必须修）

**P0 — 标题重复 + 内容污染（websecret 独有）**

事实：
- websecret 有 1 对章节标题完全相同（stg 2 ch6 和 ch7 都叫「掌握ATLAS框架核心攻击战术」）
- `content_text` 的 md5 也相同 → **ch7 的正文实际是 ch6 的内容**
- ch6 挂 18 个实体，ch7 挂 7 个实体，但正文只讲 ch6 的东西 → 学生在 ch7 看到的内容和它该讲的 7 个实体对不上
- 另有 1 对「区分主流大型语言模型」/「区分主流大语言模型」是**仅标题几乎相同**，内容各自独立，没污染

根因：
- `CLUSTER_CHAPTER_PROMPT` 每簇独立命名，LLM 没有全局视角，两个语义接近的簇可能生成相同/极近标题
- `chapter_contents: dict[str, str]` 用 title 作为 key（blueprint_tasks.py line 491 附近），同名章节后写的覆盖先写的，DB 写入时两章读取同一个 title → 共享内容

修法（两处都要改）：
1. 把 `chapter_contents` 的 key 从 `title` 改成 `cluster_id` 或直接挂在 `cluster_chapters[i]` 对象里（无碰撞风险）
2. 簇命名后加一轮「全局去重」LLM 调用：把所有候选标题扔给 LLM 做一次 "请给出 N 个语义互不重叠的最终标题"；或更简单，检测到 Jaccard 相似度 > 阈值就强制让 LLM 重命名冲突的那一章

会话 3 开场建议：先修 `dict[title]` 这个 key 碰撞（2-3 行），然后重跑 websecret 看是否还有同名。如果还有，再加全局去重轮。

**P1 — stage 分组是字符序 + stage_type 硬编码错贴（两个 space 都复现）**

事实：
- `cluster_chapters.sort(key=lambda c: c["meta"]["title"])` —— line 476，按中文标题 unicode 序
- 导致 stage 1 全是"分/区"开头的章节（入门度未知），中间全是"理/解/识"，最后是"辨/选"
- 网络安全 space：Stage 1 讲 CVE 漏洞利用链（最难），Stage 2 讲「什么是 Burp Suite」（入门），**完全倒序**
- `stage_type` 硬编码：第一个 = foundation，最后一个 = assessment，中间全 practice — 和实际内容毫无关系

修法：
- 章节内容生成完毕后，加一轮 LLM 调用做「stage 规划」：把 N 个章节标题扔给 LLM，让它产出 `[{"stage_title": "...", "stage_type": "foundation|practice|...", "chapter_indices": [...]}]`
- 或更保守：按实体 embedding 离「基础/入门」锚点的平均距离做排序代理，字符序完全丢掉
- **LLM 方案更稳**，推荐

**P2 — 章节标题动词扎堆（两个 space 都复现，websecret 更严重）**

事实：
- 网络安全：识别 × 9（38%），理解 × 6
- websecret：理解 × 14（37%），识别 × 10（26%），**63% 的章节以理解/识别开头**

根因：`CLUSTER_CHAPTER_PROMPT` 无全局多样性约束，每簇独立命名必然收敛到几个"安全动词"

修法（推荐和 P1 合并）：
- P1 的"stage 规划"那一轮 LLM 顺便做全局 re-title，把 38 个章节标题一次性给它重写，附要求"动词多样、避免重复"
- 一次 LLM 调用解决 P1 + P2

**P3 — 簇大小极不均（两个 space 都复现）**

事实：
- 网络安全：未看，但章节-实体数分布应查
- websecret：2 ~ 18 实体，**8 章 ≥10（超载），15 章 ≤4（太小）**
- 最大簇 `掌握ATLAS框架核心攻击战术` 18 实体，是最小簇的 9 倍
- KMeans 无簇大小约束

修法（按工作量从小到大）：
- A. KMeans 后做后处理：超过 `MAX_PER_CHAPTER=12` 的簇用子聚类拆，小于 `MIN_PER_CHAPTER=3` 的簇合并到最近邻簇
- B. 换算法：Agglomerative Clustering 带 distance threshold 的方式更自然（天然产出不均匀簇，但能控最大距离）
- C. 每簇 re-cluster：用 constrained KMeans 或 balanced k-means 第三方库

会话 3 推荐 A（后处理最小改动，2 小时内可做）

**P4 — 杂烩簇（网络安全独有）**

事实：
- 网络安全 space 有一章「区分主流云服务与开发工具」，簇里的实体是 Azure / GCP / GA4 / Chrome / GPG —— 五个完全不相关的东西
- LLM 自己都知道不相关，场景框直接写"面对这些名词感到困惑"
- 根因：KMeans 硬分 K 簇把所有"语义孤立实体"塞进同一个杂烩桶
- websecret 主题集中度高，没出现

修法：
- P3 解决后大概率好转（小簇被合并到最近邻）
- 更彻底：聚类后加「簇内一致性检查」，簇内实体两两余弦距离 > 阈值则标记为"建议人工审核"，不自动成章
- 会话 3 先做 P3，观察 P4 是否还存在再决定

**P5 — V2 过滤规则对 websecret 失效**

事实：websecret 268 实体只过滤 1 条（CVE），网络安全 58/228 过滤。原因：websecret 主题是 AI 安全，实体都是概念/框架名，CVE/版本号/产品名很少

结论：**不用修**。过滤规则的目的是"剔除非教学实体"，websecret 的实体确实大多是教学性的，这是正确行为。v3 §2.1 里担心的"过滤规则需要补充"事实上不需要。

### §2.2 后续任务

- 删除 V1 补偿代码（v3 §3 的 D1-D5）— **推迟到 P0-P3 修完后**
- 迁移 TutorialQualityEvaluator 到 V2 路径
- 生成新 Snapshot 覆盖 blueprint_tasks.py 和 LLMGateway 相关变更

### §2.3 会话 3 开场清单（推荐执行顺序）

1. 读 v4（本文件）对齐事实
2. 修 P0 `dict[title]` key 碰撞（2-3 行改动）
3. 重跑 websecret V2，确认标题重复和内容污染都消失
4. 实现 P1 + P2 合并修法（加一轮 LLM 做 stage 规划 + re-title）
5. 实现 P3 簇大小后处理（MIN/MAX 约束）
6. 重跑两个 space，对比 v11 / v12 质量
7. 前端再次体验评估，确认是否达到可用
8. 如果达到可用 → 写 v5 + 删 V1

---

## §3 Phase 2 要删的代码（继承 v3，未执行）

| 编号 | 代码位置 | 内容 | 状态 |
|---|---|---|---|
| D1 | blueprint_tasks.py BLUEPRINT_SYNTHESIS_PROMPT | 硬编码章节数公式 | V1 使用，未删 |
| D2 | blueprint_tasks.py V1 路径 | `LIMIT 80` 实体上限 | 同上 |
| D3 | blueprint_tasks.py V1 路径 | 均匀切片知识点分配 | 同上 |
| D4 | blueprint_tasks.py V1 路径 | entity_name_to_id / name_lower_to_id 映射 | 同上 |
| D5 | blueprint_tasks.py BLUEPRINT_SYNTHESIS_PROMPT | 整个"一次规划全局"prompt | 同上 |

**策略**：推迟到 P0-P3 修完、V2 质量达到可用之后再删。

---

## §4 会话 2 已修的 bug

| 问题 | 原因 | 修复 |
|---|---|---|
| LLMGateway `attached to a different loop` | 单例 Lock 绑旧 loop | task 入口强制重置单例 |

---

## §5 技术债（会话 3 开始记录）

| 编号 | 位置 | 内容 | 影响 |
|---|---|---|---|
| T1 | blueprint_tasks.py `chapter_contents: dict[str,str]` | 用 title 做 key，重名覆盖 | 已造成 websecret 1 章数据污染 |
| T2 | blueprint_tasks.py V2 日志 | `total=37` 和 `total_chapters=38` 不一致（原因是 T1） | 表面不一致，修 T1 后自动解决 |
| T3 | llm_gateway.py `self._lock = asyncio.Lock()` | Lock 绑创建时的 loop | 被 task 入口 reset 绕过，但根因未修；如果未来有其他地方调用 Gateway 不重置单例会复发 |
| T4 | blueprint_tasks.py stage_type 硬编码 | first=foundation, last=assessment, middle=practice | stage 分类和实际内容无关（属于 P1 一起修） |
| T5 | blueprint_tasks.py CHAPTERS_PER_STAGE 硬编码切片 | 最后一个 stage 总是满不了 4 章 | 和 P1 一起重新设计 stage 分组时一起改 |

---

## §6 已知数据污染

**websecret blueprint `840b9aba-6afa-44ae-8250-2b125c5ab428` v11**：
- 章节 ch6 和 ch7 title 都是「掌握ATLAS框架核心攻击战术」
- `content_text` MD5 相同 → ch7 正文是 ch6 的内容
- ch6 挂 18 实体，ch7 挂 7 实体，但正文讲的是 ch6 的
- **影响范围**：personal space，仅 owner zhulimin 可见，零外部用户暴露
- **处理**：不做紧急 SQL 修复。会话 3 修 T1 后重跑，自动消失

---

## §7 Phase 2 的风险与注意事项（继承 v3，部分更新）

- V2 生成会覆盖旧蓝图（`ON CONFLICT (topic_key) DO UPDATE`）
- 回滚方式：删 `BLUEPRINT_V2_ENABLED=true`，重启 celery_worker_knowledge，V1 重新生成
- LLM 成本：网络安全 ~49 次调用，websecret ~77 次调用；会话 3 加 stage 规划 + re-title 后每次 +2 调用
- 生成耗时：网络安全 11 分钟，websecret 13.5 分钟；267 实体基本是单 worker 顺序调用的耗时上限
- **新增**：会话 3 修 P0/P1/P2 的过程中会重跑两个 space，每次都会覆盖现有蓝图

---

## §8 其他路径（与 v3 相同，随时可插入）

- C: 教师巡视仪表板（1-2 个会话）
- D: 学习墙进阶（1-2 个会话）
- E: 加 reranker（1 个会话）

---

## §9 未归类的小事（继承 v3，部分更新）

- [ ] 清理根目录下的 patch_*.py 脚本
- [ ] 清理 .bak 备份文件（含 `.bak.pre_v2`、`.bak.pre_gwfix`）
- [ ] ChatView.vue 默认 topicKey `'web-security'` 可顺手改
- [ ] 前端「教程中心」没展示课程总标题（`skill_blueprints.title`），目前学生看不到「现代软件安全攻防与漏洞分析实战」这类大标题，只能看到 space 名和 stage/章节 — **前端 bug，优先级低**
- [ ] `v3 §1.2` 的实体总数 496 没把 301灯光 174 算进去，v4 已更正为 670

---

## §10 会话 2 的教训 / 工作原则更新

v3 §8 六条不变。补两条观察：

**七、"假修 vs 真修"**：v3 §4 那次把 LLMGateway 的 loop bug 写成"已修复"是错的，只是"让本次撞大运通过"。教训：修 asyncio/单例/全局状态相关 bug 时，一定要在"同一 worker 进程第二次触发"的条件下验证，而不是只看一次成功就签字。

**八、"前端是真实证据"**：从日志和 DB 只能看到"38 章 SUCCESS"，只有打开浏览器才发现 stage 倒序、标题重复、杂烩簇这些问题。**会话 3 重跑后必须前端再看一遍**，不能只信 SQL。

---

*文档版本：v4.0*
*生成时间：2026 年 4 月 14 日*
*下次更新时机：Phase 2 会话 3 结束时*
