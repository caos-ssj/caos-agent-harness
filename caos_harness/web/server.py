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

from .. import activity, app, chat, cycle, desktop, detect, missions, orchestrator, providers, scout as scouting, workspaces, worktrees
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
MAX_NOTE = 4000        # characters of one review note: several inline notes travel together as one, a line each
MAX_NOTE_LINES = 40
ACTIVE_RUN = ("queued", "running", "awaiting_approval", "finishing")
TERMINAL_RUN = ("completed", "failed", "stopped")
HEARTBEAT = 12.0   # seconds of silence after which an event stream sends a comment line, so a dead client is noticed
MAX_FINISHED_RUNS = 100
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
    "frame-src about:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class NotFound(Exception):
    """The thing a request names does not exist: answered with 404, where a refused change is 409."""


def clean_note(raw) -> str:
    """A review note as it is stored: one note per line, no control characters, within the limits. Too long is refused, never cut."""
    if raw is not None and not isinstance(raw, str):
        raise app.ConfigError("the note must be text")
    lines = [" ".join(re.sub(r"[\x00-\x1f\x7f]", " ", ln).split()) for ln in (raw or "").replace("\r", "\n").split("\n")]
    lines = [ln for ln in lines if ln]
    note = "\n".join(lines)
    if len(note) > MAX_NOTE:
        raise app.ConfigError(f"the note is too long: {len(note)} characters, the limit is {MAX_NOTE}")
    if len(lines) > MAX_NOTE_LINES:
        raise app.ConfigError(f"too many notes in one return: {len(lines)}, the limit is {MAX_NOTE_LINES}")
    return note


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
        "position": r["position"] if "position" in r.keys() and r["position"] is not None else r["id"],   # the order inside its queue; trades places on reorder
        "effort": r["effort"] if "effort" in r.keys() else None,
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
        self.duration_ms: int | None = None
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
                "duration_ms": self.duration_ms,
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
                self.duration_ms = dur
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
    def shutdown(self) -> None:
        """Stops every active run (and the agent process groups behind them) so closing the app leaves nothing running."""
        for r in list(self.runs.values()):
            try:
                if r.snapshot()["status"] in ACTIVE_RUN:
                    r.cancel()
            except Exception:
                pass

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
        self.task_dispatcher = None   # tests give "run now" a dispatcher with a fake runner
        self.running_tasks: set[int] = set()   # tasks started one by one with "run now" that have not come back yet
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
            effort = self._effort(body.get("effort"), command, None, providers.CLIS[cid]["label"])
            block = providers.agent_block(name, command=command, timeout=providers.CLIS[cid]["timeout"], effort=effort)
        elif kind == "api":
            pid, model = body.get("provider"), body.get("model")
            if pid not in providers.API or not isinstance(model, str) or not providers.MODEL.fullmatch(model):
                raise app.ConfigError("give a configured API provider and a model name")
            name = name or f"{pid}-{re.sub(r'[^a-z0-9]+', '-', model.lower()).strip('-')}"[:32]
            self._effort(body.get("effort"), (), pid, pid)
            block = providers.agent_block(name, provider=pid, model=model, timeout=300)
        elif kind == "local":
            model = body.get("model")
            if not isinstance(model, str) or not providers.MODEL.fullmatch(model):
                raise app.ConfigError("give a valid Ollama model name")
            base = re.sub(r"[^a-z0-9]+", "-", model.split(":", 1)[0].lower()).strip("-") or "local"
            name = name or base[:24]
            block = providers.agent_block(name, command=["ollama", "run", model], timeout=300)
        else:
            raise app.ConfigError("kind must be cli, api or local")
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

    @staticmethod
    def _effort(raw, command, provider, label: str) -> str | None:
        """The effort a request asks for, or None for the agent's own default. Refused, with the reason, where the tool takes none."""
        if raw in (None, ""):
            return None
        if raw not in providers.EFFORTS:
            raise app.ConfigError(f"effort must be one of {', '.join(providers.EFFORTS)}, or empty for the agent's default")
        can, why = providers.effort_support(command, provider)
        if not can:
            raise app.ConfigError(f"{label} cannot take an effort level: {why}")
        return raw

    def set_agent_effort(self, body: dict) -> dict:
        """Writes (or removes) `effort` in the `[agents.<name>]` table of harness.toml and reloads it. Nothing else in the file moves."""
        name = body.get("name")
        a = self.p.agents.get(name) if isinstance(name, str) else None
        if a is None:
            raise NotFound(f"no agent {name}")
        effort = self._effort(body.get("effort"), a.command, a.provider, a.name)
        cfg = self.p.root / app.CONFIG
        if cfg.is_symlink() or cfg.resolve().parent != self.p.root.resolve():
            raise app.ConfigError("harness.toml must be a plain file inside the project folder to be edited from here")
        before = cfg.read_text(encoding="utf-8")
        lines = before.split("\n")
        head = re.compile(r"\s*\[\s*agents\s*\.\s*(?:\"%s\"|%s)\s*\]\s*(#.*)?" % (re.escape(a.name), re.escape(a.name)))
        start = next((i for i, ln in enumerate(lines) if head.fullmatch(ln)), None)
        if start is None:
            raise app.ConfigError(f"[agents.{a.name}] is not written as its own table in harness.toml: set effort there by hand")
        end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
        body_lines = [ln for ln in lines[start + 1:end] if not re.match(r"\s*effort\s*=", ln)]
        if effort:
            last = max((i for i, ln in enumerate(body_lines) if ln.strip() and not ln.lstrip().startswith("#")), default=-1)
            body_lines.insert(last + 1, f"effort = {json.dumps(effort)}")
        self._write_text(cfg, "\n".join(lines[:start + 1] + body_lines + lines[end:]))
        try:
            fresh = app.load(cfg)
            if (fresh.agents[a.name].effort or None) != effort:
                raise app.ConfigError("harness.toml did not take the change: set effort there by hand")
        except (app.ConfigError, KeyError) as e:
            self._write_text(cfg, before)
            raise app.ConfigError(str(e)) from e
        self.p.agents[a.name] = fresh.agents[a.name]
        self._changed("board")
        return {"name": a.name, "effort": effort}

    def save_custom_provider(self, cp: dict) -> dict:
        return team_ops.save_provider_entry(self.p, cp)

    def save_failover(self, fo: dict) -> dict:
        return team_ops.save_failover_cfg(self.p, fo)

    def workspaces(self) -> dict:
        return {"current": str(self.p.root), "items": workspaces.listing(self.p.root)}

    def workspace_add(self, body: dict) -> dict:
        workspaces.register(body.get("path"), bool(body.get("initialize")))
        return self.workspaces()

    def detect(self, path: str | None = None) -> dict:
        target = workspaces.check(path) if path else self.p.root
        return detect.scan(target)

    def detect_apply(self, body: dict) -> dict:
        target = workspaces.check(body.get("path")) if body.get("path") else self.p.root
        return detect.apply_init(target, overwrite=bool(body.get("overwrite")))

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
            workspaces.remember(project.root)
            desktop.save_last_workspace(project.root)
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

    def missions(self) -> dict:
        return missions.detect_missions(self.p)

    # ─ the Run view: cycles, the landed branch, how reliable each reviewer is, and what every call cost ─
    def run_overview(self, since: float | None = None) -> dict:
        from .. import cycle, landed, ledger, scout as scouting
        root = self.p.root
        git_repo = worktrees.is_git_repo(root) and worktrees.has_head(root)
        land = landed.overview(root) if git_repo else {"branch": landed.BRANCH, "tip": None, "base": None, "entries": [], "files": [], "checked_out": False}
        done = {e["worktree"] for e in land["entries"]}
        cycles = cycle.recent(self.p, 30)
        last = {}
        for c in cycles[::-1]:   # oldest first, so the newest status of each worktree wins
            last[c["key"]] = c["status"]
        waiting = [{"key": k, "branch": w.get("branch"), "created_at": w.get("created_at"), "last": last.get(k)}
                   for k, w in (worktrees.active_worktrees(root) if git_repo else {}).items() if k not in done][:20]
        try:
            cfg = orchestrator.landing_config(self.p)
        except app.ConfigError as e:
            cfg = {"verify": None, "timeout": 900.0, "autonomous": False, "verifier": None, "target": "branch", "error": str(e)}
        agents = [n for n, a in self.p.agents.items() if orchestrator.family(a) is not None]
        # the stations: every AI agent of the project, what it is for (from what it has actually done), and whether it runs now
        led = ledger.summary(self.p)
        by_agent = {r["agent"]: r for r in led["agents"]}
        last_call = ledger.last_calls(self.p)
        vstats = {v["verifier"]: v for v in cycle.verifier_stats(self.p)}
        authors, reviewers = {c["author"] for c in cycles}, {c["review"]["verifier"] for c in cycles}
        scouts = [c["name"] for c in scouting.scouts(self.p)]
        with self.p._mu:
            busy = set(self.p._busy)
        live_by_agent = {}
        try:
            with self.p.board.lock:
                sending_rows = self.p.board.conn.execute(
                    "SELECT id, queue, text, created FROM tasks WHERE status='sending' ORDER BY id DESC"
                ).fetchall()
            for row in sending_rows:
                tid, qname, ttext, tcreated = row[0], row[1], row[2], row[3]
                if qname in live_by_agent:
                    continue
                step_lbl = ""
                started = float(tcreated or 0) or None
                try:
                    tl = self.p.traces.timeline(tid)
                    if tl:
                        ev = tl[-1]
                        started = float(tl[0].get("ts") or started or 0) or started
                        step_lbl = " · ".join(x for x in (ev.get("kind") or ev.get("status"), ev.get("name")) if x)
                except Exception:
                    pass
                live_by_agent[qname] = {
                    "task_id": tid,
                    "text": (ttext or "")[:90],
                    "step": step_lbl or "ejecutando tarea",
                    "started_at": started,
                }
        except Exception:
            pass
        stations = []
        for n in agents:
            a = self.p.agents[n]
            roles = [r for r, on in (("scout", bool(scouts) and scouts[0] == n), ("author", n in authors), ("reviewer", n in reviewers or cfg.get("verifier") == n)) if on]
            r = by_agent.get(n, {})
            is_running = (n in busy) or (n in live_by_agent)
            stations.append({"name": n, "family": orchestrator.family(a), "tier": scouting.cost_tier(a), "model": a.model or a.system or (a.command[-1] if a.command and "/" in a.command[-1] else ""),
                             "roles": roles, "running": is_running, "live": live_by_agent.get(n), "last": last_call.get(n), "calls": r.get("calls", 0), "failed": r.get("failed", 0), "seconds": r.get("seconds", 0.0),
                             "caught": vstats[n]["caught"] if n in vstats else None, "reviewed_failing": vstats[n]["failed"] if n in vstats else None})
        with self.p.board.lock:
            needs_you = self.p.board.conn.execute("SELECT COUNT(*) FROM tasks WHERE (status='sent' AND result IS NOT NULL AND (review IS NULL OR review='verify')) OR (status='pending' AND queue=?)", (app.PERSON,)).fetchone()[0]
        t0 = float(since) if since else 0.0
        recent = [c for c in cycles if c.get("at", 0) > t0]
        shift = {"since": t0 or None, "landed": sum(c["status"] == "landed" for c in recent), "failed": sum(c["status"] == "verify_failed" for c in recent),
                 "rejected": sum(c["status"] == "rejected" for c in recent), "needs_you": needs_you, **ledger.since(self.p, t0)}
        tiers = {}
        for r in led["agents"]:
            tiers[r["tier"] or "tool"] = tiers.get(r["tier"] or "tool", 0) + r["calls"]
        return {"git_repo": git_repo, "cycles": cycles, "landed": land, "verifiers": cycle.verifier_stats(self.p),
                "ledger": led, "waiting": waiting, "config": cfg, "agents": agents,
                "stations": stations, "activity": ledger.activity(self.p), "shift": shift, "tiers": tiers,
                "families": {n: (orchestrator.family(a) or "tool") for n, a in self.p.agents.items()}}

    def landed_diff(self) -> dict:
        from .. import landed
        return {"diff": landed.diff(self.p.root)}

    def landed_undo(self, body: dict) -> dict:
        from .. import landed
        return landed.undo(self.p.root, str(body.get("expected") or "") or None)

    def cycle_run(self, body: dict) -> dict:
        from .. import cycle
        key, author = str(body.get("key") or ""), str(body.get("author") or "")
        if author not in self.p.agents:
            raise app.ConfigError("choose the agent that made the change")
        return cycle.run_cycle(self.p, key, author, body.get("verifier") or None, apply=True if body.get("apply") else None, auto_redo=bool(body.get("redo")))

    # ─ skills that learn from returns (skill_eval): the numbers, a proposal from a cheap reader, and its trial ─
    def skills_evidence(self) -> dict:
        from .. import skill_eval
        return {"skills": skill_eval.overview(self.p), "min_decided": skill_eval.MIN_DECIDED, "min_evidence_tasks": skill_eval.MIN_EVIDENCE_TASKS}

    def _skill_loop(self, fn):
        try:
            return fn()
        except (ValueError, RuntimeError) as e:
            raise app.ConfigError(str(e)) from e

    def skill_propose(self, body: dict) -> dict:
        from .. import skill_eval
        return self._skill_loop(lambda: skill_eval.propose(self.p, str(body.get("skill") or ""), body.get("reader") or None))

    def skill_trial_start(self, body: dict) -> dict:
        from .. import skill_eval
        return self._skill_loop(lambda: {"trial": skill_eval.start_trial(self.p, body.get("proposal")), "status": skill_eval.trial_status(self.p, str((body.get("proposal") or {}).get("skill") or ""))})

    def skill_trial_close(self, body: dict) -> dict:
        from .. import skill_eval
        return self._skill_loop(lambda: skill_eval.close_trial(self.p, str(body.get("skill") or ""), body.get("force") or None))

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
        auto_cycle = bool(body.get("auto_cycle", False)) and isolated and mode == "act"
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

        def _extract_citations(search_root: Path, steps: list[dict], text: str) -> list[str]:
            seen: list[str] = []
            resolved_root = search_root.resolve()

            def _add(raw_path: str, line_num: str | int | None = None) -> None:
                rel = raw_path.strip().lstrip("./")
                if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                    return
                try:
                    cand = (resolved_root / rel).resolve()
                    if not cand.is_file() or (resolved_root not in cand.parents and cand != resolved_root):
                        return
                except OSError:
                    return
                cite = f"{rel}:{line_num}" if line_num else rel
                if cite not in seen and len(seen) < 8:
                    seen.append(cite)

            for st in steps:
                raw_in = str(st.get("input") or "")
                try:
                    parsed = json.loads(raw_in) if raw_in.startswith("{") else {}
                except ValueError:
                    parsed = {}
                if isinstance(parsed, dict) and isinstance(parsed.get("path"), str):
                    _add(parsed["path"], parsed.get("start_line") or None)
                name = str(st.get("name") or "")
                if ":" in name and not name.startswith("Shell"):
                    maybe_path = name.split(":", 1)[1].strip()
                    if maybe_path:
                        _add(maybe_path)
            for m_cite in re.finditer(r"(?<![\w/.-])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.[A-Za-z0-9]{1,8})(?::(\d{1,6}))?", text or ""):
                _add(m_cite.group(1), m_cite.group(2))
            return seen

        def _turn_cost_tier(prov: str, mod: str, agent_obj) -> str:
            if agent_obj is not None:
                return scouting.cost_tier(agent_obj)
            if prov == "ollama":
                return "free"
            preset = providers.API.get(prov) or providers.PRESETS.get(prov) or {}
            if mod.endswith(":free") or mod in (preset.get("free_models") or ()):
                return "free"
            return "paid"

        def _turn_family(prov: str, agent_obj) -> str:
            if agent_obj is not None:
                return orchestrator.family(agent_obj) or "tool"
            if prov == "ollama":
                return "local"
            if prov in ("claude", "codex", "agy", "opencode"):
                return prov
            return "api"

        def work():
            t0_run = time.monotonic()
            try:
                try:
                    run.execute()
                except Exception as exc:
                    with run._lock:
                        run.error = run.error or f"{type(exc).__name__}: {str(exc)[:300]}"
                result = run.snapshot()
                dur_ms = result.get("duration_ms")
                if dur_ms is None:
                    dur_ms = round((time.monotonic() - t0_run) * 1000)
                try:
                    diff_text = worktrees.workspace_diff(exec_root, max_bytes=16384).get("diff") or None
                except Exception:
                    diff_text = None
                if diff_text:
                    run.diff_text = diff_text
                cycle_res = None
                if auto_cycle and wt_info and diff_text and not result.get("error") and not result.get("cancelled"):
                    try:
                        used_mod = result.get("model") or model
                        used_prov = result.get("provider") or provider
                        cycle_author = (result.get("queue") if not direct_exec else None) or next(
                            (n for n, a in project.agents.items() if (a.model or "") == used_mod),
                            None,
                        ) or f"{used_prov}:{used_mod}"
                        cycle_res = cycle.run_cycle(project, wt_info["key"], cycle_author, apply=None, factory=self.orch_factory)
                        run.cycle_result = cycle_res
                    except Exception as exc:
                        cycle_res = {"status": "error", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
                        run.cycle_result = cycle_res
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
                        used_mod = result.get("model") or model
                        used_prov = (a_info.provider if a_info and a_info.provider else result.get("provider") or provider if direct_exec else target_kind)
                        reply_msg = {
                            "id": "reply-" + run.id,
                            "role": "assistant",
                            "content": reply_text,
                            "timestamp": time.time(),
                            "model": used_mod,
                            "provider": used_prov,
                            "family": _turn_family(used_prov, a_info),
                            "cost_tier": _turn_cost_tier(used_prov, used_mod, a_info),
                            "duration_ms": dur_ms,
                            "target_kind": target_kind,
                            "target": target,
                            "agent": role,
                            "tool_steps": result["steps"],
                            "citations": _extract_citations(exec_root, result["steps"], reply_text),
                            "questions": result.get("questions") or [],
                            "run_id": run.id,
                            "diff": diff_text,
                        }
                        if cycle_res is not None:
                            reply_msg["cycle"] = cycle_res
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
        if getattr(run, "cycle_result", None):
            snap["cycle"] = run.cycle_result
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
        scout = body.get("scout", "auto")
        if scout is not None and not isinstance(scout, str):
            raise app.ConfigError("scout must be an agent name, auto or off")
        orch_model = body.get("orchestrator_model")
        if orch_model is not None and not isinstance(orch_model, str):
            raise app.ConfigError("orchestrator_model must be a model name")
        agent_models = body.get("agent_models")
        if agent_models is not None and not isinstance(agent_models, dict):
            raise app.ConfigError("agent_models must be a mapping of agent -> model")
        plan = orchestrator.plan_orchestration(
            self.p, goal, name, pool, self.orch_factory, scout,
            orchestrator_model=orch_model, agent_models=agent_models,
        )
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
            run = orchestrator.OrchestrationRun(project, plan, session_id=sid, factory=self.orch_factory, cycle=bool(body.get("auto_cycle", False)))
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
                orch_agent = project.agents.get(plan["orchestrator"])
                orch_fam = orchestrator.family(orch_agent) or "tool" if orch_agent else "api"
                orch_tier = scouting.cost_tier(orch_agent) if orch_agent else "paid"
                scout_used = plan.get("scout") if any(s.get("brief") for s in (snap.get("orchestration") or {}).get("subtasks") or []) else None
                with self.session_lock:
                    if any(s.get("id") == sid for s in self._sessions(root)):
                        msgs = self._read_json(root / ".harness" / f"{sid}.json", [])
                        msgs.append({"id": "reply-" + run.id, "role": "assistant", "content": snap["answer"] or snap["error"] or "Stopped waiting.",
                                     "timestamp": time.time(), "model": snap["model"], "provider": "orchestrator", "family": orch_fam, "cost_tier": orch_tier,
                                     "duration_ms": snap.get("duration_ms"), "scout_agent": scout_used, "target_kind": "orchestrate",
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
                "model": providers.model_of(a.command, a.provider, a.model, a.system),
                "family": orchestrator.family(a),
                "command": " ".join(a.command),
                "timeout": a.timeout,
                "pending": sum(1 for t in tasks if t["queue"] == a.name and t["status"] == "pending"),
                "working": sum(1 for t in tasks if t["agent"] == a.name and t["status"] == "sending"),
                "test": orchestrator.family(a) is None,   # a plain command (cat, a script): a test engine, hidden from the pickers until it has work
                "effort": a.effort,
                "effort_support": dict(zip(("supported", "reason"), providers.effort_support(a.command, a.provider))),
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
            "running_tasks": sorted(self.running_tasks),
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
        effort = body.get("effort") or None
        if effort is not None and effort not in providers.EFFORTS:
            raise app.ConfigError(f"effort must be one of {', '.join(providers.EFFORTS)}, or empty for the agent's default")
        tid, queue, why = app.add_task(self.p, text, body.get("queue") or None, body.get("skill") or None, body.get("tier") or None, effort)
        return {"id": tid, "queue": queue, "why": why}

    def review(self, tid: int, body: dict) -> dict:
        verdict = body.get("verdict")
        if verdict not in VERDICTS:
            raise app.ConfigError(f"verdict must be one of {', '.join(VERDICTS)}")
        note = clean_note(body.get("note"))
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

    def reorder(self, tid: int, body: dict) -> dict:
        """Places a task that has not been sent just before another one of its own queue, or last in that queue."""
        before = body.get("before")
        if before is not None and (isinstance(before, bool) or not isinstance(before, int)):
            raise app.ConfigError("before must be a task id, or null for the end of the queue")
        r = self.p.board.get(tid)
        if not r:
            raise NotFound(f"no task {tid}")
        if r["status"] != "pending":
            raise app.ConfigError("only a task that has not been sent can be reordered")
        if before is not None:
            o = self.p.board.get(before)
            if not o or o["status"] != "pending" or o["queue"] != r["queue"]:
                raise app.ConfigError("a task is reordered inside its own queue, against a task that has not been sent")
        return {"id": tid, "before": before, "moved": self.p.board.reorder(tid, before)}

    def run_task(self, tid: int, wait: bool = False) -> dict:
        """Runs one pending task now, alone: nothing else in the queues is sent."""
        r = self.p.board.get(tid)
        if not r:
            raise NotFound(f"no task {tid}")
        if r["status"] != "pending":
            raise app.ConfigError(f"task {tid} was already sent")
        if r["queue"] == app.PERSON:
            raise app.ConfigError(f"task {tid} waits for a person: it is not run by an agent")
        if r["queue"] not in self.p.agents:
            raise app.ConfigError(f"no agent {r['queue']} in {app.CONFIG}")
        with self.p._mu:
            taken = tid in self.p._reserved or tid in self.running_tasks
            busy = r["queue"] in self.p._busy
            if not taken and not busy:
                self.running_tasks.add(tid)
        if taken:
            raise app.ConfigError(f"task {tid} is already being run")
        if busy:
            raise app.ConfigError(f"{r['queue']} is busy with another task: run this one when it finishes")

        def work():
            try:
                res = app.run_task(self.p, tid, self.task_dispatcher)
                self.last_run = [{k: res[k] for k in ("id", "agent", "ok", "reason")}]
            except Exception as e:
                self.last_run = [{"id": tid, "agent": r["queue"], "ok": False, "reason": type(e).__name__}]
            finally:
                with self.p._mu:
                    self.running_tasks.discard(tid)
                self._changed("board")

        th = threading.Thread(target=work, daemon=True)
        th.start()
        self._changed("board")
        if wait:
            th.join()
        return {"started": True, "id": tid}

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


def make_handler(api: Api, token: str | None = None, desktop_mode: bool = False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "caos-harness"
        timeout = 30

        def log_message(self, *a):
            pass

        def cors_headers(self) -> None:
            if not desktop_mode:
                return
            origin = self.headers.get("Origin")
            if origin and desktop.is_allowed_origin(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Harness, X-Harness-Token, Authorization")
                self.send_header("Access-Control-Max-Age", "600")

        def security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", CSP)
            self.cors_headers()

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
            origin = self.headers.get("Origin")
            if desktop_mode and origin and not desktop.is_allowed_origin(origin):
                self.send_json(403, {"error": "origin not allowed"})
                return False
            if write and self.headers.get("X-Harness") != "1":
                self.send_json(403, {"error": "missing X-Harness header"})
                return False
            path, _, query_str = self.path.partition("?")
            if token and path.startswith("/api/"):
                q_token = (urllib.parse.parse_qs(query_str).get("token") or [None])[0]
                if not desktop.token_matches(token, self.headers.get("X-Harness-Token"), self.headers.get("Authorization"), q_token):
                    self.send_json(401, {"error": "unauthorized"})
                    return False
            return True

        def do_OPTIONS(self):
            if not LOOPBACK.match(self.headers.get("Host", "")):
                return self.send_json(403, {"error": "loopback only"})
            origin = self.headers.get("Origin")
            if not desktop_mode or not origin or not desktop.is_allowed_origin(origin):
                return self.send_json(403, {"error": "origin not allowed"})
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.security_headers()
            self.end_headers()

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
            if path == "/api/missions":
                return self.send_json(200, api.missions())
            if path == "/api/skills/evidence":
                return self.send_json(200, api.skills_evidence())
            if path == "/api/run/overview":
                try:
                    since = float((query.get("since") or ["0"])[0])
                except ValueError:
                    since = 0.0
                return self.send_json(200, api.run_overview(since))
            if path == "/api/landed/diff":
                return self.send_json(200, api.landed_diff())
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
            if path == "/api/detect":
                return self.send_json(200, api.detect((query.get("path") or [None])[0]))
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
                if path == "/api/agents/effort":
                    return self.send_json(200, api.set_agent_effort(body))
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
                if path == "/api/landed/undo":
                    return self.send_json(200, api.landed_undo(body))
                if path == "/api/cycle/run":
                    return self.send_json(200, api.cycle_run(body))
                if path == "/api/skills/propose":
                    return self.send_json(200, api.skill_propose(body))
                if path == "/api/skills/trial/start":
                    return self.send_json(201, api.skill_trial_start(body))
                if path == "/api/skills/trial/close":
                    return self.send_json(200, api.skill_trial_close(body))
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
                if path == "/api/detect/apply":
                    return self.send_json(200, api.detect_apply(body))
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
                m_one = re.fullmatch(r"/api/task/(\d+)/(run|reorder)", path)
                if m_one:
                    tid = int(m_one.group(1))
                    return self.send_json(202, api.run_task(tid)) if m_one.group(2) == "run" else self.send_json(200, api.reorder(tid, body))
                m = re.fullmatch(r"/api/task/(\d+)/(review|discard)", path)
                if m:
                    tid = int(m.group(1))
                    return self.send_json(200, api.review(tid, body) if m.group(2) == "review" else api.discard(tid))
            except NotFound as e:
                return self.send_json(404, {"error": str(e)})
            except app.ConfigError as e:
                return self.send_json(409, {"error": str(e)})
            self.send_json(404, {"error": "unknown endpoint"})

    return Handler


def make_server(
    project: app.Project,
    port: int = 8791,
    token: str | None = None,
    desktop_mode: bool = False,
) -> ThreadingHTTPServer:
    api = Api(project)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(api, token=token, desktop_mode=desktop_mode))
    httpd.daemon_threads = True
    httpd.api = api  # type: ignore[attr-defined]
    return httpd


def serve(
    project: app.Project,
    port: int = 8791,
    token: str | None = None,
    desktop_mode: bool = False,
) -> int:
    if desktop_mode:
        desktop.ensure_user_path()
    httpd = make_server(project, port, token=token, desktop_mode=desktop_mode)
    actual_port = httpd.server_address[1]
    if desktop_mode:
        print(desktop.format_ready_line(actual_port, desktop=True), flush=True)
    print(f"caos-harness · {project.root.name} · http://127.0.0.1:{actual_port}  (Ctrl-C to stop)", flush=True)
    if desktop_mode:
        desktop.install_shutdown_handlers()
        desktop.watch_parent()
    try:
        httpd.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        print()
    finally:
        api = getattr(httpd, "api", None)
        if api is not None:
            api.shutdown()
        httpd.server_close()
    return 0
