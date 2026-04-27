-- 011: wall_posts 加 space_id，支持按课程隔离讨论
ALTER TABLE wall_posts
  ADD COLUMN space_id UUID REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE;

CREATE INDEX idx_wall_posts_space ON wall_posts(space_id, created_at DESC);
