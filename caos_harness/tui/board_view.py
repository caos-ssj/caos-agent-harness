"""TUI Board tab (`Ctrl-B` or Tab 2): queues, task list, delivery/trace inspection, and review verdicts."""
from __future__ import annotations

import json
import shlex
import threading
import time
from dataclasses import dataclass, field

from .. import app, style
from ..router.route import choose, load_profiles, load_tiers
from .common import Item, Row, _agent_desc, _popup_window, clip, git_touched, pad, sessions_dir, skill_rows, wrap
from .theme import apply_curses_skin, draw_rows

ORDER = ["to_review", "verify", "person", "sending", "pending", "returned", "sent", "ok", "superseded", "discarded"]
LABEL = style.LABEL
NEEDS = ("to_review", "verify", "person")
CLOSED = ("ok", "superseded", "discarded")
HELP = [
    ("j k  ↑ ↓", "move through the tasks"), ("Enter", "open the selected task (delivery and trace)"), ("a", "accept the delivery"),
    ("r", "return it, with a note"), ("v", "ask for evidence"), ("s", "mark it superseded"), ("d", "discard a task that is still pending"),
    ("R", "run what is pending"), ("n  i", "write a task for the chosen agent or tier"), ("p", "choose the agent or cost of error for new tasks"),
    ("m", "move a pending task to another queue"), ("e", "export the task to a Markdown file"), ("1 2 3 4", "all · needs you · in motion · closed"),
    ("[ ]", "previous / next queue"), ("Tab", "show or hide the session panel"), ("/", "commands: /run /accept /return /verify /move /agent /tier /skill /skills /export /sessions /help /quit"),
    ("Esc", "back to the list"), ("q", "leave (the session is saved)"),
]


