"""The conversation screen: a prompt reaches a real agent or a local model, output and approvals stream back, files attach safely."""
import os
import time
from pathlib import Path

import pytest
from caos_harness import app, chat, tui


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / "home"))
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a") as f:
        f.write('[agents.upper]\ncommand = ["tr", "a-z", "A-Z"]\nsystem = "llama3.2:3b"\n[agents.slow]\ncommand = ["sleep", "2"]\ntimeout = 5\n')
    return app.load(tmp_path / "harness.toml")


def wait(ui, pred, secs=6):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def type_(ui, s):
    for ch in s:
        ui.key(ch)
    ui.key("enter")


def text(rows):
    return "\n".join("".join(t for t, _ in r) for r in rows)


class FakeLLM:
    """Plan mode: answers. Act mode: asks for one command, then answers with what it saw."""
    def __init__(self, model): self.n = 0
    def chat(self, messages, tools):
        self.n += 1
        if tools and self.n == 1:
            return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "run_command", "arguments": {"command": "echo from-the-model"}}}]}
        seen = [m["content"] for m in messages if m.get("role") == "tool"]
        return {"role": "assistant", "content": "I ran it: " + (seen[-1].split("stdout:")[1].strip()[:20] if seen and "stdout:" in seen[-1] else "nothing") if seen else "plan: look at the folder"}


def test_a_prompt_goes_to_the_agent_as_a_task_and_the_delivery_comes_back(project):
    ui = tui.ChatUI(project, models=[])
    ui.command("agent upper")
    type_(ui, "make me loud")
    assert wait(ui, lambda: not ui.conv.busy())
    reply = ui.conv.turns[-1]
    assert reply.text == "MAKE ME LOUD" and reply.task == 1 and project.board.get(1)["result"] == "MAKE ME LOUD"
    out = text(ui.compose(120, 34)[0])
    assert "you" in out and "make me loud" in out and "MAKE ME LOUD" in out and "task 1" in out
    ui.key("ctrl-a"); assert ui.text == "/accept "                       # Ctrl-A asks for the reason first
    ui.command("accept"); assert project.board.get(1)["review"] is None and "needs a reason" in ui.message
    ui.command("accept read it and it matches"); assert project.board.get(1)["review"] == "ok"
    ui.command("return"); assert "needs a note" in ui.message or "no delivery" in ui.message


def test_files_attach_only_from_inside_the_project_and_never_secrets(project):
    root = project.root
    (root / "notes.txt").write_text("hello file")
    (root / ".env").write_text("TOKEN=abc")
    (root / "sub").mkdir(); (root / "sub" / "key.pem").write_text("x")
    (root / "big.txt").write_text("a" * 30000)
    out, names, refused = chat.attach(root, "read @notes.txt and @big.txt and @.env and @sub/key.pem and @../outside")
    assert names == ["notes.txt", "big.txt"] and "hello file" in out and "TOKEN" not in out and "[…cut at 20 KB]" in out
    assert len(refused) == 3 and any("outside" in r for r in refused) and any("secret" in r for r in refused)


def test_a_local_model_answers_in_plan_mode_and_commands_need_switching_on_and_approving(project, monkeypatch):
    monkeypatch.setattr("caos_harness.engines.workstation.OllamaChat", FakeLLM)
    ui = tui.ChatUI(project, models=["fake:1b"])
    ui.command("model fake:1b")
    assert "act needs" in ui.conv.set_mode("act")                       # commands are off: act is refused
    type_(ui, "what is here?")
    assert wait(ui, lambda: not ui.conv.busy()) and ui.conv.turns[-1].text == "plan: look at the folder"
    ui.command("commands on"); ui.key("tab"); assert ui.conv.mode == "act"
    type_(ui, "run something")
    assert wait(ui, lambda: ui.conv.turns[-1].status == "awaiting")
    assert "run it?" in text(ui.compose(120, 34)[0]) and "echo from-the-model" in text(ui.compose(120, 34)[0])
    ui.key("y")
    assert wait(ui, lambda: not ui.conv.busy()) and "from-the-model" in ui.conv.turns[-1].text
    type_(ui, "again")
    assert wait(ui, lambda: ui.conv.turns[-1].status == "awaiting")
    ui.key("n")
    assert wait(ui, lambda: not ui.conv.busy()) and ui.conv.turns[-1].steps[-1]["status"] == "denied"


def test_esc_stops_waiting_and_the_task_stays_on_the_board(project):
    ui = tui.ChatUI(project, models=[])
    ui.command("agent slow")
    type_(ui, "take your time")
    assert wait(ui, lambda: ui.conv.busy())
    assert "queued (1)" in (ui.conv.send("second") or "")
    ui.key("esc"); assert ui.conv.queue == []
    assert ui.conv.turns[-1].status == "stopped" and not ui.conv.busy()
    assert project.board.get(1) is not None


def test_sessions_resume_with_the_transcript_and_skin_is_remembered(project):
    ui = tui.ChatUI(project, models=[]); ui.session_id = "20260101-000000-000"
    ui.command("agent upper"); type_(ui, "first prompt")
    assert wait(ui, lambda: not ui.conv.busy()); ui.save()
    ui.command("skin mono"); assert tui.load_settings()["skin"] == "mono"
    again = tui.ChatUI(project, models=[])
    assert again.skin == "mono" and again.resume("")
    assert again.conv.name == "upper" and [t.text for t in again.conv.turns][:2] == ["first prompt", "FIRST PROMPT"] and again.history == ["first prompt"]
    again.key("ctrl-s"); assert again.popup == "sessions" and again.items[0].label == "first prompt"


