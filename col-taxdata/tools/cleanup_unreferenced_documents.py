#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable

STALE = "stale_derived_residue"
RETAIN_ACTIVE = "retained_active_binding"
RETAIN_PROVENANCE = "retained_explicit_provenance"
RETAIN_MANIFESTATION = "retained_manifestation"
RETAIN_CONFLICT = "retained_conflict"

INTRINSIC_DOCUMENT_CHILDREN = {"document_identifiers", "manifestations"}

POLYMORPHIC_BINDINGS = (
    (
        "relationships.document_endpoint",
        "relationships",
        """
        SELECT COUNT(*) FROM relationships
        WHERE (source_type = 'document' AND source_id = ?)
           OR (target_type = 'document' AND target_id = ?)
        """,
        2,
    ),
    (
        "temporal_events.document_endpoint",
        "temporal_events",
        """
        SELECT COUNT(*) FROM temporal_events
        WHERE (entity_type = 'document' AND entity_id = ?)
           OR (caused_by_type = 'document' AND caused_by_id = ?)
        """,
        2,
    ),
    (
        "case_items.document_item",
        "case_items",
        """
        SELECT COUNT(*) FROM case_items
        WHERE item_type = 'document' AND item_id = ?
        """,
        1,
    ),
    (
        "claims.document_endpoint",
        "claims",
        """
        SELECT COUNT(*) FROM claims
        WHERE (subject_type = 'document' AND subject_id = ?)
           OR (object_type = 'document' AND object_id = ?)
        """,
        2,
    ),
    (
        "review_queue.document_item",
        "review_queue",
        """
        SELECT COUNT(*) FROM review_queue
        WHERE entity_type = 'document' AND entity_id = ?
        """,
        1,
    ),
)


@dataclass(frozen=True)
class Reason:
    code: str
    count: int = 1
    detail: str | None = None


@dataclass(frozen=True)
class DocumentClassification:
    document_id: str
    canonical_keys: tuple[str, ...]
    classification: str
    reasons: tuple[Reason, ...]


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _tables(con: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }


def raw_registry_digest(con: sqlite3.Connection) -> str:
    """Hash registered immutable-manifestation metadata without reading raw bytes."""
    digest = hashlib.sha256()
    for row in con.execute(
        """
        SELECT manifestation_id, sha256, COALESCE(byte_size, -1), local_path
        FROM manifestations
        ORDER BY manifestation_id
        """
    ):
        digest.update("\0".join(str(value) for value in row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _primary_canonical_keys(
    con: sqlite3.Connection, document_id: str
) -> tuple[str, ...]:
    return tuple(
        row[0]
        for row in con.execute(
            """
            SELECT identifier_value
            FROM document_identifiers
            WHERE document_id = ?
              AND identifier_type = 'canonical_key'
              AND is_primary = 1
            ORDER BY identifier_value
            """,
            (document_id,),
        )
    )


def _direct_fk_bindings(
    con: sqlite3.Connection, document_id: str, tables: set[str]
) -> list[Reason]:
    """Find every current direct FK to documents, except intrinsic child rows."""
    reasons: list[Reason] = []
    for table in sorted(tables):
        try:
            foreign_keys = con.execute(
                f"PRAGMA foreign_key_list({_quote_identifier(table)})"
            ).fetchall()
        except sqlite3.DatabaseError:
            continue
        for foreign_key in foreign_keys:
            referenced_table = foreign_key[2]
            from_column = foreign_key[3]
            if referenced_table != "documents":
                continue
            if table in INTRINSIC_DOCUMENT_CHILDREN:
                continue
            count = con.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(table)} "
                f"WHERE {_quote_identifier(from_column)} = ?",
                (document_id,),
            ).fetchone()[0]
            if count:
                reasons.append(
                    Reason(
                        "DIRECT_DOCUMENT_BINDING",
                        int(count),
                        f"{table}.{from_column}",
                    )
                )
    return reasons


