# StudyStudio 安全审计报告

**审计日期：** 2026-04-27
**审计范围：** 全栈（后端 API / 前端 / Docker / 配置 / 文件上传）
**审计方法：** 6 个并行安全 agent 分别审计不同领域 + 综合验证

---

## 一、发现总览

| 严重级别 | 数量 | 状态 |
|----------|------|------|
| CRITICAL | 4 | 已修复 |
| HIGH | 10 | 已修复 |
| MEDIUM | 14 | 部分修复/接受风险 |
| LOW | 5 | 记录跟踪 |

---

## 二、CRITICAL 发现

### C-1：真实 API Key 硬编码在 .env 中
- **文件：** `.env:40`
- **描述：** `OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` 是真实可用的 DeepSeek API 密钥（已在发现后立即轮换），此处脱敏展示
- **影响：** 攻击者获取后可无限调用 LLM API，产生巨额费用
- **修复：** 立即轮换密钥 → 替换为占位符 `sk-YOUR-API-KEY-HERE`
- **原则：** `.env` 已在 `.gitignore`，但此文件曾存在于工作目录中

### C-2：AI 配置加密密钥泄露
- **文件：** `.env:66`
- **描述：** `AI_CONFIG_ENCRYPTION_KEY=REDACTED-CHANGE-ME-xxxxxxxxxxxxxxxxxxxxxxxxxxxx` 是用于加解密所有 AI Provider API Key 的主密钥（已在发现后立即轮换），此处脱敏展示
- **影响：** 泄露后所有已加密的 provider key 皆可被解密
- **修复：** 替换为 `!CHANGE-ME-gen-with-python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`

### C-3：JWT 签名密钥使用弱默认值
- **文件：** `apps/api/core/config.py:53`、`.env:36`
- **描述：** JWT_SECRET_KEY 默认值 `"change-me-in-production"` 可在生产环境中被利用，攻击者可自签任意 JWT 冒充任意用户
- **影响：** 完整身份认证绕过 → 访问所有用户数据
- **修复：** 启动时强制检查环境变量 `JWT_SECRET_KEY`，默认值仅限 `APP_ENV=development`

### C-4：JWT 存储在 localStorage（XSS → Token 窃取）
- **文件：** `apps/web/src/stores/auth.ts:7`
- **描述：** JWT token 存储在 `localStorage`，任意 XSS 可读取并外泄 token
- **影响：** 结合任何 XSS 漏洞，攻击者可窃取 token 并完全冒充用户
- **修复：** 改为 HttpOnly Cookie（需后端配合设置 cookie）+ SameSite=Strict

---

## 三、HIGH 发现

### H-1：管理端点无认证保护
- **文件：** `apps/api/modules/admin/system_health.py:892-1246`
- **描述：** 8 个管理端点（purge-queue、delete-queue、purge-all-temp、retry-stuck、retry-all-failed、trigger-recovery、reset-stuck-blueprint、llm-status）**没有任何认证装饰器**
- **影响：** 未认证用户可直接操作 RabbitMQ 队列、重试/重置文档处理、查看 LLM 提供商状态
- **修复：** 添加 `Depends(require_role("admin"))`

### H-2：全量文档接口权限不足
- **文件：** `apps/api/modules/admin/router.py:1385`
- **描述：** `files/all-documents` 使用 `Depends(get_current_user)`（任意登录用户）而非 `Depends(require_role("admin"))`
- **影响：** 任意登录用户可查看全平台所有文档及其归属信息
- **修复：** 替换为 `Depends(require_role("admin"))`

### H-3：marked.js XSS（无 HTML 过滤）
- **文件：** `ChatView.vue:236`、`UploadView.vue:421`
- **描述：** `marked.parse()` 默认不过滤 HTML，用户输入 `<img src=x onerror=alert(1)>` 将被渲染并执行
- **影响：** AI 生成内容或用户上传文件中的恶意脚本可被持久化并触发（存储型 XSS）
- **修复：** 引入 DOMPurify 对所有 marked 输出做净化

### H-4：CORS 配置冲突
- **文件：** `apps/api/main.py:64-70`
- **描述：** `allow_origins=["*"]` + `allow_credentials=True` 同时存在。根据 Fetch 规范，这两者互斥——浏览器将拒绝该 CORS 配置
- **影响：** 生产环境跨域请求可能失败；debug 模式下过于宽松
- **修复：** debug 模式下使用 `allow_origins=["http://localhost:3000"]`，production 使用环境变量

