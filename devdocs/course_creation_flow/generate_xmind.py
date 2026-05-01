"""
StudyStudio 课程制作全流程 — XMind 思维导图生成器
直接写 XMind 格式（ZIP + content.xml），不依赖第三方库。
输出：StudyStudio_思维导图.xmind
"""
import os, zipfile, uuid

out_dir = os.path.dirname(os.path.abspath(__file__))
out_path = os.path.join(out_dir, 'StudyStudio_思维导图.xmind')

# ── content.xml ──
# XMind 核心格式：<xmap-content> → <sheet> → <topic> 递归
content_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<xmap-content xmlns="urn:xmind:xmap:xmlns:content:2.0" xmlns:fo="http://www.w3.org/1999/XSL/Format" xmlns:xhtml="http://www.w3.org/1999/xhtml" timestamp="1714000000000" version="2.0">
<sheet id="sheet-root" timestamp="1714000000000">
<title>StudyStudio 课程制作全流程</title>
<topic id="root-topic" structure-class="org.xmind.ui.map.unbalanced" timestamp="1714000000000">
<title>StudyStudio\n课程制作全流程</title>
<children>

<!-- ===== 一、前端入口 ===== -->
<topic id="frontend">
<title>前端入口</title>
<children>
<topic id="upload-view">
<title>UploadView.vue（文件上传）</title>
<children>
<topic><title>支持格式：PDF / DOCX / MD / TXT</title></topic>
<topic><title>最大 100MB</title></topic>
<topic><title>FormData 封装 → fileApi.upload()</title></topic>
</children>
</topic>
<topic id="tutorial-view">
<title>TutorialView.vue（课程学习）</title>
<children>
<topic id="read-modes">
<title>三种阅读模式</title>
<children>
<topic><title>速览 → skim_summary 要点</title></topic>
<topic><title>正常 → 完整正文 + CHECKPOINT 断点</title></topic>
<topic><title>深度 → 正文 + prereq_adaptive 扩展</title></topic>
</children>
</topic>
<topic id="interact">
<title>互动功能</title>
<children>
<topic><title>章节测验 → ≥60% 自动标记已读</title></topic>
<topic><title>AI 反思 → LLM 评判理解总结</title></topic>
<topic><title>社交笔记 → 每章独立笔记区 + 点赞</title></topic>
<topic><title>源文档追溯 → 查看原始文档片段</title></topic>
<topic><title>关联推荐 + 证书下载</title></topic>
</children>
</topic>
</children>
</topic>
</children>
</topic>

<!-- ===== 二、10 阶段流水线 ===== -->
<topic id="pipeline">
<title>10 阶段自动化流水线</title>
<children>

<!-- 阶段 1 -->
<topic id="stage1">
<title>阶段1：文件上传与存储</title>
<children>
<topic id="s1-validation">
<title>安全校验</title>
<children>
<topic><title>Content-Type 白名单检查</title></topic>
<topic><title>文件名安全过滤（防路径穿越）</title></topic>
</children>
</topic>
<topic id="s1-dedup">
<title>SHA-256 去重</title>
<children>
<topic><title>同文件同空间 → 复用已有记录</title></topic>
<topic><title>同文件不同空间 → 新建文档记录</title></topic>
</children>
</topic>
<topic id="s1-minio">
<title>MinIO 对象存储</title>
<children>
<topic><title>键格式：files/{file_id}/{safe_filename}</title></topic>
<topic><title>AsyncMinIOClient 异步封装</title></topic>
</children>
</topic>
<topic id="s1-event">
<title>事件发布 + 状态</title>
<children>
<topic><title>EventBus → RabbitMQ</title></topic>
<topic><title>file_uploaded 事件</title></topic>
<topic><title>文档状态 → uploaded</title></topic>
</children>
</topic>
<topic><title>端点: POST /api/files/upload</title></topic>
</children>
</topic>

