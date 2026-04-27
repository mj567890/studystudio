import json
import sys
sys.path.insert(0, '/app')
from apps.api.tasks.blueprint_tasks import _normalize_chapter_content

# Test 1: Bare SQL in full_content
data1 = {
    "full_content": "先看一个查询：\nSELECT * FROM users\nWHERE id = 1\n这就是SQL注入。",
    "code_example": "",
    "scene_hook": "",
    "misconception_block": "",
    "skim_summary": "",
}
text1 = json.dumps(data1, ensure_ascii=False)
r1 = _normalize_chapter_content(text1)
fc1 = json.loads(r1) if isinstance(r1, str) else r1
has_pre1 = '<pre><code' in fc1.get('full_content', '')
print(f"Test 1 (bare SQL wrapped): {has_pre1}")
if has_pre1:
    print(f"  Result preview: {fc1['full_content'][:300]}")

# Test 2: Bare Python
data2 = {
    "full_content": "代码如下：\ndef scan_port(host, port):\n    sock = socket.socket()\n    sock.connect((host, port))\n这样就可以扫描端口。",
    "code_example": "",
    "scene_hook": "",
    "misconception_block": "",
    "skim_summary": "",
}
text2 = json.dumps(data2, ensure_ascii=False)
r2 = _normalize_chapter_content(text2)
fc2 = json.loads(r2) if isinstance(r2, str) else r2
has_pre2 = '<pre><code' in fc2.get('full_content', '')
print(f"Test 2 (bare Python wrapped): {has_pre2}")

# Test 3: Chinese text only (no code, should NOT wrap)
data3 = {
    "full_content": "SQL注入是一种常见的攻击方式，攻击者通过在输入中插入恶意SQL语句来操作数据库。防御方法包括参数化查询和输入验证。",
    "code_example": "",
    "scene_hook": "",
    "misconception_block": "",
    "skim_summary": "",
}
text3 = json.dumps(data3, ensure_ascii=False)
r3 = _normalize_chapter_content(text3)
fc3 = json.loads(r3) if isinstance(r3, str) else r3
pre_count3 = fc3.get('full_content', '').count('<pre>')
print(f"Test 3 (Chinese only, pre count): {pre_count3}")

# Test 4: Single code line (should NOT wrap, need >=2 lines)
data4 = {
    "full_content": "一行代码：print('hello')就够了。",
    "code_example": "",
    "scene_hook": "",
    "misconception_block": "",
    "skim_summary": "",
}
text4 = json.dumps(data4, ensure_ascii=False)
r4 = _normalize_chapter_content(text4)
fc4 = json.loads(r4) if isinstance(r4, str) else r4
pre_count4 = fc4.get('full_content', '').count('<pre>')
print(f"Test 4 (single line, pre count): {pre_count4}")

print("\nAll tests completed!")
