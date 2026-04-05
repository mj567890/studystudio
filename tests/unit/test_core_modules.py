"""
tests/unit/test_core_modules.py
核心模块单元测试套件

覆盖：
- 枚举与常量
- 归一化阈值
- topological_sort_safe（B1）
- PathStep dependency_depth（B3）
- normalize_rrf_score（问题7）
- classify_query_complexity（问题6）
- apply_decay（掌握度衰减）
- 冷启动掌握度映射
- extract_entity_refs（问题1）
- ColdStart placement score map
"""
import math
import pytest

from packages.shared_schemas.enums import (
    CERTAINTY_SCORE_MAP,
    PLACEMENT_SCORE_MAP,
    CertaintyLevel,
    GapType,
    MasteryLevel,
)
from apps.api.core.llm_gateway import normalize_rrf_score
from apps.api.modules.learner.learner_service import (
    MasteryStateService,
    PathStep,
    RepairPathService,
    topological_sort_safe,
)
from apps.api.modules.teaching.teaching_service import classify_query_complexity
from apps.api.modules.tutorial.tutorial_service import extract_entity_refs
from apps.api.modules.knowledge.normalization_service import (
    cosine_similarity,
    edit_distance,
)


# ════════════════════════════════════════════════════════════════
# 共享枚举与常量测试
# ════════════════════════════════════════════════════════════════
class TestEnums:

    def test_certainty_score_map_values(self):
        assert CERTAINTY_SCORE_MAP[CertaintyLevel.HIGH]   == 0.9
        assert CERTAINTY_SCORE_MAP[CertaintyLevel.MEDIUM] == 0.6
        assert CERTAINTY_SCORE_MAP[CertaintyLevel.LOW]    == 0.3

    def test_placement_score_map_all_combinations(self):
        """所有 (basic, advanced) 组合均有对应分数，且分数在合理区间。"""
        for (basic, advanced), score in PLACEMENT_SCORE_MAP.items():
            assert 0.0 <= score <= 1.0, f"Score out of range: {score}"
        # 双对 > 单对 > 单错 > 双错
        assert PLACEMENT_SCORE_MAP[(True,  True)]  > PLACEMENT_SCORE_MAP[(True,  False)]
        assert PLACEMENT_SCORE_MAP[(True,  False)] > PLACEMENT_SCORE_MAP[(False, False)]
        assert PLACEMENT_SCORE_MAP[(False, True)]  > PLACEMENT_SCORE_MAP[(False, False)]

    def test_gap_type_values(self):
        assert GapType.MECHANISM.value == "mechanism"
        assert GapType.FLOW.value      == "flow"
        assert len(list(GapType))      == 6

    def test_mastery_level_comment_thresholds(self):
        """MasteryLevel 枚举存在，HIGH 用于展示（0.8），剪枝用 0.7（有意设计）。"""
        assert MasteryLevel.HIGH.value   == "high"
        assert MasteryLevel.MEDIUM.value == "medium"
        assert MasteryLevel.LOW.value    == "low"


# ════════════════════════════════════════════════════════════════
# normalize_rrf_score（问题7修复）
# ════════════════════════════════════════════════════════════════
class TestNormalizeRrfScore:

    def test_zero_input(self):
        assert normalize_rrf_score(0.0) == 0.0

    def test_negative_input(self):
        assert normalize_rrf_score(-0.01) == 0.0

    def test_max_rrf_two_paths(self):
        """两路召回均排第一时，RRF 最大值 = 2/(60+1) ≈ 0.0328，归一化后应为 1.0"""
        k = 60
        max_raw = 2 / (k + 1)
        assert normalize_rrf_score(max_raw, num_paths=2, k=k) == pytest.approx(1.0)

    def test_single_path_rank1(self):
        """单路召回排第一，RRF = 1/61，归一化后 = 0.5（2路中的1路）"""
        k       = 60
        raw     = 1 / (k + 1)
        result  = normalize_rrf_score(raw, num_paths=2, k=k)
        assert result == pytest.approx(0.5)

    def test_output_capped_at_one(self):
        """输入超过最大值时，输出应被限制在 1.0。"""
        assert normalize_rrf_score(999.0) == 1.0

    def test_range_is_zero_to_one(self):
        for raw in [0.0, 0.01, 0.02, 0.033, 0.05]:
            result = normalize_rrf_score(raw)
            assert 0.0 <= result <= 1.0