<!-- 阶段 2 -->
<topic id="stage2">
<title>阶段2：事件驱动任务调度</title>
<children>
<topic id="s2-rabbit">
<title>RabbitMQ 订阅（main.py startup）</title>
<children>
<topic><title>file_uploaded → knowledge.ingest.queue → run_ingest</title></topic>
<topic><title>document_parsed → knowledge.extraction.queue → run_extraction</title></topic>
</children>
</topic>
<topic id="s2-celery">
<title>Celery 5 个专用队列</title>
<children>
<topic><title>knowledge（解析 + 提取 + 向量化）</title></topic>
<topic><title>knowledge.review（自动审核）</title></topic>
<topic><title>tutorial（教程相关）</title></topic>
<topic><title>blueprint.synthesis（蓝图合成）</title></topic>
<topic><title>low_priority（低优先级）</title></topic>
</children>
</topic>
<topic id="s2-timeout">
<title>超时策略</title>
<children>
<topic><title>ingest: 180s soft / 240s hard</title></topic>
<topic><title>extraction: 无限制</title></topic>
<topic><title>review: 600s soft / 720s hard</title></topic>
</children>
</topic>
</children>
</topic>

<!-- 阶段 3 -->
<topic id="stage3">
<title>阶段3：文档解析与文本分块</title>
<children>
<topic id="s3-engines">
<title>多格式解析引擎</title>
<children>
<topic><title>PDF → PyMuPDF (fitz) 按物理页 + TOC 大纲</title></topic>
<topic><title>DOCX → python-docx 段落级提取</title></topic>
<topic><title>MD/TXT → charset 检测解码</title></topic>
</children>
</topic>
<topic id="s3-split">
<title>文本分块</title>
<children>
<topic><title>LangChain RecursiveCharacterTextSplitter</title></topic>
<topic><title>每页独立分块（保留页面边界）</title></topic>
<topic><title>元数据: index_no / title_path / page_no / token_count</title></topic>
</children>
</topic>
<topic id="s3-trunc">
<title>截断保护</title>
<children>
<topic><title>MAX_CHUNK_COUNT = 500</title></topic>
<topic><title>超出标记 is_truncated</title></topic>
<topic><title>批量 INSERT document_chunks（50/批）</title></topic>
</children>
</topic>
<topic><title>状态: uploaded → parsed → 发布 document_parsed</title></topic>
</children>
</topic>

<!-- 阶段 4 -->
<topic id="stage4">
<title>阶段4：知识提取（三步 LLM 流水线）</title>
<children>
<topic id="s4-lock">
<title>🔒 原子锁</title>
<children>
<topic><title>UPDATE documents SET status='extracting'</title></topic>
<topic><title>WHERE NOT IN(extracting,extracted...)</title></topic>
<topic><title>RETURNING document_id::text</title></topic>
</children>
</topic>
<topic id="s4-step1">
<title>Step 1 — 实体识别</title>
<children>
<topic><title>Prompt: ENTITY_RECOGNITION_PROMPT</title></topic>
<topic><title>输出: 实体名称列表</title></topic>
</children>
</topic>
<topic id="s4-step2">
<title>Step 2 — 实体分类</title>
<children>
<topic><title>Prompt: ENTITY_CLASSIFICATION_PROMPT</title></topic>
<topic><title>类别: concept / element / flow / case / defense</title></topic>
<topic><title>附加 short_definition</title></topic>
</children>
</topic>
<topic id="s4-step3">
<title>Step 3 — 关系抽取</title>
<children>
<topic><title>Prompt: RELATION_EXTRACTION_PROMPT</title></topic>
<topic><title>关系: prerequisite_of / related_to / part_of / example_of</title></topic>
<topic><title>仅对 2+ 新实体的 chunk 执行</title></topic>
</children>
</topic>
<topic id="s4-dedup">
<title>去重策略</title>
<children>
<topic><title>跨块去重：按 entity_name 合并</title></topic>
<topic><title>跨文档去重：同 canonical_name + 同 domain_tag 跳过</title></topic>
</children>
</topic>
<topic><title>状态: extracting → extracted → dispatch auto_review</title></topic>
</children>
</topic>

