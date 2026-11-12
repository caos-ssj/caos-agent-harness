"""The conversation engine behind TUI and interactive chat across Ollama hosts, cloud providers, intents and Board agents."""
from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import app, providers

REF = re.compile(r"(?<![\w@])@([\w./\-]+)")
MAX_FILE = 20_000
MAX_REFS = 5
SECRET_TEXT = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bsk-[A-Za-z0-9_\-]{20,}"
    r"|\bAIza[0-9A-Za-z\-_]{30,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\bglpat-[A-Za-z0-9_\-]{20,}"
    r"|\bxox[bpas]-[A-Za-z0-9\-]{10,}"
)
SECRET_NAMES = re.compile(r"(^|/)(\.env[^/]*|.*\.(pem|key|p12|pfx)|id_[a-z0-9]+|credentials[^/]*|.*secret[^/]*)$", re.I)


@dataclass
class Turn:
    role: str                       # user | agent | note
    text: str = ""
    status: str = "done"            # working | awaiting | done | failed | stopped
    who: str = ""
    task: int | None = None
    steps: list = field(default_factory=list)
    attached: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    at: float = field(default_factory=time.time)


def attach(root: Path, text: str) -> tuple[str, list[str], list[str]]:
    """Expands `@path` references inside the project folder only; refuses hidden/secret files."""
    names, refused, blocks = [], [], []
    root = root.resolve()
    for ref in list(dict.fromkeys(REF.findall(text)))[:MAX_REFS]:
        p = (root / ref).resolve()
        rel = p.relative_to(root).as_posix() if root in p.parents or p == root else None
        if rel is None:
            refused.append(f"@{ref}: outside the project folder")
        elif not p.is_file():
            refused.append(f"@{ref}: not a file")
        elif any(part.startswith(".") for part in Path(rel).parts) or SECRET_NAMES.search(rel):
            refused.append(f"@{ref}: hidden or secret-looking files are never attached")
        else:
            try:
                with p.open("rb") as fh:
                    raw = fh.read(MAX_FILE + 1)
                data = raw.decode("utf-8", errors="strict") if len(raw) <= MAX_FILE else raw[:MAX_FILE].decode("utf-8", errors="ignore") + "\n[…cut at 20 KB]"
            except (OSError, UnicodeDecodeError):
                refused.append(f"@{ref}: not readable as text")
                continue
            if SECRET_TEXT.search(data):
                refused.append(f"@{ref}: it looks like it holds a key or token, so it was not attached")
                continue
            names.append(rel)
            blocks.append(f"\n\n--- file: {rel} ---\n{data}\n--- end of {rel} ---")
    return text + "".join(blocks), names, refused