@dataclass
class State:
    p: app.Project
    tasks: list = field(default_factory=list)
    sel: int = 0
    queue: str | None = None
    scope: str = "all"                 # all | needs | moving | closed
    mode: str = "list"                 # list | input | picker | help
    text: str = ""
    picker: list = field(default_factory=list)
    pick_i: int = 0
    pick_for: str = ""                 # "target" | "move"
    target: tuple = ("agent", "")
    skill: str | None = None
    message: str = ""
    log: list = field(default_factory=list)
    history: list = field(default_factory=list)
    hist_i: int = -1
    side: bool = True
    running: bool = False
    quit: bool = False
    session_id: str = ""
    profiles: list = field(default_factory=list)
    tiers: dict = field(default_factory=dict)
    detail_open: bool = True
    detail_scroll: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        try:
            self.profiles, self.tiers = load_profiles(), load_tiers()
        except Exception:
            self.profiles, self.tiers = [], {}
        if not self.target[1]:
            self.target = ("agent", next(iter(self.p.agents), app.PERSON))
        self.refresh()

    def refresh(self) -> None:
        with self.lock:
            rows = self.p.board.rows()
        tasks = [(r, app.task_state(r)) for r in rows]
        keep = self.current()["id"] if self.tasks and 0 <= self.sel < len(self.tasks) else None

        def pick(t):
            r, s = t
            if self.queue == "person" and s != "person": return False
            if self.queue == "review" and s not in ("to_review", "verify"): return False
            if self.queue not in (None, "person", "review") and r["queue"] != self.queue: return False
            if self.queue is not None and self.scope == "all" and s in CLOSED: return False
            if self.scope == "needs" and s not in NEEDS: return False
            if self.scope == "moving" and (s in NEEDS or s in CLOSED): return False
            if self.scope == "closed" and s not in CLOSED: return False
            if self.scope == "all" and self.queue is None and s in CLOSED: return False
            return True

        self.tasks = sorted((t for t in tasks if pick(t)), key=lambda t: (ORDER.index(t[1]), -t[0]["id"]))
        self.sel = min(self.sel, max(0, len(self.tasks) - 1))
        if keep is not None:
            for i, (r, _) in enumerate(self.tasks):
                if r["id"] == keep:
                    self.sel = i

    def current(self):
        if not self.tasks:
            return None
        r, s = self.tasks[min(self.sel, len(self.tasks) - 1)]
        return {"id": r["id"], "row": r, "state": s}

    def counts(self) -> dict:
        return app.summary(self.p)

    def lanes(self) -> list:
        rows = [(r, app.task_state(r)) for r in self.p.board.rows()]
        open_ = [(r, s) for r, s in rows if s not in CLOSED]
        out = [("", "All open", len(open_), "")]
        for a in self.p.agents.values():
            prof = next((x for x in self.profiles if x.system == a.system), None)
            sub = (_agent_desc(a) or "no model") + (f" · {prof.precision * 100:.0f}%" if prof else "")
            out.append((a.name, a.name, sum(1 for r, _ in open_ if r["queue"] == a.name), sub))
        out.append(("person", "A person", sum(1 for _, s in open_ if s == "person"), "decides what no model can"))
        out.append(("review", "To review", sum(1 for _, s in open_ if s in ("to_review", "verify")), "waiting for you"))
        return out

    def say(self, text: str, remember: bool = True) -> None:
        self.message = text
        if remember:
            self.log.append(f"{time.strftime('%H:%M')} {text}")
            self.log = self.log[-60:]
        self.save()

    def verdict(self, tid: int, v: str, note: str = "") -> None:
        if v == "redo" and not note.strip():
            self.say("A return needs a note: /return <id> <what to fix>", False)
            return
        ok = self.p.board.review(tid, v, note.strip())
        self.say(f"task {tid}: {v}" if ok else f"task {tid} does not accept '{v}' now", ok)
        self.refresh()

    def add_task(self, text: str) -> None:
        kind, name = self.target
        try:
            tid, queue, _ = app.add_task(self.p, text, name if kind == "agent" else None, self.skill, name if kind == "tier" else None)
        except (app.ConfigError, ValueError) as e:
            self.say(f"error: {e}", False)
            return
        self.say(f"task {tid} added for {'a person' if queue == app.PERSON else queue}")
        self.refresh()
        for i, (r, _) in enumerate(self.tasks):
            if r["id"] == tid:
                self.sel = i

    def run_pending(self) -> None:
        if self.running:
            self.say("a run is already going", False)
            return
        n = sum(1 for r in self.p.board.pending() if r["queue"] != app.PERSON and r["queue"] in self.p.agents)
        if not n:
            self.say("nothing is waiting for an agent", False)
            return
        self.running = True
        self.say(f"sending {n} task{'s' if n > 1 else ''}…")

        def work():
            try:
                res = app.run_pending(self.p)
                ok = sum(1 for r in res if r["ok"])
                self.say(f"run finished: {ok} delivered, {len(res) - ok} failed" if len(res) != ok else f"run finished: {ok} delivered, waiting for your review")
            except Exception as e:
                self.say(f"run failed: {e}", False)
            finally:
                self.running = False
                self.refresh()
        threading.Thread(target=work, daemon=True).start()

    def export(self, tid: int) -> None:
        r = self.p.board.get(tid)
        if not r:
            self.say(f"no task {tid}", False)
            return
        tl = self.p.board.trace.timeline(f"task:{tid}") if self.p.board.trace else []
        lines = [
            f"# Task {tid:02d}: {r['text']}", "", f"State: {LABEL.get(app.task_state(r), app.task_state(r))} · queue: {r['queue']}", "", "## Delivered", "",
            r["result"] if r["result"] is not None else "(nothing delivered yet)", "", "## Trace", "",
        ]
        lines += [f"- {time.strftime('%H:%M:%S', time.localtime(e['ts']))} {e['source']} {e['status'] or e['kind']} {e['name'] or ''} {e['reason'] or ''}".rstrip() for e in tl]
        path = self.p.root / f"task-{tid:02d}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.say(f"exported to {path.name}")

    def choices(self) -> list:
        items = []
        for a in self.p.agents.values():
            prof = next((x for x in self.profiles if x.system == a.system), None)
            items.append(Item(f"agent:{a.name}", f"{a.name}", _agent_desc(a) + (f" · {prof.precision * 100:.0f}% precise · lower bound {prof.precision_lo * 100:.0f}%" if prof else " · not measured")))
        for t, need in self.tiers.items():
            d = choose(self.profiles, need) if self.profiles else None
            goes = (d.system if d and d.action == "route" else "a person") if d else "?"
            items.append(Item(f"tier:{t}", f"cost of error: {t}", f"the router sends it to {goes}"))
        items.append(Item("agent:person", "a person", "no agent is asked"))
        return items

    def command(self, line: str) -> None:
        try:
            parts = shlex.split(line)
        except ValueError as e:
            self.say(f"error: {e}", False)
            return
        if not parts:
            return
        cmd, rest = parts[0].lower().lstrip("/"), parts[1:]
        cur = self.current()
        if cmd in ("quit", "q"):
            self.quit = True
        elif cmd == "help":
            self.mode = "help"
        elif cmd == "run":
            self.run_pending()
        elif cmd in ("accept", "ok") and (rest or cur):
            tid = int(rest[0]) if rest and rest[0].isdigit() else (cur and cur["id"])
            note = " ".join(rest[1:] if rest and rest[0].isdigit() else rest)
            if tid: self.verdict(tid, "ok", note)
        elif cmd in ("return", "redo") and (rest or cur):
            tid = int(rest[0]) if rest and rest[0].isdigit() else (cur and cur["id"])
            note = " ".join(rest[1:] if rest and rest[0].isdigit() else rest)
            if tid: self.verdict(tid, "redo", note)
        elif cmd == "verify" and (rest or cur):
            tid = int(rest[0]) if rest and rest[0].isdigit() else (cur and cur["id"])
            if tid: self.verdict(tid, "verify", " ".join(rest[1:] if rest and rest[0].isdigit() else rest))
        elif cmd in ("superseded", "supersede") and (rest or cur):
            tid = int(rest[0]) if rest and rest[0].isdigit() else (cur and cur["id"])
            if tid: self.verdict(tid, "superseded")
        elif cmd == "discard" and (rest or cur):
            tid = int(rest[0]) if rest and rest[0].isdigit() else (cur and cur["id"])
            if tid:
                ok = self.p.board.discard(tid)
                self.say(f"task {tid} discarded" if ok else f"task {tid} is already started", ok)
        elif cmd == "move" and (len(rest) >= 1 and cur or len(rest) >= 2):
            tid, q = (int(rest[0]), rest[1]) if len(rest) >= 2 and rest[0].isdigit() else (cur["id"], rest[0])
            ok = q in (*self.p.agents, app.PERSON) and self.p.board.requeue(tid, q)
            self.say(f"task {tid} moved to {q}" if ok else f"cannot move task {tid} to {q}", ok)
        elif cmd == "agent" and rest:
            if rest[0] in self.p.agents or rest[0] == app.PERSON:
                self.target = ("agent", rest[0]); self.say(f"new tasks go to {rest[0]}")
            else:
                self.say(f"unknown agent {rest[0]}", False)
        elif cmd == "tier" and rest:
            if rest[0] in self.tiers:
                self.target = ("tier", rest[0]); self.say(f"new tasks go to router tier {rest[0]}")
            else:
                self.say(f"unknown tier {rest[0]}", False)
        elif cmd == "skill":
            from ..skills import known
            if not rest or rest[0] == "none": self.skill = None; self.say("no default skill")
            elif known(rest[0]): self.skill = rest[0]; self.say(f"default skill: {rest[0]}")
            else: self.say(f"unknown skill {rest[0]}", False)
        elif cmd == "skills":
            from ..skills import load_all
            names = list(load_all(project_root=self.p.root))
            self.say(f"skills · {', '.join(names) or 'none'}"); self.message = f"{len(names)} skills: listed under Activity"
        elif cmd == "export" and cur:
            self.export(cur["id"])
        elif cmd == "sessions":
            d = sessions_dir(self.p)
            n = len(list(d.glob("*.json"))) if d.is_dir() else 0
            self.say(f"{n} saved session(s) · resume with `caos-harness tui --resume`", False)
        elif cmd == "task" and rest:
            self.add_task(" ".join(rest))
        else:
            self.say(f"unknown command /{cmd} (? for keys)", False)
        self.refresh()

    def key(self, k: str) -> None:
        if self.mode == "help":
            if k in ("esc", "q", "?", "enter"):
                self.mode = "list"
            return
        if self.mode == "picker":
            if k in ("esc", "q"): self.mode = "list"
            elif k in ("j", "down"): self.pick_i = min(max(0, len(self.picker) - 1), self.pick_i + 1)
            elif k in ("k", "up"): self.pick_i = max(0, self.pick_i - 1)
            elif k == "enter" and self.picker:
                it = self.picker[self.pick_i]
                self.mode = "list"
                if self.pick_for == "move" and (cur := self.current()):
                    self.command(f"move {cur['id']} {it.key}")
                else:
                    kind, _, val = it.key.partition(":")
                    self.target = (kind, val)
                    self.say(f"new tasks go to {it.label}")
            return
        if self.mode == "input":
            if k == "esc": self.mode, self.text, self.hist_i = "list", "", -1
            elif k == "enter":
                line, self.text, self.mode, self.hist_i = self.text.strip(), "", "list", -1
                if line:
                    self.history.append(line)
                    self.command(line[1:]) if line.startswith("/") else self.add_task(line)
            elif k == "backspace": self.text = self.text[:-1]
            elif k == "ctrl-u": self.text = ""
            elif k == "up" and self.history:
                self.hist_i = len(self.history) - 1 if self.hist_i < 0 else max(0, self.hist_i - 1); self.text = self.history[self.hist_i]
            elif k == "down" and self.history and self.hist_i >= 0:
                self.hist_i += 1
                self.text = self.history[self.hist_i] if self.hist_i < len(self.history) else ""
                if self.hist_i >= len(self.history): self.hist_i = -1
            elif k == "ctrl-r": self.run_pending()
            elif len(k) == 1 and k.isprintable(): self.text += k
            return
        cur = self.current()
        if k in ("j", "down"):
            self.sel = min(max(0, len(self.tasks) - 1), self.sel + 1)
            self.detail_scroll = 0
        elif k in ("k", "up"):
            self.sel = max(0, self.sel - 1)
            self.detail_scroll = 0
        elif k == "J":
            self.detail_scroll += 3
        elif k == "K":
            self.detail_scroll = max(0, self.detail_scroll - 3)
        elif k == "enter": self.detail_open = not self.detail_open
        elif k == "a" and cur: self.verdict(cur["id"], "ok")
        elif k == "v" and cur: self.verdict(cur["id"], "verify")
        elif k == "s" and cur: self.verdict(cur["id"], "superseded")
        elif k == "r" and cur: self.mode, self.text = "input", f"/return {cur['id']} "
        elif k == "d" and cur: self.command(f"discard {cur['id']}")
        elif k == "R": self.run_pending()
        elif k == "e" and cur: self.export(cur["id"])
        elif k in ("n", "i"): self.mode = "input"
        elif k == "/": self.mode, self.text = "input", "/"
        elif k == "p": self.mode, self.picker, self.pick_i, self.pick_for = "picker", self.choices(), 0, "target"
        elif k == "m" and cur and cur["state"] in ("pending", "person", "returned"):
            self.mode, self.pick_for, self.pick_i = "picker", "move", 0
            self.picker = [Item(a.name, a.name, _agent_desc(a)) for a in self.p.agents.values()] + [Item("person", "a person", "")]
        elif k in ("1", "2", "3", "4"):
            self.scope = ("all", "needs", "moving", "closed")[int(k) - 1]
            self.detail_scroll = 0
        elif k in ("[", "]"):
            keys = [lane[0] for lane in self.lanes()]
            i = keys.index(self.queue or "") if (self.queue or "") in keys else 0
            self.queue = keys[(i + (1 if k == "]" else -1)) % len(keys)] or None
            self.detail_scroll = 0
        elif k == "tab": self.side = not self.side
        elif k == "?": self.mode = "help"
        elif k in ("q", "ctrl-c"): self.quit = True; self.save()
        self.refresh()

    def save(self) -> None:
        if not self.session_id:
            return
        try:
            d = sessions_dir(self.p)
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{self.session_id}.json").write_text(json.dumps({"id": self.session_id, "target": list(self.target), "queue": self.queue, "scope": self.scope, "skill": self.skill,
                                                                   "log": self.log[-60:], "history": self.history[-100:]}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def restore(self, data: dict) -> None:
        t = data.get("target")
        if isinstance(t, list) and len(t) == 2 and ((t[0] == "agent" and (t[1] in self.p.agents or t[1] == app.PERSON)) or (t[0] == "tier" and t[1] in self.tiers)):
            self.target = (t[0], t[1])
        self.queue = data.get("queue") if data.get("queue") in (None, "person", "review", *self.p.agents) else None
        self.scope = data.get("scope") if data.get("scope") in ("all", "needs", "moving", "closed") else "all"
        self.skill = data.get("skill") if isinstance(data.get("skill"), str) else None
        self.log = [str(x) for x in data.get("log", [])][-60:]
        self.history = [str(x) for x in data.get("history", [])][-100:]
        self.refresh()


