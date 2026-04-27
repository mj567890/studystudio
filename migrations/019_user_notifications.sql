-- 019_user_notifications.sql
-- 用户通知系统：文档处理完成后通知用户

CREATE TABLE IF NOT EXISTS user_notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    type VARCHAR(50) NOT NULL,           -- 'document_complete' | 'document_failed' | 'blueprint_ready'
    title VARCHAR(200) NOT NULL,
    message TEXT,
    target_type VARCHAR(50),              -- 'document' | 'blueprint' | 'space'
    target_id UUID,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_notifications_user ON user_notifications(user_id, is_read);
CREATE INDEX idx_user_notifications_unread ON user_notifications(user_id, is_read) WHERE is_read = FALSE;
CREATE INDEX idx_user_notifications_created ON user_notifications(created_at DESC);
