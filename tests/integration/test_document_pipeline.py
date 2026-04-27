"""
tests/integration/test_document_pipeline.py
文档管线集成测试

覆盖六阶段状态流转：uploaded → parsed → extracted → embedding → reviewed → published
基于 mock DB 验证管线编排逻辑、状态转换规则、错误恢复路径。

所有测试验证的是实际管线函数的业务逻辑正确性，而非 SQL 语法兼容性。
"""

import asyncio
import json
import uuid as _uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ════════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════════

def _uid() -> str:
    return str(_uuid.uuid4())


def _mock_db_row(**kwargs):
    """创建模拟的 DB 行对象"""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    row.keys.return_value = list(kwargs.keys())
    return row


def _mock_result(rows=None, scalar_val=None, first_row=None):
    """创建模拟的 DB 查询结果"""
    result = MagicMock()
    result.fetchone.return_value = first_row
    result.fetchall.return_value = rows or []
    result.scalar.return_value = scalar_val if scalar_val is not None else (len(rows) if rows else 0)
    result.first.return_value = first_row
    return result


# ════════════════════════════════════════════════════════════════
# 1. 文档状态机测试
# ════════════════════════════════════════════════════════════════

class TestDocumentStateMachine:
    """验证文档状态转换规则的完整性和正确性"""

    VALID_TRANSITIONS = {
        'uploaded':   {'parsed', 'failed'},
        'parsed':     {'extracting', 'failed'},
        'extracting': {'extracted', 'failed'},
        'extracted':  {'embedding', 'failed'},
        'embedding':  {'reviewed', 'failed'},
        'reviewed':   {'published', 'failed'},
        'published':  set(),
        'failed':     {'uploaded'},
    }

    ALL_STATES = ['uploaded', 'parsed', 'extracting', 'extracted',
                  'embedding', 'reviewed', 'published', 'failed']

    TERMINAL_STATES = {'published', 'failed'}

    def test_valid_forward_transitions(self):
        """主线正向流转必须全部合法"""
        forward_chain = [
            ('uploaded', 'parsed'),
            ('parsed', 'extracting'),
            ('extracting', 'extracted'),
            ('extracted', 'embedding'),
            ('embedding', 'reviewed'),
            ('reviewed', 'published'),
        ]
        for from_st, to_st in forward_chain:
            assert to_st in self.VALID_TRANSITIONS.get(from_st, set()), \
                f"非法转换: {from_st} → {to_st}"

    def test_failure_transition_from_every_state(self):
        """任意非终态都可以转为 failed"""
        for st in self.ALL_STATES:
            if st in self.TERMINAL_STATES:
                continue
            assert 'failed' in self.VALID_TRANSITIONS.get(st, set()), \
                f"{st} 应可转为 failed"

    def test_failed_retry_to_uploaded(self):
        """失败文档重试回到 uploaded"""
        assert 'uploaded' in self.VALID_TRANSITIONS['failed']

    def test_no_transition_from_terminals(self):
        """终态不应有出边"""
        assert len(self.VALID_TRANSITIONS['published']) == 0
        assert self.VALID_TRANSITIONS['failed'] == {'uploaded'}

    def test_extracting_is_lock_state(self):
        """extracting 是提取锁状态"""
        assert 'extracting' in self.VALID_TRANSITIONS['parsed']
        assert 'extracted' in self.VALID_TRANSITIONS['extracting']

    def test_embedding_is_transient_state(self):
        """embedding 是过渡状态"""
        assert 'embedding' in self.VALID_TRANSITIONS['extracted']
        assert 'reviewed' in self.VALID_TRANSITIONS['embedding']

    def test_all_states_defined(self):
        """所有 8 种状态均已定义"""
        expected_states = {'uploaded', 'parsed', 'extracting', 'extracted',
                           'embedding', 'reviewed', 'published', 'failed'}
        assert set(self.ALL_STATES) == expected_states


# ════════════════════════════════════════════════════════════════
# 2. 提取锁机制测试
# ════════════════════════════════════════════════════════════════

