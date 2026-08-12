"""Contracts for the model-provider infrastructure shared by Agent modules."""

from __future__ import annotations

import os
from unittest.mock import Mock, patch

import httpx

from agent.common import model_provider


def test_load_model_provider_settings_reads_explicit_environment():
    with patch.dict(
        os.environ,
        {
            "OPENAI_BASE_URL": "https://provider.example/v1",
            "OPENAI_API_KEY": "test-key",
        },
        clear=False,
    ):
        settings = model_provider.load_model_provider_settings()

    assert settings.base_url == "https://provider.example/v1"
    assert settings.api_key == "test-key"
    assert settings.model_name == "deepseek-v4-flash"


def test_build_chat_model_uses_injected_settings_without_network():
    settings = model_provider.ModelProviderSettings(
        base_url="https://provider.example/v1",
        api_key="test-key",
        model_name="test-model",
    )
    fake_provider = Mock(name="provider")
    fake_model = Mock(name="model")

    with (
        patch.object(model_provider, "OpenAIProvider", return_value=fake_provider) as provider,
        patch.object(model_provider, "OpenAIChatModel", return_value=fake_model) as model,
    ):
        client = Mock(spec=httpx.AsyncClient)
        result = model_provider.build_chat_model(client, settings)

    assert result is fake_model
    provider.assert_called_once_with(
        base_url=settings.base_url,
        api_key=settings.api_key,
        http_client=client,
    )
    model.assert_called_once_with("test-model", provider=fake_provider)


def test_default_model_settings_preserve_disabled_thinking():
    assert model_provider.default_model_settings() == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }
