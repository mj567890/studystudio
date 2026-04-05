"""
apps/api/modules/knowledge/extraction_pipeline.py
Block B：知识抽取分层管线

四步抽取：实体识别 → 实体分类 → 关系识别 → 流程重建
双轨校验：JSON Schema 强校验 + 业务规则软校验
FewShotManager：注入领域示例，提升抽取准确率
三级降级：warn(70%) / pause(60%) / stop(50%)
"""
import json
import uuid
from typing import Any

import jsonschema
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.llm_gateway import get_llm_gateway

logger = structlog.get_logger(__name__)

# ── JSON Schema 定义 ─────────────────────────────────────────────────────
ENTITY_RECOGNITION_SCHEMA = {
    "type": "object",
    "required": ["entities"],
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "short_definition"],
                "properties": {
                    "name":              {"type": "string", "minLength": 1},
                    "short_definition":  {"type": "string"},
                    "aliases":           {"type": "array", "items": {"type": "string"}},
                }
            }
        }
    }
}

ENTITY_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "required": ["classified"],
    "properties": {
        "classified": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "entity_type"],
                "properties": {
                    "name":                {"type": "string"},
                    "entity_type":         {"type": "string",
                                           "enum": ["concept","element","flow","case","defense"]},
                    "detailed_explanation": {"type": "string"},
                }
            }
        }
    }
}

RELATION_EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["relations"],
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source", "target", "relation_type"],
                "properties": {
                    "source":        {"type": "string"},
                    "target":        {"type": "string"},
                    "relation_type": {"type": "string",
                                     "enum": ["prerequisite_of","related","part_of","instance_of"]},
                }
            }
        }
    }
}


# ── Prompt 模板 ──────────────────────────────────────────────────────────
ENTITY_RECOGNITION_PROMPT = """你是专业的知识点抽取专家。请从以下文本中识别所有知识点（实体），以 JSON 格式输出。
不要进行分类，只识别名称和简要定义。

文本：
{text}

{few_shot_examples}

请严格输出以下 JSON 格式，不要输出其他内容：
{{"entities": [{{"name": "知识点名称", "short_definition": "简要定义", "aliases": ["别名1"]}}]}}
"""

ENTITY_CLASSIFICATION_PROMPT = """请对以下已识别的知识点进行类型分类。
类型说明：
- concept：概念性知识（定义、原理）
- element：组成要素（组件、属性）
- flow：流程性知识（步骤、过程）
- case：案例（漏洞示例、攻击案例）
- defense：防御措施

已识别的知识点：
{entities_json}

请严格输出以下 JSON：
{{"classified": [{{"name": "知识点名称", "entity_type": "类型", "detailed_explanation": "详细说明"}}]}}
"""

RELATION_EXTRACTION_PROMPT = """请识别以下知识点之间的关系。
关系类型：
- prerequisite_of：A prerequisite_of B → 学习 B 需要先掌握 A
- related：A related B → A 和 B 相关但无前后依赖
- part_of：A part_of B → A 是 B 的组成部分
- instance_of：A instance_of B → A 是 B 的具体实例

已分类的知识点：
{entities_json}

原始文本上下文：
{context}

请严格输出以下 JSON：
{{"relations": [{{"source": "A名称", "target": "B名称", "relation_type": "类型"}}]}}
"""


# ── FewShotManager ────────────────────────────────────────────────────────
class FewShotManager:
    """
    注入领域级 few-shot 示例，提升 LLM 抽取准确率。
    阶段 1 目标：准确率 >= 70%；阶段 2 >= 85%（配合 few-shot）；阶段 3 >= 90%
    """

    EXAMPLES: dict[str, str] = {
        "php-security": """
示例输入：PHP的文件包含漏洞是指攻击者通过控制include参数来包含任意文件。
示例输出：{"entities": [
  {"name": "文件包含漏洞", "short_definition": "攻击者控制include参数包含任意文件的漏洞"},
  {"name": "include参数", "short_definition": "PHP中用于包含文件的函数参数"}
]}
""",
        "default": """
示例：请识别文本中所有有价值的知识点，包括概念、技术术语、操作步骤等。
每个知识点应有清晰的定义。
""",
    }

    def get_examples(self, domain_tag: str) -> str:
        # 按领域前缀匹配
        for key in self.EXAMPLES:
            if key != "default" and domain_tag.startswith(key.split("-")[0]):
                return self.EXAMPLES[key]
        return self.EXAMPLES["default"]


few_shot_manager = FewShotManager()


