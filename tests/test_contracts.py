"""The server's JSON against the types the page declares in web/src/api.ts. No new tooling: api.ts is read as text.

Every drift so far (`finishing`, `expired`, `summary`) was a value or a field the server produced and the page did not know. These tests
fail when that happens again."""
import re
from pathlib import Path

import pytest

from caos_harness import app
from caos_harness.engines import workstation
from caos_harness.web import server
from caos_harness.web.server import Api, TaskRun

API_TS = (Path(__file__).resolve().parent.parent / "web" / "src" / "api.ts").read_text(encoding="utf-8")


def interface_fields(name: str) -> set[str]:
    m = re.search(rf"export interface {name}(?: extends (\w+))? \{{\n(.*?)\n\}}", API_TS, re.S)
    assert m, f"interface {name} not found in api.ts"
    own = set(re.findall(r"^\s{2}(\w+)\??:", m.group(2), re.M))
    return own | (interface_fields(m.group(1)) if m.group(1) else set())


def union(interface: str, field: str) -> set[str]:
    m = re.search(rf"export interface {interface}(?: extends \w+)? \{{\n(.*?)\n\}}", API_TS, re.S)
    f = re.search(rf"^\s{{2}}{field}\??:\s*(.+)$", m.group(1), re.M)
    assert f, f"{interface}.{field} not found"
    return set(re.findall(r"""["']([a-z_]+)["']""", f.group(1)))


@pytest.fixture
def project(tmp_path):
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a") as fh:
        fh.write('[agents.upper]\ncommand = ["tr", "a-z", "A-Z"]\nsystem = "llama3.2:3b+rules"\n')
    return app.load(tmp_path / "harness.toml")


def test_the_run_statuses_the_server_can_produce_are_all_declared():
    server_side = {"queued", "running", "awaiting_approval", "finishing", "completed", "failed", "stopped"}
    assert set(server.ACTIVE_RUN) <= union("ExecutionRun", "status")
    assert server_side == union("ExecutionRun", "status")
    src = Path(workstation.__file__).read_text() + Path(server.__file__).read_text()
    used = set(re.findall(r'(?:self\.status|run\.status|\.status) = "(\w+)"', src))
    assert used <= union("ExecutionRun", "status"), used - union("ExecutionRun", "status")


def test_the_step_statuses_the_server_can_produce_are_all_declared():
    import inspect
    src = Path(workstation.__file__).read_text() + inspect.getsource(TaskRun)
    used = set()
    for literal in re.findall(r'\["status"\] = ([^\n]+)', src) + re.findall(r'"status": "(\w+)"', src):
        used |= set(re.findall(r'"(\w+)"', literal)) or {literal}
    declared = union("ToolStep", "status")
    assert {"awaiting_approval", "running", "completed", "failed", "denied", "expired"} == declared
    assert used and used <= declared, used - declared


def test_a_real_run_snapshot_has_no_field_the_page_does_not_know(tmp_path):
    run = workstation.Run(tmp_path, "p", "m", "plan", "auto", llm=type("L", (), {"chat": lambda self, m, t: {"role": "assistant", "content": "hi"}})())
    run.execute()
    snap = run.snapshot()
    known = interface_fields("ExecutionRun")
    assert set(snap) <= known, set(snap) - known
    assert snap["status"] in union("ExecutionRun", "status")


def test_a_task_run_snapshot_and_the_run_detail_fields_are_declared(project):
    tid = app.add_task(project, "hello", queue="upper")[0]
    tr = TaskRun(project, tid, "upper", "why", "agent", "upper", "auto")
    tr.execute()
    known = interface_fields("ExecutionRun")
    assert set(tr.snapshot()) <= known, set(tr.snapshot()) - known
    api = Api(project)
    api.runs[tr.id] = tr
    tr.worktree, tr.diff_text = {"key": "k", "path": "/x", "branch": "b", "was_branch_pre_existing": False}, "diff"
    assert set(api.run_detail(tr.id)) <= known


def test_task_rows_and_the_board_state_match_their_declared_types(project):
    api = Api(project)
    app.add_task(project, "one", queue="upper")
    app.add_task(project, "two", queue="person")
    app.run_pending(project)
    state = api.state()
    task_fields, state_fields = interface_fields("Task"), interface_fields("StateResponse")
    for t in state["tasks"]:
        assert set(t) <= task_fields, set(t) - task_fields
        assert t["state"] in union("Task", "state") and t["status"] in union("Task", "status")
    assert set(state) <= state_fields, set(state) - state_fields
    assert set(state["stats"]) == interface_fields("BoardStats")
    assert set(state["summary"]) == interface_fields("BoardSummary")
    assert {a_key for a in state["agents"] for a_key in a} <= interface_fields("Agent")
    assert {k for s in state["skills"] for k in s} <= interface_fields("SkillInfo")


def test_sessions_and_their_details_match_their_declared_types(project):
    api = Api(project)
    sid = api.session_create({"title": "t"})["id"]
    assert set(api.sessions_list()[0]) <= interface_fields("SessionItem")
    assert set(api.session_get(sid)) <= interface_fields("SessionDetail")
