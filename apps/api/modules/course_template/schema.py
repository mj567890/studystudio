"""课程模板 Pydantic 模型"""
from pydantic import BaseModel, Field
from datetime import datetime


class CreateTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1)
    is_public: bool = False


class UpdateTemplateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    content: str | None = None
    is_public: bool | None = None


class SetSpaceDefaultTemplateRequest(BaseModel):
    template_id: str | None = None  # 全局默认（向后兼容）
    theory_template_id: str | None = None   # 原理课
    task_template_id: str | None = None     # 任务课
    project_template_id: str | None = None  # 实战课


class TemplateOut(BaseModel):
    template_id: str
    name: str
    content: str
    is_system: bool
    is_public: bool
    created_by: str | None
    created_at: datetime
    updated_at: datetime
