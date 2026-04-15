"""
在服务器 ~/studystudio 目录下执行：
python3 patch_h7_backend.py
"""
from pathlib import Path

errors = []

def patch(content, anchor, new_text, mode="replace"):
    if anchor not in content:
        errors.append(f"  ✗ 未找到锚点: {repr(anchor[:70])}")
        return content
    if mode == "prepend":
        return content.replace(anchor, new_text + anchor, 1)
    return content.replace(anchor, new_text, 1)


# ════════════════════════════════════════════════════════════════
# 1. llm_gateway.py — 加 proactive_question 字段
# ════════════════════════════════════════════════════════════════
p1 = Path("apps/api/core/llm_gateway.py")
s1 = p1.read_text()

# Prompt suffix 加字段说明
s1 = patch(s1,
    '"error_pattern": "一句话描述用户的错误推理，如无则为 null"\n}',
    '"error_pattern": "一句话描述用户的错误推理，如无则为 null",\n  "proactive_question": "一个苏格拉底式追问，帮助学员深化理解；若本轮无需追问则为 null"\n}',
)

# TeachResponse 类加字段
s1 = patch(s1,
    "    def __init__(\n        self,\n        response_text: str,\n        certainty_level: str,\n        gap_types: list[str],\n        error_pattern: str | None,\n    ) -> None:\n        self.response_text    = response_text\n        self.certainty_level  = certainty_level\n        self.gap_types        = [GapType(g) for g in gap_types if g in GapType._value2member_map_]\n        self.error_pattern    = error_pattern",
    "    def __init__(\n        self,\n        response_text: str,\n        certainty_level: str,\n        gap_types: list[str],\n        error_pattern: str | None,\n        proactive_question: str | None = None,\n    ) -> None:\n        self.response_text       = response_text\n        self.certainty_level     = certainty_level\n        self.gap_types           = [GapType(g) for g in gap_types if g in GapType._value2member_map_]\n        self.error_pattern       = error_pattern\n        self.proactive_question  = proactive_question",
)

# _call_teach 解析时加字段
s1 = patch(s1,
    "        return TeachResponse(\n            response_text=data.get(\"response\", \"\"),\n            certainty_level=data.get(\"certainty_level\", \"medium\"),\n            gap_types=data.get(\"gap_types\", []),\n            error_pattern=data.get(\"error_pattern\"),\n        )",
    "        return TeachResponse(\n            response_text=data.get(\"response\", \"\"),\n            certainty_level=data.get(\"certainty_level\", \"medium\"),\n            gap_types=data.get(\"gap_types\", []),\n            error_pattern=data.get(\"error_pattern\"),\n            proactive_question=data.get(\"proactive_question\"),\n        )",
)

# Prompt suffix 加追问策略说明
s1 = patch(s1,
    "gap_types 可选值：definition / mechanism / flow / distinction / application / causal\n\"\"\"",
    """gap_types 可选值：definition / mechanism / flow / distinction / application / causal
proactive_question 策略：
  - certainty_level 为 low 或 medium 时，生成一个开放式追问引导学员深化思考
  - 追问应聚焦核心知识点，避免是非题，用"为什么"/"如何"/"举例说明"等形式
  - certainty_level 为 high 且无 gap_types 时，设为 null
\"\"\"",
)

p1.write_text(s1)
print("✓ llm_gateway.py 补丁完成")


# ════════════════════════════════════════════════════════════════
# 2. teaching_service.py — 响应透传 proactive_question
# ════════════════════════════════════════════════════════════════
p2 = Path("apps/api/modules/teaching/teaching_service.py")
s2 = p2.read_text()

s2 = patch(s2,
    '            "diagnosis_update": {\n                "suspected_gap_types": [g.value for g in teach_resp.gap_types],\n                "updated_entities":    [r.entity_id for r in retrieved[:3]],\n                "confidence":          confidence,\n                "error_pattern":       teach_resp.error_pattern,\n            },\n        }',
    '            "proactive_question": teach_resp.proactive_question,\n            "diagnosis_update": {\n                "suspected_gap_types": [g.value for g in teach_resp.gap_types],\n                "updated_entities":    [r.entity_id for r in retrieved[:3]],\n                "confidence":          confidence,\n                "error_pattern":       teach_resp.error_pattern,\n            },\n        }',
)

# 同时在掌握度更新里加 proactive_question 触发条件
# 当 certainty_level != high 时自动更新 learner_knowledge_states
# （已有诊断写入流程，只需透传字段，不需额外代码）

p2.write_text(s2)
print("✓ teaching_service.py 补丁完成")


if errors:
    print("\n未找到的锚点：")
    for e in errors:
        print(e)
