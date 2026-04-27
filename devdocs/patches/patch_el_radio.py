import re
from pathlib import Path

files = [
    "apps/web/src/views/tutorial/TutorialView.vue",
    "apps/web/src/views/learner/UploadView.vue",
    "apps/web/src/views/learner/QuizView.vue",
]

pattern = re.compile(r'(<el-radio\b[^>]*?)(\s:?label=)(["\'][^"\']*["\'])([^>]*?>)')

def replacer(m):
    tag_start, attr, val, tag_end = m.group(1), m.group(2), m.group(3), m.group(4)
    new_attr = attr.replace('label=', 'value=')
    return f"{tag_start}{new_attr}{val}{tag_end}"

for path_str in files:
    p = Path(path_str)
    if not p.exists():
        print(f"✗ 文件不存在: {path_str}")
        continue
    original = p.read_text()
    updated = pattern.sub(replacer, original)
    if updated != original:
        p.write_text(updated)
        count = len(pattern.findall(original))
        print(f"✓ {p.name}：替换了 {count} 处")
    else:
        print(f"- {p.name}：无需修改")
