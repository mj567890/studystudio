<template>
  <div class="page">
    <el-row :gutter="16">
      <!-- 系统配置 -->
      <el-col :span="14">
        <el-card v-loading="loading">
          <template #header>系统配置</template>

          <el-form label-width="160px" size="default">
            <el-form-item label="默认 LLM 模型">
              <el-select v-model="configs.llm_default_model" style="width:100%">
                <el-option label="deepseek-chat（推荐）" value="deepseek-chat" />
                <el-option label="deepseek-reasoner（推理增强）" value="deepseek-reasoner" />
                <el-option label="gpt-4o" value="gpt-4o" />
                <el-option label="gpt-4o-mini（轻量）" value="gpt-4o-mini" />
              </el-select>
            </el-form-item>

            <el-form-item label="每日 Token 预算">
              <el-input-number v-model="configs.daily_token_budget"
                :min="100000" :max="10000000" :step="100000"
                style="width:100%" />
              <p style="font-size:12px;color:#909399;margin-top:4px">
                当前设置：{{ Number(configs.daily_token_budget).toLocaleString() }} tokens/天
              </p>
            </el-form-item>

            <el-form-item label="单文档最大分块数">
              <el-input-number v-model="configs.max_chunk_count"
                :min="100" :max="2000" :step="100" style="width:100%" />
            </el-form-item>

            <el-divider content-position="left">知识提取参数</el-divider>
            <p style="font-size:12px;color:#909399;margin-bottom:12px">
              控制 LLM 提取实体/分类/关系时传入的文本长度上限。如果遇到 "Context size exceeded" 错误，适当调低这些值。
            </p>

            <el-form-item label="实体识别截断上限">
              <el-input-number v-model="configs['extraction.truncation.entity']"
                :min="500" :max="5000" :step="100" style="width:100%" />
              <p style="font-size:12px;color:#909399;margin-top:4px">传给 LLM 的文本最大字符数（步骤 1：从 chunk 中识别知识点）</p>
            </el-form-item>

            <el-form-item label="实体分类截断上限">
              <el-input-number v-model="configs['extraction.truncation.classify']"
                :min="500" :max="5000" :step="100" style="width:100%" />
              <p style="font-size:12px;color:#909399;margin-top:4px">传给 LLM 的文本最大字符数（步骤 2：知识点分类与定义）</p>
            </el-form-item>

            <el-form-item label="关系提取截断上限">
              <el-input-number v-model="configs['extraction.truncation.relation']"
                :min="500" :max="5000" :step="100" style="width:100%" />
              <p style="font-size:12px;color:#909399;margin-top:4px">传给 LLM 的文本最大字符数（步骤 3：知识点关系识别）</p>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="saving" @click="saveAll">保存配置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <!-- 初始化操作 -->
      <el-col :span="10">
        <el-card>
          <template #header>系统初始化</template>

          <div class="init-item">
            <div class="init-info">
              <h4>导入种子知识库</h4>
              <p>导入系统内置的示例知识点，让学习者有内容可学。</p>
            </div>
            <el-button type="primary" :loading="seeding" @click="doSeed">
              一键导入
            </el-button>
          </div>

          <el-divider />

          <div class="init-item">
            <div class="init-info">
              <h4>预生成冷启动题库</h4>
              <p>为所有领域预生成定位自检题目，提升首次进入速度。</p>
            </div>
            <el-button :loading="prebuilding" @click="doPrebuild">
              触发生成
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

const loading     = ref(false)
const saving      = ref(false)
const seeding     = ref(false)
const prebuilding = ref(false)

const configs = ref<Record<string, any>>({
  llm_default_model:               'deepseek-chat',
  daily_token_budget:              2000000,
  max_chunk_count:                 500,
  'extraction.truncation.entity':   2000,
  'extraction.truncation.classify': 1500,
  'extraction.truncation.relation': 1500,
})

async function load() {
  loading.value = true
  try {
    const res: any = await adminApi.getSystemConfigs()
    const data = res.data?.configs || {}
    for (const key of Object.keys(configs.value)) {
      if (data[key]) {
        configs.value[key] = isNaN(Number(data[key].value))
          ? data[key].value
          : Number(data[key].value)
      }
    }
  } finally { loading.value = false }
}

async function saveAll() {
  saving.value = true
  try {
    for (const [key, value] of Object.entries(configs.value)) {
      await adminApi.updateConfig({ config_key: key, config_value: String(value) })
    }
    ElMessage.success('配置已保存')
  } finally { saving.value = false }
}

async function doSeed() {
  seeding.value = true
  try {
    const res: any = await adminApi.seedKnowledge()
    ElMessage.success(res.data?.message || '种子知识库导入完成')
  } finally { seeding.value = false }
}

async function doPrebuild() {
  prebuilding.value = true
  try {
    const res: any = await adminApi.prebuildBanks()
    ElMessage.success(res.data?.message || '题库生成任务已触发')
  } finally { prebuilding.value = false }
}

onMounted(load)
</script>

<style scoped>
.page { padding: 8px; }
.init-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
.init-info h4 { margin: 0 0 4px; font-size: 14px; }
.init-info p  { margin: 0; font-size: 12px; color: #909399; }
</style>
