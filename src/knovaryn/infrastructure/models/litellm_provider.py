"""LiteLLM-backed live model provider (spec §11.1, §11.2; exec rule 2).

A real provider that talks to any OpenAI-compatible / LiteLLM-supported
endpoint. It is an *opt-in* path only: it is never constructed on the offline/
CI path, and wiring it requires the operator to select a live runtime profile
(``deepseek_flash_budget``) and supply credentials/vars via the environment.

This provider implements the minimal contract the :class:`ModelGateway`
demands of a *real* provider:

``async complete(*, model, messages, temperature, max_output_tokens, schema_hash)
    -> {"content": <json-safe dict>, "usage": {input_tokens, output_tokens,
        total_tokens, provider_request_id}, "model": str}``

When the optional ``litellm`` package is installed it is used for routing and
cost/usage telemetry; otherwise a thin ``httpx`` client calls the configured
OpenAI-compatible ``base_url`` directly. Requests carry a JSON-mode schema hint
when available so responses parse reliably.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from ...domain.errors import ProviderError
from ...identity import ENV_PREFIX

_JSON_MODE_MODELS = {"deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"{ENV_PREFIX}{name}", default)


def _litellm_available() -> bool:
    try:
        import litellm  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


class LiteLLMProvider:
    """Live provider backed by LiteLLM (or a direct OpenAI-compatible HTTP call).

    Parameters
    ----------
    api_base:
        Optional base URL override. Defaults to ``KNOVARYN_DEEPSEEK_BASE_URL``,
        then the DeepSeek public endpoint.
    api_key:
        Optional API key. Defaults to ``KNOVARYN_DEEPSEEK_API_KEY`` (never
        committed; read from the environment at runtime).
    model:
        Default model name used when ``complete`` is called without one.
    """

    name = "litellm"

    def __init__(
        self,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str = "deepseek-v4-flash",
    ) -> None:
        self.api_base = api_base or _env("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
        self.api_key = api_key or _env("DEEPSEEK_API_KEY")
        self.model = model
        self._uses_litellm = _litellm_available()

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float | None = 0.0,
        max_output_tokens: int | None = None,
        schema_hash: str | None = None,
    ) -> dict[str, Any]:
        """Complete a chat request and return a JSON-safe content dict + usage."""
        if not self.api_key and not self._env_keyed():
            raise ProviderError(
                "live provider selected but no API key configured "
                f"(set {ENV_PREFIX}DEEPSEEK_API_KEY)",
                retryable=False,
            )
        if self._uses_litellm:
            return await self._complete_litellm(
                model=model,
                messages=messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                schema_hash=schema_hash,
            )
        return await self._complete_httpx(
            model=model,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            schema_hash=schema_hash,
        )

    def _env_keyed(self) -> bool:
        return bool(_env("DEEPSEEK_API_KEY"))

    # -- LiteLLM path --------------------------------------------------------
    async def _complete_litellm(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float | None,
        max_output_tokens: int | None,
        schema_hash: str | None,
    ) -> dict[str, Any]:
        import litellm

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.0,
            "api_base": self.api_base,
            "api_key": self.api_key or litellm.api_key,
        }
        if max_output_tokens:
            kwargs["max_tokens"] = max_output_tokens
        if model in _JSON_MODE_MODELS or schema_hash:
            kwargs["response_format"] = {"type": "json_object"}

        resp = await litellm.acompletion(**kwargs)
        content = resp.choices[0].message.content or ""
        usage = (resp.usage or {}) if hasattr(resp, "usage") else {}
        return {
            "content": self._parse_content(content, schema_hash=model in _JSON_MODE_MODELS),
            "usage": {
                "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                "provider_request_id": str(uuid.uuid4()),
            },
            "model": model,
        }

    # -- direct HTTP path -----------------------------------------------------
    async def _complete_httpx(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float | None,
        max_output_tokens: int | None,
        schema_hash: str | None,
    ) -> dict[str, Any]:
        import httpx

        url = self.api_base.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.0,
        }
        if max_output_tokens:
            payload["max_tokens"] = max_output_tokens
        if model in _JSON_MODE_MODELS or schema_hash:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise ProviderError(
                f"live provider HTTP {resp.status_code}: {resp.text[:300]}",
                retryable=resp.status_code >= 500,
            )

        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        return {
            "content": self._parse_content(content, schema_hash=model in _JSON_MODE_MODELS),
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0) or 0,
                "output_tokens": usage.get("completion_tokens", 0) or 0,
                "total_tokens": usage.get("total_tokens", 0) or 0,
                "provider_request_id": str(uuid.uuid4()),
            },
            "model": model,
        }

    @staticmethod
    def _parse_content(content: str, schema_hash: bool) -> dict[str, Any]:
        """Best-effort JSON parse of the model output."""
        text = (content or "").strip()
        if not text:
            return {"error": "empty model response"}
        if schema_hash or text.startswith("{"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        # not JSON — wrap so downstream starts from a stable shape
        return {"content_text": text}


__all__ = ["LiteLLMProvider", "_litellm_available"]
