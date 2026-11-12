"""The full-screen interface: composed without a terminal, driven by keys, acting on the real board and agents."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from caos_harness import app, tui

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project(tmp_path):
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a") as f:
        f.write('[agents.upper]\ncommand = ["tr", "a-z", "A-Z"]\nsystem = "llama3.2:3b"\n')
    return app.load(tmp_path / "harness.toml")


def text(rows):
    return "\n".join("".join(t for t, _ in r) for r in rows)


def type_(st, s):
    for ch in s:
        st.key(ch)


def test_the_screen_shows_queues_tasks_and_what_waits_for_you(project):
    app.add_task(project, "check the retry policy", queue="person")
    st = tui.State(project)
    rows, _ = tui.compose(st, 170, 32)       # wide enough for the queues, the list, the open task and the session panel
    out = text(rows)
    assert "caos · harness" in out and "1 waiting for you" in out and "Queues" in out and "Session" in out
    assert "check the retry policy" in out and "with a person" in out and "upper" in out and "llama3.2:3b" in out
    assert all(sum(len(t) for t, _ in r) <= 170 for r in rows) and len(rows) == 32       # fits the window exactly


def test_typing_adds_a_task_to_the_chosen_agent_and_r_runs_it_for_real(project):
    st = tui.State(project)
    st.key("n"); type_(st, "hello tui"); st.key("enter")
    assert project.board.get(1)["queue"] == "echo" and project.board.get(1)["text"] == "hello tui"   # the first agent is the default target
    st.command("agent upper")
    st.key("n"); type_(st, "make me loud"); st.key("enter")
    st.key("R")
    for _ in range(50):
        if not st.running:
            break
        time.sleep(0.1)
    assert project.board.get(2)["result"] == "MAKE ME LOUD" and "delivered" in st.message
    assert "MAKE ME LOUD" in text(tui.compose(st, 120, 32)[0])


def test_verdict_keys_follow_the_rules_of_the_board(project):
    st = tui.State(project)
    st.key("n"); type_(st, "a thing"); st.key("enter"); st.key("R")
    for _ in range(50):
        if not st.running:
            break
        time.sleep(0.1)
    st.refresh()
    st.key("r"); assert st.mode == "input" and st.text.startswith("/return 1 ")
    st.key("enter")                                                    # no note: refused, nothing changes
    assert project.board.get(1)["review"] is None and "needs a note" in st.message
    st.key("a")
    assert project.board.get(1)["review"] == "ok"


def test_the_picker_chooses_an_agent_or_a_tier_and_move_changes_the_queue(project):
    st = tui.State(project)
    st.key("p"); assert st.mode == "picker" and any(i.key.startswith("tier:") for i in st.picker)
    st.pick_i = [i.key for i in st.picker].index("agent:upper"); st.key("enter")
    assert st.target == ("agent", "upper")
    st.add_task("move me")
    st.key("m"); st.pick_i = [i.key for i in st.picker].index("person"); st.key("enter")
    assert project.board.get(1)["queue"] == "person"


def test_sessions_are_saved_and_resumed_with_target_log_and_history(project):
    st = tui.State(project); tui.open_session(st)
    st.command("agent upper"); st.key("n"); type_(st, "first"); st.key("enter"); st.save()
    again = tui.State(project); tui.open_session(again, "")
    assert again.session_id == st.session_id and again.target == ("agent", "upper") and again.history == ["first"] and "resumed" in again.message


def test_the_export_writes_a_markdown_file_with_the_delivery_and_trace(project):
    st = tui.State(project); st.add_task("export me"); st.key("e")
    out = (project.root / "task-01.md").read_text()
    assert "# Task 01: export me" in out and "## Trace" in out and "board" in out


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs a pty")
@pytest.mark.parametrize("no_color", [False, True])
def test_on_a_real_terminal_it_opens_draws_and_leaves_cleanly(tmp_path, no_color):
    import pty
    import select
    app.init(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "TERM": "xterm-256color", "LINES": "30", "COLUMNS": "110", "CAOS_HARNESS_HOME": str(tmp_path / "home")}
    env.pop("NO_COLOR", None)
    if no_color:
        env["NO_COLOR"] = "1"
    master, slave = pty.openpty()
    import fcntl, struct, termios
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 110, 0, 0))
    proc = subprocess.Popen([sys.executable, "-m", "caos_harness"], stdin=slave, stdout=slave, stderr=slave, cwd=tmp_path, env=env, close_fds=True)
    os.close(slave)
    time.sleep(1.2)
    os.write(master, b"\x04")   # Ctrl-D leaves
    out = b""
    while select.select([master], [], [], 3)[0]:
        try:
            chunk = os.read(master, 8192)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    assert proc.wait(timeout=5) == 0
    text_ = out.decode(errors="replace")
    assert "caos" in text_ and "harness" in text_ and "agents you can check" in text_
    assert ("38;5;" in text_) == (not no_color)


def test_api_agents_show_provider_and_model_and_pickers_window_long_lists(tmp_path):
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a") as f:
        f.write('[agents.claude_api]\nprovider = "anthropic"\nmodel = "claude-x"\n')
    p = app.load(tmp_path / "harness.toml")
    st = tui.State(p)
    assert any(i.key == "agent:claude_api" and "anthropic · claude-x" in i.hint for i in st.choices())
    assert "anthropic · claude-x" in text(tui.compose(st, 120, 32)[0])
    ui = tui.ChatUI(p)
    assert any(i.key == "agent:claude_api" and "anthropic · claude-x" in i.hint for i in ui.choices())
    items = list(range(20))
    start, vis = tui._popup_window(items, 15, 6)
    assert len(vis) == 6 and 15 in vis and vis[0] == start


def test_detail_scroll_ctrl_b_refresh_and_chat_scroll_clamp(project):
    long_text = " ".join(f"delivery paragraph {i} explaining details cleanly" for i in range(25))
    tid, _, _ = app.add_task(project, long_text, queue="upper")
    res = app.run_task(project, tid, app.CommandDispatcher(project))
    assert res["ok"]
    st = tui.State(project)
    rows, _ = tui.compose(st, 100, 22)
    assert "lines 1-" in text(rows) and "J/K" in text(rows)
    st.key("J")
    assert st.detail_scroll == 3
    st.key("K")
    assert st.detail_scroll == 0

    ui = tui.ChatUI(project)
    app.add_task(project, "added while in chat", queue="person")
    ui.key("ctrl-b")
    assert ui.view == "board" and any(r["text"] == "added while in chat" for r, _ in ui.board.tasks)
    ui.key("esc")
    ui.compose(100, 22)
    ui.key("pgup")
    assert 0 <= ui.scroll <= ui._max_scroll


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs a pty")
@pytest.mark.parametrize("entry", ["chat", "board", "line"])
def test_a_terminal_that_vanishes_ends_the_session_without_spinning(tmp_path, entry):
    """The master side of the pty closes with no Ctrl-D: every read now fails at once. The process must leave promptly and not burn a core."""
    import pty
    import fcntl, struct, termios
    app.init(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "TERM": "xterm-256color", "LINES": "30", "COLUMNS": "110", "CAOS_HARNESS_HOME": str(tmp_path / "home")}
    env.pop("NO_COLOR", None)
    cmd = [sys.executable, "-m", "caos_harness"]
    if entry == "board":
        cmd = [sys.executable, "-c", "from caos_harness import app, tui; raise SystemExit(tui.run(app.load()))"]
    elif entry == "line":
        env["CAOS_TUI"] = "0"
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 110, 0, 0))
    proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, cwd=tmp_path, env=env, close_fds=True, start_new_session=True)
    os.close(slave)
    try:
        time.sleep(1.5)                                  # drawn and idle: an idle terminal must not be mistaken for a lost one
        assert proc.poll() is None
        os.close(master)                                 # the terminal emulator goes away
        t0 = time.monotonic()
        done = None
        while time.monotonic() - t0 < 6 and done is None:
            pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
            if pid:
                done = (status, usage)
            else:
                time.sleep(0.05)
        assert done is not None, "the process kept running after its terminal closed"
        status, usage = done
        assert time.monotonic() - t0 < 5
        assert usage.ru_utime + usage.ru_stime < 2.5, f"spent {usage.ru_utime + usage.ru_stime:.1f}s of CPU"
        assert os.WIFEXITED(status) and os.WEXITSTATUS(status) in (0, 1)
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
            proc.wait()


def test_the_skills_panel_counts_every_skill_and_slash_skills_lists_them_all(project):
    from caos_harness.skills import load_all
    names = list(load_all(project_root=project.root))
    assert len(names) >= 7
    rows = tui.skill_rows(names, 30)
    shown = [t for r in rows for t, _ in r]
    assert all(len(t) <= 33 for t in shown)                                  # fits the panel
    joined = " ".join(shown)
    placed = sum(n in joined for n in names)
    assert (placed == len(names)) or f"+{len(names) - placed} more · /skills" in joined   # what does not fit is counted, never silently cut
    assert tui.skill_rows([], 30)[0][0][0].strip() == "none"

    ui = tui.ChatUI(project, models=["llama3.2:3b"])
    ui._skills_cache = names
    out = text(ui.compose(130, 40)[0])
    assert f"Skills · {len(names)}" in out

    ui.text = "/skills"
    ui.key("enter")
    assert ui.popup == "skills" and [i.key for i in ui.items] == names     # the complete list, not a truncated one
    popup = text(ui.compose(130, 40)[0])
    assert f"Skills · {len(names)}" in popup and all(n in popup for n in names[: min(len(names), 8)])
    ui.key("down"); ui.key("enter")                                        # choosing one loads it first
    assert ui.popup is None and ui.conv.skill == names[1] and names[1] in ui.message
    assert "skills" in tui.ChatUI.COMMANDS


def test_the_board_view_lists_skills_under_activity_and_the_header_is_amber_only_when_someone_waits(project):
    st = tui.State(project)
    st.command("skills")
    assert "skills ·" in st.log[0] and "listed under Activity" in st.message
    rows, _ = tui.compose(st, 120, 32)
    assert not any(sty in ("amber", "amberb") for t, sty in rows[0])        # nothing waits: the header carries no amber
    app.add_task(project, "needs a human", queue="person")
    st = tui.State(project)
    rows, _ = tui.compose(st, 120, 32)
    assert [t for t, sty in rows[0] if sty == "amberb"] == ["1 waiting for you"]


def test_tui_plan_qa_and_act_summary_trust_cards(project):
    from caos_harness import chat
    ui = tui.ChatUI(project, models=["fake:1b"])
    ui.conv.set_commands(True)
    ui.conv.set_mode("act")
    ui.conv.turns.append(chat.Turn("user", "revisa rutas"))
    ui.conv.turns.append(
        chat.Turn(
            "agent",
            "Necesito confirmar 1 punto.",
            who="ollama · fake:1b",
            status="done",
            questions=[{"question": "¿Exportar CSV?", "chips": ["Sí, CSV", "Solo JSON"]}],
        )
    )
    approved = []
    ui.conv.approve = lambda yes, trust_session=False: approved.append((yes, trust_session)) or True
    ui.conv.turns.append(
        chat.Turn(
            "agent",
            "",
            who="ollama · fake:1b",
            status="awaiting",
            steps=[{
                "kind": "edit",
                "name": "write_file",
                "status": "awaiting_approval",
                "input": "write_file:demo.txt",
                "summary_what": "Crear archivo demo.txt",
                "summary_why": "Guardar ejemplo limpio.",
                "summary_goal": "Verificar salida.",
            }],
        )
    )
    out = text(ui.compose(120, 36)[0])
    assert "Preguntas de alineación (Plan)" in out and "[Sí, CSV]" in out
    assert "Qué:" in out and "Crear archivo demo.txt" in out and "Para qué:" in out and "Objetivo:" in out
    assert "[t] trust" in out
    ui.key("t")
    assert approved == [(True, True)]


def test_tui_all_five_tabs_fit_80x24_and_120x36_and_pty_tabs(project, tmp_path):
    import fcntl
    import os
    import pty
    import select
    import struct
    import subprocess
    import sys
    import termios

    ui = tui.ChatUI(project, models=["fake:1b"])
    for key, view_name in (("f1", "chat"), ("f2", "board"), ("f3", "providers"), ("f4", "metrics"), ("f5", "skills")):
        ui.key(key)
        assert ui.view == view_name
        for w, h in ((80, 24), (120, 36)):
            rows, _ = ui.compose(w, h)
            assert len(rows) == h
            assert all(sum(len(t) for t, _ in r) <= w for r in rows)

    env = {**os.environ, "PYTHONPATH": str(ROOT), "TERM": "xterm-256color", "CAOS_HARNESS_HOME": str(tmp_path / "ptyhome")}
    env.pop("CAOS_TUI", None)
    for cols, rows_n in ((80, 24), (120, 36)):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows_n, cols, 0, 0))
        proc = subprocess.Popen([sys.executable, "-m", "caos_harness"], stdin=slave, stdout=slave, stderr=slave, cwd=project.root, env=env, close_fds=True)
        os.close(slave)
        out = b""
        end = time.time() + 4
        while time.time() < end and select.select([master], [], [], 0.3)[0]:
            try:
                out += os.read(master, 4096)
            except OSError:
                break
        for seq in (b"\x1b[12~", b"\x1b[13~", b"\x1b[14~", b"\x1b[15~", b"\x04"):  # F2, F3, F4, F5, Ctrl-D
            try:
                os.write(master, seq)
            except OSError:
                break
            time.sleep(0.08)
        while time.time() < end + 2 and select.select([master], [], [], 0.3)[0]:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        os.close(master)
        assert proc.wait(timeout=5) == 0
        decoded = out.decode(errors="replace")
        assert "caos" in decoded