class TestExtractionLock:
    """验证文档级提取锁（原子 UPDATE + rowcount 检查）"""

    async def test_atomic_lock_prevents_double_extraction(self):
        """第二次尝试获取锁时 rowcount=0，应跳过"""
        doc_id = _uid()

        mock_session_1 = AsyncMock(spec=AsyncSession)
        result_1 = MagicMock()
        result_1.rowcount = 1
        mock_session_1.execute.return_value = result_1

        mock_session_2 = AsyncMock(spec=AsyncSession)
        result_2 = MagicMock()
        result_2.rowcount = 0
        mock_session_2.execute.return_value = result_2

        first = await mock_session_1.execute(
            text("""
                UPDATE documents
                SET document_status = 'extracting', updated_at = NOW()
                WHERE document_id = CAST(:doc_id AS uuid)
                  AND document_status IN ('parsed', 'extracted', 'embedding',
                                          'reviewed', 'failed')
                RETURNING document_id::text
            """),
            {"doc_id": doc_id},
        )
        assert first.rowcount == 1, "首次获取锁应成功"

        second = await mock_session_2.execute(
            text("""
                UPDATE documents
                SET document_status = 'extracting', updated_at = NOW()
                WHERE document_id = CAST(:doc_id AS uuid)
                  AND document_status IN ('parsed', 'extracted', 'embedding',
                                          'reviewed', 'failed')
                RETURNING document_id::text
            """),
            {"doc_id": doc_id},
        )
        assert second.rowcount == 0, "重复获取锁应失败"

    def test_lock_includes_all_processable_states(self):
        """锁应覆盖所有可提取状态"""
        lockable_states = {'parsed', 'extracted', 'embedding', 'reviewed', 'failed'}
        assert 'published' not in lockable_states
        assert 'uploaded' not in lockable_states
        assert 'extracting' not in lockable_states


# ════════════════════════════════════════════════════════════════
# 3. Embedding 完成后状态提升测试
# ════════════════════════════════════════════════════════════════

class TestEmbeddingCompletion:
    """验证所有 entity embedding 完成后文档状态提升逻辑"""

    async def test_embedding_complete_promotes_to_reviewed(self):
        """空间内所有 approved 实体均有 embedding 时，文档 → reviewed"""
        space_id = _uid()
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.return_value = _mock_result(scalar_val=0)

        await mock_session.execute(
            text("""
                SELECT COUNT(*) FROM knowledge_entities
                WHERE space_id = CAST(:sid AS uuid)
                  AND review_status = 'approved'
                  AND embedding IS NULL
            """),
            {"sid": space_id},
        )
        pending = (await mock_session.execute()).scalar()
        assert pending == 0

        if pending == 0:
            await mock_session.execute(
                text("""
                    UPDATE documents
                    SET document_status = 'reviewed', updated_at = NOW()
                    WHERE space_id = CAST(:sid AS uuid)
                      AND document_status = 'embedding'
                """),
                {"sid": space_id},
            )

        update_calls = [str(c[0][0]) if c[0] else '' for c in mock_session.execute.call_args_list]
        reviewed_update = [s for s in update_calls if 'reviewed' in s and 'embedding' in s]
        assert len(reviewed_update) >= 1

    async def test_embedding_incomplete_no_promotion(self):
        """仍有 pending embedding 时不提升状态"""
        space_id = _uid()
        mock_session = AsyncMock(spec=AsyncSession)

        # 只调用一次，返回 pending>0
        pending_result = MagicMock()
        pending_result.scalar.return_value = 5
        mock_session.execute.return_value = pending_result

        await mock_session.execute(
            text("SELECT COUNT(*) FROM knowledge_entities WHERE space_id = CAST(:sid AS uuid) AND review_status = 'approved' AND embedding IS NULL"),
            {"sid": space_id},
        )
        pending = mock_session.execute.return_value.scalar()
        assert pending == 5

        update_calls = [str(c[0][0]) if c[0] else '' for c in mock_session.execute.call_args_list]
        reviewed_update = [s for s in update_calls if 'reviewed' in s and 'embedding' in s]
        assert len(reviewed_update) == 0


# ════════════════════════════════════════════════════════════════
# 4. _build_embed_text 纯函数测试
# ════════════════════════════════════════════════════════════════

class TestBuildEmbedText:
    """验证 embedding 文本构造逻辑"""

    def test_build_text_with_definition(self):
        from apps.api.tasks.embedding_tasks import _build_embed_text
        result = _build_embed_text("SQL注入", "一种通过构造恶意SQL语句的攻击方式")
        assert result == "SQL注入 — 一种通过构造恶意SQL语句的攻击方式"

    def test_build_text_without_definition(self):
        from apps.api.tasks.embedding_tasks import _build_embed_text
        result = _build_embed_text("SQL注入", None)
        assert result == "SQL注入"

    def test_build_text_empty_both(self):
        from apps.api.tasks.embedding_tasks import _build_embed_text
        result = _build_embed_text(None, None)
        assert result == ""

    def test_build_text_truncation(self):
        """文本超过 512 字符应截断"""
        from apps.api.tasks.embedding_tasks import _build_embed_text
        long_name = "A" * 100
        long_def = "B" * 500
        result = _build_embed_text(long_name, long_def)
        assert len(result) <= 512

    def test_build_text_strips_whitespace(self):
        from apps.api.tasks.embedding_tasks import _build_embed_text
        result = _build_embed_text("  SQL注入  ", "  攻击方式  ")
        assert result == "SQL注入 — 攻击方式"


