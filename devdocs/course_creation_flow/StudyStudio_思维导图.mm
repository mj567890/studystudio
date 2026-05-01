<map version="1.0.1">
<!-- StudyStudio 课程制作全流程 — Freemind 思维导图 -->
<!-- 可用 FreeMind / Freeplane / XMind / MindManager 打开 -->
<node TEXT="StudyStudio 课程制作全流程" COLOR="#ffffff" BACKGROUND_COLOR="#1a1a2e" STYLE="bubble">
<font BOLD="true" SIZE="18"/>
<richcontent TYPE="NOTE"><html><body>
<p>v2.8.0 · 10 阶段自动化 · 全异步事件驱动</p>
</body></html></richcontent>

<node TEXT="一、前端入口" COLOR="#00d2ff" BACKGROUND_COLOR="#22223a" STYLE="bubble">
<icon BUILTIN="bookmark"/>
<node TEXT="UploadView.vue" COLOR="#ccccdd" BACKGROUND_COLOR="#2a2a42">
<node TEXT="支持 PDF/DOCX/MD/TXT"/>
<node TEXT="最大 100MB"/>
<node TEXT="FormData 封装"/>
</node>
<node TEXT="TutorialView.vue" COLOR="#ccccdd" BACKGROUND_COLOR="#2a2a42">
<node TEXT="三种阅读模式">
<node TEXT="速览 → skim_summary"/>
<node TEXT="正常 → full_content + CHECKPOINT"/>
<node TEXT="深度 → + prereq_adaptive"/>
</node>
<node TEXT="互动功能">
<node TEXT="章节测验 ≥60% 已读"/>
<node TEXT="AI 反思 LLM 评分"/>
<node TEXT="社交笔记 点赞互动"/>
<node TEXT="源文档追溯"/>
<node TEXT="证书下载"/>
</node>
</node>
</node>

<node TEXT="二、10 阶段自动化流水线" COLOR="#00d2ff" BACKGROUND_COLOR="#22223a" STYLE="bubble">
<icon BUILTIN="forward"/>

<node TEXT="阶段1：文件上传与存储" COLOR="#ff8c00">
<icon BUILTIN="full-1"/>
<node TEXT="安全校验">
<node TEXT="Content-Type 白名单"/>
<node TEXT="文件名安全过滤"/>
</node>
<node TEXT="SHA-256 去重">
<node TEXT="同文件同空间 → 复用"/>
<node TEXT="同文件不同空间 → 新建"/>
</node>
<node TEXT="MinIO 对象存储">
<node TEXT="键: files/{id}/{name}"/>
<node TEXT="AsyncMinIOClient"/>
</node>
<node TEXT="EventBus → file_uploaded"/>
<node TEXT="状态: uploaded"/>
</node>

<node TEXT="阶段2：事件驱动调度" COLOR="#ff8c00">
<icon BUILTIN="full-2"/>
<node TEXT="RabbitMQ 订阅">
<node TEXT="file_uploaded → ingest"/>
<node TEXT="document_parsed → extraction"/>
</node>
<node TEXT="Celery 5 队列">
<node TEXT="knowledge"/>
<node TEXT="knowledge.review"/>
<node TEXT="tutorial"/>
<node TEXT="blueprint.synthesis"/>
<node TEXT="low_priority"/>
</node>
<node TEXT="超时策略">
<node TEXT="ingest: 180s/240s"/>
<node TEXT="extraction: 无限制"/>
<node TEXT="review: 600s/720s"/>
</node>
</node>

<node TEXT="阶段3：文档解析与分块" COLOR="#00e676">
<icon BUILTIN="full-3"/>
<node TEXT="多格式引擎">
<node TEXT="PDF → PyMuPDF"/>
<node TEXT="DOCX → python-docx"/>
<node TEXT="MD/TXT → charset"/>
</node>
<node TEXT="LangChain Splitter">
<node TEXT="每页独立分块"/>
<node TEXT="元数据标注"/>
</node>
<node TEXT="截断保护">
<node TEXT="MAX 500 块"/>
<node TEXT="is_truncated"/>
</node>
<node TEXT="状态: parsed"/>
</node>

<node TEXT="阶段4：知识提取 — 三步LLM" COLOR="#7b2fbe">
<icon BUILTIN="full-4"/>
<node TEXT="🔒 原子锁 (UPDATE RETURNING)"/>
<node TEXT="Step1: 实体识别">
<node TEXT="ENTITY_RECOGNITION"/>
</node>
<node TEXT="Step2: 实体分类">
<node TEXT="concept/element/flow/case/defense"/>
<node TEXT="+ short_definition"/>
</node>
<node TEXT="Step3: 关系抽取">
<node TEXT="prerequisite_of/related_to"/>
<node TEXT="part_of/example_of"/>
</node>
<node TEXT="去重">
<node TEXT="跨块: entity_name"/>
<node TEXT="跨文档: canonical+domain"/>
</node>
<node TEXT="状态: extracted"/>
</node>

<node TEXT="阶段5：AI 两轮自动审核" COLOR="#ff4444">
<icon BUILTIN="full-5"/>
<node TEXT="Round 1">
<node TEXT="conf≥0.75 → approved"/>
<node TEXT="reject → rejected"/>
<node TEXT="其余 → Round2"/>
</node>
<node TEXT="Round 2">
<node TEXT="conf≥0.60 → approved"/>
<node TEXT="其余 → rejected"/>
</node>
<node TEXT="pg_try_advisory_lock"/>
<node TEXT="celery_beat 守护 (5min)"/>
<node TEXT="状态: embedding"/>
</node>