def open_session(st: State, resume: str | None = None) -> None:
    d = sessions_dir(st.p)
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    pick = None
    if resume is not None:
        pick = next((f for f in files if f.stem == resume), None) if resume else (files[-1] if files else None)
    if pick:
        try:
            st.session_id = pick.stem
            st.restore(json.loads(pick.read_text(encoding="utf-8")))
            st.say(f"resumed session {pick.stem}", False)
            return
        except (OSError, ValueError):
            pass
    st.session_id = time.strftime("%Y%m%d-%H%M%S")
    st.save()


SPLIT_AT = 120   # a terminal this wide shows the list and the open task side by side


def _detail_rows(st: State, cur: dict, width: int, body_h: int, used: int) -> list[Row]:
    """The open task: what was asked, what was delivered (scrollable) and its trace. `used` is how many rows of the column are already taken."""
    r = cur["row"]
    out: list[Row] = [[(f" #{cur['id']:02d} ", "bold"), (clip(r["text"], width - 6), "bone")],
                      [(clip(" queue " + r["queue"] + (f" · skill {r['skill']}" if r["skill"] else ""), width - 1), "dim")]]
    if r["review_note"]:
        out.append([(" note: " + clip(r["review_note"], width - 8), "amber")])
    out.append([(" Delivered", "bold")])
    text = r["result"] if r["result"] is not None else ("(nothing delivered yet)" if cur["state"] != "person" else "(waiting for a person)")
    room = max(2, body_h - used - len(out) - 6)
    wrapped = wrap(text, width - 3)
    max_d = max(0, len(wrapped) - room)
    st.detail_scroll = min(st.detail_scroll, max_d)
    if max_d:
        out[-1] = [(" Delivered", "bold"), (f"  lines {st.detail_scroll + 1}-{min(len(wrapped), st.detail_scroll + room)}/{len(wrapped)} · J/K", "dim")]
    for line in wrapped[st.detail_scroll : st.detail_scroll + room]:
        out.append([("   " + line, "" if r["result"] is not None else "dim")])
    out.append([(" Trace", "bold")])
    tl = st.p.board.trace.timeline(f"task:{cur['id']}") if st.p.board.trace else []
    left = body_h - used - len(out)
    for e in (tl[-left:] if left > 0 else []):
        out.append([(f"   {time.strftime('%H:%M:%S', time.localtime(e['ts']))} ", "dim"), (clip(f"{e['source']:<7} {e['status'] or e['kind']} {e['name'] or ''} {e['reason'] or ''}".strip(), width - 15), "")])
    return out