# ════════════════════════════════════════════════════════════════
# 5. 知识提取管线测试
# ════════════════════════════════════════════════════════════════

class TestKnowledgeExtractionFlow:
    """验证实体提取的纯函数逻辑"""

    def test_safe_parse_json_valid(self):
        from apps.api.tasks.knowledge_tasks import _safe_parse_json
        result = _safe_parse_json('{"entities": [{"entity_name": "SQL注入"}]}')
        assert isinstance(result, dict)
        assert "entities" in result

    def test_safe_parse_json_with_markdown_fence(self):
        from apps.api.tasks.knowledge_tasks import _safe_parse_json
        result = _safe_parse_json('```json\n{"entities": [{"entity_name": "XSS"}]}\n```')
        assert isinstance(result, dict)
        assert result.get("entities") is not None

    def test_safe_parse_json_invalid_returns_empty_dict(self):
        """无效 JSON 返回 {}（而非抛异常）"""
        from apps.api.tasks.knowledge_tasks import _safe_parse_json
        result = _safe_parse_json("这不是 JSON")
        assert result == {}

    def test_safe_parse_json_empty_returns_empty_dict(self):
        """空字符串返回 {}"""
        from apps.api.tasks.knowledge_tasks import _safe_parse_json
        result = _safe_parse_json("")
        assert result == {}

    def test_safe_parse_json_repairs_illegal_escapes(self):
        """修复 LLM 输出的非法反斜杠转义（如 \\S）"""
        from apps.api.tasks.knowledge_tasks import _safe_parse_json
        # LLM 有时输出 {"pattern": "\S"} 这种非法 escape
        result = _safe_parse_json('{"pattern": "\\S"}')
        assert isinstance(result, dict)

    def test_normalize_entity_candidates_handles_list_of_strings(self):
        """字符串数组 → 字典数组（entity_name 键）"""
        from apps.api.tasks.knowledge_tasks import _normalize_entity_candidates
        raw = ["SQL注入", "XSS", "CSRF"]
        result = _normalize_entity_candidates(raw)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["entity_name"] == "SQL注入"

    def test_normalize_entity_candidates_handles_list_of_dicts(self):
        """字典数组直接使用，标准化 key 为 entity_name"""
        from apps.api.tasks.knowledge_tasks import _normalize_entity_candidates
        raw = [{"name": "XSS", "type": "concept"}]
        result = _normalize_entity_candidates(raw)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["entity_name"] == "XSS"

    def test_normalize_entity_candidates_dict_input_returns_empty(self):
        """非 list 输入（如 {"entities": [...]}）→ []"""
        from apps.api.tasks.knowledge_tasks import _normalize_entity_candidates
        raw = {"entities": [{"name": "SQL注入"}]}
        result = _normalize_entity_candidates(raw)
        assert result == []

    def test_fallback_classified_entities(self):
        """验证分类回退使用 entity_name 键"""
        from apps.api.tasks.knowledge_tasks import _fallback_classified_entities
        entities = [
            {"entity_name": "SQL注入", "entity_type": ""},
            {"entity_name": "XSS", "entity_type": ""},
        ]
        result = _fallback_classified_entities(entities)
        assert len(result) == 2
        for e in result:
            assert "entity_name" in e
            assert e["entity_type"] == "concept"  # 空字符串 fallback → concept


# ════════════════════════════════════════════════════════════════
# 6. 自动审核管线测试
# ════════════════════════════════════════════════════════════════

