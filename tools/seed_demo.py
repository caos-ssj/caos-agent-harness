"""Builds a sample project for screenshots and for trying the dashboard: `python3 tools/seed_demo.py <folder> [--force]`.

Everything it writes is sample data and the dashboard says so: the folder gets a `.harness/sample` marker, which
makes `/api/state` report `"sample": true` and the header show a `demo` chip. The agents are two tiny
commands that print canned deliveries, so no model is needed. The counts the dashboard shows still come from the
board it creates (`Board.stats()`); only the tasks and the answers are made up.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DELIVERIES = {
    "Summarise the open pull requests of the week in five lines": "Five pull requests are open.\n1. Retry policy for the webhook (waiting on review)\n2. Config keys renamed for v1.2\n3. Docs: quickstart rewritten\n4. CI cache for the test image\n5. Dependency bump, no behaviour change",
    "Extract invoice totals from the March batch and flag mismatches": "Totals found for 38 of 41 invoices.\nMismatch: INV-0312 (total 1,240.00, lines add up to 1,204.00).\nThree invoices have no total line.",
    "Classify support tickets by urgency": "high: 4 (login loop, double charge, data export fails, webhook silent)\nmedium: 11\nlow: 23\nEach label is on the ticket; nothing was closed.",
    "Draft release notes for v1.2": "v1.2\n- The router now explains every decision in the trace.\n- Tasks returned for a redo keep their reviewer note.\n- Fixed: a task could stay in 'sending' after a crash.",
    "Cross-check the cited sources in the Q3 report": "Checked 12 citations.\n9 resolve to the cited page.\n2 resolve to a different edition.\n1 does not resolve.",
    "List the config keys that changed between v1.1 and v1.2": "Added: board.trace\nRenamed: agent.cmd -> agent.command\nRemoved: board.autosend",
    "Draft the changelog entry for the retry fix": "Fixed: a failed send returned the task to the queue but kept its claim, so it never ran again. The claim is now released with the task.",
}

# (text, queue or tier, kind, run?, verdict, note)
TASKS = [
    ("Summarise the open pull requests of the week in five lines", "summarizer", "queue", True, "ok", "Matches the five open PRs."),
    ("Extract invoice totals from the March batch and flag mismatches", "checker", "queue", True, "redo", "The three invoices without a total line are missing from the count; list them."),
    ("List the config keys that changed between v1.1 and v1.2", "checker", "queue", True, "ok", "Checked against the diff."),
    ("Classify support tickets by urgency", "low", "tier", True, None, ""),
    ("Draft release notes for v1.2", "summarizer", "queue", True, None, ""),
    ("Cross-check the cited sources in the Q3 report", "checker", "queue", True, "verify", "Attach the links for the two other editions."),
    ("Draft the changelog entry for the retry fix", "summarizer", "queue", True, "ok", "Accurate; kept."),
    ("Approve a refund above the policy limit", "critical", "tier", False, None, ""),
    ("Review the retry policy of the payment webhook", "high", "tier", False, None, ""),
    ("Translate the onboarding checklist to Spanish", "low", "tier", False, None, ""),
    ("Rename the staging buckets to the new convention", "person", "queue", False, None, ""),
]

TOML = '''# Sample project: the agents print canned answers. Nothing here calls a model.
[board]
db = ".harness/board.db"
trace = ".harness/trace.db"

[agents.summarizer]
command = ["python3", "{script}", "--agent"]
system = "llama3.2:3b"
timeout = 30

[agents.checker]
command = ["python3", "{script}", "--agent"]
system = "qwen2.5:7b+rules"
timeout = 30
'''


def agent() -> int:
    text = sys.stdin.read().strip()
    print(DELIVERIES.get(text, text))
    return 0


def seed(folder: Path, force: bool = False) -> None:
    from caos_harness import app

    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "harness.toml").exists() and not force:
        raise SystemExit(f"{folder} already has a harness.toml; pass --force to rebuild the sample")
    if force:
        shutil.rmtree(folder / ".harness", ignore_errors=True)
    (folder / "harness.toml").write_text(TOML.format(script=Path(__file__).resolve()), encoding="utf-8")
    (folder / ".harness").mkdir(exist_ok=True)
    (folder / ".harness" / "sample").write_text("sample data written by tools/seed_demo.py\n", encoding="utf-8")
    p = app.load(folder / "harness.toml")
    ids = {}

    def add(batch):
        for text, where, kind, run, verdict, note in batch:
            tid, _, _ = app.add_task(p, text, queue=where if kind == "queue" else None, tier=where if kind == "tier" else None)
            ids[text] = (tid, run, verdict, note)

    # Tasks that were sent are added and run first; the rest stay pending, as they would just after being added.
    add([t for t in TASKS if t[3] or t[1] == "critical" or t[1] == "person"])
    for r in app.run_pending(p):
        assert r["ok"], r
    add([t for t in TASKS if not (t[3] or t[1] == "critical" or t[1] == "person")])
    for text, (tid, run, verdict, note) in ids.items():
        if verdict:
            p.board.review(tid, verdict, note)
    # Spread the ages so the page shows a working day instead of one second.
    db = sqlite3.connect(p.db)
    now = time.time()
    for text, (tid, *_) in ids.items():
        back = [310, 280, 262, 190, 95, 70, 41, 26, 18, 9, 3][[t[0] for t in TASKS].index(text)] * 60
        db.execute("UPDATE tasks SET created=?, sent_at=CASE WHEN sent_at IS NULL THEN NULL ELSE ? END, reviewed_at=CASE WHEN reviewed_at IS NULL THEN NULL ELSE ? END WHERE id=?",
                   (now - back, now - back + 20, now - back + 600, tid))
    db.commit()
    db.close()
    print(f"sample project in {folder}: {len(ids)} tasks. Serve it with: cd {folder} && python3 -m caos_harness serve")


if __name__ == "__main__":
    if "--agent" in sys.argv:
        sys.exit(agent())
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit("usage: python3 tools/seed_demo.py <folder> [--force]")
    seed(Path(args[0]), "--force" in sys.argv)
