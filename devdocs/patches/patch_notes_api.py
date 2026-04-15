"""
在服务器 ~/studystudio 目录下执行：
python3 patch_notes_api.py
"""
from pathlib import Path

p = Path("apps/web/src/api/index.ts")
s = p.read_text()

NEW = """
// 个人笔记
export const notesApi = {
  list:   (params?: { topic_key?: string; keyword?: string }) =>
    http.get('/learners/me/notes', { params }),
  create: (data: {
    title?: string; content: string; source_type?: string
    topic_key?: string; chapter_id?: string; chapter_title?: string
    conversation_id?: string; tags?: string[]
  }) => http.post('/learners/me/notes', data),
  update: (noteId: string, data: { title?: string; content?: string; tags?: string[] }) =>
    http.put(`/learners/me/notes/${noteId}`, data),
  remove: (noteId: string) =>
    http.delete(`/learners/me/notes/${noteId}`),
}

// 对话重命名
export const convRenameApi = {
  rename: (conversationId: string, title: string) =>
    http.put(`/teaching/conversations/${conversationId}/title`, { title }),
}
"""

if "notesApi" in s:
    print("✓ notesApi 已存在，跳过")
else:
    p.write_text(s + NEW)
    print("✓ api/index.ts 已更新")