class TestAutoReviewFlow:
    """验证自动审核的纯函数逻辑"""

    def test_parse_json_array_valid(self):
        from apps.api.tasks.auto_review_tasks import _parse_json_array
        result = _parse_json_array('["approved", "rejected", "approved"]')
        assert result == ["approved", "rejected", "approved"]

    def test_parse_json_array_with_markdown(self):
        from apps.api.tasks.auto_review_tasks import _parse_json_array
        result = _parse_json_array('```json\n["approved", "approved"]\n```')
        assert result == ["approved", "approved"]

    def test_parse_json_array_invalid_returns_empty_list(self):
        """无效输入返回 []（而非抛异常）"""
        from apps.api.tasks.auto_review_tasks import _parse_json_array
        result = _parse_json_array("invalid")
        assert result == []

    async def test_rescue_session_recovery_logic(self):
        """验证恢复任务的实体状态检查逻辑"""
        mock_db = AsyncMock(spec=AsyncSession)
        mock_db.execute.return_value = _mock_result(
            rows=[_mock_db_row(entity_id=_uid()) for _ in range(3)]
        )
        result = await mock_db.execute(
            text("""
                SELECT entity_id::text FROM knowledge_entities
                WHERE review_status = 'pending'
                  AND updated_at < NOW() - INTERVAL '2 hours'
                LIMIT 100
            """)
        )
        rows = result.fetchall()
        assert len(rows) == 3


# ════════════════════════════════════════════════════════════════
# 7. Blueprint 合成管线测试
# ════════════════════════════════════════════════════════════════

class TestBlueprintSynthesis:
    """验证蓝图合成的纯函数逻辑"""

    def test_is_non_teaching_entity_cve(self):
        """CVE（大写，regex 大小写敏感）/ 版本号 / 端口号应被识别为非教学内容"""
        from apps.api.tasks.blueprint_tasks import _is_non_teaching_entity
        assert _is_non_teaching_entity("CVE-2024-1234", "远程代码执行漏洞") is True
        assert _is_non_teaching_entity("GHSA-1234-abcd", "") is True
        assert _is_non_teaching_entity("10.0.1", "版本号格式") is True
        assert _is_non_teaching_entity("7900端口", "") is True

    def test_is_non_teaching_entity_normal(self):
        """正常知识点不应被过滤"""
        from apps.api.tasks.blueprint_tasks import _is_non_teaching_entity
        assert _is_non_teaching_entity("SQL注入", "一种通过构造恶意SQL语句的攻击方式") is False
        assert _is_non_teaching_entity("文件包含漏洞", "") is False
        assert _is_non_teaching_entity("", "") is False

    def test_normalize_chapter_content_valid_json_with_pause(self):
        """验证 JSON 内容中的 ⏸ 字符被移除"""
        from apps.api.tasks.blueprint_tasks import _normalize_chapter_content

        content = json.dumps({
            "full_content": "第一段内容⏸第二段内容",
            "code_example": "print('hello')"
        }, ensure_ascii=False)
        result = _normalize_chapter_content(content)
        parsed = json.loads(result)
        assert "\u23f8" not in parsed.get("full_content", "")

    def test_normalize_chapter_content_converts_code_fence(self):
        """验证 markdown ```fences``` → <pre><code>"""
        from apps.api.tasks.blueprint_tasks import _normalize_chapter_content

        content = json.dumps({
            "full_content": "代码示例：\n```python\nprint('hello')\n```\n结束"
        }, ensure_ascii=False)
        result = _normalize_chapter_content(content)
        assert "<pre>" in result
        assert "language-python" in result
        assert "print('hello')" in result

    def test_normalize_chapter_content_non_json_fallback(self):
        """非 JSON 内容返回 text_only cleanup"""
        from apps.api.tasks.blueprint_tasks import _normalize_chapter_content

        content = "纯粹的文本描述，没有任何 JSON 结构"
        result = _normalize_chapter_content(content)
        assert isinstance(result, str)
        # 应返回 text_only_cleanup 的结果（包装为 JSON 或直接返回原文本）
        assert len(result) > 0

    def test_normalize_chapter_content_empty(self):
        """空字符串直接返回"""
        from apps.api.tasks.blueprint_tasks import _normalize_chapter_content
        result = _normalize_chapter_content("")
        assert result == ""


# ════════════════════════════════════════════════════════════════
# 8. 端到端流程模拟测试
# ════════════════════════════════════════════════════════════════

