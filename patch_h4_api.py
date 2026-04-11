"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h4_api.py
"""
from pathlib import Path

p = Path("apps/web/src/api/index.ts")
src = p.read_text()

ANCHOR = "// D2/D7：主观题 AI 批改"

NEW_API = """// H-4：遗忘曲线复习提醒
export const reviewApi = {
  getDue: () => http.get('/learners/me/review-due'),
}

"""

if "reviewApi" in src:
    print("✓ reviewApi 已存在，跳过")
elif ANCHOR not in src:
    # 直接追加到文件末尾
    p.write_text(src + "\n// H-4：遗忘曲线复习提醒\nexport const reviewApi = {\n  getDue: () => http.get('/learners/me/review-due'),\n}\n")
    print("✓ reviewApi 已追加到 api/index.ts 末尾")
else:
    p.write_text(src.replace(ANCHOR, NEW_API + ANCHOR))
    print("✓ reviewApi 已插入 api/index.ts")
