"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h7_frontend.py
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

# ── 1. 消息对象加 proactive_question 字段 ─────────────────────────────────
s = patch(s,
    """      content:    data.assistant_message,
      diagnosis:  data.diagnosis_update,
      next_steps: data.suggested_next_steps,""",
    """      content:            data.assistant_message,
      diagnosis:          data.diagnosis_update,
      next_steps:         data.suggested_next_steps,
      proactive_question: data.proactive_question || null,""",
)

# ── 2. 模板：next_steps 下方插入追问气泡 ──────────────────────────────────
s = patch(s,
    """            <div v-if="msg.next_steps && msg.next_steps.length" class="next-steps">
              <p style="font-size:12px;color:#909399;margin-bottom:6px">🔗 相关知识点</p>
              <el-tag
                v-for="s in msg.next_steps"
                :key="s.ref_id"
                size="small"
                style="margin:2px;cursor:pointer"
                @click="sendMessage(`请解释一下「${s.title}」`)"
              >{{ s.title }}</el-tag>
            </div>""",
    """            <div v-if="msg.next_steps && msg.next_steps.length" class="next-steps">
              <p style="font-size:12px;color:#909399;margin-bottom:6px">🔗 相关知识点</p>
              <el-tag
                v-for="s in msg.next_steps"
                :key="s.ref_id"
                size="small"
                style="margin:2px;cursor:pointer"
                @click="sendMessage(`请解释一下「${s.title}」`)"
              >{{ s.title }}</el-tag>
            </div>
            <!-- H-7 苏格拉底式追问 -->
            <div v-if="msg.proactive_question" class="proactive-q">
              <span class="pq-icon">🤔</span>
              <span class="pq-text">{{ msg.proactive_question }}</span>
              <el-button
                size="small" type="primary" plain
                style="margin-left:8px;flex-shrink:0"
                @click="sendMessage(msg.proactive_question)"
              >回答这个问题</el-button>
            </div>""",
)

# ── 3. 样式：追问气泡 CSS ──────────────────────────────────────────────────
STYLE_ANCHOR = ".chat-layout {"
s = patch(s, STYLE_ANCHOR,
    """.proactive-q {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 12px;
  background: #f0f7ff;
  border: 1px solid #cce0ff;
  border-radius: 8px;
  font-size: 13px;
  color: #1a6db5;
  flex-wrap: wrap;
}
.pq-icon { font-size: 14px; flex-shrink: 0; margin-top: 1px; }
.pq-text { flex: 1; line-height: 1.5; min-width: 0; }

""" + STYLE_ANCHOR,
    "prepend"
)

p.write_text(s)
print("✓ ChatView.vue H-7 补丁完成")

if errors:
    print("\n未找到的锚点：")
    for e in errors:
        print(e)