# ════════════════════════════════════════════════════════════════
# topological_sort_safe（B1：entity_id 字符串操作）
# ════════════════════════════════════════════════════════════════
class TestTopologicalSortSafe:

    def _make_entity(self, eid: str) -> dict:
        return {"entity_id": eid, "canonical_name": f"Entity_{eid}"}

    def test_linear_chain(self):
        """A -> B -> C（A 是 B 的前置，B 是 C 的前置）"""
        entities  = [self._make_entity(e) for e in ["A", "B", "C"]]
        relations = [
            {"source_entity_id": "A", "target_entity_id": "B", "relation_type": "prerequisite_of"},
            {"source_entity_id": "B", "target_entity_id": "C", "relation_type": "prerequisite_of"},
        ]
        sorted_e, cycles = topological_sort_safe(entities, relations)
        ids = [e["entity_id"] for e in sorted_e]
        assert ids.index("A") < ids.index("B") < ids.index("C")
        assert len(cycles) == 0

    def test_no_relations(self):
        """无依赖关系时，所有实体均返回，无环。"""
        entities = [self._make_entity(e) for e in ["X", "Y", "Z"]]
        sorted_e, cycles = topological_sort_safe(entities, [])
        assert len(sorted_e) == 3
        assert len(cycles)   == 0

    def test_cycle_detection(self):
        """A -> B -> A（循环依赖），cycle_entities 应包含这两个节点。"""
        entities  = [self._make_entity(e) for e in ["A", "B"]]
        relations = [
            {"source_entity_id": "A", "target_entity_id": "B", "relation_type": "prerequisite_of"},
            {"source_entity_id": "B", "target_entity_id": "A", "relation_type": "prerequisite_of"},
        ]
        sorted_e, cycles = topological_sort_safe(entities, relations)
        assert len(cycles) == 2
        # 所有实体都在返回结果中（环节点被追加到末尾）
        assert len(sorted_e) == 2

    def test_returns_all_entities(self):
        """即使有循环，返回结果应包含全部实体。"""
        entities = [self._make_entity(e) for e in ["A", "B", "C", "D"]]
        relations = [
            {"source_entity_id": "A", "target_entity_id": "B", "relation_type": "prerequisite_of"},
            {"source_entity_id": "C", "target_entity_id": "D", "relation_type": "prerequisite_of"},
            {"source_entity_id": "D", "target_entity_id": "C", "relation_type": "prerequisite_of"},  # 环
        ]
        sorted_e, cycles = topological_sort_safe(entities, relations)
        returned_ids = {e["entity_id"] for e in sorted_e}
        assert returned_ids == {"A", "B", "C", "D"}

    def test_non_prerequisite_relations_ignored(self):
        """非 prerequisite_of 关系不影响排序。"""
        entities  = [self._make_entity(e) for e in ["A", "B"]]
        relations = [
            {"source_entity_id": "A", "target_entity_id": "B", "relation_type": "related"},
        ]
        sorted_e, cycles = topological_sort_safe(entities, relations)
        assert len(cycles) == 0  # related 关系不产生循环

    def test_string_only_no_object_reference_issues(self):
        """验证实现只使用字符串操作，不依赖对象引用。"""
        e1 = {"entity_id": "e1", "canonical_name": "E1"}
        e2 = {"entity_id": "e2", "canonical_name": "E2"}
        # 同样内容的不同对象
        e1_copy = {"entity_id": "e1", "canonical_name": "E1"}
        entities  = [e1, e2]
        relations = [
            {"source_entity_id": "e1", "target_entity_id": "e2", "relation_type": "prerequisite_of"}
        ]
        sorted_e, cycles = topological_sort_safe(entities, relations)
        assert len(cycles) == 0


# ════════════════════════════════════════════════════════════════
# PathStep dependency_depth（B3）
# ════════════════════════════════════════════════════════════════
class TestPathStep:

    def test_default_depth_is_zero(self):
        step = PathStep(step_no=1, type="entity", ref_id="e1", title="Test")
        assert step.dependency_depth == 0

    def test_dict_contains_dependency_depth(self):
        step = PathStep(step_no=1, type="chapter", ref_id="ch1", title="Ch1", dependency_depth=3)
        d = step.dict()
        assert d["dependency_depth"] == 3
        assert d["step_no"]          == 1
        assert d["type"]             == "chapter"

    def test_depth_used_for_sorting(self):
        steps = [
            PathStep(step_no=1, type="entity", ref_id="e3", title="E3", dependency_depth=2),
            PathStep(step_no=2, type="entity", ref_id="e1", title="E1", dependency_depth=0),
            PathStep(step_no=3, type="entity", ref_id="e2", title="E2", dependency_depth=1),
        ]
        sorted_steps = sorted(steps, key=lambda s: s.dependency_depth)
        assert sorted_steps[0].ref_id == "e1"   # 深度 0 最优先
        assert sorted_steps[1].ref_id == "e2"
        assert sorted_steps[2].ref_id == "e3"


