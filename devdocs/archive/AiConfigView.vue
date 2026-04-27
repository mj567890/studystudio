<!--
  apps/web/src/views/admin/AiConfigView.vue
  Admin AI 配置：Provider 管理 + 能力路由绑定 + 连接测试 + 维度迁移
  用 tab 切分以避免改动已有路由表
-->
<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

// 由于不确定项目里 http 实例的导出名，这里直接用一个本地 axios 实例；
// 若你项目里统一用 src/api/index.ts 中的 http，可改为：
//   import http from '@/api/http'  或 import { http } from '@/api'
const http = axios.create({ baseURL: '/api', timeout: 30000 })
http.interceptors.request.use(cfg => {
  const tk = localStorage.getItem('access_token')
  if (tk) cfg.headers.Authorization = `Bearer ${tk}`
  return cfg
})
http.interceptors.response.use(
  r => r.data,
  err => {
    const msg = err.response?.data?.detail?.msg || err.response?.data?.msg || err.message
    ElMessage.error(msg || '请求失败')
    return Promise.reject(err)
  },
)

// ═══════════════════════ state ═══════════════════════
const activeTab = ref<'providers' | 'routing'>('providers')

interface Provider {
  provider_id: string
  name: string
  kind: string
  base_url: string
  api_key_masked: string
  has_api_key: boolean
  extra_config: Record<string, any>
  enabled: boolean
  last_tested_at: string | null
  last_test_ok: boolean | null
  last_test_error: string | null
}

interface Capability {
  key: string
  group: string
  kind: 'chat' | 'embedding'
  label: string
  required: boolean
}

interface Binding {
  binding_id: string
  capability: string
  provider_id: string
  provider_name: string
  provider_kind: string
  provider_base_url: string
  model_name: string
  priority: number
  params: Record<string, any>
  enabled: boolean
}

const providers      = ref<Provider[]>([])
const capabilities   = ref<Capability[]>([])
const bindings       = ref<Binding[]>([])
const loading        = ref(false)

// ═══════════════════════ provider dialog ═══════════════════════
const providerDlgVisible = ref(false)
const providerDlgEditing = ref<string | null>(null)
const providerForm = reactive({
  name: '',
  kind: 'openai_compatible',
  base_url: '',
  api_key: '',
  extra_config_text: '{}',
  enabled: true,
})

function openCreateProvider() {
  providerDlgEditing.value = null
  providerForm.name = ''
  providerForm.kind = 'openai_compatible'
  providerForm.base_url = ''
  providerForm.api_key = ''
  providerForm.extra_config_text = '{}'
  providerForm.enabled = true
  providerDlgVisible.value = true
}

function openEditProvider(p: Provider) {
  providerDlgEditing.value = p.provider_id
  providerForm.name = p.name
  providerForm.kind = p.kind
  providerForm.base_url = p.base_url
  providerForm.api_key = ''   // 空 = 不修改
  providerForm.extra_config_text = JSON.stringify(p.extra_config || {}, null, 2)
  providerForm.enabled = p.enabled
  providerDlgVisible.value = true
}

async function saveProvider() {
  let extra: any = {}
  try { extra = JSON.parse(providerForm.extra_config_text || '{}') }
  catch { ElMessage.error('extra_config 不是合法 JSON'); return }

  const payload: any = {
    name: providerForm.name,
    kind: providerForm.kind,
    base_url: providerForm.base_url,
    extra_config: extra,
    enabled: providerForm.enabled,
  }
  // 新建时必传 api_key（允许空），编辑时空串 = 不修改
  if (providerDlgEditing.value === null) {
    payload.api_key = providerForm.api_key
    await http.post('/admin/ai/providers', payload)
  } else {
    if (providerForm.api_key) payload.api_key = providerForm.api_key
    await http.post(`/admin/ai/providers/${providerDlgEditing.value}`, payload)
  }
  ElMessage.success('已保存')
  providerDlgVisible.value = false
  await loadProviders()
}

async function deleteProvider(p: Provider) {
  try {
    await ElMessageBox.confirm(
      `确认删除 Provider「${p.name}」吗？被能力绑定使用的 provider 会删除失败。`,
      '提示', { type: 'warning' })
  } catch { return }
  await http.delete(`/admin/ai/providers/${p.provider_id}`)
  ElMessage.success('已删除')
  await loadProviders()
}

