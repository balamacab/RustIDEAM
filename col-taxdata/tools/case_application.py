from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any
import uuid

from case_contract_validation import (
    CONTRACT_VERSION,
    CaseContractError,
    validate_case_input,
    validate_case_result,
    validate_result_preserves_draft,
)
from case_retrieval import (
    CorpusRetrievalService,
    RetrievalHit,
    RetrievalIntegrityError,
)
from llm_client import CaseStructuringService
from register_case_bundle import deterministic_id, register_case
from rematerialize_case import refresh_case_materializations
from validate_case_bundle import validate_case


ANALYZER_NAME = "natural_language_case_orchestrator"
ANALYZER_VERSION = "1"


CASE_ANALYSIS_INTEGRITY_FAILURE = "CASE_ANALYSIS_INTEGRITY_FAILURE"
CASE_PERSISTENCE_FAILURE = "CASE_PERSISTENCE_FAILURE"
CASE_MATERIALIZATION_FAILURE = "CASE_MATERIALIZATION_FAILURE"
CASE_VALIDATION_FAILURE = "CASE_VALIDATION_FAILURE"


class CaseAnalysisIntegrityError(RuntimeError):
    """Base failure for deterministic CASE analysis/application integrity."""

    code = CASE_ANALYSIS_INTEGRITY_FAILURE

    def __init__(self, detail: str):
        super().__init__(f"{self.code}: {detail}")
        self.detail = detail


class CasePersistenceError(CaseAnalysisIntegrityError):
    """CASE registration or writable-state preparation failed safely."""

    code = CASE_PERSISTENCE_FAILURE


class CaseMaterializationError(CaseAnalysisIntegrityError):
    """Deterministic CASE materialization failed safely."""

    code = CASE_MATERIALIZATION_FAILURE


class CaseValidationError(CaseAnalysisIntegrityError):
    """Generated/persisted CASE state failed canonical validation."""

    code = CASE_VALIDATION_FAILURE


@dataclass(frozen=True)
class AnalysisOutcome:
    case_id: str
    case_ref: str
    result: dict[str, Any]
    persistence_mode: str
    registration: dict[str, Any]
    materialization: dict[str, Any]
    validation: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_case_input_json(case_input: dict[str, Any]) -> str:
    """Return the deterministic serialized CaseInput used by CASE identity."""
    validate_case_input(case_input)
    return _compact_json(case_input)


def case_input_sha256(case_input: dict[str, Any]) -> str:
    """Fingerprint the canonical v3 CaseInput without changing its contents."""
    canonical = canonical_case_input_json(case_input).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _app_ref(kind: str, material: str) -> str:
    return f"{kind}:{uuid.uuid5(uuid.NAMESPACE_URL, material).hex}"


def _internal_case_id(case_input: dict[str, Any]) -> str:
    return deterministic_id(
        "CASE",
        (
            "col-taxdata:case-input:v3:"
            f"{canonical_case_input_json(case_input)}"
        ),
    )


def _internal_claim_id(
    case_id: str,
    candidate: dict[str, Any],
) -> str:
    return deterministic_id(
        "CLM",
        (
            f"col-taxdata:case-claim:v3:{case_id}:"
            f"{candidate['claim_ref']}:{candidate['text']}"
        ),
    )


def _document_display(hit: RetrievalHit) -> str:
    if hit.document_title:
        return hit.document_title
    components = [hit.document_type or "Documento"]
    if hit.document_number:
        components.append(hit.document_number)
    if hit.document_year:
        components.append(f"de {hit.document_year}")
    return " ".join(components)


def _source_public_ref(hit: RetrievalHit) -> str:
    return _app_ref("source", f"canonical-source:{hit.source_id}")


def _document_public_ref(hit: RetrievalHit) -> str:
    assert hit.document_id is not None
    return _app_ref("document", f"canonical-document:{hit.document_id}")


def _evidence_public_ref(
    candidate: dict[str, Any],
    hit: RetrievalHit,
) -> str:
    return _app_ref(
        "evidence",
        f"{candidate['claim_ref']}:{hit.extracted_segment_id}:{hit.text_sha256}",
    )


def _unresolved_ref(candidate: dict[str, Any], category: str) -> str:
    return _app_ref(
        "unresolved",
        f"{category}:{candidate['claim_ref']}:{candidate['text']}",
    )


