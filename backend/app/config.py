"""Provider configuration: OpenRouter model IDs live here, never in code.

Free ``:free`` variants rotate frequently (ADR-0001), so every model ID is an
env-overridable config value. Swapping a model is a .env edit, not a change.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

# Spec defaults, all free variants (ADR-0001). The embedding model produces
# 1024-dim vectors (verified empirically at ingestion time, per ADR-0002).
_DEFAULT_EMBEDDING_MODEL = "liquid/lfm-2.5-embedding-350m:free"
_DEFAULT_LLM_CHAIN = (
    "qwen/qwen3.8-27b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
)
_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class ProviderConfig:
    """Everything the OpenRouter wrappers need, as plain values."""

    openrouter_api_key: str
    openrouter_base_url: str
    embedding_model: str
    llm_models: tuple[str, ...]


def load_provider_config(env: Mapping[str, str] | None = None) -> ProviderConfig:
    """Read provider settings from ``env`` (defaults to the process environment).

    The production path (``env=None``) loads ``backend/.env`` first, so every
    entrypoint (API, CLI) sees the same configuration without each one having
    to remember to call ``load_dotenv()``. Tests pass ``env=`` explicitly and
    never touch the filesystem.
    """
    if env is None:
        load_dotenv()
    source = os.environ if env is None else env
    llm_models = tuple(
        model.strip()
        for model in source.get("LLM_MODELS", ",".join(_DEFAULT_LLM_CHAIN)).split(",")
        if model.strip()
    )
    if not llm_models:  # blank or all-comma value restores the default chain
        llm_models = _DEFAULT_LLM_CHAIN
    return ProviderConfig(
        openrouter_api_key=source.get("OPENROUTER_API_KEY", ""),
        openrouter_base_url=source.get("OPENROUTER_BASE_URL", _DEFAULT_BASE_URL),
        embedding_model=source.get("EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL),
        llm_models=llm_models,
    )