# ── 抽取管线 ─────────────────────────────────────────────────────────────
class ExtractionPipeline:
    """
    四步分层抽取管线。每步独立校验，失败只回退该步骤，不整批重跑。
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db  = db
        self.llm = get_llm_gateway()

    async def run(
        self,
        chunk_id:    str,
        content:     str,
        space_type:  str,
        space_id:    str | None,
        domain_tag:  str,
        owner_id:    str,
    ) -> dict[str, list]:
        """
        执行完整的四步抽取，返回候选实体和关系列表。
        """
        few_shot = few_shot_manager.get_examples(domain_tag)

        # Step 1: 实体识别
        raw_entities = await self._step_entity_recognition(content, few_shot, chunk_id)
        if not raw_entities:
            return {"entities": [], "relations": []}

        # Step 2: 实体分类
        classified = await self._step_entity_classification(raw_entities, chunk_id)
        if not classified:
            return {"entities": [], "relations": []}

        # Step 3: 关系识别
        relations = await self._step_relation_extraction(classified, content, chunk_id)

        # Step 4: 流程重建（仅对 flow 类型）
        flow_entities = [e for e in classified if e.get("entity_type") == "flow"]
        # 流程实体的详细步骤已在 Step 2 中提取，此处可进一步结构化（当前版本跳过）

        # 添加空间元数据
        for entity in classified:
            entity["space_type"] = space_type
            entity["space_id"]   = space_id
            entity["owner_id"]   = owner_id
            entity["domain_tag"] = domain_tag
            entity["entity_id"]  = str(uuid.uuid4())

        return {"entities": classified, "relations": relations}

    async def _step_entity_recognition(
        self, content: str, few_shot: str, chunk_id: str
    ) -> list[dict]:
        prompt = ENTITY_RECOGNITION_PROMPT.format(
            text=content[:3000],
            few_shot_examples=few_shot
        )
        try:
            response = await self.llm.generate(prompt)
            data = self._parse_json(response)
            jsonschema.validate(data, ENTITY_RECOGNITION_SCHEMA)
            return data["entities"]
        except (json.JSONDecodeError, jsonschema.ValidationError, Exception) as e:
            await self._push_audit(chunk_id, "entity_recognition", str(e), "")
            return []

    async def _step_entity_classification(
        self, entities: list[dict], chunk_id: str
    ) -> list[dict]:
        prompt = ENTITY_CLASSIFICATION_PROMPT.format(
            entities_json=json.dumps(entities, ensure_ascii=False)
        )
        try:
            response = await self.llm.generate(prompt)
            data = self._parse_json(response)
            jsonschema.validate(data, ENTITY_CLASSIFICATION_SCHEMA)
            return data["classified"]
        except Exception as e:
            await self._push_audit(chunk_id, "entity_classification", str(e), "")
            return []

    async def _step_relation_extraction(
        self, entities: list[dict], context: str, chunk_id: str
    ) -> list[dict]:
        prompt = RELATION_EXTRACTION_PROMPT.format(
            entities_json=json.dumps(
                [{"name": e["name"], "type": e.get("entity_type")} for e in entities],
                ensure_ascii=False
            ),
            context=context[:2000],
        )
        try:
            response = await self.llm.generate(prompt)
            data = self._parse_json(response)
            jsonschema.validate(data, RELATION_EXTRACTION_SCHEMA)

            # 软校验：关系两端必须是已识别的实体
            entity_names = {e["name"] for e in entities}
            valid_relations = [
                r for r in data["relations"]
                if r["source"] in entity_names and r["target"] in entity_names
            ]
            return valid_relations
        except Exception as e:
            await self._push_audit(chunk_id, "relation_extraction", str(e), "")
            return []

    def _parse_json(self, text: str) -> dict:
        """清理并解析 LLM 返回的 JSON，处理可能的 markdown 包裹。"""
        import re
        cleaned = re.sub(r"^```json\s*|\s*```$", "", text.strip())
        return json.loads(cleaned)

    async def _push_audit(
        self, chunk_id: str, step: str, error: str, raw_output: str
    ) -> None:
        """将失败信息推入审核队列。"""
        await self.db.execute(
            text("""
                INSERT INTO extract_audit (audit_id, chunk_id, step, error, raw_output)
                VALUES (:audit_id, :chunk_id, :step, :error, :raw_output)
            """),
            {
                "audit_id":   str(uuid.uuid4()),
                "chunk_id":   chunk_id,
                "step":       step,
                "error":      error[:500],
                "raw_output": raw_output[:2000],
            }
        )
        logger.warning("Extraction step failed", chunk_id=chunk_id, step=step, error=error[:200])
