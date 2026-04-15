"""
在服务器 ~/studystudio 目录下执行：
python3 patch_notes_router.py
"""
from pathlib import Path
import shutil

# ── 1. 复制 NotesView.vue 到正确位置 ────────────────────────────────────
src = Path("NotesView.vue")
dst = Path("apps/web/src/views/learner/NotesView.vue")
if src.exists():
    shutil.copy(src, dst)
    print(f"✓ NotesView.vue 已复制到 {dst}")
else:
    print("✗ NotesView.vue 不存在，请先上传文件")

# ── 2. router/index.ts 加 notes 路由 ────────────────────────────────────
p = Path("apps/web/src/router/index.ts")
s = p.read_text()

if "NotesView" in s:
    print("✓ notes 路由已存在，跳过")
else:
    s = s.replace(
        "{ path: 'upload',     component: () => import('@/views/learner/UploadView.vue') },",
        "{ path: 'upload',     component: () => import('@/views/learner/UploadView.vue') },\n        { path: 'notes',      component: () => import('@/views/learner/NotesView.vue') },",
    )
    p.write_text(s)
    print("✓ router/index.ts 已添加 notes 路由")

# ── 3. LayoutView.vue 导航栏加「笔记」入口 ──────────────────────────────
lp = Path("apps/web/src/views/LayoutView.vue")
ls = lp.read_text()

if "notes" in ls and "笔记" in ls:
    print("✓ 导航笔记入口已存在，跳过")
else:
    # 找上传入口，在其后插入笔记
    ls = ls.replace(
        "'/upload'",
        "'/upload'",
    )
    # 更通用的方式：找包含 upload 的导航项
    import re
    # 找 el-menu-item 里含 upload 的那行
    m = re.search(r'(<el-menu-item[^>]*index=["\']\/upload["\'][^>]*>.*?<\/el-menu-item>)', ls, re.DOTALL)
    if m:
        old_item = m.group(0)
        new_item = old_item + '\n        <el-menu-item index="/notes">📒 我的笔记</el-menu-item>'
        ls = ls.replace(old_item, new_item, 1)
        lp.write_text(ls)
        print("✓ LayoutView.vue 导航已添加笔记入口")
    else:
        print("✗ 未找到 upload 导航项，请手动在 LayoutView.vue 导航栏添加：")
        print('  <el-menu-item index="/notes">📒 我的笔记</el-menu-item>')
