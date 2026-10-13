# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
OpenAI-compatible chat client, stdlib only.

List models (with context windows), plain completions, tool-calling
completions with streaming deltas, and the one-request probe that decides
whether a model can emit native tool calls. Every call returns a ``Reply``
and never raises on transport or HTTP errors, so the agent can tell the user
the REAL reason a call failed (HTTP status + body, unreachable host, timeout).

``ChatClient`` is the protocol the rest of iTailor codes against; a
``FakeClient`` with scripted replies satisfies it for tests and the
evaluation harness.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..events import CancelToken, RunCancelled, run_cancellable

CONTEXT_WINDOW_KEYS = ("context_length", "context_window", "max_context_length",
                       "max_model_len", "max_input_tokens", "max_tokens", "max_position_embeddings")

TOOL_UNSUPPORTED_HINTS = (
    "tool-call-parser", "tool_call_parser", "tool_choice", "does not support tools",
    "tools are not supported", "tool calling is not supported", "tool use is not supported",
    "function calling is not supported", "tools is not supported",
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------
@dataclass
class ModelConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: float = 120.0
    temperature: float = 0.1
    max_tokens: int = 2400
    extra_headers: dict = field(default_factory=dict)
    extra_body: dict = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def describe(self) -> dict:
        return {"baseUrl": self.base_url, "model": self.model, "hasKey": bool(self.api_key)}


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    raw: dict | None = None


@dataclass
class Reply:
    ok: bool
    message: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    error: str = ""
    finish_reason: str | None = None
    cancelled: bool = False

    @property
    def text(self) -> str:
        content = self.message.get("content") if self.message else None
        if isinstance(content, list):  # some servers return content parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return str(content or self.message.get("reasoning_content", "") or "").strip()

    @property
    def tool_calls(self) -> list[ToolCall]:
        calls = self.message.get("tool_calls") if self.message else None
        return [parse_tool_call(call) for call in (calls or [])]


class ChatClient(Protocol):
    def chat(self, messages: list, *, tools: list | None = None, tool_choice: Any = None,
             temperature: float | None = None, max_tokens: int | None = None,
             cancel: CancelToken | None = None, on_delta: Callable[[str], None] | None = None,
             stream: bool = False) -> Reply: ...

    def describe(self) -> dict: ...


# ---------------------------------------------------------------------------
# Endpoint and error helpers
# ---------------------------------------------------------------------------
def normalize_base(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def chat_endpoint(base_url: str) -> str:
    address = normalize_base(base_url)
    if not address:
        return ""
    return address if address.endswith("/chat/completions") else address + "/chat/completions"


def models_endpoint(base_url: str) -> str:
    address = normalize_base(base_url)
    if not address:
        return ""
    if address.endswith("/chat/completions"):
        return address[: -len("/chat/completions")] + "/models"
    return address if address.endswith("/models") else address + "/models"


def extract_context_window(item: Any) -> int:
    if not isinstance(item, dict):
        return 0
    candidates = [item] + [item[k] for k in ("meta", "capabilities", "config", "details")
                           if isinstance(item.get(k), dict)]
    for source in candidates:
        for key in CONTEXT_WINDOW_KEYS:
            value = source.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
    return 0


def http_status_of(detail: str) -> int | None:
    match = re.search(r"HTTP (\d{3})", str(detail or ""))
    return int(match.group(1)) if match else None


def is_retryable(detail: str) -> bool:
    status = http_status_of(detail)
    text = str(detail or "").lower()
    return ((status is not None and status >= 500) or status == 429
            or "timed out" in text or "timeout" in text or "could not reach" in text
            or "temporarily unavailable" in text or "connection reset" in text
            or "remote end closed" in text or "connection refused" in text)


def error_kind(detail: str) -> str:
    status = http_status_of(detail)
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not-found"
    if status == 429:
        return "rate-limit"
    if is_retryable(detail):
        return "unavailable"
    return "error"


def friendly_error(detail: str, action: str = "calling the model") -> str:
    status = http_status_of(detail)
    trimmed = re.sub(r"\s+", " ", str(detail or ""))[:400]
    if status in (401, 403):
        return (f"The model API rejected the API key (HTTP {status}) while {action}. "
                f"Check the key and the base URL. {trimmed}")
    if status == 404:
        return f"The model API answered 404 while {action} - usually the base URL or model id is wrong. {trimmed}"
    if is_retryable(detail):
        return f"The model API is unavailable or overloaded ({trimmed or 'no detail'}). Try again in a moment."
    return f"The model API failed while {action}: {trimmed or 'no further detail'}"


def usage_of(data: dict) -> dict:
    usage = (data or {}).get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    return {"promptTokens": prompt, "completionTokens": completion,
            "totalTokens": int(usage.get("total_tokens") or prompt + completion), "reported": bool(usage)}


def parse_tool_call(call: Any) -> ToolCall:
    if not isinstance(call, dict):
        return ToolCall(id="", name="", args={})
    fn = call.get("function") or {}
    name = str(fn.get("name") or call.get("name") or "")
    raw = fn.get("arguments") if "arguments" in fn else call.get("arguments", "{}")
    args: dict
    if isinstance(raw, dict):
        args = raw
    else:
        try:
            parsed = json.loads(str(raw or "{}"))
            args = parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001
            args = {"__parse_error": str(raw)[:2000]}
    return ToolCall(id=str(call.get("id") or ""), name=name, args=args, raw=call)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _headers(cfg: ModelConfig, extra: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    headers.update(cfg.extra_headers or {})
    headers.update(extra or {})
    return headers


def _describe_url_error(exc: Exception) -> str:
    if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower():
        return "The request to the model API timed out"
    reason = getattr(exc, "reason", exc)
    return f"Could not reach the model API: {reason}"


def _consume_stream(response, on_delta, cancel: CancelToken | None):
    """Parse an SSE body of chat.completion.chunk events into one message."""
    message: dict = {"role": "assistant", "content": ""}
    tool_calls: dict[int, dict] = {}
    usage = {}
    finish = None
    reasoning = ""
    for raw_line in response:
        if cancel is not None and cancel.is_cancelled:
            break
        line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except Exception:  # noqa: BLE001
            continue
        if data.get("usage"):
            usage = usage_of(data)
        choices = data.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        if choice.get("finish_reason"):
            finish = choice["finish_reason"]
        delta = choice.get("delta") or choice.get("message") or {}
        content = delta.get("content")
        if isinstance(content, str) and content:
            message["content"] += content
            if on_delta:
                on_delta(content)
        if isinstance(delta.get("reasoning_content"), str):
            reasoning += delta["reasoning_content"]
        for part in delta.get("tool_calls") or []:
            index = part.get("index") if isinstance(part.get("index"), int) else len(tool_calls)
            entry = tool_calls.setdefault(index, {"id": part.get("id") or f"call_{index}",
                                                  "type": "function",
                                                  "function": {"name": "", "arguments": ""}})
            if part.get("id"):
                entry["id"] = part["id"]
            fn = part.get("function") or {}
            if fn.get("name"):
                entry["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                entry["function"]["arguments"] += fn["arguments"]
    if tool_calls:
        message["tool_calls"] = [tool_calls[k] for k in sorted(tool_calls)]
    if not message["content"] and reasoning:
        message["reasoning_content"] = reasoning
    return message, usage, finish


class OpenAICompatibleClient:
    """The real client. ``cfg`` names the endpoint, key and model."""

    def __init__(self, cfg: ModelConfig, on_usage: Callable[[dict, str], None] | None = None) -> None:
        self.cfg = cfg
        self.on_usage = on_usage

    def describe(self) -> dict:
        return self.cfg.describe()

    def _record(self, usage: dict) -> None:
        if self.on_usage and usage:
            try:
                self.on_usage(usage, self.cfg.model)
            except Exception:  # noqa: BLE001
                pass

    def chat(self, messages: list, *, tools: list | None = None, tool_choice: Any = None,
             temperature: float | None = None, max_tokens: int | None = None,
             cancel: CancelToken | None = None, on_delta: Callable[[str], None] | None = None,
             stream: bool = False, model: str | None = None, timeout: float | None = None,
             extra_body: dict | None = None) -> Reply:
        cfg = self.cfg
        endpoint = chat_endpoint(cfg.base_url)
        model = model or cfg.model
        if not endpoint or not model:
            return Reply(ok=False, error="Missing base URL or model.")
        body: dict = {"model": model, "messages": messages,
                      "temperature": cfg.temperature if temperature is None else temperature,
                      "max_tokens": max_tokens or cfg.max_tokens}
        body.update(cfg.extra_body or {})
        body.update(extra_body or {})
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
            body["parallel_tool_calls"] = False
        streaming = bool(stream and on_delta)
        if streaming:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        request = urllib.request.Request(
            endpoint, data=json.dumps(body).encode("utf-8"), method="POST",
            headers=_headers(cfg, {"Accept": "text/event-stream"} if streaming else None))
        timeout = timeout or cfg.timeout

        def call() -> Reply:
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    content_type = str(response.headers.get("content-type") or "")
                    if streaming and "text/event-stream" in content_type:
                        message, usage, finish = _consume_stream(response, on_delta, cancel)
                        if cancel is not None and cancel.is_cancelled:
                            return Reply(ok=False, error="cancelled", cancelled=True, usage=usage)
                        return Reply(ok=True, message=message, usage=usage, finish_reason=finish)
                    data = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", "replace")[:500]
                except Exception:  # noqa: BLE001
                    detail = ""
                if streaming and exc.code == 400 and re.search(r"stream", detail, re.I):
                    return self.chat(messages, tools=tools, tool_choice=tool_choice,
                                     temperature=temperature, max_tokens=max_tokens, cancel=cancel,
                                     stream=False, model=model, timeout=timeout, extra_body=extra_body)
                return Reply(ok=False, error=f"HTTP {exc.code} from the model API. {detail}".strip())
            except urllib.error.URLError as exc:
                return Reply(ok=False, error=_describe_url_error(exc))
            except Exception as exc:  # noqa: BLE001
                return Reply(ok=False, error=f"{type(exc).__name__}: {exc}")
            choices = data.get("choices") or []
            if not choices:
                return Reply(ok=False, usage=usage_of(data), error="The model returned no choices.")
            message = choices[0].get("message") or {}
            if not isinstance(message, dict):
                return Reply(ok=False, error="The model returned an invalid message shape.")
            if on_delta and isinstance(message.get("content"), str) and message["content"]:
                on_delta(message["content"])
            return Reply(ok=True, message=message, usage=usage_of(data),
                         finish_reason=choices[0].get("finish_reason"))

        try:
            reply = run_cancellable(call, cancel)
        except RunCancelled:
            return Reply(ok=False, error="cancelled", cancelled=True)
        self._record(reply.usage)
        return reply

    def chat_with_retries(self, messages: list, *, max_attempts: int = 6,
                          on_retry: Callable[[int, str], None] | None = None,
                          cancel: CancelToken | None = None, **kwargs) -> Reply:
        """Same call, retried on transient failures with exponential backoff.

        Backoff: 0.5s · 2^(attempt-1), capped at 4s (Patch Code's values).
        """
        last = Reply(ok=False, error="no attempt")
        for attempt in range(1, max(1, max_attempts) + 1):
            if cancel is not None and cancel.is_cancelled:
                return Reply(ok=False, error="cancelled", cancelled=True)
            last = self.chat(messages, cancel=cancel, **kwargs)
            if last.ok or last.cancelled or not is_retryable(last.error) or attempt >= max_attempts:
                return last
            if on_retry:
                on_retry(attempt, last.error)
            wait = min(0.5 * 2 ** (attempt - 1), 4.0)
            if cancel is not None:
                try:
                    cancel.wait(wait)
                except RunCancelled:
                    return Reply(ok=False, error="cancelled", cancelled=True)
            else:
                time.sleep(wait)
        return last

    def complete(self, messages: list, **kwargs) -> Reply:
        kwargs.pop("tools", None)
        kwargs.pop("stream", None)
        return self.chat_with_retries(messages, stream=False, **kwargs)

    def list_models(self, timeout: float = 20.0) -> dict:
        endpoint = models_endpoint(self.cfg.base_url)
        if not endpoint:
            return {"ok": False, "models": [], "contexts": {}, "message": "Base URL is empty."}
        request = urllib.request.Request(endpoint, method="GET", headers=_headers(self.cfg))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                detail = ""
            return {"ok": False, "models": [], "contexts": {},
                    "message": f"HTTP {exc.code} from the model API. {detail}".strip()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "models": [], "contexts": {}, "message": _describe_url_error(exc)}
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            items = data.get("models") if isinstance(data, dict) else []
        contexts: dict[str, int] = {}
        for item in items or []:
            if isinstance(item, str):
                contexts.setdefault(item, 0)
                continue
            if not isinstance(item, dict):
                continue
            identifier = item.get("id") or item.get("name") or item.get("model")
            if not identifier:
                continue
            window = extract_context_window(item)
            if window > 0 or str(identifier) not in contexts:
                contexts[str(identifier)] = window
        models = sorted(contexts)
        if not models:
            return {"ok": True, "models": [], "contexts": {},
                    "message": "Connection worked, but no models were returned."}
        return {"ok": True, "models": models, "contexts": contexts,
                "message": f"{len(models)} model(s) available."}

    def probe_tool_calling(self, model: str | None = None, timeout: float = 30.0) -> dict:
        """Ask the model to call one trivial tool. Only an actual model response
        decides a capability; an outage stays inconclusive."""
        reply = self.chat(
            [{"role": "system", "content": "You are checking native tool-call support. Call the provided tool."},
             {"role": "user", "content": "Call the tool with value ok."}],
            tools=[{"type": "function", "function": {
                "name": "itailor_probe", "description": "Probe whether this model can emit native tool calls.",
                "parameters": {"type": "object", "properties": {"value": {"type": "string", "description": "Return ok."}},
                               "required": ["value"], "additionalProperties": False}}}],
            tool_choice="required", temperature=0, max_tokens=64, model=model, timeout=timeout)
        if not reply.ok:
            status = http_status_of(reply.error)
            text = reply.error.lower()
            if status in (400, 422) and any(h in text for h in TOOL_UNSUPPORTED_HINTS):
                return {"verdict": "unsupported", "detail": reply.error}
            return {"verdict": "inconclusive", "detail": reply.error}
        calls = reply.tool_calls
        if len(calls) == 1 and calls[0].name == "itailor_probe":
            return {"verdict": "supported", "detail": "Native tool calling supported."}
        if len(calls) == 1:
            return {"verdict": "unsupported", "detail": f"Unexpected tool call: {calls[0].name or '(missing name)'}."}
        if len(calls) > 1:
            return {"verdict": "unsupported", "detail": "The probe returned multiple tool calls."}
        return {"verdict": "unsupported", "detail": "The probe response did not include tool_calls."}


# ---------------------------------------------------------------------------
# A scripted client for tests and the evaluation harness
# ---------------------------------------------------------------------------
class FakeClient:
    """Replies come from a script: a list of strings or dicts, or a function
    ``(messages, tools) -> str | dict``. A dict reply is a full assistant
    message (so it can carry ``tool_calls``)."""

    def __init__(self, script: list | Callable | None = None, *, native_tools: bool = True,
                 model: str = "fake-model") -> None:
        self.script = list(script) if isinstance(script, (list, tuple)) else script
        self.native_tools = native_tools
        self.model = model
        self.calls: list[dict] = []

    def describe(self) -> dict:
        return {"baseUrl": "fake://", "model": self.model, "hasKey": True}

    def _next(self, messages, tools):
        if callable(self.script):
            return self.script(messages, tools)
        if self.script:
            return self.script.pop(0)
        return "Done."

    def chat(self, messages: list, *, tools: list | None = None, tool_choice: Any = None,
             temperature: float | None = None, max_tokens: int | None = None,
             cancel: CancelToken | None = None, on_delta: Callable[[str], None] | None = None,
             stream: bool = False, **kwargs) -> Reply:
        self.calls.append({"messages": list(messages), "tools": list(tools or [])})
        item = self._next(messages, tools)
        if isinstance(item, dict):
            message = dict(item)
            message.setdefault("role", "assistant")
            message.setdefault("content", "")
        else:
            message = {"role": "assistant", "content": str(item)}
        if on_delta and message.get("content"):
            on_delta(message["content"])
        return Reply(ok=True, message=message,
                     usage={"promptTokens": 10, "completionTokens": 5, "totalTokens": 15, "reported": True})

    def chat_with_retries(self, messages: list, **kwargs) -> Reply:
        kwargs.pop("max_attempts", None)
        kwargs.pop("on_retry", None)
        return self.chat(messages, **kwargs)

    def complete(self, messages: list, **kwargs) -> Reply:
        kwargs.pop("tools", None)
        return self.chat(messages, **kwargs)

    def list_models(self, timeout: float = 20.0) -> dict:
        return {"ok": True, "models": [self.model], "contexts": {self.model: 32768}, "message": "fake"}

    def probe_tool_calling(self, model: str | None = None, timeout: float = 30.0) -> dict:
        return {"verdict": "supported" if self.native_tools else "unsupported", "detail": "fake"}


def tool_call_message(name: str, args: dict, content: str = "", call_id: str = "call_1") -> dict:
    """Build a native tool-call assistant message for a ``FakeClient`` script."""
    return {"role": "assistant", "content": content,
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)}}]}