def compose(st: State, w: int, h: int, embedded: bool = False) -> tuple[list[Row], tuple[int, int] | None]:
    """Composes the Board layout cleanly. Note `rows[0]` uses `amberb` strictly when `needs_you > 0`."""
    rows: list[Row] = []
    if not embedded:
        s = st.counts()
        left = [("caos · harness", "bold"), (f"  {st.p.root.name}", "dim")]
        right = [(f"{s['needs_you']} waiting for you", "amberb")] if s["needs_you"] else [("nothing waiting", "dim")]
        if s["runnable"]:
            right += [(f" · {s['runnable']} ready to run", "dim")]
        if st.running:
            right += [(" · running…", "bone")]
        gap = max(1, w - sum(len(t) for t, _ in left) - sum(len(t) for t, _ in right) - 2)
        rows.append([(" ", "")] + left + [(" " * gap, "")] + right)
        rows.append([("─" * w, "silver")])

    body_h = h - (2 if embedded else 4)
    LW = 30 if w >= 100 else 24
    cur = st.current()
    split = w >= SPLIT_AT and st.detail_open and cur is not None
    RW = 34 if (st.side and w >= (160 if split else 120)) else 0     # beside a split, the session panel needs the extra room
    seps = 1 + (1 if split else 0) + (1 if RW else 0)
    CW = w - LW - RW - seps - (0 if split else 0)
    DW = 0
    if split:
        DW = max(40, int((CW) * 0.56))
        CW = CW - DW
    lanes = st.lanes()

    lcol: list[Row] = [[(" Queues", "bold")]]
    for key, name, n, sub in lanes:
        on = (st.queue or "") == key
        cnt_style = "amber" if key in ("person", "review") and n else "dim"
        lcol.append([("›" if on else " ", "champagne"), (clip(f" {name}", LW - 7).ljust(LW - 7), "bone" if on else ""), (f"{n:>3}", cnt_style)])
        if sub and n >= 0:
            lcol.append([("   " + clip(sub, LW - 4), "dim")])
    while len(lcol) < body_h:
        lcol.append([])

    ccol: list[Row] = [[(" Tasks  ", "bold"), (f"{len(st.tasks)} shown · scope {st.scope}", "dim")]]
    list_h = max(4, int(body_h * (0.5 if (st.detail_open and not split) else 0.95)) - 1)
    start = max(0, min(st.sel - list_h // 2, len(st.tasks) - list_h))
    for i in range(start, min(len(st.tasks), start + list_h)):
        r, state = st.tasks[i]
        sel = i == st.sel
        tone = "amber" if state in NEEDS else ("sage" if state == "ok" else ("coral" if state == "returned" else ("dim" if state in CLOSED else "steel")))
        ccol.append([("›" if sel else " ", "champagne"), (f"{r['id']:>3} ", "dim"), (clip(LABEL.get(state, state), 13).ljust(14), tone), (clip(r["text"], CW - 21), "rev" if sel else "")])
    if not st.tasks:
        ccol += [[(" Nothing here. ", "dim"), ("n", "bone"), (" writes a task, ", "dim"), ("1-4", "bone"), (" changes the scope.", "dim")]]
    dcol: list[Row] = []
    if split:
        dcol = [[(" Task", "bold")]] + _detail_rows(st, cur, DW - 1, body_h, 1)
    elif st.detail_open and cur:
        ccol.append([("─" * CW, "silver")])
        ccol += _detail_rows(st, cur, CW, body_h, len(ccol))
    while len(ccol) < body_h:
        ccol.append([])

    rcol: list[Row] = []
    if RW:
        kind, name = st.target
        a = st.p.agents.get(name) if kind == "agent" else None
        prof = next((x for x in st.profiles if a and x.system == a.system), None)
        rcol = [[(" Session", "bold")], [(" new tasks go to", "dim")], [("  " + (f"{name}" if kind == "agent" else f"router · cost of error {name}"), "bone")]]
        if a:
            rcol.append([("  model " + (_agent_desc(a) or "(none)"), "dim")])
            rcol.append([("  " + (f"{prof.precision * 100:.1f}% precise · lower bound {prof.precision_lo * 100:.1f}%" if prof else "not measured"), "dim")])
        if st.skill:
            rcol.append([(f"  skill {st.skill}", "dim")])
        from ..skills import load_all
        names = list(load_all(project_root=st.p.root))
        rcol += [[], [(f" Skills · {len(names)}", "bold")]] + skill_rows(names, RW - 3)
        rcol += [[], [(" Touched files", "bold")]]
        touched = git_touched(st.p)
        rcol += [[("  " + clip(t, RW - 3), "dim")] for t in touched] or [[("  no changes", "dim")]] if touched is not None else [[("  not a git repository", "dim")]]
        rcol += [[], [(" Activity", "bold")]]
        for line in st.log[-max(3, body_h - len(rcol)):]:
            rcol.append([("  " + clip(line, RW - 3), "dim")])
    while len(rcol) < body_h:
        rcol.append([])
    while len(ccol) < body_h:
        ccol.append([])

    while len(dcol) < body_h:
        dcol.append([])
    for i in range(body_h):
        row = pad(lcol[i][:], LW) + [("│", "silver")] + pad(ccol[i][:], CW)
        if split:
            row += [("│", "silver")] + pad(dcol[i][:], DW)
        if RW:
            row += [("│", "silver")] + rcol[i]
        rows.append(row)

    rows.append([("─" * w, "silver")])
    cursor = None
    if st.mode == "input":
        rows.append([(" caos ", "bold"), ("› ", "champagne"), (st.text, "")])
        cursor = (len(rows) - 1, min(w - 2, 8 + len(st.text)))
    elif st.mode in ("picker", "help"):
        items = st.picker if st.mode == "picker" else HELP
        hint = "picker · j/k move, Enter chooses, Esc closes" if st.mode == "picker" else "keys · Esc closes"
        rows.append([(" " + hint, "dim")])
        box_w = min(w - 4, 78)
        vis = items if st.mode == "help" else _popup_window(items, st.pick_i, 12)[1]
        start_i = 0 if st.mode == "help" else _popup_window(items, st.pick_i, 12)[0]
        box: list[Row] = [[("┌─ " + ("Keys" if st.mode == "help" else "Choose"), "bold"), (" ─" + "─" * max(0, box_w - 14) + "┐", "silver")]]
        for j, it in enumerate(vis):
            if st.mode == "help":
                k, desc = it
                line = pad([("  " + k.ljust(12), "amber"), (clip(desc, box_w - 16), "")], box_w - 2)
            else:
                sel = start_i + j == st.pick_i
                line = pad([(" › " if sel else "   ", "champagne"), (clip(it.label, 24).ljust(24), "rev" if sel else "bone"), (" " + clip(it.hint, box_w - 30), "dim")], box_w - 2)
            box.append([("│", "silver")] + line + [("│", "silver")])
        box.append([("└" + "─" * (box_w - 2) + "┘", "silver")])
        top = max(2, h - 3 - len(box))
        rows[top : top + len(box)] = box
    else:
        default_msg = "n new · R run · a ok · r redo · 1-4 scope · Esc chat" if embedded else "n new task · R run · a accept · r return · 1-4 scope · Ctrl-B chat · ? keys"
        rows.append([(clip(" " + (st.message or default_msg), w - 2), "dim")])
    return rows[:h], cursor


def run(p: app.Project, resume: str | None = None) -> int:
    import curses
    from .common import TerminalWatch, _too_small, _wrapper

    def main(scr):
        attrs = apply_curses_skin(curses, "night")
        curses.curs_set(1)
        scr.timeout(400)
        scr.keypad(True)
        st = State(p)
        open_session(st, resume)
        names = {curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_BACKSPACE: "backspace", 127: "backspace", 8: "backspace", 10: "enter", 13: "enter", 27: "esc", 9: "tab", 21: "ctrl-u", 18: "ctrl-r", 3: "ctrl-c", 4: "ctrl-d", curses.KEY_ENTER: "enter"}
        while not st.quit:
            h, w = scr.getmaxyx()
            scr.erase()
            if h < 20 or w < 72:
                _too_small(scr, w)
            else:
                rows, cursor = compose(st, w, h)
                draw_rows(scr, rows, attrs, cursor, w, h, curses)
            scr.refresh()
            c = watch.read(scr)
            if c == -1:
                if watch.lost():
                    break
                if st.running:
                    st.refresh()
                continue
            if c == curses.KEY_RESIZE:
                continue
            k = names.get(c) or (chr(c) if 0 <= c < 0x110000 and chr(c).isprintable() else "")
            if k == "ctrl-d":
                st.quit = True
                st.save()
                break
            if k:
                st.key(k)
        st.save()

    watch = TerminalWatch(400)
    with watch:
        _wrapper(main, watch)
    return 0
