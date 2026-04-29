<template>
  <div class="health-page">

    <!-- 顶部 Header 区域：状态横幅 + 操作栏合并 -->
    <div class="header-panel">
      <div class="header-status">
        <div class="status-indicator" :class="overallAlertType">
          <el-icon class="status-icon">
            <CircleCheckFilled v-if="overallAlertType === 'success'" />
            <WarningFilled v-else-if="overallAlertType === 'warning'" />
            <CircleCloseFilled v-else-if="overallAlertType === 'error'" />
            <InfoFilled v-else />
          </el-icon>
          <div class="status-text">
            <span class="status-summary">{{ healthData?.overall_summary || '正在加载系统状态…' }}</span>
            <span v-if="healthData" class="status-meta">
              检测时间：{{ formatTime(healthData.checked_at) }}　耗时 {{ healthData.check_duration_ms }}ms
            </span>
          </div>
        </div>
        <div class="header-actions">
          <el-button type="primary" :loading="loading" :icon="Refresh" @click="fetchHealth">
            刷新
          </el-button>
          <el-checkbox v-model="autoRefresh" class="auto-refresh-checkbox">
            每 15 秒自动刷新
          </el-checkbox>
          <div class="service-tags">
            <el-tag
              :type="healthData?.database?.reachable ? 'success' : 'danger'"
              size="small"
              :effect="healthData?.database?.reachable ? 'light' : 'dark'"
            >
              <el-icon><Connection /></el-icon>
              数据库{{ healthData?.database?.reachable ? '正常' : '异常' }}
            </el-tag>
            <el-tag
              :type="healthData?.rabbitmq?.reachable ? 'success' : 'danger'"
              size="small"
              :effect="healthData?.rabbitmq?.reachable ? 'light' : 'dark'"
            >
              <el-icon><Share /></el-icon>
              RabbitMQ{{ healthData?.rabbitmq?.reachable ? '正常' : '异常' }}
            </el-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- 管线异常告警（直接可见，无需切换 Tab） -->
    <el-alert
      v-if="pipelineAlertVisible"
      :type="pipelineAlertType"
      show-icon
      :closable="true"
      class="pipeline-alert"
      @close="pipelineAlertVisible = false"
    >
      <template #title>
        <span v-if="pipelineAlertType === 'error'">处理管线存在严重问题</span>
        <span v-else-if="pipelineAlertType === 'warning'">处理管线需要关注</span>
        <span v-else>处理管线运行中</span>
      </template>
      <template #default>
        <div class="pipeline-alert-body">
          <div class="pipeline-alert-stats">
            <span>文档总数 <b>{{ pipelineSummary.total_documents }}</b></span>
            <span v-if="pipelineSummary.stuck_count">卡住 <b class="text-warning">{{ pipelineSummary.stuck_count }}</b></span>
            <span v-if="pipelineSummary.failed_count">失败 <b class="text-danger">{{ pipelineSummary.failed_count }}</b></span>
          </div>
          <div v-if="pipelineSummary.stuck_documents?.length" class="pipeline-alert-docs">
            <div v-for="doc in pipelineSummary.stuck_documents.slice(0, 3)" :key="doc.document_id" class="pipeline-alert-doc">
              <el-tag :type="doc.severity === 'error' ? 'danger' : 'warning'" size="small" effect="dark">
                {{ doc.status }}
              </el-tag>
              <span class="doc-title">{{ doc.title }}</span>
              <span class="doc-detail">{{ doc.diagnosis?.substring(0, 60) }}…</span>
              <span v-if="doc.error_detail" class="doc-error">
                {{ doc.error_detail.primary_error?.substring(0, 50) }}
              </span>
            </div>
          </div>
          <div v-if="pipelineSummary.recent_failures?.length" class="pipeline-alert-docs">
            <div v-for="doc in pipelineSummary.recent_failures.slice(0, 3)" :key="doc.document_id" class="pipeline-alert-doc">
              <el-tag type="danger" size="small" effect="dark">failed</el-tag>
              <span class="doc-title">{{ doc.title }}</span>
              <span class="doc-detail">{{ doc.error_hint?.substring(0, 80) }}</span>
            </div>
          </div>
          <div class="pipeline-alert-actions">
            <el-button size="small" type="primary" text @click="activeQueueTab = 'pipeline'">
              查看完整管线 →
            </el-button>
            <el-button size="small" type="warning" text @click="goToTasksForPipeline">
              查看相关任务 →
            </el-button>
          </div>
        </div>
      </template>
    </el-alert>

    <!-- 统计卡片行 -->
    <el-row :gutter="12" class="stat-row">
      <el-col :span="4">
        <div class="stat-card" :class="workerStatClass">
          <div class="stat-card-icon">
            <el-icon><Cpu /></el-icon>
          </div>
          <div class="stat-card-body">
            <el-statistic title="Worker 在线" :value="healthData?.workers?.workers?.length || 0" />
          </div>
          <div class="stat-card-badge">
            <el-icon v-if="(healthData?.workers?.workers?.length || 0) > 0"><CircleCheckFilled /></el-icon>
            <el-icon v-else><CircleCloseFilled /></el-icon>
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat-card" :class="queueStatClass">
          <div class="stat-card-icon">
            <el-icon><List /></el-icon>
          </div>
          <div class="stat-card-body">
            <el-statistic title="工作队列" :value="workQueues.length" />
          </div>
          <div class="stat-card-badge">
            <el-icon v-if="queueOverallType === 'success'"><CircleCheckFilled /></el-icon>
            <el-icon v-else-if="queueOverallType === 'warning'"><WarningFilled /></el-icon>
            <el-icon v-else><CircleCloseFilled /></el-icon>
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat-card" :class="pendingStatClass"
          :style="(healthData?.rabbitmq?.total_messages || 0) > 0 ? 'cursor:pointer' : ''"
          :title="(healthData?.rabbitmq?.total_messages || 0) > 0 ? '点击查看运行中的任务' : ''"
          @click="(healthData?.rabbitmq?.total_messages || 0) > 0 && goToRunningTasks()">
          <div class="stat-card-icon">
            <el-icon><Timer /></el-icon>
          </div>
          <div class="stat-card-body">
            <el-statistic title="待处理任务" :value="healthData?.rabbitmq?.total_messages || 0" />
          </div>
          <div class="stat-card-badge">
            <el-icon v-if="(healthData?.rabbitmq?.total_messages || 0) === 0"><CircleCheckFilled /></el-icon>
            <el-icon v-else><WarningFilled /></el-icon>
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat-card" :class="dbLatencyStatClass">
          <div class="stat-card-icon">
            <el-icon><DataLine /></el-icon>
          </div>
          <div class="stat-card-body">
            <el-statistic
              title="数据库延迟"
              :value="healthData?.database?.latency_ms ?? '—'"
              :suffix="healthData?.database?.latency_ms != null ? 'ms' : ''"
            />
          </div>
          <div class="stat-card-badge">
            <el-icon v-if="dbLatencyStatClass === 'stat-healthy'"><CircleCheckFilled /></el-icon>
            <el-icon v-else-if="dbLatencyStatClass === 'stat-warning'"><WarningFilled /></el-icon>
            <el-icon v-else><CircleCloseFilled /></el-icon>
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat-card" :class="pipelineStatClass">
          <div class="stat-card-icon">
            <el-icon><SetUp /></el-icon>
          </div>
          <div class="stat-card-body">
            <el-statistic title="管线文档" :value="pipelineDocTotal" />
          </div>
          <div class="stat-card-badge">
            <el-icon v-if="pipelineStatClass === 'stat-healthy'"><CircleCheckFilled /></el-icon>
            <el-icon v-else><WarningFilled /></el-icon>
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat-card" :class="pipelineFailedStatClass">
          <div class="stat-card-icon">
            <el-icon><CircleCloseFilled /></el-icon>
          </div>
          <div class="stat-card-body">
            <el-statistic title="失败文档" :value="pipelineData?.documents_by_status?.failed ?? '—'" />
          </div>
          <div class="stat-card-badge">
            <el-icon v-if="pipelineFailedStatClass === 'stat-healthy'"><CircleCheckFilled /></el-icon>
            <el-icon v-else><CircleCloseFilled /></el-icon>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- Token 风险提醒（条件显示） -->
    <el-alert
      v-if="healthData?.token_waste?.status === 'warning'"
      type="warning"
      show-icon
      :closable="true"
      class="token-alert"
    >
      <template #title>Token 消耗风险</template>
      <template #default>
        <div
          v-for="(w, i) in healthData.token_waste.warnings"
          :key="i"
          class="token-warning-item"
        >{{ w }}</div>
      </template>
    </el-alert>

    <!-- 主体区域：Workers + 队列 -->
    <el-row :gutter="12" class="main-row">

      <!-- 左列：Workers 状态 -->
      <el-col :span="6">
        <el-card class="workers-card" shadow="never">
          <template #header>
            <div class="card-header">
              <div class="card-header-left">
                <el-icon class="card-header-icon"><Cpu /></el-icon>
                <span class="card-header-title">Celery Workers</span>
              </div>
              <el-tag
                :type="(healthData?.workers?.workers?.length || 0) > 0 ? 'success' : 'danger'"
                size="small"
                effect="plain"
              >
                {{ healthData?.workers?.summary || '加载中' }}
              </el-tag>
            </div>
          </template>

          <div
            v-for="w in (healthData?.workers?.workers || [])"
            :key="w.hostname"
            class="worker-item"
          >
            <div class="worker-header">
              <span class="worker-dot running" />
              <code class="worker-hostname">{{ w.hostname }}</code>
            </div>
            <div class="worker-queues">
              <el-icon class="worker-queues-icon"><Connection /></el-icon>
              {{ w.queue_labels?.join('、') || '无' }}
            </div>
          </div>

          <el-empty
            v-if="!healthData?.workers?.workers?.length"
            description="无在线 Worker"
            :image-size="60"
          />
        </el-card>
      </el-col>

      <!-- 右列：队列 Tabs -->
      <el-col :span="18">
        <el-card class="queues-card" shadow="never">
          <template #header>
            <div class="card-header">
              <div class="card-header-left">
                <el-icon class="card-header-icon"><Grid /></el-icon>
                <span class="card-header-title">消息队列总览</span>
              </div>
              <el-tag :type="queueOverallType" size="small" effect="plain">
                {{ healthData?.rabbitmq?.summary || '加载中' }}
              </el-tag>
            </div>
          </template>

          <el-tabs v-model="activeQueueTab" class="queue-tabs">

            <!-- 工作队列 Tab -->
            <el-tab-pane name="work">
              <template #label>
                <div class="tab-label">
                  <el-icon><List /></el-icon>
                  <span>工作队列</span>
                  <el-badge
                    v-if="workQueues.some(q => q.status === 'error')"
                    type="danger"
                    is-dot
                  />
                  <el-badge
                    v-else-if="workQueues.some(q => q.status === 'warning')"
                    type="warning"
                    is-dot
                  />
                </div>
              </template>
              <el-table :data="workQueues" stripe size="small" class="queue-table">
                <el-table-column label="状态" width="72" align="center">
                  <template #default="{ row }">
                    <el-tag :type="statusTagType(row.status)" size="small" round>
                      {{ statusLabel(row.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="队列" min-width="160">
                  <template #default="{ row }">
                    <div class="queue-name-primary">{{ row.label || row.name }}</div>
                    <div class="queue-name-mono">{{ row.name }}</div>
                  </template>
                </el-table-column>
                <el-table-column label="消息" width="72" align="center">
                  <template #default="{ row }">
                    <el-tag :type="row.messages > 0 ? 'warning' : 'info'" size="small">
                      {{ row.messages }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="消费者" width="72" align="center">
                  <template #default="{ row }">
                    <el-tag :type="row.consumers > 0 ? 'success' : 'danger'" size="small">
                      {{ row.consumers }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="诊断说明" min-width="180">
                  <template #default="{ row }">
                    <div
                      v-for="(e, i) in row.explanations"
                      :key="i"
                      class="explanation-item"
                    >{{ e }}</div>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="130" align="center">
                  <template #default="{ row }">
                    <el-button
                      v-for="(act, i) in (row.actions || [])"
                      :key="i"
                      :type="act.danger ? 'danger' : 'primary'"
                      size="small"
                      text
                      @click="confirmAction(act, row.name)"
                    >{{ act.label }}</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <!-- 事件队列 Tab -->
            <el-tab-pane name="event" v-if="eventQueues.length">
              <template #label>
                <div class="tab-label">
                  <el-icon><Bell /></el-icon>
                  <span>事件队列</span>
                  <el-badge
                    v-if="eventQueues.some(q => q.status === 'warning')"
                    type="warning"
                    is-dot
                  />
                </div>
              </template>
              <p class="tab-description">
                这些队列由 API 进程订阅，用于接收系统事件并触发对应的 Celery 任务。
              </p>
              <el-table :data="eventQueues" stripe size="small" class="queue-table">
                <el-table-column label="状态" width="72" align="center">
                  <template #default="{ row }">
                    <el-tag :type="statusTagType(row.status)" size="small" round>
                      {{ statusLabel(row.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="队列" min-width="180">
                  <template #default="{ row }">
                    <div class="queue-name-primary">{{ row.label || row.name }}</div>
                    <div class="queue-name-mono">{{ row.name }}</div>
                  </template>
                </el-table-column>
                <el-table-column label="消息" width="72" align="center">
                  <template #default="{ row }">
                    <el-tag :type="row.messages > 0 ? 'warning' : 'info'" size="small">
                      {{ row.messages }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="消费者" width="72" align="center">
                  <template #default="{ row }">
                    <el-tag :type="row.consumers > 0 ? 'success' : 'danger'" size="small">
                      {{ row.consumers }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="诊断说明" min-width="200">
                  <template #default="{ row }">
                    <div
                      v-for="(e, i) in row.explanations"
                      :key="i"
                      class="explanation-item"
                    >{{ e }}</div>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <!-- 死信队列 Tab -->
            <el-tab-pane name="dlq" v-if="dlqQueues.length">
              <template #label>
                <div class="tab-label">
                  <el-icon><WarnTriangleFilled /></el-icon>
                  <span>死信队列</span>
                  <el-badge
                    v-if="dlqQueues.some(q => q.messages > 0)"
                    type="danger"
                    is-dot
                  />
                </div>
              </template>
              <p class="tab-description tab-description--danger">
                任务重试多次仍失败后会进入死信队列，需要排查原因后手动处理。
              </p>
              <el-table :data="dlqQueues" stripe size="small" class="queue-table">
                <el-table-column label="状态" width="72" align="center">
                  <template #default="{ row }">
                    <el-tag :type="statusTagType(row.status)" size="small" round>
                      {{ statusLabel(row.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="队列" prop="label" min-width="200" />
                <el-table-column label="失败消息" width="90" align="center">
                  <template #default="{ row }">
                    <el-tag :type="row.messages > 0 ? 'danger' : 'info'" size="small">
                      {{ row.messages }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="说明" min-width="200">
                  <template #default="{ row }">
                    <span class="explanation-item">{{ row.explanations?.join('；') }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="130" align="center">
                  <template #default="{ row }">
                    <el-button
                      v-for="(act, i) in (row.actions || [])"
                      :key="i"
                      :type="act.danger ? 'danger' : 'primary'"
                      size="small"
                      text
                      @click="confirmAction(act, row.name)"
                    >{{ act.label }}</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <!-- 临时队列 Tab -->
            <el-tab-pane name="temp" v-if="tempQueues.length">
              <template #label>
                <div class="tab-label">
                  <el-icon><Files /></el-icon>
                  <span>临时队列 ({{ tempQueues.length }})</span>
                </div>
              </template>
              <div class="temp-tab-header">
                <p class="tab-description">
                  RabbitMQ 内部使用的临时队列，通常无需关注，不影响 Token 消耗。
                </p>
                <el-button
                  v-if="tempQueues.some(q => q.messages > 0)"
                  size="small"
                  type="warning"
                  plain
                  :icon="Delete"
                  @click="confirmPurgeAllTemp"
                >一键清理</el-button>
              </div>
              <el-table :data="tempQueues" stripe size="small" class="queue-table">
                <el-table-column label="队列名" prop="name" min-width="280">
                  <template #default="{ row }">
                    <code class="queue-name-mono">{{ row.name }}</code>
                  </template>
                </el-table-column>
                <el-table-column label="消息" width="72" align="center" prop="messages" />
                <el-table-column label="说明" min-width="200">
                  <template #default="{ row }">
                    <span class="explanation-item explanation-item--muted">
                      {{ row.explanations?.join('；') }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="130" align="center">
                  <template #default="{ row }">
                    <el-button
                      v-for="(act, i) in (row.actions || [])"
                      :key="i"
                      size="small"
                      text
                      type="primary"
                      @click="confirmAction(act, row.name)"
                    >{{ act.label }}</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <!-- 处理管线 Tab -->
            <el-tab-pane name="pipeline">
              <template #label>
                <div class="tab-label">
                  <el-icon><SetUp /></el-icon>
                  <span>处理管线</span>
                  <el-badge
                    v-if="(pipelineData?.documents_by_status?.failed || 0) > 0"
                    type="danger"
                    is-dot
                  />
                  <el-badge
                    v-else-if="(pipelineData?.stuck_documents?.length || 0) > 0"
                    type="warning"
                    is-dot
                  />
                </div>
              </template>

              <!-- 操作栏 -->
              <div class="pipeline-actions">
                <el-button size="small" type="primary" :icon="Refresh" :loading="pipelineLoading" @click="fetchPipelineStatus">
                  刷新管线
                </el-button>
                <el-button
                  v-if="(pipelineData?.documents_by_status?.failed || 0) > 0"
                  size="small" type="warning" plain :icon="WarningFilled"
                  @click="retryAllFailed"
                >重试所有失败 ({{ pipelineData.documents_by_status.failed }})</el-button>
                <el-button
                  size="small" type="info" plain :icon="MagicStick"
                  @click="triggerRecovery"
                >触发系统恢复</el-button>
              </div>

              <!-- 管线阶段流图 -->
              <div class="pipeline-flow">
                <div
                  v-for="(stage, i) in pipelineStages"
                  :key="stage.key"
                  class="pipeline-stage"
                  :class="{ 'has-stuck': stage.hasStuck }"
                >
                  <div class="stage-dot" :class="stage.severity" />
                  <div class="stage-label">{{ stage.label }}</div>
                  <div class="stage-count">
                    <el-tag :type="stage.count > 0 ? 'warning' : 'info'" size="small">
                      {{ stage.count }}
                    </el-tag>
                  </div>
                  <span v-if="!stage.isLast" class="stage-arrow">→</span>
                </div>
              </div>

              <!-- 卡住文档 -->
              <div class="pipeline-section" v-if="pipelineData?.stuck_documents?.length">
                <h4 class="section-title">
                  <el-icon><WarningFilled /></el-icon>
                  卡住的文档 ({{ pipelineData.stuck_documents.length }})
                </h4>
                <el-table :data="pipelineData.stuck_documents" size="small" stripe>
                  <el-table-column label="严重程度" width="80" align="center">
                    <template #default="{ row }">
                      <el-tag :type="row.severity === 'error' ? 'danger' : 'warning'" size="small">
                        {{ row.severity === 'error' ? '严重' : '警告' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="文档" min-width="160">
                    <template #default="{ row }">
                      <div class="queue-name-primary">{{ row.title }}</div>
                      <div class="queue-name-mono">{{ row.document_id }}</div>
                    </template>
                  </el-table-column>
                  <el-table-column label="当前阶段" width="90">
                    <template #default="{ row }">
                      <el-tag size="small">{{ statusLabel(row.status) || row.status }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="空间" prop="space_name" width="100" />
                  <el-table-column label="停留" width="80" align="center">
                    <template #default="{ row }">
                      <el-tag :type="row.hours_stuck > 4 ? 'danger' : row.hours_stuck > 1 ? 'warning' : 'info'" size="small">
                        {{ row.hours_stuck }}h
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="诊断" min-width="220">
                    <template #default="{ row }">
                      <div class="explanation-item">{{ row.diagnosis }}</div>
                      <div v-if="row.error_detail" class="error-detail-chip">
                        <el-tooltip placement="top">
                          <template #content>
                            <div class="error-tooltip">
                              <div>{{ row.error_detail.unique_errors }} 种错误，共 {{ row.error_detail.error_count }} 次</div>
                              <div>涉及阶段: {{ (row.error_detail.steps_affected || []).join(' → ') }}</div>
                              <div v-for="(e, i) in row.error_detail.sample_errors" :key="i" class="error-sample">
                                [{{ e.step }}@chunk#{{ e.index }}] {{ e.error }}
                              </div>
                            </div>
                          </template>
                          <el-tag size="small" type="danger" effect="dark">
                            {{ row.error_detail.primary_error?.substring(0, 60) }}{{ (row.error_detail.primary_error?.length || 0) > 60 ? '…' : '' }}
                          </el-tag>
                        </el-tooltip>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="170" align="center">
                    <template #default="{ row }">
                      <el-button
                        v-if="row.suggested_action && row.suggested_action !== 'retry_ingest'"
                        size="small"
                        type="primary"
                        text
                        @click="retryDocument(row.document_id, row.suggested_action)"
                      >{{ actionLabel(row.suggested_action) }}</el-button>
                      <el-tooltip v-else-if="row.suggested_action === 'retry_ingest'" content="请在文件管理页面使用重新解析功能">
                        <el-tag size="small" type="info">需重新上传</el-tag>
                      </el-tooltip>
                      <el-button
                        size="small"
                        text
                        type="warning"
                        @click="goToTasksForPipeline()"
                      >查看任务</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <!-- 最近失败 -->
              <div class="pipeline-section" v-if="pipelineData?.recent_failures?.length">
                <h4 class="section-title">
                  <el-icon><CircleCloseFilled /></el-icon>
                  最近失败 ({{ pipelineData.recent_failures.length }})
                </h4>
                <el-table :data="pipelineData.recent_failures" size="small" stripe>
                  <el-table-column label="文档" prop="title" min-width="160" />
                  <el-table-column label="失败时间" width="160">
                    <template #default="{ row }">
                      <span class="time-cell">{{ formatTime(row.failed_at) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="距今" width="70" align="center">
                    <template #default="{ row }">
                      {{ row.hours_since_failure }}h
                    </template>
                  </el-table-column>
                  <el-table-column label="错误提示" prop="error_hint" min-width="200" />
                  <el-table-column label="操作" width="140" align="center">
                    <template #default="{ row }">
                      <el-button size="small" type="primary" text @click="retryDocument(row.document_id, 'retry_extraction')">
                        重试
                      </el-button>
                      <el-button size="small" text type="warning" @click="goToTasksForPipeline()">
                        查看任务
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <!-- LLM Provider 状态 -->
              <div class="pipeline-section" v-if="llmStatus">
                <h4 class="section-title">
                  <el-icon><Connection /></el-icon>
                  LLM Provider 状态
                  <el-button size="small" :loading="llmLoading" @click="fetchLlmStatus" text :icon="Refresh" style="margin-left: 8px" />
                </h4>
                <el-table :data="Object.entries(llmStatus.providers || {}).map(([k, v]: [string, any]) => ({ id: k, ...v }))" size="small" stripe>
                  <el-table-column prop="id" label="Provider" width="140" />
                  <el-table-column label="状态" width="80">
                    <template #default="{ row }">
                      <el-tag :type="row.reachable ? 'success' : 'danger'" size="small">
                        {{ row.reachable ? '正常' : '异常' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="model" label="模型" min-width="140" />
                  <el-table-column label="错误" prop="error" min-width="180">
                    <template #default="{ row }">
                      <span class="explanation-item explanation-item--muted">{{ row.error || '—' }}</span>
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <!-- 卡死蓝图 -->
              <div class="pipeline-section" v-if="pipelineData?.stuck_blueprints?.length">
                <h4 class="section-title">
                  <el-icon><Tools /></el-icon>
                  卡死的蓝图 ({{ pipelineData.stuck_blueprints.length }})
                </h4>
                <el-table :data="pipelineData.stuck_blueprints" size="small" stripe>
                  <el-table-column label="空间" prop="space_name" width="120" />
                  <el-table-column label="状态" width="90" align="center">
                    <template #default>
                      <el-tag type="warning" size="small">generating</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="卡住时长" width="90" align="center">
                    <template #default="{ row }">
                      <el-tag :type="row.hours_stuck > 4 ? 'danger' : 'warning'" size="small">
                        {{ row.hours_stuck }}h
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="诊断" prop="diagnosis" min-width="220" />
                  <el-table-column label="操作" width="120" align="center">
                    <template #default="{ row }">
                      <el-button size="small" type="danger" text @click="resetStuckBlueprint(row.blueprint_id)">
                        重置为 draft
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <!-- 空状态 -->
              <el-empty v-if="!pipelineData && !pipelineLoading" description="暂无管线数据，点击上方刷新按钮加载" :image-size="80" />
            </el-tab-pane>

            <!-- 全部文档 Tab -->
            <el-tab-pane name="documents">
              <template #label>
                <div class="tab-label">
                  <el-icon><Document /></el-icon>
                  <span>全部文档</span>
                  <el-badge v-if="docTotal > 0" :value="docTotal" type="info" class="doc-badge" />
                </div>
              </template>

              <!-- 过滤栏 -->
              <div class="doc-filters">
                <el-select v-model="docFilter.status" placeholder="管线状态" clearable size="small" style="width:130px" @change="loadDocuments(1)">
                  <el-option v-for="s in docStatusOptions" :key="s.value" :label="s.label" :value="s.value" />
                </el-select>
                <el-select v-model="docFilter.space_type" placeholder="空间类型" clearable size="small" style="width:110px" @change="loadDocuments(1)">
                  <el-option label="个人" value="personal" />
                  <el-option label="全局" value="global" />
                </el-select>
                <el-select v-model="docFilter.sort_by" size="small" style="width:120px" @change="loadDocuments(1)">
                  <el-option label="创建时间" value="created_at" />
                  <el-option label="更新时间" value="updated_at" />
                  <el-option label="标题" value="title" />
                  <el-option label="状态" value="document_status" />
                  <el-option label="文件大小" value="file_size" />
                </el-select>
                <el-button size="small" :icon="Refresh" @click="loadDocuments()" :loading="docLoading">刷新</el-button>
                <span class="doc-filter-summary" v-if="docTotal > 0">
                  共 {{ docTotal }} 篇，第 {{ docPage }}/{{ docTotalPages }} 页
                </span>
              </div>

              <!-- 文档表格 -->
              <el-table :data="documents" stripe size="small" class="queue-table" v-loading="docLoading">
                <el-table-column label="文档标题" min-width="200" sortable sort-by="title">
                  <template #default="{ row }">
                    <div class="queue-name-primary">{{ row.title }}</div>
                    <div class="queue-name-mono">{{ row.file_name }} · {{ formatFileSize(row.file_size) }}</div>
                  </template>
                </el-table-column>
                <el-table-column label="所属用户" width="140">
                  <template #default="{ row }">
                    <div class="queue-name-primary">{{ row.owner_name }}</div>
                    <div class="queue-name-mono">{{ row.owner_email }}</div>
                  </template>
                </el-table-column>
                <el-table-column label="管线进度" width="170">
                  <template #default="{ row }">
                    <div class="progress-cell">
                      <div class="progress-bar-wrap">
                        <div
                          class="progress-bar-fill"
                          :class="'progress-' + (row.document_status === 'failed' ? 'failed' : row.pipeline_progress >= 100 ? 'done' : 'active')"
                          :style="{ width: row.document_status === 'failed' ? '100%' : row.pipeline_progress + '%' }"
                        />
                      </div>
                      <div class="progress-label">
                        <el-tag
                          :type="statusBadgeType(row.document_status)"
                          size="small"
                          effect="dark"
                        >{{ row.status_label }}</el-tag>
                        <span class="progress-pct">{{ row.document_status === 'failed' ? '✗' : row.pipeline_progress + '%' }}</span>
                      </div>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="空间" width="110">
                  <template #default="{ row }">
                    <div class="queue-name-primary">{{ row.space_name }}</div>
                    <el-tag size="small" :type="row.space_type === 'global' ? 'warning' : 'info'" effect="plain">
                      {{ row.space_type === 'global' ? '全局' : '个人' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="知识点" width="90" align="center">
                  <template #default="{ row }">
                    <span class="knowledge-stat">
                      <span class="knowledge-approved">{{ row.approved_entities }}</span>
                      <span class="knowledge-sep">/</span>
                      <span class="knowledge-pending">{{ row.embedded_entities }}</span>
                    </span>
                    <div class="knowledge-stat-hint">已审/已嵌入</div>
                  </template>
                </el-table-column>
                <el-table-column label="停留/错误" min-width="160">
                  <template #default="{ row }">
                    <div v-if="row.document_status === 'failed'" class="doc-error-cell">
                      <el-tooltip placement="top" :content="row.error_hint" :disabled="!row.error_hint">
                        <span class="error-hint-text">{{ row.error_hint || '未知错误' }}</span>
                      </el-tooltip>
                    </div>
                    <div v-else-if="row.hours_stuck > 1" class="doc-stuck-cell">
                      <el-tag :type="row.hours_stuck > 4 ? 'danger' : 'warning'" size="small">
                        停留 {{ row.hours_stuck }}h
                      </el-tag>
                    </div>
                    <span v-else class="explanation-item--muted">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="更新时间" width="150">
                  <template #default="{ row }">
                    <span class="time-cell">{{ formatTime(row.updated_at) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="140" align="center" fixed="right">
                  <template #default="{ row }">
                    <el-button
                      v-if="row.document_status === 'failed' || row.hours_stuck > 2"
                      size="small" type="primary" text
                      @click="retryDocumentAction(row)"
                    >{{ row.document_status === 'failed' ? '重试' : '解锁重试' }}</el-button>
                    <el-button
                      size="small" type="info" text
                      @click="reparseDocumentAction(row)"
                    >重新解析</el-button>
                  </template>
                </el-table-column>
              </el-table>

              <!-- 分页 -->
              <div class="doc-pagination" v-if="docTotalPages > 1">
                <el-pagination
                  v-model:current-page="docPage"
                  :page-size="docPageSize"
                  :total="docTotal"
                  layout="prev, pager, next, jumper"
                  small
                  background
                  @current-change="loadDocuments"
                />
              </div>
            </el-tab-pane>

          </el-tabs>
        </el-card>
      </el-col>

    </el-row>

    <!-- 底部：课程生成进度 -->
    <el-card class="progress-card" shadow="never">
      <template #header>
        <div class="card-header">
          <div class="card-header-left">
            <el-icon class="card-header-icon"><Reading /></el-icon>
            <span class="card-header-title">课程生成进度</span>
          </div>
          <el-button size="small" text :icon="Refresh" @click="loadBpProgress">
            刷新
          </el-button>
        </div>
      </template>
      <el-table :data="bpSpaces" size="small" class="queue-table">
        <el-table-column prop="name" label="课程名称" min-width="140" />
        <el-table-column label="类型" width="72">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.space_type === 'global' ? 'warning' : 'info'"
              effect="plain"
            >{{ row.space_type === 'global' ? '全局' : '个人' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="知识点" width="120">
          <template #default="{ row }">
            <span class="knowledge-stat">
              <span class="knowledge-approved">{{ row.approved }} 已审</span>
              <span class="knowledge-sep">/</span>
              <span class="knowledge-pending">{{ row.pending }} 待审</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="章节数" prop="chapter_count" width="72" align="center" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.stage === '已完成' ? 'success' : row.stage === '生成中' ? 'warning' : row.stage === '审核中' ? 'info' : ''"
              :effect="row.stage === '生成中' ? 'dark' : 'plain'"
            >
              <el-icon v-if="row.stage === '生成中'" class="is-loading"><Loading /></el-icon>
              {{ row.stage }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="150">
          <template #default="{ row }">
            <span class="time-cell">
              {{ row.bp_updated_at ? new Date(row.bp_updated_at).toLocaleString('zh-CN') : '—' }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Refresh, Monitor, ArrowDown, ArrowUp,
  CircleCheckFilled, WarningFilled, CircleCloseFilled, InfoFilled,
  Connection, Share, Cpu, List, Timer, DataLine, Grid,
  Bell, WarnTriangleFilled, Files, Delete, Reading, Loading,
  SetUp, MagicStick, Tools, VideoPlay, Finished, Document,
} from '@element-plus/icons-vue'
import { http } from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'

const healthData = ref<any>(null)
const loading = ref(false)
const autoRefresh = ref(false)
const activeQueueTab = ref('work')
const pipelineAlertVisible = ref(true)
let timer: any = null
const router = useRouter()

function goToRunningTasks() {
  router.push('/admin/tasks?status=running')
}

function goToTasksForPipeline() {
  router.push('/admin/tasks?status=failed')
}

// ── 管线告警数据（直接来自主 health 响应，无需额外请求）──
const pipelineSummary = computed(() => {
  return healthData.value?.pipeline_summary || {}
})

const pipelineAlertType = computed(() => {
  const s = pipelineSummary.value
  if (s.failed_count > 0) return 'error'
  if (s.stuck_count > 0 || s.has_issues) return 'warning'
  if (s.total_documents > 0) return 'info'
  return ''
})

// ── 管线状态（pipeline Tab 内使用，延迟加载）──────────────
const pipelineData = ref<any>(null)
const pipelineLoading = ref(false)
const llmStatus = ref<any>(null)
const llmLoading = ref(false)

// ── 整体状态 ──────────────────────────────────────────────
const overallAlertType = computed(() => {
  const m: Record<string, string> = { healthy: 'success', warning: 'warning', error: 'error' }
  return m[healthData.value?.overall] || 'info'
})

// ── 队列分组 ──────────────────────────────────────────────
const workQueues = computed<any[]>(() =>
  (healthData.value?.rabbitmq?.queues || []).filter((q: any) => q.category === 'work')
)
const eventQueues = computed<any[]>(() =>
  (healthData.value?.rabbitmq?.queues || []).filter((q: any) => q.category === 'event')
)
const dlqQueues = computed<any[]>(() =>
  (healthData.value?.rabbitmq?.queues || []).filter((q: any) => q.category === 'dlq')
)
const tempQueues = computed<any[]>(() =>
  (healthData.value?.rabbitmq?.queues || []).filter((q: any) => q.category === 'temp' || q.category === 'unknown')
)

// ── 统计卡片颜色状态 ──────────────────────────────────────
const queueOverallType = computed(() => {
  if (workQueues.value.some((q: any) => q.status === 'error')) return 'danger'
  if (workQueues.value.some((q: any) => q.status === 'warning')) return 'warning'
  return 'success'
})

const workerStatClass = computed(() =>
  (healthData.value?.workers?.workers?.length || 0) > 0 ? 'stat-healthy' : 'stat-error'
)
const queueStatClass = computed(() => ({
  success: 'stat-healthy',
  warning: 'stat-warning',
  danger: 'stat-error',
}[queueOverallType.value] || 'stat-healthy'))

const pendingStatClass = computed(() => {
  const n = healthData.value?.rabbitmq?.total_messages || 0
  if (n === 0) return 'stat-healthy'
  if (n < 200) return 'stat-warning'
  return 'stat-error'
})

const dbLatencyStatClass = computed(() => {
  if (!healthData.value?.database?.reachable) return 'stat-error'
  const ms = healthData.value?.database?.latency_ms ?? 0
  if (ms < 100) return 'stat-healthy'
  if (ms < 500) return 'stat-warning'
  return 'stat-error'
})

// ── 管线统计卡片 ──────────────────────────────────────────
const pipelineStatClass = computed(() => {
  const stuck = pipelineData.value?.stuck_documents?.length || 0
  const failed = pipelineData.value?.documents_by_status?.failed || 0
  if (failed > 0 || stuck > 0) return 'stat-warning'
  return 'stat-healthy'
})

const pipelineFailedStatClass = computed(() => {
  const failed = pipelineData.value?.documents_by_status?.failed || 0
  if (failed > 0) return 'stat-error'
  return 'stat-healthy'
})

const pipelineDocTotal = computed(() => {
  const counts: Record<string, number> = pipelineData.value?.documents_by_status || {}
  return Object.values(counts).reduce((a: number, b) => a + (Number(b) || 0), 0) || '—'
})

// ── 管线阶段流图 ──────────────────────────────────────────
const pipelineStages = computed(() => {
  const stages = [
    { key: 'uploaded',  label: '已上传' },
    { key: 'parsed',    label: '已解析' },
    { key: 'extracted', label: '已提取' },
    { key: 'embedding', label: '嵌入中' },
    { key: 'reviewed',  label: '已审核' },
    { key: 'published', label: '已发布' },
  ]
  return stages.map((s, i) => {
    const count = pipelineData.value?.documents_by_status?.[s.key] || 0
    const stuckThresholds: Record<string, number> = {
      uploaded: 60, parsed: 30, extracted: 60, embedding: 120, reviewed: 240,
    }
    const isActive = count > 0 && s.key in stuckThresholds
    const hasStuck = pipelineData.value?.stuck_documents?.some((d: any) => d.status === s.key)
    return {
      ...s,
      isLast: i === stages.length - 1,
      count,
      isActive,
      hasStuck: !!hasStuck,
      severity: hasStuck ? 'error' : isActive ? 'warning' : 'healthy',
    }
  })
})

// ── 工具函数 ──────────────────────────────────────────────
function statusTagType(status: string) {
  return ({ healthy: 'success', warning: 'warning', error: 'danger', info: 'info' } as Record<string, string>)[status] || 'info'
}

function statusLabel(status: string) {
  return ({ healthy: '正常', warning: '警告', error: '异常', info: '信息' } as Record<string, string>)[status] || status
}

function formatTime(iso: string) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}

// ── 数据请求 ──────────────────────────────────────────────
async function fetchHealth() {
  loading.value = true
  try {
    const { data } = await http.get('/admin/health')
    healthData.value = data ?? null
  } catch (err) {
    console.error('Health check failed:', err)
  } finally {
    loading.value = false
  }
}

watch(autoRefresh, (val) => {
  if (timer) { clearInterval(timer); timer = null }
  if (val) timer = setInterval(fetchHealth, 15000)
})

// ── 队列操作 ──────────────────────────────────────────────
async function confirmAction(act: any, queueName: string) {
  try {
    await ElMessageBox.confirm(act.confirm, '操作确认', {
      confirmButtonText: '确认执行',
      cancelButtonText: '取消',
      type: act.danger ? 'warning' : 'info',
    })
  } catch { return }

  try {
    if (act.action === 'purge_queue') {
      await http.post('/admin/health/purge-queue', { queue_name: queueName })
      ElMessage.success('队列已清空')
    } else if (act.action === 'delete_queue') {
      await http.post('/admin/health/delete-queue', { queue_name: queueName })
      ElMessage.success('队列已删除')
    } else if (act.action === 'restart_worker') {
      ElMessage.info('Worker 重启功能需要服务器端 docker 权限，建议通过命令行执行: docker compose restart ' + (act.params?.service || ''))
      return
    }
    fetchHealth()
  } catch (err) {
    ElMessage.error('操作失败: ' + ((err as any)?.response?.data?.data?.message || (err as any)?.message || '未知错误'))
  }
}

async function confirmPurgeAllTemp() {
  try {
    await ElMessageBox.confirm('确认清理所有无用的临时队列？', '一键清理', {
      confirmButtonText: '确认清理',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch { return }

  try {
    const { data } = await http.post('/admin/health/purge-all-temp')
    ElMessage.success(data?.message || '清理完成')
    fetchHealth()
  } catch (err) {
    ElMessage.error('操作失败: ' + ((err as any)?.response?.data?.data?.message || (err as any)?.message || '未知错误'))
  }
}

// ── 管线数据请求 ──────────────────────────────────────────
async function fetchPipelineStatus() {
  pipelineLoading.value = true
  try {
    const { data } = await http.get('/admin/health/pipeline-status')
    pipelineData.value = data ?? null
  } catch (err) {
    console.error('Pipeline status fetch failed:', err)
  } finally {
    pipelineLoading.value = false
  }
}

async function fetchLlmStatus() {
  llmLoading.value = true
  try {
    const { data } = await http.get('/admin/health/llm-status')
    llmStatus.value = data ?? null
  } catch (err) {
    console.error('LLM status fetch failed:', err)
  } finally {
    llmLoading.value = false
  }
}

// ── 管线操作 ──────────────────────────────────────────────
function actionLabel(action: string): string {
  const labels: Record<string, string> = {
    retry_extraction:         '重新提取实体',
    retry_ingest:             '重新解析文档',
    retry_review:             '重新触发审核',
    retry_blueprint:          '重新生成蓝图',
    retry_backfill_embeddings: '补填 Embedding',
  }
  return labels[action] || action
}

async function retryDocument(docId: string, action: string) {
  try {
    await ElMessageBox.confirm(
      `确认对此文档执行「${actionLabel(action)}」操作？`,
      '操作确认',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }

  try {
    const { data } = await http.post('/admin/health/retry-stuck', {
      document_id: docId,
      action,
    })
    ElMessage.success(data?.message || '操作已提交')
    fetchPipelineStatus()
  } catch (err) {
    ElMessage.error('操作失败: ' + ((err as any)?.response?.data?.data?.message || (err as any)?.message || '未知错误'))
  }
}

async function retryAllFailed() {
  try {
    await ElMessageBox.confirm(
      '确认重试所有失败的文档？这将把 failed 状态重置为 parsed 并重新触发提取任务。',
      '批量重试确认',
      { confirmButtonText: '确认重试全部', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }

  try {
    const { data } = await http.post('/admin/health/retry-all-failed')
    ElMessage.success(data?.message || '操作已提交')
    fetchPipelineStatus()
  } catch (err) {
    ElMessage.error('操作失败: ' + ((err as any)?.response?.data?.data?.message || (err as any)?.message || '未知错误'))
  }
}

async function triggerRecovery() {
  try {
    await ElMessageBox.confirm(
      '手动触发系统恢复任务？系统将：\n1) 检查 pending 实体 → 派发审核\n2) 重置卡死的 generating blueprint\n3) 补派发缺失的提取任务',
      '触发系统恢复',
      { confirmButtonText: '确认触发', cancelButtonText: '取消', type: 'info' }
    )
  } catch { return }

  try {
    const { data } = await http.post('/admin/health/trigger-recovery')
    ElMessage.success(data?.message || '恢复任务已触发')
  } catch (err) {
    ElMessage.error('触发失败: ' + ((err as any)?.response?.data?.data?.message || (err as any)?.message || '未知错误'))
  }
}

async function resetStuckBlueprint(bpId: string) {
  try {
    await ElMessageBox.confirm(
      '确认重置此卡死的蓝图？重置后系统恢复任务将重新触发生成。',
      '重置蓝图',
      { confirmButtonText: '确认重置', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }

  try {
    const { data } = await http.post('/admin/health/reset-stuck-blueprint', { blueprint_id: bpId })
    ElMessage.success(data?.message || '蓝图已重置')
    fetchPipelineStatus()
  } catch (err) {
    ElMessage.error('操作失败: ' + ((err as any)?.response?.data?.data?.message || (err as any)?.message || '未知错误'))
  }
}

// ── 课程进度 ──────────────────────────────────────────────
const bpSpaces = ref([] as any[])

async function loadBpProgress() {
  try {
    const res = await http.get('/admin/health/blueprint-progress')
    bpSpaces.value = res.data?.spaces || []
  } catch {}
}

// ── 全部文档 Tab ──────────────────────────────────────────
const documents = ref([] as any[])
const docTotal = ref(0)
const docPage = ref(1)
const docPageSize = ref(50)
const docTotalPages = ref(1)
const docLoading = ref(false)

const docFilter = ref({
  status: '',
  space_type: '',
  sort_by: 'created_at' as string,
})

const docStatusOptions = [
  { label: '已上传', value: 'uploaded' },
  { label: '已解析', value: 'parsed' },
  { label: '已提取', value: 'extracted' },
  { label: '嵌入中', value: 'embedding' },
  { label: '已审核', value: 'reviewed' },
  { label: '已发布', value: 'published' },
  { label: '失败', value: 'failed' },
]

function statusBadgeType(status: string): string {
  if (status === 'published' || status === 'reviewed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'embedding' || status === 'extracted') return 'warning'
  return 'info'
}

function formatFileSize(bytes: number | null | undefined): string {
  if (bytes == null) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

async function loadDocuments(page?: number) {
  if (page !== undefined) docPage.value = page
  docLoading.value = true
  try {
    const params: any = {
      page: docPage.value,
      page_size: docPageSize.value,
      sort_by: docFilter.value.sort_by,
      sort_order: 'desc',
    }
    if (docFilter.value.status) params.status = docFilter.value.status
    if (docFilter.value.space_type) params.space_type = docFilter.value.space_type

    const { data } = await http.get('/files/all-documents', { params })
    if (data) {
      documents.value = data.documents || []
      docTotal.value = data.total || 0
      docTotalPages.value = data.total_pages || 1
    }
  } catch (err) {
    console.error('Load documents failed:', err)
  } finally {
    docLoading.value = false
  }
}

async function retryDocumentAction(row: any) {
  const action = row.document_status === 'failed' ? 'retry_extraction' : 'retry_extraction'
  try {
    await ElMessageBox.confirm(
      `确认对文档「${row.title}」执行重试操作？`,
      '操作确认',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }

  try {
    const { data } = await http.post('/admin/health/retry-stuck', {
      document_id: row.document_id,
      action,
    })
    ElMessage.success(data?.message || '已触发重试')
    loadDocuments()
  } catch (err) {
    ElMessage.error('操作失败: ' + ((err as any)?.response?.data?.data?.message || (err as any)?.message || '未知错误'))
  }
}

async function reparseDocumentAction(row: any) {
  try {
    await ElMessageBox.confirm(
      `确认对文档「${row.title}」执行重新解析？这将重新提取文档内容。`,
      '操作确认',
      { confirmButtonText: '确认重新解析', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }

  try {
    const { data } = await http.post(`/files/reparse/${row.document_id}`)
    ElMessage.success(data?.message || data?.msg || '已触发重新解析')
    loadDocuments()
  } catch (err) {
    ElMessage.error('操作失败: ' + ((err as any)?.response?.data?.data?.message || (err as any)?.message || '未知错误'))
  }
}

onMounted(() => {
  fetchHealth()
  loadBpProgress()
  fetchPipelineStatus()
  fetchLlmStatus()
  loadDocuments()
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
/* ── 页面根容器 ─────────────────────────────────────────── */
.health-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px 0;
}

/* ── Header 面板 ────────────────────────────────────────── */
.header-panel {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 16px 20px;
}

.header-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.status-icon {
  font-size: 28px;
  flex-shrink: 0;
}

.status-indicator.success .status-icon { color: var(--el-color-success); }
.status-indicator.warning .status-icon { color: var(--el-color-warning); }
.status-indicator.error   .status-icon { color: var(--el-color-danger); }
.status-indicator.info    .status-icon { color: var(--el-color-info); }

.status-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.status-summary {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.status-meta {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.auto-refresh-checkbox {
  height: 32px;
}

.service-tags {
  display: flex;
  gap: 6px;
}

.service-tags .el-tag {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ── 统计卡片 ────────────────────────────────────────────── */
.stat-row {
  /* margin handled by parent gap */
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
  position: relative;
  overflow: hidden;
  transition: box-shadow 0.2s;
}

.stat-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  border-radius: 8px 0 0 8px;
}

.stat-card.stat-healthy::before { background: var(--el-color-success); }
.stat-card.stat-warning::before { background: var(--el-color-warning); }
.stat-card.stat-error::before   { background: var(--el-color-danger); }

.stat-card-icon {
  font-size: 28px;
  flex-shrink: 0;
}
.stat-card.stat-healthy .stat-card-icon { color: var(--el-color-success); }
.stat-card.stat-warning .stat-card-icon { color: var(--el-color-warning); }
.stat-card.stat-error   .stat-card-icon { color: var(--el-color-danger); }

.stat-card-body {
  flex: 1;
  min-width: 0;
}

.stat-card-badge {
  position: absolute;
  top: 10px;
  right: 12px;
  font-size: 16px;
  opacity: 0.7;
}
.stat-card.stat-healthy .stat-card-badge { color: var(--el-color-success); }
.stat-card.stat-warning .stat-card-badge { color: var(--el-color-warning); }
.stat-card.stat-error   .stat-card-badge { color: var(--el-color-danger); }

/* ── 管线告警 ─────────────────────────────────────────── */
.pipeline-alert {
  margin-bottom: 12px;
}

.pipeline-alert-body {
  font-size: 13px;
}

.pipeline-alert-stats {
  display: flex;
  gap: 16px;
  margin-bottom: 8px;
}

.pipeline-alert-stats .text-warning { color: var(--el-color-warning); }
.pipeline-alert-stats .text-danger  { color: var(--el-color-danger); }

.pipeline-alert-docs {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 4px;
}

.pipeline-alert-doc {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.pipeline-alert-doc .doc-title {
  font-weight: 600;
  color: var(--el-text-color-primary);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pipeline-alert-doc .doc-detail,
.pipeline-alert-doc .doc-error {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pipeline-alert-doc .doc-error {
  color: var(--el-color-danger);
}

.pipeline-alert-actions {
  margin-top: 8px;
}

/* ── Token 警告 ─────────────────────────────────────────── */
.token-alert {
  /* gap handled by parent */
}

.token-warning-item {
  font-size: 13px;
  margin-top: 4px;
  line-height: 1.6;
}

/* ── 主体行 ─────────────────────────────────────────────── */
.main-row {
  align-items: flex-start;
}

/* ── 通用卡片 Header ─────────────────────────────────────── */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.card-header-icon {
  font-size: 16px;
  color: var(--el-color-primary);
}

.card-header-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

/* ── Workers 卡片 ────────────────────────────────────────── */
.workers-card {
  height: 100%;
}

.worker-item {
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  margin-bottom: 8px;
  transition: border-color 0.15s;
}

.worker-item:last-child {
  margin-bottom: 0;
}

.worker-item:hover {
  border-color: var(--el-color-primary-light-5);
}

.worker-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.worker-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.worker-dot.running {
  background: var(--el-color-success);
  box-shadow: 0 0 6px rgba(103, 194, 58, 0.5);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 4px rgba(103, 194, 58, 0.4); }
  50%       { box-shadow: 0 0 10px rgba(103, 194, 58, 0.7); }
}

.worker-hostname {
  font-size: 12px;
  font-family: monospace;
  font-weight: 600;
  color: var(--el-text-color-primary);
  word-break: break-all;
}

.worker-queues {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: 16px;
}

.worker-queues-icon {
  font-size: 12px;
  flex-shrink: 0;
}

/* ── 队列 Tabs ──────────────────────────────────────────── */
.queues-card {
  /* full width */
}

.queue-tabs {
  margin-top: -4px;
}

.tab-label {
  display: flex;
  align-items: center;
  gap: 5px;
}

.tab-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 0 0 8px 0;
  line-height: 1.6;
}

.tab-description--danger {
  color: var(--el-color-danger);
}

.temp-tab-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.temp-tab-header .tab-description {
  margin: 0;
}

/* ── 队列表格通用 ────────────────────────────────────────── */
.queue-table {
  width: 100%;
}

.queue-name-primary {
  font-weight: 600;
  font-size: 13px;
  color: var(--el-text-color-primary);
}

.queue-name-mono {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-family: monospace;
  margin-top: 2px;
}

.explanation-item {
  font-size: 12px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
  display: block;
}

.explanation-item--muted {
  color: var(--el-text-color-secondary);
}

/* ── 课程进度卡片 ────────────────────────────────────────── */
.progress-card {
  /* gap handled by parent */
}

.knowledge-stat {
  font-size: 12px;
  white-space: nowrap;
}

.knowledge-approved {
  color: var(--el-color-success);
  font-weight: 600;
}

.knowledge-sep {
  color: var(--el-text-color-placeholder);
  margin: 0 3px;
}

.knowledge-pending {
  color: var(--el-text-color-secondary);
}

.time-cell {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-family: monospace;
}

/* ── 管线 Tab ─────────────────────────────────────────────── */
.pipeline-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.pipeline-flow {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 14px 10px;
  margin-bottom: 16px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  overflow-x: auto;
  flex-wrap: nowrap;
}

.pipeline-stage {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  padding: 4px 6px;
  border-radius: 4px;
  transition: background 0.2s;
}

.pipeline-stage.has-stuck {
  background: var(--el-color-warning-light-9);
  border: 1px dashed var(--el-color-warning-light-5);
}

.stage-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.stage-dot.healthy  { background: var(--el-color-success); }
.stage-dot.warning  { background: var(--el-color-warning); }
.stage-dot.error    { background: var(--el-color-danger); }

.stage-label {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  color: var(--el-text-color-primary);
}

.stage-count {
  flex-shrink: 0;
}

.stage-arrow {
  margin: 0 8px;
  font-size: 16px;
  font-weight: 700;
  color: var(--el-text-color-placeholder);
  user-select: none;
}

.pipeline-section {
  margin-bottom: 16px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  margin: 0 0 8px 0;
  color: var(--el-text-color-primary);
}

.section-title .el-icon {
  color: var(--el-color-warning);
}

/* ── 错误详情 ────────────────────────────────────────────── */
.error-detail-chip {
  margin-top: 4px;
}

.error-detail-chip .el-tag {
  cursor: help;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.error-tooltip {
  max-width: 400px;
  font-size: 12px;
  line-height: 1.6;
}

/* ── 全部文档 Tab ────────────────────────────────────────── */
.doc-badge {
  margin-left: 2px;
}

.doc-badge .el-badge__content {
  font-size: 10px;
}

.doc-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.doc-filter-summary {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: auto;
}

.progress-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.progress-bar-wrap {
  width: 100%;
  height: 6px;
  background: var(--el-fill-color-light);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-bar-fill.progress-active {
  background: linear-gradient(90deg, var(--el-color-primary), var(--el-color-primary-light-3));
}

.progress-bar-fill.progress-done {
  background: var(--el-color-success);
}

.progress-bar-fill.progress-failed {
  background: var(--el-color-danger);
}

.progress-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.progress-pct {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  font-family: monospace;
}

.doc-error-cell {
  max-width: 200px;
}

.error-hint-text {
  font-size: 11px;
  color: var(--el-color-danger);
  cursor: help;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.5;
}

.doc-stuck-cell {
  white-space: nowrap;
}

.knowledge-stat-hint {
  font-size: 10px;
  color: var(--el-text-color-placeholder);
}

.doc-pagination {
  display: flex;
  justify-content: center;
  margin-top: 14px;
  padding-top: 8px;
}

.error-sample {
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px solid rgba(255,255,255,0.15);
  font-family: monospace;
  font-size: 11px;
  word-break: break-all;
}
</style>
