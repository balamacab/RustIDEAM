#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from materialize_case_sources import canonical_case_sources


def md_escape(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def compact_quote(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split())


def load_unresolved(case_dir: Path) -> list[dict[str, object]]:
    path = case_dir / "unresolved.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("items", []))


def claim_rows(
    con: sqlite3.Connection,
    case_id: str,
) -> list[tuple]:
    return con.execute(
        """
        SELECT
            c.claim_id,
            c.status,
            c.object_literal,
            c.claim_type,
            c.confidence_extraction,
            c.requires_human_review
        FROM claims c
        JOIN case_items ci
          ON ci.item_type = 'claim'
         AND ci.item_id = c.claim_id
        WHERE ci.case_id = ?
        ORDER BY c.claim_id
        """,
        (case_id,),
    ).fetchall()


def claim_evidence_rows(
    con: sqlite3.Connection,
    claim_id: str,
) -> list[tuple]:
    return con.execute(
        """
        SELECT
            e.evidence_id,
            m.source_id,
            e.manifestation_id,
            e.extracted_segment_id,
            e.exact_quote,
            e.source_url,
            e.source_sha256,
            e.retrieved_at,
            e.extraction_method,
            e.extractor_version,
            e.review_status
        FROM evidence e
        JOIN manifestations m
          ON m.manifestation_id = e.manifestation_id
        WHERE e.claim_id = ?
        ORDER BY
            m.source_id,
            e.manifestation_id,
            COALESCE(e.extracted_segment_id, ''),
            e.evidence_id
        """,
        (claim_id,),
    ).fetchall()


def relationship_rows(
    con: sqlite3.Connection,
    case_id: str,
) -> list[tuple]:
    return con.execute(
        """
        SELECT
            r.relationship_id,
            r.source_type,
            r.source_id,
            r.relation_type,
            r.target_type,
            r.target_id,
            r.scope,
            r.asserted_date,
            r.effective_date,
            r.end_date,
            r.status,
            r.evidence_id,
            r.confidence,
            r.requires_human_review
        FROM relationships r
        JOIN case_items ci
          ON ci.item_type = 'relationship'
         AND ci.item_id = r.relationship_id
        WHERE ci.case_id = ?
        ORDER BY r.relationship_id
        """,
        (case_id,),
    ).fetchall()


def render_report(
    *,
    con: sqlite3.Connection,
    case_id: str,
    case_dir: Path,
) -> str:
    case = con.execute(
        """
        SELECT title, query_text, as_of_date, status
        FROM cases
        WHERE case_id = ?
        """,
        (case_id,),
    ).fetchone()
    if case is None:
        raise RuntimeError(f"case not found: {case_id}")

    title, _query_text, as_of_date, case_status = case
    claims = claim_rows(con, case_id)
    relationships = relationship_rows(con, case_id)
    sources = canonical_case_sources(con, case_id=case_id)
    unresolved = load_unresolved(case_dir)

    lines: list[str] = []
    lines.append(f"# {case_id} — Informe canónico")
    lines.append("")
    lines.append("## Estado del expediente")
    lines.append("")
    lines.append(f"- Título: {title}")
    lines.append(f"- Fecha de corte: {as_of_date or 'no definida'}")
    lines.append(f"- Estado del caso: {case_status}")
    lines.append(f"- Claims vinculados: {len(claims)}")
    lines.append(
        "- Claims validados/human_verified: "
        + str(
            sum(
                status in {"validated", "human_verified"}
                for _, status, *_ in claims
            )
        )
    )
    lines.append(f"- Relaciones vinculadas: {len(relationships)}")
    lines.append(f"- Fuentes canónicas: {len(sources)}")
    lines.append(f"- Pendientes fácticos: {len(unresolved)}")
    lines.append("")

    lines.append("## Conclusiones jurídicas registradas")
    lines.append("")
    for (
        claim_id,
        status,
        object_literal,
        claim_type,
        confidence,
        requires_review,
    ) in claims:
        evidence = claim_evidence_rows(con, claim_id)
        lines.append(f"### {claim_id}")
        lines.append("")
        lines.append(object_literal or "")
        lines.append("")
        lines.append(
            f"Estado: **{status}** · "
            f"Tipo: `{claim_type}` · "
            f"Evidencias directas: {len(evidence)} · "
            f"Revisión humana requerida: "
            f"{'sí' if requires_review else 'no'}"
        )
        if confidence is not None:
            lines.append(
                f"Confianza de extracción registrada: {confidence:g}"
            )
        lines.append("")

        if evidence:
            lines.append("| Evidencia | Fuente | Segmento | SHA-256 |")
            lines.append("| --- | --- | --- | --- |")
            for row in evidence:
                (
                    evidence_id,
                    source_id,
                    _manifestation_id,
                    extracted_segment_id,
                    _quote,
                    _source_url,
                    source_sha256,
                    _retrieved_at,
                    _method,
                    _version,
                    _review_status,
                ) = row
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            md_escape(evidence_id),
                            md_escape(source_id),
                            md_escape(extracted_segment_id or "—"),
                            md_escape(source_sha256),
                        ]
                    )
                    + " |"
                )
            lines.append("")

            for row in evidence:
                (
                    evidence_id,
                    source_id,
                    manifestation_id,
                    extracted_segment_id,
                    exact_quote,
                    source_url,
                    source_sha256,
                    retrieved_at,
                    extraction_method,
                    extractor_version,
                    review_status,
                ) = row
                lines.append(f"#### Evidencia {evidence_id}")
                lines.append("")
                lines.append(f"- Fuente: `{source_id}`")
                lines.append(f"- Manifestación: `{manifestation_id}`")
                lines.append(
                    f"- Segmento extraído: "
                    f"`{extracted_segment_id or 'N/A'}`"
                )
                lines.append(f"- URL: {source_url}")
                lines.append(f"- SHA-256: `{source_sha256}`")
                lines.append(f"- Recuperada: {retrieved_at}")
                lines.append(
                    f"- Extracción: `{extraction_method}` "
                    f"(`{extractor_version}`)"
                )
                lines.append(f"- Estado de revisión: `{review_status}`")
                lines.append("")
                quote = compact_quote(exact_quote)
                if quote:
                    lines.append("> " + quote.replace("\n", "\n> "))
                    lines.append("")

    lines.append("## Relaciones jurídicas vinculadas")
    lines.append("")
    if relationships:
        lines.append(
            "| Relación | Origen | Tipo | Destino | Estado | Evidencia |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in relationships:
            (
                relationship_id,
                source_type,
                source_id,
                relation_type,
                target_type,
                target_id,
                _scope,
                _asserted_date,
                _effective_date,
                _end_date,
                status,
                evidence_id,
                _confidence,
                _requires_review,
            ) = row
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_escape(relationship_id),
                        md_escape(f"{source_type}:{source_id}"),
                        md_escape(relation_type),
                        md_escape(f"{target_type}:{target_id}"),
                        md_escape(status),
                        md_escape(evidence_id or "—"),
                    ]
                )
                + " |"
            )
    else:
        lines.append("No hay relaciones jurídicas vinculadas.")
    lines.append("")

    lines.append("## Fuentes canónicas")
    lines.append("")
    for source in sources:
        lines.append(f"### {source['id']}")
        lines.append("")
        lines.append(f"- Autoridad: {source.get('authority') or 'N/A'}")
        lines.append(f"- Tipo: `{source.get('type') or 'N/A'}`")
        lines.append(f"- URL: {source.get('url') or 'N/A'}")
        doc_ids = source.get("document_ids", [])
        lines.append(
            "- Documentos: "
            + (
                ", ".join(f"`{doc_id}`" for doc_id in doc_ids)
                if doc_ids
                else "ninguno"
            )
        )
        for manifestation in source.get("manifestations", []):
            lines.append(
                "- Manifestación: "
                f"`{manifestation['manifestation_id']}` · "
                f"SHA-256 `{manifestation['sha256']}` · "
                f"{manifestation['retrieved_at']}"
            )
        lines.append("")

    lines.append("## Pendientes fácticos")
    lines.append("")
    if unresolved:
        for item in unresolved:
            lines.append(f"### {item.get('code', 'UNSPECIFIED')}")
            lines.append("")
            lines.append(str(item.get("question", "")).strip())
            impact = str(item.get("impact", "")).strip()
            if impact:
                lines.append("")
                lines.append(f"Impacto: {impact}")
            lines.append("")
    else:
        lines.append("No hay pendientes fácticos registrados.")
        lines.append("")

    lines.append("## Regla de trazabilidad")
    lines.append("")
    lines.append(
        "Este informe es una materialización determinística del estado "
        "registrado del caso. Las conclusiones jurídicas se leen de "
        "`claims`; su soporte se lee de `evidence`; las relaciones "
        "normativas se leen de `relationships`; las fuentes se derivan "
        "del grafo canónico de soporte; y los hechos pendientes se leen "
        "de `unresolved.json`. El informe no crea autoridad jurídica "
        "ni convierte hechos no confirmados en hechos probados."
    )
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize a deterministic Markdown report from a registered "
            "case, its canonical evidence graph, and unresolved facts."
        )
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--db", default="data/state/taxdata.sqlite")
    parser.add_argument("--output")
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    try:
        rendered = render_report(
            con=con,
            case_id=args.case_id,
            case_dir=Path(args.case_dir),
        )
    finally:
        con.close()

    if args.output:
        Path(args.output).write_text(
            rendered,
            encoding="utf-8",
        )
    else:
        print(rendered, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
