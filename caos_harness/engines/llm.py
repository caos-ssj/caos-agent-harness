"""Cliente de llamadas a funciones sobre Ollama (/api/chat con `tools`)."""
from __future__ import annotations

import json
import time
import urllib.request


class OllamaChat:
    def __init__(self, model="qwen2.5:7b", base_url="http://127.0.0.1:11434", timeout=180.0):
        self.model, self.base_url, self.timeout = model, base_url.rstrip("/"), timeout
        self.latencies: list[float] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        body = json.dumps({"model": self.model, "stream": False, "messages": messages, "tools": tools,
                           "options": {"temperature": 0, "seed": 0}}).encode()
        req = urllib.request.Request(f"{self.base_url}/api/chat", body, {"Content-Type": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())["message"]
        finally:
            self.latencies.append(time.perf_counter() - t0)
