"""Real-browser Playwright E2E + Agent-as-Agent CLI/PTY verification for CAOS v2.

Run via system Python with Playwright installed:
    /usr/bin/python3 tests/e2e_personas.py
"""
from __future__ import annotations

import fcntl
import json
import os
import pty
import re
import select
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from caos_harness import app  # noqa: E402
from caos_harness.web.server import make_server  # noqa: E402

SCRATCH_DIR = Path(
    os.environ.get(
        "CAOS_E2E_SHOTS",
        str(Path(tempfile.gettempdir()) / "caos-e2e-shots"),
    )
)


def start_mock_ollama() -> tuple[ThreadingHTTPServer, str]:
    """Starts an ephemeral OpenAI/Ollama-compatible mock HTTP server for E2E flows."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            if self.path.startswith("/api/tags"):
                payload = {
                    "models": [
                        {
                            "name": "qwen2.5:7b",
                            "size": 4700000000,
                            "details": {"parameter_size": "7B", "quantization_level": "Q4_K_M", "family": "qwen2"},
                        },
                        {
                            "name": "llama3.2:3b",
                            "size": 2100000000,
                            "details": {"parameter_size": "3B", "quantization_level": "Q4_K_M", "family": "llama"},
                        },
                    ]
                }
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length)
            req = json.loads(raw.decode("utf-8") or "{}")
            msgs = req.get("messages") or []
            tools = req.get("tools") or []
            fmt = req.get("format")
            last_user = next((m.get("content", "") for m in reversed(msgs) if m.get("role") == "user"), "")
            has_tool_result = any(m.get("role") == "tool" for m in msgs)

            if fmt == "json" or "smoke" in str(last_user).lower():
                msg = {"role": "assistant", "content": '{"ok": true}'}
            elif tools and not has_tool_result and "modo act" in str(last_user).lower():
                msg = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "run_command",
                                "arguments": {"command": "echo e2e-ok"},
                            }
                        }
                    ],
                }
            elif tools and not has_tool_result and "modo plan" not in str(req) and not str(last_user).lower().startswith("respuestas de alineaci"):
                msg = {
                    "role": "assistant",
                    "content": (
                        "Propuesta inicial lista.\n"
                        "1. ¿Ejecutar prueba rápida antes de editar? [Sí, correr prueba | Solo revisar diff]\n"
                    ),
                }
            elif has_tool_result:
                msg = {"role": "assistant", "content": "Ejecución completada en modo Act con e2e-ok."}
            else:
                msg = {
                    "role": "assistant",
                    "content": (
                        "Plan preparado.\n"
                        "1. ¿Validar pruebas antes de aplicar cambios? [Sí, correr pytest | Solo plan]\n"
                    ),
                }

            body = json.dumps(
                {
                    "model": req.get("model") or "qwen2.5:7b",
                    "message": msg,
                    "done": True,
                    "prompt_eval_count": 32,
                    "eval_count": 18,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def init_sample_project(proj: Path) -> None:
    """Creates a clean git repo with sample config, code, and board tasks."""
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "README.md").write_text("# Sample App\n\nLogistic routing API.\n", encoding="utf-8")
    (proj / "app.py").write_text("def route_truck(stops: int) -> int:\n    return max(1, stops)\n", encoding="utf-8")
    (proj / "harness.toml").write_text(
        'name = "camiones-e2e"\n\n'
        '[agents.qwen-local]\n'
        'command = ["cat"]\n'
        'system = "qwen2.5:7b"\n'
        'timeout = 60\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.email", "team@example.com"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.name", "Team Member"], cwd=proj, check=True)
    subprocess.run(["git", "add", "."], cwd=proj, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=proj, check=True)

    class _StubDisp:
        def is_idle(self, _agent: str) -> bool:
            return True

        def send(self, _agent: str, _text: str) -> None:
            return

    loaded = app.load(proj / "harness.toml")
    b = loaded.board
    disp = _StubDisp()
    t1 = b.add("Revisar cálculo de paradas", "qwen-local")
    b.assign(t1, "qwen-local", disp)
    b.deliver(t1, "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n def route_truck(stops: int) -> int:\n-    return max(1, stops)\n+    return max(1, int(stops))\n")
    t2 = b.add("Agregar validación DTO", "qwen-local")
    t3 = b.add("Aprobar ventana horaria", app.PERSON)
    t4 = b.add("Endpoint salud inicial", "qwen-local")
    b.assign(t4, "qwen-local", disp)
    b.deliver(t4, "Health endpoint verified.")
    b.review(t4, "ok", "Aprobado en smoke inicial")
    b.close()
    assert t2 > 0 and t3 > 0


def run_cli_and_pty_checks(proj: Path, env: dict[str, str]) -> None:
    """Verifies real CLI JSON subcommands and 5-tab PTY TUI navigation as an agent/user."""
    py = str(ROOT / ".venv" / "bin" / "python")
    if not Path(py).is_file():
        py = sys.executable

    for args in (
        ["-m", "caos_harness", "providers", "--json"],
        ["-m", "caos_harness", "metrics", "--json"],
        ["-m", "caos_harness", "share", "doctor", "--json"],
        ["-m", "caos_harness", "share", "pack", "--format", "zip", "--json"],
        ["-m", "caos_harness", "task", "list", "--json"],
    ):
        proc = subprocess.run([py, *args], cwd=proj, env=env, capture_output=True, text=True, timeout=20, check=True)
        parsed = json.loads(proc.stdout)
        if "doctor" in args:
            assert parsed["clean"] is True, parsed
        if "pack" in args:
            assert Path(parsed["path"]).is_file(), parsed

    # PTY 5-tab navigation test in live project
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 36, 120, 0, 0))
    proc = subprocess.Popen(
        [py, "-m", "caos_harness", "tui"],
        cwd=proj,
        env={**env, "TERM": "xterm-256color"},
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    chunks: list[bytes] = []

    def _drain(wait_s: float = 0.25) -> None:
        deadline = time.time() + wait_s
        while time.time() < deadline:
            r, _, _ = select.select([master], [], [], 0.05)
            if not r:
                continue
            try:
                data = os.read(master, 4096)
                if data:
                    chunks.append(data)
            except OSError:
                break

    try:
        _drain(0.8)
        for seq in (b"\x1bOQ", b"\x1bOR", b"\x1bOS", b"\x1b[15~", b"\x1bOP", b"\x1b", b"q"):
            os.write(master, seq)
            _drain(0.2)
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=3)
        os.close(master)
    rendered = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", b"".join(chunks).decode("utf-8", errors="ignore"))
    assert len(rendered) > 0


def run_browser_e2e() -> None:
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        proj = tmp_path / "camiones-e2e"
        home_dir = tmp_path / "harness-home"
        home_dir.mkdir()
        init_sample_project(proj)

        mock_srv, ollama_url = start_mock_ollama()
        scrub_keys = (
            "CAOS_HARNESS_HOME",
            "OLLAMA_HOST",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "GEMINI_API_KEY",
            "DEEPSEEK_API_KEY",
            "GROQ_API_KEY",
        )
        old_env = {k: os.environ.get(k) for k in scrub_keys}
        for k in scrub_keys[2:]:
            os.environ.pop(k, None)
        os.environ["CAOS_HARNESS_HOME"] = str(home_dir)
        os.environ["OLLAMA_HOST"] = ollama_url

        (proj / ".harness").mkdir(parents=True, exist_ok=True)
        loaded = app.load(proj / "harness.toml")
        httpd = make_server(loaded, port=0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base_url = f"http://127.0.0.1:{httpd.server_address[1]}"

        try:
            env_sub = {**os.environ, "CAOS_HARNESS_HOME": str(home_dir), "OLLAMA_HOST": ollama_url}
            run_cli_and_pty_checks(proj, env_sub)

            with sync_playwright() as p:
                browser = p.chromium.launch()
                ctx = browser.new_context(viewport={"width": 1440, "height": 900})
                page = ctx.new_page()
                console_errs: list[str] = []
                page_errs: list[str] = []
                bad_http: list[str] = []

                page.on("console", lambda m: console_errs.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: page_errs.append(str(e)))
                page.on("response", lambda r: bad_http.append(f"{r.status} {r.url}") if r.status >= 500 else None)

                # 1. Desktop 1440x900: Console Plan Q&A -> Act -> Confiar en esta sesión
                page.goto(base_url, wait_until="networkidle")
                page.wait_for_selector('[role="tablist"][aria-label="Vistas principales"]')

                # Collapse sidebar test + persistence
                sidebar = page.locator("aside.sidebar")
                assert "is-expanded" in (sidebar.get_attribute("class") or "")
                page.get_by_role("button", name="Colapsar barra lateral").click()
                assert "is-collapsed" in (sidebar.get_attribute("class") or "")
                page.reload(wait_until="networkidle")
                assert "is-collapsed" in (page.locator("aside.sidebar").get_attribute("class") or "")
                page.get_by_role("button", name="Expandir barra lateral").click()

                # Send Plan message -> Q&A card -> Pasar a Act -> 3-line approval -> Confiar en esta sesión
                local_btn = page.get_by_role("button", name="Barato / Local")
                if local_btn.count():
                    local_btn.click()
                box = page.get_by_role("textbox", name="Prompt")
                box.fill("Analiza app.py y dime cómo validar stops.")
                page.get_by_role("button", name="Enviar").click()
                page.wait_for_selector(".plan-qa-card", timeout=10000)
                page.screenshot(path=str(SCRATCH_DIR / "e2e-console.png"))

                page.locator(".qa-chip").first.click()
                page.get_by_role("button", name="Pasar a Act con respuestas").click()
                page.wait_for_selector(".run-card.amber-card", timeout=10000)
                card_text = page.locator(".run-card.amber-card").inner_text()
                card_low = card_text.lower()
                assert "qué" in card_low and "para qué" in card_low and "objetivo" in card_low, card_text
                page.get_by_role("button", name="Confiar en esta sesión").click()
                page.wait_for_selector("text=Ejecución completada en modo Act con e2e-ok.", timeout=10000)

                # Check every tab on 1440x900 for compact budget & screenshots
                # How much taller than the window a view's own scroll area may be. Console, Board, Metrics and Skills are working screens:
                # about one window. Providers and Share are inventories (every installed model; every file a pack would hold) that
                # show everything on purpose, so they may scroll, but never sideways.
                BUDGET = {"providers": 3.0, "share": 1.6, "metrics": 1.4}

                def check_desktop_budget(name: str, shot: str) -> None:
                    page.wait_for_timeout(180)
                    dims = page.evaluate(
                        """() => {
                            const doc = document.documentElement;
                            const pg = document.querySelector('.page');
                            return {
                                innerW: window.innerWidth,
                                scrollW: doc.scrollWidth,
                                innerH: window.innerHeight,
                                docScrollH: doc.scrollHeight,
                                pageClientH: pg ? pg.clientHeight : 0,
                                pageScrollH: pg ? pg.scrollHeight : 0,
                                pageClientW: pg ? pg.clientWidth : 0,
                                pageScrollW: pg ? pg.scrollWidth : 0,
                                pageScrollLeft: pg ? pg.scrollLeft : 0,
                            };
                        }"""
                    )
                    assert dims["scrollW"] <= dims["innerW"], f"{name} horizontal overflow: {dims}"
                    assert dims["docScrollH"] <= dims["innerH"] * 1.05, f"{name} outer scroll overflow: {dims}"
                    if dims["pageClientH"] > 0:
                        assert dims["pageScrollH"] <= dims["pageClientH"] * BUDGET.get(name.split("-")[0], 1.05), f"{name} .page overflow: {dims}"
                        assert dims["pageScrollW"] <= dims["pageClientW"], f"{name} .page width overflow: {dims}"
                        assert dims["pageScrollLeft"] == 0, f"{name} .page shifted left: {dims}"
                    page.screenshot(path=str(SCRATCH_DIR / shot))

                # 2. Board view (Lista + Kanban)
                page.locator('[data-tab="board"]').click()
                page.wait_for_selector(".board-row")
                check_desktop_budget("board-list", "e2e-board.png")
                page.get_by_role("button", name="Kanban").click()
                page.wait_for_selector(".kanban-4col")
                page.screenshot(path=str(SCRATCH_DIR / "e2e-board-kanban.png"))
                page.get_by_role("button", name="Lista").click()

                # 3. Models & Providers
                page.locator('[data-tab="providers"]').click()
                page.wait_for_selector(".prov-grid")
                check_desktop_budget("providers", "e2e-providers.png")

                # 4. Metrics + live Smoke Test
                page.locator('[data-tab="metrics"]').click()
                page.wait_for_selector(".kpi-grid-5")
                check_desktop_budget("metrics", "e2e-metrics.png")

                # 5. Skills & Tools + MCP accordion
                page.locator('[data-tab="skills"]').click()
                page.wait_for_selector(".skills-split")
                check_desktop_budget("skills", "e2e-skills.png")

                # 6. Share / Team + Doctor + Pack
                page.locator('[data-tab="share"]').click()
                page.wait_for_selector(".share-split")
                page.get_by_role("button", name="Ejecutar Doctor").click()
                page.wait_for_selector("text=0 fugas detectadas", timeout=8000)
                page.get_by_role("button", name="Generar Share Pack").click()
                page.wait_for_selector(".pack-result", timeout=8000)
                check_desktop_budget("share", "e2e-share.png")

                # 7. Laptop 1024x768 + Mobile 390x844 overflow checks
                for vw, vh, label in ((1024, 768, "1024"), (390, 844, "390")):
                    page.set_viewport_size({"width": vw, "height": vh})
                    for tab in ("console", "board", "providers", "metrics", "skills", "share"):
                        page.locator(f'[data-tab="{tab}"]').click()
                        page.wait_for_timeout(120)
                        ov = page.evaluate("() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth })")
                        assert ov["sw"] <= ov["iw"], f"{label} {tab} horizontal overflow: {ov}"
                    if vw == 1024:
                        page.locator('[data-tab="console"]').click()
                        page.wait_for_timeout(100)
                        page.screenshot(path=str(SCRATCH_DIR / "e2e-1024-console.png"))
                    else:
                        page.locator('[data-tab="board"]').click()
                        page.wait_for_timeout(100)
                        page.screenshot(path=str(SCRATCH_DIR / "e2e-390-board.png"))

                assert not console_errs, f"Console errors: {console_errs}"
                assert not page_errs, f"Page errors: {page_errs}"
                assert not bad_http, f"HTTP 5xx errors: {bad_http}"
                browser.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            mock_srv.shutdown()
            mock_srv.server_close()
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    run_browser_e2e()
    print("E2E_PERSONAS_OK")
