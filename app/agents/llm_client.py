import json

from openai import AzureOpenAI, OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings

settings = get_settings()


def _create_client(config: Settings) -> OpenAI:
    if config.llm_provider == "azure_openai":
        return AzureOpenAI(
            api_key=config.azure_openai_api_key,
            azure_endpoint=config.azure_openai_endpoint,
            api_version=config.azure_openai_api_version,
        )
    return OpenAI(api_key=config.openai_api_key)


def _resolve_model(config: Settings, requested_model: str | None) -> str:
    if requested_model:
        return requested_model
    if config.llm_provider == "azure_openai":
        if not config.azure_openai_deployment:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT is required for Azure OpenAI")
        return config.azure_openai_deployment
    return config.llm_model


def _completion_parameters(
    *,
    config: Settings,
    model: str | None,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    json_schema: dict,
    temperature: float,
) -> dict:
    parameters = {
        "model": _resolve_model(config, model),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": json_schema, "strict": True},
        },
    }
    if config.llm_provider != "azure_openai":
        parameters["temperature"] = temperature
    return parameters


_client = _create_client(settings)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def structured_call(
    *,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    json_schema: dict,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict:
    """Call the LLM and force a structured JSON response matching json_schema.
    Raises on malformed output after retries so the orchestrator can route the
    claim to an exception queue rather than silently proceeding."""
    resp = _client.chat.completions.create(
        **_completion_parameters(
            config=settings,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_name=schema_name,
            json_schema=json_schema,
            temperature=temperature,
        )
    )
    content = resp.choices[0].message.content
    return json.loads(content)