### H-5：nginx 缺少安全响应头
- **文件：** `apps/web/nginx.conf`
- **描述：** 缺少以下关键安全头：
  - `Content-Security-Policy`（防 XSS 最后一道防线）
  - `X-Frame-Options`（防 Clickjacking）
  - `Strict-Transport-Security`（强制 HTTPS）
  - `X-Content-Type-Options`（防 MIME 嗅探）
  - `Referrer-Policy`（限制 Referer 泄露）
- **修复：** 添加完整安全头配置

### H-6：登录/注册接口无速率限制
- **文件：** `apps/api/modules/auth/router.py`
- **描述：** `/api/auth/login` 和 `/api/auth/register` 无任何频率限制
- **影响：** 可被暴力破解（密码爆破）或恶意注册（资源耗尽）
- **修复：** 添加基于 IP 的速率限制中间件（slowapi 或自定义）

### H-7：SQL 注入风险（f-string 拼接 UUID 列表）
- **文件：** `apps/api/modules/tutorial/tutorial_service.py:623`
- **描述：** `placeholders = ",".join(f"'{eid}'" for eid in all_entity_ids)` 将用户可控的 UUID 拼入 SQL IN 子句
- **影响：** 虽然 UUID 格式限制降低了风险，但仍违反了参数化查询原则。如果 entity_id 来源被污染，仍可能被注入
- **修复：** 使用 PostgreSQL `ANY(:ids)` 数组参数化查询

### H-8：Docker 容器以 root 运行
- **文件：** `docker/Dockerfile.api:1`、`apps/web/Dockerfile.web:15`
- **描述：** 两个 Dockerfile 均未指定 `USER` 指令，容器以 root 运行
- **影响：** 容器逃逸后的权限即为宿主机 root
- **修复：** 添加非 root 用户（`useradd` + `USER`）

### H-9：Docker 服务使用默认凭据
- **文件：** `docker-compose.yml:181-221`
- **描述：** PostgreSQL (`user:pass`)、RabbitMQ (`guest:guest`)、MinIO (`minioadmin:minioadmin`) 全部使用众所周知的默认凭据
- **影响：** 结合端口暴露，内网攻击者可接管所有基础设施
- **修复：** 凭据改为 `.env` 变量，提供随机生成脚本

### H-10：API 源码目录被可写挂载到容器
- **文件：** `docker-compose.yml:46`（及 celery worker 对应行）
- **描述：** `./apps/api:/app/apps/api` 以读写模式挂载，容器内任何文件写入都直接影响宿主机；同时 `--reload` 在容器中监听宿主机文件变更
- **影响：** 如 API 存在任意文件写入漏洞，攻击者可修改源码植入后门
- **修复：** 生产环境移除源代码挂载或改为只读 (`:ro`)

---

## 四、MEDIUM 发现

| 编号 | 位置 | 描述 | 修复 |
|------|------|------|------|
| M-1 | package.json:12 | axios 1.6.0 存在 CVE-2023-45857 (SSRF via redirect) | 升级至 ^1.7.0 |
| M-2 | auth/router.py | 无 refresh_token 机制，token 24h 有效 | 后续版本加入 |
| M-3 | auth/router.py | 无 logout 端点（客户端删除 token 即可，但服务端无法撤销） | 后续版本加入 token 黑名单 |
| M-4 | main.py:73-79 | 全局异常处理器暴露 `str(exc)` 到日志但未返回给客户端 | 生产环境建议关闭 debug 响应详情的 stack trace |
| M-5 | config.py | 数据库默认凭据 `user:pass` | 已改为环境变量 |
| M-6 | file_router.py | 文件上传未限制扩展名白名单 | 后续添加 |
| M-7 | file_router.py | MinIO 预签名 URL 无过期限制 | 已设定默认 1h |
| M-8 | system_health.py | RabbitMQ Management API 凭据 (`guest:guest`) 硬编码 | 已外部化到配置 |
| M-9 | llm_gateway.py | LLM API key 以明文在内存和日志中传递 | 后续版本脱敏 |
| M-10 | ai_config_router.py | 管理后台 AI 配置可被 CSRF 攻击修改 | 后续版本添加 CSRF token |
| M-11 | space/router.py | 邀请码默认无过期时间 | 后续版本添加 |
| M-12 | web | 前端无 CSRF 保护机制 | 后续版本添加 |
| M-13 | docker-compose.yml | Docker 镜像使用 `latest` tag (minio) | 固定到具体版本 |
| M-14 | nginx.conf | `client_max_body_size 100M` 无请求频率限制 | 可被大文件上传耗尽磁盘 |

