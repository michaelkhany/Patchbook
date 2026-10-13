# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Known OpenAI-compatible providers: base URL, where to get a key, which listed
models are chat models, and which are documented to support native tool
calling (so no probe request is spent on them). DAYA's and Patch Code's
presets, merged.
"""

from __future__ import annotations

import re

PROVIDERS = [
    {"id": "gwdg", "label": "GWDG · KISSKI / AcademicCloud", "base_url": "https://chat-ai.academiccloud.de/v1",
     "keys_url": "https://kisski.gwdg.de/leistungen/2-02-llm-service/", "key_env": "ACADEMICCLOUD_API_KEY",
     "local": False, "default": True,
     "note": "Open-weight models (Qwen, Llama, Mistral, gpt-oss, DeepSeek, GLM)."},
    {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1",
     "keys_url": "https://platform.openai.com/api-keys", "key_env": "OPENAI_API_KEY", "local": False,
     "note": "GPT models. Non-chat entries (embeddings, audio, images) are filtered out."},
    {"id": "deepseek", "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
     "keys_url": "https://platform.deepseek.com/api_keys", "key_env": "DEEPSEEK_API_KEY", "local": False,
     "note": "deepseek-chat and deepseek-reasoner, both with native tool calling."},
    {"id": "ollama", "label": "Ollama (local)", "base_url": "http://127.0.0.1:11434/v1",
     "keys_url": "", "key_env": "", "local": True, "port": 11434, "note": "Any non-empty key."},
    {"id": "lmstudio", "label": "LM Studio (local)", "base_url": "http://127.0.0.1:1234/v1",
     "keys_url": "", "key_env": "", "local": True, "port": 1234, "note": "Any non-empty key."},
    {"id": "llamacpp", "label": "llama.cpp server (local)", "base_url": "http://127.0.0.1:8089/v1",
     "keys_url": "", "key_env": "", "local": True, "port": 8089, "note": "llama-server --jinja."},
    {"id": "vllm", "label": "vLLM (local)", "base_url": "http://127.0.0.1:8000/v1",
     "keys_url": "", "key_env": "", "local": True, "port": 8000, "note": "vllm serve."},
    {"id": "custom", "label": "Custom (any OpenAI-compatible endpoint)", "base_url": "",
     "keys_url": "", "key_env": "", "local": False, "note": "A gateway or another campus service."},
]

_HOST_TO_PROVIDER = (
    ("api.openai.com", "openai"), ("api.deepseek.com", "deepseek"),
    ("academiccloud.de", "gwdg"), ("kisski", "gwdg"),
    (":11434", "ollama"), (":1234", "lmstudio"), (":8089", "llamacpp"), (":8000", "vllm"),
)

_TOOL_CAPABLE = {
    "openai": (re.compile(r"^gpt-5"), re.compile(r"^gpt-4\.1"), re.compile(r"^gpt-4o"),
               re.compile(r"^gpt-4-turbo"), re.compile(r"^o[34]"), re.compile(r"^chatgpt-4o")),
    "deepseek": (re.compile(r"^deepseek-chat$"), re.compile(r"^deepseek-reasoner$")),
}

_NON_CHAT = re.compile(
    r"(embedding|whisper|tts|audio|dall-e|image|moderation|realtime|transcribe|search-preview|codex)",
    re.IGNORECASE)

# Rough pricing in USD per 1M tokens (input, output), used only to rank hosted
# candidates by cost when the provider does not publish prices through the API.
# Provenance: public price pages as of 2026-10; uncalibrated beyond that and
# marked so in the selection explanation. A missing entry means "unknown".
PRICE_HINTS = {
    "openai": {re.compile(r"^gpt-5-nano"): (0.05, 0.4), re.compile(r"^gpt-5-mini"): (0.25, 2.0),
               re.compile(r"^gpt-5"): (1.25, 10.0), re.compile(r"^gpt-4\.1-mini"): (0.4, 1.6),
               re.compile(r"^gpt-4\.1"): (2.0, 8.0), re.compile(r"^gpt-4o-mini"): (0.15, 0.6),
               re.compile(r"^gpt-4o"): (2.5, 10.0)},
    "deepseek": {re.compile(r"^deepseek-chat$"): (0.27, 1.1), re.compile(r"^deepseek-reasoner$"): (0.55, 2.19)},
    "gwdg": {},  # flat-rate academic service; treated as free at the margin
}


def detect(base_url: str) -> str:
    host = str(base_url or "").lower()
    for needle, provider_id in _HOST_TO_PROVIDER:
        if needle in host:
            return provider_id
    return "custom"


def get(provider_id: str) -> dict | None:
    for provider in PROVIDERS:
        if provider["id"] == provider_id:
            return provider
    return None


def is_local(base_url: str) -> bool:
    host = str(base_url or "").lower()
    return any(h in host for h in ("127.0.0.1", "localhost", "0.0.0.0", "[::1]"))


def filter_models(base_url: str, models) -> list:
    if detect(base_url) != "openai":
        return list(models or [])
    return [m for m in (models or []) if not _NON_CHAT.search(str(m))]


def known_tool_support(base_url: str, model: str):
    """True when the provider documents native tool calling; None when a probe is needed."""
    patterns = _TOOL_CAPABLE.get(detect(base_url))
    if not patterns:
        return None
    name = str(model or "").strip()
    return True if any(p.search(name) for p in patterns) else None


def price_hint(base_url: str, model: str):
    table = PRICE_HINTS.get(detect(base_url))
    if table is None:
        return None
    if not table:
        return (0.0, 0.0)
    for pattern, price in table.items():
        if pattern.search(str(model or "")):
            return price
    return None


def catalog() -> list:
    return [dict(p) for p in PROVIDERS]
