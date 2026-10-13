# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Finding model sources on this machine without asking first.

Order (§7.1 of the design): explicit environment variables, config files
iTailor and its relatives write, local servers already listening on their
default ports, and local model files on disk. Each finding is a ``Source``;
``itailor.llm.select`` turns the models they expose into candidates.

Nothing here downloads, starts or installs anything.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.request
from dataclasses import dataclass, field, asdict

from . import providers
from .client import ModelConfig, OpenAICompatibleClient

ENV_BASE = ("ITAILOR_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE")
ENV_KEY = ("ITAILOR_API_KEY", "OPENAI_API_KEY")
ENV_MODEL = ("ITAILOR_MODEL", "OPENAI_MODEL")

# Provider-specific key variables that imply a provider even without a URL.
PROVIDER_KEY_ENVS = (("ACADEMICCLOUD_API_KEY", "gwdg"), ("GWDG_API_KEY", "gwdg"),
                     ("DEEPSEEK_API_KEY", "deepseek"), ("OPENAI_API_KEY", "openai"))

GGUF_DIRS = (
    os.path.join("~", ".itailor", "models"),
    os.path.join("~", ".cache", "lm-studio", "models"),
    os.path.join("~", ".lmstudio", "models"),
    os.path.join("~", "models"),
)


@dataclass
class Source:
    id: str
    kind: str                      # env | config | local-server | local-file
    base_url: str = ""
    api_key: str = ""              # the key itself, in memory only
    key_env: str = ""              # the variable it came from, for config files
    model: str = ""                # a model the source names explicitly
    provider: str = "custom"
    local: bool = False
    note: str = ""
    models: list = field(default_factory=list)
    contexts: dict = field(default_factory=dict)
    reachable: bool | None = None
    message: str = ""

    def public(self) -> dict:
        data = asdict(self)
        data["api_key"] = "[set]" if self.api_key else ""
        return data

    def config(self, model: str | None = None) -> ModelConfig:
        return ModelConfig(base_url=self.base_url, api_key=self.api_key or ("local" if self.local else ""),
                           model=model or self.model)


def _first_env(names) -> tuple[str, str]:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return name, value.strip()
    return "", ""


def from_environment() -> list[Source]:
    sources: list[Source] = []
    base_var, base = _first_env(ENV_BASE)
    key_var, key = _first_env(ENV_KEY)
    model_var, model = _first_env(ENV_MODEL)
    if base:
        sources.append(Source(id="env", kind="env", base_url=base, api_key=key, key_env=key_var,
                              model=model, provider=providers.detect(base), local=providers.is_local(base),
                              note=f"from {base_var}" + (f", {key_var}" if key_var else "")))
    for var, provider_id in PROVIDER_KEY_ENVS:
        value = os.environ.get(var)
        if not value or not value.strip():
            continue
        preset = providers.get(provider_id) or {}
        if base and providers.detect(base) == provider_id:
            continue  # already covered by the explicit base URL
        sources.append(Source(id=f"env-{provider_id}", kind="env", base_url=preset.get("base_url", ""),
                              api_key=value.strip(), key_env=var, provider=provider_id,
                              note=f"{preset.get('label', provider_id)} key found in {var}"))
    return sources


