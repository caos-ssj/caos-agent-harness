"""El cliente real se prueba contra un servidor HTTP local falso (sin Ollama ni red)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from caos_harness.validation.llm import OllamaClient
from caos_harness.validation.pipeline import process
from caos_harness.validation.sut import RateLimited


def serve(handler_fn):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            handler_fn(self)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def reply(h, content, code=200, headers=None):
    body = json.dumps({"message": {"content": content}}).encode()
    h.send_response(code)
    for k, v in (headers or {}).items():
        h.send_header(k, v)
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def test_good_json_is_parsed_and_classified():
    srv, url = serve(lambda h: reply(h, '{"label": "bug", "confidence": 0.9}'))
    o = process({"id": "1", "text": "La app muestra un error"}, OllamaClient(base_url=url).call)
    srv.shutdown()
    assert (o.status, o.label) == ("ok", "bug")


def test_broken_json_becomes_schema_drift_escalation():
    srv, url = serve(lambda h: reply(h, "claro, es un bug"))
    o = process({"id": "1", "text": "La app muestra un error"}, OllamaClient(base_url=url).call)
    srv.shutdown()
    assert (o.status, o.reason) == ("escalated", "schema_drift")


def test_http_429_raises_rate_limited_with_retry_after():
    srv, url = serve(lambda h: reply(h, "", 429, {"Retry-After": "2"}))
    with pytest.raises(RateLimited) as e:
        OllamaClient(base_url=url).call("hola mundo")
    srv.shutdown()
    assert e.value.retry_after == 2.0


def test_slow_server_times_out_and_pipeline_exhausts_retries():
    import time

    srv, url = serve(lambda h: (time.sleep(0.6), reply(h, '{"label":"bug","confidence":1}')))
    o = process({"id": "1", "text": "La app muestra un error"}, OllamaClient(base_url=url, timeout=0.1).call)
    srv.shutdown()
    assert (o.status, o.reason) == ("escalated", "retries_exhausted")


def test_hybrid_escalates_when_llm_and_rules_disagree():
    from caos_harness.validation.llm import HybridClient

    h = HybridClient(lambda t: {"label": "other", "confidence": 0.95})
    o = process({"id": "1", "text": "Quiero un reembolso del pago de ayer"}, h.call)
    assert (o.status, o.reason) == ("escalated", "low_confidence")


def test_hybrid_keeps_answer_when_they_agree():
    from caos_harness.validation.llm import HybridClient

    h = HybridClient(lambda t: {"label": "billing", "confidence": 0.9})
    o = process({"id": "1", "text": "Quiero un reembolso del pago de ayer"}, h.call)
    assert (o.status, o.label) == ("ok", "billing")