// ═══════════════════════ provider test dialog ═══════════════════════
const testDlgVisible = ref(false)
const testDlgTarget = ref<Provider | null>(null)
const testForm = reactive({
  model_name: 'deepseek-chat',
  capability_kind: 'chat' as 'chat' | 'embedding',
})
const testResult = ref<any>(null)
const testing = ref(false)

function openTestProvider(p: Provider) {
  testDlgTarget.value = p
  testForm.model_name = ''
  testForm.capability_kind = 'chat'
  testResult.value = null
  testDlgVisible.value = true
}

async function runTest() {
  if (!testDlgTarget.value || !testForm.model_name.trim()) {
    ElMessage.warning('请填写 model_name'); return
  }
  testing.value = true
  testResult.value = null
  try {
    const res: any = await http.post('/admin/ai/test', {
      provider_id: testDlgTarget.value.provider_id,
      model_name: testForm.model_name.trim(),
      capability_kind: testForm.capability_kind,
    })
    testResult.value = res.data
    if (res.data.ok) {
      ElMessage.success(`连接成功，延迟 ${res.data.latency_ms}ms`)
      // 如是 embedding 且维度不匹配，提示是否迁移
      if (res.data.capability_kind === 'embedding' && res.data.dimension_mismatch) {
        try {
          await ElMessageBox.confirm(
            `⚠️ 检测到向量维度为 ${res.data.detected_dimension}，当前 schema 使用 ${res.data.current_dimension}。\n\n` +
            `不迁移的话，embedding 写入时会因维度不匹配报错。\n\n` +
            `迁移会：\n` +
            `  1. 将 knowledge_entities 和 document_chunks 中所有现有 embedding 重置为 NULL\n` +
            `  2. DROP 并重建 ivfflat 索引\n` +
            `  3. ALTER COLUMN TYPE vector(${res.data.detected_dimension})\n\n` +
            `已有 embedding 需要通过 Phase 1 批量任务重新生成。\n\n` +
            `是否现在迁移？`,
            '维度不匹配',
            { type: 'warning', confirmButtonText: '立即迁移', cancelButtonText: '取消' },
          )
          const migRes: any = await http.post('/admin/ai/embedding/migrate-dimension', {
            new_dim: res.data.detected_dimension,
            confirm: true,
          })
          ElMessage.success(migRes.data.message || '迁移完成')
        } catch { /* 用户取消 */ }
      }
      await loadProviders()
    } else {
      ElMessage.error('连接失败：' + (res.data.error || '未知错误'))
    }
  } finally {
    testing.value = false
  }
}

// ═══════════════════════ bindings ═══════════════════════
const bindingsByCapability = computed(() => {
  const map: Record<string, Binding[]> = {}
  for (const b of bindings.value) {
    if (!map[b.capability]) map[b.capability] = []
    map[b.capability].push(b)
  }
  return map
})

const capGroups = computed(() => {
  const groups: Record<string, Capability[]> = {}
  for (const c of capabilities.value) {
    if (!groups[c.group]) groups[c.group] = []
    groups[c.group].push(c)
  }
  return groups
})

const bindDlgVisible = ref(false)
const bindDlgCapability = ref<Capability | null>(null)
const bindForm = reactive({
  binding_id: '' as string | '',
  provider_id: '',
  model_name: '',
  priority: 0,
  params_text: '{}',
  enabled: true,
})

function openCreateBinding(cap: Capability) {
  bindDlgCapability.value = cap
  bindForm.binding_id = ''
  bindForm.provider_id = ''
  bindForm.model_name = ''
  // 下一个可用 priority
  const existing = bindingsByCapability.value[cap.key] || []
  bindForm.priority = existing.length ? Math.max(...existing.map(b => b.priority)) + 1 : 0
  bindForm.params_text = '{}'
  bindForm.enabled = true
  bindDlgVisible.value = true
}

function openEditBinding(cap: Capability, b: Binding) {
  bindDlgCapability.value = cap
  bindForm.binding_id = b.binding_id
  bindForm.provider_id = b.provider_id
  bindForm.model_name = b.model_name
  bindForm.priority = b.priority
  bindForm.params_text = JSON.stringify(b.params || {}, null, 2)
  bindForm.enabled = b.enabled
  bindDlgVisible.value = true
}

