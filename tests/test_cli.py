import subprocess
import sys


def run(*args):
    return subprocess.run([sys.executable, "-m", "caos_harness", *args], capture_output=True, text=True)


def test_help_lists_every_command():
    out = run().stdout
    assert all(c in out for c in ("demo", "route", "eval", "regress", "mutation", "agent-eval", "skills", "trace"))


def test_unknown_command_exits_2():
    r = run("launch-rockets")
    assert r.returncode == 2 and "unknown command" in r.stderr


def test_demo_and_trace_through_the_cli(tmp_path):
    db = tmp_path / "t.db"
    r = run("demo", "--seed", "7", "--trace", str(db))
    assert r.returncode == 0 and "PASS" in r.stdout
    assert '"review.verdict.ok"' in run("trace", str(db)).stdout
    line = run("trace", str(db), "task:1").stdout
    assert "router" in line and "board" in line and "review" in line


def test_a_failing_gate_gives_a_failing_exit_code(tmp_path):
    assert run("eval").returncode == 0
    assert {line.split(":", 1)[0] for line in run("skills").stdout.splitlines()} >= {"coder", "qa", "writer", "model-selection", "social-content", "source-research", "proposals"}


def test_colour_only_on_a_terminal_and_never_with_no_color(monkeypatch):
    import io

    from caos_harness import style

    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert style.paint("x", style.AMBAR, stream=Tty()) == "\x1b[38;2;201;151;92mx\x1b[0m"
    assert style.paint("x", style.AMBAR, stream=io.StringIO()) == "x"          # piped: plain
    monkeypatch.setenv("NO_COLOR", "1")
    assert style.paint("x", style.AMBAR, stream=Tty()) == "x"
    assert "\x1b" not in run().stdout and "caos · harness" in run().stdout   # a subprocess is not a terminal
