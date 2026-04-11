"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h6_db.py
"""
import subprocess

SQL = """
ALTER TABLE chapter_progress
  ADD COLUMN IF NOT EXISTS duration_seconds INTEGER DEFAULT 0;

CREATE TABLE IF NOT EXISTS chapter_quiz_attempts (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL,
    chapter_id      TEXT        NOT NULL,
    score           INTEGER     NOT NULL DEFAULT 0,
    correct_count   INTEGER     NOT NULL DEFAULT 0,
    total_count     INTEGER     NOT NULL DEFAULT 0,
    wrong_entity_ids JSONB      NOT NULL DEFAULT '[]',
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user
    ON chapter_quiz_attempts (user_id, attempted_at DESC);
"""

result = subprocess.run(
    ["docker", "compose", "exec", "-T", "postgres",
     "psql", "-U", "user", "-d", "adaptive_learning", "-c", SQL],
    capture_output=True, text=True
)
print(result.stdout)
if result.returncode == 0:
    print("✓ 数据库迁移成功")
else:
    print("✗ 迁移失败：", result.stderr)
