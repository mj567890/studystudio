"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h6_frontend.py
"""
from pathlib import Path

errors = []

def patch(content, anchor, new_text, mode="replace"):
    if anchor not in content:
        errors.append(f"  ✗ 未找到锚点: {repr(anchor[:60])}")
        return content
    if mode == "prepend":
        return content.replace(anchor, new_text + anchor, 1)
    return content.replace(anchor, new_text, 1)


# ════════════════════════════════════════════════════════════════
# api/index.ts — markChapter 加 duration_seconds；加 errorPatternApi
# ════════════════════════════════════════════════════════════════
p_api = Path("apps/web/src/api/index.ts")
s_api = p_api.read_text()

s_api = patch(s_api,
    "markChapter: (data: { tutorial_id: string; chapter_id: string; completed: boolean; status?: string }) =>",
    "markChapter: (data: { tutorial_id: string; chapter_id: string; completed: boolean; status?: string; duration_seconds?: number }) =>",
)

if "errorPatternApi" not in s_api:
    s_api += """
// H-6：错题模式
export const errorPatternApi = {
  get: () => http.get('/learners/me/error-patterns'),
}
"""

p_api.write_text(s_api)
print("✓ api/index.ts 已更新")


# ════════════════════════════════════════════════════════════════
# TutorialView.vue — 计时 + markChapter 上报 + 测验错题展示
# ════════════════════════════════════════════════════════════════
p_tv = Path("apps/web/src/views/tutorial/TutorialView.vue")
s_tv = p_tv.read_text()

# 1. import 加 errorPatternApi
s_tv = patch(s_tv,
    "import { learnerApi, knowledgeApi, tutorialApi, recommendApi } from '@/api'",
    "import { learnerApi, knowledgeApi, tutorialApi, recommendApi, errorPatternApi } from '@/api'",
)

# 2. ref 区加计时变量
s_tv = patch(s_tv,
    "const relatedRecs    = ref<any[]>([])",
    "const relatedRecs    = ref<any[]>([])\nconst chapterEnterTime = ref<number>(0)\nconst errorPatterns  = ref<any[]>([])",
)

# 3. selectChapter 函数里记录进入时间
#    找 selectChapter 函数开头
s_tv = patch(s_tv,
    "async function selectChapter(chapter: any) {",
    """async function selectChapter(chapter: any) {
  chapterEnterTime.value = Date.now()
  errorPatterns.value = []""",
)

# 4. markChapter 上报 duration_seconds
s_tv = patch(s_tv,
    "  await learnerApi.markChapter({\n    tutorial_id: tutorial.value.tutorial_id,\n    chapter_id:  chapter.chapter_id,\n    completed:   status === 'read',\n    status:      status || 'read',\n  })",
    """  const durationSec = chapterEnterTime.value
    ? Math.round((Date.now() - chapterEnterTime.value) / 1000)
    : 0
  await learnerApi.markChapter({
    tutorial_id:      tutorial.value.tutorial_id,
    chapter_id:       chapter.chapter_id,
    completed:        status === 'read',
    status:           status || 'read',
    duration_seconds: durationSec,
  })""",
)

# 5. 测验提交后加载错题模式
s_tv = patch(s_tv,
    "    quizSubmitted.value = true",
    """    quizSubmitted.value = true
    // H-6 加载错题模式
    try {
      const ep: any = await errorPatternApi.get()
      errorPatterns.value = (ep.data?.patterns || []).slice(0, 5)
    } catch { /* 静默处理 */ }""",
)

# 6. 测验结果弹窗里展示错题模式
#    在 el-result 下方插入错题卡片
OLD_RESULT = """          <el-result :icon="quizScore>=60?'success':'warning'" :title="`得分 ${quizScore} 分`" :sub-title="`答对 ${quizCorrect}/${quizTotal} 题，掌握度已更新`">
            <template #extra>
              <el-button type="primary" @click="quizVisible=false">完成</el-button>
              <el-button @click="pickQuestions">换一套题</el-button>
              <el-button type="success" plain @click="quizVisible=false;openReflect()">🧠 写反思巩固</el-button>
            </template>
          </el-result>"""

NEW_RESULT = """          <el-result :icon="quizScore>=60?'success':'warning'" :title="`得分 ${quizScore} 分`" :sub-title="`答对 ${quizCorrect}/${quizTotal} 题，掌握度已更新`">
            <template #extra>
              <el-button type="primary" @click="quizVisible=false">完成</el-button>
              <el-button @click="pickQuestions">换一套题</el-button>
              <el-button type="success" plain @click="quizVisible=false;openReflect()">🧠 写反思巩固</el-button>
            </template>
          </el-result>
          <!-- H-6 错题模式提示 -->
          <div v-if="errorPatterns.length" style="margin-top:16px;text-align:left">
            <p style="font-size:13px;color:#606266;margin-bottom:8px">近期常错知识点：</p>
            <div v-for="ep in errorPatterns" :key="ep.canonical_name"
              style="display:flex;align-items:center;justify-content:space-between;
                     padding:6px 10px;margin-bottom:4px;background:#fff7e6;
                     border:1px solid #ffe0a0;border-radius:6px">
              <span style="font-size:13px;font-weight:500;color:#303133">{{ ep.canonical_name }}</span>
              <span style="font-size:12px;color:#e6a23c">错误 {{ ep.wrong_count }} 次</span>
            </div>
          </div>"""

s_tv = patch(s_tv, OLD_RESULT, NEW_RESULT)

p_tv.write_text(s_tv)
print("✓ TutorialView.vue H-6 补丁应用完成")


if errors:
    print("\n以下锚点未找到：")
    for e in errors:
        print(e)
