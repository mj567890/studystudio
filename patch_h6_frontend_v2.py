"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h6_frontend_v2.py
"""
from pathlib import Path

errors = []

def patch(content, anchor, new_text, mode="replace"):
    if anchor not in content:
        errors.append(f"  ✗ 未找到锚点: {repr(anchor[:70])}")
        return content
    if mode == "prepend":
        return content.replace(anchor, new_text + anchor, 1)
    return content.replace(anchor, new_text, 1)


p = Path("apps/web/src/views/tutorial/TutorialView.vue")
s = p.read_text()

# 1. selectChapter — 记录进入时间（实际函数名是 ch 不是 chapter）
s = patch(s,
    "async function selectChapter(ch: any) {\n  currentChapter.value = ch",
    "async function selectChapter(ch: any) {\n  chapterEnterTime.value = Date.now()\n  errorPatterns.value = []\n  currentChapter.value = ch",
)

# 2. 测验结果展示 — el-result 实际缩进是 6 空格
OLD_RESULT = """      <el-result :icon="quizScore>=60?'success':'warning'" :title="`得分 ${quizScore} 分`" :sub-title="`答对 ${quizCorrect}/${quizTotal} 题，掌握度已更新`">
        <template #extra>
          <el-button type="primary" @click="quizVisible=false">完成</el-button>
          <el-button @click="pickQuestions">换一套题</el-button>
          <el-button type="success" plain @click="quizVisible=false;openReflect()">🧠 写反思巩固</el-button>
        </template>
      </el-result>
    </div>"""

NEW_RESULT = """      <el-result :icon="quizScore>=60?'success':'warning'" :title="`得分 ${quizScore} 分`" :sub-title="`答对 ${quizCorrect}/${quizTotal} 题，掌握度已更新`">
        <template #extra>
          <el-button type="primary" @click="quizVisible=false">完成</el-button>
          <el-button @click="pickQuestions">换一套题</el-button>
          <el-button type="success" plain @click="quizVisible=false;openReflect()">🧠 写反思巩固</el-button>
        </template>
      </el-result>
      <div v-if="errorPatterns.length" style="margin-top:16px;text-align:left">
        <p style="font-size:13px;color:#606266;margin-bottom:8px">近期常错知识点：</p>
        <div v-for="ep in errorPatterns" :key="ep.canonical_name"
          style="display:flex;align-items:center;justify-content:space-between;
                 padding:6px 10px;margin-bottom:4px;background:#fff7e6;
                 border:1px solid #ffe0a0;border-radius:6px">
          <span style="font-size:13px;font-weight:500;color:#303133">{{ ep.canonical_name }}</span>
          <span style="font-size:12px;color:#e6a23c">错误 {{ ep.wrong_count }} 次</span>
        </div>
      </div>
    </div>"""

s = patch(s, OLD_RESULT, NEW_RESULT)

p.write_text(s)
print("✓ TutorialView.vue 前端补丁完成")

if errors:
    print("\n未找到的锚点：")
    for e in errors: print(e)
