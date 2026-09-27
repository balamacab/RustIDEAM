from __future__ import annotations

from copy import deepcopy
from typing import Any

from llm_client import ModelRoute, StructuredGenerationCapability


class DeterministicIntakeAdapter:
    """Deterministic semantic intake adapter for shared port/contract tests."""

    adapter_id = "deterministic-intake"
    provider_id = "deterministic-test"
    structured_generation_capability = StructuredGenerationCapability(
        mechanism="deterministic-test-schema",
        schema_constrained=True,
        direct_object=True,
        post_response_repair=False,
    )

    def __init__(self, outputs: list[dict[str, Any] | Exception]):
        self._outputs = list(outputs)
        self.calls: list[ModelRoute] = []

    def structure_intake(
        self,
        *,
        case_input: dict[str, Any],
        route: ModelRoute,
    ) -> dict[str, Any]:
        del case_input
        self.calls.append(route)
        if not self._outputs:
            raise AssertionError("deterministic intake output queue exhausted")
        value = self._outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)
