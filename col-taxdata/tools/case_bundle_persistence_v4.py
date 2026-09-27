from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Iterable

from case_contract_validation_v4 import validate_legal_research_bundle


PERSISTENCE_VERSION = "1"


class BundlePersistenceError(RuntimeError):
    """Base failure for v4 LegalResearchBundle persistence."""


class BundleIntegrityError(BundlePersistenceError):
    """Raised when persisted bundle state cannot be trusted or reconstructed."""


class BundleMaterializationError(BundlePersistenceError):
    """Raised when the transport-safe bundle file cannot be materialized safely."""


@dataclass(frozen=True)
class ArtifactSpec:
    field: str
    artifact_kind: str
    ref_key: str | None
    owner: str
    authority_role: str
    collection: bool


_ARTIFACT_SPECS = (
    ArtifactSpec(
        "case_input",
        "case_input",
        None,
        "caller",
        "caller_input",
        False,
    ),
    ArtifactSpec(
        "intake_draft",
        "intake_draft",
        "intake_ref",
        "internal_intake_model",
        "intake_only",
        False,
    ),
    ArtifactSpec(
        "research_plan",
        "research_plan",
        "plan_ref",
        "platform",
        "platform_research",
        False,
    ),
    ArtifactSpec(
        "research_result",
        "research_result",
        "result_ref",
        "platform",
        "platform_research",
        False,
    ),
    ArtifactSpec(
        "sources",
        "official_source",
        "source_ref",
        "platform",
        "source_metadata",
        True,
    ),
    ArtifactSpec(
        "authorities",
        "canonical_authority",
        "authority_ref",
        "platform",
        "canonical_legal_support",
        True,
    ),
    ArtifactSpec(
        "evidence_spans",
        "evidence_span",
        "evidence_ref",
        "platform",
        "canonical_legal_support",
        True,
    ),
    ArtifactSpec(
        "normative_relationships",
        "normative_relationship",
        "relationship_ref",
        "platform",
        "canonical_legal_support",
        True,
    ),
    ArtifactSpec(
        "rule_fragments",
        "rule_fragment",
        "rule_ref",
        "platform",
        "canonical_legal_support",
        True,
    ),
    ArtifactSpec(
        "deterministic_evaluations",
        "deterministic_evaluation",
        "evaluation_ref",
        "platform",
        "deterministic_platform",
        True,
    ),
    ArtifactSpec(
        "calculation_traces",
        "calculation_trace",
        "calculation_ref",
        "platform",
        "deterministic_platform",
        True,
    ),
    ArtifactSpec(
        "unresolved",
        "unresolved_item",
        "unresolved_ref",
        "platform",
        "unresolved_platform",
        True,
    ),
)

_SPECS_BY_KIND = {spec.artifact_kind: spec for spec in _ARTIFACT_SPECS}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: Any) -> str:
    """Return a deterministic JSON representation used for persisted hashes."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _artifact_ref(spec: ArtifactSpec, payload: dict[str, Any]) -> str:
    if spec.ref_key is None:
        return spec.artifact_kind
    value = payload.get(spec.ref_key)
    if not isinstance(value, str) or not value:
        raise BundleIntegrityError(
            f"{spec.artifact_kind} is missing {spec.ref_key}"
        )
    return value


def _artifact_records(
    bundle: dict[str, Any],
) -> list[tuple[ArtifactSpec, int, str, str, str]]:
    records: list[tuple[ArtifactSpec, int, str, str, str]] = []
    for spec in _ARTIFACT_SPECS:
        value = bundle[spec.field]
        payloads: Iterable[dict[str, Any]]
        if spec.collection:
            payloads = value
        else:
            payloads = (value,)

        for ordinal, payload in enumerate(payloads):
            payload_json = canonical_json(payload)
            records.append(
                (
                    spec,
                    ordinal,
                    _artifact_ref(spec, payload),
                    payload_json,
                    hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                )
            )
    return records


def _bundle_metadata(
    *,
    case_ref: str,
    bundle: dict[str, Any],
) -> dict[str, str]:
    return {
        "bundle_ref": bundle["bundle_ref"],
        "case_ref": case_ref,
        "contract_version": bundle["contract_version"],
        "status": bundle["status"],
        "bundle_sha256": json_sha256(bundle),
        "research_context_sha256": json_sha256(
            bundle["research_result"]["research_context"]
        ),
        "generated_at": bundle["generated_at"],
    }


def _assert_existing_metadata(
    row: tuple[Any, ...],
    expected: dict[str, str],
) -> None:
    names = (
        "case_ref",
        "contract_version",
        "status",
        "bundle_sha256",
        "research_context_sha256",
        "generated_at",
    )
    actual = dict(zip(names, row))
    mismatched = [
        name for name in names if actual[name] != expected[name]
    ]
    if mismatched:
        raise BundleIntegrityError(
            "existing bundle_ref has conflicting immutable metadata: "
            + ", ".join(mismatched)
        )


def persist_legal_research_bundle(
    con: sqlite3.Connection,
    *,
    case_ref: str,
    bundle: dict[str, Any],
    dry_run: bool = False,
    persisted_at: str | None = None,
) -> dict[str, Any]:
    """Persist one validated v4 bundle as immutable ownership-aware artifacts.

    The legacy v3 claims/case_items tables are deliberately not used. Model-owned
    IntakeDraft material is stored only with the explicit intake-only role, while
    canonical support and deterministic results are platform-owned artifacts.
    Reusing an existing bundle_ref is allowed only when the reconstructed bundle
    is byte-semantically identical under deterministic JSON canonicalization.
    """
    validate_legal_research_bundle(bundle)
    if not isinstance(case_ref, str) or not case_ref:
        raise BundlePersistenceError("case_ref must be a non-empty string")

    metadata = _bundle_metadata(case_ref=case_ref, bundle=bundle)
    records = _artifact_records(bundle)
    existing = con.execute(
        """
        SELECT
            case_ref,
            contract_version,
            status,
            bundle_sha256,
            research_context_sha256,
            generated_at
        FROM case_v4_bundles
        WHERE bundle_ref = ?
        """,
        (metadata["bundle_ref"],),
    ).fetchone()

    if existing is not None:
        _assert_existing_metadata(existing, metadata)
        reconstructed = load_legal_research_bundle(
            con,
            bundle_ref=metadata["bundle_ref"],
        )
        if canonical_json(reconstructed) != canonical_json(bundle):
            raise BundleIntegrityError(
                "existing bundle_ref reconstructs to different bundle content"
            )
        return {
            **metadata,
            "mode": "preview" if dry_run else "write",
            "action": "reuse",
            "artifact_count": len(records),
            "artifacts_inserted": 0,
            "artifacts_reused": len(records),
            "would_insert_bundle": False,
            "would_insert_artifacts": 0,
        }

    if dry_run:
        return {
            **metadata,
            "mode": "preview",
            "action": "insert",
            "artifact_count": len(records),
            "artifacts_inserted": 0,
            "artifacts_reused": 0,
            "would_insert_bundle": True,
            "would_insert_artifacts": len(records),
        }

    timestamp = persisted_at or utc_now()
    try:
        with con:
            con.execute(
                """
                INSERT INTO case_v4_bundles(
                    bundle_ref,
                    case_ref,
                    contract_version,
                    status,
                    bundle_sha256,
                    research_context_sha256,
                    generated_at,
                    persisted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metadata["bundle_ref"],
                    metadata["case_ref"],
                    metadata["contract_version"],
                    metadata["status"],
                    metadata["bundle_sha256"],
                    metadata["research_context_sha256"],
                    metadata["generated_at"],
                    timestamp,
                ),
            )
            for spec, ordinal, artifact_ref, payload_json, payload_sha256 in records:
                con.execute(
                    """
                    INSERT INTO case_v4_artifacts(
                        bundle_ref,
                        artifact_kind,
                        artifact_ref,
                        owner,
                        authority_role,
                        ordinal,
                        payload_json,
                        payload_sha256
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metadata["bundle_ref"],
                        spec.artifact_kind,
                        artifact_ref,
                        spec.owner,
                        spec.authority_role,
                        ordinal,
                        payload_json,
                        payload_sha256,
                    ),
                )
    except sqlite3.Error as exc:
        raise BundlePersistenceError(
            f"v4 bundle persistence failed safely: {exc}"
        ) from exc

    reconstructed = load_legal_research_bundle(
        con,
        bundle_ref=metadata["bundle_ref"],
    )
    if canonical_json(reconstructed) != canonical_json(bundle):
        raise BundleIntegrityError(
            "persisted bundle does not reconstruct to the validated input"
        )

    return {
        **metadata,
        "mode": "write",
        "action": "insert",
        "artifact_count": len(records),
        "artifacts_inserted": len(records),
        "artifacts_reused": 0,
        "would_insert_bundle": False,
        "would_insert_artifacts": 0,
    }


def load_legal_research_bundle(
    con: sqlite3.Connection,
    *,
    bundle_ref: str,
) -> dict[str, Any]:
    """Reconstruct and integrity-check a v4 bundle without corpus/filesystem access."""
    row = con.execute(
        """
        SELECT
            contract_version,
            status,
            bundle_sha256,
            research_context_sha256,
            generated_at
        FROM case_v4_bundles
        WHERE bundle_ref = ?
        """,
        (bundle_ref,),
    ).fetchone()
    if row is None:
        raise BundlePersistenceError(f"bundle not found: {bundle_ref}")

    (
        contract_version,
        status,
        expected_bundle_sha256,
        expected_context_sha256,
        generated_at,
    ) = row

    artifact_rows = con.execute(
        """
        SELECT
            artifact_kind,
            artifact_ref,
            owner,
            authority_role,
            ordinal,
            payload_json,
            payload_sha256
        FROM case_v4_artifacts
        WHERE bundle_ref = ?
        ORDER BY artifact_kind, ordinal, artifact_ref
        """,
        (bundle_ref,),
    ).fetchall()

    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {
        spec.artifact_kind: [] for spec in _ARTIFACT_SPECS
    }
    for (
        artifact_kind,
        artifact_ref,
        owner,
        authority_role,
        ordinal,
        payload_json,
        expected_payload_sha256,
    ) in artifact_rows:
        spec = _SPECS_BY_KIND.get(artifact_kind)
        if spec is None:
            raise BundleIntegrityError(
                f"unknown persisted artifact kind: {artifact_kind}"
            )
        if owner != spec.owner or authority_role != spec.authority_role:
            raise BundleIntegrityError(
                f"ownership/trust mismatch for {artifact_kind}:{artifact_ref}"
            )
        actual_payload_sha256 = hashlib.sha256(
            payload_json.encode("utf-8")
        ).hexdigest()
        if actual_payload_sha256 != expected_payload_sha256:
            raise BundleIntegrityError(
                f"payload hash mismatch for {artifact_kind}:{artifact_ref}"
            )
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise BundleIntegrityError(
                f"invalid persisted JSON for {artifact_kind}:{artifact_ref}"
            ) from exc
        if _artifact_ref(spec, payload) != artifact_ref:
            raise BundleIntegrityError(
                f"artifact ref mismatch for {artifact_kind}:{artifact_ref}"
            )
        grouped[artifact_kind].append((ordinal, payload))

    bundle: dict[str, Any] = {
        "kind": "legal_research_bundle",
        "contract_version": contract_version,
        "bundle_ref": bundle_ref,
        "status": status,
        "generated_at": generated_at,
    }
    for spec in _ARTIFACT_SPECS:
        entries = sorted(grouped[spec.artifact_kind], key=lambda item: item[0])
        if [ordinal for ordinal, _ in entries] != list(range(len(entries))):
            raise BundleIntegrityError(
                f"non-contiguous ordinals for {spec.artifact_kind}"
            )
        if spec.collection:
            bundle[spec.field] = [payload for _, payload in entries]
        else:
            if len(entries) != 1:
                raise BundleIntegrityError(
                    f"expected exactly one {spec.artifact_kind}, found {len(entries)}"
                )
            bundle[spec.field] = entries[0][1]

    validate_legal_research_bundle(bundle)
    actual_bundle_sha256 = json_sha256(bundle)
    if actual_bundle_sha256 != expected_bundle_sha256:
        raise BundleIntegrityError(
            "reconstructed LegalResearchBundle hash does not match persistence"
        )
    actual_context_sha256 = json_sha256(
        bundle["research_result"]["research_context"]
    )
    if actual_context_sha256 != expected_context_sha256:
        raise BundleIntegrityError(
            "reconstructed research-context fingerprint hash does not match persistence"
        )
    return bundle


def render_legal_research_bundle(bundle: dict[str, Any]) -> str:
    """Render deterministic, standalone JSON suitable for external transport."""
    validate_legal_research_bundle(bundle)
    return json.dumps(
        bundle,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def materialization_path(
    *,
    case_root: Path,
    bundle_ref: str,
) -> Path:
    token = hashlib.sha256(bundle_ref.encode("utf-8")).hexdigest()[:32]
    return Path(case_root) / "v4" / token / "legal_research_bundle.json"


def _sha256_text(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def plan_legal_research_bundle_materialization(
    *,
    case_root: Path,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    """Preview deterministic bundle materialization without modifying the filesystem."""
    rendered = render_legal_research_bundle(bundle)
    path = materialization_path(
        case_root=case_root,
        bundle_ref=bundle["bundle_ref"],
    )
    stored = path.read_text(encoding="utf-8") if path.exists() else None
    if stored is None:
        status = "missing"
    elif stored == rendered:
        status = "current"
    else:
        status = "stale"
    return {
        "path": str(path),
        "status": status,
        "before_sha256": _sha256_text(stored),
        "canonical_sha256": _sha256_text(rendered),
        "would_write": status != "current",
    }


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def materialize_legal_research_bundle(
    *,
    case_root: Path,
    bundle: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    """Preview or write one deterministic standalone LegalResearchBundle JSON file."""
    before = plan_legal_research_bundle_materialization(
        case_root=case_root,
        bundle=bundle,
    )
    updated = False
    if write and before["would_write"]:
        path = Path(before["path"])
        try:
            _atomic_write_text(path, render_legal_research_bundle(bundle))
        except OSError as exc:
            raise BundleMaterializationError(
                f"v4 bundle materialization failed safely: {exc}"
            ) from exc
        updated = True

    after = plan_legal_research_bundle_materialization(
        case_root=case_root,
        bundle=bundle,
    )
    if write and after["status"] != "current":
        raise BundleMaterializationError(
            "v4 bundle materialization did not converge to canonical bytes"
        )

    return {
        "mode": "write" if write else "preview",
        "updated": updated,
        "before": before,
        "after": after,
    }


def persist_and_materialize_legal_research_bundle(
    *,
    db_path: Path,
    case_root: Path,
    case_ref: str,
    bundle: dict[str, Any],
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Persist and materialize v4 state, or execute the same decision logic as preview."""
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        persistence = persist_legal_research_bundle(
            con,
            case_ref=case_ref,
            bundle=bundle,
            dry_run=dry_run,
        )
        materialization_bundle = (
            bundle
            if dry_run
            else load_legal_research_bundle(
                con,
                bundle_ref=bundle["bundle_ref"],
            )
        )
    finally:
        con.close()

    materialization = materialize_legal_research_bundle(
        case_root=case_root,
        bundle=materialization_bundle,
        write=not dry_run,
    )
    return persistence, materialization