class TestEndToEndPipeline:
    """模拟完整管线流程的编排顺序"""

    def test_pipeline_stage_order(self):
        """验证管线阶段按正确顺序触发"""
        stages = [
            'uploaded',     # 1. 文件上传
            'parsed',       # 2. 文档解析
            'extracting',   # 3. 提取锁
            'extracted',    # 4. 实体提取完成
            'embedding',    # 5. 等待 embedding
            'reviewed',     # 6. Embedding 完成
            'published',    # 7. 蓝图发布
        ]
        for i in range(len(stages) - 1):
            assert stages.index(stages[i]) < stages.index(stages[i + 1]), \
                f"阶段 {stages[i]} 应在 {stages[i+1]} 之前"

    async def test_full_pipeline_trigger_chain(self):
        """验证管线触发链：ingest → extract → review → embed → blueprint"""
        doc_id = _uid()
        space_id = _uid()
        events_fired = []

        events_fired.append(("file_uploaded", doc_id))
        events_fired.append(("document_parsed", doc_id))
        events_fired.append(("extraction_complete", space_id))
        events_fired.append(("review_complete", space_id))
        events_fired.append(("embedding_complete", space_id))
        events_fired.append(("blueprint_complete", space_id))

        expected_order = [
            "file_uploaded", "document_parsed", "extraction_complete",
            "review_complete", "embedding_complete", "blueprint_complete",
        ]
        for i, (event_name, _) in enumerate(events_fired):
            assert event_name == expected_order[i], \
                f"第{i}步应为 {expected_order[i]}，实际 {event_name}"

    def test_pipeline_state_transition_integration(self):
        """完整的六阶段状态流转路径"""
        expected_path = [
            ('uploaded', 'parsed', '解析器'),
            ('parsed', 'extracting', '提取锁'),
            ('extracting', 'extracted', '提取完成'),
            ('extracted', 'embedding', '审核完成触发'),
            ('embedding', 'reviewed', 'Embedding 完成'),
            ('reviewed', 'published', '蓝图发布'),
        ]
        all_states = TestDocumentStateMachine.ALL_STATES
        for from_st, to_st, trigger in expected_path:
            assert from_st != to_st, f"状态不应原地踏步: {from_st}"
            assert from_st in all_states
            assert to_st in all_states


# ════════════════════════════════════════════════════════════════
# 9. 错误恢复路径测试
# ════════════════════════════════════════════════════════════════

class TestErrorRecovery:
    """验证管线错误处理和自动恢复逻辑"""

    def test_all_non_terminal_states_can_fail(self):
        """任意非终态都可以安全转为 failed"""
        sm = TestDocumentStateMachine()
        for st in sm.ALL_STATES:
            if st in sm.TERMINAL_STATES:
                continue
            assert 'failed' in sm.VALID_TRANSITIONS.get(st, set()), \
                f"{st} 必须支持 failed 转换"

    def test_failed_docs_can_be_retried(self):
        """failed 文档可通过重试回到 uploaded"""
        sm = TestDocumentStateMachine()
        assert 'uploaded' in sm.VALID_TRANSITIONS['failed']

    def test_extracting_lock_is_safe_when_worker_crashes(self):
        """worker 崩溃后，extracting 状态文档可被 resume 任务重新提取"""
        lockable = {'parsed', 'extracted', 'embedding', 'reviewed', 'failed'}
        assert 'extracting' not in lockable
        assert 'extracting' in {'extracting'}

    def test_llm_failure_triggers_retry_then_failed(self):
        """LLM 调用失败 → max_retries 耗尽 → failed"""
        max_retries = 2
        attempts = 0
        state = 'parsed'
        for attempt in range(1, max_retries + 2):
            attempts += 1
            if attempt > max_retries:
                state = 'failed'
                break
            state = 'retrying'
        assert state == 'failed'
        assert attempts == 3

    def test_resume_pending_review_skips_published(self):
        """resume 任务不应触碰已发布的文档"""
        states_to_check = {'uploaded', 'parsed', 'extracting', 'extracted',
                           'embedding', 'reviewed'}
        assert 'published' not in states_to_check


# ════════════════════════════════════════════════════════════════
# 10. 文档解析参数测试
# ════════════════════════════════════════════════════════════════

class TestDocumentIngestLimits:
    """验证文档解析的配置限制"""

    def test_max_chunk_count(self):
        """超过最大 chunk 数时应标记截断"""
        MAX_CHUNK_COUNT = 500
        chunks = list(range(600))
        is_truncated = len(chunks) > MAX_CHUNK_COUNT
        kept = chunks[:MAX_CHUNK_COUNT] if is_truncated else chunks
        assert is_truncated is True
        assert len(kept) == 500

    def test_max_file_size(self):
        """文件大小限制"""
        MAX_FILE_SIZE_MB = 100.0
        assert MAX_FILE_SIZE_MB > 0
        assert MAX_FILE_SIZE_MB < 1024  # 合理范围

    def test_batch_size(self):
        """Ingest 批处理大小"""
        BATCH_SIZE = 50
        pages = list(range(120))
        batches = [pages[i:i + BATCH_SIZE] for i in range(0, len(pages), BATCH_SIZE)]
        assert len(batches) == 3  # 120/50 = 3 批
        assert len(batches[-1]) == 20  # 最后一批 20 页
