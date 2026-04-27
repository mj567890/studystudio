-- Phase 2: 订阅表
CREATE TABLE IF NOT EXISTS space_subscriptions (
    subscription_id   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    subscriber_id     uuid        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    space_id          uuid        NOT NULL REFERENCES knowledge_spaces(space_id) ON DELETE CASCADE,
    topic_key         varchar(255) NOT NULL,
    subscribed_version int        NOT NULL DEFAULT 1,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (subscriber_id, space_id, topic_key)
);

CREATE INDEX IF NOT EXISTS idx_ss_subscriber ON space_subscriptions(subscriber_id);
CREATE INDEX IF NOT EXISTS idx_ss_space_topic ON space_subscriptions(space_id, topic_key);
