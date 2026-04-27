# 专项计划：精读模式原文对照功能

> 目标：在精读模式下，用户学习某个章节时，能看到 AI 引用的原文段落，并知道它来自哪个文件的第几页。

---

## 一、现状梳理

| 层级 | 现状 | 问题 |
|------|------|------|
| 数据库 | `document_chunks` 表无 `page_no` 字段 | 无法记录页码 |
| 后端解析 | `reparse` 接口已重写，但按全文分段，不区分页 | chunk 没有页码来源 |
| 后端查询 | `/api/teaching/chapters/{id}/source` 接口已有 | 待确认返回结构 |
| 前端精读 | `TutorialView.vue` 有"查看原文"按钮和 `openSource` 逻辑 | 待确认实际展示效果 |

---

## 二、完整链路设计

```
用户点击"查看原文"
        ↓
前端请求 /api/teaching/chapters/{chapter_id}/source
        ↓
后端返回：引用的 chunk 列表（含 page_no、content、file_name、document_id）
        ↓
前端展示：按文件分组，每条显示页码 + 原文片段
        ↓
（可选）点击页码 → 新标签打开 PDF 预览，跳转到对应页
```

---

## 三、执行步骤

### 步骤 1：数据库加字段

```bash
docker compose exec -T postgres psql -U user -d adaptive_learning -c "
  ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS page_no integer;
"
```

验证：
```bash
docker compose exec -T postgres psql -U user -d adaptive_learning -c "\d document_chunks" | grep page_no
```

---

### 步骤 2：修复 reparse 接口，支持页码提取

**目标文件：** `~/studystudio/apps/api/modules/admin/router.py`

**核心逻辑：**
先看 `DocumentIngestService._extract_text` 是否支持逐页返回，如果不支持则改用 pdfplumber/pymupdf 直接按页提取。

**先查：**
```bash
sed -n '207,280p' ~/studystudio/apps/api/modules/knowledge/ingest_service.py
```

**预期实现（reparse 接口修改后的核心逻辑）：**

```python
# 用 pymupdf 或 pdfplumber 按页提取
import fitz  # pymupdf

pages_text = []  # [(page_no, text), ...]
with fitz.open(str(tmp_path)) as doc:
    for i, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            pages_text.append((i + 1, text))

# 分段时标记页码
from langchain_text_splitters import RecursiveCharacterTextSplitter
splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)

chunk_rows = []
for page_no, page_text in pages_text:
    chunks = splitter.split_text(page_text)
    for chunk_text in chunks:
        if chunk_text.strip():
            chunk_rows.append({
                "chunk_id": str(uuid.uuid4()),
                "document_id": document_id,
                "index_no": len(chunk_rows),
                "title_path": json.dumps([]),
                "content": chunk_text.strip(),
                "token_count": len(chunk_text) // 4,
                "page_no": page_no,
            })
```

INSERT 语句加上 `page_no`：
```sql
INSERT INTO document_chunks
  (chunk_id, document_id, index_no, title_path, content, token_count, page_no)
VALUES
  (:chunk_id, CAST(:document_id AS uuid), :index_no,
   CAST(:title_path AS jsonb), :content, :token_count, :page_no)
```

> **注意：** 如果 pymupdf 未安装，执行前先在容器里安装：
> ```bash
> docker compose exec api pip install pymupdf --break-system-packages
> ```
> 安装后验证：
> ```bash
> docker compose exec api python3 -c "import fitz; print(fitz.__version__)"
> ```

---

### 步骤 3：确认并完善 source 接口

**先查接口现状：**
```bash
grep -n "source\|chapter_source\|getChapterSource" \
  ~/studystudio/apps/api/modules/teaching/router.py | head -20
```

**期望返回结构：**
```json
{
  "code": 200,
  "data": {
    "sources": [
      {
        "document_id": "uuid",
        "file_name": "高中物理.pdf",
        "title": "文档标题",
        "page_no": 12,
        "content": "原文片段内容...",
        "chunk_id": "uuid"
      }
    ]
  }
}
```

如果现有接口缺少 `page_no` 或 `file_name`，在 SQL 里补上：
```sql
SELECT
    dc.chunk_id,
    dc.content,
    dc.page_no,
    d.title,
    f.file_name,
    d.document_id
FROM document_chunks dc
JOIN documents d ON d.document_id = dc.document_id
JOIN files f ON f.file_id = d.file_id
WHERE dc.chunk_id = ANY(:chunk_ids)
ORDER BY dc.page_no NULLS LAST, dc.index_no
```

---

### 步骤 4：前端精读页展示原文

