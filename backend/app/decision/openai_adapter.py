"""OpenAI Responses API adapter with no tools or retrieval."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Protocol, cast

from app.core.config import Settings
from app.decision.exceptions import DecisionAdapterError
from app.decision.prompt import build_prompt
from app.decision.schemas import AdapterResult, DecisionInput, DecisionOutput


class ResponsesClient(Protocol):
    async def parse(self, **kwargs: object) -> object: ...


class OpenAIDecisionAdapter:
    """Call strict structured Responses API output without exposing any tool."""

    def __init__(self, *, settings: Settings, responses_client: ResponsesClient | None = None) -> None:
        self._settings = settings
        self._responses_client = responses_client

    async def evaluate(self, decision_input: DecisionInput) -> AdapterResult:
        if not self._settings.openai_api_key:
            raise DecisionAdapterError("openai_api_key_missing")
        if not self._settings.openai_model:
            raise DecisionAdapterError("openai_model_missing")
        request_payload: dict[str, object] = {
            "model": self._settings.openai_model,
            "input": build_prompt(
                decision_input,
                prompt_version=self._settings.openai_decision_prompt_version,
            ),
            "text_format": DecisionOutput,
            "max_output_tokens": self._settings.openai_decision_max_output_tokens,
            "store": self._settings.openai_decision_store,
            "tool_choice": "none",
        }
        try:
            client = self._responses_client or self._build_client()
            response = await client.parse(**request_payload)
        except TimeoutError as exc:
            raise DecisionAdapterError("openai_timeout") from exc
        except Exception as exc:
            error_code = (
                "openai_timeout"
                if "timeout" in type(exc).__name__.lower()
                else "openai_sdk_unavailable"
                if isinstance(exc, ModuleNotFoundError)
                else "openai_error"
            )
            raise DecisionAdapterError(error_code) from exc
        status = getattr(response, "status", "completed")
        parsed = getattr(response, "output_parsed", None)
        if status != "completed":
            raise DecisionAdapterError("openai_incomplete")
        if parsed is None:
            raise DecisionAdapterError("openai_invalid_output")
        output = parsed.model_dump(mode="json") if isinstance(parsed, DecisionOutput) else parsed
        return AdapterResult(
            output=output,
            request_id=cast(str | None, getattr(response, "id", None)),
        )

    def _build_client(self) -> ResponsesClient:
        module: Any = import_module("openai")
        client = module.AsyncOpenAI(
            api_key=self._settings.openai_api_key,
            timeout=self._settings.openai_decision_timeout_seconds,
            max_retries=self._settings.openai_decision_max_retries,
        )
        return cast(ResponsesClient, client.responses)
