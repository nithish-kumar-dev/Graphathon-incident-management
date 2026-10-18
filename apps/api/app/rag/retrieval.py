"""Hybrid retrieval for the investigator: typed graph, memory and knowledge context with ids and rationales.

Steps (Phase 3 brief):
1. extract   service ids/names and error terms from the incident, alerts and evidence
2. graph     bounded traversal with the named tools (depth <= 3, capped results, tenant-scoped)
3. keyword   full-text lookup on DocumentChunk.text_excerpt and AgentMemory.summary
4. vector    optional nearest neighbours (current model/version/dimension only)
5. dedupe    by node id, merging which steps matched
6. filter    authorisation (tenant scope; document classification re-checked at read time) and
             provenance (verified + grounded + validator/ground truth; no proposed-only fixes)
7. rerank    shared service, environment, error terms, recency, verified outcome, similarity
8. context   every item carries ids, source refs, score components and a plain-language rationale

Rules that keep text similarity from becoming a cause:
- Knowledge chunks are `claim_type: context`. They are never findings.
- A memory reached only by text similarity is `text_similarity_only` with precedent `none`. Only a memory
  about this incident, or one sharing an affected service, can support or warn against an action.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from redis.exceptions import ResponseError

from app.api import models as m
from app.api.errors import NotFound
from app.graph.client import GraphUnavailable
from app.rag.embeddings import Embedder, EmbeddingUnavailable
from app.tools import graph_tools as t
from app.tools.graph_tools import ToolContext

ERROR_TERM_RE = re.compile(
    r"\b(?:[1-5]xx|[45]\d{2}|timeouts?|timed|latency|p99|pool|exhaust(?:ed|ion)?|oom|deadlock|errors?|"
    r"rollback|connection|saturat\w*|unavailable|crash\w*)\b")
EXECUTED = {"executed_simulated"}
FULLTEXT_INDEXES = (("AgentMemory", "summary"), ("DocumentChunk", "text_excerpt"))
VECTOR_LABELS = ("AgentMemory", "DocumentChunk")


@dataclass(frozen=True)
class Limits:
    max_depth: int = 3
    max_memories: int = 10
    max_chunks: int = 8
    keyword_k: int = 15
    vector_k: int = 15
    deployment_window_hours: int = 72
    recency_half_life_days: float = 90.0


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StepStatus(_Out):
    status: Literal["completed", "skipped", "failed"]
    detail: str | None = None
    candidates: int = 0


class ScoreComponent(_Out):
    name: str
    value: float


class Extracted(_Out):
    service_ids: list[str]
    service_names: list[str]
    error_terms: list[str]
    query_text: str


class ScoredMemory(_Out):
    id: str
    summary: str
    memory_type: str
    outcome: Literal["successful", "failed", "unknown"]
    verification_status: Literal["verified"]
    validation_method: str | None
    about_incident_id: str | None
    about_incident_key: str | None
    applicability: Literal["same_incident", "shared_service", "dependency_related", "text_similarity_only"]
    precedent: Literal["supports", "warns_against", "none"]
    shared_service_ids: list[str]
    grounded_in: list[m.EvidenceRef]
    validated_by: list[str]
    derived_from_action_ids: list[str]
    matched_by: list[Literal["graph", "keyword", "vector"]]
    score: float
    components: list[ScoreComponent]
    rationale: list[str]


class ScoredChunk(_Out):
    id: str
    claim_type: Literal["context"] = "context"
    document_id: str
    document_title: str
    document_classification: str
    ordinal: int
    source_ref: str
    text_excerpt: str
    graph_links: list[str]
    matched_by: list[Literal["graph", "keyword", "vector"]]
    score: float
    components: list[ScoreComponent]
    rationale: list[str]


class GraphContext(_Out):
    incident: m.IncidentSummary
    alerts: list[m.AlertOut]
    evidence: list[m.EvidenceOut]
    explanation_paths: list[m.ExplanationPath]
    dependencies: dict[str, list[m.DependencyOut]]
    ownership: dict[str, list[m.TeamOut]]
    decisions: dict[str, list[m.DecisionOut]]
    runbooks: dict[str, list[m.RunbookRef]]
    recent_deployments: list[t.DeploymentHit]


class MemoryContext(_Out):
    items: list[ScoredMemory]
    excluded: dict[str, int]


class KnowledgeContext(_Out):
    items: list[ScoredChunk]
    excluded: dict[str, int]


class RetrievalBundle(_Out):
    incident_id: str
    as_of: datetime
    extracted: Extracted
    graph_context: GraphContext
    memory_context: MemoryContext
    knowledge_context: KnowledgeContext
    steps: dict[Literal["graph", "keyword", "vector"], StepStatus]
    embedding_model: str | None = None
    data_classification: Literal["synthetic"] = "synthetic"


# =============================================================================================
def retrieve(ctx: ToolContext, incident_id: str, *, embedder: Embedder | None,
             allowed_classifications: frozenset[str], limits: Limits | None = None) -> RetrievalBundle:
    limits = limits or Limits()
    repo = ctx.repo
    inc = repo.get_node("Incident", incident_id)
    if inc is None:
        raise NotFound(f"incident {incident_id} not found")

    # 1-2. bounded graph traversal (required: failures propagate as GraphUnavailable)
    graph = _graph_context(ctx, inc, limits)
    affected = set(graph.incident.affected_service_ids)
    neighbourhood = affected | {d.service.id for deps in graph.dependencies.values() for d in deps}
    targets = affected | {p.target_service_id for p in graph.explanation_paths}
    steps = {"graph": StepStatus(status="completed", candidates=len(neighbourhood))}

    extracted = _extract(repo, inc, graph)
    terms = extracted.error_terms + [n.lower() for n in extracted.service_names]

    # FalkorDB answers a full-text query on a missing index with zero rows, not an error, so the
    # indexes from migration 0002 are checked explicitly; otherwise a missing migration looks like "no hits".
    try:
        indexes = repo.node_indexes()
    except ResponseError:
        indexes = {}

    # 3. keyword
    kw_mem, kw_chunk = {}, {}
    missing_ft = [f"{lbl}.{prop}" for lbl, prop in FULLTEXT_INDEXES
                  if "FULLTEXT" not in indexes.get((lbl, prop), {}).get("types", ())]
    if missing_ft:
        steps["keyword"] = StepStatus(status="failed", detail=f"full-text index missing ({', '.join(missing_ft)}); "
                                                              "apply migration 0002; graph only")
    else:
        try:
            kw_mem = {r["id"]: r["score"] for r in repo.fulltext_search("AgentMemory", terms, k=limits.keyword_k)}
            kw_chunk = {r["id"]: r["score"] for r in repo.fulltext_search("DocumentChunk", terms,
                                                                          k=limits.keyword_k)}
            steps["keyword"] = StepStatus(status="completed", candidates=len(kw_mem) + len(kw_chunk))
        except ResponseError as exc:
            steps["keyword"] = StepStatus(status="failed", detail=_short(exc))

    # 4. vector (optional)
    vec_mem, vec_chunk, model = {}, {}, None
    bad_vec = [] if embedder is None else _vector_index_problems(indexes, embedder.dim)
    if embedder is None:
        steps["vector"] = StepStatus(status="skipped", detail="embedding provider disabled; graph + keyword only")
    elif bad_vec:
        steps["vector"] = StepStatus(status="failed", detail=f"{'; '.join(bad_vec)}; graph + keyword only")
    else:
        try:
            qvec = embedder.embed([extracted.query_text], "query")[0]
            version, model = embedder.version, embedder.model
            for label, target in (("AgentMemory", vec_mem), ("DocumentChunk", vec_chunk)):
                for r in repo.vector_search(label, qvec, k=limits.vector_k, model=embedder.model, version=version,
                                            dim=embedder.dim):
                    target[r["id"]] = max(0.0, min(1.0, 1.0 - float(r["distance"])))
            n = len(vec_mem) + len(vec_chunk)
            steps["vector"] = StepStatus(status="completed", candidates=n,
                                         detail=None if n else "no vectors stored for the current model/version")
        except EmbeddingUnavailable as exc:
            steps["vector"] = StepStatus(status="failed", detail=f"{type(exc).__name__}; graph + keyword only")
        except ResponseError as exc:
            steps["vector"] = StepStatus(status="failed", detail=f"vector query failed ({_short(exc)}); "
                                                                 "graph + keyword only")

    # 5-8. memories and knowledge
    memory = _memories(ctx, incident_id, affected, neighbourhood, set(extracted.error_terms), kw_mem, vec_mem, limits)
    knowledge = _knowledge(ctx, incident_id, graph, targets, set(extracted.error_terms), kw_chunk, vec_chunk,
                           allowed_classifications, limits)
    return RetrievalBundle(incident_id=incident_id, as_of=m.to_dt(ctx.now_ms), extracted=extracted,
                           graph_context=graph, memory_context=memory, knowledge_context=knowledge, steps=steps,
                           embedding_model=model)


# ---------------------------------------------------------------------------------------------
def _graph_context(ctx: ToolContext, inc: dict, limits: Limits) -> GraphContext:
    repo, iid = ctx.repo, inc["id"]
    services = repo.neighbors("Incident", iid, "AFFECTS", "Service", outgoing=True)
    alerts = repo.neighbors("Incident", iid, "HAS_ALERT", "Alert", outgoing=True, order_by="fired_at_ms")
    evidence = t.get_incident_evidence(ctx, t.IncidentEvidenceArgs(incident_id=iid)).items
    paths = t.get_explanation_path(ctx, t.ExplanationPathArgs(incident_id=iid)).paths
    deps = {s["id"]: t.expand_dependencies(ctx, t.ExpandDependenciesArgs(
        service_id=s["id"], max_depth=limits.max_depth, limit=50)).items for s in services}
    targets = sorted({s["id"] for s in services} | {p.target_service_id for p in paths})[:10]
    near = sorted({s["id"] for s in services} | {d.service.id for v in deps.values() for d in v})[:10]
    return GraphContext(
        incident=m.IncidentSummary(
            id=iid, key=inc["key"], title=inc["title"], severity=inc["severity"], status=inc["status"],
            started_at=m.to_dt(inc["started_at_ms"]), resolved_at=m.to_dt(inc.get("resolved_at_ms")),
            affected_service_ids=sorted(s["id"] for s in services), alert_count=len(alerts)),
        alerts=[m.AlertOut(id=a["id"], fingerprint=a["fingerprint"], severity=a["severity"],
                           fired_at=m.to_dt(a["fired_at_ms"]), last_fired_at=m.to_dt(a.get("last_fired_at_ms")),
                           dedup_count=a.get("dedup_count") or 0, summary=a.get("summary_redacted"),
                           source_ref=a.get("source_ref")) for a in alerts],
        evidence=evidence,
        explanation_paths=paths,
        dependencies=deps,
        ownership={s: t.get_service_ownership(ctx, t.ServiceOwnershipArgs(service_id=s)).teams for s in targets},
        decisions={s: t.get_current_decisions(ctx, t.CurrentDecisionsArgs(service_id=s)).items for s in targets},
        runbooks={s: t.get_applicable_runbooks(ctx, t.ApplicableRunbooksArgs(service_id=s)).items for s in targets},
        recent_deployments=t.get_recent_deployments(ctx, t.RecentDeploymentsArgs(
            service_ids=near, window_hours=limits.deployment_window_hours)).items if near else [],
    )


def _extract(repo, inc: dict, graph: GraphContext) -> Extracted:
    names = sorted({s["name"] for s in repo.get_nodes("Service", graph.incident.affected_service_ids).values()})
    texts = [inc["title"]] + [a.fingerprint.replace(":", " ").replace("_", " ") + " " + (a.summary or "")
                               for a in graph.alerts] + [e.excerpt or "" for e in graph.evidence]
    terms = sorted({mt.group(0).lower() for txt in texts for mt in ERROR_TERM_RE.finditer(txt.lower())})
    query = f"{inc['title']}. " + " ".join(a.summary or "" for a in graph.alerts) + \
            f" Services: {', '.join(names)}. Signals: {', '.join(terms)}."
    return Extracted(service_ids=graph.incident.affected_service_ids, service_names=names, error_terms=terms,
                     query_text=query[:1000])


def _memories(ctx, incident_id, affected, neighbourhood, query_terms, kw, vec, limits) -> MemoryContext:
    repo = ctx.repo
    graph_ids = {r["memory"]["id"] for r in repo.incident_memories(incident_id, include_unverified=True, limit=50)}
    candidates = graph_ids | set(kw) | set(vec)
    excluded: dict[str, int] = {}
    details = repo.memory_details(sorted(candidates))
    evidence = repo.get_nodes("Evidence", [e for d in details for e in d["evidence_ids"]])
    out = []
    for d in details:
        mem = d["memory"]
        reason = _exclusion(mem, d, evidence)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        shared = sorted(affected & set(d["incident_service_ids"]))
        if d["incident_id"] == incident_id:
            applicability = "same_incident"
        elif shared:
            applicability = "shared_service"
        elif neighbourhood & set(d["incident_service_ids"]):
            applicability = "dependency_related"
        else:
            applicability = "text_similarity_only"
        precedent = "none"
        if applicability in {"same_incident", "shared_service"}:
            precedent = "supports" if mem["outcome"] == "successful" else "warns_against" if mem["outcome"] == "failed" \
                else "none"
        matched = [s for s, hit in (("graph", mem["id"] in graph_ids), ("keyword", mem["id"] in kw),
                                    ("vector", mem["id"] in vec)) if hit]
        mem_terms = {x.group(0).lower() for x in ERROR_TERM_RE.finditer(mem["summary"].lower())}
        overlap = len(mem_terms & query_terms) / max(1, len(query_terms))
        age_days = max(0.0, (ctx.now_ms - (mem.get("validated_at_ms") or mem["created_at_ms"])) / 86_400_000)
        comps = [
            ScoreComponent(name="applicability", value={"same_incident": 0.35, "shared_service": 0.30,
                                                        "dependency_related": 0.15,
                                                        "text_similarity_only": 0.0}[applicability]),
            ScoreComponent(name="environment", value=0.05),  # tenant/env scope guarantees a match
            ScoreComponent(name="error_terms", value=round(0.15 * min(1.0, overlap), 4)),
            ScoreComponent(name="recency", value=round(0.10 * math.exp(-age_days / limits.recency_half_life_days), 4)),
            ScoreComponent(name="verified_outcome", value={"successful": 0.15, "failed": 0.12}.get(mem["outcome"], 0.0)),
            ScoreComponent(name="vector_similarity", value=round(0.15 * vec.get(mem["id"], 0.0), 4)),
            ScoreComponent(name="keyword", value=0.05 if mem["id"] in kw else 0.0),
        ]
        rationale = [{
            "same_incident": f"about this incident ({d['incident_key']})",
            "shared_service": f"about {d['incident_key']}, which also affected {', '.join(shared)}",
            "dependency_related": f"about {d['incident_key']} on a dependency of the affected services",
            "text_similarity_only": "matched by text only; no shared service, so it cannot support or warn",
        }[applicability],
            (f"verified {mem['outcome']} outcome ({mem.get('validation_method')}"
            f"{', by ' + ', '.join(d['validator_ids']) if d['validator_ids'] else ''})"),
            f"grounded in {', '.join(sorted(d['evidence_ids']))}"]
        if mem_terms & query_terms:
            rationale.append(f"shares error terms: {', '.join(sorted(mem_terms & query_terms))}")
        out.append(ScoredMemory(
            id=mem["id"], summary=mem["summary"], memory_type=mem["memory_type"], outcome=mem["outcome"],
            verification_status="verified", validation_method=mem.get("validation_method"),
            about_incident_id=d["incident_id"], about_incident_key=d["incident_key"], applicability=applicability,
            precedent=precedent, shared_service_ids=shared,
            grounded_in=[_ev(evidence[e]) for e in sorted(d["evidence_ids"]) if e in evidence],
            validated_by=sorted(d["validator_ids"]), derived_from_action_ids=sorted(a["id"] for a in d["actions"]),
            matched_by=matched, score=round(sum(c.value for c in comps), 4),
            components=[c for c in comps if c.value], rationale=rationale))
    out.sort(key=lambda x: (-x.score, x.id))
    if len(out) > limits.max_memories:
        excluded["over_limit"] = len(out) - limits.max_memories
    return MemoryContext(items=out[:limits.max_memories], excluded=excluded)


def _exclusion(mem: dict, d: dict, evidence: dict) -> str | None:
    if mem["verification_status"] != "verified":
        return mem["verification_status"]                       # draft / rejected / superseded
    if not [e for e in d["evidence_ids"] if e in evidence]:
        return "missing_provenance"
    if not d["validator_ids"] and mem.get("validation_method") != "ground_truth":
        return "missing_provenance"
    if any(a.get("status") not in EXECUTED for a in d["actions"]):
        return "unexecuted_action"
    return None


def _knowledge(ctx, incident_id, graph: GraphContext, targets, query_terms, kw, vec, allowed, limits) -> KnowledgeContext:
    repo = ctx.repo
    governing = {dec.id for decs in graph.decisions.values() for dec in decs}
    doc_ids = {doc.id for decs in graph.decisions.values() for dec in decs for doc in dec.documented_in}
    for sid in targets:
        doc_ids |= {d["id"] for d in repo.neighbors("Service", sid, "RELATES_TO", "Document", outgoing=False, limit=20)}
    doc_ids |= {d["id"] for d in repo.neighbors("Incident", incident_id, "RELATES_TO", "Document", outgoing=False,
                                                 limit=20)}
    graph_chunks = {c["id"] for did in sorted(doc_ids)
                    for c in repo.neighbors("Document", did, "HAS_CHUNK", "DocumentChunk", outgoing=True, limit=20)}
    excluded: dict[str, int] = {}
    out = []
    for row in repo.chunk_details(sorted(graph_chunks | set(kw) | set(vec))):
        c, doc = row["chunk"], row["document"]
        if doc.get("classification") not in allowed:
            excluded["unauthorised"] = excluded.get("unauthorised", 0) + 1
            continue
        links = [f"Decision {x['id']} -[DOCUMENTED_IN]-> Document {doc['id']}" for x in row["decisions"]
                 if x["id"] in governing]
        links += [f"Document {doc['id']} -[RELATES_TO]-> {x['label']} {x['id']}" for x in row["relates_to"]
                  if x["id"] in targets or x["id"] == incident_id]
        chunk_terms = {x.group(0).lower() for x in ERROR_TERM_RE.finditer(c["text_excerpt"].lower())}
        overlap = len(chunk_terms & query_terms) / max(1, len(query_terms))
        comps = [ScoreComponent(name="graph_link", value=0.40 if links else 0.0),
                 ScoreComponent(name="vector_similarity", value=round(0.35 * vec.get(c["id"], 0.0), 4)),
                 ScoreComponent(name="keyword", value=0.15 if c["id"] in kw else 0.0),
                 ScoreComponent(name="error_terms", value=round(0.10 * min(1.0, overlap), 4))]
        matched = [s for s, hit in (("graph", c["id"] in graph_chunks), ("keyword", c["id"] in kw),
                                    ("vector", c["id"] in vec)) if hit]
        rationale = links[:] or ["no graph link to this incident's services or policies; text match only"]
        if c["id"] in vec:
            rationale.append(f"vector similarity {vec[c['id']]:.2f}")
        out.append(ScoredChunk(id=c["id"], document_id=doc["id"], document_title=doc["title"],
                               document_classification=doc["classification"], ordinal=c["ordinal"],
                               source_ref=c["source_ref"], text_excerpt=c["text_excerpt"], graph_links=links,
                               matched_by=matched, score=round(sum(x.value for x in comps), 4),
                               components=[x for x in comps if x.value], rationale=rationale))
    out.sort(key=lambda x: (-x.score, x.id))
    if len(out) > limits.max_chunks:
        excluded["over_limit"] = len(out) - limits.max_chunks
    return KnowledgeContext(items=out[:limits.max_chunks], excluded=excluded)


def _ev(props: dict) -> m.EvidenceRef:
    return m.EvidenceRef(id=props["id"], kind=props["kind"], source_ref=props["source_ref"],
                         observed_at=m.to_dt(props.get("observed_at_ms")), excerpt=props.get("excerpt_redacted"))


def _vector_index_problems(indexes: dict, dim: int) -> list[str]:
    problems = []
    for label in VECTOR_LABELS:
        idx = indexes.get((label, "embedding"))
        if idx is None or "VECTOR" not in idx["types"]:
            problems.append(f"vector index missing ({label}.embedding)")
        elif idx["options"].get("dimension") != dim:
            problems.append(f"vector index {label}.embedding has dimension {idx['options'].get('dimension')}, "
                            f"embedder has {dim}")
    return problems


def _short(exc: Exception) -> str:
    return str(exc).split("\n")[0][:120]


__all__ = ["GraphUnavailable", "Limits", "RetrievalBundle", "retrieve"]