def test_the_screen_fits_the_window_shows_a_banner_when_empty_and_a_picker_on_top(project):
    ui = tui.ChatUI(project, models=["fake:1b"])
    rows, cursor = ui.compose(120, 34)
    out = text(rows)
    assert len(rows) == 34 and all(sum(len(t) for t, _ in r) <= 120 for r in rows) and "agents you can check" in out and "Session" in out and cursor
    ui.key("ctrl-p"); out = text(ui.compose(120, 34)[0])
    assert "Choose the target" in out and "ollama · fake:1b" in out and "router · cost of error low" in out
    ui.key("esc"); ui.key("?"); assert "Keys" in text(ui.compose(120, 34)[0])
    ui.key("x"); ui.key("ctrl-b"); assert ui.view == "board" and "Queues" in text(ui.compose(120, 34)[0])
    ui.key("ctrl-b"); assert ui.view == "chat"


def test_slash_commands_are_suggested_and_tab_completes_them(project):
    ui = tui.ChatUI(project, models=[])
    ui.key("/"); ui.key("s")
    assert ui.suggest() == ["sessions", "side", "skill", "skills", "skin"] and "Tab completes" in text(ui.compose(120, 34)[0])
    ui.key("tab"); assert ui.text == "/sessions "
    ui.text = ""; ui.key("tab"); assert ui.conv.mode == "plan" and "act needs" in ui.message          # without a slash, Tab is the mode switch


def test_cancel_rejects_a_waiting_command_and_ends_the_run(project, monkeypatch):
    monkeypatch.setattr("caos_harness.engines.workstation.OllamaChat", FakeLLM)
    ui = tui.ChatUI(project, models=["fake:1b"]); ui.command("model fake:1b"); ui.command("commands on"); ui.key("tab")
    type_(ui, "do it"); assert wait(ui, lambda: ui.conv.turns[-1].status == "awaiting")
    ui.key("esc")
    assert ui.conv.turns[-1].status == "stopped" and not ui.conv.busy()


def test_density_and_hints_are_personal_settings_and_the_modal_is_a_closed_frame(project):
    ui = tui.ChatUI(project, models=[])
    ui.command("density compact"); ui.command("hints minimal")
    cfg = tui.load_settings()
    assert cfg["density"] == "compact" and cfg["hints"] == "minimal"
    again = tui.ChatUI(project, models=[]); assert again.density == "compact" and again.hints == "minimal"
    again.key("?"); out = text(again.compose(110, 30)[0])
    assert "┌" in out and "┘" in out and "Keys" in out


def test_attach_never_reads_past_the_cap_and_refuses_text_that_holds_a_key(project):
    root = project.root
    (root / "log.txt").write_text("x" * 5_000_000)
    (root / "notes.md").write_text("remember: sk-" + "a" * 30)
    (root / "ok.txt").write_text("fine")
    out, names, refused = chat.attach(root, "@log.txt @notes.md @ok.txt @a @b @c @d")
    assert names[0] == "log.txt" and len(out) < 25_000 and any("holds a key" in r for r in refused) and "ok.txt" in names
    assert len(chat.REF.findall("@a @b @c @d @e @f @g")) == 7 and len(names) + len(refused) <= chat.MAX_REFS


def test_a_new_exchange_keeps_its_own_run_and_history_excludes_refusal_notes(project, monkeypatch):
    seen = []
    class Spy(FakeLLM):
        def chat(self, messages, tools):
            seen.append([m["content"] for m in messages if m["role"] in ("user", "assistant")])
            return {"role": "assistant", "content": "ok " + str(len(seen))}
    monkeypatch.setattr("caos_harness.engines.workstation.OllamaChat", Spy)
    ui = tui.ChatUI(project, models=["fake:1b"]); ui.command("model fake:1b")
    type_(ui, "first @missing.txt"); assert wait(ui, lambda: not ui.conv.busy())
    type_(ui, "second"); assert wait(ui, lambda: not ui.conv.busy())
    assert seen[1] == ["first @missing.txt", "ok 1", "second"]          # the refusal note is not history and no real turn is dropped


def test_stopping_an_agent_turn_is_not_overwritten_when_the_task_finishes(project):
    ui = tui.ChatUI(project, models=[]); ui.command("agent slow"); type_(ui, "wait")
    assert wait(ui, lambda: ui.conv.busy()); ui.key("esc")
    time.sleep(2.4)
    assert ui.conv.turns[-1].status == "stopped" and "Stopped waiting" in ui.conv.turns[-1].text


def test_prompts_typed_while_an_agent_works_wait_in_order_and_commands_are_shown_whole(project, monkeypatch):
    ui = tui.ChatUI(project, models=[]); ui.command("agent slow"); type_(ui, "one")
    assert wait(ui, lambda: ui.conv.busy())
    ui.command("agent upper")
    assert "queued (1)" in ui.conv.send("two")
    assert wait(ui, lambda: len(ui.conv.turns) >= 4 and not ui.conv.busy(), 12)
    assert [t.text for t in ui.conv.turns if t.role == "user"] == ["one", "two"] and not ui.conv.queue
    # a long command that waits for approval is drawn in full, with where it runs, never clipped
    long_cmd = "echo " + "x" * 150
    t = chat.Turn("agent", "", "awaiting", who="m", steps=[{"name": "Shell command", "status": "awaiting_approval", "input": long_cmd}])
    ui.conv.turns.append(t)
    out = text(ui.compose(110, 40)[0]).replace("\n", "")
    assert "x" * 150 in out.replace(" ", "").replace("│", "") or out.count("x") >= 150
    assert "not in a sandbox" in out and "run it?" in out
