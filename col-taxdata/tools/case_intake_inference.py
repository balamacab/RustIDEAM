from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IntakeInferencePort(Protocol):
    """Application-owned semantic boundary for CASE intake inference.

    Implementations translate provider transport and response envelopes internally.
    The application receives only a structured intake candidate. The route object is
    the current provider-neutral CASE routing envelope retained for v3 compatibility;
    provider endpoint details never cross this boundary.
    """

    adapter_id: str
    provider_id: str
    structured_generation_capability: Any

    def structure_intake(
        self,
        *,
        case_input: dict[str, Any],
        route: Any,
    ) -> dict[str, Any]:
        """Return one directly parseable structured intake candidate."""
