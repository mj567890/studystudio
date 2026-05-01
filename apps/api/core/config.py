"""
apps/api/core/config.py
配置管理 —— 使用 pydantic-settings，支持环境变量覆盖
敏感信息（密钥、数据库密码）统一从环境变量读取，禁止硬编码
"""
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    url: str = Field(
        default="postgresql+asyncpg://user:pass@localhost:5432/adaptive_learning",
        alias="DATABASE_URL"
    )
    pool_size:    int = 10
    max_overflow: int = 20


class RedisSettings(BaseSettings):
    url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")


class RabbitMQSettings(BaseSettings):
    url: str = Field(
        default="amqp://guest:guest@localhost:5672/",
        alias="RABBITMQ_URL"
    )
    celery_broker_url: str = Field(
        default="amqp://guest:guest@localhost:5672/",
        alias="CELERY_BROKER_URL"
    )


class MinIOSettings(BaseSettings):
    endpoint:    str = Field(default="http://localhost:9000", alias="MINIO_ENDPOINT")
    access_key:  str = Field(default="minioadmin", alias="MINIO_ACCESS_KEY")
    secret_key:  str = Field(default="minioadmin", alias="MINIO_SECRET_KEY")
    bucket:      str = Field(default="adaptive-learning", alias="MINIO_BUCKET")


class LLMSettings(BaseSettings):
    openai_api_key:    str  = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url:   str  = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    default_model:     str  = Field(default="gpt-4o", alias="LLM_DEFAULT_MODEL")
    embedding_model:   str  = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    max_tokens:        int  = 4096
    request_timeout:   float = Field(default=120.0, alias="LLM_REQUEST_TIMEOUT")
    daily_token_budget: int = Field(default=2_000_000, alias="DAILY_TOKEN_BUDGET")


class JWTSettings(BaseSettings):
    secret_key:      str = Field(
        default="",
        alias="JWT_SECRET_KEY",
        description="JWT 签名密钥。生产环境必须设置为强随机字符串（openssl rand -hex 32）"
    )
    algorithm:       str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours


class NormalizationSettings(BaseSettings):
    cross_layer_threshold: float = 0.88   # 跨层去重阈值（宽松，优先减少冗余）
    same_layer_threshold:  float = 0.94   # 同层归一阈值（严格，防止错误合并）
    edit_distance_max:     int   = 3


class MediaSettings(BaseSettings):
    """图表/图片生成网关配置 — Media Gateway"""
    kroki_endpoint:       str   = Field(default="http://kroki:8000", alias="KROKI_ENDPOINT")
    kroki_timeout:        float = Field(default=30.0, alias="KROKI_TIMEOUT")
    diagram_cache_enabled: bool = Field(default=True, alias="DIAGRAM_CACHE_ENABLED")


class TutorialSettings(BaseSettings):
    coherence_embedding_threshold: float = 0.4   # 初始保守值，需根据真实数据校准
    prerequisite_ref_rate_min:     float = 0.3
    max_chunk_count:               int   = 500
    max_file_size_mb:              float = 100.0
    max_path_steps:                int   = 20
    # 文档切分参数
    chunk_size:                    int   = Field(default=3500, alias="CHUNK_SIZE")
    chunk_overlap:                 int   = Field(default=350, alias="CHUNK_OVERLAP")
    ingest_batch_size:             int   = Field(default=50, alias="INGEST_BATCH_SIZE")
    # 知识抽取各阶段文本截断上限（字符数），防止超出 LLM 上下文窗口
    extraction_truncation_entity:   int   = Field(default=2000, alias="EXTRACTION_TRUNCATION_ENTITY")
    extraction_truncation_classify: int   = Field(default=1500, alias="EXTRACTION_TRUNCATION_CLASSIFY")
    extraction_truncation_relation: int   = Field(default=1500, alias="EXTRACTION_TRUNCATION_RELATION")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env:    str = Field(default="development", alias="APP_ENV")
    debug:  bool = Field(default=True, alias="APP_DEBUG")

    database:      DatabaseSettings      = DatabaseSettings()
    redis:         RedisSettings         = RedisSettings()
    rabbitmq:      RabbitMQSettings      = RabbitMQSettings()
    minio:         MinIOSettings         = MinIOSettings()
    llm:           LLMSettings           = LLMSettings()
    jwt:           JWTSettings           = JWTSettings()
    normalization: NormalizationSettings = NormalizationSettings()
    tutorial:      TutorialSettings      = TutorialSettings()
    media:         MediaSettings         = MediaSettings()


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # 安全审计 2026-04-27：非开发环境强制要求 JWT_SECRET_KEY
    if settings.env != "development" and not settings.jwt.secret_key:
        raise RuntimeError(
            "JWT_SECRET_KEY must be set in production environment. "
            "Generate with: openssl rand -hex 32"
        )
    if settings.jwt.secret_key in ("", "change-me-in-production", "dev-secret-key-CHANGE-IN-PRODUCTION"):
        if settings.env != "development":
            raise RuntimeError(
                "JWT_SECRET_KEY is using an insecure default. "
                "Generate with: openssl rand -hex 32"
            )
    return settings


CONFIG = get_settings()
