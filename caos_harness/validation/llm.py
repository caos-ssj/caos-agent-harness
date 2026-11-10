"""Cliente real: clasifica con un modelo local de Ollama (por defecto llama3.2:3b, salida JSON).

Traduce los fallos de red/HTTP a las excepciones que entiende el pipeline:
  tiempo agotado -> TimeoutError, HTTP 429 -> RateLimited, JSON roto -> dict sin 'label' (cambio de esquema).
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

from .sut import RateLimited

PROMPT = (
    "Clasifica el ticket de soporte en una sola categoría: billing (facturas, cobros, pagos, reembolsos), "
    "bug (errores o fallos de la app), access (contraseña, login, cuenta bloqueada) u other (todo lo demás). "
    'Responde SOLO un JSON con esta forma: {"label": "billing|bug|access|other", "confidence": 0.0-1.0}. '
    "confidence es tu certeza entre 0 y 1."
)


class OllamaClient:
    def __init__(self, model: str = "llama3.2:3b", base_url: str = "http://127.0.0.1:11434", timeout: float = 30.0):
        self.model, self.base_url, self.timeout = model, base_url.rstrip("/"), timeout
        self.calls = 0
        self.latencies: list[float] = []
        self.tokens_in = self.tokens_out = 0  # lo que cuenta Ollama: prompt_eval_count y eval_count

    def call(self, text: str) -> dict:
        self.calls += 1
        t0 = time.perf_counter()
        try:
            return self._call(text)
        finally:
            self.latencies.append(time.perf_counter() - t0)

    def _call(self, text: str) -> dict:
        body = json.dumps({
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "seed": 0},
            "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}],
        }).encode()
        req = urllib.request.Request(f"{self.base_url}/api/chat", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise RateLimited(float(e.headers.get("Retry-After", 1)))
            raise
        except (socket.timeout, TimeoutError):
            raise TimeoutError("ollama timeout")
        except urllib.error.URLError as e:
            if isinstance(e.reason, (socket.timeout, TimeoutError)):
                raise TimeoutError("ollama timeout")
            raise
        self.tokens_in += int(data.get("prompt_eval_count") or 0)
        self.tokens_out += int(data.get("eval_count") or 0)
        content = data.get("message", {}).get("content", "")
        try:
            out = json.loads(content)
        except json.JSONDecodeError:
            return {"raw": content[:200]}
        if not isinstance(out, dict):
            return {"raw": content[:200]}
        try:
            if "confidence" in out:
                out["confidence"] = float(out["confidence"])
        except (TypeError, ValueError):
            out.pop("confidence", None)
        return out


class HybridClient:
    """LLM + reglas: si no coinciden, la confianza baja y el pipeline escala a una persona.

    Motivo: la confianza que declara el propio modelo no está calibrada (ver README).
    Dos señales independientes que discrepan son una señal mejor de «duda».
    """

    def __init__(self, llm_call, rules_call=None, disagree_conf: float = 0.4):
        from .sut import classify
        self.llm_call, self.rules_call = llm_call, rules_call or classify
        self.disagree_conf = disagree_conf
        self.model = getattr(getattr(llm_call, "__self__", None), "model", "llm") + "+rules"

    def call(self, text: str) -> dict:
        out = self.llm_call(text)
        if "label" not in out or "confidence" not in out:
            return out  # el pipeline lo escala como cambio de esquema
        rules = self.rules_call(text)
        if rules["label"] != out["label"] and rules["confidence"] >= 0.5:
            return {"label": out["label"], "confidence": min(out["confidence"], self.disagree_conf)}
        return out
