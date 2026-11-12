"""Stability, concurrency and HTTP hardening of the control plane: sessions on disk, run bookkeeping, request limits, the board's sqlite use."""
import http.client
import json
import sqlite3
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from caos_harness import app
from caos_harness.board.core import Board
from caos_harness.web import server
from caos_harness.web.server import Api, make_handler


@pytest.fixture
def project(tmp_path):
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a") as f:
        f.write('[agents.upper]\ncommand = ["tr", "a-z", "A-Z"]\nsystem = "llama3.2:3b+rules"\n')
    return app.load(tmp_path / "harness.toml")


def wait_idle(api, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if all(r.snapshot()["status"] not in server.ACTIVE_RUN for r in list(api.runs.values())):
            return
        time.sleep(0.02)
    raise AssertionError("runs never finished: " + str([r.snapshot()["status"] for r in api.runs.values()]))


# ── sessions on disk ─────────────────────────────────────────────────────────
def test_concurrent_session_traffic_loses_no_entry_and_never_corrupts_json(project):
    api = Api(project)
    workers, barrier, errors = 8, threading.Barrier(9), []
    made: list[str] = []

    def worker(i):
        try:
            barrier.wait()
            sid = api.session_create({"title": f"s{i}"})["id"]
            made.append(sid)
            api.session_rename(sid, {"title": f"renamed {i}"})
            api.session_add_message(sid, {"content": f"hello {i}", "target_kind": "agent", "target": "upper"})
            api.sessions_list()
            api.session_get(sid)
        except Exception as exc:        # noqa: BLE001 - collected and asserted below
            errors.append(repr(exc))

    def reader():
        barrier.wait()
        for _ in range(60):
            for s in api.sessions_list():
                api.session_get(s["id"])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)] + [threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    wait_idle(api)
    sessions = json.loads((project.root / ".harness" / "sessions.json").read_text())
    assert sorted(s["id"] for s in sessions) == sorted(made) and len(set(made)) == workers
    assert {s["title"] for s in sessions} == {f"renamed {i}" for i in range(workers)}
    for s in sessions:
        msgs = json.loads((project.root / ".harness" / f"{s['id']}.json").read_text())
        assert [m["role"] for m in msgs] == ["user", "assistant"]                   # the reply landed in the right file, once
        assert s["messages_count"] == 2 and s["root"] == str(project.root.resolve())
    assert [p.name for p in (project.root / ".harness").glob("*.tmp")] == []


def test_two_creates_in_the_same_millisecond_get_distinct_ids(project, monkeypatch):
    api = Api(project)
    monkeypatch.setattr(server.time, "time", lambda: 1_700_000_000.0)
    ids = {api.session_create({})["id"] for _ in range(5)}
    assert len(ids) == 5 and len(api.sessions_list()) == 5


def test_a_failed_write_leaves_the_previous_file_and_no_temp_file(project, monkeypatch):
    api = Api(project)
    sid = api.session_create({"title": "keep me"})["id"]
    before = (project.root / ".harness" / "sessions.json").read_text()
    monkeypatch.setattr(server.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        api.session_rename(sid, {"title": "lost"})
    monkeypatch.undo()
    assert (project.root / ".harness" / "sessions.json").read_text() == before
    assert list((project.root / ".harness").glob("*.tmp")) == []


def test_a_message_is_checked_against_the_project_path_not_only_its_name(project):
    api = Api(project)
    msg = {"content": "hi", "target_kind": "agent", "target": "upper"}
    sid = api.session_create({})["id"]
    sp = project.root / ".harness" / "sessions.json"

    def set_session(**kw):
        rows = json.loads(sp.read_text())
        rows[0].update(kw)
        sp.write_text(json.dumps(rows))

    set_session(root="/somewhere/else/" + project.root.name)             # same folder name, another place
    with pytest.raises(app.ConfigError, match="only runs commands in the project"):
        api.session_add_message(sid, msg)
    rows = json.loads(sp.read_text())
    del rows[0]["root"]                                                  # an older session: only the name is known
    rows[0]["project"] = "other-name"
    sp.write_text(json.dumps(rows))
    with pytest.raises(app.ConfigError, match="only runs commands in the project"):
        api.session_add_message(sid, msg)
    set_session(project=project.root.name)
    assert api.session_add_message(sid, msg)["run_id"]
    wait_idle(api)


def test_a_model_name_must_look_like_one(project):
    api = Api(project)
    sid = api.session_create({})["id"]
    with pytest.raises(app.ConfigError, match="valid model name"):
        api.session_add_message(sid, {"content": "hi", "target_kind": "model", "target": "bad model; rm -rf /", "mode": "plan"})


def test_a_run_whose_reply_cannot_be_saved_still_leaves_the_in_progress_states(project, monkeypatch):
    api = Api(project)
    sid = api.session_create({})["id"]
    gate = threading.Event()
    monkeypatch.setattr(app, "run_task", lambda p, tid: (gate.wait(5), {"ok": True, "result": "done"})[1])
    rid = api.session_add_message(sid, {"content": "hi", "target_kind": "agent", "target": "upper"})["run_id"]
    monkeypatch.setattr(Api, "_write_json", staticmethod(lambda path, obj: (_ for _ in ()).throw(OSError("disk full"))))
    gate.set()
    end = time.monotonic() + 10
    while api.run_detail(rid)["status"] in server.ACTIVE_RUN and time.monotonic() < end:
        time.sleep(0.02)
    snap = api.run_detail(rid)
    assert snap["status"] == "failed" and "could not save the reply" in snap["error"]


# ── run bookkeeping ──────────────────────────────────────────────────────────
class Stub:
    def __init__(self, status, sid=None):
        self.status, self.session_id = status, sid

    def snapshot(self):
        return {"status": self.status}


def test_finished_runs_are_bounded_and_active_ones_are_never_dropped(project, monkeypatch):
    api = Api(project)
    monkeypatch.setattr(server, "MAX_FINISHED_RUNS", 5)
    for i in range(12):
        api.runs[f"done{i}"] = Stub("completed")
        if i % 4 == 0:
            api.runs[f"live{i}"] = Stub("awaiting_approval", "s")
    api._evict_runs()
    assert [k for k in api.runs if k.startswith("done")] == [f"done{i}" for i in range(7, 12)]   # the newest five
    assert sorted(k for k in api.runs if k.startswith("live")) == ["live0", "live4", "live8"]


def test_many_real_messages_keep_the_run_table_bounded(project, monkeypatch):
    api = Api(project)
    monkeypatch.setattr(server, "MAX_FINISHED_RUNS", 4)
    sid = api.session_create({})["id"]
    for i in range(14):
        rid = api.session_add_message(sid, {"content": f"msg {i}", "target_kind": "agent", "target": "upper"})["run_id"]
        wait_idle(api)
        assert api.run_detail(rid) is not None                           # the run just made can always be looked at
    assert len(api.runs) <= 4 + 1


# ── HTTP ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def raw(project):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Api(project)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    def request(method, path, body=b"", headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            c.putrequest(method, path)
            for k, v in {"X-Harness": "1", **(headers or {})}.items():
                c.putheader(k, v)
            c.endheaders(body)
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()
    yield request
    srv.shutdown()
    srv.server_close()


@pytest.mark.parametrize("value,code", [("abc", 400), ("-5", 400), ("1_0", 400), ("12.5", 400), ("²", 400), (str(server.MAX_BODY + 1), 413)])
def test_a_bad_content_length_gets_a_clean_json_error(raw, value, code):
    status, headers, body = raw("POST", "/api/task", b"", {"Content-Length": value})
    assert status == code and "error" in json.loads(body)
    assert "Traceback" not in body.decode()


def test_a_good_body_still_works_and_an_empty_one_is_an_empty_object(raw):
    payload = json.dumps({"text": "x task", "queue": "upper"}).encode()
    status, _, body = raw("POST", "/api/task", payload, {"Content-Length": str(len(payload))})
    assert status == 201 and json.loads(body)["queue"] == "upper"
    status, _, body = raw("POST", "/api/task", b"", {"Content-Length": "0"})
    assert status == 409 and json.loads(body) == {"error": "the task needs a text"}


@pytest.mark.parametrize("path", ["/api/state", "/", "/index.html", "/api/nope", "/..%2f..%2fharness.toml"])
def test_every_answer_carries_the_defensive_headers(raw, path):
    status, headers, _ = raw("GET", path)
    h = {k.lower(): v for k, v in headers.items()}
    assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer" and h["x-frame-options"] == "DENY"
    assert "default-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]


def test_the_csp_admits_the_built_app_and_the_sandboxed_preview_frame():
    html = (server.DIST / "index.html").read_text()
    assert "<script>" not in html and "onclick=" not in html            # no inline script: `script-src 'self'` is enough
    assert "script-src 'self'" in server.CSP and "frame-src about:" in server.CSP and "img-src 'self' data:" in server.CSP


def test_an_unexpected_error_is_a_clean_500_without_a_traceback(project, monkeypatch):
    api = Api(project)
    monkeypatch.setattr(api, "state", lambda: 1 / 0)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
        c.request("GET", "/api/state")
        r = c.getresponse()
        assert r.status == 500 and json.loads(r.read()) == {"error": "internal error"}
    finally:
        srv.shutdown()
        srv.server_close()


# ── the board ────────────────────────────────────────────────────────────────
def test_two_connections_on_one_file_write_concurrently_without_database_is_locked(tmp_path):
    path = tmp_path / "board.db"
    boards = [Board(path), Board(path)]                               # the server and a CLI process, as far as sqlite can tell
    errors = []

    def writer(b, tag):
        try:
            for i in range(40):
                tid = b.add(f"{tag} task {i}", queue="q")
                b.discard(tid)
        except Exception as exc:        # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=writer, args=(boards[i % 2], f"w{i}")) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    assert len(boards[0].rows()) == 160 and boards[1].stats()["by_status"] == {"discarded": 160}
    for b in boards:
        b.close()
    with pytest.raises(sqlite3.ProgrammingError):
        boards[0].conn.execute("select 1")


def test_a_write_that_fails_half_way_is_rolled_back_and_releases_the_file(tmp_path):
    class Broken:
        def event(self, *a, **k):
            raise RuntimeError("trace down")
    path = tmp_path / "board.db"
    b = Board(path, trace=Broken())
    with pytest.raises(RuntimeError):
        b.add("half written task")
    assert b.rows() == []                                              # the insert did not survive
    other = sqlite3.connect(path, timeout=0.3)                         # and no transaction is left holding the write lock
    other.execute("INSERT INTO tasks (text, created) VALUES ('from elsewhere', 1)")
    other.commit()
    other.close()
    assert [r["text"] for r in b.rows()] == ["from elsewhere"]


def test_the_project_opens_one_board_even_when_threads_ask_together(project):
    barrier, seen = threading.Barrier(8), []

    def ask():
        barrier.wait()
        seen.append(id(project.board))
    threads = [threading.Thread(target=ask) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(seen)) == 1


# ── "waiting for you": one definition for the web, the TUI and the REPL ──────
def test_waiting_for_you_counts_the_same_in_the_web_state_and_the_summary(project):
    api = Api(project)
    b = project.board
    app.add_task(project, "a human decides", queue="person")
    delivered = app.add_task(project, "hello", queue="upper")[0]
    verify = app.add_task(project, "check it", queue="upper")[0]
    pending = app.add_task(project, "still pending", queue="upper")[0]
    app.run_pending(project, only="upper")
    assert b.review(verify, "verify", "look again")
    assert b.review(pending, "ok")                                       # closed: must not count
    state = api.state()
    from_tasks = sum(t["state"] in ("to_review", "verify", "person") for t in state["tasks"])
    assert state["summary"]["needs_you"] == from_tasks == app.summary(project)["needs_you"]
    assert state["summary"]["with_person"] == 1 and state["summary"]["needs_you"] == 3   # person + delivered + verify