def _read_json(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def from_config_files(project: str | None = None) -> list[Source]:
    """iTailor's own config, then Patch Code's settings (same shape, different key)."""
    sources: list[Source] = []
    home = os.path.expanduser("~")
    candidates = [("itailor-user", os.path.join(home, ".itailor", "config.json"))]
    if project:
        candidates.append(("itailor-project", os.path.join(project, ".itailor", "settings.local.json")))
        candidates.append(("itailor-project-shared", os.path.join(project, ".itailor", "settings.json")))
        candidates.append(("patchcode-project", os.path.join(project, ".patchcode", "settings.local.json")))
    candidates.append(("patchcode-user", os.path.join(home, ".patchcode", "settings.json")))
    for ident, path in candidates:
        data = _read_json(path)
        if not data:
            continue
        base = str(data.get("baseUrl") or data.get("base_url") or data.get("serviceAddress") or "").strip()
        if not base:
            provider_id = data.get("provider")
            preset = providers.get(provider_id) if provider_id else None
            base = (preset or {}).get("base_url", "")
        if not base:
            continue
        key_env = str(data.get("apiKeyEnv") or data.get("api_key_env") or "").strip()
        key = os.environ.get(key_env, "").strip() if key_env else ""
        if not key:
            key = str(data.get("apiKey") or data.get("api_key") or "").strip()  # discouraged but honoured
        model = str(data.get("model") or "").strip()
        sources.append(Source(id=ident, kind="config", base_url=base, api_key=key, key_env=key_env,
                              model="" if model == "auto" else model, provider=providers.detect(base),
                              local=providers.is_local(base), note=f"from {path}"))
    return sources


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def from_local_servers(timeout: float = 1.5) -> list[Source]:
    """Servers already listening on the default ports (Ollama, LM Studio, llama.cpp, vLLM)."""
    sources: list[Source] = []
    for preset in providers.PROVIDERS:
        if not preset.get("local") or not preset.get("port"):
            continue
        if not _port_open("127.0.0.1", int(preset["port"])):
            continue
        source = Source(id=f"local-{preset['id']}", kind="local-server", base_url=preset["base_url"],
                        api_key="local", provider=preset["id"], local=True,
                        note=f"{preset['label']} is listening on port {preset['port']}")
        listed = OpenAICompatibleClient(source.config()).list_models(timeout=timeout)
        source.reachable = bool(listed.get("ok"))
        source.message = listed.get("message", "")
        source.models = list(listed.get("models") or [])
        source.contexts = dict(listed.get("contexts") or {})
        sources.append(source)
    return sources


def from_local_files() -> list[Source]:
    """GGUF weights on disk. Reported so `init` can offer to serve them; not usable as-is."""
    sources: list[Source] = []
    for pattern in GGUF_DIRS:
        root = os.path.expanduser(pattern)
        if not os.path.isdir(root):
            continue
        found = []
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if name.lower().endswith(".gguf"):
                    found.append(os.path.join(dirpath, name))
            if len(found) > 50:
                break
        if found:
            sources.append(Source(id=f"files-{os.path.basename(root) or 'models'}", kind="local-file",
                                  local=True, models=found[:50], note=f"{len(found)} GGUF file(s) under {root}"))
    return sources


def discover(project: str | None = None, *, servers: bool = True, files: bool = True) -> list[Source]:
    sources = from_environment() + from_config_files(project)
    if servers:
        sources += from_local_servers()
    if files:
        sources += from_local_files()
    # De-duplicate by base URL, keeping the first (highest-precedence) finding.
    seen: set[str] = set()
    unique: list[Source] = []
    for source in sources:
        key = source.base_url.rstrip("/").lower() or source.id
        if key in seen:
            continue
        seen.add(key)
        unique.append(source)
    return unique


def fill_models(sources: list[Source], timeout: float = 20.0) -> list[Source]:
    """List models for every usable source that has not been listed yet."""
    for source in sources:
        if source.kind == "local-file" or source.models or not source.base_url:
            continue
        if not source.api_key and not source.local:
            source.reachable = False
            source.message = "no API key"
            continue
        listed = OpenAICompatibleClient(source.config()).list_models(timeout=timeout)
        source.reachable = bool(listed.get("ok"))
        source.message = listed.get("message", "")
        source.models = providers.filter_models(source.base_url, listed.get("models") or [])
        source.contexts = dict(listed.get("contexts") or {})
    return sources


def probe_reachability(url: str, timeout: float = 3.0) -> bool:
    """One HEAD/GET to say whether an endpoint answers at all (not whether it authorises)."""
    try:
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "itailor"})
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True  # it answered
    except Exception:  # noqa: BLE001
        return False
