from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from case_attempt_evidence import RejectedStructuringEvidenceStore
from case_intake_inference import IntakeInferencePort
from llm_client import CaseStructuringService, LLMPlatformConfig, load_platform_config
from openai_compatible_intake_adapter import OpenAICompatibleIntakeAdapter


@dataclass(frozen=True)
class CaseIntakeComposition:
    """Configured runtime composition without leaking provider construction to entry points."""

    structurer: CaseStructuringService
    provider: str
    primary_model: str


def build_intake_inference_port(config: LLMPlatformConfig) -> IntakeInferencePort:
    """Select the concrete intake adapter from infrastructure configuration."""
    if config.adapter == "openai-compatible":
        return OpenAICompatibleIntakeAdapter(config)
    raise ValueError(f"unsupported CASE intake adapter {config.adapter!r}")


def build_case_intake_composition(
    config_path: Path,
    *,
    evidence_store: RejectedStructuringEvidenceStore | None = None,
) -> CaseIntakeComposition:
    """Compose CASE intake policy + adapter once at the infrastructure boundary."""
    config = load_platform_config(config_path)
    port = build_intake_inference_port(config)
    return CaseIntakeComposition(
        structurer=CaseStructuringService(config, port, evidence_store=evidence_store),
        provider=config.provider,
        primary_model=config.primary.name,
    )
