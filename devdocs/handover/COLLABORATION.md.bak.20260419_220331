# StudyStudio 协作偏好备忘

> 给下次会话的 Claude 读。这份文档不讲项目，只讲「怎么跟这个用户配合」。
> 读完这份再动手，能避免很多返工。

---

## 一、基本协作环境

- 用户在 **Ubuntu 服务器**上部署，通过 **SSH 客户端**远程访问
- 所有操作通过 Claude 给出**脚本让用户在服务器执行**，然后把输出粘贴回来
- 用户**不会**手动改源码或手动跑零散命令——一切都是脚本化的
- 项目路径：`~/studystudio/`

---

## 二、脚本书写规则（最重要）

### 2.1 一次性给全，不要分段

**错误做法：** "先跑这段，看完输出我再给下一步"——除非是必要的分步验证，否则不要这样。

**正确做法：** 一次把相关的脚本全部给完，用户一口气执行完。比如写文件、改文件、重启、验证四件事能合并就合并。

**例外：** 强制分步的场景才分——比如 DB 迁移要先干跑再正式应用；比如需要从上一步输出拿信息才能写下一步脚本。

### 2.2 脚本内容不要引起 SSH 客户端崩溃

这是用户第一条消息就强调的。具体：

- **不要**在注释里写可能被客户端误解析的控制字符
- **避免**过长的单行命令（某些 SSH 客户端会截断或溢出）
- **小心**中文标点（比如全角逗号、冒号）出现在 heredoc 或脚本注释里时的编码问题
- **慎用**复杂的嵌套引号转义，能用 `python3 << 'EOF'` 这种带引号的 heredoc 就优先用

### 2.3 修改源码用脚本幂等改，不让用户手工编辑

**首选工具**（从安全到万能）：

1. `python3 << 'EOF'` + pathlib 读写 —— **最推荐**，写错了能 raise SystemExit 阻止破坏
2. `sed`/`awk` 按行号或锚点替换 —— 简单替换用
3. `cat > file << 'EOF'` —— **新建文件**用，覆盖整文件要慎重

**所有修改脚本必须幂等**：再跑一次不会出错、不会重复插入。典型做法：

```python
if MARKER in text:
    print("已存在，跳过")
else:
    # 插入或替换
```

**锚点匹配失败时要 raise SystemExit**，不要静默继续——避免把文件改烂。

### 2.4 关键操作先备份

- 改数据库前：`pg_dump` 到 `/tmp/xxx_backup_$(date +%Y%m%d_%H%M%S).sql`
- 改关键源码前：`cp file file.bak`（项目里已经有多个 `.bak` 前例，比如 `db.py.bak.20260413_203543`）
- 迁移 SQL 先**干跑**：`BEGIN; ... ROLLBACK;` 验证语法和数据影响，再正式 `COMMIT`

---

## 三、工作节奏

### 3.1 先勘察，再动手

改代码前**必须**先看现有代码风格：
- 看 1~2 个同类文件作为模板
- 确认项目用的是 ORM 还是 raw SQL、有没有 Alembic、模块怎么组织
- 新代码照猫画虎，不要引入新范式

勘察脚本单独给一条，读完输出再写修改脚本。这是**唯一允许分步**的常规场景。

### 3.2 小步快跑，每步验证

**不要**一口气改 10 个文件最后统一测试。正确节奏：

1. 改 1 处或 1 组相关改动
2. 给一条验证脚本（跑测试、看日志、查 DB 状态）
3. 用户贴输出
4. 绿了再进下一步

Phase 1 是按 Step 1 (DB) → Step 2 (后端模块) → Step 3 (查询改造) → Step 4 (前端) 分的，每一步内部也有多次验证。这个节奏用户接受度最高。

### 3.3 测试用 Service 层而不是 HTTP 层

写功能测试时**优先进容器跑 Python 直接调 Service**，不要求用户给密码或构造 JWT。例子：

