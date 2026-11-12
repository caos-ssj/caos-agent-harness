"""Security of the Share Pack and of what a request may name, the preflight, and the terminal's new voice."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from pathlib import Path

import pytest
from caos_harness import app, completion, doctor, providers, share, style, term
from caos_harness.engines import workstation
from caos_harness.web.server import Api

ROOT = Path(__file__).resolve().parent.parent


def cli(folder, *args, env=None):
    e = {**os.environ, "PYTHONPATH": str(ROOT), "CAOS_HARNESS_HOME": str(Path(folder) / ".home"), **(env or {})}
    e.pop("NO_COLOR", None)
    return subprocess.run([sys.executable, "-m", "caos_harness", *args], capture_output=True, text=True, cwd=folder, env=e)


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / ".home"))
    for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    app.init(tmp_path)
    return tmp_path


# ─ what counts as a secret ─

@pytest.mark.parametrize("line", [
    'openai_api_key = "sk1234abcd5678efgh"', 'user_token = "abc123def456ghi"', 'password: "hunter2hunter2"', "TOKEN=abc12345678xyz90",
    '"client_secret": "a1b2c3d4e5f6g7h8"', "db = postgres://admin:pw1234@host/app", "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123",
    "ghp_" + "a" * 36, "hf_" + "b" * 34, "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
])
def test_the_detector_catches_a_secret_by_its_name_or_by_its_shape(line):
    assert providers.looks_like_secret(line)


@pytest.mark.parametrize("line", [
    'api_key_env = "OPENAI_API_KEY"', "key_env: str | None = None", "const key = e.key", "max_tokens = 4096", 'secret = os.environ["X"]',
    "# OPENAI_API_KEY=your_key_here", 'api_key = ""', 'token_url = "https://example.test/oauth/token"', "password = prompt_for_it()",
    'error_key = "missing_api_key"', "keyboard = 12345678901", 'key_file = "~/.ssh/id_ed25519"',
])
def test_the_detector_leaves_names_of_variables_placeholders_and_code_alone(line):
    assert not providers.looks_like_secret(line)


# ─ the Share Pack ─

def test_harness_toml_loses_every_secret_looking_value_and_keeps_the_variable_names(proj):
    with open(proj / "harness.toml", "a") as f:
        f.write('[agents.x]\ncommand = ["cat"]\nopenai_api_key = "abc12345def67890"\nuser_token = "zzz-123456789"\nkey_env = "OPENAI_API_KEY"\n')
    text, found = share._sanitize_harness_toml(proj)
    assert "abc12345def67890" not in text and "zzz-123456789" not in text and 'key_env = "OPENAI_API_KEY"' in text
    assert text.count(share.REDACTED) == 2 and {f["kind"] for f in found} == {"secret_token"}


def test_a_private_path_is_rewritten_in_the_copy_and_never_in_your_file(proj):
    (proj / "src").mkdir()
    (proj / "src" / "a.py").write_text('p = "/home/someone/proj/x"\nprint(1)\n')
    res = share.build_share_pack(proj, fmt="dir")
    out = Path(res["path"])
    assert (out / "src" / "a.py").read_text() == 'p = "/path/to/workspace/proj/x"\nprint(1)\n'
    assert "/home/someone" in (proj / "src" / "a.py").read_text()                       # the original is untouched
    assert "src/a.py" in res["redacted_paths"] and any(r["path"] == "src/a.py" and r["lines"] == [1] for r in res["redactions"])
    assert res["verified"] is True


def test_a_file_with_a_credential_never_enters_the_pack_even_past_sixty_findings(proj):
    for i in range(70):   # the old report was capped at 60 issues, and a file past the cap slipped in
        (proj / f"leak{i}.txt").write_text(f'password = "hunter2hunter2-{i}"\n')
    (proj / "fine.txt").write_text("nothing here\n")
    res = share.build_share_pack(proj, fmt="dir")
    names = {p.name for p in Path(res["path"]).rglob("*") if p.is_file()}
    assert "fine.txt" in names and not any(n.startswith("leak") for n in names)
    assert len([e for e in res["excluded"] if e["reason"] == "holds a credential"]) == 70


@pytest.mark.parametrize("fmt,ext", [("zip", ".zip"), ("tar.gz", ".tar.gz"), ("dir", "")])
def test_the_three_formats_produce_what_they_say(proj, fmt, ext):
    (proj / "README.md").write_text("# hi\n")
    res = share.build_share_pack(proj, fmt=fmt)
    assert res["format"] == fmt and res["filename"].endswith(ext)
    p = Path(res["path"])
    if fmt == "zip":
        names = set(zipfile.ZipFile(p).namelist())
    elif fmt == "tar.gz":
        names = set(tarfile.open(p, "r:gz").getnames())
    else:
        names = {f.relative_to(p).as_posix() for f in p.rglob("*") if f.is_file()}
    assert {"README.md", ".env.example", "TEAM_SETUP.md", "harness.toml"} <= names


@pytest.mark.parametrize("bad", ["tar", "tgz", "rar", ""])
def test_an_unknown_format_is_refused_not_turned_into_a_zip(proj, bad):
    if bad == "":
        assert share.normalize_format(bad) == "zip"
        return
    with pytest.raises(ValueError, match="use zip, dir, tar.gz"):
        share.build_share_pack(proj, fmt=bad)
    assert not (proj / ".harness" / "exports").exists()
    r = cli(proj, "share", "pack", "--format", bad)
    assert r.returncode == 2 and "unknown format" in r.stderr
    j = cli(proj, "share", "pack", "--format", bad, "--json")
    assert j.returncode == 2 and json.loads(j.stdout) == {"ok": False, "error": f"unknown format '{bad}': use zip, dir, tar.gz"}


def test_the_preview_writes_nothing_and_matches_what_the_build_writes(proj):
    (proj / "a.md").write_text("# a\n")
    (proj / "b.py").write_text("print(1)\n")
    (proj / "leak.txt").write_text('token = "abc12345def67890"\n')
    prev = share.preview_share_pack(proj, fmt="tar.gz")
    assert prev["dry_run"] is True and not (proj / ".harness" / "exports").exists()
    assert {"a.md", "b.py"} <= {i["path"] for i in prev["included"]} and {"path": "leak.txt", "reason": "holds a credential"} in prev["excluded"]
    assert any(c["id"] == "credentials" for c in prev["sanitization"])
    built = share.build_share_pack(proj, fmt="dir")
    names = {p.relative_to(built["path"]).as_posix() for p in Path(built["path"]).rglob("*") if p.is_file()}
    assert names == {i["path"] for i in prev["included"]} | {g["path"] for g in prev["generated"]}
    assert prev["files_count"] == built["files_count"]


def test_pack_dry_run_and_preview_through_the_cli(proj):
    j = json.loads(cli(proj, "share", "preview", "--json").stdout)
    k = json.loads(cli(proj, "share", "pack", "--dry-run", "--json").stdout)
    assert j["dry_run"] and k["dry_run"] and j["files_count"] == k["files_count"] and not (proj / ".harness" / "exports").exists()
    plain = cli(proj, "share", "pack", "--dry-run").stdout
    assert "preview" in plain and "nothing written" in plain and "\x1b" not in plain


def test_the_web_api_previews_refuses_formats_and_guards_what_a_test_request_names(proj, monkeypatch):
    api = Api(app.load(proj / "harness.toml"))
    assert api.share_preview({"format": "tar.gz"})["format"] == "tar.gz"
    with pytest.raises(app.ConfigError, match="unknown format"):
        api.share_pack({"format": "tar"})
    for url in ("file:///etc/passwd", "ftp://x", "http://user:pw@host"):
        with pytest.raises(app.ConfigError):
            api.provider_test({"id": "ollama", "base_url": url})
    with pytest.raises(app.ConfigError, match="declares"):
        api.provider_test({"id": "openai", "key_env": "AWS_SECRET_ACCESS_KEY"})
    with pytest.raises(app.ConfigError, match="not openai's address"):
        api.provider_test({"id": "openai", "base_url": "https://collector.example.test/v1"})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-0123456789abcdefghij")
    seen = []
    api.transport = lambda url, headers, data, timeout: (seen.append(url) or (200, {"data": [{"id": "gpt-4.1-mini"}]}))
    ok = api.provider_test({"id": "openai", "key_env": "OPENAI_API_KEY", "base_url": "https://api.openai.com/v1"})
    assert ok["ok"] and seen and seen[0].startswith("https://api.openai.com/")


def test_a_gateway_saved_with_its_own_variable_may_name_it(proj, monkeypatch):
    api = Api(app.load(proj / "harness.toml"))
    api.save_custom_provider({"name": "Gateway", "base_url": "https://gw.example.test/v1", "api_key_env": "GATEWAY_API_KEY", "models": ["m"]})
    assert "GATEWAY_API_KEY" in providers.declared_key_envs(proj)
    monkeypatch.setenv("GATEWAY_API_KEY", "gw-key-0123456789")
    api.transport = lambda url, headers, data, timeout: (200, {"data": [{"id": "m"}]})
    assert api.provider_test({"id": "gateway", "key_env": "GATEWAY_API_KEY"})["ok"]


# ─ Act: what an approval card shows ─

def test_the_preview_of_a_write_is_a_diff_and_never_prints_a_credential(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    pv = workstation.write_preview(tmp_path, "write_file", {"path": "a.txt", "content": 'one\nTWO\napi_key = "abc12345def67890"\n'})
    assert pv["new_file"] is False and pv["added"] == 2 and pv["removed"] == 1 and "-two" in pv["diff"] and "+TWO" in pv["diff"]
    assert "abc12345def67890" not in json.dumps(pv) and "redacted" in pv["diff"]
    fresh = workstation.write_preview(tmp_path, "write_file", {"path": "n/new.py", "content": "print(1)\n"})
    assert fresh["new_file"] and fresh["content"] == "print(1)" and fresh["lines"] == 1
    assert workstation.write_preview(tmp_path, "edit_file", {"path": "a.txt", "target": "zzz", "replacement": "x"})["error"].startswith("target text not found")
    assert "refused" in workstation.write_preview(tmp_path, "write_file", {"path": ".env", "content": "x"})["error"]
    edit = workstation.write_preview(tmp_path, "edit_file", {"path": "a.txt", "target": "two", "replacement": "2"})
    assert edit["added"] == 1 and edit["removed"] == 1 and (tmp_path / "a.txt").read_text() == "one\ntwo\n"   # nothing was written


def test_an_approval_step_carries_the_preview_before_anything_is_written(tmp_path):
    class Llm:
        turn = 0

        def chat(self, msgs, tools=None):
            self.turn += 1
            if self.turn == 1:
                return {"role": "assistant", "tool_calls": [{"id": "c", "function": {"name": "write_file", "arguments": {"path": "notes.txt", "content": "hello\n"}}}]}
            return {"role": "assistant", "content": "done"}

    run = workstation.Run(tmp_path, "write notes", "m", "act", "coder", llm=Llm())
    t = threading.Thread(target=run.execute, daemon=True)
    t.start()
    while run.status in ("running", "queued"):
        time.sleep(0.01)
    step = run.snapshot()["steps"][0]
    assert step["status"] == "awaiting_approval" and step["preview"]["new_file"] and step["preview"]["content"] == "hello"
    assert not (tmp_path / "notes.txt").exists()
    run.decide(0, False)
    t.join(timeout=3)


# ─ routing profiles, skills ─

def test_profiles_bend_the_router_toward_privacy_or_toward_quality(proj, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-0123456789abcdef")
    local = ["qwen2.5-coder:7b", "llama3.2:3b"]
    pick = lambda i, prof: providers.resolve_intent(i, root=proj, local_models=local, profile=prof)
    assert pick("codigo", None)["provider"] == "anthropic" and pick("codigo", "hybrid")["profile"] == "hybrid"
    assert pick("codigo", "local-first")["provider"] == "ollama" and pick("razonar", "local-first")["provider"] == "ollama"
    assert pick("rapido", "cloud-max")["provider"] == "anthropic"
    assert providers.resolve_intent("codigo", root=proj, local_models=[], profile="local-first")["provider"] == "anthropic"   # nothing local: it goes out
    with pytest.raises(ValueError, match="local-first, hybrid, cloud-max"):
        providers.normalize_profile("fast")
    providers.save_intent_map("codigo", "openai", "pinned-model")
    assert pick("codigo", "local-first")["pinned"] is True                                                                       # an operator's pin wins


def test_chat_and_run_take_a_skill_and_a_profile(proj, monkeypatch):
    from caos_harness import __main__ as cli_main
    seen = []

    class Fake:
        def __init__(self, **kw):
            seen.append(kw)

        def chat(self, messages, tools):
            return {"role": "assistant", "content": "ok"}

    real_run = workstation.Run
    roles = []
    monkeypatch.setattr("caos_harness.engines.workstation.Run", lambda *a, **k: (roles.append(a[4]), real_run(*a, **k))[1])
    monkeypatch.setattr("caos_harness.engines.workstation.ProviderChat", Fake)
    monkeypatch.setattr("caos_harness.engines.workstation.OllamaChat", lambda model: Fake(provider="ollama", model=model))
    monkeypatch.setattr(providers, "probe_ollama", lambda hosts=None, timeout=1.2: {"online": True, "hosts": [], "models": ["qwen2.5-coder:7b"], "details": []})
    p = app.load(proj / "harness.toml")
    assert cli_main.work("chat", ["--skill", "qa", "--intent", "codigo", "--profile", "local-first", "--json", "check"], project=p) == 0
    assert roles[-1] == "qa" and seen[-1]["model"] == "qwen2.5-coder:7b"
    assert cli_main.work("chat", ["--profile", "local-first", "--json", "no intent given"], project=p) == 0          # --profile alone steers `codigo`
    assert cli_main.work("run", ["x", "--intent", "local", "--skill", "writer", "--json"], project=p) == 0 and roles[-1] == "writer"
    assert cli_main.work("chat", ["--skill", "no-such-skill", "--json", "x"], project=p) == 2
    assert cli_main.work("chat", ["--profile", "turbo", "--intent", "codigo", "--json", "x"], project=p) == 2
    assert cli_main.work("chat", ["--profile", "hybrid", "--provider", "openai", "--json", "x"], project=p) == 2    # a profile cannot steer an explicit provider


# ─ the CLI ─

def test_doctor_without_a_project_is_blocked_and_says_how_to_start(tmp_path):
    r = cli(tmp_path, "doctor", "--json")
    res = json.loads(r.stdout)
    assert r.returncode == 1 and res["verdict"] == "blocked" and res["next_actions"] == ["caos-harness init"] and res["tokens_spent"] == 0


def test_doctor_dry_run_names_its_verdict_checks_and_next_actions(proj):
    r = cli(proj, "doctor", "--dry-run", "--json")
    res = json.loads(r.stdout)
    assert r.returncode == 0 and res["dry_run"] is True and res["verdict"] in ("ready", "warning")
    assert {"project", "agents", "ollama", "cloud", "failover", "mcp", "git", "leaks"} <= {c["id"] for c in res["checks"]}
    assert next(c for c in res["checks"] if c["id"] == "ollama")["detail"].endswith("not probed (dry run)")
    (proj / "oops.txt").write_text('password = "hunter2hunter2"\n')
    bad = cli(proj, "doctor", "--dry-run", "--json")
    jb = json.loads(bad.stdout)
    assert bad.returncode == 1 and jb["verdict"] == "blocked" and any("share doctor" in a for a in jb["next_actions"])


def test_doctor_warns_about_an_agent_without_its_key_and_strict_makes_that_fail(proj):
    with open(proj / "harness.toml", "a") as f:
        f.write('[agents.cloudy]\nprovider = "openai"\nmodel = "gpt-4.1-mini"\n')
    r = cli(proj, "doctor", "--dry-run")
    assert r.returncode == 0 and r.stdout.startswith("Doctor: warning") and "OPENAI_API_KEY is not set" in r.stdout and "\x1b" not in r.stdout
    assert cli(proj, "doctor", "--dry-run", "--strict").returncode == 1


def test_the_preflight_dry_run_never_touches_the_network(proj, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the network was touched")

    monkeypatch.setattr(providers, "probe_ollama", boom)
    monkeypatch.setattr(providers, "http", boom)
    res = doctor.preflight(app.load(proj / "harness.toml"), dry_run=True)
    assert res["verdict"] in ("ready", "warning") and res["tokens_spent"] == 0


def test_a_redo_needs_a_note_in_the_cli_as_it_does_on_the_dashboard(proj):
    cli(proj, "task", "add", "do it", "--queue", "echo")
    cli(proj, "run")
    no_note = cli(proj, "review", "1", "redo")
    assert no_note.returncode == 2 and "a redo needs a note" in no_note.stderr
    assert json.loads(cli(proj, "review", "1", "redo", "--json").stdout)["ok"] is False
    done = cli(proj, "review", "1", "redo", "fix the title", "--json")
    assert done.returncode == 0 and json.loads(done.stdout) == {"ok": True, "id": 1, "verdict": "redo", "note": "fix the title"}


def test_json_everywhere_and_failures_are_json_under_json(proj):
    added = json.loads(cli(proj, "task", "add", "x", "--queue", "echo", "--json").stdout)
    assert added["ok"] and added["id"] == 1 and added["queue"] == "echo"
    bad = cli(proj, "task", "add", "x", "--queue", "ghost", "--json")
    assert bad.returncode == 2 and json.loads(bad.stdout)["ok"] is False and bad.stderr == ""
    assert json.loads(cli(proj, "run", "--json").stdout)["results"][0]["ok"] is True
    assert json.loads(cli(proj, "discard", "1", "--json").stdout) == {"ok": False, "id": 1}
    assert "by_status" in json.loads(cli(proj, "status", "--json").stdout)
    assert json.loads(cli(proj, "providers", "list", "--profile", "cloud-max", "--json").stdout)["profile"] == "cloud-max"


def test_watch_redraws_and_needs_a_terminal_unless_told_how_many_frames(proj):
    r = cli(proj, "status", "--watch", "--interval", "0.2", "--count", "2")
    assert r.returncode == 0 and r.stdout.count("every 0.2 s") == 2
    assert "needs a terminal" in cli(proj, "task", "list", "--watch").stderr
    assert cli(proj, "metrics", "--watch", "--interval", "fast", "--count", "1").returncode == 2


def test_completion_scripts_are_valid_and_know_every_command(tmp_path):
    from caos_harness.__main__ import COMMANDS, WORK
    for shell in ("bash", "zsh"):
        out = cli(tmp_path, "completion", shell)
        assert out.returncode == 0
        assert all(c in out.stdout for c in [*COMMANDS, *WORK, "tar.gz", "local-first", "cloud-max"])
        exe = shutil.which(shell)
        if exe:
            assert subprocess.run([exe, "-n"], input=out.stdout, text=True, capture_output=True).returncode == 0
    assert cli(tmp_path, "completion", "fish").returncode == 2 and cli(tmp_path, "completion").returncode == 2
    assert set(completion.SUBCOMMANDS["share"]) == {"doctor", "preview", "pack", "upload"}


def test_the_cli_and_repl_speak_english_only():
    pat = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]|\b(?:Ejecutar|Proyecto|Estado|Pulsa|Falta|Aprobar)\b")
    for name in ("__main__.py", "repl.py", "term.py", "doctor.py", "completion.py", "style.py"):
        hits = [(i, ln.strip()[:80]) for i, ln in enumerate((ROOT / "caos_harness" / name).read_text(encoding="utf-8").splitlines(), 1) if pat.search(ln)]
        assert not hits, (name, hits)


def test_repl_pack_takes_the_three_formats_and_refuses_others(proj, capsys):
    from caos_harness import repl
    sess = repl.Session(app.load(proj / "harness.toml"))
    assert sess.handle("/pack tar.gz")
    assert "Share Pack created" in capsys.readouterr().out and list((proj / ".harness" / "exports").glob("*.tar.gz"))
    assert sess.handle("/pack tar")
    assert "unknown format" in capsys.readouterr().err


# ─ the terminal's layout ─

def test_panels_and_tables_are_boxes_on_a_terminal_and_plain_lines_when_piped(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    with style.force(True):
        box = term.panel("title", ["alpha", "beta " + style.paint("x", style.CORAL)], 40)
        assert box[0].startswith(("╭", "\x1b")) and "╭" in term.strip_ansi(box[0]) and term.strip_ansi(box[-1]).startswith("╰")
        assert {term.vlen(ln) for ln in box} == {40}                       # every line the same width, colour not counted
        tbl = term.table(["id", "name"], [["1", "ab"], ["22", "a longer name"]], ">", w=60)
        assert [term.vlen(ln) for ln in tbl] == [term.vlen(tbl[0])] * len(tbl) and "┬" in term.strip_ansi(tbl[0]) and "┼" in term.strip_ansi(tbl[2])
        narrow = term.table(["a", "b"], [["x" * 60, "y"]], w=40)
        assert max(term.vlen(ln) for ln in narrow) <= 40 and "…" in "".join(narrow)
    with style.force(False):
        assert term.panel("title", ["alpha"]) == ["title", "  alpha"]
        assert term.table(["id", "name"], [["1", "ab"], ["22", "cd"]], ">", header=False) == [" 1  ab", "22  cd"]


def test_no_color_removes_colour_not_structure(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "xterm-256color")
    with style.force(True):
        assert not style.enabled() and style.fancy() and style.paint("x", style.AMBAR) == "x"
        assert "╭" in term.panel("t", ["a"], 20)[0]
    monkeypatch.setenv("TERM", "dumb")
    with style.force(True):
        assert not style.fancy() and term.panel("t", ["a"]) == ["t", "  a"]


def test_the_palette_keeps_the_champagne_of_the_mark_and_has_a_colour_per_state():
    assert style.CHAMPAN == (235, 211, 187)
    assert len({style.AMBAR, style.ACERO, style.SALVIA, style.CORAL}) == 4
    assert set(style.VERDICT_TONE) == {"ready", "warning", "blocked"} and style.TONE["to_review"] == style.AMBAR and style.TONE["ok"] == style.SALVIA


def test_the_spinner_draws_only_on_a_terminal_and_ends_with_a_line():
    class Tty(io.StringIO):
        def isatty(self):
            return True

    quiet = io.StringIO()
    with term.Spinner("work", stream=quiet):
        pass
    assert quiet.getvalue() == ""                                          # piped: silent
    tty = Tty()
    with term.Spinner("work", stream=tty, enabled=True, interval=0.01) as sp:
        time.sleep(0.05)
        sp.update("more work")
    out = term.strip_ansi(tty.getvalue())
    assert "⠋" in out and "✓ more work" in out
    bad = Tty()
    with pytest.raises(RuntimeError):
        with term.Spinner("boom", stream=bad, enabled=True, interval=0.01):
            raise RuntimeError("x")
    assert "✗ boom" in term.strip_ansi(bad.getvalue())


def test_watch_stops_after_count_frames_and_on_ctrl_c():
    out, naps = io.StringIO(), []
    frames = iter(range(10))
    assert term.watch(lambda: f"frame {next(frames)}", interval=0.5, out=out, count=3, sleep=naps.append) == 0
    assert out.getvalue().count("frame") == 3 and naps == [0.5, 0.5]

    def interrupted(_):
        raise KeyboardInterrupt

    assert term.watch(lambda: "x", out=io.StringIO(), sleep=interrupted) == 0


def test_a_real_terminal_draws_boxes_and_obeys_no_color(proj):
    import pty
    import select
    cli(proj, "task", "add", "look at the retry policy", "--queue", "person")
    for no_color in (False, True):
        env = {**os.environ, "PYTHONPATH": str(ROOT), "COLUMNS": "100", "TERM": "xterm-256color", "CAOS_HARNESS_HOME": str(proj / ".home")}
        env.pop("NO_COLOR", None)
        if no_color:
            env["NO_COLOR"] = "1"
        out = b""
        for args in (["task", "list"], ["doctor", "--dry-run"]):
            master, slave = pty.openpty()
            proc = subprocess.Popen([sys.executable, "-m", "caos_harness", *args], stdin=slave, stdout=slave, stderr=slave, cwd=proj, env=env, close_fds=True)
            os.close(slave)
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
        assert "╭" in text and "│" in text and "look at the retry policy" in text and "READY" in text
        assert ("\x1b[38;2;" in text) == (not no_color)


# ─ over HTTP, on an ephemeral port ─

@pytest.fixture
def http(proj):
    from http.server import ThreadingHTTPServer
    import urllib.error
    import urllib.request
    from caos_harness.web.server import make_handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Api(app.load(proj / "harness.toml"))))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json", "X-Harness": "1"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read()), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read()), e.headers
    yield call
    srv.shutdown()
    srv.server_close()


def test_the_preview_and_preflight_endpoints_and_a_refused_format(http, proj):
    st, prev, _ = http("/api/share/preview?format=tar.gz&include_docs=0")
    assert st == 200 and prev["format"] == "tar.gz" and prev["dry_run"] is True
    assert http("/api/share/preview", {"format": "dir"})[1]["format"] == "dir"
    st, err, _ = http("/api/share/preview?format=tar")
    assert st == 400 and "unknown format" in err["error"]
    st, err, _ = http("/api/share/pack", {"format": "rar"})
    assert st == 409 and "unknown format" in err["error"] and not (proj / ".harness" / "exports").exists()
    st, res, _ = http("/api/preflight?dry_run=1")
    assert st == 200 and res["dry_run"] is True and res["verdict"] in ("ready", "warning") and res["tokens_spent"] == 0
    st, built, _ = http("/api/share/pack", {"format": "tar.gz"})
    assert st == 200 and built["filename"].endswith(".tar.gz") and built["verified"] is True
    st, ex, _ = http("/api/share/exports")
    assert any(e["filename"].endswith(".tar.gz") for e in ex["exports"])


def test_the_cli_shows_what_a_person_is_asked_to_approve(capsys):
    from caos_harness.__main__ import _show_approval
    step = {"input": "notes.txt", "summary_what": "Create notes.txt", "preview": {"path": "notes.txt", "new_file": True, "added": 1, "removed": 0, "bytes": 6, "diff": "--- a/notes.txt\n+++ b/notes.txt\n@@ -0,0 +1 @@\n+hello", "diff_truncated": False}}
    assert _show_approval(step, "/w") == "Apply this change? [y/N] "
    out = capsys.readouterr().out
    assert "notes.txt" in out and "new file" in out and "+hello" in out and "Create notes.txt" in out
    assert _show_approval({"input": "ls -la", "summary_what": "list"}, "/w") == "Run with your OS permissions? [y/N] "
    assert "Command in /w" in capsys.readouterr().out