async function saveBinding() {
  if (!bindDlgCapability.value || !bindForm.provider_id || !bindForm.model_name.trim()) {
    ElMessage.warning('请填写完整'); return
  }
  let params: any = {}
  try { params = JSON.parse(bindForm.params_text || '{}') }
  catch { ElMessage.error('params 不是合法 JSON'); return }

  await http.post('/admin/ai/bindings', {
    capability: bindDlgCapability.value.key,
    provider_id: bindForm.provider_id,
    model_name: bindForm.model_name.trim(),
    priority: bindForm.priority,
    params,
    enabled: bindForm.enabled,
  })
  ElMessage.success('已保存')
  bindDlgVisible.value = false
  await loadBindings()
}

async function deleteBinding(b: Binding) {
  try {
    await ElMessageBox.confirm(
      `确认解绑 ${b.capability} 的 priority=${b.priority}（${b.provider_name} / ${b.model_name}）？`,
      '提示', { type: 'warning' })
  } catch { return }
  await http.delete(`/admin/ai/bindings/${b.binding_id}`)
  ElMessage.success('已解绑')
  await loadBindings()
}

// ═══════════════════════ loaders ═══════════════════════
async function loadProviders() {
  loading.value = true
  try {
    const res: any = await http.get('/admin/ai/providers')
    providers.value = res.data.providers || []
  } finally { loading.value = false }
}

async function loadCapabilities() {
  const res: any = await http.get('/admin/ai/capabilities')
  capabilities.value = res.data.capabilities || []
}

async function loadBindings() {
  const res: any = await http.get('/admin/ai/bindings')
  bindings.value = res.data.bindings || []
}

onMounted(async () => {
  await Promise.all([loadProviders(), loadCapabilities(), loadBindings()])
})

const groupLabel: Record<string, string> = {
  chat: '对话类',
  vector: '向量类',
  vision: '视觉（未来）',
  audio: '语音（未来）',
  image: '图像生成（未来）',
  safety: '内容安全（未来）',
}
</script>