<!-- 阶段 5 -->
<topic id="stage5">
<title>阶段5：AI 自动审核（两轮质量把关）</title>
<children>
<topic id="s5-r1">
<title>Round 1 评审</title>
<children>
<topic><title>LLM 逐实体评审</title></topic>
<topic><title>approve + confidence ≥ 0.75 → approved</title></topic>
<topic><title>reject → rejected</title></topic>
<topic><title>其余 → Round 2</title></topic>
</children>
</topic>
<topic id="s5-r2">
<title>Round 2 评审</title>
<children>
<topic><title>更严格二次审核</title></topic>
<topic><title>approve + confidence ≥ 0.60 → approved</title></topic>
<topic><title>其余 → rejected</title></topic>
<topic><title>保证无实体永久 pending</title></topic>
</children>
</topic>
<topic id="s5-concur">
<title>并发安全 & 守护</title>
<children>
<topic><title>pg_try_advisory_lock() 空间级锁</title></topic>
<topic><title>每批 5 个实体</title></topic>
<topic><title>celery_beat 每 5 分钟守护</title></topic>
</children>
</topic>
<topic><title>状态: extracted → embedding</title></topic>
</children>
</topic>

<!-- 阶段 6 -->
<topic id="stage6">
<title>阶段6：向量化生成</title>
<children>
<topic id="s6-text">
<title>嵌入文本构建</title>
<children>
<topic><title>canonical_name + " — " + short_definition</title></topic>
<topic><title>截断 512 字符</title></topic>
</children>
</topic>
<topic id="s6-batch">
<title>批量生成</title>
<children>
<topic><title>backfill_entity_embeddings 任务</title></topic>
<topic><title>batch_size = 32</title></topic>
<topic><title>LLMGateway.embed() 调用</title></topic>
</children>
</topic>
<topic id="s6-store">
<title>pgvector 存储</title>
<children>
<topic><title>PostgreSQL vector 类型</title></topic>
<topic><title>索引加速相似度检索</title></topic>
</children>
</topic>
<topic><title>并行: embed_document_chunks（原文相似搜索）</title></topic>
<topic><title>状态: embedding → reviewed → dispatch synthesize</title></topic>
</children>
</topic>

<!-- 阶段 7 -->
<topic id="stage7">
<title>阶段7：蓝图/课程生成（V2 合成引擎）</title>
<children>
<topic id="s7-p1">
<title>Phase 1: 过滤 + 聚类</title>
<children>
<topic id="s7-filter">
<title>过滤非教学实体</title>
<children>
<topic><title>CVE 编号 / 版本号</title></topic>
<topic><title>厂商产品名 / 漏洞描述</title></topic>
</children>
</topic>
<topic id="s7-kmeans">
<title>K-Means 聚类</title>
<children>
<topic><title>K = max(4, round(N/7))</title></topic>
<topic><title>上限 30</title></topic>
</children>
</topic>
<topic id="s7-rebal">
<title>均衡化 _rebalance_clusters()</title>
<children>
<topic><title>合并 &lt; 3 实体的簇</title></topic>
<topic><title>拆分 &gt; 12 实体的簇</title></topic>
</children>
</topic>
</children>
</topic>
<topic id="s7-p2">
<title>Phase 2: LLM 四步生成</title>
<children>
<topic><title>① 簇命名 → CLUSTER_CHAPTER_PROMPT</title></topic>
<topic><title>  → 标题 + 目标 + 任务描述 + 通过标准 + 常见误区</title></topic>
<topic><title>② 阶段规划 → STAGE_PLANNING_PROMPT</title></topic>
<topic><title>  → 基础 → 实践 → 评估（动词多样化）</title></topic>
<topic><title>③ 课程标题 → COURSE_TITLE_PROMPT</title></topic>
<topic><title>④ 章节正文 → CHAPTER_CONTENT_PROMPT</title></topic>
<topic><title>  → 600-900 字结构化内容</title></topic>
</children>
</topic>
<topic id="s7-content">
<title>章节内容结构</title>
<children>
<topic><title>scene_hook — 场景导入</title></topic>
<topic><title>skim_summary — 速览要点列表</title></topic>
<topic><title>full_content — 正文（含 CHECKPOINT 断点）</title></topic>
<topic><title>code_example — 代码示例</title></topic>
<topic><title>misconception_block — 常见误区纠正</title></topic>
<topic><title>prereq_adaptive — 自适应扩展</title></topic>
</children>
</topic>
<topic id="s7-modes">
<title>两种工作模式</title>
<children>
<topic id="s7-modea">
<title>模式 A：全新生成</title>
<children>
<topic><title>首次创建课程</title></topic>
<topic><title>K-Means 从头聚类 + 生成</title></topic>
</children>
</topic>
<topic id="s7-modeb">
<title>模式 B：增量合并</title>
<children>
<topic><title>追加文档到已有课程</title></topic>
<topic><title>余弦相似度差异分析</title></topic>
<topic><title>&gt; 0.92：已覆盖，跳过</title></topic>
<topic><title>0.75-0.92：补充到最相似章节</title></topic>
<topic><title>&lt; 0.75：生成新章节</title></topic>
<topic><title>学员进度自动重映射</title></topic>
</children>
</topic>
</children>
</topic>
<topic><title>状态: reviewed → published → dispatch pregen_quizzes</title></topic>
</children>
</topic>

