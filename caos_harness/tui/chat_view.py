"""Unified 5-tab CAOS terminal workspace starting in Chat (`caos-harness`)."""
from __future__ import annotations

import json
import shlex
import threading
import time
import urllib.request

from .. import app, chat, metrics, providers, share, skills
from ..router.route import choose
from . import board_view, extra_views
from .common import (
    FRAMES,
    Item,
    Row,
    TerminalWatch,
    _agent_desc,
    _popup_window,
    _too_small,
    _wrapper,
    box_rows,
    clip,
    git_branch,
    git_touched,
    load_settings,
    new_id,
    pad,
    save_settings,
    sessions_dir,
    skill_rows,
    wrap,
)
from .theme import SKINS, apply_curses_skin, draw_rows

CHAT_HELP = [
    ("Enter", "send prompt or execute /command"),
    ("@path", "attach a file from this folder"),
    ("Tab", "switch Plan (Steel, read-only) ↔ Act (Amber, edit/shell)"),
    ("F1..F5", "switch tabs: 1 Chat · 2 Board · 3 Proveedores · 4 Métricas · 5 Skills/Share"),
    ("Ctrl-P", "choose intent, provider, agent, router tier, or local model"),
    ("Ctrl-L", "toggle side inspector panel (auto-shown when w ≥ 120)"),
    ("Ctrl-B", "toggle Chat ↔ Board"),
    ("y / t / n", "approve step / approve & trust session / reject step"),
    ("Esc", "close popup or cancel running request"),
    ("Ctrl-S / N", "resume previous session / start a new session"),
    ("Ctrl-T", "cycle terminal color skin (night / ember / mono)"),
]


def ollama_models() -> list[str]:
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "caos-harness"})
        with urllib.request.urlopen(req, timeout=1.0) as r:
            return sorted(m["name"] for m in json.loads(r.read().decode()).get("models", []) if "embed" not in m["name"].lower())
    except Exception:
        return []