class Conversation:
    def __init__(self, p: app.Project):
        self.p = p
        self.turns: list[Turn] = []
        self.kind = "agent"                       # agent | model | tier | provider | intent
        self.name = next(iter(p.agents), app.PERSON)
        self.provider = "ollama"
        self.base_url: str | None = None
        self.mode = "plan"                        # plan | act
        self.commands_on = False
        self.skill: str | None = None
        self.trusted_session: set[str] = set()
        self._run = None
        self.queue: list[str] = []
        self.lock = threading.RLock()
        self.version = 0

    def target_label(self) -> str:
        if self.kind == "agent":
            return self.name
        if self.kind == "tier":
            return f"router · {self.name}"
        if self.kind == "intent":
            return f"intent · {self.name}"
        if self.kind == "provider":
            return f"{self.provider} · {self.name}"
        return f"ollama · {self.name}"

    def set_target(self, kind: str, name: str, provider: str = "ollama", base_url: str | None = None) -> None:
        self.kind = kind
        self.name = name
        self.provider = provider or ("ollama" if kind == "model" else "")
        self.base_url = base_url
        if kind not in ("model", "provider", "intent"):
            self.mode = "plan"
        self.version += 1

    def set_mode(self, mode: str) -> str:
        if mode == "act" and (self.kind not in ("model", "provider", "intent") or not self.commands_on):
            return "act needs a direct model/provider/intent target and shell commands switched on (/commands on)"
        self.mode = mode
        self.version += 1
        return f"mode: {mode}"

    def set_commands(self, on: bool) -> None:
        self.commands_on = on
        if not on:
            self.mode = "plan"
        self.version += 1

    def busy(self) -> bool:
        return any(t.status in ("working", "awaiting") for t in self.turns)

    def send(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        if self.busy():
            self.queue.append(text)
            self.version += 1
            return f"queued ({len(self.queue)}): it goes when the agent finishes; Esc stops waiting"
        prompt, names, refused = attach(self.p.root, text)
        prior = [
            {"role": "user" if t.role == "user" else "assistant", "content": t.text[:4000]}
            for t in self.turns
            if t.role in ("user", "agent") and t.status == "done" and t.text
        ][-12:]
        with self.lock:
            self.turns.append(Turn("user", text, attached=names))
            for r in refused:
                self.turns.append(Turn("note", r))
            who_label = self.target_label() if self.kind in ("provider", "intent") else (self.name if self.kind != "tier" else "")
            reply = Turn("agent", "", "working", who=who_label)
            self.turns.append(reply)
            self.version += 1
        threading.Thread(target=self._work, args=(prompt, reply, prior), daemon=True).start()
        return ""

    def _work(self, prompt: str, reply: Turn, prior: list) -> None:
        try:
            if self.kind in ("model", "provider", "intent"):
                self._ask_model(prompt, reply, prior)
            else:
                self._ask_agent(prompt, reply)
        except Exception as e:
            with self.lock:
                reply.text, reply.status = f"{type(e).__name__}: {str(e)[:300]}", "failed"
        finally:
            self.version += 1
            nxt = None
            with self.lock:
                if self.queue and not self.busy():
                    nxt = self.queue.pop(0)
            if nxt:
                self.send(nxt)

    def _ask_agent(self, prompt: str, reply: Turn) -> None:
        kind = "tier" if self.kind == "tier" else "agent"
        tid, queue, why = app.add_task(self.p, prompt, self.name if kind == "agent" else None, self.skill, self.name if kind == "tier" else None)
        with self.lock:
            reply.task, reply.who = tid, ("a person" if queue == app.PERSON else queue)
            reply.steps.append({"name": f"task {tid} -> {reply.who}", "status": "running", "input": why})
            self.version += 1
        res = app.run_task(self.p, tid)
        with self.lock:
            if reply.status == "stopped":
                reply.steps[-1]["status"] = "completed" if res["ok"] else "failed"
                return
            reply.steps[-1]["status"] = "completed" if res["ok"] else ("awaiting" if res["person"] else "failed")
            if res["person"]:
                reply.text, reply.status = "This task went to a person; nothing was sent to an agent. It waits on the board.", "done"
            elif res["ok"]:
                reply.text, reply.status = res["result"] or "(the agent printed nothing)", "done"
            else:
                reply.text, reply.status = res["reason"], "failed"

    def _ask_model(self, prompt: str, reply: Turn, prior: list) -> None:
        from .engines.workstation import Run

        prov, mod, base_url, intent_name = self.provider or "ollama", self.name, self.base_url, ""
        if self.kind == "intent":
            resolved = providers.resolve_intent(self.name, root=self.p.root)
            prov, mod, intent_name = resolved["provider"], resolved["model"], self.name
            with self.lock:
                reply.who = f"{prov} · {mod}"
        run = Run(
            self.p.root,
            prompt,
            mod,
            self.mode if self.commands_on else "plan",
            self.skill or "coder",
            history=prior,
            provider=prov,
            base_url=base_url,
            intent=intent_name,
            initial_trusted=self.trusted_session,
        )
        self._run = run
        threading.Thread(target=run.execute, daemon=True).start()
        try:
            self._poll(run, reply)
        finally:
            self.trusted_session |= run.trusted
            if self._run is run:
                self._run = None

    def _poll(self, run, reply: Turn) -> None:
        while True:
            snap = run.snapshot()
            with self.lock:
                if reply.status == "stopped":
                    return
                reply.steps = snap["steps"]
                reply.questions = snap.get("questions") or []
                reply.status = "awaiting" if snap["status"] == "awaiting_approval" else "working"
                self.version += 1
            if snap["status"] in ("finishing", "failed"):
                with self.lock:
                    reply.text = snap["answer"] or snap["error"]
                    reply.status = "failed" if snap["error"] else "done"
                return
            time.sleep(0.15)

    def approve(self, yes: bool, trust_session: bool = False) -> bool:
        run = self._run
        if not run:
            return False
        snap = run.snapshot()
        if snap["status"] != "awaiting_approval":
            return False
        try:
            run.decide(len(snap["steps"]) - 1, yes, trust_session=trust_session)
        except ValueError:
            return False
        return True

    def _cancel_run(self) -> None:
        if self._run:
            self._run.cancel()

    def stop_waiting(self) -> None:
        self.queue.clear()
        self._cancel_run()
        with self.lock:
            for t in self.turns:
                if t.status in ("working", "awaiting"):
                    t.status, t.text = "stopped", "Stopped waiting. The agent may still finish; its task stays on the board."
            self.version += 1

    def markdown(self) -> str:
        out = [f"# Conversation with {self.target_label()}", ""]
        for t in self.turns:
            if t.role == "user":
                out += [f"**You:** {t.text}", ""]
            elif t.role == "agent":
                out += [f"**{t.who or 'Agent'}:**" + (f" (task {t.task})" if t.task else ""), "", t.text, ""]
                for s in t.steps:
                    if s.get("input") and s.get("name") == "Shell command":
                        out += [f"```\n$ {s['input']}\n```", ""]
            else:
                out += [f"_{t.text}_", ""]
        return "\n".join(out)

    def to_json(self) -> dict:
        return {
            "target": [self.kind, self.name],
            "provider": self.provider,
            "skill": self.skill,
            "turns": [asdict(t) for t in self.turns if t.status != "working"][-200:],
        }

    def from_json(self, data: dict) -> None:
        t = data.get("target")
        if isinstance(t, list) and len(t) == 2 and isinstance(t[0], str) and isinstance(t[1], str) and t[0] in ("agent", "tier", "model", "provider", "intent"):
            self.kind, self.name = t
        self.provider = str(data.get("provider") or "ollama")
        self.skill = data.get("skill") if isinstance(data.get("skill"), str) else None
        self.turns = []
        for raw in data.get("turns", []):
            if isinstance(raw, dict) and raw.get("role") in ("user", "agent", "note"):
                self.turns.append(
                    Turn(
                        raw["role"],
                        str(raw.get("text", ""))[:20000],
                        raw.get("status") if raw.get("status") in ("done", "failed", "stopped") else "done",
                        str(raw.get("who", "")),
                        raw.get("task") if isinstance(raw.get("task"), int) else None,
                        [],
                        [str(x) for x in raw.get("attached", [])][:20],
                        raw.get("questions") if isinstance(raw.get("questions"), list) else [],
                        float(raw.get("at", 0) or 0),
                    )
                )
        self.version += 1
