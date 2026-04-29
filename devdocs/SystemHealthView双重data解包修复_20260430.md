# SystemHealthView 双重 data 解包修复

**日期**：2026-04-30
**状态**：已修复并部署（本地 + 生产服务器 10.10.50.14）
**关联**：与 `课程模板功能_20260430.md` Bug 1 同根同源

---

## 1. 问题现象

管理员系统监控页面（`/admin` → 系统监控）中：
- **数据库**标签始终显示"异常"（红色）
- **RabbitMQ**标签始终显示"异常"（红色）
- 实际 API 返回 `reachable: true`，服务运行正常

## 2. 根因分析

### 数据链路

```
服务器返回:  {"code":200, "data":{"overall":"healthy","database":{"reachable":true},...}}
                  │
                  ▼
axios 拦截器:  res => res.data  → 剥离 Axios 信封
              返回 {"code":200, "data":{...}}
                  │
                  ▼
const { data } = await http.get(...)  → 解构出 data 属性
              data = {"overall":"healthy", "database":{...},...}  ← 已是目标数据
                  │
                  ▼
healthData.value = data?.data ?? null  → data.data = undefined → null  ← 多解了一层！
                  │
                  ▼
模板渲染:  healthData?.database?.reachable  →  null?.database?.reachable  →  undefined → 显示"异常"
```

### 核心错误

`const { data } = ...` 解构后拿到的 `data` **本身就是业务数据对象**（`{overall, database, rabbitmq, ...}`），它没有嵌套的 `.data` 属性。`data?.data` 永远是 `undefined`。

## 3. 修复方案

所有成功路径：去掉多余的 `.data` 层级。

```typescript
// ❌ 错误 — 双重解包（上一轮"修复"引入）
healthData.value = data?.data ?? null
pipelineData.value = data?.data ?? null
ElMessage.success(data?.data?.message || '...')

// ✅ 正确
healthData.value = data ?? null
pipelineData.value = data ?? null
ElMessage.success(data?.message || '...')
```

**错误 handlers 不修改**：`catch` 块中 `err.response.data.data.message` 是正确的三层路径（axios 错误拦截器不做变换，`err.response` 是原始 HTTP 响应）。

## 4. 修复清单（12 处）

| # | 函数 | 行 | 修复前 | 修复后 |
|---|------|----|--------|--------|
| 1 | `fetchHealth` | 1094 | `data?.data \|\| null` | `data \|\| null` |
| 2 | `confirmPurgeAllTemp` | 1145 | `data?.data?.message` | `data?.message` |
| 3 | `fetchPipelineStatus` | 1157 | `data?.data \|\| null` | `data \|\| null` |
| 4 | `fetchLlmStatus` | 1169 | `data?.data \|\| null` | `data \|\| null` |
| 5 | `retryDocument` | 1203 | `data?.data?.message` | `data?.message` |
| 6 | `retryAllFailed` | 1221 | `data?.data?.message` | `data?.message` |
| 7 | `triggerRecovery` | 1239 | `data?.data?.message` | `data?.message` |
| 8 | `resetStuckBlueprint` | 1256 | `data.data.message` | `data?.message` |
| 9 | `loadBpProgress` | 1269 | `res.data?.data?.spaces` | `res.data?.spaces` |
| 10 | `loadDocuments` | 1325 | `if(data?.data)` / `data.data.xxx` | `if(data)` / `data.xxx` |
| 11 | `retryDocumentAction` | 1352 | `data.data?.message` | `data?.message` |
| 12 | `reparseDocumentAction` | 1370 | `data.data?.message` | `data?.message` |

## 5. 为什么这是重复问题

项目中至少 **7 份文档** 明确写道：

> axios 拦截器已剥一层：res.data = payload，不写 res.data.data

来源：`HANDOVER.md`、`HANDOVER1.md`、`SYSTEM_REFERENCE.md`、`SYSTEM_REFERENCE1.md`、`SYSTEM_REFERENCE202604211010.md`、`COLLABORATION.md`、`课程模板功能_20260430.md`

但每次新组件开发或旧组件修改时，开发者容易**忘记拦截器的存在**，在 `const { data } = http.get()` 之后再接 `.data`。

### 问题模式

| 组件 | 出现时间 | 写法 |
|------|---------|------|
| TemplateSelector (Bug 1) | 2026-04-30 | `res.data.data.templates` |
| SystemHealthView (Bug 3) | 2026-04-30 | `data?.data ?? null` |

**根本原因**：`const { data } = ...` 解构命名与 API 响应 `data` 字段同名，造成视觉混淆。

## 6. 预防措施

1. **代码审查清单**：PR 检查项中加入"grep `data\.data` — 确认无双重解包"
2. **统一 API 客户端封装**：考虑在 `api/index.ts` 中增加类型安全的响应包装，让 TypeScript 编译器在 `data.data` 时报警
3. **命名约定**：建议 `const { data: payload } = await http.get(...)` — 用 `payload` 命名区分，避免 `data.data` 连锁

## 7. 验证方法

1. 打开系统监控页面 → 数据库标签显示绿色"正常"
2. RabbitMQ 标签显示绿色"正常"
3. 浏览器 Console 无 TypeError
4. 管线状态、LLM 状态、文档列表正常加载
5. 各操作按钮（重试、清理等）点击后提示消息正常显示