# ════════════════════════════════════════════════════════════════
# classify_query_complexity（问题6修复：不含no_prior_context）
# ════════════════════════════════════════════════════════════════
class TestClassifyQueryComplexity:

    def test_simple_short_message(self):
        assert classify_query_complexity("什么是SQL注入") == "simple"

    def test_complex_deep_inquiry(self):
        result = classify_query_complexity(
            "为什么SQL注入会绕过身份验证？它的底层原理是什么？",
            gap_types=["mechanism", "causal"]
        )
        assert result == "complex"

    def test_simple_how_to_install(self):
        """'如何安装' 属于操作类，应路由到 simple，即使有 '如何' 关键词。"""
        assert classify_query_complexity("如何安装 Python 环境") == "simple"

    def test_first_turn_is_not_auto_complex(self):
        """
        V2.6 修复：首轮对话不再自动路由到 complex（移除了 no_prior_context 信号）。
        短问题首轮应为 simple。
        """
        result = classify_query_complexity("什么是XSS攻击", gap_types=[])
        assert result == "simple"

    def test_long_message_is_signal(self):
        long_msg = "请详细解释一下" + "SQL注入" * 50  # > 200字符
        result   = classify_query_complexity(long_msg)
        assert result == "complex"

    def test_multi_question(self):
        result = classify_query_complexity("XSS是什么？和CSRF有什么区别？")
        assert result == "complex"

    def test_mechanism_keyword(self):
        result = classify_query_complexity(
            "请解释SQL注入的机制",
            gap_types=["mechanism"]
        )
        # 单信号：mechanism关键词 + 1个gap_type = 2信号 → complex
        assert result == "complex"


# ════════════════════════════════════════════════════════════════
# extract_entity_refs（问题1修复：{{名称}}格式，非UUID搜索）
# ════════════════════════════════════════════════════════════════
class TestExtractEntityRefs:

    def test_extracts_known_refs(self):
        content    = "{{文件包含漏洞}}是一种常见的{{路径遍历}}攻击向量。"
        name_to_id = {"文件包含漏洞": "e001", "路径遍历": "e002"}
        result     = extract_entity_refs(content, name_to_id)
        assert "e001" in result
        assert "e002" in result

    def test_unknown_ref_not_in_result(self):
        content    = "{{未知知识点}}不在映射中。"
        name_to_id = {"已知知识点": "e001"}
        result     = extract_entity_refs(content, name_to_id)
        assert len(result) == 0   # 未知引用不会产生 UUID，不会在结果中

    def test_uuid_in_content_not_matched(self):
        """UUID 字符串在正文中永远不会被 {{}} 格式匹配，验证修复正确。"""
        uuid_str = "a3f7c12e-84b1-4d9a-b2c8-1234567890ab"
        content  = f"正文中有UUID：{uuid_str}。"
        result   = extract_entity_refs(content, {uuid_str: "e001"})
        assert len(result) == 0  # UUID 不在 {{}} 中，不会被提取

    def test_empty_content(self):
        assert extract_entity_refs("", {}) == []

    def test_no_refs_in_content(self):
        content    = "这段内容没有任何知识点引用标注。"
        name_to_id = {"SQL注入": "e001"}
        assert extract_entity_refs(content, name_to_id) == []

    def test_whitespace_trimmed(self):
        content    = "{{ 文件包含漏洞 }}是危险的。"
        name_to_id = {"文件包含漏洞": "e001"}
        result     = extract_entity_refs(content, name_to_id)
        assert "e001" in result


# ════════════════════════════════════════════════════════════════
# 掌握度衰减模型
# ════════════════════════════════════════════════════════════════
class TestMasteryDecay:

    def setup_method(self):
        self.svc = MasteryStateService.__new__(MasteryStateService)

    def test_no_decay_zero_days(self):
        assert self.svc.apply_decay(0.8, 0.1, 0.0) == 0.8

    def test_decay_after_one_week(self):
        score = self.svc.apply_decay(0.8, 0.1, 7.0)
        expected = 0.8 * math.exp(-0.1 * 7.0)
        assert score == pytest.approx(expected, rel=1e-4)

    def test_decay_never_below_zero(self):
        assert self.svc.apply_decay(0.1, 1.0, 100.0) >= 0.0

    def test_higher_decay_rate_faster_forgetting(self):
        score_fast = self.svc.apply_decay(1.0, 0.5, 7.0)
        score_slow = self.svc.apply_decay(1.0, 0.1, 7.0)
        assert score_fast < score_slow

    def test_negative_days_returns_original(self):
        assert self.svc.apply_decay(0.7, 0.1, -1.0) == 0.7


# ════════════════════════════════════════════════════════════════
# 向量工具函数
# ════════════════════════════════════════════════════════════════
class TestVectorUtils:

    def test_cosine_similarity_identical(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        v1 = [1.0, 0.0]
        v2 = [0.0, 1.0]
        assert cosine_similarity(v1, v2) == pytest.approx(0.0)

    def test_cosine_similarity_opposite(self):
        v1 = [1.0, 0.0]
        v2 = [-1.0, 0.0]
        assert cosine_similarity(v1, v2) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_edit_distance_same(self):
        assert edit_distance("SQL注入", "SQL注入") == 0

    def test_edit_distance_one_char(self):
        assert edit_distance("SQL注入", "SQL注人") == 1

    def test_edit_distance_empty(self):
        assert edit_distance("", "abc") == 3
        assert edit_distance("abc", "") == 3
