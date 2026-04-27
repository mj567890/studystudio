"""
packages/shared_schemas/enums.py
共享枚举与常量定义 —— 所有模块共用，禁止在各模块内重复定义
"""
from enum import Enum


class EntityType(str, Enum):
    CONCEPT  = "concept"
    ELEMENT  = "element"
    FLOW     = "flow"
    CASE     = "case"
    DEFENSE  = "defense"


class SpaceType(str, Enum):
    GLOBAL   = "global"
    COURSE   = "course"
    PERSONAL = "personal"


class Visibility(str, Enum):
    PUBLIC  = "public"
    COURSE  = "course"
    PRIVATE = "private"


class ReviewStatus(str, Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class GapType(str, Enum):
    DEFINITION  = "definition"   # 定义型障碍
    MECHANISM   = "mechanism"    # 机制型障碍
    FLOW        = "flow"         # 流程型障碍
    DISTINCTION = "distinction"  # 区分型障碍
    APPLICATION = "application"  # 应用型障碍
    CAUSAL      = "causal"       # 因果型障碍


class MasteryLevel(str, Enum):
    """
    注意两个阈值语义不同（均为有意设计）：
    - HIGH (>= 0.8)：展示级别，用于 UI 展示"已掌握"标签
    - 剪枝阈值 0.7：补洞路径算法中"已掌握可跳过"的宽松标准，减少冗余步骤
    """
    HIGH    = "high"    # mastery_score >= 0.8
    MEDIUM  = "medium"  # mastery_score >= 0.5
    LOW     = "low"     # mastery_score < 0.5


class TutorialStatus(str, Enum):
    DRAFT             = "draft"
    SKELETON_READY    = "skeleton_ready"
    CONTENT_GENERATED = "content_generated"
    REVIEWED          = "reviewed"
    PUBLISHED         = "published"


class DocumentStatus(str, Enum):
    UPLOADED  = "uploaded"
    PARSED    = "parsed"
    EXTRACTED = "extracted"
    REVIEWED  = "reviewed"
    PUBLISHED = "published"


class CertaintyLevel(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


# 置信度映射表
CERTAINTY_SCORE_MAP: dict[str, float] = {
    CertaintyLevel.HIGH:   0.9,
    CertaintyLevel.MEDIUM: 0.6,
    CertaintyLevel.LOW:    0.3,
}

# 冷启动掌握度映射：(basic_correct, advanced_correct) -> initial_score
PLACEMENT_SCORE_MAP: dict[tuple[bool, bool], float] = {
    (True,  True):  0.75,
    (True,  False): 0.50,
    (False, True):  0.40,
    (False, False): 0.15,
}
