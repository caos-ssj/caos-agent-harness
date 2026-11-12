import subprocess
import sys


def run(*args):
    return subprocess.run([sys.executable, "-m", "caos_harness", *args], capture_output=True, text=True)


def test_help_lists_every_command():
    out = run("help").stdout
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
    r, g, b = style.AMBAR
    assert style.paint("x", style.AMBAR, stream=Tty()) == f"\x1b[38;2;{r};{g};{b}mx\x1b[0m"
    assert style.paint("x", style.AMBAR, stream=io.StringIO()) == "x"          # piped: plain
    monkeypatch.setenv("NO_COLOR", "1")
    assert style.paint("x", style.AMBAR, stream=Tty()) == "x"
    assert "\x1b" not in run().stdout and "caos · harness" in run().stdout   # a subprocess is not a terminal


def cli(folder, *args):
    import os
    from pathlib import Path
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    env.pop("NO_COLOR", None)
    return subprocess.run([sys.executable, "-m", "caos_harness", *args], capture_output=True, text=True, cwd=folder, env=env)


def test_entry_screen_guides_a_folder_with_and_without_a_project(tmp_path):
    out = cli(tmp_path).stdout
    assert "No project in this folder" in out and "caos-harness init" in out and "\x1b" not in out
    cli(tmp_path, "init")
    out = cli(tmp_path).stdout
    assert "0 tasks" in out and "task add" in out


def test_task_list_uses_the_dashboards_words_and_orders_by_what_needs_you(tmp_path):
    cli(tmp_path, "init")
    cli(tmp_path, "task", "add", "first", "--queue", "echo")
    cli(tmp_path, "task", "add", "second", "--queue", "person")
    out = cli(tmp_path, "task", "list").stdout.splitlines()
    assert "with a person" in out[0] and "second" in out[0] and "pending" in out[1]   # a person's task needs you before a pending one
    assert "\x1b" not in "".join(out)                                                  # piped: no colour, no header
    assert "1 waiting for you" in cli(tmp_path).stdout


def test_run_with_text_adds_sends_and_prints_the_delivery_for_scripts(tmp_path):
    cli(tmp_path, "init")
    r = cli(tmp_path, "run", "hello there", "--agent", "echo")
    assert r.returncode == 0 and r.stdout.strip() == "hello there" and "delivered, waiting for review" in r.stderr
    j = cli(tmp_path, "run", "second", "--agent", "echo", "--json")
    import json as _j
    assert _j.loads(j.stdout)["result"] == "second" and j.returncode == 0
    waits = cli(tmp_path, "run", "decide this", "--agent", "person")
    assert waits.returncode == 3 and waits.stdout == "" and "waiting for a person" in waits.stderr
    assert "nothing to send" in cli(tmp_path, "run").stdout            # the old form still works: only the person's task is left


def test_cli_providers_metrics_share_worktree_and_json(tmp_path, monkeypatch):
    import json as _j
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / "home"))
    proj = tmp_path / "proj"
    proj.mkdir()
    cli(proj, "init")
    cli(proj, "task", "add", "json task", "--queue", "echo")

    tl = cli(proj, "task", "list", "--json")
    assert tl.returncode == 0 and _j.loads(tl.stdout)[0]["text"] == "json task"
    ts = cli(proj, "task", "show", "1", "--json")
    assert ts.returncode == 0 and _j.loads(ts.stdout)["task"]["id"] == 1
    sk = cli(proj, "skills", "--json")
    assert sk.returncode == 0 and any("category" in item for item in _j.loads(sk.stdout))

    pr = cli(proj, "providers", "list", "--json")
    assert pr.returncode == 0 and "providers" in _j.loads(pr.stdout)
    fo = cli(proj, "providers", "failover", "on", "--target", "ollama", "--model", "fake:1b", "--json")
    assert fo.returncode == 0 and _j.loads(fo.stdout)["enabled"] is True

    mt = cli(proj, "metrics", "--json")
    assert mt.returncode == 0 and "kpis" in _j.loads(mt.stdout)
    assert "##" in cli(proj, "metrics", "--md").stdout or "# CAOS Operational Metrics" in cli(proj, "metrics", "--md").stdout

    doc = cli(proj, "share", "doctor", "--json")
    assert doc.returncode == 0 and _j.loads(doc.stdout)["clean"] is True
    pk = cli(proj, "share", "pack", "--format", "zip", "--json")
    assert pk.returncode == 0 and _j.loads(pk.stdout)["ok"] is True

    (proj / "leak.txt").write_text("TOKEN=sk-12345678901234567890123456")
    doc_bad = cli(proj, "share", "doctor", "--json")
    assert doc_bad.returncode == 1 and _j.loads(doc_bad.stdout)["clean"] is False

    wt = cli(proj, "worktree", "list", "--json")
    assert wt.returncode == 0 and isinstance(_j.loads(wt.stdout), list)


def test_cli_chat_and_run_support_intent_and_provider(tmp_path, monkeypatch):
    import json as _j
    from caos_harness import __main__ as cli_main, app, providers
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / "home"))
    p = app.load(app.init(tmp_path))

    seen = []

    class FakeProviderLLM:
        def __init__(self, **kw):
            seen.append(kw)

        def chat(self, messages, tools):
            return {"role": "assistant", "content": "ok via intent", "usage": {"prompt_tokens": 5, "completion_tokens": 3}}

    monkeypatch.setattr("caos_harness.engines.workstation.ProviderChat", FakeProviderLLM)
    monkeypatch.setattr("caos_harness.engines.workstation.OllamaChat", lambda model: FakeProviderLLM(provider="ollama", model=model))
    providers.save_intent_map("codigo", "openai", "gpt-test")
    rc = cli_main.work("chat", ["--intent", "codigo", "--json", "check code"], project=p)
    assert rc == 0 and seen and seen[-1]["model"] == "gpt-test"
    rc2 = cli_main.work("run", ["--provider", "anthropic", "--model", "claude-test", "--json", "inspect"], project=p)
    assert rc2 == 0 and seen[-1]["provider"] == "anthropic" and seen[-1]["model"] == "claude-test"