def _polymorphic_bindings(
    con: sqlite3.Connection, document_id: str, tables: set[str]
) -> list[Reason]:
    reasons: list[Reason] = []
    for detail, table, sql, parameter_count in POLYMORPHIC_BINDINGS:
        if table not in tables:
            continue
        count = con.execute(sql, (document_id,) * parameter_count).fetchone()[0]
        if count:
            reasons.append(
                Reason("POLYMORPHIC_DOCUMENT_BINDING", int(count), detail)
            )
    return reasons


def _identifier_evidence_state(
    con: sqlite3.Connection, document_id: str, tables: set[str]
) -> tuple[int, int, int, int]:
    if "document_identifier_evidence" not in tables:
        return 0, 0, 0, 0
    rows = con.execute(
        """
        SELECT di.identifier_type, di.is_primary, die.evidence_id,
               e.manifestation_id, e.source_sha256, m.sha256
        FROM document_identifier_evidence die
        JOIN document_identifiers di
          ON di.identifier_id = die.identifier_id
        JOIN evidence e
          ON e.evidence_id = die.evidence_id
        LEFT JOIN manifestations m
          ON m.manifestation_id = e.manifestation_id
        WHERE di.document_id = ?
        ORDER BY die.identifier_id, die.evidence_id
        """,
        (document_id,),
    ).fetchall()

    def valid(row: sqlite3.Row | tuple[object, ...]) -> bool:
        return (
            row[3] is not None
            and row[5] is not None
            and row[4] == row[5]
        )

    primary = [
        row
        for row in rows
        if row[0] == "canonical_key" and row[1] == 1
    ]
    return (
        len(rows),
        sum(1 for row in rows if valid(row)),
        len(primary),
        sum(1 for row in primary if valid(row)),
    )


def classify_document(
    con: sqlite3.Connection, document_id: str
) -> DocumentClassification:
    """Classify one canonical Document conservatively for lifecycle cleanup."""
    tables = _tables(con)
    keys = _primary_canonical_keys(con, document_id)
    exists = con.execute(
        "SELECT 1 FROM documents WHERE document_id = ?", (document_id,)
    ).fetchone()
    if exists is None:
        raise RuntimeError(f"document not found: {document_id}")

    manifestation_count = con.execute(
        "SELECT COUNT(*) FROM manifestations WHERE document_id = ?",
        (document_id,),
    ).fetchone()[0]
    if manifestation_count:
        return DocumentClassification(
            document_id,
            keys,
            RETAIN_MANIFESTATION,
            (Reason("HAS_MANIFESTATION", int(manifestation_count)),),
        )

    bindings = _direct_fk_bindings(con, document_id, tables)
    bindings.extend(_polymorphic_bindings(con, document_id, tables))
    if bindings:
        return DocumentClassification(
            document_id, keys, RETAIN_ACTIVE, tuple(bindings)
        )

    if len(keys) != 1:
        code = (
            "MISSING_PRIMARY_CANONICAL_IDENTIFIER"
            if not keys
            else "MULTIPLE_PRIMARY_CANONICAL_IDENTIFIERS"
        )
        return DocumentClassification(
            document_id, keys, RETAIN_CONFLICT, (Reason(code, len(keys)),)
        )

    (
        evidence_count,
        valid_evidence_count,
        primary_evidence_count,
        valid_primary_evidence_count,
    ) = _identifier_evidence_state(con, document_id, tables)
    if evidence_count:
        if evidence_count != valid_evidence_count:
            return DocumentClassification(
                document_id,
                keys,
                RETAIN_CONFLICT,
                (
                    Reason(
                        "INVALID_IDENTIFIER_EVIDENCE_CHAIN",
                        evidence_count - valid_evidence_count,
                    ),
                    Reason(
                        "VALID_IDENTIFIER_EVIDENCE_CHAIN",
                        valid_evidence_count,
                    ),
                ),
            )
        if valid_primary_evidence_count == 0:
            return DocumentClassification(
                document_id,
                keys,
                RETAIN_CONFLICT,
                (
                    Reason(
                        "IDENTIFIER_EVIDENCE_WITHOUT_PRIMARY_SUPPORT",
                        evidence_count,
                    ),
                ),
            )
        return DocumentClassification(
            document_id,
            keys,
            RETAIN_PROVENANCE,
            (
                Reason("VALID_IDENTIFIER_EVIDENCE_CHAIN", valid_evidence_count),
                Reason(
                    "VALID_PRIMARY_IDENTIFIER_EVIDENCE_CHAIN",
                    valid_primary_evidence_count,
                ),
            ),
        )

    return DocumentClassification(
        document_id,
        keys,
        STALE,
        (Reason("NO_MANIFESTATION_PROVENANCE_OR_ACTIVE_BINDING"),),
    )