<!-- 阶段 8 -->
<topic id="stage8">
<title>阶段8：测验预生成</title>
<children>
<topic><title>读取每章 core_term 关联实体</title></topic>
<topic><title>调用 QUIZ_GENERATION_PROMPT</title></topic>
<topic><title>写入 chapter_quizzes 表</title></topic>
<topic><title>学生端随机抽题（≥60% 自动已读）</title></topic>
</children>
</topic>

<!-- 阶段 9 -->
<topic id="stage9">
<title>阶段9：学生学习与交互</title>
<children>
<topic id="s9-load">
<title>数据加载</title>
<children>
<topic><title>GET /api/tutorials/topic/{key} 加载课程</title></topic>
<topic><title>GET /api/learners/me/chapter-progress/{id} 加载进度</title></topic>
</children>
</topic>
<topic id="s9-parse">
<title>内容解析</title>
<children>
<topic><title>chapterContent computed 解析结构化字段</title></topic>
<topic><title>contentSegments 按 CHECKPOINT 切分</title></topic>
</children>
</topic>
<topic id="s9-progress">
<title>进度追踪</title>
<children>
<topic><title>章节测验 ≥60% 自动标记已读</title></topic>
<topic><title>阶段/课程进度实时计算</title></topic>
</children>
</topic>
</children>
</topic>

<!-- 阶段 10 -->
<topic id="stage10">
<title>阶段10：教师引导式迭代（三层方案）</title>
<children>
<topic id="s10-l1">
<title>Layer 1：生成前约束</title>
<children>
<topic><title>上传时输入全局教学指令</title></topic>
<topic><title>注入所有 LLM Prompt</title></topic>
<topic><title>控制风格 / 难度 / 受众</title></topic>
<topic><title>示例: "增加实操案例，弱化理论推导"</title></topic>
</children>
</topic>
<topic id="s10-l2">
<title>Layer 2：对话式章节精调</title>
<children>
<topic><title>入口：'✨ 精调本章' 按钮</title></topic>
<topic><title>交互：ElMessageBox.prompt textarea</title></topic>
<topic><title>API: POST /admin/courses/chapters/{id}/refine</title></topic>
<topic><title>鉴权: require_space_owner()（仅课程所有者）</title></topic>
<topic><title>LLM: tutorial_content route, 150s timeout</title></topic>
<topic><title>版本: refinement_version + 1</title></topic>
</children>
</topic>
<topic id="s10-l3">
<title>Layer 3：附属内容联动</title>
<children>
<topic><title>测验缓存自动失效</title></topic>
<topic><title>regenerate_chapter_quiz 重新生成</title></topic>
<topic><title>generate_discussion_seeds 可选更新</title></topic>
</children>
</topic>
</children>
</topic>

</children>
</topic>

<!-- ===== 三、文档状态机 ===== -->
<topic id="state-machine">
<title>文档状态机</title>
<children>
<topic><title>uploaded → 已上传</title></topic>
<topic><title>parsed → 已解析</title></topic>
<topic><title>extracting → 提取中 🔒（原子锁）</title></topic>
<topic><title>extracted → 已提取</title></topic>
<topic><title>embedding → 向量化中</title></topic>
<topic><title>reviewed → 已审核</title></topic>
<topic><title>published → 已发布 ✓</title></topic>
</children>
</topic>

<!-- ===== 四、事件链路 ===== -->
<topic id="event-chain">
<title>事件链路（RabbitMQ）</title>
<children>
<topic><title>file_uploaded → knowledge.ingest.queue</title></topic>
<topic><title>document_parsed → knowledge.extraction.queue</title></topic>
<topic><title>entities_reviewed → 内部 dispatch</title></topic>
<topic><title>embeddings_complete → _trigger_blueprint_if_ready()</title></topic>
<topic><title>blueprint_published → blueprint.notify</title></topic>
</children>
</topic>

