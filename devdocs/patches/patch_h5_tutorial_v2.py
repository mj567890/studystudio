"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h5_tutorial.py
"""
from pathlib import Path

p = Path("apps/web/src/views/tutorial/TutorialView.vue")
src = p.read_text()
errors = []

def patch(content, anchor, new_text):
    if anchor not in content:
        errors.append(f"  ✗ 未找到锚点: {repr(anchor[:60])}")
        return content
    return content.replace(anchor, new_text, 1)

# ── 1. import 加 recommendApi ────────────────────────────────────────────
src = patch(src,
    "import { learnerApi, knowledgeApi, tutorialApi } from '@/api'",
    "import { learnerApi, knowledgeApi, tutorialApi, recommendApi } from '@/api'",
)

# ── 2. 在 loading ref 前插入 relatedRecs ref ─────────────────────────────
src = patch(src,
    "const loading        = ref(false)",
    "const relatedRecs    = ref<any[]>([])\nconst loading        = ref(false)",
)

# ── 3. markChapter 成功后触发推荐加载 ────────────────────────────────────
src = patch(src,
    "    ElMessage.success(status==='read' ? '已标记为已读' : '已标记为忽略')",
    """    ElMessage.success(status==='read' ? '已标记为已读' : '已标记为忽略')
    if (status === 'read') {
      relatedRecs.value = []
      try {
        const res: any = await recommendApi.getRelated(chapter.chapter_id)
        relatedRecs.value = res.data?.recommendations || []
      } catch { /* 推荐加载失败不阻断主流程 */ }
    } else {
      relatedRecs.value = []
    }""",
)

# ── 4. jumpToRec 函数，插在 markChapter 前 ───────────────────────────────
src = patch(src,
    "async function markChapter",
    """function jumpToRec(rec: any) {
  if (!tutorial.value) return
  const allChapters = tutorial.value.source === 'blueprint'
    ? tutorial.value.stages?.flatMap((s: any) => s.chapters) || []
    : tutorial.value.chapter_tree || []
  const target = allChapters.find((c: any) => c.chapter_id === rec.chapter_id)
  if (target) selectChapter(target)
}

async function markChapter""",
)

# ── 5. 模板：推荐区块插在 social-section 前 ──────────────────────────────
src = patch(src,
    '            <div class="social-section">',
    """            <!-- H-5 关联知识推荐 -->
            <div v-if="relatedRecs.length" class="related-section">
              <p class="section-label">完成此章节后，推荐继续学习</p>
              <div class="related-list">
                <div
                  v-for="rec in relatedRecs" :key="rec.chapter_id"
                  class="related-card"
                  @click="jumpToRec(rec)"
                >
                  <div class="related-card-top">
                    <span class="related-chapter">{{ rec.chapter_title }}</span>
                    <el-tag type="info" size="small" effect="plain">{{ rec.stage_title }}</el-tag>
                  </div>
                  <div class="related-unlock">
                    <span class="related-key">{{ rec.source_name }}</span>
                    <span class="related-arrow"> → </span>
                    <span class="related-target">{{ rec.target_name }}</span>
                  </div>
                  <div v-if="rec.target_def" class="related-def">{{ rec.target_def }}</div>
                </div>
              </div>
            </div>

            <div class="social-section">""",
)

# ── 6. 样式：推荐区块 CSS，插在 .social-section 前 ───────────────────────
src = patch(src,
    ".social-section { margin-top: 20px; padding-top: 16px; border-top: 1px solid #eee; }",
    """.related-section { margin-top: 24px; padding-top: 16px; border-top: 1px solid #f0f0f0; }
.related-list { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.related-card { background: #f0f7ff; border: 1px solid #d0e8ff; border-radius: 8px; padding: 10px 14px; cursor: pointer; transition: background .15s; }
.related-card:hover { background: #e0f0ff; }
.related-card-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.related-chapter { font-size: 13px; font-weight: 600; color: #1a6db5; }
.related-unlock { font-size: 12px; color: #606266; margin-bottom: 2px; }
.related-key { color: #409eff; font-weight: 500; }
.related-arrow { color: #909399; }
.related-target { color: #67c23a; font-weight: 500; }
.related-def { font-size: 11px; color: #909399; }
.social-section { margin-top: 20px; padding-top: 16px; border-top: 1px solid #eee; }""",
)

if errors:
    print("补丁部分失败：")
    for e in errors:
        print(e)
else:
    p.write_text(src)
    print("✓ TutorialView.vue H-5 补丁全部应用成功")
