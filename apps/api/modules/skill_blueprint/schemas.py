from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChapterGlossaryItem(BaseModel):
    entity_id: str
    canonical_name: str = ""
    entity_type: str = ""
    short_definition: str = ""
    detailed_explanation: str = ""
    link_role: Literal["core", "glossary", "support"] = "glossary"


class SkillChapter(BaseModel):
    chapter_id: str
    stage_id: str
    chapter_order: int = 1
    title: str
    objective: str = ""
    can_do_after: str = ""
    practice_task: str = ""
    pass_criteria: str = ""
    estimated_minutes: int = 30
    learning_points: list[str] = Field(default_factory=list)
    target_entity_ids: list[str] = Field(default_factory=list)
    glossary_entity_ids: list[str] = Field(default_factory=list)
    glossary: list[ChapterGlossaryItem] = Field(default_factory=list)


class SkillStage(BaseModel):
    stage_id: str
    stage_order: int = 1
    title: str
    objective: str = ""
    can_do_after: str = ""
    chapters: list[SkillChapter] = Field(default_factory=list)


class SkillBlueprint(BaseModel):
    blueprint_id: str
    topic_key: str
    space_type: str = "personal"
    space_id: str | None = None
    version: int = 1
    status: str = "draft"
    skill_goal: str = ""
    target_role: str = ""
    summary: str = ""
    source_fingerprint: str = ""
    source_entity_count: int = 0
    stages: list[SkillStage] = Field(default_factory=list)


class PathStep(BaseModel):
    step_id: str
    type: Literal["chapter", "entity"] = "chapter"
    title: str
    objective: str = ""
    topic_key: str
    chapter_id: str | None = None
    estimated_minutes: int = 30
    unlocked: bool = True
    score: float = 1.0


class TopicCard(BaseModel):
    topic_key: str
    space_type: str = "personal"
    space_id: str | None = None
    version: int = 1
    status: str = "draft"
    skill_goal: str = ""
    summary: str = ""
    chapter_count: int = 0
    approved_entity_count: int = 0
    updated_at: str | None = None


class ChapterContent(BaseModel):
    chapter_id: str
    title: str
    objective: str = ""
    can_do_after: str = ""
    practice_task: str = ""
    pass_criteria: str = ""
    learning_points: list[str] = Field(default_factory=list)
    sections: list[dict] = Field(default_factory=list)
    glossary: list[ChapterGlossaryItem] = Field(default_factory=list)
