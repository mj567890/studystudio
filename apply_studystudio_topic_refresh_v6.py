#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path


FILES = [
    "apps/api/modules/tutorial/tutorial_service.py",
    "apps/api/modules/learner/learner_service.py",
    "apps/api/modules/routers.py",
    "apps/web/src/api/index.ts",
    "apps/web/src/views/tutorial/TutorialView.vue",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def backup_file(path: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(path.name + f".bak.{timestamp}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def require_contains(haystack: str, needle: str, label: str) -> None:
    if needle not in haystack:
        raise RuntimeError(f"未找到预期代码块：{label}")


def patch_tutorial_service(content: str) -> str:
    repo_pattern = re.compile(
        r"class SkeletonRepository:[\s\S]*?# ════════════════════════════════════════════════════════════════\n# 教程生成服务（B2：Redis分布式锁）\n# ════════════════════════════════════════════════════════════════",
        re.M,
    )
    repo_replacement = """class SkeletonRepository:

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_approved_by_topic(self, topic_key: str) -> dict | None:
        result = await self.db.execute(
            text(\"\"\"
                SELECT skeleton_id::text, tutorial_id::text, topic_key, chapter_tree, status
                FROM tutorial_skeletons
                WHERE topic_key = :topic_key
                  AND status = 'approved'
                ORDER BY created_at DESC
                LIMIT 1
            \"\"\"),
            {\"topic_key\": topic_key}
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            \"skeleton_id\":  row.skeleton_id,
            \"tutorial_id\":  row.tutorial_id,
            \"topic_key\":    row.topic_key,
            \"chapter_tree\": row.chapter_tree,
            \"status\":       row.status,
        }

    async def get_any_by_topic(self, topic_key: str) -> dict | None:
        result = await self.db.execute(
            text(\"\"\"
                SELECT skeleton_id::text, tutorial_id::text, topic_key, chapter_tree, status
                FROM tutorial_skeletons
                WHERE topic_key = :topic_key
                ORDER BY created_at DESC
                LIMIT 1
            \"\"\"),
            {\"topic_key\": topic_key}
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            \"skeleton_id\":  row.skeleton_id,
            \"tutorial_id\":  row.tutorial_id,
            \"topic_key\":    row.topic_key,
            \"chapter_tree\": row.chapter_tree,
            \"status\":       row.status,
        }

    async def insert_if_not_exists(self, skeleton: dict) -> bool:
        \"\"\"
        D2（V2.6）：使用 xmax=0 技巧精确区分新插入与冲突。
        True = 本次新插入；False = topic_key 已存在（冲突）。
        \"\"\"
        result = await self.db.execute(
            text(\"\"\"
                INSERT INTO tutorial_skeletons
                  (skeleton_id, tutorial_id, topic_key, chapter_tree, status)
                VALUES
                  (:skeleton_id, :tutorial_id, :topic_key, CAST(:chapter_tree AS jsonb), 'draft')
                ON CONFLICT (topic_key)
                DO UPDATE SET
                  skeleton_id = EXCLUDED.skeleton_id,
                  tutorial_id = EXCLUDED.tutorial_id,
                  chapter_tree = EXCLUDED.chapter_tree,
                  status = 'draft'
                WHERE jsonb_array_length(tutorial_skeletons.chapter_tree) = 0
                RETURNING tutorial_id::text AS tutorial_id
            \"\"\"),
            {
                \"skeleton_id\":  skeleton[\"skeleton_id\"],
                \"tutorial_id\":  skeleton[\"tutorial_id\"],
                \"topic_key\":    skeleton[\"topic_key\"],
                \"chapter_tree\": json.dumps(skeleton[\"chapter_tree\"], ensure_ascii=False),
            }
        )
        row = result.fetchone()
        await self.db.commit()
        return bool(row)

    async def replace_topic_skeleton(self, skeleton: dict, status: str = 'draft') -> str:
        params = {
            \"skeleton_id\":  skeleton[\"skeleton_id\"],
            \"tutorial_id\":  skeleton[\"tutorial_id\"],
            \"topic_key\":    skeleton[\"topic_key\"],
            \"chapter_tree\": json.dumps(skeleton[\"chapter_tree\"], ensure_ascii=False),
            \"status\":       status,
        }

        result = await self.db.execute(
            text(\"\"\"
                UPDATE tutorial_skeletons
                SET skeleton_id = :skeleton_id,
                    chapter_tree = CAST(:chapter_tree AS jsonb),
                    status = :status
                WHERE topic_key = :topic_key
                RETURNING tutorial_id::text AS tutorial_id
            \"\"\"),
            params,
        )
        row = result.fetchone()

        tutorial_id = row.tutorial_id if row else skeleton[\"tutorial_id\"]
        if not row:
            await self.db.execute(
                text(\"\"\"
                    INSERT INTO tutorial_skeletons
                      (skeleton_id, tutorial_id, topic_key, chapter_tree, status)
                    VALUES
                      (:skeleton_id, :tutorial_id, :topic_key, CAST(:chapter_tree AS jsonb), :status)
                \"\"\"),
                params,
            )

        await self.db.commit()
        return tutorial_id

    async def clear_contents(self, tutorial_id: str) -> None:
        await self.db.execute(
            text(\"DELETE FROM tutorial_contents WHERE tutorial_id = :tid\"),
            {\"tid\": tutorial_id},
        )
        await self.db.commit()

    async def get(self, tutorial_id: str) -> dict | None:
        result = await self.db.execute(
            text(\"SELECT tutorial_id::text, topic_key, chapter_tree FROM tutorial_skeletons \"
                 \"WHERE tutorial_id = :tid\"),
            {\"tid\": tutorial_id}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None

    async def mark_approved(self, tutorial_id: str) -> None:
        await self.db.execute(
            text(\"\"\"
                UPDATE tutorial_skeletons
                SET status = 'approved'
                WHERE tutorial_id = :tid
            \"\"\"),
            {\"tid\": tutorial_id}
        )
        await self.db.commit()
        logger.info(\"Skeleton marked approved\", tutorial_id=tutorial_id)


# ════════════════════════════════════════════════════════════════
# 教程生成服务（B2：Redis分布式锁）
# ════════════════════════════════════════════════════════════════"""

    content, n = repo_pattern.subn(repo_replacement, content, count=1)
    if n != 1:
        raise RuntimeError(f"tutorial_service.py：替换 SkeletonRepository 失败，命中 {n} 次")

    service_pattern = re.compile(
        r"class TutorialGenerationService:[\s\S]*?\n    async def fill_content\(",
        re.M,
    )
    service_replacement = """class TutorialGenerationService:
    \"\"\"
    两阶段教程生成服务。
    B2（V2.6）：Redis 分布式锁 + Lua 脚本原子释放，防止并发重复生成骨架。
    \"\"\"

    def __init__(self, db: AsyncSession) -> None:
        self.db      = db
        self.repo    = SkeletonRepository(db)
        self.llm     = get_llm_gateway()
        self.quality = TutorialQualityEvaluator()

    async def generate(self, topic_key: str, user_id: str, force_refresh: bool = False) -> str:
        \"\"\"
        入口：返回 tutorial_id。
        - 正常情况复用已生成教程
        - 知识点/依赖关系变化后自动重建
        - force_refresh=True 时强制按最新知识图谱重建
        \"\"\"
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(CONFIG.redis.url)

        lock_key = f\"skeleton_lock:{topic_key}\"
        lock_val = str(uuid.uuid4())
        acquired = await redis_client.set(lock_key, lock_val, nx=True, ex=30)
        tutorial_id = str(uuid.uuid4())

        try:
            existing = await self.repo.get_approved_by_topic(topic_key)
            if existing:
                tutorial_id = existing[\"tutorial_id\"]
                if force_refresh or await self._needs_rebuild(topic_key, existing.get(\"chapter_tree\") or []):
                    await self._refresh_existing_tutorial(topic_key, tutorial_id, user_id)
                else:
                    event_bus = get_event_bus()
                    await event_bus.publish(\"skeleton_generated\", {
                        \"tutorial_id\":        tutorial_id,
                        \"topic_key\":          topic_key,
                        \"requesting_user_id\": user_id,
                    })
                return tutorial_id

            draft = await self.repo.get_any_by_topic(topic_key)
            if draft:
                tutorial_id = draft[\"tutorial_id\"]
                if force_refresh:
                    await self._refresh_existing_tutorial(topic_key, tutorial_id, user_id)
                else:
                    logger.info(
                        \"Skeleton in draft, reusing tutorial_id\",
                        tutorial_id=tutorial_id,
                        topic_key=topic_key,
                    )
                return tutorial_id

            if acquired:
                from apps.api.tasks.tutorial_tasks import generate_skeleton
                generate_skeleton.delay(tutorial_id, topic_key, user_id)
            return tutorial_id
        finally:
            if acquired:
                await redis_client.eval(
                    \"if redis.call('get',KEYS[1])==ARGV[1] then \"
                    \"return redis.call('del',KEYS[1]) else return 0 end\",
                    1, lock_key, lock_val
                )
            await redis_client.aclose()

    async def _load_topic_graph(self, topic_key: str) -> tuple[list[dict], list[dict]]:
        entities_result = await self.db.execute(
            text(\"\"\"
                SELECT entity_id::text, canonical_name, domain_tag
                FROM knowledge_entities
                WHERE review_status = 'approved'
                  AND domain_tag = :topic_key
                ORDER BY canonical_name
            \"\"\"),
            {\"topic_key\": topic_key}
        )
        entities = [dict(r._mapping) for r in entities_result.fetchall()]
        entity_ids = {e[\"entity_id\"] for e in entities}
        if not entity_ids:
            return [], []

        relations_result = await self.db.execute(
            text(\"\"\"
                SELECT source_entity_id::text, target_entity_id::text, relation_type
                FROM knowledge_relations
                WHERE relation_type = 'prerequisite_of'
            \"\"\")
        )
        relations = [
            dict(r._mapping)
            for r in relations_result.fetchall()
            if r.source_entity_id in entity_ids and r.target_entity_id in entity_ids
        ]
        return entities, relations

    @staticmethod
    def _graph_signature(entities: list[dict], relations: list[dict]) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        entity_pairs = {(e[\"entity_id\"], e[\"canonical_name\"]) for e in entities}
        edge_pairs = {
            (r[\"source_entity_id\"], r[\"target_entity_id\"])
            for r in relations
            if r.get(\"relation_type\") == \"prerequisite_of\"
        }
        return entity_pairs, edge_pairs

    @staticmethod
    def _chapter_tree_signature(chapter_tree: list[dict]) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        entity_pairs: set[tuple[str, str]] = set()
        edge_pairs: set[tuple[str, str]] = set()
        for chapter in chapter_tree or []:
            title = chapter.get(\"title\", \"\")
            target_ids = chapter.get(\"target_entity_ids\", []) or []
            prereq_ids = chapter.get(\"prerequisite_entity_ids\", []) or []
            for target_id in target_ids:
                entity_pairs.add((target_id, title))
                for source_id in prereq_ids:
                    edge_pairs.add((source_id, target_id))
        return entity_pairs, edge_pairs

    async def _needs_rebuild(self, topic_key: str, chapter_tree: list[dict]) -> bool:
        entities, relations = await self._load_topic_graph(topic_key)
        current_entities, current_edges = self._graph_signature(entities, relations)
        cached_entities, cached_edges = self._chapter_tree_signature(chapter_tree)
        return current_entities != cached_entities or current_edges != cached_edges

    def _build_chapter_tree(self, topic_key: str, entities: list[dict], relations: list[dict]) -> list[dict]:
        if not entities:
            logger.warning(\"No approved entities for topic\", topic_key=topic_key)
            return []

        sorted_entities, cycle_entities = topological_sort_safe(entities, relations)
        if cycle_entities:
            logger.warning(\"Cycle in knowledge graph\", count=len(cycle_entities), topic_key=topic_key)

        return [
            {
                \"chapter_id\":              str(uuid.uuid4()),
                \"title\":                   entity[\"canonical_name\"],
                \"order_no\":                i + 1,
                \"target_entity_ids\":       [entity[\"entity_id\"]],
                \"prerequisite_entity_ids\": self._get_prereqs(entity[\"entity_id\"], relations),
                \"estimated_minutes\":       15,
            }
            for i, entity in enumerate(sorted_entities)
        ]

    async def _refresh_existing_tutorial(
        self, topic_key: str, tutorial_id: str, requesting_user_id: str
    ) -> None:
        entities, relations = await self._load_topic_graph(topic_key)
        chapter_tree = self._build_chapter_tree(topic_key, entities, relations)

        skeleton = {
            \"skeleton_id\":  str(uuid.uuid4()),
            \"tutorial_id\":  tutorial_id,
            \"topic_key\":    topic_key,
            \"chapter_tree\": chapter_tree,
        }

        status = 'draft' if chapter_tree else 'approved'
        tutorial_id = await self.repo.replace_topic_skeleton(skeleton, status=status)
        await self.repo.clear_contents(tutorial_id)

        event_bus = get_event_bus()
        if chapter_tree:
            from apps.api.tasks.tutorial_tasks import generate_content
            generate_content.delay(tutorial_id)

        await event_bus.publish(\"skeleton_generated\", {
            \"tutorial_id\":        tutorial_id,
            \"topic_key\":          topic_key,
            \"requesting_user_id\": requesting_user_id,
        })

    async def build_skeleton(
        self, tutorial_id: str, topic_key: str, requesting_user_id: str
    ) -> None:
        \"\"\"
        骨架生成核心逻辑（由 Celery 同步任务包装调用）。
        骨架是主题级通用资产，不传入 user_id，与任何用户无关。
        \"\"\"
        entities, relations = await self._load_topic_graph(topic_key)
        chapter_tree = self._build_chapter_tree(topic_key, entities, relations)

        if not chapter_tree:
            logger.warning(
                \"No approved entities for topic, publish empty tutorial\",
                topic_key=topic_key,
            )
            skeleton = {
                \"skeleton_id\":  str(uuid.uuid4()),
                \"tutorial_id\":  tutorial_id,
                \"topic_key\":    topic_key,
                \"chapter_tree\": [],
            }
            await self.repo.replace_topic_skeleton(skeleton, status='approved')
            event_bus = get_event_bus()
            await event_bus.publish(\"skeleton_generated\", {
                \"tutorial_id\":        tutorial_id,
                \"topic_key\":          topic_key,
                \"requesting_user_id\": requesting_user_id,
            })
            return

        skeleton = {
            \"skeleton_id\":  str(uuid.uuid4()),
            \"tutorial_id\":  tutorial_id,
            \"topic_key\":    topic_key,
            \"chapter_tree\": chapter_tree,
        }

        saved = await self.repo.insert_if_not_exists(skeleton)

        event_bus = get_event_bus()
        if saved:
            from apps.api.tasks.tutorial_tasks import generate_content
            generate_content.delay(tutorial_id)

            await event_bus.publish(\"skeleton_generated\", {
                \"tutorial_id\":        tutorial_id,
                \"topic_key\":          topic_key,
                \"requesting_user_id\": requesting_user_id,
            })
        else:
            existing = await self.repo.get_any_by_topic(topic_key)
            if existing:
                await event_bus.publish(\"skeleton_generated\", {
                    \"tutorial_id\":        existing[\"tutorial_id\"],
                    \"topic_key\":          topic_key,
                    \"requesting_user_id\": requesting_user_id,
                })

    async def fill_content("""
    content, n = service_pattern.subn(service_replacement, content, count=1)
    if n != 1:
        raise RuntimeError(f"tutorial_service.py：替换 TutorialGenerationService 失败，命中 {n} 次")

    return content


def patch_learner_service(content: str) -> str:
    old_entities = """        # 2. 获取所有需要学习的实体
        entities_result = await self.db.execute(
            text(\"\"\"
                SELECT entity_id, canonical_name, domain_tag
                FROM knowledge_entities
                WHERE review_status = 'approved'
                ORDER BY domain_tag
            \"\"\")
        )
        all_entities = [
            {\"entity_id\": str(r.entity_id), \"canonical_name\": r.canonical_name,
             \"domain_tag\": r.domain_tag}
            for r in entities_result.fetchall()
        ]
"""
    new_entities = """        # 2. 仅获取当前主题的已审核实体，避免学习路径与教程串题
        entities_result = await self.db.execute(
            text(\"\"\"
                SELECT entity_id::text AS entity_id, canonical_name, domain_tag
                FROM knowledge_entities
                WHERE review_status = 'approved'
                  AND domain_tag = :topic_key
                ORDER BY canonical_name
            \"\"\"),
            {\"topic_key\": topic_key}
        )
        all_entities = [dict(r._mapping) for r in entities_result.fetchall()]
        allowed_entity_ids = {e[\"entity_id\"] for e in all_entities}

        if not all_entities:
            event_bus = get_event_bus()
            await event_bus.publish(\"repair_path_generated\", {
                \"user_id\":      user_id,
                \"topic_key\":    topic_key,
                \"step_count\":   0,
                \"is_truncated\": False,
            })
            return {
                \"user_id\":             user_id,
                \"topic_key\":           topic_key,
                \"required_entity_ids\": [],
                \"path_steps\":          [],
                \"is_truncated\":        False,
                \"total_steps\":         0,
            }
"""
    require_contains(content, old_entities, "RepairPathService 实体查询块")
    content = content.replace(old_entities, new_entities, 1)

    old_relations = """        # 3. 获取依赖关系
        relations_result = await self.db.execute(
            text(\"\"\"
                SELECT source_entity_id::text, target_entity_id::text, relation_type
                FROM knowledge_relations
                WHERE relation_type = 'prerequisite_of'
            \"\"\")
        )
        all_relations = [
            {\"source_entity_id\": str(r.source_entity_id),
             \"target_entity_id\": str(r.target_entity_id),
             \"relation_type\":    r.relation_type}
            for r in relations_result.fetchall()
        ]
"""
    new_relations = """        # 3. 获取依赖关系，并限制在当前主题子图内
        relations_result = await self.db.execute(
            text(\"\"\"
                SELECT source_entity_id::text, target_entity_id::text, relation_type
                FROM knowledge_relations
                WHERE relation_type = 'prerequisite_of'
            \"\"\")
        )
        all_relations = [
            {\"source_entity_id\": str(r.source_entity_id),
             \"target_entity_id\": str(r.target_entity_id),
             \"relation_type\":    r.relation_type}
            for r in relations_result.fetchall()
            if str(r.source_entity_id) in allowed_entity_ids
            and str(r.target_entity_id) in allowed_entity_ids
        ]
"""
    require_contains(content, old_relations, "RepairPathService 依赖关系块")
    content = content.replace(old_relations, new_relations, 1)

    return content


def patch_routers(content: str) -> str:
    require_contains(
        content,
        "from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException",
        "routers.py FastAPI import",
    )
    content = content.replace(
        "from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException",
        "from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query",
        1,
    )

    old_sig = """async def get_tutorial(
    topic_key:    str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:"""
    new_sig = """async def get_tutorial(
    topic_key:      str,
    force_refresh:  bool = Query(False),
    current_user:   dict = Depends(get_current_user),
    db: AsyncSession     = Depends(get_db),
) -> dict:"""
    require_contains(content, old_sig, "get_tutorial 签名")
    content = content.replace(old_sig, new_sig, 1)

    old_call = 'tutorial_id = await svc.generate(topic_key, current_user["user_id"])'
    new_call = 'tutorial_id = await svc.generate(topic_key, current_user["user_id"], force_refresh=force_refresh)'
    require_contains(content, old_call, "get_tutorial generate 调用")
    content = content.replace(old_call, new_call, 1)

    return content


def patch_index_ts(content: str) -> str:
    old_block = """export const tutorialApi = {
  getByTopic: (topicKey: string) =>
    http.get(`/tutorials/topic/${topicKey}`),
}
"""
    new_block = """export const tutorialApi = {
  getByTopic: (topicKey: string, forceRefresh = false) =>
    http.get(`/tutorials/topic/${topicKey}`, {
      params: { force_refresh: forceRefresh },
    }),
}
"""
    require_contains(content, old_block, "index.ts tutorialApi")
    return content.replace(old_block, new_block, 1)


def patch_tutorial_view(content: str) -> str:
    old_header = """        <el-card class=\"chapter-list\">
          <template #header>
            <el-select v-model=\"topicKey\" placeholder=\"选择主题\" size=\"small\"
              filterable style=\"width:100%\" :loading=\"domainsLoading\"
              @change=\"loadTutorial\">
              <el-option v-for=\"d in domains\" :key=\"d.domain_tag\"
                :label=\"d.domain_tag\" :value=\"d.domain_tag\" />
            </el-select>
          </template>
"""
    new_header = """        <el-card class=\"chapter-list\">
          <template #header>
            <div class=\"header-bar\">
              <el-select v-model=\"topicKey\" placeholder=\"选择主题\" size=\"small\"
                filterable style=\"width:100%\" :loading=\"domainsLoading\"
                @change=\"() => loadTutorial()\">
                <el-option v-for=\"d in domains\" :key=\"d.domain_tag\"
                  :label=\"d.domain_tag\" :value=\"d.domain_tag\" />
              </el-select>
              <el-button size=\"small\" :disabled=\"!topicKey\" :loading=\"loading\"
                @click=\"refreshTutorial\">
                重新生成教程
              </el-button>
            </div>
          </template>
"""
    require_contains(content, old_header, "TutorialView header")
    content = content.replace(old_header, new_header, 1)

    old_alert = """            <el-alert v-if=\"tutorial?.status === 'skeleton_ready'\" type=\"warning\"
              title=\"内容正在生成中，请稍后刷新\" show-icon :closable=\"false\"
              style=\"margin-bottom:16px\" />
"""
    new_alert = """            <el-alert v-if=\"tutorial?.status !== 'approved' || !currentChapter?.content_text\" type=\"warning\"
              title=\"内容正在按最新知识点生成，请稍后刷新\" show-icon :closable=\"false\"
              style=\"margin-bottom:16px\" />
"""
    require_contains(content, old_alert, "TutorialView alert")
    content = content.replace(old_alert, new_alert, 1)

    old_load = """async function loadTutorial() {
  if (!topicKey.value) return
  loading.value = true
  try {
    const res: any = await tutorialApi.getByTopic(topicKey.value)
    tutorial.value = res.data
    if (res.data?.chapter_tree?.length) {
      await selectChapter(res.data.chapter_tree[0])
      await loadProgress()
    }
  } finally { loading.value = false }
}
"""
    new_load = """async function loadTutorial(forceRefresh = false) {
  if (!topicKey.value) return
  loading.value = true
  try {
    const res: any = await tutorialApi.getByTopic(topicKey.value, forceRefresh)
    tutorial.value = res.data

    const chapters = res.data?.chapter_tree || []
    if (!chapters.length) {
      currentChapter.value = null
      progress.value = {}
      if (forceRefresh) {
        ElMessage.success('教程已按最新知识点刷新，当前领域暂无可学章节')
      }
      return
    }

    const keepCurrent = chapters.find((c: any) =>
      c.chapter_id === currentChapter.value?.chapter_id ||
      c.title === currentChapter.value?.title
    )
    await selectChapter(keepCurrent || chapters[0])
    await loadProgress()

    if (forceRefresh) {
      ElMessage.success('已按最新知识点重建教程，章节会逐步生成内容')
    }
  } finally { loading.value = false }
}

async function refreshTutorial() {
  await loadTutorial(true)
}
"""
    require_contains(content, old_load, "TutorialView loadTutorial")
    content = content.replace(old_load, new_load, 1)

    old_mount = """onMounted(() => {
  loadDomains()
  if (topicKey.value) loadTutorial()
})
"""
    new_mount = """watch(
  () => route.query.topic,
  (nextTopic) => {
    topicKey.value = (nextTopic as string) || ''
    tutorial.value = null
    currentChapter.value = null
    progress.value = {}
    if (topicKey.value) {
      loadTutorial()
    }
  }
)

onMounted(() => {
  loadDomains()
  if (topicKey.value) loadTutorial()
})
"""
    require_contains(content, old_mount, "TutorialView onMounted")
    content = content.replace(old_mount, new_mount, 1)

    style_old = """.page { padding: 8px; }
.chapter-list { height: calc(100vh - 120px); overflow-y: auto; }
"""
    style_new = """.page { padding: 8px; }
.header-bar { display: flex; gap: 8px; align-items: center; }
.chapter-list { height: calc(100vh - 120px); overflow-y: auto; }
"""
    require_contains(content, style_old, "TutorialView style")
    content = content.replace(style_old, style_new, 1)

    return content


def apply(root: Path) -> list[str]:
    touched = []
    path_map = {
        "apps/api/modules/tutorial/tutorial_service.py": patch_tutorial_service,
        "apps/api/modules/learner/learner_service.py": patch_learner_service,
        "apps/api/modules/routers.py": patch_routers,
        "apps/web/src/api/index.ts": patch_index_ts,
        "apps/web/src/views/tutorial/TutorialView.vue": patch_tutorial_view,
    }

    for rel, patcher in path_map.items():
        path = root / rel
        if not path.exists():
            raise FileNotFoundError(f"找不到文件：{rel}")
        original = read_text(path)
        patched = patcher(original)
        if patched == original:
            raise RuntimeError(f"{rel} 没有发生变化，已中止")
        backup_file(path)
        write_text(path, patched)
        touched.append(rel)

    return touched


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    print(f"[INFO] repo root: {root}")

    missing = [rel for rel in FILES if not (root / rel).exists()]
    if missing:
        print("[ERROR] 以下文件不存在：")
        for rel in missing:
            print("  -", rel)
        return 2

    touched = apply(root)
    print("[OK] 已写入源码补丁：")
    for rel in touched:
        print("  -", rel)
    print("")
    print("下一步：")
    print("  docker-compose up -d --build api celery_worker celery_beat web")
    print("")
    print("建议验证：")
    print("  1) 学习路径只出现当前主题的知识点")
    print("  2) 教程页点击“重新生成教程”后，删除/修改过的知识点会刷新")
    print("  3) 教程仍是“一知识点一章节”的现有设计，但会与当前主题、当前知识点集保持一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
