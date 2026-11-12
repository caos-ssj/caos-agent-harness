"""Local dashboard for a harness project: a JSON API over the board and the static app, on loopback only.

    caos-harness serve [--port 8791]

Writes need the header `X-Harness: 1` and a loopback Host, so a page on another origin cannot post to it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import activity, app, chat, orchestrator, providers, workspaces, worktrees
from ..board.core import VERDICTS
from ..engines.workstation import Run
from ..router.route import choose, load_profiles, load_tiers
from ..skills import load_all
from . import team_ops
from .events import EventBus

DIST = Path(__file__).resolve().parent / "dist"
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".json": "application/json",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".zip": "application/zip",
}
LOOPBACK = re.compile(r"^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")
MAX_BODY = 64 * 1024
ACTIVE_RUN = ("queued", "running", "awaiting_approval", "finishing")
TERMINAL_RUN = ("completed", "failed", "stopped")
HEARTBEAT = 12.0   # seconds of silence after which an event stream sends a comment line, so a dead client is noticed
MAX_FINISHED_RUNS = 100
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
    "frame-src about:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def app_reports() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "reports"


def task_row(r) -> dict:
    if r["status"] == "sent":
        state = r["review"] if r["review"] in ("ok", "superseded", "verify") else ("to_review" if r["result"] is not None else "sent")
    else:
        state = "person" if r["status"] == "pending" and r["queue"] == app.PERSON else r["status"]
    return {
        "id": r["id"],
        "text": r["text"],
        "state": state,
        "status": r["status"],
        "queue": r["queue"],
        "agent": r["agent"],
        "skill": r["skill"],
        "created": r["created"],
        "sent_at": r["sent_at"],
        "review": r["review"],
        "review_note": r["review_note"],
        "reviewed_at": r["reviewed_at"],
        "delivered": r["result"] is not None,
        "parent_id": r["parent_id"],
        "criteria": r["criteria"],
        "worktree_key": r["worktree_key"],
    }


class TaskRun:
    """Tracks a console-originated agent or router execution backed by a real Board task."""

    def __init__(self, project: app.Project, task_id: int, queue: str, reason: str, target_kind: str, target: str, role: str):
        self.id = uuid.uuid4().hex
        self.project = project
        self.task_id = task_id
        self.queue = queue
        self.reason = reason
        self.target_kind = target_kind
        self.target = target
        self.role = role
        self.status = "queued"
        self.steps: list[dict] = [{"name": f"Task #{task_id:02d} -> {queue}", "kind": "skill" if role != "auto" else "read", "status": "running", "input": reason}]
        self.answer = ""
        self.error = ""
        self._cancelled = False
        self._lock = threading.RLock()
        self.session_id: str | None = None
        self.worktree: dict | None = None
        self.trusted: set[str] = set()
        self.on_change = None

    def _changed(self) -> None:
        cb = self.on_change
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def snapshot(self) -> dict:
        with self._lock:
            a = self.project.agents.get(self.queue)
            return {
                "id": self.id,
                "status": self.status,
                "model": (a.model or a.system or self.queue) if a else self.target,
                "provider": (a.provider or self.target_kind) if a else self.target_kind,
                "target_kind": self.target_kind,
                "target": self.target,
                "task_id": self.task_id,
                "queue": self.queue,
                "workspace": str(self.project.root),
                "steps": [dict(s) for s in self.steps],
                "answer": self.answer,
                "error": self.error,
                "cancelled": self._cancelled,
            }

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            if self.status in ("queued", "running"):
                self.status = "stopped"
                self.answer = "Stopped waiting. Any already dispatched task keeps its trace on the Board."
                self.steps[-1]["status"] = "denied"
            self._changed()

    def execute(self) -> None:
        with self._lock:
            if self._cancelled:
                return
            self.status = "running"
            self._changed()
        t0 = time.monotonic()
        if self.queue == app.PERSON:
            with self._lock:
                self.steps[-1]["status"] = "awaiting_approval"
                self.steps[-1]["output"] = self.reason
                self.answer = f"Routed to a person as Task #{self.task_id:02d}: {self.reason}."
                self.status = "finishing"
                self._changed()
            return
        try:
            res = app.run_task(self.project, self.task_id)
            dur = round((time.monotonic() - t0) * 1000)
            with self._lock:
                if self._cancelled:
                    return
                self.steps[-1]["duration_ms"] = dur
                if res.get("person"):
                    self.steps[-1]["status"] = "awaiting_approval"
                    self.answer = f"Task #{self.task_id:02d} requires human review on the Board."
                elif res.get("ok"):
                    self.steps[-1]["status"] = "completed"
                    self.steps[-1]["output"] = (res.get("result") or "")[:4000]
                    self.answer = res.get("result") or "(the agent returned no output)"
                else:
                    self.steps[-1]["status"] = "failed"
                    self.steps[-1]["output"] = res.get("reason") or "dispatch failed"
                    self.error = res.get("reason") or "dispatch failed"
                self.status = "finishing"
                self._changed()
        except Exception as exc:
            with self._lock:
                if not self._cancelled:
                    self.steps[-1]["status"] = "failed"
                    self.error = f"{type(exc).__name__}: {str(exc)[:300]}"
                    self.status = "finishing"
                    self._changed()


class Api:
    """Everything the dashboard can read or do. Kept apart from HTTP so it is tested directly."""

    def __init__(self, project: app.Project):
        self.p, self.running = project, threading.Lock()
        self.last_run: list[dict] = []
        self.runs: dict[str, Run] = {}
        self.session_lock = threading.RLock()
        self.transport = providers.http
        self.commands_on: set[str] = set()
        self.trusted_by_session: dict[str, set[str]] = {}
        self.bus = EventBus()
        self.orch_factory = None   # tests give the orchestrator a dispatcher with a fake runner
        self._watch_board()

    def _watch_board(self) -> None:
        """Every committed write to the board wakes the event streams."""
        self.p.board.on_change = lambda: self.bus.publish("board")

    def _changed(self, *channels: str) -> None:
        for c in channels:
            self.bus.publish(c)

    def _watch_run(self, run) -> None:
        def cb():
            self.bus.publish("run:" + run.id)
            self.bus.publish("runs")
        run.on_change = cb

    def router_table(self) -> dict:
        profiles, tiers = load_profiles(), load_tiers()
        runs = {a.system: a.name for a in self.p.agents.values() if a.system}
        demotions = team_ops.metrics.load_demotions(self.p.root)
        rows = []
        for tier, need in tiers.items():
            eligible = [p for p in profiles if not (demotions.get(p.system) or {}).get("demoted")] or profiles
            d = choose(eligible, need)
            rows.append({"tier": tier, "needs": need, "action": d.action, "system": d.system, "agent": runs.get(d.system) if d.system else None, "reason": d.reason})
        return {
            "tiers": rows,
            "profiles": [
                {
                    "system": p.system,
                    "measured": p.measured,
                    "precision": p.precision,
                    "precision_lo": p.precision_lo,
                    "precision_hi": p.precision_hi,
                    "n": p.n_answered,
                    "coverage": p.coverage,
                    "seconds_per_1000": round(p.cost),
                    "tokens_per_1000": p.tokens_per_1000,
                    "demoted": bool((demotions.get(p.system) or {}).get("demoted")),
                }
                for p in profiles
                if p.n_answered
            ],
        }

    def providers_info(self, profile: str | None = None) -> dict:
        return team_ops.providers_payload(self.p, self.transport, profile)

    def provider_test(self, body: dict) -> dict:
        return team_ops.provider_test(self.p, body, self.transport)

    def provider_smoke(self, body: dict) -> dict:
        return team_ops.provider_smoke(self.p, body, self.transport)

    def provider_save_key(self, body: dict) -> dict:
        return team_ops.provider_save_key(self.p, body)

    def save_ollama_host(self, body: dict) -> dict:
        return team_ops.save_ollama_host(self.p, body)

    def save_intent_override(self, body: dict) -> dict:
        return team_ops.save_intent_override(self.p, body)

    def add_agent(self, body: dict) -> dict:
        kind = body.get("kind")
        cfg = self.p.root / app.CONFIG
        name = str(body.get("name") or "").strip().lower()
        if kind == "cli":
            cid = body.get("id")
            if cid not in providers.CLIS:
                raise app.ConfigError("unknown CLI: " + ", ".join(providers.CLIS))
            if not providers.detect_clis()[list(providers.CLIS).index(cid)]["installed"]:
                raise app.ConfigError(f"{providers.CLIS[cid]['bin']} is not installed here")
            name = name or cid
            model = body.get("model")
            try:
                command = providers.cli_command(cid, model if isinstance(model, str) and model.strip() else None)
            except ValueError as e:
                raise app.ConfigError(str(e)) from e
            block = providers.agent_block(name, command=command, timeout=providers.CLIS[cid]["timeout"])
        elif kind == "api":
            pid, model = body.get("provider"), body.get("model")
            if pid not in providers.API or not isinstance(model, str) or not providers.MODEL.fullmatch(model):
                raise app.ConfigError("give a configured API provider and a model name")
            name = name or f"{pid}-{re.sub(r'[^a-z0-9]+', '-', model.lower()).strip('-')}"[:32]
            block = providers.agent_block(name, provider=pid, model=model, timeout=300)
        else:
            raise app.ConfigError("kind must be cli or api")
        if not providers.NAME.fullmatch(name) or name == app.PERSON or name in self.p.agents:
            raise app.ConfigError(f"the agent name '{name}' is taken or not valid (lowercase letters, digits, - and _)")
        if cfg.is_symlink() or cfg.resolve().parent != self.p.root.resolve():
            raise app.ConfigError("harness.toml must be a plain file inside the project folder to be edited from here")
        for v in (name, str(body.get("model") or "")):
            if providers.looks_like_secret(v):
                raise app.ConfigError("that looks like a key: only names go in harness.toml")
        before = cfg.read_text(encoding="utf-8")
        self._write_text(cfg, before.rstrip("\n") + "\n" + block)
        try:
            fresh = app.load(cfg)
        except app.ConfigError:
            self._write_text(cfg, before)
            raise
        self.p.agents.update(fresh.agents)
        return {"name": name, "agents": list(self.p.agents)}

    def save_custom_provider(self, cp: dict) -> dict:
        return team_ops.save_provider_entry(self.p, cp)

    def save_failover(self, fo: dict) -> dict:
        return team_ops.save_failover_cfg(self.p, fo)

    def workspaces(self) -> dict:
        return {"current": str(self.p.root), "items": workspaces.listing(self.p.root)}

    def workspace_add(self, body: dict) -> dict:
        workspaces.register(body.get("path"), bool(body.get("initialize")))
        return self.workspaces()

    def workspace_remove(self, body: dict) -> dict:
        target = workspaces.check(body.get("path"))
        if target == self.p.root:
            raise app.ConfigError("this is the workspace in use; switch to another one first")
        workspaces.forget(str(target))
        return self.workspaces()

    def workspace_switch(self, body: dict) -> dict:
        target = workspaces.check(body.get("path"))
        if str(target) not in workspaces.registered() and target != self.p.root:
            raise app.ConfigError("that folder is not in the list: add it first")
        with self.session_lock:
            if self.running.locked() or any(r.snapshot()["status"] in ACTIVE_RUN for r in list(self.runs.values())):
                raise app.ConfigError("something is running here; wait for it to finish before switching")
            project = app.load(target / app.CONFIG)
            workspaces.remember(self.p.root)
            self.p, self.last_run = project, []
            self.commands_on.clear()
            self.trusted_by_session.clear()
            self._watch_board()
        self._changed("board", "runs", "sessions")
        return self.workspaces()

    def repositories(self) -> list[dict]:
        """The project the server was started in. Console shell execution stays strictly here."""
        return [{"name": self.p.root.name, "path": str(self.p.root), "current": True}]

    def quality(self) -> dict:
        out = {}
        m = app_reports() / "validation" / "mutation.md"
        if m.is_file():
            found = re.search(r"Detectadas: \*\*(\d+)/(\d+)\*\*", m.read_text(encoding="utf-8"))
            if found:
                out["mutation"] = {"caught": int(found.group(1)), "total": int(found.group(2)), "source": "make mutation"}
        return out

    def metrics_snapshot(self, scope: str = "project") -> dict:
        return team_ops.metrics_payload(self.p, scope, app_reports())

    def metrics_demote(self, body: dict) -> dict:
        return team_ops.metrics_demote(self.p, body)

    def metrics_series(self, scope: str = "project", bucket: str = "day") -> dict:
        return team_ops.metrics_series(self.p, scope, bucket)

    def providers_compare(self, body: dict) -> dict:
        return team_ops.providers_compare(self.p, body, self.transport)

    def skill_clone(self, body: dict) -> dict:
        return team_ops.clone_skill(self.p, body)

    def tools_info(self) -> dict:
        return team_ops.tools_payload(self.p)

    def skill_save(self, body: dict) -> dict:
        return team_ops.save_skill(self.p, body)

    def share_doctor(self, body: dict) -> dict:
        return team_ops.share_doctor(self.p, body)

    def share_pack(self, body: dict) -> dict:
        return team_ops.share_pack(self.p, body)

    def share_preview(self, body: dict) -> dict:
        return team_ops.share_preview(self.p, body)

    def preflight(self, dry_run: bool = False) -> dict:
        return team_ops.preflight(self.p, dry_run)

    def share_upload(self, body: dict) -> dict:
        return team_ops.share_upload(self.p, body)

    def share_exports(self) -> dict:
        return team_ops.share_exports_list(self.p)

    # ── session storage ──────────────────────────────────────────────────────
    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as h:
                h.write(text)
            if path.exists():
                os.chmod(tmp, path.stat().st_mode & 0o777)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @classmethod
    def _write_json(cls, path: Path, obj) -> None:
        cls._write_text(path, json.dumps(obj, indent=2, ensure_ascii=False))

    @staticmethod
    def _read_json(path: Path, default):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default
        return data if isinstance(data, type(default)) else default

    def _sessions(self, root: Path) -> list[dict]:
        return self._read_json(root / ".harness" / "sessions.json", [])

    def _save_sessions(self, root: Path, sessions: list[dict]) -> None:
        self._write_json(root / ".harness" / "sessions.json", sessions)

    def _session_busy(self, sid: str) -> bool:
        return any(getattr(r, "session_id", None) == sid and r.snapshot()["status"] in ACTIVE_RUN for r in list(self.runs.values()))

    def _evict_runs(self) -> None:
        with self.session_lock:
            finished = [rid for rid, r in list(self.runs.items()) if r.snapshot()["status"] not in ACTIVE_RUN]
            for rid in finished[:max(0, len(finished) - MAX_FINISHED_RUNS)]:
                self.runs.pop(rid, None)

    def sessions_list(self) -> list[dict]:
        with self.session_lock:
            root = self.p.root
            if not (root / ".harness" / "sessions.json").is_file():
                self._save_sessions(root, [])
                return []
            return self._sessions(root)

    def session_get(self, sid: str) -> dict | None:
        with self.session_lock:
            root = self.p.root
            meta = next((s for s in self._sessions(root) if s.get("id") == sid), None)
            if not meta:
                return None
            messages = self._read_json(root / ".harness" / f"{sid}.json", [])
            active = next((r.id for r in list(self.runs.values()) if getattr(r, "session_id", None) == sid and r.snapshot()["status"] in ACTIVE_RUN), None)
            return {**meta, "messages": messages, "active_run": active, "commands_enabled": sid in self.commands_on, "active_worktree": worktrees.get(root, sid)}

    def session_rename(self, sid: str, body: dict) -> dict:
        title = str(body.get("title") or "").strip()
        if not title or len(title) > 120:
            raise app.ConfigError("the session title must have between 1 and 120 characters")
        with self.session_lock:
            root = self.p.root
            sessions = self._sessions(root)
            found = None
            for item in sessions:
                if item.get("id") == sid:
                    item["title"] = title
                    if isinstance(body.get("target_kind"), str) and body["target_kind"] in ("model", "agent", "tier", "provider", "intent"):
                        item["target_kind"] = body["target_kind"]
                    if isinstance(body.get("target"), str) and body["target"].strip():
                        item["target"] = body["target"].strip()[:120]
                    found = dict(item)
                    break
            if not found:
                raise app.ConfigError("No such session")
            self._save_sessions(root, sessions)
        self._changed("sessions")
        return found

    def session_commands(self, sid: str, body: dict) -> dict:
        if type(body.get("enabled")) is not bool:
            raise app.ConfigError("enabled must be true or false")
        with self.session_lock:
            if not any(s.get("id") == sid for s in self._sessions(self.p.root)):
                raise app.ConfigError("No such session")
            if body["enabled"]:
                self.commands_on.add(sid)
            else:
                self.commands_on.discard(sid)
                self.trusted_by_session.pop(sid, None)
            return {"id": sid, "commands_enabled": sid in self.commands_on}

    def session_create(self, body: dict) -> dict:
        with self.session_lock:
            root = self.p.root
            sessions = self._sessions(root)
            taken = {s.get("id") for s in sessions}
            ms = int(time.time() * 1000)
            while f"sess-{ms}" in taken:
                ms += 1
            sid = f"sess-{ms}"
            new_sess = {
                "id": sid,
                "title": body.get("title") or "New session",
                "project": body.get("project") or root.name,
                "root": str(root.resolve()),
                "created_at": time.time(),
                "updated_at": time.time(),
                "mode": body.get("mode") or "plan",
                "messages_count": 0,
            }
            self._write_json(root / ".harness" / f"{sid}.json", [])
            sessions.insert(0, new_sess)
            self._save_sessions(root, sessions)
        self._changed("sessions")
        return new_sess

    def session_delete(self, sid: str) -> bool:
        with self.session_lock:
            if self._session_busy(sid):
                raise app.ConfigError("A session with a run in progress cannot be deleted")
            root = self.p.root
            self._save_sessions(root, [s for s in self._sessions(root) if s.get("id") != sid])
            (root / ".harness" / f"{sid}.json").unlink(missing_ok=True)
            self.commands_on.discard(sid)
            self.trusted_by_session.pop(sid, None)
        self._changed("sessions")
        return True

    def session_add_message(self, sid: str, body: dict) -> dict:
        content = str(body.get("content") or "").strip()
        mode = body.get("mode", "plan")
        model = str(body.get("model") or "").strip()
        provider = str(body.get("provider") or "ollama").strip()
        role = body.get("agent", "auto")
        target_kind = body.get("target_kind")
        target = str(body.get("target") or "").strip()
        isolated = bool(body.get("isolated", False))
        base_url = body.get("base_url")
        intent_used = ""

        if not content or len(content) > 20000:
            raise app.ConfigError("The message must have between 1 and 20000 characters")
        if role != "auto" and role not in load_all(project_root=self.p.root):
            raise app.ConfigError("Unknown skill")

        if target_kind is None:
            if mode not in ("plan", "act") or not model:
                raise app.ConfigError("Choose a valid model in plan or act mode")
            target_kind = "model" if provider == "ollama" else "provider"
            target = model
        elif target_kind in ("model", "provider"):
            model = target or model
            if mode not in ("plan", "act") or not model:
                raise app.ConfigError("Choose a valid model in plan or act mode")
            target = model
        elif target_kind == "intent":
            if target not in providers.INTENTS or mode not in ("plan", "act"):
                raise app.ConfigError("Choose a valid intent (rapido, codigo, razonar, local)")
            try:
                resolved = providers.resolve_intent(target, root=self.p.root, profile=body.get("profile"))
            except ValueError as e:
                raise app.ConfigError(str(e)) from e
            provider = resolved["provider"]
            model = resolved["model"]
            intent_used = target
        elif target_kind == "agent":
            if target not in self.p.agents:
                raise app.ConfigError(f"Unknown agent: {target}")
            mode = "plan"
            isolated = False
        elif target_kind == "tier":
            if target not in load_tiers():
                raise app.ConfigError(f"Unknown router tier: {target}")
            mode = "plan"
            isolated = False
        else:
            raise app.ConfigError("target_kind must be model, provider, intent, agent, or tier")
        if target_kind in ("model", "provider", "intent") and not providers.MODEL.fullmatch(model):
            raise app.ConfigError("That is not a valid model name")

        direct_exec = target_kind in ("model", "provider", "intent")
        with self.session_lock:
            project = self.p
            root = project.root
            session = self.session_get(sid)
            if not session:
                raise app.ConfigError("No such session")
            if direct_exec and mode == "act" and sid not in self.commands_on:
                raise app.ConfigError("Commands are off for this session. Turn them on for this session first; every edit or command still asks you.")
            same = Path(session["root"]).resolve() == root.resolve() if session.get("root") else session.get("project") == root.name
            if not same:
                raise app.ConfigError("This console only runs commands in the project the server was started in")
            if self._session_busy(sid):
                raise app.ConfigError("This session already has a run in progress")

            wt_info = worktrees.ensure(root, sid) if isolated else None
            exec_root = Path(wt_info["path"]) if wt_info else root
            expanded_prompt, attached, refused = chat.attach(exec_root, content)
            history = [
                {"role": m["role"], "content": m["content"][:4000]}
                for m in session["messages"][-12:]
                if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and (m["role"] == "user" or m.get("run_id"))
            ]

            task_id = None
            if direct_exec:
                run = Run(
                    exec_root,
                    expanded_prompt,
                    model,
                    mode,
                    role,
                    history=history,
                    provider=provider,
                    base_url=base_url,
                    intent=intent_used,
                    initial_trusted=self.trusted_by_session.get(sid),
                )
            else:
                skill_arg = None if role == "auto" else role
                tid, queue, why = app.add_task(
                    project,
                    expanded_prompt,
                    queue=target if target_kind == "agent" else None,
                    skill=skill_arg,
                    tier=target if target_kind == "tier" else None,
                )
                task_id = tid
                run = TaskRun(project, tid, queue, why, target_kind, target, role)

            run.session_id = sid
            run.worktree = wt_info
            run.target_kind = target_kind
            run.target = target
            self._watch_run(run)
            self.runs[run.id] = run

            sessions = self._sessions(root)
            for item in sessions:
                if item.get("id") == sid:
                    item["mode"] = mode
                    item["target_kind"] = target_kind
                    item["target"] = target
            self._save_sessions(root, sessions)

            messages = session["messages"]
            messages.append({
                "id": "msg-" + run.id,
                "role": "user",
                "content": content,
                "timestamp": time.time(),
                "attached": attached,
            })
            self._write_json(root / ".harness" / f"{sid}.json", messages)
        self._evict_runs()

        def work():
            try:
                try:
                    run.execute()
                except Exception as exc:
                    with run._lock:
                        run.error = run.error or f"{type(exc).__name__}: {str(exc)[:300]}"
                result = run.snapshot()
                try:
                    diff_text = worktrees.workspace_diff(exec_root, max_bytes=16384).get("diff") or None
                except Exception:
                    diff_text = None
                if diff_text:
                    run.diff_text = diff_text
                with self.session_lock:
                    if direct_exec and getattr(run, "trusted", None):
                        self.trusted_by_session.setdefault(sid, set()).update(run.trusted)
                    messages = self._read_json(root / ".harness" / f"{sid}.json", []) if any(s.get("id") == sid for s in self._sessions(root)) else None
                    if messages is not None:
                        reply_text = result["answer"] or (result["error"] and f"The run failed: {result['error']}") or "Stopped waiting."
                        if refused and not result.get("cancelled"):
                            reply_text = "Attachments skipped:\n- " + "\n- ".join(refused) + "\n\n" + reply_text
                        a_info = project.agents.get(result.get("queue", "")) if not direct_exec else None
                        u = result.get("usage") or {}
                        tok = int(u.get("prompt_tokens") or 0) + int(u.get("completion_tokens") or 0)
                        reply_msg = {
                            "id": "reply-" + run.id,
                            "role": "assistant",
                            "content": reply_text,
                            "timestamp": time.time(),
                            "model": result.get("model") or model,
                            "provider": (a_info.provider if a_info and a_info.provider else result.get("provider") or provider if direct_exec else target_kind),
                            "target_kind": target_kind,
                            "target": target,
                            "agent": role,
                            "tool_steps": result["steps"],
                            "questions": result.get("questions") or [],
                            "run_id": run.id,
                            "diff": diff_text,
                        }
                        if tok > 0:
                            reply_msg["tokens"] = tok
                        if task_id is not None:
                            reply_msg["task_id"] = task_id
                        messages.append(reply_msg)
                        self._write_json(root / ".harness" / f"{sid}.json", messages)
                        sessions = self._sessions(root)
                        for item in sessions:
                            if item.get("id") == sid:
                                item["updated_at"] = time.time()
                                item["messages_count"] = len(messages)
                        self._save_sessions(root, sessions)
            except Exception as exc:
                with run._lock:
                    run.error = run.error or f"could not save the reply: {type(exc).__name__}: {str(exc)[:200]}"
            finally:
                with run._lock:
                    if run.status in ACTIVE_RUN:
                        run.status = "stopped" if getattr(run, "_cancelled", False) else "failed" if run.error else "completed"
                self._evict_runs()
                self._changed("run:" + run.id, "runs", "sessions", "board")

        threading.Thread(target=work, daemon=True).start()
        self._changed("runs", "sessions")
        out = {"run_id": run.id, "attached": attached, "refused": refused}
        if task_id is not None:
            out["task_id"] = task_id
        if wt_info is not None:
            out["worktree"] = wt_info
        return out

    def run_detail(self, run_id: str) -> dict | None:
        run = self.runs.get(run_id)
        if not run:
            return None
        snap = run.snapshot()
        snap.setdefault("target_kind", getattr(run, "target_kind", "model"))
        snap.setdefault("target", getattr(run, "target", snap.get("model")))
        if getattr(run, "worktree", None):
            snap["worktree"] = run.worktree
        if getattr(run, "diff_text", None):
            snap["diff"] = run.diff_text
        return snap

    def run_cancel(self, run_id: str) -> dict:
        run = self.runs.get(run_id)
        if run is None:
            raise app.ConfigError("No such run")
        run.cancel()
        self._changed("run:" + run_id, "runs")
        return self.run_detail(run_id)

    def run_decision(self, run_id: str, body: dict) -> dict:
        run = self.runs.get(run_id)
        if run is None:
            raise app.ConfigError("No such run")
        if type(body.get("approve")) is not bool or type(body.get("step")) is not int:
            raise app.ConfigError("Invalid decision")
        trust_session = bool(body.get("trust_session", False))
        if not hasattr(run, "decide"):
            raise app.ConfigError("this run has no command waiting for a decision")
        try:
            try:
                run.decide(body["step"], body["approve"], trust_session=trust_session)
            except TypeError:
                run.decide(body["step"], body["approve"])
        except ValueError as exc:
            raise app.ConfigError(str(exc)) from exc
        return run.snapshot()

    # ── orchestration ──────────────────────────────────────────────────────────
    def orchestrate_options(self, goal: str = "") -> dict:
        return orchestrator.options(self.p, goal)

    def orchestrate_plan(self, body: dict) -> dict:
        goal = str(body.get("goal") or "")
        opts = orchestrator.options(self.p, goal)
        name = body.get("orchestrator") or opts["suggested"]["name"] or opts["default_orchestrator"]
        if not isinstance(name, str) or name not in self.p.agents:
            raise app.ConfigError("choose an agent to orchestrate")
        pool = body.get("pool")
        if pool is not None and (not isinstance(pool, list) or not all(isinstance(x, str) for x in pool)):
            raise app.ConfigError("pool must be a list of agent names")
        plan = orchestrator.plan_orchestration(self.p, goal, name, pool, self.orch_factory)
        plan["suggested"] = opts["suggested"]
        if body.get("auto_execute") is True:
            return self.orchestrate_launch({"session_id": body.get("session_id"), "plan": plan})
        return plan

    def orchestrate_launch(self, body: dict) -> dict:
        """Carries out the plan the person reviewed (their edits are what runs) and returns the run to follow on its event stream."""
        sid, raw = body.get("session_id"), body.get("plan")
        if not isinstance(sid, str) or not isinstance(raw, dict):
            raise app.ConfigError("give a session and the reviewed plan")
        plan = orchestrator.normalize_plan(raw, self.p, None, strict=True)   # the pool only suggested; any agent of the project may be given a subtask
        with self.session_lock:
            project, root = self.p, self.p.root
            session = self.session_get(sid)
            if not session:
                raise app.ConfigError("No such session")
            if self._session_busy(sid):
                raise app.ConfigError("This session already has a run in progress")
            run = orchestrator.OrchestrationRun(project, plan, session_id=sid, factory=self.orch_factory)
            self._watch_run(run)
            self.runs[run.id] = run
            messages = session["messages"]
            messages.append({"id": "msg-" + run.id, "role": "user", "content": plan["goal"], "timestamp": time.time(), "attached": [], "orchestrate": True})
            self._write_json(root / ".harness" / f"{sid}.json", messages)
            sessions = self._sessions(root)
            for item in sessions:
                if item.get("id") == sid:
                    item["mode"], item["target_kind"], item["target"] = "orchestrate", "orchestrate", plan["orchestrator"]
            self._save_sessions(root, sessions)
        self._evict_runs()

        def work():
            try:
                try:
                    run.execute()
                except Exception as exc:
                    with run._lock:
                        run.error = run.error or f"{type(exc).__name__}: {str(exc)[:300]}"
                snap = run.snapshot()
                with self.session_lock:
                    if any(s.get("id") == sid for s in self._sessions(root)):
                        msgs = self._read_json(root / ".harness" / f"{sid}.json", [])
                        msgs.append({"id": "reply-" + run.id, "role": "assistant", "content": snap["answer"] or snap["error"] or "Stopped waiting.",
                                     "timestamp": time.time(), "model": snap["model"], "provider": "orchestrator", "target_kind": "orchestrate",
                                     "target": plan["orchestrator"], "agent": "auto", "tool_steps": snap["steps"], "questions": [], "run_id": run.id,
                                     "task_id": snap["task_id"], "orchestration": snap["orchestration"]})
                        self._write_json(root / ".harness" / f"{sid}.json", msgs)
                        sessions = self._sessions(root)
                        for item in sessions:
                            if item.get("id") == sid:
                                item["updated_at"], item["messages_count"] = time.time(), len(msgs)
                        self._save_sessions(root, sessions)
            except Exception as exc:
                with run._lock:
                    run.error = run.error or f"could not save the reply: {type(exc).__name__}: {str(exc)[:200]}"
            finally:
                with run._lock:
                    if run.status in ACTIVE_RUN:
                        run.status = "stopped" if run._cancelled else "failed" if run.error else "completed"
                self._evict_runs()
                self._changed("run:" + run.id, "runs", "sessions", "board")

        threading.Thread(target=work, daemon=True).start()
        self._changed("runs", "sessions")
        return {"run_id": run.id, "plan": plan}

    def state(self) -> dict:
        b = self.p.board
        rows = b.rows(descending=True, limit=400)
        with (b.trace.lock if b.trace else b.lock):
            decisions = dict(b.trace.db.execute("SELECT run_id, json_extract(data,'$.tier') || '|' || COALESCE(name,'') || '|' || status || '|' || COALESCE(reason,'') FROM events WHERE source='router'").fetchall()) if b.trace else {}
            moved = {r[0] for r in b.trace.db.execute("SELECT DISTINCT run_id FROM events WHERE source='board' AND kind='requeue'").fetchall()} if b.trace else set()
        tasks = []
        for r in rows:
            t = task_row(r)
            d = decisions.get(f"task:{r['id']}")
            if d and f"task:{r['id']}" not in moved:
                tier, system, action, reason = d.split("|", 3)
                t["router"] = {"tier": tier, "system": system or None, "action": action, "reason": reason}
            tasks.append(t)
        agents = [
            {
                "name": a.name,
                "system": a.system,
                "provider": a.provider,
                "model": a.model,
                "command": " ".join(a.command),
                "timeout": a.timeout,
                "pending": sum(1 for t in tasks if t["queue"] == a.name and t["status"] == "pending"),
                "working": sum(1 for t in tasks if t["agent"] == a.name and t["status"] == "sending"),
            }
            for a in self.p.agents.values()
        ]
        return {
            "project": self.p.root.name,
            "root": str(self.p.root),
            "now": time.time(),
            "agents": agents,
            "tasks": tasks,
            "stats": b.stats(),
            "summary": app.summary(self.p),
            "quality": self.quality(),
            "running": self.running.locked(),
            "last_run": self.last_run,
            "sample": (self.p.root / ".harness" / "sample").is_file(),
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "local": s.local,
                    "category": s.category,
                    "team_shareable": s.team_shareable,
                    "body": s.body,
                }
                for s in load_all(project_root=self.p.root).values()
            ],
            "tiers": list(load_tiers()),
        }

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
        git_repo = False
        git_dirty = []
        branch = None
        try:
            r = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                git_repo = True
                git_dirty = [l.strip() for l in r.stdout.splitlines() if l.strip()]
                br = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True, timeout=2)
                branch = br.stdout.strip() if br.returncode == 0 and br.stdout.strip() else "detached"
        except Exception:
            pass
        return {
            "repo": root.name,
            "path": str(root),
            "git_repo": git_repo,
            "has_head": worktrees.has_head(root) if git_repo else False,
            "branch": branch,
            "dirty_files": git_dirty,
            "worktrees": list(worktrees.active_worktrees(root).values()),
            "integrated_worktrees": worktrees.integrated_worktrees(root) if git_repo else [],
            "skills": [s.name for s in load_all(project_root=self.p.root).values()],
            "agents": [a.name for a in self.p.agents.values()],
            "stats": self.p.board.stats(),
        }

    def workspace_files(self) -> dict:
        return {"files": worktrees.safe_workspace_files(self.p.root)}

    def workspace_diff(self, worktree_key: str | None = None) -> dict:
        target = self.p.root
        wt = worktrees.get(self.p.root, worktree_key) if worktree_key else None
        if wt:
            target = Path(wt["path"])
        out = worktrees.workspace_diff(target)
        out["worktree"] = wt
        return out

    def worktree_inspect(self, key: str) -> dict:
        return worktrees.inspect(self.p.root, key)

    def worktree_patch(self, body: dict) -> dict:
        key = str(body.get("key") or "").strip() or None
        return worktrees.export_patch(self.p.root, key)

    def worktree_cleanup(self, body: dict) -> dict:
        """Removes the worktrees that have nothing of their own left. A worktree a run is still using is never touched."""
        removed, kept = [], []
        with self.session_lock:
            for key in worktrees.integrated_worktrees(self.p.root):
                if self._session_busy(key):
                    kept.append(key)
                    continue
                worktrees.discard(self.p.root, key)
                removed.append(key)
        return {"removed": removed, "kept_busy": kept}

    def activity_feed(self) -> dict:
        return activity.feed(self.p)

    def board_global(self) -> dict:
        return activity.consolidated(self.p)

    def sessions_global(self) -> dict:
        return activity.recent_sessions(self.p)

    def worktree_discard(self, body: dict) -> dict:
        key = str(body.get("key") or "")
        with self.session_lock:
            if self._session_busy(key):
                raise app.ConfigError("cannot discard a worktree while a run is still in progress")
            return worktrees.discard(self.p.root, key)

    def move(self, tid: int, body: dict) -> dict:
        queue = body.get("queue")
        if not isinstance(queue, str) or (queue != app.PERSON and queue not in self.p.agents):
            raise app.ConfigError(f"unknown queue: {queue} (an agent from harness.toml, or {app.PERSON})")
        if not self.p.board.requeue(tid, queue):
            raise app.ConfigError("only a pending task that is not already there can be moved")
        return {"id": tid, "queue": queue}

    def discard(self, tid: int) -> dict:
        if not self.p.board.discard(tid):
            raise app.ConfigError("only a pending task can be discarded")
        return {"id": tid}

    def run(self, wait: bool = False) -> dict:
        if not self.running.acquire(blocking=False):
            raise app.ConfigError("a run is already in progress")

        def work():
            try:
                self.last_run = app.run_pending(self.p)
            finally:
                self.running.release()
                self._changed("board")

        th = threading.Thread(target=work, daemon=True)
        self._changed("board")
        th.start()
        if wait:
            th.join()
        return {"started": True}


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        server_version = "caos-harness"
        timeout = 30

        def log_message(self, *a):
            pass

        def security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", CSP)

        def send_json(self, code: int, obj) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.security_headers()
            self.end_headers()
            self.wfile.write(body)

        def fail(self, code: int, message: str) -> None:
            self.close_connection = True
            self.send_json(code, {"error": message})

        def body_length(self) -> int | None:
            raw = (self.headers.get("Content-Length") or "").strip()
            if not raw:
                return 0
            if not (raw.isascii() and raw.isdigit()):
                self.fail(400, "Content-Length must be a non-negative integer")
                return None
            n = int(raw)
            if n > MAX_BODY:
                self.fail(413, "body too large")
                return None
            return n

        def guard(self, write: bool) -> bool:
            if not LOOPBACK.match(self.headers.get("Host", "")):
                self.send_json(403, {"error": "loopback only"})
                return False
            if write and self.headers.get("X-Harness") != "1":
                self.send_json(403, {"error": "missing X-Harness header"})
                return False
            return True

        def do_GET(self):
            self.safely(self._get)

        def do_POST(self):
            self.safely(self._post)

        def safely(self, handle) -> None:
            try:
                handle()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                self.close_connection = True
            except Exception:
                try:
                    self.fail(500, "internal error")
                except OSError:
                    pass

        def stream(self, first, wait, done=lambda payload: False, event: str = "message") -> None:
            """A server-sent event stream. `first()` reads the current state, `wait(timeout)` sleeps until something changed (or the timeout),
            and the stream ends when `done(payload)` says so or the client goes away (the write then raises and `safely` closes quietly)."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.security_headers()
            self.end_headers()
            self.close_connection = True
            last = None
            while True:
                payload = first()
                blob = json.dumps(payload, ensure_ascii=False)
                if blob != last:
                    self.wfile.write(f"event: {event}\ndata: {blob}\n\n".encode())
                    self.wfile.flush()
                    last = blob
                if done(payload):
                    return
                if not wait(HEARTBEAT):
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()

        def _get(self):
            if not self.guard(False):
                return
            path, _, query_str = self.path.partition("?")
            query = urllib.parse.parse_qs(query_str)
            if path == "/api/events":
                state = {"total": api.bus.total()}

                def wait_any(timeout):
                    new = api.bus.wait_any(state["total"], timeout)
                    changed, state["total"] = new != state["total"], new
                    return changed
                return self.stream(lambda: api.bus.versions("board", "runs", "sessions"), wait_any, event="change")
            m_ev = re.fullmatch(r"/api/runs/([a-f0-9]{32})/events", path)
            if m_ev:
                rid = m_ev.group(1)
                if api.run_detail(rid) is None:
                    return self.send_json(404, {"error": "no such run"})
                seen = {"v": api.bus.version("run:" + rid)}

                def wait_run(timeout):
                    new = api.bus.wait("run:" + rid, seen["v"], timeout)
                    changed, seen["v"] = new != seen["v"], new
                    return changed
                return self.stream(lambda: api.run_detail(rid), wait_run, lambda snap: snap is None or snap["status"] in TERMINAL_RUN, event="run")
            if path == "/api/state":
                return self.send_json(200, api.state())
            if path == "/api/router":
                return self.send_json(200, api.router_table())
            if path == "/api/providers":
                try:
                    return self.send_json(200, api.providers_info((query.get("profile") or [None])[0]))
                except app.ConfigError as e:
                    return self.send_json(400, {"error": str(e)})
            if path == "/api/metrics":
                scope = (query.get("scope") or ["project"])[0]
                return self.send_json(200, api.metrics_snapshot(scope))
            if path == "/api/metrics/series":
                try:
                    return self.send_json(200, api.metrics_series((query.get("scope") or ["project"])[0], (query.get("bucket") or ["day"])[0]))
                except app.ConfigError as e:
                    return self.send_json(400, {"error": str(e)})
            if path == "/api/orchestrate/options":
                return self.send_json(200, api.orchestrate_options((query.get("goal") or [""])[0][:4000]))
            if path == "/api/tools":
                return self.send_json(200, api.tools_info())
            if path == "/api/share/exports":
                return self.send_json(200, api.share_exports())
            if path == "/api/share/preview":
                flag = lambda k: (query.get(k) or ["1"])[0] not in ("0", "false")
                try:
                    return self.send_json(200, api.share_preview({"include_code": flag("include_code"), "include_docs": flag("include_docs"), "include_skills": flag("include_skills"), "format": (query.get("format") or ["zip"])[0]}))
                except app.ConfigError as e:
                    return self.send_json(400, {"error": str(e)})
            if path == "/api/preflight":
                return self.send_json(200, api.preflight((query.get("dry_run") or ["0"])[0] in ("1", "true")))
            if path == "/api/share/download":
                fn = Path((query.get("file") or [""])[0]).name
                exp_dir = (api.p.root / ".harness" / "exports").resolve()
                target = (exp_dir / fn).resolve()
                if not fn or not target.is_file() or exp_dir not in target.parents:
                    return self.send_json(404, {"error": "export not found"})
                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/gzip" if target.name.endswith(".tar.gz") else ("text/x-diff; charset=utf-8" if target.name.endswith(".patch") else "application/zip"))
                self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
                self.send_header("Content-Length", str(len(data)))
                self.security_headers()
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/workspaces":
                return self.send_json(200, api.workspaces())
            if path == "/api/repositories":
                return self.send_json(200, api.repositories())
            if path == "/api/workspace/status":
                return self.send_json(200, api.workspace_status())
            if path == "/api/workspace/files":
                return self.send_json(200, api.workspace_files())
            if path == "/api/activity":
                return self.send_json(200, api.activity_feed())
            if path == "/api/sessions/global":
                return self.send_json(200, api.sessions_global())
            if path == "/api/board/global":
                return self.send_json(200, api.board_global())
            if path == "/api/workspace/worktree":
                try:
                    return self.send_json(200, api.worktree_inspect((query.get("key") or [""])[0]))
                except app.ConfigError as e:
                    return self.send_json(404, {"error": str(e)})
            if path == "/api/workspace/diff":
                wt_key = (query.get("worktree") or [None])[0]
                return self.send_json(200, api.workspace_diff(wt_key))
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
                f = DIST / "index.html"
            if not f.is_file():
                return self.send_json(503, {"error": "the dashboard is not built: run `make web`"})
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", TYPES.get(f.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable" if "/assets/" in path else "no-cache")
            self.security_headers()
            self.end_headers()
            self.wfile.write(data)

        def _post(self):
            if not self.guard(True):
                return
            n = self.body_length()
            if n is None:
                return
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self.send_json(400, {"error": "the body must be a JSON object"})
            path = self.path.split("?", 1)[0]
            try:
                if path == "/api/orchestrate/plan":
                    return self.send_json(202 if body.get("auto_execute") is True else 200, api.orchestrate_plan(body))
                if path == "/api/orchestrate/launch":
                    return self.send_json(202, api.orchestrate_launch(body))
                if path == "/api/task":
                    return self.send_json(201, api.add(body))
                if path == "/api/providers/test":
                    return self.send_json(200, api.provider_test(body))
                if path == "/api/providers/smoke":
                    return self.send_json(200, api.provider_smoke(body))
                if path == "/api/providers/key":
                    return self.send_json(200, api.provider_save_key(body))
                if path == "/api/providers/ollama-hosts":
                    return self.send_json(200, api.save_ollama_host(body))
                if path == "/api/intents":
                    return self.send_json(200, api.save_intent_override(body))
                if path == "/api/agents":
                    return self.send_json(201, api.add_agent(body))
                if path == "/api/metrics/demote":
                    return self.send_json(200, api.metrics_demote(body))
                if path == "/api/providers/compare":
                    return self.send_json(200, api.providers_compare(body))
                if path == "/api/skills/clone":
                    return self.send_json(201, api.skill_clone(body))
                if path == "/api/skills/save":
                    return self.send_json(200, api.skill_save(body))
                if path == "/api/share/doctor":
                    return self.send_json(200, api.share_doctor(body))
                if path == "/api/share/pack":
                    return self.send_json(200, api.share_pack(body))
                if path == "/api/share/preview":
                    return self.send_json(200, api.share_preview(body))
                if path == "/api/share/upload":
                    return self.send_json(200, api.share_upload(body))
                if path == "/api/workspaces":
                    return self.send_json(200, api.workspace_add(body))
                if path == "/api/workspaces/switch":
                    return self.send_json(200, api.workspace_switch(body))
                if path == "/api/workspaces/remove":
                    return self.send_json(200, api.workspace_remove(body))
                if path == "/api/workspace/convert_task":
                    return self.send_json(201, api.add(body))
                if path == "/api/workspace/worktree/patch":
                    return self.send_json(200, api.worktree_patch(body))
                if path == "/api/workspace/worktree/cleanup":
                    return self.send_json(200, api.worktree_cleanup(body))
                if path == "/api/workspace/worktree/discard":
                    return self.send_json(200, api.worktree_discard(body))
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
                m_cancel = re.fullmatch(r"/api/runs/([a-f0-9]{32})/cancel", path)
                if m_cancel:
                    return self.send_json(200, api.run_cancel(m_cancel.group(1)))
                m_msg = re.fullmatch(r"/api/sessions/([a-zA-Z0-9_-]+)/messages", path)
                if m_msg:
                    return self.send_json(201, api.session_add_message(m_msg.group(1), body))
                m_rename = re.fullmatch(r"/api/sessions/([a-zA-Z0-9_-]+)/rename", path)
                if m_rename:
                    return self.send_json(200, api.session_rename(m_rename.group(1), body))
                m_cmd = re.fullmatch(r"/api/sessions/([a-zA-Z0-9_-]+)/commands", path)
                if m_cmd:
                    return self.send_json(200, api.session_commands(m_cmd.group(1), body))
                m_del = re.fullmatch(r"/api/sessions/([a-zA-Z0-9_-]+)/delete", path)
                if m_del:
                    api.session_delete(m_del.group(1))
                    return self.send_json(200, {"deleted": True})
                m_move = re.fullmatch(r"/api/task/(\d+)/move", path)
                if m_move:
                    return self.send_json(200, api.move(int(m_move.group(1)), body))
                m = re.fullmatch(r"/api/task/(\d+)/(review|discard)", path)
                if m:
                    tid = int(m.group(1))
                    return self.send_json(200, api.review(tid, body) if m.group(2) == "review" else api.discard(tid))
            except app.ConfigError as e:
                return self.send_json(409, {"error": str(e)})
            self.send_json(404, {"error": "unknown endpoint"})

    return Handler


def make_server(project: app.Project, port: int = 8791) -> ThreadingHTTPServer:
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
