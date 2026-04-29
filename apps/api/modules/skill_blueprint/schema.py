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