def _source_less_document_ids(con: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in con.execute(
            """
            SELECT d.document_id
            FROM documents d
            WHERE NOT EXISTS (
                SELECT 1 FROM manifestations m
                WHERE m.document_id = d.document_id
            )
            ORDER BY d.document_id
            """
        )
    ]


def build_plan(con: sqlite3.Connection) -> dict[str, object]:
    classifications = [
        classify_document(con, document_id)
        for document_id in _source_less_document_ids(con)
    ]
    candidates = [
        item for item in classifications if item.classification == STALE
    ]
    retained = [
        item for item in classifications if item.classification != STALE
    ]
    conflicts = [
        item
        for item in classifications
        if item.classification == RETAIN_CONFLICT
    ]

    identifiers_to_delete = 0
    for item in candidates:
        identifiers_to_delete += con.execute(
            "SELECT COUNT(*) FROM document_identifiers WHERE document_id = ?",
            (item.document_id,),
        ).fetchone()[0]

    return {
        "source_less_documents": len(classifications),
        "candidate_delete_count": len(candidates),
        "retained_count": len(retained),
        "conflict_count": len(conflicts),
        "identifier_rows_to_delete": int(identifiers_to_delete),
        "candidate_deletes": [asdict(item) for item in candidates],
        "retained": [asdict(item) for item in retained],
        "conflicts": [asdict(item) for item in conflicts],
    }


def _connect(db_path: Path, *, apply: bool) -> sqlite3.Connection:
    if apply:
        con = sqlite3.connect(db_path, timeout=30)
    else:
        uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=30)
        con.execute("PRAGMA query_only = ON")
    con.execute("PRAGMA foreign_keys = ON")
    return con


def cleanup(*, db_path: Path, apply: bool) -> dict[str, object]:
    """Preview or apply deterministic cleanup of unsupported source-less Documents."""
    con = _connect(db_path, apply=apply)
    try:
        if not apply:
            plan = build_plan(con)
            return {
                "mode": "dry-run",
                **plan,
                "raw_registry_digest": raw_registry_digest(con),
                "deleted_documents": 0,
                "persistent_mutation": False,
            }

        con.execute("BEGIN IMMEDIATE")
        try:
            before_digest = raw_registry_digest(con)
            plan = build_plan(con)
            deleted: list[str] = []
            for item in plan["candidate_deletes"]:
                document_id = str(item["document_id"])
                current = classify_document(con, document_id)
                if current.classification != STALE:
                    raise RuntimeError(
                        f"classification changed before delete: {document_id} "
                        f"became {current.classification}"
                    )
                deleted_count = con.execute(
                    "DELETE FROM documents WHERE document_id = ?",
                    (document_id,),
                ).rowcount
                if deleted_count != 1:
                    raise RuntimeError(
                        f"expected to delete one document, deleted "
                        f"{deleted_count}: {document_id}"
                    )
                deleted.append(document_id)

            after_digest = raw_registry_digest(con)
            if before_digest != after_digest:
                raise RuntimeError(
                    "manifestation registry changed during document cleanup"
                )
            con.commit()
        except Exception:
            con.rollback()
            raise

        return {
            "mode": "apply",
            **plan,
            "deleted_documents": len(deleted),
            "deleted_document_ids": deleted,
            "raw_registry_digest_before": before_digest,
            "raw_registry_digest_after": after_digest,
            "hashes_unchanged": before_digest == after_digest,
            "persistent_mutation": bool(deleted),
        }
    finally:
        con.close()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Classify source-less canonical Documents and remove only unsupported "
            "derived residue. Default mode is a mutation-free dry-run."
        )
    )
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply exactly the deterministic stale-residue classification.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = cleanup(db_path=Path(args.db), apply=args.apply)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "error", "error": str(exc)},
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