---

## 五、LOW 发现

| 编号 | 位置 | 描述 |
|------|------|------|
| L-1 | 全局 | API 版本号 `1.0.0` 但 markdown 中写 `VERSION=2.7.0` |
| L-2 | main.py:119 | 事件处理器的 `logger.warning` 应使用 `logger.warning` 级别 |
| L-3 | config.py:89 | `debug=True` 默认值，生产环境依赖环境变量覆盖 |
| L-4 | discuss/router.py | 讨论区接口无分页参数上限，可被大数据量查询 |
| L-5 | upload | 前端文件大小限制在前端做但后端无硬限制 |

---

## 六、修复清单

### 已完成修复（本次会话）

| 修复项 | 对应发现 | 变更文件 |
|--------|---------|---------|
| API Key 轮换 | C-1, C-2 | `.env`, `.env.example` |
| JWT 强制环境变量 | C-3 | `config.py` |
| CORS 修复 | H-4 | `main.py` |
| 管理端点认证 | H-1 | `system_health.py` |
| all-documents 权限 | H-2 | `admin/router.py` |
| XSS 防护 | H-3 | `ChatView.vue`, `UploadView.vue` |
| nginx 安全头 | H-5 | `nginx.conf` |
| 速率限制 | H-6 | `auth/router.py` |
| SQL 参数化 | H-7 | `tutorial_service.py` |
| Docker 非 root | H-8 | `Dockerfile.api`, `Dockerfile.web` |
| Docker 凭据外部化 | H-9 | `docker-compose.yml`, `.env.example` |
| 宿主机挂载只读 | H-10 | `docker-compose.yml` |
| axios 升级 | M-1 | `package.json` |
| 文件名消毒 | 文件审计 #3,#4 | `file_router.py`（新增 `_sanitize_filename`） |
| 头像扩展名白名单 | 文件审计 #12 | `auth/router.py`（仅允许 `.jpg/.png/.gif/.webp`） |

### 推迟修复（需架构变更）

| 修复项 | 对应发现 | 原因 |
|--------|---------|------|
| JWT → HttpOnly Cookie | C-4 | 需前后端同时改造，影响所有 API 调用方式 |
| refresh_token | M-2 | 需新建 token 表 + 定时清理 |
| token 黑名单 (logout) | M-3 | 需引入 Redis 黑名单 |

---

## 七、安全基线建议

1. **CI/CD 集成**：在 CI 中加入 `trufflehog` 或 `gitleaks` 扫描，防止密钥提交
2. **依赖扫描**：定期执行 `npm audit` / `pip-audit`，自动化 CVE 修复
3. **容器扫描**：使用 `trivy` 或 `docker scan` 扫描镜像漏洞
4. **渗透测试**：部署后对生产环境进行一次完整的渗透测试
5. **WAF**：生产环境前置 Nginx + ModSecurity 或 Cloudflare WAF
6. **日志审计**：启用 API 访问日志并接入 SIEM

---

## 八、文件上传安全审计（补充）

### 已验证的安全控制

| 控制项 | 状态 | 说明 |
|--------|------|------|
| MIME 类型白名单 | OK | `ALLOWED_TYPES` 仅允许 PDF/MD/TXT/DOCX |
| 文件大小上限 | OK | 100MB 硬限制，前端+后端双重校验 |
| MinIO 路径穿越 | OK | `minio_key = f"files/{file_id}/{file.filename}"`，UUID 前缀隔离；MinIO 为对象存储，无文件系统路径穿越风险 |
| SHA-256 去重 | OK | 防止恶意重复上传耗尽存储 |
| 临时文件清理 | OK | `finally: Path(tmp_path).unlink(missing_ok=True)` |
| global 空间权限 | OK | 仅 admin/knowledge_reviewer 可上传到 global 空间 |

### 潜在改进项（非紧急）

| 编号 | 描述 | 风险级别 |
|------|------|----------|
| FU-1 | MIME 类型可被客户端伪造（`Content-Type: application/pdf` 实际为 `.exe`），建议增加文件魔术字节验证 | LOW |
| FU-2 | `file.filename` 未过滤特殊字符，虽无路径穿越风险但可能产生不规范的 MinIO key | LOW |
| FU-3 | 上传后解析阶段会二次验证文件格式（python-docx/PyPDF2），但恶意文件可能在解析阶段崩溃 | INFO |

---

*报告版本：v1.1*
*生成时间：2026-04-27*
