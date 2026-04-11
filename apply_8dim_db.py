#!/usr/bin/env python3
"""
八维度数据库迁移
执行：cd ~/studystudio && python3 apply_8dim_db.py
"""
import subprocess
import sys

PSQL = [
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "user", "-d", "adaptive_learning",
]

STATEMENTS = [
    (
        "D3 章内检查点表",
        """
        CREATE TABLE IF NOT EXISTS chapter_checkpoints (
          id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          chapter_id  VARCHAR NOT NULL,
          position    INTEGER NOT NULL,
          question    TEXT    NOT NULL,
          answer_hint TEXT    NOT NULL,
          created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_checkpoints_chapter ON chapter_checkpoints(chapter_id);
        """,
    ),
    (
        "D7 章末反思表",
        """
        CREATE TABLE IF NOT EXISTS chapter_reflections (
          id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          user_id       UUID    NOT NULL REFERENCES users(user_id),
          chapter_id    VARCHAR NOT NULL,
          own_example   TEXT,
          misconception TEXT,
          ai_feedback   TEXT,
          created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(user_id, chapter_id)
        );
        CREATE INDEX IF NOT EXISTS idx_reflections_user ON chapter_reflections(user_id);
        """,
    ),
    (
        "D4 tutorial_annotations 加字段",
        """
        ALTER TABLE tutorial_annotations
          ADD COLUMN IF NOT EXISTS note_type VARCHAR  NOT NULL DEFAULT 'personal',
          ADD COLUMN IF NOT EXISTS likes     INTEGER  NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS is_public BOOLEAN  NOT NULL DEFAULT false;
        CREATE INDEX IF NOT EXISTS idx_annotations_type_public
          ON tutorial_annotations(chapter_id, note_type, is_public);
        """,
    ),
    (
        "D8 学员成就表",
        """
        CREATE TABLE IF NOT EXISTS learner_achievements (
          id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          user_id          UUID    NOT NULL REFERENCES users(user_id),
          achievement_type VARCHAR NOT NULL,
          ref_id           VARCHAR,
          payload          JSONB   NOT NULL DEFAULT '{}',
          earned_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_achievements_user ON learner_achievements(user_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_achievement_user_ref
          ON learner_achievements(user_id, achievement_type, COALESCE(ref_id, ''));
        """,
    ),
    (
        "D6 阅读偏好表",
        """
        CREATE TABLE IF NOT EXISTS learner_learning_mode (
          user_id    UUID PRIMARY KEY REFERENCES users(user_id),
          read_mode  VARCHAR     NOT NULL DEFAULT 'normal',
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """,
    ),
]

VERIFY = """
SELECT table_name FROM information_schema.tables
WHERE table_schema='public'
  AND table_name IN (
    'chapter_checkpoints','chapter_reflections',
    'learner_achievements','learner_learning_mode'
  )
ORDER BY table_name;
"""

def run(sql: str, label: str) -> None:
    result = subprocess.run(
        PSQL + ["-c", sql],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ❌ {label}")
        print(result.stderr)
        sys.exit(1)
    print(f"  ✅ {label}")

print("\n🗄  八维度数据库迁移\n")
for label, sql in STATEMENTS:
    run(sql, label)

print("\n🔍 验证结果：")
result = subprocess.run(PSQL + ["-c", VERIFY], capture_output=True, text=True)
print(result.stdout)

print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("  数据库迁移完成 ✅")
print("  下一步：运行 apply_8dim_phase1.py")
print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