def _unresolved_for_candidate(
    candidate: dict[str, Any],
    *,
    hits: list[RetrievalHit],
) -> dict[str, Any]:
    if not hits:
        category = "corpus_gap"
        description = (
            "No matching corpus segment was retrieved for this candidate; "
            "corpus coverage or search targeting must be checked before support."
        )
        next_action = "corpus_expansion"
    elif any(hit.document_id is None for hit in hits):
        category = "unresolved_legal_target"
        description = (
            "Relevant text was retrieved but at least one candidate source is "
            "not bound to a canonical document identity."
        )
        next_action = "deterministic_resolution"
    else:
        category = "unsupported_claim"
        description = (
            "Corpus text was retrieved, but the candidate did not satisfy the "
            "conservative deterministic evidence-support rule."
        )
        next_action = "human_review"

    item: dict[str, Any] = {
        "kind": "case_unresolved",
        "contract_version": CONTRACT_VERSION,
        "unresolved_ref": _unresolved_ref(candidate, category),
        "category": category,
        "description": description,
        "related_claim_refs": [candidate["claim_ref"]],
        "next_action": next_action,
    }
    if candidate.get("related_question_refs"):
        item["related_question_refs"] = list(candidate["related_question_refs"])
    return item


def _public_objects_for_support(
    retrieval: CorpusRetrievalService,
    candidate: dict[str, Any],
    supports: list[RetrievalHit],
    *,
    include_debug_provenance: bool,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    evidence: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    documents: dict[str, dict[str, Any]] = {}
    provisions: dict[str, dict[str, Any]] = {}

    for hit in supports:
        source_ref = _source_public_ref(hit)
        document_ref = _document_public_ref(hit)
        evidence_ref = _evidence_public_ref(candidate, hit)

        sources[source_ref] = {
            "source_ref": source_ref,
            "authority": hit.authority,
            "source_url": hit.source_url,
            "source_kind": hit.source_kind,
        }

        document: dict[str, Any] = {
            "document_ref": document_ref,
            "display_name": _document_display(hit),
        }
        if hit.document_type:
            document["document_type"] = hit.document_type
        if hit.document_number:
            document["number"] = hit.document_number
        if hit.document_year:
            document["year"] = hit.document_year
        if hit.document_issuer:
            document["issuer"] = hit.document_issuer
        documents[document_ref] = document

        item: dict[str, Any] = {
            "kind": "case_evidence",
            "contract_version": CONTRACT_VERSION,
            "evidence_ref": evidence_ref,
            "source_ref": source_ref,
            "document_ref": document_ref,
            "exact_quote": hit.text,
            "source_url": hit.source_url,
            "retrieved_at": hit.retrieved_at,
            "support_status": "validated",
            "provenance_ref": _app_ref(
                "provenance",
                f"{hit.manifestation_id}:{hit.extracted_segment_id}",
            ),
        }

        provision = retrieval.provision_for_segment(hit.extracted_segment_id)
        if provision is not None and provision["document_id"] == hit.document_id:
            provision_ref = _app_ref(
                "provision",
                f"canonical-provision:{provision['provision_id']}",
            )
            display = provision["designation"]
            if provision.get("title"):
                display = f"{display} — {provision['title']}"
            provisions[provision_ref] = {
                "provision_ref": provision_ref,
                "document_ref": document_ref,
                "display_name": display,
            }
            item["provision_ref"] = provision_ref

        if include_debug_provenance:
            item["debug_provenance"] = {
                "manifestation_id": hit.manifestation_id,
                "extracted_segment_id": hit.extracted_segment_id,
                "document_id": hit.document_id,
                "source_sha256": hit.manifestation_sha256,
                "sequence_no": hit.sequence_no,
            }
        evidence.append(item)

    return (
        evidence,
        list(sources.values()),
        list(documents.values()),
        list(provisions.values()),
    )


def _build_result(
    *,
    case_input: dict[str, Any],
    draft: dict[str, Any],
    retrieval: CorpusRetrievalService,
    case_ref: str,
    include_debug_provenance: bool,
) -> tuple[
    dict[str, Any],
    dict[str, list[RetrievalHit]],
]:
    supported_claims: list[dict[str, Any]] = []
    remaining_candidates: list[dict[str, Any]] = []
    unresolved = deepcopy(draft["unresolved"])
    all_evidence: dict[str, dict[str, Any]] = {}
    all_sources: dict[str, dict[str, Any]] = {}
    all_documents: dict[str, dict[str, Any]] = {}
    all_provisions: dict[str, dict[str, Any]] = {}
    support_hits: dict[str, list[RetrievalHit]] = {}

    for candidate in draft["candidate_claims"]:
        hits = retrieval.search_candidate(candidate)
        supports = retrieval.exact_canonical_support(candidate, hits)
        if not supports:
            remaining_candidates.append(deepcopy(candidate))
            unresolved.append(
                _unresolved_for_candidate(candidate, hits=hits)
            )
            support_hits[candidate["claim_ref"]] = []
            continue

        (
            evidence,
            sources,
            documents,
            provisions,
        ) = _public_objects_for_support(
            retrieval,
            candidate,
            supports,
            include_debug_provenance=include_debug_provenance,
        )
        support_hits[candidate["claim_ref"]] = supports
        for item in evidence:
            all_evidence[item["evidence_ref"]] = item
        for item in sources:
            all_sources[item["source_ref"]] = item
        for item in documents:
            all_documents[item["document_ref"]] = item
        for item in provisions:
            all_provisions[item["provision_ref"]] = item

        claim: dict[str, Any] = {
            "claim_ref": candidate["claim_ref"],
            "text": candidate["text"],
            "status": "validated",
            "evidence_refs": [
                _evidence_public_ref(candidate, hit)
                for hit in supports
            ],
        }
        if candidate.get("related_question_refs"):
            claim["related_question_refs"] = list(
                candidate["related_question_refs"]
            )
        supported_claims.append(claim)

    blocked_question = any(
        question["status"] == "blocked"
        for question in draft["questions"]
    )
    if blocked_question:
        analysis_status = "blocked"
    elif unresolved or remaining_candidates:
        analysis_status = "partial"
    else:
        analysis_status = "complete"

    result: dict[str, Any] = {
        "kind": "case_result",
        "contract_version": CONTRACT_VERSION,
        "case_ref": case_ref,
        "analysis_status": analysis_status,
        "facts": deepcopy(draft["facts"]),
        "questions": deepcopy(draft["questions"]),
        "supported_claims": supported_claims,
        "remaining_candidate_claims": remaining_candidates,
        "unresolved": unresolved,
        "evidence": list(all_evidence.values()),
        "sources": list(all_sources.values()),
        "documents": list(all_documents.values()),
        "provisions": list(all_provisions.values()),
        "model_metadata": deepcopy(draft["model_metadata"]),
        "generated_at": utc_now(),
    }
    for name in ("client_reference", "as_of_date"):
        if name in case_input:
            result[name] = case_input[name]

    validate_result_preserves_draft(draft, result)
    validate_case_result(result)
    return result, support_hits


def _legacy_unresolved(result: dict[str, Any], case_id: str) -> dict[str, Any]:
    items = []
    for item in result["unresolved"]:
        question = item["description"]
        if item.get("needed_information"):
            question = f"{question} Needed: {item['needed_information']}"
        items.append(
            {
                "code": (
                    f"ISSUE16_{item['category']}_"
                    f"{item['unresolved_ref'].split(':', 1)[-1][:12]}"
                ).upper(),
                "question": question,
                "impact": (
                    "The item remains unresolved in the v3 CaseResult and "
                    "cannot be promoted to canonical support."
                ),
            }
        )
    return {"case_id": case_id, "items": items}


def _write_internal_bundle(
    *,
    case_dir: Path,
    case_id: str,
    case_input: dict[str, Any],
    draft: dict[str, Any],
    result: dict[str, Any],
    support_hits: dict[str, list[RetrievalHit]],
) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "sources").mkdir(parents=True, exist_ok=True)

    (case_dir / "query.md").write_text(
        case_input["problem_text"],
        encoding="utf-8",
    )

    claims = []
    bindings: dict[str, dict[str, Any]] = {}
    for candidate in draft["candidate_claims"]:
        claim_id = _internal_claim_id(case_id, candidate)
        supports = support_hits.get(candidate["claim_ref"], [])
        claims.append(
            {
                "id": claim_id,
                "claim": candidate["text"],
                "status": "validated" if supports else "candidate",
                "sources": [],
                "requires_human_review": not bool(supports),
            }
        )
        if supports:
            bindings[claim_id] = {
                "status": "validated",
                "source_segments": [
                    {
                        "document_id": hit.document_id,
                        "sequence_no": hit.sequence_no,
                        "text_sha256": hit.text_sha256,
                    }
                    for hit in supports
                ],
                "relevance": (
                    "Issue #16 deterministic exact-text support from "
                    "verified canonical extracted segments."
                ),
            }

    (case_dir / "evidence.json").write_text(
        json.dumps(
            {
                "case_id": case_id,
                "status": result["analysis_status"],
                "claims": claims,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (case_dir / "claim_bindings.json").write_text(
        json.dumps(bindings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # register_case_bundle requires a manifest as an internal input. It starts
    # empty here and is replaced by the canonical materializer after registration.
    (case_dir / "sources" / "manifest.json").write_text(
        json.dumps({"case_id": case_id, "sources": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "unresolved.json").write_text(
        json.dumps(
            _legacy_unresolved(result, case_id),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (case_dir / "case_draft.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "case_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _persist_to_target(
    *,
    db_path: Path,
    case_dir: Path,
    case_id: str,
    case_input: dict[str, Any],
    draft: dict[str, Any],
    result: dict[str, Any],
    support_hits: dict[str, list[RetrievalHit]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        _write_internal_bundle(
            case_dir=case_dir,
            case_id=case_id,
            case_input=case_input,
            draft=draft,
            result=result,
            support_hits=support_hits,
        )
        registration = register_case(
            case_dir=case_dir,
            as_of_date=case_input.get("as_of_date"),
            db_path=db_path,
        )
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        raise CasePersistenceError(
            f"CASE registration failed safely: {exc}"
        ) from exc

    try:
        con = sqlite3.connect(db_path)
    except sqlite3.Error as exc:
        raise CasePersistenceError(
            f"CASE database could not be opened for materialization: {exc}"
        ) from exc

    try:
        try:
            materialization = refresh_case_materializations(
                con,
                case_id=case_id,
                case_dir=case_dir,
                write=True,
            )
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            raise CaseMaterializationError(
                f"CASE materialization failed safely: {exc}"
            ) from exc

        try:
            validation = validate_case(
                con=con,
                case_id=case_id,
                case_dir=case_dir,
            )
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            raise CaseValidationError(
                f"CASE validation could not complete safely: {exc}"
            ) from exc
    finally:
        con.close()

    if not validation["valid"]:
        raise CaseValidationError(
            "generated case bundle failed canonical validation: "
            + ",".join(validation["errors"])
        )
    return registration, materialization, validation


def _backup_sqlite(source: Path, target: Path) -> None:
    source_con = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_con = sqlite3.connect(target)
    try:
        source_con.backup(target_con)
    finally:
        target_con.close()
        source_con.close()


def analyze_case(
    *,
    case_input: dict[str, Any],
    db_path: Path,
    case_root: Path,
    structurer: CaseStructuringService,
    dry_run: bool = False,
    include_debug_provenance: bool = False,
    raw_request_sha256: str | None = None,
) -> AnalysisOutcome:
    """Analyze one natural-language case and optionally persist canonical case state.

    LLM work ends at a validated CaseDraft. Retrieval and claim promotion after
    that boundary are deterministic and read-only until the fully constructed
    v3 CaseResult has passed schema and semantic graph validation.
    """
    validate_case_input(case_input)
    structuring = structurer.structure(
        case_input,
        raw_request_sha256=raw_request_sha256,
    )
    draft = structuring.draft

    case_id = _internal_case_id(case_input)
    case_ref = _app_ref("case", f"canonical-case:{case_id}")

    read_con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        retrieval = CorpusRetrievalService(read_con)
        result, support_hits = _build_result(
            case_input=case_input,
            draft=draft,
            retrieval=retrieval,
            case_ref=case_ref,
            include_debug_provenance=include_debug_provenance,
        )
    except sqlite3.Error as exc:
        raise CaseAnalysisIntegrityError(
            f"corpus retrieval failed safely: {exc}"
        ) from exc
    finally:
        read_con.close()

    if dry_run:
        with tempfile.TemporaryDirectory(prefix="col-taxdata-case-preview-") as tmp:
            temp_root = Path(tmp)
            temp_db = temp_root / "preview.sqlite"
            temp_case_dir = temp_root / case_id
            _backup_sqlite(db_path, temp_db)
            registration, materialization, validation = _persist_to_target(
                db_path=temp_db,
                case_dir=temp_case_dir,
                case_id=case_id,
                case_input=case_input,
                draft=draft,
                result=result,
                support_hits=support_hits,
            )
        persistence_mode = "dry-run"
    else:
        case_dir = case_root / case_id
        registration, materialization, validation = _persist_to_target(
            db_path=db_path,
            case_dir=case_dir,
            case_id=case_id,
            case_input=case_input,
            draft=draft,
            result=result,
            support_hits=support_hits,
        )
        persistence_mode = "write"

    return AnalysisOutcome(
        case_id=case_id,
        case_ref=case_ref,
        result=result,
        persistence_mode=persistence_mode,
        registration=registration,
        materialization=materialization,
        validation=validation,
    )
