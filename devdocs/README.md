# devdocs — StudyStudio 开发过程文档

这个目录存放**开发过程**中的所有非代码产物：会话交接、架构方案、代码快照、历史补丁脚本、废弃代码副本。

与它平级的 `docs/` 目录是**成果文档区**（用户手册、部署手册、测试报告、项目 LOG），两者不混。

---

## 目录结构

```
devdocs/
├── README.md              ← 本文件
├── handover/               ← 会话交接文档（HANDOVER + SYSTEM_REFERENCE + COLLABORATION）
├── handoff/               ← 历史会话交接文档（NextSteps 系列）
├── architecture/          ← 架构设计 / 重构方案
├── snapshots/             ← 代码快照（按日期）
├── archive/               ← 老分析 / 早期脚本 / 废弃 .py 副本
├── patches/               ← 历史补丁脚本（patch_*.py / fix_*.py）
└── security/              ← 安全审计报告与备份
```

---

## 给下次 Claude 会话开场的提示

新会话开始时，读取 `devdocs/handover/` 下的三份文档：

1. **HANDOVER.md**：项目交接（做了啥、下次做啥、关键决策）
2. **SYSTEM_REFERENCE.md**：技术参考（架构、接口、规范、坑位、诊断命令）
3. **COLLABORATION.md**：协作习惯（脚本书写规则、工作节奏、用户偏好）

如果需要回溯历史，再看 `handoff/NextSteps_v{N}.md` 或 `snapshots/` 下的快照。

---

## 当前状态速览（2026-04-27）

- **主要文档**：`handover/HANDOVER.md`（v13.0）、`handover/SYSTEM_REFERENCE.md`（v3.0）
- **部署系统**：新装 + 升级完整方案，详见 `architecture/deployment_system.md`
- **安全审计**：全栈审计完成（4 CRITICAL + 10 HIGH 已修复），详见 `security/SECURITY_AUDIT_REPORT_20260427.md`
- **当前版本**：`VERSION` = `2.7.0`
- **Blueprint V2**：P0/P1/P2/P3 质量修复已完成
- **管线优化**：Phase 0~9 全完成，详见 `PROJECT_LOG_V2_管线优化记录.md`
- **下步重点**：生产环境部署验证、API Key 轮换、管理员面板合并评估

---

## 目录内容说明

### handover/

**主要工作文档区**，每次会话后更新。包含三份长期维护文档：
- `HANDOVER.md`：项目交接（做了啥、下次做啥、已知 Bug、关键决策）
- `SYSTEM_REFERENCE.md`：技术参考（架构、接口清单、规范、坑位、诊断命令）
- `COLLABORATION.md`：协作习惯（脚本规则、工作节奏、用户偏好）

历史版本保留在同目录下（`.bak.YYYYMMDD` 后缀），不删除。

### handoff/

历史会话交接文档（NextSteps 系列，Phase 2 之前使用）。
已被 `handover/` 三文件体系取代，保留供历史回溯。

### architecture/

架构层面的设计文档和重构方案，变化慢，跨会话稳定。例如：
- 蓝图生成的聚类 + LLM 命名方案
- Phase 1 embedding 管线设计
- AI 配置后台的 provider/binding 模型

### snapshots/

代码快照，`create_snapshot.py` 之类的脚本生成的项目打包。命名格式：
- `snapshot_YYYYMMDD.txt` 或
- `StudyStudio_Snapshot_YYYYMMDD_HHMMSS.txt`（旧命名）

新快照建议用短格式：`snapshot_YYYYMMDD_HHMMSS.txt`。

### archive/

不再活跃但要保留的东西：

- **早期开发文档**：`project_analysis.md`、`StudyStudio_Handover.md`
- **废弃 .py 副本**：
  - `llm_gateway.py` / `crypto.py` / `embedding_tasks.py`——和 `apps/api/` 下同名文件 diff 完全一致，是根目录残留的副本
  - `ai_config_router.py` / `create_tutorial_view.py`——早期脚本，`apps/api/` 下无对应文件
  - `fix_chat_history.py`——早期修复脚本
- grep 已验证：无任何代码 import 这些文件

### patches/

历史上对活跃代码打的补丁脚本，26 个 `patch_*.py`，覆盖 h4 ~ h7、notes、notebooks、wall、review、certificate、ai_merge、hooks 等多个模块。按字母序排列。

这些脚本的目的是"打完就扔"，但留下来方便追溯"某次改动到底改了什么"。如果确认不再需要追溯，可以整个 patches/ 删除，但先保留。

---

## 什么不放在这里

- **`docs/`** 是成果文档区（用户手册 / 部署手册 / 测试报告 / PROJECT_LOG），跟这里的"开发过程"区分
- **`_backups/`**（根目录同级）放配置备份，比如 `docker-compose.yml.bak.*`
- **代码备份**（如 `apps/api/tasks/blueprint_tasks.py.bak.pre_v2`）就地保留，不挪进 devdocs
- **活跃脚本**（`install.sh` / `dev_tools.sh` / `patch.sh` / `002_ai_config.sql` / `requirements.txt`）留在根目录

---

## 维护约定

1. **每次会话结束**：更新 `handover/HANDOVER.md`，旧版本加 `.bak.YYYYMMDD` 后缀保留
2. **大的代码变更前后**：生成新 snapshot 放进 `snapshots/`
3. **架构决策**：写成方案文档放进 `architecture/`
4. **清理**：定期检查 `snapshots/` 是否太大（单个可能 2MB+），超过半年的旧快照可以压缩或删除

---

*README 版本：v2.2*
*更新时间：2026-04-27*
