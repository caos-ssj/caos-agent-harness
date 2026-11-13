import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from caos_harness import app, desktop
from caos_harness.web.server import make_server


def _req(url: str, method: str = "GET", headers: dict | None = None, body: bytes | None = None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_ensure_user_path_appends_existing_bins_without_duplicates(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    local_bin = fake_home / ".local" / "bin"
    cargo_bin = fake_home / ".cargo" / "bin"
    nvm_bin = fake_home / ".nvm" / "versions" / "node" / "v22.0.0" / "bin"
    for d in (local_bin, cargo_bin, nvm_bin):
        d.mkdir(parents=True)
    monkeypatch.setenv("PATH", f"{local_bin}{os.pathsep}/usr/bin")

    merged = desktop.ensure_user_path(home=fake_home).split(os.pathsep)
    assert merged.count(str(local_bin)) == 1
    assert str(cargo_bin) in merged
    assert str(nvm_bin) in merged


def test_resolve_desktop_project_uses_last_workspace_then_default_fallback(tmp_path, monkeypatch):
    empty_cwd = tmp_path / "outside"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    # First launch outside any workspace creates/loads the default desktop workspace.
    proj_default = desktop.resolve_desktop_project()
    assert (proj_default.root / app.CONFIG).is_file()

    # Switching or opening an explicit workspace remembers it as last active.
    real_ws = tmp_path / "real-repo"
    real_ws.mkdir()
    app.init(real_ws)
    proj_explicit = desktop.resolve_desktop_project(str(real_ws))
    assert proj_explicit.root == real_ws.resolve()

    # Launching again from outside any repo restores `real-repo` automatically.
    proj_restored = desktop.resolve_desktop_project()
    assert proj_restored.root == real_ws.resolve()


def test_desktop_server_token_cors_sse_and_ephemeral_port(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    app.init(ws)
    proj = app.load(ws / app.CONFIG)
    tok = "caos-desktop-secret-123"
    srv = make_server(proj, port=0, token=tok, desktop_mode=True)
    port = srv.server_address[1]
    assert port > 0
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        base = f"http://127.0.0.1:{port}"
        assert json.loads(desktop.format_ready_line(port).split(" ", 1)[1])["port"] == port

        # Missing or wrong token on /api/ is rejected with 401.
        st, _, _ = _req(f"{base}/api/state")
        assert st == 401
        st, _, _ = _req(f"{base}/api/state", headers={"X-Harness-Token": "wrong"})
        assert st == 401

        # Valid X-Harness-Token or Bearer succeeds.
        st, _, body = _req(f"{base}/api/state", headers={"X-Harness-Token": tok})
        assert st == 200 and json.loads(body)["project"] == "ws"
        st, _, _ = _req(f"{base}/api/state", headers={"Authorization": f"Bearer {tok}"})
        assert st == 200

        # CORS preflight: allow Tauri origin, block unknown origin.
        st, hdrs, _ = _req(f"{base}/api/state", method="OPTIONS", headers={"Origin": "http://tauri.localhost"})
        assert st == 204 and hdrs.get("Access-Control-Allow-Origin") == "http://tauri.localhost"
        st, _, _ = _req(f"{base}/api/state", method="OPTIONS", headers={"Origin": "https://evil.example"})
        assert st == 403
        st, _, _ = _req(f"{base}/api/state", headers={"Origin": "https://evil.example", "X-Harness-Token": tok})
        assert st == 403

        # Mutating POST requires both X-Harness: 1 and token.
        st, _, _ = _req(f"{base}/api/workspaces", method="POST", headers={"X-Harness-Token": tok}, body=b"{}")
        assert st == 403
        st, _, _ = _req(
            f"{base}/api/workspaces",
            method="POST",
            headers={"X-Harness": "1", "X-Harness-Token": tok, "Origin": "http://tauri.localhost"},
            body=json.dumps({"path": str(ws)}).encode(),
        )
        assert st == 200

        # SSE /api/events authenticates cleanly via query ?token=.
        req = urllib.request.Request(f"{base}/api/events?token={tok}")
        with urllib.request.urlopen(req, timeout=4) as resp:
            assert resp.status == 200
            assert "text/event-stream" in (resp.headers.get("Content-Type") or "")
            first_line = resp.readline().decode()
            assert first_line.startswith("event: change")
    finally:
        srv.shutdown()
        srv.server_close()


def test_watch_parent_exits_when_the_launcher_disappears(monkeypatch):
    import signal as _signal
    killed = []
    parents = iter([4242, 4242, 1])
    monkeypatch.setattr(desktop.os, "getppid", lambda: next(parents))
    monkeypatch.setattr(desktop.os, "kill", lambda pid, sig: killed.append(sig))
    t = desktop.watch_parent(interval=0.01)
    t.join(2)
    assert killed == [_signal.SIGTERM]


def test_api_shutdown_cancels_only_active_runs(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    app.init(ws)
    httpd = make_server(app.load(ws / app.CONFIG))
    try:
        class R:
            def __init__(self, status):
                self.status, self.cancelled = status, False
            def snapshot(self):
                return {"status": self.status}
            def cancel(self):
                self.cancelled = True
        live, done = R("running"), R("completed")
        httpd.api.runs.update({"a": live, "b": done})
        httpd.api.shutdown()
        assert live.cancelled and not done.cancelled
    finally:
        httpd.server_close()
