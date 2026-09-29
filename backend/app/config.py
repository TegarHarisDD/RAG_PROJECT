"""Provider configuration: OpenRouter model IDs live here, never in code.

Free ``:free`` variants rotate frequently (ADR-0001), so every model ID is an
env-overridable config value. Swapping a model is a .env edit, not a change.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar

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

# Retrieval/generation tuning (spec: top-k = 4 defaults; low temperature).
# Tuning knobs, not model IDs — still env-overridable so the Eval Set can
# compare settings without code changes.
_DEFAULT_TOP_K = 4
_DEFAULT_TEMPERATURE = 0.2


@dataclass(frozen=True)
class RetrievalConfig:
    """How a Question is answered: top-k Chunks retrieved, LLM temperature."""

    top_k: int
    temperature: float


_T = TypeVar("_T", bound=float)  # int and float both satisfy this bound


def _numeric_setting(
    name: str, source: Mapping[str, str], default: _T, cast: Callable[[str], _T]
) -> _T:
    """One numeric env setting: blank restores the default, garbage is a clean error."""
    raw = source.get(name, "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None


def load_retrieval_config(env: Mapping[str, str] | None = None) -> RetrievalConfig:
    """Read retrieval settings from ``env`` (defaults to the process environment).

    Mirrors ``load_provider_config``: the production path loads ``backend/.env``
    first so every entrypoint sees the same values; tests pass ``env=``
    explicitly and never touch the filesystem. Malformed values raise a clean
    ``ValueError`` naming the variable — silently falling back would hide a
    misconfiguration, and ``TOP_K=0`` would refuse every question.
    """
    if env is None:
        load_dotenv()
    source = os.environ if env is None else env
    top_k = _numeric_setting("TOP_K", source, _DEFAULT_TOP_K, int)
    temperature = _numeric_setting("ANSWER_TEMPERATURE", source, _DEFAULT_TEMPERATURE, float)
    if top_k < 1:
        raise ValueError(f"TOP_K must be at least 1, got {top_k}")
    if not 0.0 <= temperature <= 2.0:
        raise ValueError(f"ANSWER_TEMPERATURE must be between 0 and 2, got {temperature}")
    return RetrievalConfig(top_k=top_k, temperature=temperature)


@dataclass(frozen=True)
class AbuseConfig:
    """The abuse limits (spec: enforced in the FastAPI layer, under the free
    provider caps so real visitor traffic always has headroom)."""

    max_question_chars: int
    questions_per_ip_per_hour: int
    daily_question_limit: int


def load_abuse_config(env: Mapping[str, str] | None = None) -> AbuseConfig:
    """Read abuse limits from ``env`` (defaults to the process environment).

    Mirrors ``load_retrieval_config``: tests pass ``env=`` explicitly. A zero
    or negative limit would silently reject every visitor, so it raises at
    startup instead of becoming a mysteriously dead demo.
    """
    if env is None:
        load_dotenv()
    source = os.environ if env is None else env
    config = AbuseConfig(
        max_question_chars=_numeric_setting(
            "QUESTION_MAX_CHARS", source, 500, int
        ),
        questions_per_ip_per_hour=_numeric_setting(
            "RATE_LIMIT_PER_HOUR", source, 5, int
        ),
        daily_question_limit=_numeric_setting(
            "DAILY_QUESTION_LIMIT", source, 40, int
        ),
    )
    for name, value in (
        ("QUESTION_MAX_CHARS", config.max_question_chars),
        ("RATE_LIMIT_PER_HOUR", config.questions_per_ip_per_hour),
        ("DAILY_QUESTION_LIMIT", config.daily_question_limit),
    ):
        if value < 1:
            raise ValueError(f"{name} must be at least 1, got {value}")
    return config


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
