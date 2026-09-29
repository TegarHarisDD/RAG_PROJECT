"""Provider configuration: model IDs live in config, never hardcoded."""
from app.config import load_provider_config


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
