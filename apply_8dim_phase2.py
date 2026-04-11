#!/usr/bin/env python3
"""
apply_8dim_phase2.py
八维度系统 Phase 2：前端部署

执行内容：
  1. 追加 api/index.ts     （新增 8 个 API 命名空间）
  2. 替换 TutorialView.vue （完整重写，含八维度全部 UI）
  3. 触发 docker compose build web && up -d

运行方式（项目根目录）：
  python3 apply_8dim_phase2.py
"""
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT    = Path(__file__).parent
WEB_SRC = ROOT / "apps/web/src"

def ok(msg):   print(f"  \033[32m✓\033[0m  {msg}")
def info(msg): print(f"  \033[34m→\033[0m  {msg}")
def warn(msg): print(f"  \033[33m⚠\033[0m  {msg}")
def fail(msg): print(f"  \033[31m✗\033[0m  {msg}"); sys.exit(1)

def backup(path: Path):
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".bak.8dim.{ts}")
    shutil.copy2(path, bak)
    info(f"备份 → {bak.name}")
    return bak

# ════════════════════════════════════════════════════════════════
# 步骤 1：追加 api/index.ts
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 1：扩展 api/index.ts\033[0m")

API_TS = WEB_SRC / "api/index.ts"
if not API_TS.exists():
    fail(f"找不到 {API_TS}")

content = API_TS.read_text(encoding="utf-8")
if "learningModeApi" in content:
    ok("api/index.ts 已包含八维度接口，跳过")
else:
    backup(API_TS)
    APPEND = """
// ══ 八维度学习增强系统 API ════════════════════════════════════

// D6：学习节奏偏好
export const learningModeApi = {
  get: () =>
    http.get('/learners/me/learning-mode'),
  set: (readMode: 'skim' | 'normal' | 'deep') =>
    http.post('/learners/me/learning-mode', { read_mode: readMode }),
}

// D7：章末反思
export const reflectApi = {
  get: (chapterId: string) =>
    http.get(`/learners/me/reflect/${chapterId}`),
  submit: (data: { chapter_id: string; own_example: string; misconception?: string }) =>
    http.post('/learners/me/reflect', data),
}

// D4：社区笔记
export const socialApi = {
  getNotes: (chapterId: string) =>
    http.get(`/tutorials/social-notes/${chapterId}`),
  postNote: (data: {
    tutorial_id: string; chapter_id: string
    note_type: string; content: string; is_public: boolean
  }) => http.post('/tutorials/social-notes', data),
  likeNote: (noteId: string) =>
    http.post(`/tutorials/social-notes/${noteId}/like`),
}

// D8：成就 + 掌握度雷达
export const achievementApi = {
  list: () =>
    http.get('/learners/me/achievements'),
  radar: (topicKey: string) =>
    http.get('/learners/me/mastery-radar', { params: { topic_key: topicKey } }),
}

// D2/D7：主观题 AI 批改
export const rubricApi = {
  check: (data: { question_id: string; ai_rubric: string; answer: string }) =>
    http.post('/learners/me/rubric-check', data),
}
"""
    with API_TS.open("a", encoding="utf-8") as f:
        f.write(APPEND)
    ok("api/index.ts 追加完成（5 个新命名空间）")

# ════════════════════════════════════════════════════════════════
# 步骤 2：替换 TutorialView.vue
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 2：部署 TutorialView.vue（八维度增强版）\033[0m")

TV_DEST = WEB_SRC / "views/tutorial/TutorialView.vue"
TV_SRC  = ROOT / "TutorialView_8dim.vue"

if not TV_SRC.exists():
    fail(f"找不到源文件 TutorialView_8dim.vue，请确保它在 {ROOT}")

if TV_DEST.exists():
    backup(TV_DEST)

shutil.copy2(TV_SRC, TV_DEST)
ok("TutorialView.vue 替换完成")

# ════════════════════════════════════════════════════════════════
# 步骤 3：确认 router/index.ts 无需修改（路由路径未变）
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 3：检查路由配置\033[0m")

ROUTER_TS = WEB_SRC / "router/index.ts"
if ROUTER_TS.exists():
    r = ROUTER_TS.read_text(encoding="utf-8")
    if "/tutorial" in r:
        ok("router/index.ts 已有 /tutorial 路由，无需修改")
    else:
        warn("/tutorial 路由未找到，请确认 TutorialView 已正确注册")
else:
    warn("未找到 router/index.ts，请手动检查路由")

# ════════════════════════════════════════════════════════════════
# 步骤 4：构建前端镜像
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 4：构建前端 Docker 镜像\033[0m")
info("正在构建 web 镜像（约 2-4 分钟）…")

result = subprocess.run(
    ["docker", "compose", "build", "web"],
    cwd=ROOT,
    capture_output=False,   # 实时输出到终端
)
if result.returncode != 0:
    fail("docker compose build web 失败，请检查上方错误输出")
ok("web 镜像构建完成")

# ════════════════════════════════════════════════════════════════
# 步骤 5：重启前端容器
# ════════════════════════════════════════════════════════════════
print("\n\033[1m🔧 步骤 5：重启前端容器\033[0m")

result = subprocess.run(
    ["docker", "compose", "up", "-d", "web"],
    cwd=ROOT,
    capture_output=False,
)
if result.returncode != 0:
    fail("docker compose up -d web 失败")
ok("web 容器已重启")

# ════════════════════════════════════════════════════════════════
# 完成
# ════════════════════════════════════════════════════════════════
print("""
\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m
\033[32m  Phase 2 前端部署完成 ✅\033[0m
\033[32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m

  已完成：
  ✓ api/index.ts       新增 5 个 API 命名空间
  ✓ TutorialView.vue   八维度完整 UI（含备份）
  ✓ web 容器           已重新构建并重启

  验证步骤（浏览器打开）：
  → 教程中心是否显示  速览/标准/精读  切换按钮
  → 章节顶部是否显示  💡 情境开篇
  → 正文中是否出现    ⏸ 检查点气泡（需先重新生成蓝图）
  → 底部是否新增      🧠 写反思  按钮
  → 是否显示          同学笔记  区块

  ⚠️  现有章节内容（旧格式纯文本）将正常显示，但不带新特性。
     新特性需要重新生成蓝图才激活：
     管理后台 → 知识库管理 → 选择领域 → 重新生成蓝图

  下一步：
  → 浏览器测试新 UI，反馈问题
  → 触发一个领域的蓝图重新生成，验证新 Prompt 效果
""")