<!-- ===== 五、技术栈 ===== -->
<topic id="tech-stack">
<title>技术栈</title>
<children>
<topic id="tech-frontend">
<title>前端</title>
<children>
<topic><title>Vue 3 + TypeScript</title></topic>
<topic><title>Vite 构建</title></topic>
<topic><title>Element Plus UI</title></topic>
<topic><title>Pinia 状态管理</title></topic>
</children>
</topic>
<topic id="tech-api">
<title>API 网关</title>
<children>
<topic><title>FastAPI 异步框架</title></topic>
<topic><title>Pydantic v2</title></topic>
<topic><title>Uvicorn 服务</title></topic>
<topic><title>WebSocket 支持</title></topic>
</children>
</topic>
<topic id="tech-ai">
<title>AI / 文档处理</title>
<children>
<topic><title>LangChain</title></topic>
<topic><title>LLMGateway 多模型网关</title></topic>
<topic><title>PyMuPDF (fitz)</title></topic>
<topic><title>python-docx</title></topic>
</children>
</topic>
<topic id="tech-storage">
<title>存储层</title>
<children>
<topic><title>PostgreSQL + pgvector</title></topic>
<topic><title>MinIO / S3</title></topic>
<topic><title>Redis 缓存</title></topic>
</children>
</topic>
<topic id="tech-tasks">
<title>任务系统</title>
<children>
<topic><title>Celery 异步任务</title></topic>
<topic><title>RabbitMQ 消息队列</title></topic>
<topic><title>EventBus 内部事件总线</title></topic>
</children>
</topic>
</children>
</topic>

<!-- ===== 六、项目规模 ===== -->
<topic id="metrics">
<title>项目规模指标</title>
<children>
<topic><title>27 个数据库迁移</title></topic>
<topic><title>144 个测试用例（0 失败）</title></topic>
<topic><title>9 个 Docker 服务</title></topic>
<topic><title>10 个自动化阶段</title></topic>
<topic><title>5 个 Celery 专用队列</title></topic>
<topic><title>3 层教师迭代方案</title></topic>
</children>
</topic>

</children>
</topic>
</sheet>
</xmap-content>'''

# ── styles.xml ──
styles_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<xmap-styles xmlns="urn:xmind:xmap:xmlns:style:2.0" xmlns:fo="http://www.w3.org/1999/XSL/Format" version="2.0">
<styles>
<style id="default-theme">
<topic-properties>
<shape-class>org.xmind.topicShape.roundedRect</shape-class>
<line-class>org.xmind.branchConnection.roundedElbow</line-class>
</topic-properties>
</style>
</styles>
<master-styles>
<style id="central-topic" type="topic">
<topic-properties svg:fill="#1a1a2e" fill="#1a1a2e" fo:color="#ffffff" line-color="#00d2ff" shape-class="org.xmind.topicShape.roundedRect" xmlns:svg="http://www.w3.org/2000/svg"/>
</style>
<style id="main-topic" type="topic">
<topic-properties svg:fill="#22223a" fill="#22223a" fo:color="#00d2ff" line-color="#00d2ff" xmlns:svg="http://www.w3.org/2000/svg"/>
</style>
<style id="sub-topic" type="topic">
<topic-properties svg:fill="#2a2a42" fill="#2a2a42" fo:color="#ccccdd" line-color="#444466" xmlns:svg="http://www.w3.org/2000/svg"/>
</style>
</master-styles>
</xmap-styles>'''

# ── manifest.xml ──
manifest_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<manifest xmlns="urn:xmind:xmap:xmlns:manifest:2.0">
<file-entry full-path="content.xml" media-type="text/xml"/>
<file-entry full-path="styles.xml" media-type="text/xml"/>
</manifest>'''

# ── 打包为 ZIP（.xmind）──
with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('content.xml', content_xml.encode('utf-8'))
    zf.writestr('styles.xml', styles_xml.encode('utf-8'))
    zf.writestr('META-INF/', '')
    zf.writestr('META-INF/manifest.xml', manifest_xml.encode('utf-8'))

print(f'XMind saved: {out_path}')
print(f'File size: {os.path.getsize(out_path)} bytes')
