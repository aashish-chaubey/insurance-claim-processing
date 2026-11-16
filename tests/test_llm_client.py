import pytest
from openai import AzureOpenAI, OpenAI
from pydantic import ValidationError

from app.agents.llm_client import _completion_parameters, _create_client, _resolve_model
from app.config import Settings


def test_azure_openai_configuration_creates_azure_client():
    settings = Settings(
        _env_file=None,
        llm_provider="azure_openai",
        azure_openai_api_key="test-key",
        azure_openai_endpoint="https://test-resource.openai.azure.com/",
        azure_openai_api_version="2024-10-21",
        azure_openai_deployment="claims-model",
    )

    client = _create_client(settings)

    assert isinstance(client, AzureOpenAI)
    assert str(client.base_url).endswith("/openai/")
    assert _resolve_model(settings, None) == "claims-model"
    assert _resolve_model(settings, "override-deployment") == "override-deployment"


def test_openai_configuration_remains_supported():
    settings = Settings(_env_file=None, openai_api_key="test-key", llm_model="gpt-4o-mini")

    client = _create_client(settings)

    assert type(client) is OpenAI
    assert _resolve_model(settings, None) == "gpt-4o-mini"


def test_azure_completion_omits_unsupported_temperature():
    settings = Settings(
        _env_file=None,
        llm_provider="azure_openai",
        azure_openai_api_key="test-key",
        azure_openai_endpoint="https://test-resource.openai.azure.com/",
        azure_openai_deployment="claims-model",
    )

    parameters = _completion_parameters(
        config=settings,
        model=None,
        system_prompt="system",
        user_prompt="user",
        schema_name="result",
        json_schema={"type": "object"},
        temperature=0.0,
    )

    assert "temperature" not in parameters
    assert parameters["model"] == "claims-model"


def test_openai_completion_keeps_configured_temperature():
    settings = Settings(_env_file=None, openai_api_key="test-key")

    parameters = _completion_parameters(
        config=settings,
        model=None,
        system_prompt="system",
        user_prompt="user",
        schema_name="result",
        json_schema={"type": "object"},
        temperature=0.25,
    )

    assert parameters["temperature"] == 0.25


def test_azure_openai_configuration_requires_endpoint_key_and_deployment():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, llm_provider="azure_openai")

    message = str(error.value)
    assert "AZURE_OPENAI_API_KEY" in message
    assert "AZURE_OPENAI_ENDPOINT" in message
    assert "AZURE_OPENAI_DEPLOYMENT" in message
