from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from case_bundle_persistence_v4 import (
    BundleIntegrityError,
    BundleMaterializationError,
    BundlePersistenceError,
    _ARTIFACT_SPECS,
    _SPECS_BY_KIND,
    _artifact_records,
    _artifact_ref,
    _assert_existing_metadata,
    _atomic_write_text,
    _bundle_metadata,
    _sha256_text,
    canonical_json,
    json_sha256,
    utc_now,
)
from case_contract_validation_v5 import validate_legal_research_bundle


PERSISTENCE_VERSION = "2"


def persist_legal_research_bundle(
    con: sqlite3.Connection,
    *,
    case_ref: str,
    bundle: dict[str, Any],
    dry_run: bool = False,
    persisted_at: str | None = None,
) -> dict[str, Any]:
    """Persist one validated v5 bundle without reinterpreting v4 storage.

    ResearchAspect/ResearchTask live in the immutable ResearchPlan artifact;
    EvidenceSelection/AspectCoverage/OmittedWork live in ResearchResult.  Whole
    canonical JSON persistence therefore preserves every v5 typed ref/state
    exactly while retaining the established owner/authority roles.
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
        FROM case_v5_bundles
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
                "existing v5 bundle_ref reconstructs to different bundle content"
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
                INSERT INTO case_v5_bundles(
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
                    INSERT INTO case_v5_artifacts(
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
            f"v5 bundle persistence failed safely: {exc}"
        ) from exc

    reconstructed = load_legal_research_bundle(
        con,
        bundle_ref=metadata["bundle_ref"],
    )
    if canonical_json(reconstructed) != canonical_json(bundle):
        raise BundleIntegrityError(
            "persisted v5 bundle does not reconstruct to the validated input"
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
    """Reconstruct and integrity-check a v5 bundle from version-specific state."""
    row = con.execute(
        """
        SELECT
            contract_version,
            status,
            bundle_sha256,
            research_context_sha256,
            generated_at
        FROM case_v5_bundles
        WHERE bundle_ref = ?
        """,
        (bundle_ref,),
    ).fetchone()
    if row is None:
        raise BundlePersistenceError(f"v5 bundle not found: {bundle_ref}")

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
        FROM case_v5_artifacts
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
                f"unknown persisted v5 artifact kind: {artifact_kind}"
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
    if json_sha256(bundle) != expected_bundle_sha256:
        raise BundleIntegrityError(
            "reconstructed v5 LegalResearchBundle hash does not match persistence"
        )
    if json_sha256(bundle["research_result"]["research_context"]) != expected_context_sha256:
        raise BundleIntegrityError(
            "reconstructed v5 research-context fingerprint hash does not match persistence"
        )
    return bundle


def render_legal_research_bundle(bundle: dict[str, Any]) -> str:
    """Render deterministic standalone v5 JSON for external transport."""
    validate_legal_research_bundle(bundle)
    return json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def materialization_path(*, case_root: Path, bundle_ref: str) -> Path:
    import hashlib
    token = hashlib.sha256(bundle_ref.encode("utf-8")).hexdigest()[:32]
    return Path(case_root) / "v5" / token / "legal_research_bundle.json"


def plan_legal_research_bundle_materialization(
    *,
    case_root: Path,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    rendered = render_legal_research_bundle(bundle)
    path = materialization_path(case_root=case_root, bundle_ref=bundle["bundle_ref"])
    stored = path.read_text(encoding="utf-8") if path.exists() else None
    status = "missing" if stored is None else "current" if stored == rendered else "stale"
    return {
        "path": str(path),
        "status": status,
        "before_sha256": _sha256_text(stored),
        "canonical_sha256": _sha256_text(rendered),
        "would_write": status != "current",
    }


def materialize_legal_research_bundle(
    *,
    case_root: Path,
    bundle: dict[str, Any],
    write: bool,
) -> dict[str, Any]:
    before = plan_legal_research_bundle_materialization(
        case_root=case_root,
        bundle=bundle,
    )
    updated = False
    if write and before["would_write"]:
        try:
            _atomic_write_text(
                Path(before["path"]),
                render_legal_research_bundle(bundle),
            )
        except OSError as exc:
            raise BundleMaterializationError(
                f"v5 bundle materialization failed safely: {exc}"
            ) from exc
        updated = True
    after = plan_legal_research_bundle_materialization(
        case_root=case_root,
        bundle=bundle,
    )
    if write and after["status"] != "current":
        raise BundleMaterializationError(
            "v5 bundle materialization did not converge to canonical bytes"
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
    """Persist/materialize v5, or run identical decision logic without mutation."""
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
