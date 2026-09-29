"""Provider configuration: model IDs live in config, never hardcoded."""
import pytest

from app.config import load_provider_config, load_retrieval_config


def test_default_models_match_the_spec_free_chain() -> None:
    """The spec's all-free model IDs are the out-of-the-box configuration."""
    config = load_provider_config(env={})

    assert config.embedding_model == "liquid/lfm-2.5-embedding-350m:free"
    assert config.llm_models == (
        "qwen/qwen3.8-27b:free",
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
    )


def test_env_overrides_model_ids() -> None:
    """Free variants rotate; swapping models is an env edit, not a code change."""
    config = load_provider_config(
        env={
            "OPENROUTER_API_KEY": "test-key",
            "EMBEDDING_MODEL": "other/embedder:free",
            "LLM_MODELS": " first/new:free , second/new:free ",
        }
    )

    assert config.openrouter_api_key == "test-key"
    assert config.embedding_model == "other/embedder:free"
    assert config.llm_models == ("first/new:free", "second/new:free")


def test_empty_llm_models_value_falls_back_to_defaults() -> None:
    """A blank or all-comma LLM_MODELS restores the default chain, not an empty one."""
    config = load_provider_config(env={"LLM_MODELS": " , "})

    assert config.llm_models == load_provider_config(env={}).llm_models


def test_retrieval_defaults_match_the_spec() -> None:
    """top-k = 4 and low temperature are the out-of-the-box retrieval settings."""
    config = load_retrieval_config(env={})

    assert config.top_k == 4
    assert config.temperature == 0.2


def test_env_overrides_retrieval_settings() -> None:
    """The Eval Set can compare settings without code changes."""
    config = load_retrieval_config(env={"TOP_K": "6", "ANSWER_TEMPERATURE": "0.5"})

    assert (config.top_k, config.temperature) == (6, 0.5)


def test_blank_retrieval_values_fall_back_to_defaults() -> None:
    """An uncommented-but-empty ``TOP_K=`` line restores the default, not a crash."""
    config = load_retrieval_config(env={"TOP_K": " ", "ANSWER_TEMPERATURE": ""})

    assert config == load_retrieval_config(env={})


def test_malformed_retrieval_values_raise_clean_errors() -> None:
    """A non-numeric value is a readable config error, never a raw int() traceback."""
    with pytest.raises(ValueError, match="TOP_K"):
        load_retrieval_config(env={"TOP_K": "four"})
    with pytest.raises(ValueError, match="ANSWER_TEMPERATURE"):
        load_retrieval_config(env={"ANSWER_TEMPERATURE": "0.2.3"})


def test_top_k_must_be_positive_and_temperature_bounded() -> None:
    """TOP_K=0 would refuse every question; TOP_K=-3 is a negative Atlas limit;
    an out-of-range temperature is a config mistake, not a runtime surprise."""
    with pytest.raises(ValueError, match="TOP_K"):
        load_retrieval_config(env={"TOP_K": "0"})
    with pytest.raises(ValueError, match="TOP_K"):
        load_retrieval_config(env={"TOP_K": "-3"})
    with pytest.raises(ValueError, match="ANSWER_TEMPERATURE"):
        load_retrieval_config(env={"ANSWER_TEMPERATURE": "5"})
