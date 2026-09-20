"""Appel unifié des LLM (Ollama local, API compatibles OpenAI comme Mammouth)."""
from __future__ import annotations
import os
import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


class ProviderError(RuntimeError):
    pass


def chat(provider: str, model: str, system: str, user: str,
         json_mode: bool = True, timeout: int = 300, **options) -> str:
    if provider == "ollama":
        return _ollama(model, system, user, json_mode, timeout, options)
    if provider in ("mammouth", "openai"):
        return _openai_compat(provider, model, system, user, json_mode, timeout, options)
    raise ProviderError(f"Provider inconnu : {provider}")


def _ollama(model, system, user, json_mode, timeout, options) -> str:
    payload = {
        "model": model,
        "stream": False,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "options": {k: v for k, v in options.items() if k in ("num_ctx", "temperature")},
    }
    if json_mode:
        payload["format"] = "json"
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ProviderError(f"Ollama ({model}) : {e}") from e
    return r.json()["message"]["content"]


def _openai_compat(provider, model, system, user, json_mode, timeout, options) -> str:
    env = provider.upper()
    base = os.environ.get(f"{env}_BASE_URL", "https://api.mammouth.ai/v1")
    key = os.environ.get(f"{env}_API_KEY")
    if not key:
        raise ProviderError(f"Variable {env}_API_KEY manquante")
    payload = {"model": model,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}]}
    if "temperature" in options:
        payload["temperature"] = options["temperature"]
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        r = httpx.post(f"{base}/chat/completions", json=payload, timeout=timeout,
                       headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ProviderError(f"{provider} ({model}) : {e}") from e
    return r.json()["choices"][0]["message"]["content"]
