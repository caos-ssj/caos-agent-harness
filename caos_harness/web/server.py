"""Local dashboard for a harness project: a JSON API over the board and the static app, on loopback only.

    caos-harness serve [--port 8791]

Writes need the header `X-Harness: 1` and a loopback Host, so a page on another origin cannot post to it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import app
from ..board.core import VERDICTS
from ..router.route import choose, load_profiles, load_tiers
from ..skills import load_all
from ..engines.workstation import Run

DIST = Path(__file__).resolve().parent / "dist"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".woff2": "font/woff2",
         ".json": "application/json", ".png": "image/png", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8"}
LOOPBACK = re.compile(r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")
MAX_BODY = 64 * 1024


def app_reports() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "reports"


def task_row(r) -> dict:
    if r["status"] == "sent":
        state = r["review"] if r["review"] in ("ok", "superseded", "verify") else ("to_review" if r["result"] is not None else "sent")
    else:
        state = "person" if r["status"] == "pending" and r["queue"] == app.PERSON else r["status"]
    return {"id": r["id"], "text": r["text"], "state": state, "status": r["status"], "queue": r["queue"], "agent": r["agent"], "skill": r["skill"],
            "created": r["created"], "sent_at": r["sent_at"], "review": r["review"], "review_note": r["review_note"], "reviewed_at": r["reviewed_at"],
            "delivered": r["result"] is not None}


class Api:
    """Everything the dashboard can read or do. Kept apart from HTTP so it is tested directly."""
    def __init__(self, project: app.Project):
        self.p, self.running = project, threading.Lock()
        self.last_run: list[dict] = []
        self.runs: dict[str, Run] = {}
        self.session_lock = threading.RLock()
        self.commands_on: set[str] = set()   # sessions where the operator switched shell commands on; memory only

    def router_table(self) -> dict:
        profiles, tiers = load_profiles(), load_tiers()
        runs = {a.system: a.name for a in self.p.agents.values() if a.system}
        rows = []
        for tier, need in tiers.items():
            d = choose(profiles, need)
            rows.append({"tier": tier, "needs": need, "action": d.action, "system": d.system, "agent": runs.get(d.system) if d.system else None, "reason": d.reason})
        return {"tiers": rows, "profiles": [{"system": p.system, "measured": p.measured, "precision": p.precision, "precision_lo": p.precision_lo, "coverage": p.coverage,
                                             "seconds_per_1000": round(p.cost), "tokens_per_1000": p.tokens_per_1000} for p in profiles if p.n_answered]}

    def providers_info(self) -> dict:
        """What can actually run. Only Ollama is wired; cloud entries say whether their key is present in the environment
        and nothing else: no prices and no model lists, because none of that is measured or used here."""
        models, status = [], "offline"
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "caos-harness"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                models = [m.get("name") for m in json.loads(resp.read().decode()).get("models", [])]
                status = "online"
        except Exception:
            pass
        providers = [{"id": "ollama", "name": "Ollama (local)", "type": "local", "status": status, "wired": True, "quota": "local", "cost_per_m": "local compute",
                      "models": models, "default_model": "qwen2.5:7b" if "qwen2.5:7b" in models else (models[0] if models else ""),
                      "description": "Models served by the local Ollama service. The only provider the console and the board agents use.", "is_fallback": True}]
        for pid, name, env in (("anthropic", "Anthropic", "ANTHROPIC_API_KEY"), ("deepseek", "DeepSeek", "DEEPSEEK_API_KEY"), ("openai", "OpenAI", "OPENAI_API_KEY")):
            providers.append({"id": pid, "name": name, "type": "cloud", "status": "key_present" if os.environ.get(env) else "missing_key", "wired": False,
                              "quota": "", "cost_per_m": "not measured", "models": [], "default_model": "", "api_key_env": env,
                              "description": f"Not wired to the console. The key is read from the environment variable {env}; it is never stored by the harness."})
        for cp in self._custom_providers():
            providers.append({**cp, "wired": False, "status": "key_present" if cp.get("api_key_env") and os.environ.get(cp["api_key_env"]) else "missing_key"})
        failover = {"enabled": False, "strategy": "not_implemented", "fallback_target": "ollama", "fallback_model": "",
                    "description": "Automatic failover is not implemented. This only records which local model you would fall back to."}
        fp = self.p.root / ".harness" / "failover.json"
        if fp.is_file():
            try:
                saved = json.loads(fp.read_text(encoding="utf-8"))
                failover.update({k: saved[k] for k in ("fallback_target", "fallback_model") if isinstance(saved.get(k), str)})
            except Exception:
                pass
        return {"providers": providers, "active_failover": failover}

    def _custom_providers(self) -> list[dict]:
        """Saved custom providers, never with a key: a stored `api_key` from an older file is dropped on read."""
        f = self.p.root / ".harness" / "custom_providers.json"
        try:
            rows = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else []
        except Exception:
            rows = []
        return [{k: v for k, v in r.items() if k != "api_key"} for r in rows if isinstance(r, dict)]

    def save_custom_provider(self, cp: dict) -> dict:
        """Stores name, base URL, models and the NAME of the environment variable that holds the key. A key itself is refused."""
        if cp.get("api_key"):
            raise app.ConfigError("keys are not stored: export the key in your shell and give the variable name as api_key_env")
        env = cp.get("api_key_env")
        if env is not None and not (isinstance(env, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", env)):
            raise app.ConfigError("api_key_env must be an environment variable name, like OPENROUTER_API_KEY")
        if not isinstance(cp.get("name"), str) or not cp["name"].strip():
            raise app.ConfigError("the provider needs a name")
        clean = {"id": str(cp.get("id") or re.sub(r"[^a-z0-9]+", "-", cp["name"].lower()).strip("-")), "name": cp["name"].strip()[:80], "type": "cloud",
                 "base_url": str(cp.get("base_url") or "")[:300], "models": [str(m)[:120] for m in (cp.get("models") or [])][:40], "api_key_env": env,
                 "cost_per_m": "not measured", "quota": "", "default_model": "", "description": "Custom provider, not wired to the console."}
        f = self.p.root / ".harness" / "custom_providers.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        rows = [r for r in self._custom_providers() if r.get("id") != clean["id"]] + [clean]
        f.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")  # rewriting also purges any key an older version saved
        return clean

    def save_failover(self, fo: dict) -> dict:
        keep = {k: str(fo[k])[:120] for k in ("fallback_target", "fallback_model") if isinstance(fo.get(k), str)}
        f = self.p.root / ".harness" / "failover.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(keep, indent=2, ensure_ascii=False), encoding="utf-8")
        return {**keep, "enabled": False, "strategy": "not_implemented"}

    def repositories(self) -> list[dict]:
        """The project the server was started in. The console only runs commands there."""
        return [{"name": self.p.root.name, "path": str(self.p.root), "current": True}]

    def quality(self) -> dict:
        """Figures read from the reports the commands write; absent report, absent figure."""
        out = {}
        m = app_reports() / "validation" / "mutation.md"
        if m.is_file():
            found = re.search(r"Detectadas: \*\*(\d+)/(\d+)\*\*", m.read_text(encoding="utf-8"))
            if found:
                out["mutation"] = {"caught": int(found.group(1)), "total": int(found.group(2)), "source": "make mutation"}
        return out

    def sessions_list(self) -> list[dict]:
        sp = self.p.root / ".harness" / "sessions.json"
        if not sp.is_file():
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text("[]", encoding="utf-8")
            return []
        try:
            return json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            return []

    def session_get(self, sid: str) -> dict | None:
        mf = self.p.root / ".harness" / f"{sid}.json"
        sessions = self.sessions_list()
        meta = next((s for s in sessions if s["id"] == sid), None)
        if not meta:
            return None
        messages = []
        if mf.is_file():
            try:
                messages = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                messages = []
        active = next((r.id for r in self.runs.values() if getattr(r, "session_id", None) == sid and r.snapshot()["status"] in ("queued", "running", "awaiting_approval", "finishing")), None)
        return {**meta, "messages": messages, "active_run": active, "commands_enabled": sid in self.commands_on}

    def session_commands(self, sid: str, body: dict) -> dict:
        """Shell commands are off by default and are switched on per session, by the operator. The switch lives in the memory
        of this server process: a restart turns every session off again."""
        if type(body.get("enabled")) is not bool:
            raise app.ConfigError("enabled must be true or false")
        if not any(s["id"] == sid for s in self.sessions_list()):
            raise app.ConfigError("No such session")
        (self.commands_on.add if body["enabled"] else self.commands_on.discard)(sid)
        return {"id": sid, "commands_enabled": sid in self.commands_on}

    def session_create(self, body: dict) -> dict:
        sid = f"sess-{int(time.time() * 1000)}"
        title = body.get("title") or "New session"
        mode = body.get("mode") or "plan"
        project = body.get("project") or self.p.root.name
        new_sess = {
            "id": sid,
            "title": title,
            "project": project,
            "created_at": time.time(),
            "updated_at": time.time(),
            "mode": mode,
            "messages_count": 0
        }
        sp = self.p.root / ".harness" / "sessions.json"
        sessions = self.sessions_list()
        sessions.insert(0, new_sess)
        sp.write_text(json.dumps(sessions, indent=2, ensure_ascii=False), encoding="utf-8")
        (self.p.root / ".harness" / f"{sid}.json").write_text("[]", encoding="utf-8")
        return new_sess

    def session_delete(self, sid: str) -> bool:
        if any(getattr(r, "session_id", None) == sid and r.snapshot()["status"] in ("queued", "running", "awaiting_approval", "finishing") for r in self.runs.values()):
            raise app.ConfigError("A session with a run in progress cannot be deleted")
        sp = self.p.root / ".harness" / "sessions.json"
        sessions = [s for s in self.sessions_list() if s["id"] != sid]
        sp.write_text(json.dumps(sessions, indent=2, ensure_ascii=False), encoding="utf-8")
        mf = self.p.root / ".harness" / f"{sid}.json"
        if mf.is_file():
            mf.unlink(missing_ok=True)
        return True

    def session_add_message(self, sid: str, body: dict) -> dict:
        content = body.get("content", "").strip()
        mode = body.get("mode", "plan")
        model = body.get("model", "")
        provider = body.get("provider", "ollama")
        role = body.get("agent", "auto")
        if not content or len(content) > 20000:
            raise app.ConfigError("The message must have between 1 and 20000 characters")
        if mode not in ("plan", "act") or provider != "ollama" or not isinstance(model, str) or not model.strip():
            raise app.ConfigError("The console runs Ollama models only, in plan or act mode")
        if role != "auto" and role not in load_all():
            raise app.ConfigError("Unknown skill")
        with self.session_lock:
            session = self.session_get(sid)
            if not session:
                raise app.ConfigError("No such session")
            if mode == "act" and sid not in self.commands_on:
                raise app.ConfigError("Commands are off for this session. Turn them on for this session first; every command still needs your approval.")
            if session.get("project") != self.p.root.name:
                raise app.ConfigError("This console only runs commands in the project the server was started in")
            if any(getattr(r, "session_id", None) == sid and r.snapshot()["status"] in ("queued", "running", "awaiting_approval", "finishing") for r in self.runs.values()):
                raise app.ConfigError("This session already has a run in progress")
            history = [{"role": m["role"], "content": m["content"][:4000]} for m in session["messages"][-12:] if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and (m["role"] == "user" or m.get("run_id"))]
            run = Run(self.p.root, content, model, mode, role, history=history)
            run.session_id = sid
            self.runs[run.id] = run
            sp = self.p.root / ".harness" / "sessions.json"
            sessions = self.sessions_list()
            for item in sessions:
                if item["id"] == sid:
                    item["mode"] = mode
            sp.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")
            messages = session["messages"]
            messages.append({"id": "msg-" + run.id, "role": "user", "content": content, "timestamp": time.time()})
            mf = self.p.root / ".harness" / f"{sid}.json"
            mf.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")

        def work():
            run.execute()
            result = run.snapshot()
            with self.session_lock:
                current = self.session_get(sid)
                if current is None:
                    return
                messages = current["messages"]
                messages.append({"id": "reply-" + run.id, "role": "assistant", "content": result["answer"] or ("The run failed: " + result["error"]), "timestamp": time.time(), "model": model, "provider": "ollama", "agent": role, "tool_steps": result["steps"], "run_id": run.id})
                mf.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
                sp = self.p.root / ".harness" / "sessions.json"
                sessions = self.sessions_list()
                for item in sessions:
                    if item["id"] == sid:
                        item["updated_at"] = time.time()
                        item["messages_count"] = len(messages)
                sp.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")
            with run._lock:
                if run.status == "finishing":
                    run.status = "failed" if run.error else "completed"
        threading.Thread(target=work, daemon=True).start()
        return {"run_id": run.id}

    def run_detail(self, run_id: str) -> dict | None:
        run = self.runs.get(run_id)
        return run.snapshot() if run else None

    def run_decision(self, run_id: str, body: dict) -> dict:
        run = self.runs.get(run_id)
        if run is None:
            raise app.ConfigError("No such run")
        if type(body.get("approve")) is not bool or type(body.get("step")) is not int:
            raise app.ConfigError("Invalid decision")
        try:
            run.decide(body["step"], body["approve"])
        except ValueError as exc:
            raise app.ConfigError(str(exc)) from exc
        return run.snapshot()

    def state(self) -> dict:
        b = self.p.board
        with b.lock:
            rows = b.conn.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 400").fetchall()
            decisions = dict(b.trace.db.execute("SELECT run_id, json_extract(data,'$.tier') || '|' || COALESCE(name,'') || '|' || status FROM events WHERE source='router'").fetchall()) if b.trace else {}
        tasks = []
        for r in rows:
            t = task_row(r)
            d = decisions.get(f"task:{r['id']}")
            if d:
                tier, system, action = d.split("|")
                t["router"] = {"tier": tier, "system": system or None, "action": action}
            tasks.append(t)
        agents = [{"name": a.name, "system": a.system, "command": " ".join(a.command), "timeout": a.timeout,
                   "pending": sum(1 for t in tasks if t["queue"] == a.name and t["status"] == "pending"),
                   "working": sum(1 for t in tasks if t["agent"] == a.name and t["status"] == "sending")} for a in self.p.agents.values()]
        return {"project": self.p.root.name, "now": time.time(), "agents": agents, "tasks": tasks, "stats": b.stats(), "quality": self.quality(), "running": self.running.locked(),
                "last_run": self.last_run, "sample": (self.p.root / ".harness" / "sample").is_file(), "skills": [{"name": s.name, "description": s.description, "local": s.local} for s in load_all().values()], "tiers": list(load_tiers())}

    def task(self, tid: int) -> dict | None:
        r = self.p.board.get(tid)
        if not r:
            return None
        t = task_row(r)
        t["result"] = r["result"]
        t["timeline"] = [{k: e[k] for k in ("seq", "ts", "source", "kind", "name", "status", "reason")} for e in self.p.board.trace.timeline(f"task:{tid}")]
        return t

    def add(self, body: dict) -> dict:
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise app.ConfigError("the task needs a text")
        tid, queue, why = app.add_task(self.p, text, body.get("queue") or None, body.get("skill") or None, body.get("tier") or None)
        return {"id": tid, "queue": queue, "why": why}

    def review(self, tid: int, body: dict) -> dict:
        verdict, note = body.get("verdict"), str(body.get("note") or "").strip()
        if verdict not in VERDICTS:
            raise app.ConfigError(f"verdict must be one of {', '.join(VERDICTS)}")
        if verdict == "redo" and not note:
            raise app.ConfigError("a redo needs a note: say what to fix")
        if not self.p.board.review(tid, verdict, note):
            raise app.ConfigError(f"task {tid} is not in a state that accepts '{verdict}'")
        return {"id": tid, "verdict": verdict}

    def workspace_status(self) -> dict:
        root = self.p.root
        git_dirty = []
        branch = "main"
        try:
            r = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                git_dirty = [l.strip() for l in r.stdout.splitlines() if l.strip()]
            br = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True, timeout=2)
            if br.returncode == 0 and br.stdout.strip():
                branch = br.stdout.strip()
        except Exception:
            pass
        return {
            "repo": root.name,
            "path": str(root),
            "branch": branch,
            "dirty_files": git_dirty,
            "skills": [s.name for s in load_all().values()],
            "agents": [a.name for a in self.p.agents.values()],
            "stats": self.p.board.stats()
        }

    def discard(self, tid: int) -> dict:
        if not self.p.board.discard(tid):
            raise app.ConfigError("only a pending task can be discarded")
        return {"id": tid}

    def run(self, wait: bool = False) -> dict:
        """Sends what is pending. One run at a time; the page polls `running`."""
        if not self.running.acquire(blocking=False):
            raise app.ConfigError("a run is already in progress")

        def work():
            try:
                self.last_run = app.run_pending(self.p)
            finally:
                self.running.release()
        th = threading.Thread(target=work, daemon=True)
        th.start()
        if wait:
            th.join()
        return {"started": True}


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        server_version = "caos-harness"

        def log_message(self, *a):
            pass

        def send_json(self, code: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def guard(self, write: bool) -> bool:
            if not LOOPBACK.match(self.headers.get("Host", "")):
                self.send_json(403, {"error": "loopback only"})
                return False
            if write and self.headers.get("X-Harness") != "1":
                self.send_json(403, {"error": "missing X-Harness header"})
                return False
            return True

        def do_GET(self):
            if not self.guard(False):
                return
            path = self.path.split("?", 1)[0]
            if path == "/api/state":
                return self.send_json(200, api.state())
            if path == "/api/router":
                return self.send_json(200, api.router_table())
            if path == "/api/providers":
                return self.send_json(200, api.providers_info())
            if path == "/api/repositories":
                return self.send_json(200, api.repositories())
            if path == "/api/workspace/status":
                return self.send_json(200, api.workspace_status())
            if path == "/api/sessions":
                return self.send_json(200, api.sessions_list())
            m_run = re.fullmatch(r"/api/runs/([a-f0-9]{32})", path)
            if m_run:
                result = api.run_detail(m_run.group(1))
                return self.send_json(200, result) if result else self.send_json(404, {"error": "no such run"})
            m_sess = re.fullmatch(r"/api/sessions/([a-zA-Z0-9_-]+)", path)
            if m_sess:
                s = api.session_get(m_sess.group(1))
                return self.send_json(200, s) if s else self.send_json(404, {"error": "no such session"})
            m = re.fullmatch(r"/api/task/(\d+)", path)
            if m:
                t = api.task(int(m.group(1)))
                return self.send_json(200, t) if t else self.send_json(404, {"error": "no such task"})
            if path.startswith("/api/"):
                return self.send_json(404, {"error": "unknown endpoint"})
            f = (DIST / path.lstrip("/")).resolve() if path != "/" else DIST / "index.html"
            if not f.is_file() or DIST.resolve() not in f.parents:
                f = DIST / "index.html"  # the app routes on the client
            if not f.is_file():
                return self.send_json(503, {"error": "the dashboard is not built: run `make web`"})
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", TYPES.get(f.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if "/assets/" in path else "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if not self.guard(True):
                return
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self.send_json(413, {"error": "body too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self.send_json(400, {"error": "the body must be a JSON object"})
            path = self.path.split("?", 1)[0]
            try:
                if path == "/api/task":
                    return self.send_json(201, api.add(body))
                if path == "/api/workspace/convert_task":
                    return self.send_json(201, api.add(body))
                if path == "/api/run":
                    return self.send_json(202, api.run())
                if path == "/api/sessions":
                    return self.send_json(201, api.session_create(body))
                if path == "/api/providers":
                    return self.send_json(200, api.save_custom_provider(body))
                if path == "/api/providers/failover":
                    return self.send_json(200, api.save_failover(body))
                m_decide = re.fullmatch(r"/api/runs/([a-f0-9]{32})/decision", path)
                if m_decide:
                    return self.send_json(200, api.run_decision(m_decide.group(1), body))
                m_msg = re.fullmatch(r"/api/sessions/([a-zA-Z0-9_-]+)/messages", path)
                if m_msg:
                    return self.send_json(201, api.session_add_message(m_msg.group(1), body))
                m_cmd = re.fullmatch(r"/api/sessions/([a-zA-Z0-9_-]+)/commands", path)
                if m_cmd:
                    return self.send_json(200, api.session_commands(m_cmd.group(1), body))
                m_del = re.fullmatch(r"/api/sessions/([a-zA-Z0-9_-]+)/delete", path)
                if m_del:
                    api.session_delete(m_del.group(1))
                    return self.send_json(200, {"deleted": True})
                m = re.fullmatch(r"/api/task/(\d+)/(review|discard)", path)
                if m:
                    tid = int(m.group(1))
                    return self.send_json(200, api.review(tid, body) if m.group(2) == "review" else api.discard(tid))
            except app.ConfigError as e:
                return self.send_json(409, {"error": str(e)})
            self.send_json(404, {"error": "unknown endpoint"})
    return Handler


def make_server(project: app.Project, port: int = 8791) -> ThreadingHTTPServer:
    """The dashboard's HTTP server, bound to loopback only and not yet serving: `serve` blocks on it, the REPL runs it in a thread."""
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(Api(project)))


def serve(project: app.Project, port: int = 8791) -> int:
    httpd = make_server(project, port)
    print(f"caos-harness · {project.root.name} · http://127.0.0.1:{port}  (Ctrl-C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.server_close()
    return 0
