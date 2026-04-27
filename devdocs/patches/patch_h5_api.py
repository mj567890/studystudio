"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h5_api.py
"""
from pathlib import Path

p = Path("apps/web/src/api/index.ts")
src = p.read_text()

NEW_API = """
// H-5：关联知识推荐
export const recommendApi = {
  getRelated: (chapterId: string) =>
    http.get('/learners/me/related-recommendations', { params: { chapter_id: chapterId } }),
}
"""

if "recommendApi" in src:
    print("✓ recommendApi 已存在，跳过")
else:
    p.write_text(src + NEW_API)
    print("✓ recommendApi 已追加到 api/index.ts")