<template>
  <div class="ai-config-view">
    <el-tabs v-model="activeTab">
      <!-- ═════════════════════ Providers ═════════════════════ -->
      <el-tab-pane label="Provider 管理" name="providers">
        <div class="tab-header">
          <div class="tab-hint">
            AI 服务提供方。每个 provider 是一个可独立配置 base_url + api_key 的连接。
            同一个 provider 可以被多个能力绑定使用。
          </div>
          <el-button type="primary" @click="openCreateProvider">+ 新增 Provider</el-button>
        </div>

        <el-table :data="providers" v-loading="loading" border stripe>
          <el-table-column prop="name" label="名称" width="180" />
          <el-table-column prop="kind" label="协议" width="160" />
          <el-table-column prop="base_url" label="Base URL" show-overflow-tooltip />
          <el-table-column label="API Key" width="200">
            <template #default="{ row }">
              <span v-if="row.has_api_key" class="masked">{{ row.api_key_masked }}</span>
              <el-tag v-else type="danger" size="small">未设置</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
                {{ row.enabled ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="上次测试" width="160">
            <template #default="{ row }">
              <el-tooltip v-if="row.last_test_error" :content="row.last_test_error" placement="top">
                <el-tag type="danger" size="small">失败</el-tag>
              </el-tooltip>
              <el-tag v-else-if="row.last_test_ok" type="success" size="small">通过</el-tag>
              <el-tag v-else type="info" size="small">未测试</el-tag>
              <div v-if="row.last_tested_at" class="muted small">
                {{ new Date(row.last_tested_at).toLocaleString() }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="280">
            <template #default="{ row }">
              <el-button link size="small" @click="openTestProvider(row)">测试</el-button>
              <el-button link size="small" @click="openEditProvider(row)">编辑</el-button>
              <el-button link type="danger" size="small" @click="deleteProvider(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ═════════════════════ Routing ═════════════════════ -->
      <el-tab-pane label="能力路由" name="routing">
        <div class="tab-header">
          <div class="tab-hint">
            能力（capability）→ provider 绑定。每个能力支持多个 priority 级别，0 为主，1/2/3 依次 fallback。
            标 ★ 的是系统当前必需的核心能力。
          </div>
        </div>

        <div v-for="(caps, gkey) in capGroups" :key="gkey" class="cap-group">
          <h3 class="group-title">{{ groupLabel[gkey] || gkey }}</h3>
          <div v-for="cap in caps" :key="cap.key" class="cap-row">
            <div class="cap-header">
              <div class="cap-label">
                <span v-if="cap.required" class="required-star">★</span>
                {{ cap.label }}
                <span class="cap-key">{{ cap.key }}</span>
                <el-tag size="small" :type="cap.kind === 'embedding' ? 'warning' : ''">{{ cap.kind }}</el-tag>
              </div>
              <el-button link type="primary" size="small" @click="openCreateBinding(cap)">+ 添加绑定</el-button>
            </div>
            <div class="cap-bindings">
              <div v-if="!bindingsByCapability[cap.key]?.length" class="muted">
                未绑定（chat 能力会 fallback 到旧版 CONFIG；embedding 未绑定则完全不可用）
              </div>
              <el-table v-else :data="bindingsByCapability[cap.key]" size="small" border>
                <el-table-column label="优先级" width="90">
                  <template #default="{ row }">
                    <el-tag :type="row.priority === 0 ? 'success' : 'info'" size="small">
                      {{ row.priority === 0 ? '主 0' : '备 ' + row.priority }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="provider_name" label="Provider" width="180" />
                <el-table-column prop="model_name" label="Model" />
                <el-table-column label="Params" width="200">
                  <template #default="{ row }">
                    <code class="params-preview">{{ JSON.stringify(row.params) }}</code>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="80">
                  <template #default="{ row }">
                    <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
                      {{ row.enabled ? '启用' : '禁用' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="160">
                  <template #default="{ row }">
                    <el-button link size="small" @click="openEditBinding(cap, row)">编辑</el-button>
                    <el-button link type="danger" size="small" @click="deleteBinding(row)">解绑</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ═════════════════════ Provider 编辑弹窗 ═════════════════════ -->
    <el-dialog v-model="providerDlgVisible"
               :title="providerDlgEditing ? '编辑 Provider' : '新增 Provider'"
               width="560px">
      <el-form :model="providerForm" label-width="110px">
        <el-form-item label="名称">
          <el-input v-model="providerForm.name" placeholder="DeepSeek-Main / SiliconFlow-Embed" />
        </el-form-item>
        <el-form-item label="协议">
          <el-select v-model="providerForm.kind" style="width: 100%">
            <el-option label="OpenAI 兼容" value="openai_compatible" />
            <el-option label="Azure OpenAI" value="azure_openai" />
            <el-option label="Ollama" value="ollama" />
            <el-option label="Anthropic（占位）" value="anthropic" />
            <el-option label="Gemini（占位）" value="gemini" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="providerForm.base_url"
                    placeholder="https://api.deepseek.com/v1 / https://api.siliconflow.cn/v1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="providerForm.api_key" type="password" show-password
                    :placeholder="providerDlgEditing ? '留空表示不修改' : '必填'" />
        </el-form-item>
        <el-form-item label="Extra Config">
          <el-input v-model="providerForm.extra_config_text" type="textarea" :rows="3"
                    placeholder='{"api_version":"2024-02-01"}（Azure 等特殊协议用，一般留空）' />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="providerForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="providerDlgVisible = false">取消</el-button>
        <el-button type="primary" @click="saveProvider">保存</el-button>
      </template>
    </el-dialog>

    <!-- ═════════════════════ Provider 测试弹窗 ═════════════════════ -->
    <el-dialog v-model="testDlgVisible" :title="`测试 Provider：${testDlgTarget?.name || ''}`" width="560px">
      <el-form :model="testForm" label-width="110px">
        <el-form-item label="能力类型">
          <el-radio-group v-model="testForm.capability_kind">
            <el-radio value="chat">chat（测 /v1/chat/completions）</el-radio>
            <el-radio value="embedding">embedding（测 /v1/embeddings）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="Model Name">
          <el-input v-model="testForm.model_name"
                    :placeholder="testForm.capability_kind === 'chat' ? 'deepseek-chat' : 'BAAI/bge-m3'" />
        </el-form-item>
      </el-form>
      <div v-if="testResult" class="test-result">
        <el-alert v-if="testResult.ok" type="success" :closable="false">
          <div>✅ 连接成功，延迟 {{ testResult.latency_ms }} ms</div>
          <div v-if="testResult.capability_kind === 'chat' && testResult.sample">
            首字响应：<code>{{ testResult.sample }}</code>
          </div>
          <div v-if="testResult.capability_kind === 'embedding'">
            探测维度：<strong>{{ testResult.detected_dimension }}</strong>
            （当前 schema：{{ testResult.current_dimension }}）
            <el-tag v-if="testResult.dimension_mismatch" type="warning" size="small">需迁移</el-tag>
            <el-tag v-else type="success" size="small">匹配</el-tag>
          </div>
        </el-alert>
        <el-alert v-else type="error" :closable="false">
          <div>❌ 连接失败</div>
          <div><code>{{ testResult.error }}</code></div>
        </el-alert>
      </div>
      <template #footer>
        <el-button @click="testDlgVisible = false">关闭</el-button>
        <el-button type="primary" :loading="testing" @click="runTest">测试</el-button>
      </template>
    </el-dialog>

    <!-- ═════════════════════ Binding 编辑弹窗 ═════════════════════ -->
    <el-dialog v-model="bindDlgVisible"
               :title="`${bindDlgCapability?.label || ''} - 绑定配置`"
               width="560px">
      <el-form :model="bindForm" label-width="110px">
        <el-form-item label="能力">
          <el-tag>{{ bindDlgCapability?.key }}</el-tag>
          <span class="muted small" style="margin-left:8px">
            {{ bindDlgCapability?.kind }}
          </span>
        </el-form-item>
        <el-form-item label="Provider">
          <el-select v-model="bindForm.provider_id" style="width: 100%">
            <el-option v-for="p in providers.filter(pp => pp.enabled)"
                       :key="p.provider_id"
                       :label="`${p.name}（${p.kind}）`"
                       :value="p.provider_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="Model Name">
          <el-input v-model="bindForm.model_name"
                    placeholder="deepseek-chat / BAAI/bge-m3 / text-embedding-3-small" />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="bindForm.priority" :min="0" :max="10" />
          <span class="muted small" style="margin-left:8px">0=主，1/2/3 依次 fallback</span>
        </el-form-item>
        <el-form-item label="Params">
          <el-input v-model="bindForm.params_text" type="textarea" :rows="3"
                    :placeholder="bindDlgCapability?.kind === 'embedding' ?
                      '{&quot;dimensions&quot;: 1024}（OpenAI text-embedding-3-* 支持）' :
                      '{&quot;temperature&quot;: 0.3, &quot;max_tokens&quot;: 2000}'" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="bindForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindDlgVisible = false">取消</el-button>
        <el-button type="primary" @click="saveBinding">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ai-config-view { padding: 16px 24px; }
.tab-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px;
}
.tab-hint { color: #606266; font-size: 13px; max-width: 800px; line-height: 1.6; }
.masked { font-family: 'Courier New', monospace; color: #606266; }
.muted { color: #909399; }
.small { font-size: 12px; }

.cap-group { margin-bottom: 24px; }
.group-title {
  margin: 16px 0 12px;
  font-size: 15px;
  color: #303133;
  border-left: 3px solid #409eff;
  padding-left: 10px;
}
.cap-row {
  background: #fafafa; border: 1px solid #ebeef5; border-radius: 4px;
  padding: 12px 16px; margin-bottom: 10px;
}
.cap-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 8px;
}
.cap-label {
  display: flex; align-items: center; gap: 10px;
  font-weight: 500;
}
.cap-key {
  font-family: 'Courier New', monospace;
  font-size: 12px; color: #909399;
}
.required-star { color: #f56c6c; font-size: 14px; }
.cap-bindings { margin-top: 4px; }
.params-preview {
  font-family: 'Courier New', monospace;
  font-size: 12px; color: #606266;
}
.test-result { margin-top: 16px; }
</style>
