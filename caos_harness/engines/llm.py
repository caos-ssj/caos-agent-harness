"""Unified chat/tool-calling adapter across Ollama (any host), Anthropic and OpenAI-compatible gateways."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from .. import providers


class OllamaChat:
    """Backwards-compatible Ollama `/api/chat` client with tool-calling."""

    def __init__(self, model: str = "qwen2.5:7b", base_url: str | None = None, timeout: float = 180.0):
        self.model = model
        self.base_url = (base_url or providers.default_ollama_url()).rstrip("/")
        self.timeout = timeout
        self.latencies: list[float] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        payload: dict = {
            "model": self.model,
            "stream": False,
            "messages": messages,
            "options": {"temperature": 0, "seed": 0},
        }
        if tools:
            payload["tools"] = tools
        body = json.dumps(payload).encode()
        req = urllib.request.Request(f"{self.base_url}/api/chat", body, {"Content-Type": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = json.loads(r.read())
                msg = dict(raw.get("message") or {})
                pt = raw.get("prompt_eval_count") or 0
                ct = raw.get("eval_count") or 0
                if pt or ct:
                    msg["usage"] = {"prompt_tokens": pt, "completion_tokens": ct}
                return msg
        finally:
            self.latencies.append(time.perf_counter() - t0)


def _to_anthropic(messages: list[dict], tools: list[dict]) -> tuple[str, list[dict], list[dict]]:
    sys_parts: list[str] = []
    conv: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            if m.get("content"):
                sys_parts.append(str(m["content"]))
            continue
        if role == "tool":
            tid = m.get("tool_call_id") or m.get("tool_name") or "tool"
            block = {"type": "tool_result", "tool_use_id": tid, "content": str(m.get("content") or "")}
            if conv and conv[-1]["role"] == "user" and isinstance(conv[-1]["content"], list):
                conv[-1]["content"].append(block)
            else:
                conv.append({"role": "user", "content": [block]})
            continue
        if role == "assistant" and m.get("tool_calls"):
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": str(m["content"])})
            for idx, tc in enumerate(m["tool_calls"]):
                fn = tc.get("function") or {}
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id") or f"call_{idx}",
                    "name": fn.get("name", ""),
                    "input": args if isinstance(args, dict) else {},
                })
            conv.append({"role": "assistant", "content": blocks})
            continue
        conv.append({"role": "assistant" if role == "assistant" else "user", "content": str(m.get("content") or "")})

    ant_tools = []
    for t in tools or []:
        fn = t.get("function") or {}
        if fn.get("name"):
            ant_tools.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            })
    return "\n\n".join(sys_parts), conv or [{"role": "user", "content": "Continue."}], ant_tools


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id") or m.get("tool_name") or "call_0",
                "content": str(m.get("content") or ""),
            })
            continue
        if role == "assistant" and m.get("tool_calls"):
            tcs = []
            for idx, tc in enumerate(m["tool_calls"]):
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args or {})
                tcs.append({"id": tc.get("id") or f"call_{idx}", "type": "function", "function": {"name": fn.get("name", ""), "arguments": args}})
            out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": tcs})
            continue
        out.append({"role": role if role in ("system", "user", "assistant") else "user", "content": str(m.get("content") or "")})
    return out


class ProviderChat:
    """Executes tool-capable chat across Ollama, Anthropic, and OpenAI-compatible gateways, with optional failover."""

    def __init__(
        self,
        provider: str,
        model: str,
        base_url: str | None = None,
        key: str | None = None,
        key_env: str | None = None,
        timeout: float = 120.0,
        transport: providers.Transport = providers.http,
        root: Path | None = None,
        failover_targets: list[tuple[str, str]] | None = None,
    ):
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self._explicit_key = key
        self.key_env = key_env
        self.timeout = timeout
        self.transport = transport
        self.root = root
        self.failover_targets = failover_targets or []
        self.latencies: list[float] = []
        self.failover_used: str | None = None

    def _single_chat(self, prov: str, mod: str, messages: list[dict], tools: list[dict], base_url: str | None = None) -> dict:
        if prov == "ollama":
            url = base_url or self.base_url or providers.default_ollama_url()
            return OllamaChat(model=mod, base_url=url, timeout=self.timeout).chat(messages, tools)

        key = self._explicit_key if (prov == self.provider and self._explicit_key is not None) else None
        if key is None:
            key, _ = providers.key_for(prov, self.key_env if prov == self.provider else None, root=self.root)
        kind, chat_url, _, label = providers.endpoint_for(prov, base_url=base_url or (self.base_url if prov == self.provider else None), root=self.root)
        if not key and not chat_url.startswith("http://127.0.0.1"):
            raise providers.ProviderError(f"{label}: missing API key")

        if kind == "anthropic":
            sys_prompt, conv, ant_tools = _to_anthropic(messages, tools)
            payload: dict = {"model": mod, "max_tokens": 4096, "messages": conv}
            if sys_prompt:
                payload["system"] = sys_prompt
            if ant_tools:
                payload["tools"] = ant_tools
            status, data = self.transport(chat_url, providers._headers("anthropic", key), payload, self.timeout)
            if status != 200:
                raise providers._fail(label, status)
            text_parts = []
            tool_calls = []
            for idx, b in enumerate(data.get("content") or []):
                if b.get("type") == "text":
                    text_parts.append(str(b.get("text") or ""))
                elif b.get("type") == "tool_use":
                    tool_calls.append({
                        "id": b.get("id") or f"call_{idx}",
                        "function": {"name": b.get("name", ""), "arguments": b.get("input") or {}},
                    })
            usage_raw = data.get("usage") or {}
            msg: dict = {
                "role": "assistant",
                "content": providers.redact("".join(text_parts), key),
                "usage": {"prompt_tokens": usage_raw.get("input_tokens", 0), "completion_tokens": usage_raw.get("output_tokens", 0)},
            }
            if tool_calls:
                msg["tool_calls"] = tool_calls
            return msg

        payload = {"model": mod, "messages": _to_openai_messages(messages)}
        if tools:
            payload["tools"] = tools
        status, data = self.transport(chat_url, providers._headers("openai", key), payload, self.timeout)
        if status != 200:
            raise providers._fail(label, status)
        choice = (data.get("choices") or [{}])[0].get("message") or {}
        tool_calls = []
        for idx, tc in enumerate(choice.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            tool_calls.append({
                "id": tc.get("id") or f"call_{idx}",
                "function": {"name": fn.get("name", ""), "arguments": args if isinstance(args, dict) else {}},
            })
        usage_raw = data.get("usage") or {}
        msg = {
            "role": "assistant",
            "content": providers.redact(str(choice.get("content") or ""), key),
            "usage": {"prompt_tokens": usage_raw.get("prompt_tokens", 0), "completion_tokens": usage_raw.get("completion_tokens", 0)},
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return msg

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        t0 = time.perf_counter()
        attempts = [(self.provider, self.model)] + [t for t in self.failover_targets if t != (self.provider, self.model)]
        last_exc: Exception | None = None
        try:
            for idx, (prov, mod) in enumerate(attempts):
                try:
                    res = self._single_chat(prov, mod, messages, tools)
                    if idx > 0:
                        self.failover_used = f"{prov} · {mod}"
                        res["failover_used"] = self.failover_used
                    return res
                except Exception as exc:
                    last_exc = exc
                    continue
            assert last_exc is not None
            raise last_exc
        finally:
            self.latencies.append(time.perf_counter() - t0)