class ChatUI:
    """Unified 5-tab interactive workspace: 1 Chat · 2 Board · 3 Proveedores · 4 Métricas · 5 Skills/Share."""

    # Preserve exact `s*` alphabetical commands (`sessions`, `side`, `skill`, `skills`, `skin`) for slash completion tests.
    COMMANDS = {
        "accept": "accept last delivery (<why>)",
        "agent": "choose an agent from harness.toml",
        "board": "switch to Tab 2: Board",
        "chat": "switch to Tab 1: Chat",
        "clear": "clear visible transcript",
        "commands": "turn shell permissions on|off for Act mode",
        "density": "relaxed or compact spacing",
        "doctor": "scan workspace for leaked keys/local paths",
        "export": "save current transcript to Markdown",
        "help": "show keyboard shortcuts",
        "hints": "full, minimal or none footer hints",
        "intent": "route by intent: rapido | codigo | razonar | local",
        "metrics": "switch to Tab 4: Métricas",
        "mode": "switch plan | act",
        "model": "choose an Ollama model",
        "new": "start a new chat session",
        "pack": "build a sanitized Share Pack .zip",
        "probe": "run a live smoke test on the active target",
        "provider": "choose a connected cloud/local provider",
        "providers": "switch to Tab 3: Proveedores",
        "quit": "save session and exit",
        "return": "return last delivery (<note>)",
        "run": "run pending tasks on the board",
        "sessions": "resume a saved chat session",
        "side": "toggle side panel (Ctrl-L)",
        "skill": "load a skill before prompts (`none` clears)",
        "skills": "list or pick available skills",
        "skin": "switch night | ember | mono",
        "team": "switch to Tab 5: Skills & Share",
        "tier": "let policy router pick by cost of error",
        "verify": "ask for evidence on last delivery",
        "worktree": "show git worktree & branch status",
    }

    VIEWS = [
        ("chat", "1 Chat"),
        ("board", "2 Board"),
        ("providers", "3 Prov"),
        ("metrics", "4 Métr"),
        ("skills", "5 Skills/Share"),
    ]

    def __init__(self, p: app.Project, models=None):
        self.p = p
        self.conv = chat.Conversation(p)
        self.board = board_view.State(p)
        self.view = "chat"
        self.text = ""
        self.history: list[str] = []
        self.hist_i = -1
        self.scroll = 0
        self.popup: str | None = None
        self.items: list = []
        self.pick_i = 0
        self.message = ""
        self.qa_pick: dict[int, int] = {}   # Plan Q&A: which chip each question is on (keys 1-4)
        self.qa_turn: int | None = None     # the Plan turn the picks belong to
        self.qa_text = ""                   # what the keys wrote into the composer, so a second press knows it is still theirs
        self.session_id = ""
        self.quit = False
        self.last_ctrl_c = 0.0
        cfg = load_settings()
        self.side = cfg.get("side", True) is not False
        self.skin = cfg.get("skin") if cfg.get("skin") in SKINS else "night"
        self.density = cfg.get("density") if cfg.get("density") in ("relaxed", "compact") else "relaxed"
        self.hints = cfg.get("hints") if cfg.get("hints") in ("full", "minimal", "none") else "full"
        self._models = models
        self._max_scroll: int | None = None
        self._meta_at: float = -10.0
        self._meta_sig: tuple = ()
        self._touched_cache: list[str] | None = None
        self._branch_cache: str = "local"
        self._skills_cache: list[str] = list(skills.load_all(project_root=p.root))
        self.extra_sel: dict[str, int] = {"providers": 0, "metrics": 0, "skills": 0}
        self.metrics_scope = "project"
        self.last_probe: dict | None = None
        self.last_smoke: dict | None = None
        self.doctor_res: dict | None = None
        self.pack_res: dict | None = None
        if self.conv.name == app.PERSON and not p.agents:
            self.message = "No agent selected · Ctrl-P picks an intent, provider or local model"

    # ── persistence ──────────────────────────────────────────────────────────
    def sdir(self) -> Path:
        return sessions_dir(self.p) / "chat"

    def save(self) -> None:
        if not self.session_id:
            return
        try:
            d = self.sdir()
            d.mkdir(parents=True, exist_ok=True)
            data = self.conv.to_json()
            data.update({
                "id": self.session_id,
                "history": self.history[-100:],
                "title": next((t.text for t in self.conv.turns if t.role == "user"), "")[:60],
            })
            (d / f"{self.session_id}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def new_session(self) -> None:
        self.save()
        self.conv = chat.Conversation(self.p)
        self.session_id = new_id()
        self.scroll = 0
        self.message = "new session"
        self.save()

    def resume(self, sid: str | None) -> bool:
        d = self.sdir()
        files = sorted(d.glob("*.json")) if d.is_dir() else []
        pick = next((f for f in files if f.stem == sid), None) if sid else (files[-1] if files else None)
        if not pick:
            return False
        try:
            data = json.loads(pick.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        self.conv = chat.Conversation(self.p)
        self.conv.from_json(data)
        self.history = [str(x) for x in data.get("history", [])][-100:]
        self.session_id = pick.stem
        self.scroll = 0
        self.message = f"resumed {pick.stem}"
        return True

    def sessions(self) -> list:
        d = self.sdir()
        out = []
        for f in sorted(d.glob("*.json"), reverse=True)[:12] if d.is_dir() else []:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                out.append(Item(f.stem, data.get("title") or "(no prompt yet)", f"{len(data.get('turns', []))} turns · {data.get('target', ['', ''])[1]}"))
            except (OSError, ValueError):
                continue
        return out

    def settings(self) -> None:
        save_settings({**load_settings(), "skin": self.skin, "side": self.side, "density": self.density, "hints": self.hints})

    # ── pickers ──────────────────────────────────────────────────────────────
    def choices(self) -> list:
        items: list[Item] = []
        models = self._models if self._models is not None else ollama_models()
        for intent_key in providers.INTENTS:
            res = providers.resolve_intent(intent_key, root=self.p.root, local_models=models)
            items.append(Item(f"intent:{intent_key}", f"intent · {intent_key}", f"→ {res['provider']} · {res['model']}"))
        for a in self.p.agents.values():
            items.append(Item(f"agent:{a.name}", f"{a.name}", _agent_desc(a)))
        for t, need in self.board.tiers.items():
            d = choose(self.board.profiles, need) if self.board.profiles else None
            items.append(Item(f"tier:{t}", f"router · cost of error {t}", "→ " + ((d.system if d and d.action == "route" else "a person") if d else "?")))
        for pid, spec in providers.API.items():
            try:
                k, _ = providers.key_for(pid, root=self.p.root)
            except providers.ProviderError:
                k = None
            if k:
                items.append(Item(f"provider:{pid}:{spec['default_model']}", f"provider · {pid}", spec["default_model"]))
        items.append(Item("agent:person", "a person", "no agent is asked"))
        measured = {x.system.split("+")[0]: x for x in self.board.profiles}
        for m in models:
            prof = measured.get(m)
            items.append(Item(f"model:{m}", f"ollama · {m}", f"{prof.precision * 100:.0f}% precise · lo {prof.precision_lo * 100:.0f}%" if prof else "local model"))
        return items

    def suggest(self) -> list[str]:
        if not self.text.startswith("/") or " " in self.text:
            return []
        typed = self.text[1:].lower()
        return sorted(name for name in self.COMMANDS if name.startswith(typed))

    # ── commands ─────────────────────────────────────────────────────────────
    def command(self, line: str) -> None:
        try:
            parts = shlex.split(line)
        except ValueError as e:
            self.message = f"error: {e}"
            return
        if not parts:
            return
        cmd, rest = parts[0].lower().lstrip("/"), parts[1:]
        c = self.conv
        if cmd in ("quit", "q", "exit"):
            self.quit = True
        elif cmd == "help":
            self.popup = "help"
        elif cmd == "chat":
            self.view = "chat"
        elif cmd == "board":
            self.board.refresh()
            self.view = "board"
        elif cmd == "providers":
            self.view = "providers"
        elif cmd == "metrics":
            self.view = "metrics"
        elif cmd in ("team", "share"):
            self.view = "skills"
        elif cmd == "doctor":
            self.doctor_res = share.doctor(self.p.root)
            n = len(self.doctor_res["issues"])
            self.message = "Doctor limpio: 0 fugas detectadas" if self.doctor_res["clean"] else f"Doctor detectó {n} alerta(s)"
        elif cmd == "pack":
            fmt = "dir" if rest and rest[0] == "dir" else "zip"
            self.pack_res = share.build_share_pack(self.p.root, fmt=fmt)
            self.message = f"Share Pack creado: {self.pack_res['filename']}"
        elif cmd in ("probe", "smoke"):
            prov = rest[0] if rest else (c.provider or ("ollama" if c.kind == "model" else "ollama"))
            mod = rest[1] if len(rest) > 1 else c.name
            if not mod or c.kind in ("agent", "tier"):
                mods = self._models if self._models is not None else ollama_models()
                mod = mods[0] if mods else "qwen2.5:7b"
            self.last_smoke = providers.smoke_test(prov, mod, root=self.p.root)
            self.message = f"Smoke {'OK' if self.last_smoke['ok'] else 'FAIL'} · {prov} {mod} ({self.last_smoke['latency_ms']}ms)"
        elif cmd == "intent":
            if rest and rest[0] in providers.INTENTS:
                c.set_target("intent", rest[0])
                res = providers.resolve_intent(rest[0], root=self.p.root, local_models=self._models)
                self.message = f"intent {rest[0]} → {res['provider']} · {res['model']}"
            else:
                self.popup, self.items, self.pick_i = "picker", [x for x in self.choices() if x.key.startswith("intent:")], 0
        elif cmd == "provider":
            if rest:
                pid = rest[0]
                mod = rest[1] if len(rest) > 1 else providers.PRESETS.get(pid, {}).get("default_model", "")
                c.set_target("provider", f"{pid}:{mod}" if mod else pid)
                self.message = f"provider {pid}" + (f" · {mod}" if mod else "")
            else:
                self.popup, self.items, self.pick_i = "picker", self.choices(), 0
        elif cmd in ("model", "agent", "tier"):
            if rest:
                name = rest[0]
                if cmd == "agent" and (name in self.p.agents or name == "person"):
                    c.set_target("agent", name); self.message = f"target: {name}"
                elif cmd == "tier" and name in self.board.tiers:
                    c.set_target("tier", name); self.message = f"target: router, cost of error {name}"
                elif cmd == "model":
                    c.set_target("model", name); self.message = f"target: ollama {name}"
                else:
                    self.message = f"no {cmd} {name}"
            else:
                self.popup, self.items, self.pick_i = "picker", self.choices(), 0
        elif cmd == "mode":
            self.message = c.set_mode(rest[0]) if rest and rest[0] in ("plan", "act") else "mode plan or act"
        elif cmd == "commands":
            on = bool(rest) and rest[0] == "on"
            c.set_commands(on)
            self.message = "shell commands ON for this session: each one asks first, and runs with your permissions" if on else "shell commands off"
        elif cmd == "worktree":
            self.message = f"branch {git_branch(self.p)} · {len(git_touched(self.p) or [])} modified file(s)"
        elif cmd == "skill":
            if not rest or rest[0] == "none":
                c.skill = None; self.message = "no skill"
            elif skills.known(rest[0]):
                c.skill = rest[0]; self.message = f"skill {rest[0]}"
            else:
                self.message = f"no skill {rest[0]}"
        elif cmd == "skills":
            self.popup, self.pick_i = "skills", 0
            all_sk = skills.load_all(project_root=self.p.root)
            self.items = [Item(x.name, x.name + (" ✓" if c.skill == x.name else ""), f"[{x.category}] " + clip(x.description, 60)) for x in all_sk.values()]
        elif cmd == "new":
            self.new_session()
        elif cmd in ("sessions", "resume"):
            if rest:
                self.message = "resumed" if self.resume(rest[0]) else f"no session {rest[0]}"
            else:
                self.popup, self.items, self.pick_i = "sessions", self.sessions(), 0
                if not self.items:
                    self.popup, self.message = None, "no earlier sessions yet"
        elif cmd == "export":
            path = self.p.root / f"conversation-{self.session_id or 'now'}.md"
            path.write_text(c.markdown(), encoding="utf-8")
            self.message = f"exported to {path.name}"
        elif cmd == "side":
            self.side = not self.side; self.settings()
        elif cmd == "density":
            self.density = rest[0] if rest and rest[0] in ("relaxed", "compact") else ("compact" if self.density == "relaxed" else "relaxed")
            self.settings(); self.message = f"density: {self.density}"
        elif cmd == "hints":
            self.hints = rest[0] if rest and rest[0] in ("full", "minimal", "none") else {"full": "minimal", "minimal": "none", "none": "full"}[self.hints]
            self.settings(); self.message = f"hints: {self.hints}"
        elif cmd == "skin":
            names = list(SKINS)
            self.skin = rest[0] if rest and rest[0] in SKINS else names[(names.index(self.skin) + 1) % len(names)]
            self.settings(); self.message = f"skin: {self.skin}"
        elif cmd in ("accept", "return", "verify"):
            last = next((t for t in reversed(c.turns) if t.role == "agent" and t.task and t.status == "done"), None)
            if not last:
                self.message = "no delivery to review"
            else:
                v = {"accept": "ok", "return": "redo", "verify": "verify"}[cmd]
                note = " ".join(rest)
                if v in ("redo", "ok") and not note.strip():
                    self.message = "a return needs a note: /return <what to fix>" if v == "redo" else "an accept needs a reason: /accept <why>"
                else:
                    ok = self.p.board.review(last.task, v, note)
                    self.message = f"task {last.task}: {v}" if ok else f"task {last.task} does not accept '{v}' now"
        elif cmd == "run":
            self.board.run_pending(); self.message = self.board.message
        elif cmd == "clear":
            c.turns = []; c.version += 1
        else:
            self.message = f"unknown command /{cmd}; /help lists them"

    # ── keys ─────────────────────────────────────────────────────────────────
    def _switch_extra_key(self, k: str) -> bool:
        if k == "f1" or k == "alt-1": self.view = "chat"; return True
        if k == "f2" or k == "alt-2": self.board.refresh(); self.view = "board"; return True
        if k == "f3" or k == "alt-3": self.view = "providers"; return True
        if k == "f4" or k == "alt-4": self.view = "metrics"; return True
        if k == "f5" or k == "alt-5": self.view = "skills"; return True
        return False

    def plan_questions(self) -> list[dict] | None:
        """The open alignment questions of a Plan turn, when keys 1-4 may answer them: Plan mode, the last turn asked, nothing is
        running or waiting for an approval, and no popup is open."""
        c = self.conv
        if self.view != "chat" or self.popup or c.mode != "plan" or c.busy() or not c.turns:
            return None
        last = c.turns[-1]
        qs = [q for q in (getattr(last, "questions", None) or []) if isinstance(q, dict)][:4]
        return qs or None

    def answer_question(self, n: int, qs: list[dict]) -> None:
        """Key `n` moves question `n` to its next option (the first on the first press) and writes every pick into the composer,
        to be read and sent with Enter."""
        if n > len(qs):
            self.message = f"there is no question {n}"
            return
        chips = [str(x) for x in (qs[n - 1].get("chips") or [])] or ["Yes", "No"]
        self.qa_pick[n] = (self.qa_pick[n] + 1) % len(chips) if n in self.qa_pick else 0
        parts = []
        for i in sorted(self.qa_pick):
            opts = [str(x) for x in (qs[i - 1].get("chips") or [])] or ["Yes", "No"]
            parts.append(f"{qs[i - 1].get('question', '')}: {opts[self.qa_pick[i] % len(opts)]}")
        self.text = self.qa_text = "Alignment answers: " + "; ".join(parts)
        self.message = f"question {n}: [{chips[self.qa_pick[n]]}] · 1-{len(qs)} change an answer · Enter sends"

    def key(self, k: str) -> None:
        if self._switch_extra_key(k):
            self._meta_at = -10.0
            return
        if self.view == "board":
            if k == "ctrl-b" or (k == "esc" and self.board.mode == "list"):
                self.view = "chat"; self._meta_at = -10.0
            else:
                self.board.key(k)
                if self.board.quit:
                    self.board.quit = False; self.view = "chat"; self._meta_at = -10.0
            return
        if self.view in ("providers", "metrics", "skills"):
            if k == "esc" or k == "q":
                self.view = "chat"; return
            if k in ("1", "2", "3", "4", "5"):
                target_v = self.VIEWS[int(k) - 1][0]
                if target_v == "board":
                    self.board.refresh()
                self.view = target_v
                return
            if k in ("j", "down"):
                self.extra_sel[self.view] = self.extra_sel.get(self.view, 0) + 1; return
            if k in ("k", "up"):
                self.extra_sel[self.view] = max(0, self.extra_sel.get(self.view, 0) - 1); return
            self._handle_extra_action(k)
            return

        c = self.conv
        if self.popup:
            if k in ("down", "j"): self.pick_i = min(max(0, len(self.items) - 1), self.pick_i + 1)
            elif k in ("up", "k"): self.pick_i = max(0, self.pick_i - 1)
            elif k == "esc" or self.popup == "help": self.popup = None
            elif k == "enter" and self.items:
                it = self.items[self.pick_i]
                kind = self.popup
                self.popup = None
                if kind == "picker":
                    t, _, n = it.key.partition(":")
                    if t == "provider":
                        pid, _, mod = n.partition(":")
                        c.set_target("provider", mod or pid, provider=pid)
                    else:
                        c.set_target(t, n)
                    self.message = f"target: {it.label}"
                elif kind == "sessions":
                    self.save(); self.resume(it.key)
                elif kind == "skills":
                    c.skill = it.key; self.message = f"skill {it.key}: new messages load it first"
            return

        awaiting = any(t.status == "awaiting" for t in c.turns)
        if awaiting and not self.text and k in ("y", "n", "t"):
            if k == "t":
                self.message = "approved & trusted for this session" if c.approve(True, trust_session=True) else "nothing waits"
            else:
                self.message = ("command approved" if k == "y" else "command rejected") if c.approve(k == "y") else "nothing waits for a decision"
            return

        qa = self.plan_questions()
        qid = id(c.turns[-1]) if qa is not None else None
        if qid != self.qa_turn or (self.qa_pick and self.text != self.qa_text):
            self.qa_pick, self.qa_text, self.qa_turn = {}, "", qid   # a new turn, or the composer was edited or cleared: the picks are no longer its
        if qa is not None and k in ("1", "2", "3", "4") and (not self.text or self.text == self.qa_text):
            self.answer_question(int(k), qa)
            return

        if k == "esc":
            if c.busy(): c.stop_waiting(); self.message = "stopped waiting"
            else: self.text = ""
        elif k == "enter":
            line, self.text = self.text.strip(), ""
            self.qa_pick, self.qa_text = {}, ""
            if line:
                self.history.append(line); self.hist_i = -1
                if line.startswith("/"):
                    self.command(line[1:])
                else:
                    msg = c.send(line)
                    if msg:
                        self.message = msg
                    if not self.session_id:
                        self.session_id = new_id()
                    self.scroll = 0; self.save()
        elif k == "backspace":
            self.text = self.text[:-1]
        elif k == "ctrl-u":
            self.text = ""
        elif k == "tab":
            hits = self.suggest()
            if hits:
                self.text = f"/{hits[0]} "
            elif not self.text:
                self.message = c.set_mode("act" if c.mode == "plan" else "plan")
        elif k == "?":
            if not self.text: self.popup = "help"
            else: self.text += "?"
        elif k == "up" and self.history:
            self.hist_i = len(self.history) - 1 if self.hist_i < 0 else max(0, self.hist_i - 1)
            self.text = self.history[self.hist_i]
        elif k == "down" and self.history and self.hist_i >= 0:
            self.hist_i += 1
            self.text = self.history[self.hist_i] if self.hist_i < len(self.history) else ""
            if self.hist_i >= len(self.history): self.hist_i = -1
        elif k == "pgup":
            cap = self._max_scroll if self._max_scroll is not None else self.scroll + 6
            self.scroll = min(cap, self.scroll + 6)
        elif k == "pgdn":
            self.scroll = max(0, self.scroll - 6)
        elif k == "ctrl-p":
            self.popup, self.items, self.pick_i = "picker", self.choices(), 0
        elif k == "ctrl-a":
            last = next((t for t in reversed(c.turns) if t.role == "agent" and t.task and t.status == "done"), None)
            if last: self.text = "/accept "
            else: self.message = "no finished agent task in this session yet"
        elif k == "ctrl-b":
            self.board.refresh(); self.view = "board"
        elif k == "ctrl-l":
            self.side = not self.side; self.settings()
        elif k == "ctrl-n":
            self.new_session()
        elif k == "ctrl-s":
            self.command("sessions")
        elif k == "ctrl-t":
            self.command("skin")
        elif k == "ctrl-d":
            self.quit = True; self.save()
        elif k == "ctrl-c":
            now = time.monotonic()
            if self.text:
                self.text = ""
            elif c.busy():
                c.stop_waiting(); self.message = "stopped waiting"
            elif now - self.last_ctrl_c < 2.0:
                self.quit = True; self.save()
            else:
                self.last_ctrl_c = now; self.message = "Ctrl-C again to exit (session saved)"
        elif len(k) == 1 and k.isprintable():
            self.text += k

    def _handle_extra_action(self, k: str) -> None:
        if self.view == "providers":
            hosts = providers.ollama_hosts(self.p.root)
            ol = providers.probe_ollama(hosts)
            entries = [(e["provider"], e["model"]) for e in extra_views.provider_entries(self.p, ol, hosts)]
            idx = max(0, min(self.extra_sel.get("providers", 0), len(entries) - 1))
            pid, mod = entries[idx]
            if k == "t":
                if pid == "ollama":
                    pr = providers.probe_ollama(hosts)
                    self.last_probe = {"ok": pr["online"], "message": f"{len(pr['models'])} modelos en {len(hosts)} host(s)"}
                else:
                    self.last_probe = providers.test(pid, root=self.p.root)
                self.message = self.last_probe.get("message", "")
            elif k == "s":
                self.last_smoke = providers.smoke_test(pid, mod, root=self.p.root)
                self.message = f"Smoke {'OK' if self.last_smoke['ok'] else 'FAIL'} · {pid} {mod}"
            elif k == "enter":
                if pid == "ollama":
                    self.conv.set_target("model", mod)
                else:
                    self.conv.set_target("provider", f"{pid}:{mod}")
                self.message = f"target → {pid} · {mod}"
                self.view = "chat"
        elif self.view == "metrics":
            if k == "g":
                self.metrics_scope = "global" if self.metrics_scope == "project" else "project"
                self.message = f"scope metrics → {self.metrics_scope}"
            elif k in ("s", "d"):
                snap = metrics.snapshot(self.p, scope=self.metrics_scope)
                mods = snap["models"]
                if mods:
                    idx = max(0, min(self.extra_sel.get("metrics", 0), len(mods) - 1))
                    row = mods[idx]
                    if k == "s":
                        res = providers.smoke_test(row["provider"], row["model"], root=self.p.root)
                        metrics.record_run(self.p.root, row["provider"], row["model"], res.get("latency_ms", 0), res["ok"], kind="smoke")
                        self.message = f"Smoke {'OK' if res['ok'] else 'FAIL'} · {row['model']}"
                    else:
                        metrics.set_demotion(self.p.root, metrics.demotion_key(row["provider"], row["model"]), not row["demoted"])
                        self.message = f"{'Degradado' if not row['demoted'] else 'Restaurado'} {row['model']}"
        elif self.view == "skills":
            all_sk = list(skills.load_all(project_root=self.p.root).values())
            if k == "enter" and all_sk:
                idx = max(0, min(self.extra_sel.get("skills", 0), len(all_sk) - 1))
                self.conv.skill = all_sk[idx].name
                self.message = f"skill activo: {all_sk[idx].name}"
                self.view = "chat"
            elif k == "c":
                self.doctor_res = share.doctor(self.p.root)
                self.message = "Doctor limpio" if self.doctor_res["clean"] else f"{len(self.doctor_res['issues'])} alerta(s)"
            elif k == "p":
                self.pack_res = share.build_share_pack(self.p.root, fmt="zip")
                self.message = f"Share Pack listo: {self.pack_res['filename']}"

    # ── rendering ────────────────────────────────────────────────────────────
    def _header_rows(self, w: int) -> list[Row]:
        c = self.conv
        if self._touched_cache is None or time.monotonic() - self._meta_at > 3.0:
            self._meta_at = time.monotonic()
            self._branch_cache = git_branch(self.p)
            self._touched_cache = git_touched(self.p)
            if not self._skills_cache:
                self._skills_cache = list(skills.load_all(project_root=self.p.root))
        wt = " · git" if self._touched_cache is not None else ""
        left: Row = [(" ", ""), ("◈ caos", "champagne"), (" · " + clip(self.p.root.name, 18), "bone"), (f" [⎇ {clip(self._branch_cache, 14)}{wt}]", "steel")]
        tabs: Row = []
        s = self.board.counts()
        for vid, lbl in self.VIEWS:
            lbl_show = f"2 Board({s['needs_you']})" if vid == "board" and s["needs_you"] else lbl
            if w < 100:
                lbl_show = lbl.split()[0]
            if self.view == vid:
                tabs += [("[" + lbl_show + "] ", "champagne")]
            else:
                tabs += [(" " + lbl_show + "  ", "dim")]
        gap = max(1, w - sum(len(t) for t, _ in left) - sum(len(t) for t, _ in tabs) - 1)
        row1 = pad(left + [(" " * gap, "")] + tabs, w)

        if self.view != "chat":
            mode_line: Row = [(" ", ""), (f"◆ {dict(self.VIEWS).get(self.view, self.view)}", "steelb"), (" · F1..F5 vistas · Ctrl-B Board/Chat · Ctrl-P motor · q volver", "dim")]
            return [row1, pad(mode_line, w), [("─" * w, "silver")]]

        tgt = c.target_label()
        if c.mode == "act":
            right = "PERMISO ACT: lee repo, editar/shell pide y/t/n · Tab→Plan" if w >= 100 else "Tab→Plan"
            m_left: Row = [(" ", ""), ("▶ ACT", "act_bar"), (f" · {clip(tgt, 28)}", "amber")]
        else:
            right = "solo lectura · Tab→Act · Ctrl-P motor" if w >= 100 else "Tab→Act"
            m_left = [(" ", ""), ("◆ PLAN", "plan_bar"), (f" · {clip(tgt, 28)}", "steel")]
        if c.skill:
            m_left += [(f" · skill:{c.skill}", "champagne")]
        gap2 = max(1, w - sum(len(t) for t, _ in m_left) - len(right) - 2)
        row2 = pad(m_left + [(" " * gap2, "")] + [(right, "dim")], w)
        return [row1, row2, [("─" * w, "silver")]]

    def turn_lines(self, cw: int) -> tuple[list[Row], list[int]]:
        """Formats transcript turns using structured CAOS Unicode cards (`Plan` Q&A, `Act` approval)."""
        turns = self.conv.turns
        if not turns:
            return [
                [],
                [("  ◈ caos · harness", "champagne"), ("  agents you can check", "dim")],
                [("  Escribe tu tarea abajo, adjunta archivos con ", "dim"), ("@ruta", "bone"), (" o elige motor con ", "dim"), ("Ctrl-P", "steelb"), (".", "dim")],
                [("  • ", "steel"), ("Plan", "steelb"), (" analiza el código y propone preguntas antes de tocar nada.", "dim")],
                [("  • ", "amber"), ("Act", "amberb"), (" ejecuta cambios paso a paso pidiendo confirmación explícita.", "dim")],
            ], []

        lines: list[Row] = []
        gap = 0 if self.density == "compact" else 1
        unread: list[int] = []
        frame = FRAMES[int(time.monotonic() * 8) % len(FRAMES)]
        card_w = max(30, min(cw - 4, 88))
        for t in turns:
            if t.role == "user":
                lines += [[]] * gap
                lines.append([("  you ", "champagne"), (clip(t.text, cw - 7), "bold")])
                for ln in wrap(t.text, cw - 7)[1:]:
                    lines.append([("      " + ln, "bone")])
                if t.attached:
                    lines.append([("      adjuntos: " + ", ".join(t.attached), "dim")])
                continue
            if t.role == "note":
                lines.append([("  · " + clip(t.text, cw - 5), "dim")])
                continue

            if t.status in ("working", "awaiting") and not t.text and not t.steps:
                lines.append([("  " + frame + " ", "steelb"), ("pensando…", "dim")])
                continue

            head_st = "coralb" if t.status == "failed" else ("amberb" if t.status == "awaiting" else "sageb")
            task_tag = f" · task {t.task}" if t.task else ""
            meta = f"{t.who or 'agent'}{task_tag} · {t.status}"
            lines += [[]] * gap
            lines.append([("  " + clip(meta, cw - 4), head_st)])

            for step in t.steps:
                st = step.get("status", "")
                kind = step.get("kind", "bash")
                st_sym = "✓" if st == "completed" else ("✗" if st in ("failed", "denied", "expired") else ("⚡" if st == "awaiting_approval" else frame))
                st_col = "sage" if st == "completed" else ("coral" if st in ("failed", "denied", "expired") else ("amberb" if st == "awaiting_approval" else "steel"))
                lines.append([("    " + st_sym + " ", st_col), (clip(f"{kind} · {step.get('name', '')}", cw - 10), "steel" if kind == "read" else "bone")])
                if st == "awaiting_approval":
                    card_lines: list[Row] = []
                    if step.get("summary_what"):
                        card_lines.append([("Qué:      ", "amberb"), (clip(step["summary_what"], card_w - 14), "bone")])
                    if step.get("summary_why"):
                        card_lines.append([("Para qué: ", "steel"), (clip(step["summary_why"], card_w - 14), "")])
                    if step.get("summary_goal"):
                        card_lines.append([("Objetivo: ", "steel"), (clip(step["summary_goal"], card_w - 14), "")])
                    raw_in = str(step.get("input") or "")
                    if raw_in:
                        for wline in wrap(raw_in, card_w - 6):
                            card_lines.append([(wline, "bone")])
                    card_lines.append([("not in a sandbox · run it? [y] approve  [t] trust  [n] reject", "champagne")])
                    for row in box_rows("⚡ Aprobación Act requerida", card_lines, card_w, border="amber", title_style="amberb"):
                        lines.append([("    ", "")] + row)
                elif step.get("input") and step.get("name") == "Shell command":
                    for wline in wrap("$ " + str(step["input"]), card_w - 6):
                        lines.append([("      " + wline, "dim")])

            if t.text:
                for ln in wrap(t.text, cw - 6):
                    lines.append([("    " + ln, "coral" if t.status == "failed" else "")])

            qs = [q for q in (t.questions or []) if isinstance(q, dict)]
            if qs:
                q_rows: list[Row] = []
                for idx_q, q in enumerate(qs[:4], 1):
                    q_rows.append([(f"{idx_q}. ", "steelb"), (clip(str(q.get("question", "")), card_w - 8), "bone")])
                    chip_list = (q.get("chips") or [])[:4]
                    if chip_list:
                        live = self.qa_pick.get(idx_q) if t is self.conv.turns[-1] else None
                        runs: Row = [("   ", "")]
                        for ci, ch in enumerate(chip_list):
                            runs.append((f"[{clip(str(ch), 22)}] ", "sageb" if live is not None and live % len(chip_list) == ci else "steel"))
                        q_rows.append(runs)
                for row in box_rows("? Preguntas de alineación (Plan)", q_rows, card_w, border="steel", title_style="steelb"):
                    lines.append([("    ", "")] + row)
        return lines, unread

    def compose(self, w: int, h: int) -> tuple[list[Row], tuple[int, int] | None]:
        header = self._header_rows(w)
        if self.view == "board":
            b_rows, b_cur = board_view.compose(self.board, w, max(12, h - len(header)), embedded=True)
            adj = (b_cur[0] + len(header), b_cur[1]) if b_cur else None
            return (header + b_rows)[:h], adj
        if self.view == "providers":
            body, _ = extra_views.compose_providers_tab(self.p, w, h - len(header), self.extra_sel.get("providers", 0), self.last_probe, self.last_smoke, self.message)
            return (header + body)[:h], None
        if self.view == "metrics":
            body, _ = extra_views.compose_metrics_tab(self.p, self.metrics_scope, w, h - len(header), self.extra_sel.get("metrics", 0), self.message)
            return (header + body)[:h], None
        if self.view == "skills":
            body, _ = extra_views.compose_skills_share_tab(self.p, w, h - len(header), self.extra_sel.get("skills", 0), self.conv.skill, self.doctor_res, self.pack_res, self.message)
            return (header + body)[:h], None

        # Tab 1: Chat (full-width on narrow terminals < 120 cols, side inspector when w >= 120 and self.side)
        rw = 34 if (self.side and w >= 120) else 0
        cw = w - rw - (1 if rw else 0)
        body_h = max(4, h - len(header) - 3)
        tlines, _ = self.turn_lines(cw)
        max_sc = max(0, len(tlines) - body_h)
        self._max_scroll = max_sc
        sc = min(self.scroll, max_sc)
        self.scroll = sc
        start = max(0, len(tlines) - body_h - sc)
        vis = tlines[start : start + body_h]
        while len(vis) < body_h:
            vis.append([])

        rcol: list[Row] = []
        if rw:
            c = self.conv
            ol = self._models if self._models is not None else []
            rcol = [
                [(" Session", "champagne")],
                [("  motor: " + clip(c.target_label(), rw - 10), "steel")],
                [(f"  modo:  {c.mode.upper()}", "amberb" if c.mode == "act" else "steelb")],
                [],
                [(f" Skills · {len(self._skills_cache)}", "bold")],
            ] + skill_rows(self._skills_cache, rw - 3)
            rcol += [[], [(" Git · " + clip(self._branch_cache, 18), "bold")]]
            rcol += [[("  " + clip(t, rw - 3), "dim")] for t in (self._touched_cache or [])] or [[("  sin cambios locales", "dim")]]
            if ol:
                rcol += [[], [(f" Ollama · {len(ol)} local", "bold")]]
            if len(c.queue):
                rcol += [[], [(f" En cola: {len(c.queue)}", "amber")]]
        while len(rcol) < body_h:
            rcol.append([])

        rows = list(header)
        for i in range(body_h):
            row = pad(vis[i][:], cw)
            if rw:
                row += [("│", "silver")] + rcol[i]
            rows.append(row)

        rows.append([("─" * w, "silver")])
        prompt_prefix = " ▶ " if self.conv.mode == "act" else " › "
        p_col = "amberb" if self.conv.mode == "act" else "champagne"
        input_row: Row = [(prompt_prefix, p_col), (self.text[-(w - 6) :], "bone")]
        rows.append(pad(input_row, w))
        cursor = (len(rows) - 1, min(w - 2, len(prompt_prefix) + len(self.text)))

        sug = self.suggest()
        qa_open = self.plan_questions()
        if qa_open and not self.text and not self.message:
            hint_msg = f" 1-{len(qa_open)} answer the plan questions · or just type · F1-F5 views"
        elif sug:
            hint_msg = " Tab completes · " + "  ".join("/" + s for s in sug[:6])
        elif qa_open and not self.message:
            hint_msg = f" 1-{len(qa_open)} answer the plan questions (Enter sends) · Tab Act/Plan"
        elif self.hints == "none":
            hint_msg = " " + self.message
        elif self.hints == "minimal":
            hint_msg = f" Tab modo · Ctrl-P motor · Ctrl-L panel · {self.message}".rstrip()
        else:
            hint_msg = f" F1-F5 vistas · Ctrl-P motor · Ctrl-L panel · Tab Act/Plan · ? ayuda · {self.message}".rstrip()
        rows.append([(clip(hint_msg, w - 1), "dim")])

        if self.popup:
            box_w = min(w - 4, 80)
            if self.popup == "help":
                box: list[Row] = [[("┌─ Keys", "bold"), (" ─" + "─" * max(0, box_w - 11) + "┐", "silver")]]
                for k, desc in CHAT_HELP:
                    line = pad([("  " + k.ljust(12), "amber"), (clip(desc, box_w - 16), "")], box_w - 2)
                    box.append([("│", "silver")] + line + [("│", "silver")])
                box.append([("└" + "─" * (box_w - 2) + "┘", "silver")])
            else:
                title = f"Skills · {len(self.items)}" if self.popup == "skills" else ("Sessions" if self.popup == "sessions" else "Choose the target")
                vis_cap = max(12, min(20, h - len(header) - 6))
                start_i, v_items = _popup_window(self.items, self.pick_i, vis_cap)
                box = [[("┌─ " + title, "bold"), (" ─" + "─" * max(0, box_w - 6 - len(title)) + "┐", "silver")]]
                for j, it in enumerate(v_items):
                    sel = start_i + j == self.pick_i
                    line = pad([(" › " if sel else "   ", "champagne"), (clip(it.label, 32).ljust(32), "rev" if sel else "bone"), (" " + clip(it.hint, box_w - 38), "dim")], box_w - 2)
                    box.append([("│", "silver")] + line + [("│", "silver")])
                box.append([("└" + "─" * (box_w - 2) + "┘", "silver")])
            top = max(len(header), h - 3 - len(box))
            rows[top : top + len(box)] = box
        return rows[:h], cursor


def run_chat(p: app.Project, resume: str | None = None) -> int:
    import curses

    def main(scr):
        curses.curs_set(1)
        scr.timeout(200)
        scr.keypad(True)
        ui = ChatUI(p)
        if resume is not None:
            ui.resume(resume or None)
        else:
            ui.session_id = new_id()
            ui.save()
        cur_skin = None
        attrs: dict[str, int] = {}
        names = {
            curses.KEY_UP: "up", curses.KEY_DOWN: "down",
            curses.KEY_PPAGE: "pgup", curses.KEY_NPAGE: "pgdn",
            curses.KEY_BACKSPACE: "backspace", 127: "backspace", 8: "backspace",
            10: "enter", 13: "enter", 9: "tab", 21: "ctrl-u",
            16: "ctrl-p", 1: "ctrl-a", 2: "ctrl-b", 4: "ctrl-d", 12: "ctrl-l",
            14: "ctrl-n", 19: "ctrl-s", 20: "ctrl-t", 3: "ctrl-c",
            curses.KEY_ENTER: "enter",
            getattr(curses, "KEY_F1", -99): "f1",
            getattr(curses, "KEY_F2", -98): "f2",
            getattr(curses, "KEY_F3", -97): "f3",
            getattr(curses, "KEY_F4", -96): "f4",
            getattr(curses, "KEY_F5", -95): "f5",
        }
        while not ui.quit:
            if ui.skin != cur_skin:
                cur_skin = ui.skin
                attrs = apply_curses_skin(curses, cur_skin)
            h, w = scr.getmaxyx()
            scr.erase()
            if h < 20 or w < 72:
                _too_small(scr, w)
            else:
                rows, cursor = ui.compose(w, h)
                draw_rows(scr, rows, attrs, cursor, w, h, curses)
            scr.refresh()
            c = watch.read(scr)
            if c == -1:
                if watch.lost():
                    break
                continue
            if c == curses.KEY_RESIZE:
                continue
            if c == 27:
                scr.nodelay(True)
                nxt = scr.getch()
                scr.nodelay(False)
                if nxt in (49, 50, 51, 52, 53):
                    ui.key("alt-" + chr(nxt))
                    continue
                ui.key("esc")
                continue
            k = names.get(c) or (chr(c) if 0 <= c < 0x110000 and chr(c).isprintable() else "")
            if k:
                ui.key(k)
        ui.save()

    watch = TerminalWatch(200)
    with watch:
        _wrapper(main, watch)
    return 0
