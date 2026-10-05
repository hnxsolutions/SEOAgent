"""Persists the topic graph and answers the cannibalisation question from it.

`SeoGrowthEngine.cluster_topics` already groups phrases; this does not replace
it, it writes down what it produced and attaches real things to it — the
`BlogTopic` that will cover a node, the `CrawlPage` that already does, the
service page the cluster is meant to feed.

Having the graph in the database is what makes the cannibalisation answer
useful. "This topic is a duplicate" is a refusal; "this belongs to the Local SEO
cluster, where *Local SEO guide* already covers the same intent — update that
instead" is a decision someone can act on. The second answer is only possible
once the structure is stored.

Clusters are rebuilt incrementally: an existing cluster is matched by its
normalised pillar topic and updated, never duplicated. The unique constraint on
(project, pillar_topic) is the backstop.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.content_engine.scoring import (
    CANNIBAL_THRESHOLD,
    find_cannibalisation,
    normalise_phrase,
    similarity,
)
from app.models.blog import BlogDraft, BlogDraftStatus, BlogTopic, BlogTopicStatus
from app.models.content_cluster import (
    ClusterNodeStatus,
    ClusterNodeType,
    ContentCluster,
    ContentClusterNode,
)
from app.models.crawl import CrawlPage
from app.services.content_engine import latest_completed_crawl

logger = structlog.get_logger(__name__)


class CannibalisationVerdict:
    """What the check concluded. Three outcomes, never a bare boolean."""

    CLEAR = "CLEAR"
    UPDATE_EXISTING_CONTENT = "UPDATE_EXISTING_CONTENT"
    POTENTIAL_CANNIBALIZATION = "POTENTIAL_CANNIBALIZATION"


class ContentClusterService:
    """Builds the cluster graph and checks new topics against it."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Cannibalisation
    # ------------------------------------------------------------------

    async def check_cannibalisation(
        self, project_id: UUID, tenant_id: UUID, candidate: str
    ) -> Dict[str, Any]:
        """Compare a candidate topic against everything the site already has.

        Four sources, in descending order of how much a clash costs:
        published articles, existing drafts, queued topics, and live pages. A
        clash with something already published is the expensive one — that is
        where two URLs genuinely compete — so it is reported first.
        """
        sources: List[Tuple[str, str, Optional[str], str]] = []

        for title, slug, status in await self._draft_titles(project_id, tenant_id):
            kind = "published article" if status == BlogDraftStatus.published else "existing draft"
            sources.append((title, kind, slug, "blog_draft"))

        for title, keyword in await self._topic_titles(project_id, tenant_id):
            sources.append((title, "queued topic", None, "blog_topic"))
            if keyword and keyword != title:
                sources.append((keyword, "queued topic", None, "blog_topic"))

        for title, url in await self._page_titles(project_id, tenant_id):
            sources.append((title, "existing page", url, "crawl_page"))

        match = find_cannibalisation(candidate, [(title, ref) for title, _, ref, _ in sources])
        if match is None:
            return {
                "verdict": CannibalisationVerdict.CLEAR,
                "checked_against": len(sources),
                "conflict": None,
                "recommended_action": "Write it — nothing on the site targets this intent.",
            }

        kind, reference, origin = next(
            ((k, r, o) for t, k, r, o in sources if t == match.existing),
            ("existing content", None, "unknown"),
        )

        # A clash with something already live — a published article or a page
        # that was always there — is a true cannibalisation risk: two URLs
        # competing for one search. A clash with an unwritten topic is only a
        # duplicate sitting in the queue, which costs nothing yet.
        live_clash = kind in ("published article", "existing page")
        verdict = (
            CannibalisationVerdict.POTENTIAL_CANNIBALIZATION
            if live_clash
            else CannibalisationVerdict.UPDATE_EXISTING_CONTENT
        )

        return {
            "verdict": verdict,
            "checked_against": len(sources),
            "conflict": {
                "title": match.existing,
                "kind": kind,
                "reference": reference,
                "origin": origin,
                "overlap": match.overlap,
            },
            "reason": (
                f"\"{candidate}\" overlaps {match.overlap:.0%} with the {kind} "
                f"\"{match.existing}\". Two pages competing for one search split "
                f"the signals between them and neither wins."
            ),
            "recommended_action": (
                f"Update the {kind} \"{match.existing}\" to cover this angle rather "
                f"than publishing a second page for the same search."
                if live_clash
                else f"Drop this candidate; \"{match.existing}\" is already queued for the same intent."
            ),
            "threshold": CANNIBAL_THRESHOLD,
        }

    # ------------------------------------------------------------------
    # Cluster graph
    # ------------------------------------------------------------------

    async def rebuild(self, project_id: UUID, tenant_id: UUID) -> Dict[str, Any]:
        """Recompute clusters from current opportunities and attach real nodes."""
        from app.services.seo_growth import SeoGrowthEngine

        try:
            raw = await SeoGrowthEngine(self.db).topic_clusters(project_id, tenant_id)
        except Exception as exc:
            logger.warning("cluster_source_failed", project_id=str(project_id), error=str(exc))
            return {"status": "skipped", "reason": f"Clustering source unavailable: {exc}"}

        if not raw:
            return {"status": "completed", "clusters": 0, "reason": "No opportunities to cluster yet."}

        topics = {normalise_phrase(t.title): t for t in await self._topics(project_id, tenant_id)}
        pages = await self._pages(project_id, tenant_id)

        created = 0
        updated = 0
        nodes_added = 0

        for group in raw:
            pillar = str(group.get("topic") or group.get("pillar") or group.get("name") or "").strip()
            if not pillar:
                continue
            members = [str(m) for m in (group.get("keywords") or group.get("members") or []) if m]

            cluster, is_new = await self._upsert_cluster(project_id, tenant_id, pillar, members)
            created += int(is_new)
            updated += int(not is_new)

            nodes_added += await self._attach_nodes(cluster, tenant_id, pillar, members, topics, pages)

        await self.db.commit()
        logger.info(
            "content_clusters_rebuilt",
            project_id=str(project_id), created=created, updated=updated, nodes=nodes_added,
        )
        return {
            "status": "completed",
            "clusters_created": created,
            "clusters_updated": updated,
            "nodes_added": nodes_added,
        }

    async def list_clusters(self, project_id: UUID, tenant_id: UUID) -> List[Dict[str, Any]]:
        result = await self.db.execute(
            select(ContentCluster)
            .options(selectinload(ContentCluster.nodes))
            .where(
                ContentCluster.project_id == project_id,
                ContentCluster.tenant_id == tenant_id,
            )
            .order_by(ContentCluster.priority_score.desc())
        )
        clusters = list(result.scalars().all())
        return [self._cluster_dict(c) for c in clusters]

    def _cluster_dict(self, cluster: ContentCluster) -> Dict[str, Any]:
        nodes = list(cluster.nodes or [])
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for node in nodes:
            key = node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type)
            by_type.setdefault(key, []).append({
                "id": str(node.id),
                "title": node.title,
                "status": node.status.value if hasattr(node.status, "value") else node.status,
                "target_query": node.target_query,
                "url": node.url,
                "priority_score": node.priority_score,
                "reason": node.reason,
            })
        return {
            "id": str(cluster.id),
            "name": cluster.name,
            "pillar_topic": cluster.pillar_topic,
            "coverage": cluster.coverage,
            "priority_score": cluster.priority_score,
            "node_count": len(nodes),
            "nodes": by_type,
            "missing_count": len(by_type.get(ClusterNodeType.missing.value, [])),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _upsert_cluster(
        self, project_id: UUID, tenant_id: UUID, pillar: str, members: Sequence[str]
    ) -> Tuple[ContentCluster, bool]:
        key = normalise_phrase(pillar)[:255]
        result = await self.db.execute(
            select(ContentCluster).where(
                ContentCluster.project_id == project_id,
                ContentCluster.pillar_topic == key,
            )
        )
        cluster = result.scalar_one_or_none()
        if cluster:
            cluster.name = pillar[:255]
            return cluster, False

        cluster = ContentCluster(
            tenant_id=tenant_id,
            project_id=project_id,
            name=pillar[:255],
            pillar_topic=key,
            description=f"Built from {len(members)} related queries measured in Search Console.",
        )
        self.db.add(cluster)
        await self.db.flush()
        return cluster, True

    async def _attach_nodes(
        self,
        cluster: ContentCluster,
        tenant_id: UUID,
        pillar: str,
        members: Sequence[str],
        topics: Dict[str, BlogTopic],
        pages: Sequence[Tuple[str, str, UUID]],
    ) -> int:
        existing = {
            n.title for n in await self._cluster_nodes(cluster.id)
        }
        added = 0
        covered = 0

        candidates: List[Tuple[str, ClusterNodeType]] = [(pillar, ClusterNodeType.pillar)]
        candidates += [(m, ClusterNodeType.supporting) for m in members if m != pillar]

        for title, node_type in candidates:
            if title in existing:
                covered += 1
                continue

            topic = topics.get(normalise_phrase(title))
            page = self._matching_page(title, pages)

            if page is not None:
                status, url, page_id, reason = (
                    ClusterNodeStatus.published, page[1], page[2],
                    "A page on the site already covers this.",
                )
                covered += 1
                resolved_type = ClusterNodeType.service_page if node_type is ClusterNodeType.supporting else node_type
            elif topic is not None:
                status, url, page_id, reason = (
                    ClusterNodeStatus.drafted
                    if topic.status in (BlogTopicStatus.drafted, BlogTopicStatus.published)
                    else ClusterNodeStatus.planned,
                    None, None,
                    "Queued as a blog topic.",
                )
                covered += int(topic.status == BlogTopicStatus.published)
                resolved_type = node_type
            else:
                status, url, page_id, reason = (
                    ClusterNodeStatus.planned, None, None,
                    "Nothing covers this yet — a gap in the cluster.",
                )
                resolved_type = ClusterNodeType.missing if node_type is ClusterNodeType.supporting else node_type

            self.db.add(
                ContentClusterNode(
                    tenant_id=tenant_id,
                    cluster_id=cluster.id,
                    node_type=resolved_type,
                    status=status,
                    title=title[:500],
                    target_query=title[:500],
                    blog_topic_id=topic.id if topic is not None else None,
                    crawl_page_id=page_id,
                    url=url,
                    priority_score=float(getattr(topic, "priority_score", 0) or 0),
                    reason=reason,
                )
            )
            existing.add(title)
            added += 1

        total = len(candidates) or 1
        cluster.coverage = round(covered / total, 2)
        return added

    def _matching_page(
        self, title: str, pages: Sequence[Tuple[str, str, UUID]]
    ) -> Optional[Tuple[str, str, UUID]]:
        for page_title, url, page_id in pages:
            if similarity(title, page_title) >= CANNIBAL_THRESHOLD:
                return (page_title, url, page_id)
        return None

    async def _cluster_nodes(self, cluster_id: UUID) -> List[ContentClusterNode]:
        result = await self.db.execute(
            select(ContentClusterNode).where(ContentClusterNode.cluster_id == cluster_id)
        )
        return list(result.scalars().all())

    async def _topics(self, project_id: UUID, tenant_id: UUID) -> List[BlogTopic]:
        result = await self.db.execute(
            select(BlogTopic).where(
                BlogTopic.project_id == project_id, BlogTopic.tenant_id == tenant_id
            )
        )
        return list(result.scalars().all())

    async def _topic_titles(self, project_id: UUID, tenant_id: UUID) -> List[Tuple[str, Optional[str]]]:
        result = await self.db.execute(
            select(BlogTopic.title, BlogTopic.target_keyword).where(
                BlogTopic.project_id == project_id,
                BlogTopic.tenant_id == tenant_id,
                BlogTopic.status != BlogTopicStatus.rejected,
            )
        )
        return [(t or "", k) for t, k in result.all()]

    async def _draft_titles(
        self, project_id: UUID, tenant_id: UUID
    ) -> List[Tuple[str, Optional[str], Any]]:
        result = await self.db.execute(
            select(BlogDraft.title, BlogDraft.slug, BlogDraft.status).where(
                BlogDraft.project_id == project_id,
                BlogDraft.tenant_id == tenant_id,
                BlogDraft.status != BlogDraftStatus.rejected,
            )
        )
        return [(t or "", s, st) for t, s, st in result.all()]

    async def _page_titles(self, project_id: UUID, tenant_id: UUID) -> List[Tuple[str, str]]:
        pages = await self._pages(project_id, tenant_id)
        return [(title, url) for title, url, _ in pages]

    async def _pages(self, project_id: UUID, tenant_id: UUID) -> List[Tuple[str, str, UUID]]:
        crawl = await latest_completed_crawl(self.db, project_id, tenant_id)
        if not crawl:
            return []
        result = await self.db.execute(
            select(CrawlPage.title, CrawlPage.url, CrawlPage.id)
            .where(CrawlPage.crawl_job_id == crawl.id)
            .limit(1000)
        )
        return [(t or "", u or "", pid) for t, u, pid in result.all() if t or u]
