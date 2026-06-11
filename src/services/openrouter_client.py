"""OpenRouter chat completions client for optional text planning."""

import json
from typing import Any

import httpx

from src.config import AppConfig


def is_openrouter_configured(config: AppConfig) -> bool:
    """Return whether an OpenRouter API key is configured."""
    return bool(config.openrouter_api_key)


def build_openrouter_headers(config: AppConfig) -> dict[str, str]:
    """Build OpenRouter request headers without exposing secrets."""
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": config.openrouter_app_name,
    }
    if config.openrouter_api_key:
        headers["Authorization"] = f"Bearer {config.openrouter_api_key}"
    return headers


def call_openrouter_chat(
    config: AppConfig,
    selected_model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Call OpenRouter's OpenAI-compatible chat completions endpoint."""
    if not is_openrouter_configured(config):
        return {
            "ok": False,
            "text": "",
            "usage": {},
            "raw_response": {},
            "error": "OpenRouter API key is not configured.",
        }
    endpoint = f"{config.openrouter_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": selected_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    try:
        response = httpx.post(endpoint, headers=build_openrouter_headers(config), json=payload, timeout=timeout_seconds)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as error:
        return {"ok": False, "text": "", "usage": {}, "raw_response": {}, "error": safe_openrouter_error_message(error)}
    except (httpx.HTTPError, json.JSONDecodeError, OSError) as error:
        return {"ok": False, "text": "", "usage": {}, "raw_response": {}, "error": safe_openrouter_error_message(error)}
    choices = data.get("choices") if isinstance(data, dict) else []
    if not choices:
        return {"ok": False, "text": "", "usage": data.get("usage", {}) if isinstance(data, dict) else {}, "raw_response": data, "error": "OpenRouter returned no choices."}
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    text = str(message.get("content") or "").strip()
    if not text:
        return {"ok": False, "text": "", "usage": data.get("usage", {}), "raw_response": data, "error": "Selected model returned an empty response."}
    return {"ok": True, "text": text, "usage": data.get("usage", {}), "raw_response": data, "error": None}


def safe_openrouter_error_message(error: Exception) -> str:
    """Return a concise OpenRouter error message without secrets."""
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        try:
            payload = error.response.json()
        except json.JSONDecodeError:
            payload = {}
        message = payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else None
        if message:
            return f"OpenRouter request failed with HTTP {status_code}: {_redact_secret_like_text(str(message))}"
        return f"OpenRouter request failed with HTTP {status_code}."
    return f"OpenRouter request failed: {type(error).__name__}."


def _redact_secret_like_text(value: str) -> str:
    """Redact secret-like fragments from a message."""
    words = value.split()
    cleaned = []
    for word in words:
        if len(word) > 24 and any(character.isdigit() for character in word):
            cleaned.append("[redacted]")
        else:
            cleaned.append(word)
    return " ".join(cleaned)