<node TEXT="阶段6：向量化生成" COLOR="#4488ff">
<icon BUILTIN="full-6"/>
<node TEXT="嵌入文本 (512字符截断)"/>
<node TEXT="批量 batch_size=32"/>
<node TEXT="pgvector 存储"/>
<node TEXT="chunk 向量并行"/>
<node TEXT="状态: reviewed"/>
</node>

<node TEXT="阶段7：蓝图/课程生成 V2" COLOR="#00e676">
<icon BUILTIN="full-7"/>
<node TEXT="Phase 1: 过滤 + K-Means">
<node TEXT="过滤非教学实体"/>
<node TEXT="K=max(4,round(N/7)), ≤30"/>
<node TEXT="均衡化 ± 重分配"/>
</node>
<node TEXT="Phase 2: LLM 四步生成">
<node TEXT="① 簇命名"/>
<node TEXT="② 阶段规划"/>
<node TEXT="③ 课程标题"/>
<node TEXT="④ 章节正文 600-900字"/>
</node>
<node TEXT="内容结构">
<node TEXT="scene_hook"/>
<node TEXT="skim_summary"/>
<node TEXT="full_content"/>
<node TEXT="code_example"/>
<node TEXT="misconception_block"/>
<node TEXT="prereq_adaptive"/>
</node>
<node TEXT="两种模式">
<node TEXT="A: 全新生成 (K-Means)"/>
<node TEXT="B: 增量合并 (cosine diff)">
<node TEXT="&gt;0.92 跳过"/>
<node TEXT="0.75-0.92 补充"/>
<node TEXT="&lt;0.75 新章"/>
</node>
</node>
<node TEXT="状态: published"/>
</node>

<node TEXT="阶段8：测验预生成" COLOR="#ff8c00">
<icon BUILTIN="full-8"/>
<node TEXT="读取 core_term 实体"/>
<node TEXT="QUIZ_GENERATION_PROMPT"/>
<node TEXT="写入 chapter_quizzes"/>
</node>

<node TEXT="阶段9：学生学习与交互" COLOR="#4488ff">
<icon BUILTIN="full-9"/>
<node TEXT="课程加载 + 进度"/>
<node TEXT="contentSegments 切分"/>
<node TEXT="测验/反思/笔记"/>
</node>

<node TEXT="阶段10：教师三层迭代" COLOR="#ff8c00">
<icon BUILTIN="full-1"/>
<icon BUILTIN="full-0"/>
<node TEXT="Layer 1: 生成前约束">
<node TEXT="上传时输入全局指令"/>
<node TEXT="注入所有 Prompt"/>
</node>
<node TEXT="Layer 2: 对话式精调">
<node TEXT="✨ 精调本章 按钮"/>
<node TEXT="require_space_owner()"/>
<node TEXT="refinement_version+1"/>
</node>
<node TEXT="Layer 3: 联动再生">
<node TEXT="测验缓存失效"/>
<node TEXT="题目重新生成"/>
<node TEXT="讨论种子更新"/>
</node>
</node>

</node>

<node TEXT="三、文档状态机" COLOR="#ff8c00" BACKGROUND_COLOR="#22223a" STYLE="bubble">
<icon BUILTIN="hourglass"/>
<node TEXT="uploaded"/>
<node TEXT="parsed"/>
<node TEXT="extracting 🔒"/>
<node TEXT="extracted"/>
<node TEXT="embedding"/>
<node TEXT="reviewed"/>
<node TEXT="published ✓"/>
</node>

<node TEXT="四、事件链路 (RabbitMQ)" COLOR="#7b2fbe" BACKGROUND_COLOR="#22223a" STYLE="bubble">
<icon BUILTIN="connection"/>
<node TEXT="file_uploaded → ingest"/>
<node TEXT="document_parsed → extraction"/>
<node TEXT="entities_reviewed (内部)"/>
<node TEXT="embeddings_complete (内部)"/>
<node TEXT="blueprint_published → notify"/>
</node>

<node TEXT="五、技术栈" COLOR="#00d2ff" BACKGROUND_COLOR="#22223a" STYLE="bubble">
<icon BUILTIN="wizard"/>
<node TEXT="前端">
<node TEXT="Vue 3 + TS"/>
<node TEXT="Vite"/>
<node TEXT="Element Plus"/>
<node TEXT="Pinia"/>
</node>
<node TEXT="API">
<node TEXT="FastAPI"/>
<node TEXT="Pydantic v2"/>
<node TEXT="Uvicorn"/>
</node>
<node TEXT="AI/文档">
<node TEXT="LangChain"/>
<node TEXT="LLMGateway"/>
<node TEXT="PyMuPDF"/>
<node TEXT="python-docx"/>
</node>
<node TEXT="存储">
<node TEXT="PostgreSQL+pgvector"/>
<node TEXT="MinIO/S3"/>
<node TEXT="Redis"/>
</node>
<node TEXT="任务">
<node TEXT="Celery"/>
<node TEXT="RabbitMQ"/>
<node TEXT="EventBus"/>
</node>
</node>

<node TEXT="六、项目规模指标" COLOR="#00e676" BACKGROUND_COLOR="#22223a" STYLE="bubble">
<icon BUILTIN="list"/>
<node TEXT="27 数据库迁移"/>
<node TEXT="144 测试 (0 失败)"/>
<node TEXT="9 Docker 服务"/>
<node TEXT="10 自动化阶段"/>
<node TEXT="5 Celery 队列"/>
<node TEXT="3 教师迭代层"/>
</node>

</node>
</map>
