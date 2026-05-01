from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel

class EntityLinkOut(BaseModel):
    entity_id:        str
    canonical_name:   str
    short_definition: Optional[str] = None
    link_type:        str

class ChapterOut(BaseModel):
    chapter_id:       str
    title:            str
    objective:        Optional[str] = None
    task_description: Optional[str] = None
    pass_criteria:    Optional[str] = None
    common_mistakes:  Optional[str] = None
    content_text:     Optional[str] = None
    chapter_order:    int
    status:           str
    hotwords:         List[EntityLinkOut] = []

class StageOut(BaseModel):
    stage_id:    str
    title:       str
    description: Optional[str] = None
    stage_type:  str
    stage_order: int
    chapters:    List[ChapterOut] = []

class BlueprintOut(BaseModel):
    blueprint_id: str
    topic_key:    str
    title:        str
    skill_goal:   Optional[str] = None
    status:       str
    version:      int
    stages:       List[StageOut] = []
    space_id:     Optional[str] = None
    created_at:   datetime
    updated_at:   datetime

class BlueprintStatusOut(BaseModel):
    topic_key:    str
    status:       str
    blueprint_id: Optional[str] = None
    space_id:     Optional[str] = None
    message:      str

class GenerateBlueprintRequest(BaseModel):
    space_id:            Optional[str] = None
    force_regen:         bool = False
    teacher_instruction: Optional[str] = None
    type_instructions:   Optional[dict] = None  # {"theory": "...", "task": "...", "project": "..."}

class StartGenerationRequest(BaseModel):
    space_id:              str
    selected_proposal_id:  str  # "A" / "B" / "C"
    adjustments:           Optional[dict] = None  # {total_hours, difficulty, theory_ratio}
    extra_notes:           Optional[str] = None   # 教师额外要求
    calibration_answers:   Optional[dict] = None   # ★v2.2: 5 道经验校准题答案 {q1_pain_points: [...], ...}
    course_map_confirmed:  bool = False           # ★v2.2: 教师是否确认了 Course Map

class ProposalAdjustments(BaseModel):
    total_hours:   Optional[int] = None
    difficulty:    Optional[str] = None  # beginner/intermediate/advanced
    theory_ratio:  Optional[int] = None  # 0-100

# ══════════════════════════════════════════
# v2.2 新增：经验校准 + Course Map
# ══════════════════════════════════════════

class CalibrationAnswers(BaseModel):
    answers: dict  # {q1_pain_points: [...], q2_cases: "...", q3_misconceptions: [...], q4_priority: [...], q5_red_lines: [...]}

class CalibrationQuestionRequest(BaseModel):
    space_id: str
    selected_proposal_id: str
    adjustments: Optional[dict] = None

class CourseMapRegenerateRequest(BaseModel):
    reason: str  # "order" | "granularity" | "priority" | "mark_mode" | "not_sure"
    marked_chapters: Optional[dict] = None  # mark_mode 时使用
