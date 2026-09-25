from __future__ import annotations

from typing import Any


REVIEW_REQUIRED_STATUSES = frozenset({"candidate", "unresolved"})
REVIEW_COMPLETE_STATUSES = frozenset({"validated", "human_verified"})


def case_claim_requires_human_review(
    bundle_claim: dict[str, Any],
    *,
    persisted_status: str,
) -> bool:
    """Return the canonical review requirement for a persisted CASE claim.

    Unsupported CASE conclusions must remain visibly review-required after
    translation from generated bundle state into SQLite. Validated and
    human-verified claims retain the existing no-review state after canonical
    support has been established. For other workflow states, preserve an
    explicitly declared boolean when one exists.
    """
    declared = bundle_claim.get("requires_human_review")
    if declared is not None and not isinstance(declared, bool):
        claim_id = bundle_claim.get("id", "<unknown>")
        raise ValueError(
            "requires_human_review must be boolean for "
            f"{claim_id}: {declared!r}"
        )

    if persisted_status in REVIEW_REQUIRED_STATUSES:
        return True
    if persisted_status in REVIEW_COMPLETE_STATUSES:
        return False
    return bool(declared) if declared is not None else False