```bash
docker compose exec -T api python3 << 'PY_EOF'
import asyncio
from apps.api.core.db import async_session_factory
from apps.api.modules.xxx.service import XxxService

async def main():
    async with async_session_factory() as db:
        svc = XxxService(db)
        # ... 调用 + assert
asyncio.run(main())
PY_EOF
```

好处：不用暴露密码、覆盖全面、出错信息直接。

---

## 四、输出和交付规则

### 4.1 关键文档最后落地成 Markdown 文件

阶段性任务完成后，必须写两份文档：
- `devdocs/handover/HANDOVER.md`——项目交接（做了啥、下次做啥、关键决策）
- `devdocs/handover/SYSTEM_REFERENCE.md`——技术参考（架构、坑位、诊断命令）

完成这次社交学习 Phase 1 后，还加了第三份 `COLLABORATION.md`（本文档）。

### 4.2 不要在 claude.ai 给"下载文件"

用户在普通 Claude 聊天里（不是 Projects 文件系统），**给"附件卡片"或"文件下载"会看不到**。

**正确做法**：内容直接贴在消息里，用 `````markdown`（4 反引号）包裹，避免被 3 反引号的代码块吞掉后续内容。

如果文档特别长，分多条消息发，每条一个文件。

### 4.3 脚本里不要在注释里写 Markdown 的反引号

会让 heredoc 混乱。需要在 shell 脚本里写代码示例时，用缩进或单独一行 echo，不要嵌套反引号。

---

## 五、用户的思维风格

### 5.1 理念导向，在意"为什么"

用户会在决策节点停下来问"为什么这么设计"。回答的时候：
- 先给**推荐方案**和**理由**
- 再列**备选方案**和**权衡**
- 避免含糊的"都行"——给明确建议，但留选择空间

上次会话讨论社交学习的 4 阶段设计、多版本 blueprint 要不要做、公共领域的重新定位，都是这种模式。

### 5.2 默认"按你推荐的来"

一旦讨论清楚理由，用户很可能直接说"按你推荐的来"。这时候就要**一把推到底**，不要反复确认。

### 5.3 分阶段、避免"不伦不类的半成品"

用户明确认可这个原则（见 HANDOVER 的决策记录）。设计功能时一定要拆成**每阶段独立可交付**的小块，不要搞"大爆炸式"提交。

### 5.4 不追求炫技，但追求"该有的都有"

比如 Phase 1 的"最后一个 owner 不能退出"、"member 看不到 invite_code"、"邀请码字符集去除易混字符"——这些边界用户不会要求，但会欣赏 Claude 主动做。

---

## 六、几个容易忘的技术约束

这些不是协作偏好，但每次会话重启都可能忘，写在这里做 checklist：

- **项目用 raw SQL，没有 ORM（不用 Alembic）**。迁移是手写 `.sql` 文件放在 `migrations/` 下
- **Web 容器是纯 nginx**，没有 node。前端构建在**宿主机**做，然后 `docker compose cp` 部署
- **DB 连接**：`docker compose exec postgres psql -U user -d adaptive_learning`
- **认证依赖**：`from apps.api.modules.auth.router import get_current_user`，`current_user["user_id"]` 是字符串 UUID
- **API 响应格式**：`{code, msg, data}`，前端 axios 拦截器会拆一层拿 `res.data`
- **前端剪贴板**：HTTP 环境下 `navigator.clipboard` 不可用，必须 `execCommand('copy')` fallback

---

## 七、下次会话的"开场白规范"

用户习惯这样开场：

> 先查看 devdocs/handover/ 下的三个文档，HANDOVER.md 是总体交接，SYSTEM_REFERENCE.md 是技术参考，COLLABORATION.md 是我的协作习惯。然后我想推进 XXX。

Claude 收到后应该：

1. 读完三份文档
2. **不要**问"还需要什么信息"这种套话
3. 直接给出"第一步勘察脚本"——按这份文档 §3.1 的规则
4. 等用户贴回输出，再给修改脚本

这是本项目第三次迭代验证过的最顺模式。
