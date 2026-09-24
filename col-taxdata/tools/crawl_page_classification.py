from __future__ import annotations

from dataclasses import asdict, dataclass
from html.parser import HTMLParser
import re
import urllib.parse

from source_identity import UNKNOWN, classify_source_url


UNCLASSIFIED = "unclassified"
CONFIRMED_INDEX = "confirmed_index"
LEGAL_DOCUMENT = "legal_document"
LEGAL_EXTRACTION_FAILURE = "legal_extraction_failure"
AMBIGUOUS = "ambiguous"

ALLOWED_HOST = "normograma.dian.gov.co"
ALLOWED_PREFIX = "/dian/compilacion/"
DOC_PREFIX = "/dian/compilacion/docs/"
SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}

LEGAL_CUE_PATTERNS = (
    re.compile(r"\bSENTENCIA\s+[A-Z]?-?\d", re.IGNORECASE),
    re.compile(
        r"\b(?:LEY|DECRETO|RESOLUCI[ÓO]N|CIRCULAR|CONCEPTO|OFICIO)"
        r"\s+(?:N[ÚU]MERO\s+)?[A-Z0-9._/-]+",
        re.IGNORECASE,
    ),
    re.compile(r"\bCORTE\s+CONSTITUCIONAL\b", re.IGNORECASE),
    re.compile(r"\bART[IÍ]CULO\s+\d", re.IGNORECASE),
)


@dataclass(frozen=True)
class PageClassification:
    """Deterministic crawler-page classification with auditable evidence."""

    state: str
    reason_code: str
    source_family: str
    internal_link_count: int
    document_link_count: int
    index_link_count: int
    non_link_text_chars: int
    legal_cues: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["legal_cues"] = list(self.legal_cues)
        return result


class _StructureParser(HTMLParser):
    """Collect link structure separately from non-anchor visible body text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.non_link_text: list[str] = []
        self.skip_depth = 0
        self.anchor_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "a":
            self.anchor_depth += 1
            for key, value in attrs:
                if key.lower() == "href" and value:
                    self.hrefs.append(value)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "a" and self.anchor_depth:
            self.anchor_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth or self.anchor_depth:
            return
        value = " ".join(data.split())
        if value:
            self.non_link_text.append(value)


def _canonical_normograma_link(base_url: str, href: str) -> str | None:
    value = href.strip()
    if not value or value.startswith(("#", "javascript:", "mailto:")):
        return None
    absolute = urllib.parse.urljoin(base_url, value)
    parsed = urllib.parse.urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return None
    if (parsed.hostname or "").lower() != ALLOWED_HOST:
        return None
    path = urllib.parse.unquote(parsed.path)
    lower = path.lower()
    if not lower.startswith(ALLOWED_PREFIX):
        return None
    if not lower.endswith((".htm", ".html")):
        return None
    return urllib.parse.urlunparse(("https", ALLOWED_HOST, path, "", "", ""))


def _structure_evidence(
    source_url: str,
    html: str,
) -> tuple[int, int, int, int, tuple[str, ...]]:
    parser = _StructureParser()
    parser.feed(html)

    links = {
        link
        for href in parser.hrefs
        if (link := _canonical_normograma_link(source_url, href)) is not None
        and link != source_url
    }
    document_links = {
        link
        for link in links
        if urllib.parse.urlparse(link).path.lower().startswith(DOC_PREFIX)
    }
    index_links = links - document_links

    non_link_text = " ".join(parser.non_link_text)
    cue_names: list[str] = []
    for pattern in LEGAL_CUE_PATTERNS:
        match = pattern.search(non_link_text)
        if match:
            cue_names.append(match.group(0)[:120])

    return (
        len(links),
        len(document_links),
        len(index_links),
        len(non_link_text),
        tuple(cue_names),
    )


def classify_heading_failure(
    *,
    source_url: str,
    html: str,
) -> PageClassification:
    """Classify a page only after legal extraction failed to find a heading.

    Missing a heading is deliberately not navigation evidence. Known legal
    source families remain legal extraction failures. Unknown sources become
    confirmed navigation only when link structure is strongly navigation-like;
    all other cases remain explicitly ambiguous.
    """

    source_family = classify_source_url(source_url).family
    (
        internal_links,
        document_links,
        index_links,
        non_link_text_chars,
        legal_cues,
    ) = _structure_evidence(source_url, html)

    if source_family != UNKNOWN:
        return PageClassification(
            state=LEGAL_EXTRACTION_FAILURE,
            reason_code="KNOWN_LEGAL_SOURCE_HEADING_NOT_DETECTED",
            source_family=source_family,
            internal_link_count=internal_links,
            document_link_count=document_links,
            index_link_count=index_links,
            non_link_text_chars=non_link_text_chars,
            legal_cues=legal_cues,
        )

    document_share = (
        document_links / internal_links if internal_links else 0.0
    )
    navigation_supported = (
        internal_links >= 4
        and document_links >= 4
        and document_share >= 0.60
        and non_link_text_chars <= 2000
        and not legal_cues
    )
    if navigation_supported:
        return PageClassification(
            state=CONFIRMED_INDEX,
            reason_code="NAVIGATION_LINK_STRUCTURE_CONFIRMED",
            source_family=source_family,
            internal_link_count=internal_links,
            document_link_count=document_links,
            index_link_count=index_links,
            non_link_text_chars=non_link_text_chars,
            legal_cues=legal_cues,
        )

    reason = (
        "LEGAL_CUES_WITHOUT_TRUSTED_SOURCE_IDENTITY"
        if legal_cues
        else "INSUFFICIENT_NAVIGATION_EVIDENCE"
    )
    return PageClassification(
        state=AMBIGUOUS,
        reason_code=reason,
        source_family=source_family,
        internal_link_count=internal_links,
        document_link_count=document_links,
        index_link_count=index_links,
        non_link_text_chars=non_link_text_chars,
        legal_cues=legal_cues,
    )
