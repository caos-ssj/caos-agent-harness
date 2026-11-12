"""The interactive session: plain without a terminal, quiet with NO_COLOR, and every command does what its CLI twin does."""
import io
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from caos_harness import app, repl, style

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project(tmp_path):
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a") as f:
        f.write('[agents.upper]\ncommand = ["tr", "a-z", "A-Z"]\nsystem = "llama3.2:3b"\n')
    return app.load(tmp_path / "harness.toml")


def session(project, script: str, capsys):
    code = repl.run(project, stdin=io.StringIO(script), interactive=False)
    return code, capsys.readouterr().out


def test_without_a_terminal_the_session_is_plain_text_and_commands_work(project, capsys):
    code, out = session(project, '/task add "check the retry policy" --queue upper\n/run\n/status\n/review 1 ok "read it"\n/quit\n', capsys)
    assert code == 0 and "\x1b" not in out and "╭" not in out         # no colour, no emblem when piped
    assert "task 1 -> upper" in out and "delivered, waiting for review" in out
    assert "Waiting for you · 1" in out and "to review" in out
    assert "task 1: ok" in out
    assert project.board.get(1)["review"] == "ok"


def test_the_banner_carries_real_figures_and_nothing_else(project):
    app.add_task(project, "first", queue="person")
    text = repl.banner(project, cols=100, emblem=False)
    assert "harness" in text and "1 for you" in text and "a person 1" in text and "upper 0" in text
    assert "1 tasks" in text and "\x1b" not in text


def test_the_emblem_is_drawn_only_on_a_terminal_and_stacks_on_a_narrow_one(project, monkeypatch):
    monkeypatch.setattr("sys.stdout", type("T", (io.StringIO,), {"isatty": lambda self: True})())
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    wide = repl.banner(project, cols=100, emblem=True)
    r, g, b = style.AMBAR
    assert "╭───────╮" in wide and f"\x1b[38;2;{r};{g};{b}m" in wide        # the amber tick
    narrow = repl.banner(project, cols=50, emblem=True)
    assert "╭" not in narrow                                             # no room: facts only
    monkeypatch.setenv("NO_COLOR", "1")
    assert "\x1b" not in repl.banner(project, cols=100, emblem=True) and "╭───────╮" in repl.banner(project, cols=100, emblem=True)


def test_unknown_commands_plain_text_and_bad_quotes_do_not_end_the_session(project, capsys):
    code, out = session(project, '/nope\nsome words\n/task add "unterminated\n/help\n/quit\n', capsys)
    assert code == 0
    assert "unknown command /nope" in out and 'Not added' in out and "error:" in out and "Commands" in out
    assert project.board.stats()["tasks"] == 0


def test_plain_text_becomes_a_task_only_when_confirmed(project, capsys):
    sess = repl.Session(project, ask=lambda prompt: "y")
    sess.handle("look at the failing build")
    assert project.board.get(1)["queue"] == "echo"                      # the first agent in harness.toml
    sess2 = repl.Session(project, ask=lambda prompt: "n")
    sess2.handle("another one")
    assert project.board.stats()["tasks"] == 1


def test_aliases_and_a_redo_without_a_note_are_refused_like_the_cli(project, capsys):
    session(project, '/t add "x" --queue upper\n/run\n/r 1 redo\n/quit\n', capsys)
    out = capsys.readouterr().out
    assert project.board.get(1)["review"] is None                       # a redo needs its note; nothing changed


def test_serve_starts_the_dashboard_on_loopback_and_stops_on_leaving(project, capsys):
    sess = repl.Session(project)
    sess.handle("/serve 0")
    port = sess.httpd.server_address[1]
    assert sess.httpd.server_address[0] == "127.0.0.1"
    assert json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state"))["project"] == project.root.name
    sess.httpd.shutdown(); sess.httpd.server_close()


def test_the_prompt_is_plain_without_colour_and_amber_while_something_waits(project, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert repl.prompt_text(project, tty=True) == "caos › "
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr("sys.stdout", type("T", (io.StringIO,), {"isatty": lambda self: True})())
    assert "\x1b[0m" in repl.prompt_text(project, tty=True)
    assert "\x01" in repl.prompt_text(project, tty=True)               # escapes bracketed for readline


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs a pty")
@pytest.mark.parametrize("no_color", [False, True])
def test_a_real_terminal_opens_the_session_and_respects_no_color(tmp_path, no_color):
    import pty
    import select
    app.init(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "TERM": "xterm-256color", "COLUMNS": "100", "CAOS_TUI": "0"}   # CAOS_TUI=0: the line-mode session
    env.pop("NO_COLOR", None)
    if no_color:
        env["NO_COLOR"] = "1"
    master, slave = pty.openpty()
    proc = subprocess.Popen([sys.executable, "-m", "caos_harness"], stdin=slave, stdout=slave, stderr=slave, cwd=tmp_path, env=env, close_fds=True)
    os.close(slave)
    os.write(master, b"/quit\n")
    out = b""
    while select.select([master], [], [], 5)[0]:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    proc.wait(timeout=5)
    text = out.decode()
    assert "caos · harness" in text and "╭───────╮" in text and "caos" in text and "›" in text
    assert ("\x1b[38;2;" in text) == (not no_color)


def test_repl_command_reads_piped_commands_for_scripts(project):
    r = subprocess.run([sys.executable, "-m", "caos_harness", "repl"], input="/task list\n/quit\n", capture_output=True, text=True, cwd=project.root, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0 and "nothing open" in r.stdout and "\x1b" not in r.stdout


def test_repl_compact_two_line_banner_default_and_new_slash_commands(project, capsys, monkeypatch):
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(project.root.parent / "replhome"))
    compact = repl.banner(project, cols=100, emblem=False)
    assert "╭───────╮" not in compact and "◈ caos · harness" in compact and len(compact.splitlines()) <= 5
    sess = repl.Session(project)
    assert sess.handle("/metrics")
    assert "Metrics (" in capsys.readouterr().out
    assert sess.handle("/doctor --dry-run")
    out = capsys.readouterr().out
    assert "Doctor: " in out and "dry run" in out and "0 tokens" in out and "Leak scan" in out
    assert sess.handle("/share doctor")
    assert "Doctor: clean" in capsys.readouterr().out
    assert sess.handle("/pack zip")
    assert "Share Pack created" in capsys.readouterr().out

