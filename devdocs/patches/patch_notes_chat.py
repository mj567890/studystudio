"""
在服务器 ~/studystudio 目录下执行：
python3 patch_notes_chat.py
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


p = Path("apps/web/src/views/tutorial/ChatView.vue")
s = p.read_text()

# ── 1. import 加 notesApi / convRenameApi ────────────────────────────────
s = patch(s,
    "import { learnerApi, knowledgeApi, tutorialApi } from '@/api'",
    "import { learnerApi, knowledgeApi, tutorialApi, notesApi, convRenameApi } from '@/api'",
)

# ── 2. AI 气泡：next_steps 上方加「存为笔记」按钮 ───────────────────────
s = patch(s,
    '<div v-if="msg.next_steps && msg.next_steps.length" class="next-steps">',
    """<div style="margin-top:6px;text-align:right">
              <el-button link size="small" style="color:#909399;font-size:12px"
                @click="saveAsNote(msg)">📌 存为笔记</el-button>
            </div>
            <div v-if="msg.next_steps && msg.next_steps.length" class="next-steps">""",
)

# ── 3. 对话列表：对话名称旁加重命名按钮 ─────────────────────────────────
# 找对话列表项模板，在 turn_count 旁加 rename 按钮
OLD_CONV_ITEM = """@click="selectConversation(conv.conversation_id)">"""
NEW_CONV_ITEM = """@click="selectConversation(conv.conversation_id)">"""
# 找 deleteConversation 按钮，在旁边加重命名
s = patch(s,
    '@click.stop="deleteConversation(conv.conversation_id)"',
    '@click.stop="startRename(conv)" style="color:#409eff">✏️</el-button>\n              <el-button link size="small" style="color:#f56c6c;padding:0"\n                @click.stop="deleteConversation(conv.conversation_id)"',
)

# ── 4. script：加 saveAsNote / startRename 函数 ──────────────────────────
s = patch(s,
    "async function sendMessage(text: string) {",
    """async function saveAsNote(msg: any) {
  if (!msg.content) return
  try {
    const res: any = await notesApi.create({
      content:         msg.content,
      source_type:     'ai_chat',
      topic_key:       topicKey.value,
      chapter_id:      chapterId.value || '',
      chapter_title:   chapterTitle.value || '',
      conversation_id: conversationId.value,
    })
    ElMessage.success(`已存为笔记：${res.data?.title || ''}`)
  } catch {
    ElMessage.error('存为笔记失败')
  }
}

async function startRename(conv: any) {
  try {
    const { value } = await (ElMessageBox as any).prompt('输入新名称', '重命名对话', {
      confirmButtonText: '确认',
      cancelButtonText:  '取消',
      inputValue:        conv.title || '',
      inputValidator:    (v: string) => v.trim() ? true : '名称不能为空',
    })
    await convRenameApi.rename(conv.conversation_id, value.trim())
    conv.title = value.trim()
    ElMessage.success('已重命名')
  } catch { /* 取消 */ }
}

async function sendMessage(text: string) {""",
)

# ── 5. import ElMessageBox ───────────────────────────────────────────────
s = patch(s,
    "import { ElMessage } from 'element-plus'",
    "import { ElMessage, ElMessageBox } from 'element-plus'",
)

p.write_text(s)
print("✓ ChatView.vue 笔记+重命名补丁完成")

if errors:
    print("\n未找到的锚点：")
    for e in errors:
        print(e)