**目标文件：** `~/studystudio/apps/web/src/views/tutorial/TutorialView.vue`

**先查当前"查看原文"的展示逻辑：**
```bash
grep -n "sourceVisible\|sourcePages\|openSource\|查看原文" \
  ~/studystudio/apps/web/src/views/tutorial/TutorialView.vue | head -20
```

**期望 UI 效果（原文弹窗/抽屉）：**

```
┌─────────────────────────────────────────┐
│ 参考原文来源                       [关闭] │
├─────────────────────────────────────────┤
│ 📄 高中物理.pdf                          │
│                                         │
│ 第 12 页                                 │
│ ┌─────────────────────────────────────┐ │
│ │ 牛顿第二定律指出，物体的加速度与合   │ │
│ │ 外力成正比，与质量成反比...          │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ 第 15 页                                 │
│ ┌─────────────────────────────────────┐ │
│ │ 在匀加速运动中，速度随时间线性增大...│ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

**前端 template 参考（替换原有 source 展示区域）：**

```vue
<el-drawer v-model="sourceVisible" title="参考原文来源" size="45%" direction="rtl">
  <div v-if="sourceLoading" style="text-align:center;padding:40px">
    <el-icon class="is-loading"><Loading /></el-icon> 加载中…
  </div>
  <div v-else-if="!sourceDocs.length" style="padding:40px;text-align:center;color:#999">
    暂无原文来源信息
  </div>
  <div v-else>
    <!-- 按文件分组 -->
    <div v-for="doc in sourceDocs" :key="doc.document_id" style="margin-bottom:24px">
      <div style="font-weight:600;color:#303133;margin-bottom:12px;display:flex;align-items:center;gap:8px">
        <el-icon><Document /></el-icon>
        {{ doc.file_name || doc.title }}
      </div>
      <div v-for="chunk in doc.chunks" :key="chunk.chunk_id" style="margin-bottom:12px">
        <div v-if="chunk.page_no" style="font-size:12px;color:#909399;margin-bottom:4px">
          第 {{ chunk.page_no }} 页
        </div>
        <div style="background:#f5f7fa;border-left:3px solid #409eff;padding:10px 14px;
                    font-size:13px;color:#606266;line-height:1.7;border-radius:0 4px 4px 0">
          {{ chunk.content }}
        </div>
      </div>
    </div>
  </div>
</el-drawer>
```

**script 数据处理（把平铺的 sources 按 document_id 分组）：**

```typescript
const sourceDocs = computed(() => {
  const map = new Map<string, any>()
  for (const s of sourcePages.value) {
    if (!map.has(s.document_id)) {
      map.set(s.document_id, {
        document_id: s.document_id,
        file_name: s.file_name,
        title: s.title,
        chunks: []
      })
    }
    map.get(s.document_id).chunks.push(s)
  }
  return [...map.values()]
})
```

---

### 步骤 5：（可选）PDF 内页预览

如果要实现点击页码直接预览 PDF 对应页，需要额外工作：

1. 后端加 MinIO presign URL 接口（按 document_id 生成临时访问链接）
2. 前端用 `<iframe>` 或 `pdf.js` 加载 PDF，传入 `#page=N` 参数跳转指定页

此步骤工作量较大，建议作为二期，一期只展示文字原文片段。

---

## 四、执行顺序

```
步骤1（5分钟）  → 步骤2（20分钟）→ 步骤3（10分钟）→ 步骤4（20分钟）→ 步骤5（可选）
加字段           修复解析接口       完善source接口    前端展示改版       PDF预览
```

---

## 五、验证方法

1. 执行步骤1后：`\d document_chunks` 能看到 `page_no integer` 字段
2. 执行步骤2后：点击"重新解析"，等待完成，查询 `SELECT page_no, count(*) FROM document_chunks WHERE document_id='xxx' GROUP BY page_no ORDER BY page_no;` 应看到按页分布的 chunk
3. 执行步骤3后：直接 curl 测试接口返回有 `page_no` 字段
4. 执行步骤4后：精读某章节，点"查看原文"，能看到带页码的原文片段

---

## 六、注意事项

- **重新解析只影响新上传或手动触发的文档**，已有文档的旧 chunk 没有 page_no，需要管理员在"文档管理"tab 里逐一点"重新解析"才能补上
- **非 PDF 文档**（如 .txt、.docx）没有物理页码，page_no 统一设为 1 或按段落顺序编号，不影响功能
- **chunk 和 chapter 的关联**：需要确认 teaching 模块是通过 embedding 向量检索还是固定关联来找到引用 chunk，这决定步骤3的实现方式
