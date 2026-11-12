"""Phase 4: one palette for the dashboard, the CLI and the full-screen interface; the wide split in Board and Skills; Plan answers on keys 1-4."""
import io
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from caos_harness import app, chat, providers, style, tui
from caos_harness.tui import board_view, extra_views
from caos_harness.tui.theme import SKINS, apply_curses_skin

ROOT = Path(__file__).resolve().parent.parent
COPPER = {"amber": "#EE9A3E", "champagne": "#E2B076", "bone": "#F5F2EC", "silver": "#BBB3A8", "dim": "#948C81", "sage": "#6BC78E", "coral": "#E87066", "steel": "#7FA6D6"}


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / "home"))
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a") as f:
        f.write('[agents.upper]\ncommand = ["tr", "a-z", "A-Z"]\nsystem = "llama3.2:3b"\n')
    return app.load(tmp_path / "harness.toml")


def text(rows):
    return ["".join(t for t, _ in r) for r in rows]


# ─ the palette ─

def test_the_terminal_speaks_the_dashboards_copper_palette():
    assert (style.AMBAR, style.ACERO, style.SALVIA, style.CORAL) == (rgb("#EE9A3E"), rgb("#7FA6D6"), rgb("#6BC78E"), rgb("#E87066"))
    assert (style.HUESO, style.GRIS, style.TENUE, style.PLATA) == (rgb("#F5F2EC"), rgb("#BBB3A8"), rgb("#9A9287"), rgb("#6E5842"))
    assert style.COBRE == rgb("#E2B076") and style.CHAMPAN == rgb("#EBD3BB")
    css = (ROOT / "web" / "src" / "theme.css").read_text()           # the Web is the source of the palette: the same values
    for token in ("#EE9A3E", "#7FA6D6", "#6BC78E", "#E87066", "#040405", "226, 176, 118", "#F5F2EC", "#948C81"):
        assert token.lower() in css.lower(), token


def test_the_night_skin_matches_the_palette_and_the_other_skins_are_untouched():
    assert {k: v[1] for k, v in SKINS["night"].items()} == COPPER
    assert SKINS["ember"]["amber"] == (208, "#FF8700") and SKINS["mono"] is None


def test_every_night_index_is_the_nearest_xterm_colour_to_its_hex():
    lv = [0, 95, 135, 175, 215, 255]
    pal = {16 + i: (lv[i // 36], lv[(i // 6) % 6], lv[i % 6]) for i in range(216)} | {232 + i: (8 + 10 * i,) * 3 for i in range(24)}
    for name, (idx, hexv) in SKINS["night"].items():
        r, g, b = rgb(hexv)
        best = min(pal, key=lambda k: (pal[k][0] - r) ** 2 + (pal[k][1] - g) ** 2 + (pal[k][2] - b) ** 2)
        assert idx == best, (name, idx, best)


def test_no_color_and_pipes_stay_plain_text(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert "\x1b[38;2;238;154;62m" in style.paint("x", style.AMBAR, stream=Tty())
    monkeypatch.setenv("NO_COLOR", "1")
    assert style.paint("x", style.AMBAR, stream=Tty()) == "x"
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert style.paint("x", style.AMBAR, stream=Tty()) == "x"
    out = subprocess.run([sys.executable, "-m", "caos_harness", "help"], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT)}).stdout
    assert "\x1b" not in out and "caos · harness" in out                # piped: no colour, no escape codes
    curses = SimpleNamespace(A_NORMAL=0, A_BOLD=1, A_DIM=2, A_REVERSE=4, has_colors=lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")
    attrs = apply_curses_skin(curses, "night")                          # NO_COLOR: attributes only, no colour pairs
    assert attrs["bone"] == 1 and attrs["rev"] == 4 and attrs["sage"] == 0


# ─ Board: list and task side by side ─

def board_with_task(project, long=False):
    for i in range(6):
        tid, *_ = app.add_task(project, f"check the retry policy of the dispatcher, case {i}", queue="upper")
        app.run_task(project, tid)
    st = board_view.State(project)
    st.detail_open = True
    return st


def body_separators(rows):
    return {tuple(i for i, ch in enumerate(line) if ch == "│") for line in rows if line.count("│") >= 2}


def test_board_shows_the_list_and_the_open_task_side_by_side_from_120_columns(project):
    st = board_with_task(project)
    wide = text(board_view.compose(st, 132, 30)[0])
    narrow = text(board_view.compose(st, 96, 30)[0])
    head = next(r for r in wide if "Tasks" in r)
    assert head.rstrip().endswith("Task") and head.count("│") == 2                 # queues | tasks | task
    assert any("to review" in r and ("queue upper" in r or "Delivered" in r) for r in wide)       # the task sits on the same rows as the list
    assert not any("to review" in r and ("queue upper" in r or "Delivered" in r) for r in narrow)  # narrower, it stacks under the list as before
    assert all(len(r) <= 132 for r in wide) and all(len(r) <= 96 for r in narrow)
    assert len(body_separators(wide)) == 1                                        # every body row has its column edges in the same places: nothing shifted or overlapped
    assert "Session" not in "\n".join(wide)                                        # the session panel gives way to the task...
    assert "Session" in "\n".join(text(board_view.compose(st, 170, 30)[0]))       # ...and comes back when there is room for both


def test_a_long_delivery_wraps_inside_its_column_and_scrolls(project):
    tid, *_ = app.add_task(project, "long one", queue="upper")
    app.run_task(project, tid)
    project.board.conn.execute("UPDATE tasks SET result=? WHERE id=?", ("word " * 400, tid))
    project.board.conn.commit()
    st = board_view.State(project)
    st.detail_open = True
    rows = text(board_view.compose(st, 132, 24)[0])
    assert all(len(r) <= 132 for r in rows) and any(re.search(r"lines \d+-\d+/\d+", r) for r in rows)
    assert len(body_separators(rows)) == 1


def test_a_closed_detail_keeps_the_list_alone_even_when_wide(project):
    st = board_with_task(project)
    st.detail_open = False
    rows = text(board_view.compose(st, 132, 30)[0])
    assert not any(r.count("│") == 2 and r.rstrip().endswith("Task") for r in rows) and not any("Delivered" in r for r in rows)


# ─ Skills: the list and the whole skill side by side ─

def test_skills_show_the_whole_selected_skill_beside_the_doctor_and_pack_from_120_columns(project):
    done = {"clean": True, "scanned": 9, "issues": []}
    wide, _ = extra_views.compose_skills_share_tab(project, 132, 30, 2, None, done, None, "")
    narrow, _ = extra_views.compose_skills_share_tab(project, 96, 30, 2, None, done, None, "")
    w, n = text(wide), text(narrow)
    names = list(__import__("caos_harness.skills", fromlist=["x"]).load_all(project_root=project.root).values())
    picked = names[2]
    assert any("Skills (" in r and "Skill · Tools · Doctor · Share Pack" in r for r in w)       # two boxes on the same top row
    assert any(picked.name in r for r in w) and any("bundle (solo lectura)" in r for r in w) and any("SKILL.md" in r for r in w)
    assert any("Doctor:" in r for r in w) and any("Tools & MCP:" in r for r in w)
    doctor = next(r for r in w if "Doctor:" in r)
    assert doctor.rstrip().endswith("│") and doctor.index("│") > 46                                # the Doctor is inside the right-hand box, to the right of the list column
    skill_row = next(i for i, r in enumerate(w) if "SKILL.md" in r)
    assert skill_row < next(i for i, r in enumerate(w) if "Doctor:" in r)                         # the skill first, then the tools, the Doctor and the pack
    assert not any("SKILL.md" in r for r in n) and next(i for i, r in enumerate(n) if "Doctor:" in r) > max(i for i, r in enumerate(n) if names[-1].name in r)
    assert all(len(r) <= 132 for r in w) and all(len(r) <= 96 for r in n) and len(wide) == len(narrow) == 30


def test_providers_and_metrics_stay_single_column_when_wide(project, monkeypatch):
    monkeypatch.setattr(providers, "probe_ollama", lambda hosts=None, timeout=1.2: {"online": True, "hosts": [{"id": "local", "label": "Local", "url": "http://127.0.0.1:11434", "online": True, "models": ["a:1b"]}], "models": ["a:1b"], "details": []})
    prov, _ = extra_views.compose_providers_tab(project, 132, 30, 0, None, None, "")
    met, _ = extra_views.compose_metrics_tab(project, "project", 132, 30, 0, "")
    for rows in (prov, met):
        assert all(r.count("╭") <= 1 for r in text(rows)) and all(len(r) <= 132 for r in text(rows))


# ─ Plan answers on keys 1-4 ─

QUESTIONS = [{"question": "Run the tests first?", "chips": ["Yes", "Only the diff"]}, {"question": "Isolate in a worktree?", "chips": ["Yes", "No", "Later"]}]


def asking_ui(project, mode="plan", status="done"):
    ui = tui.ChatUI(project, models=["llama3.2:3b"])
    ui.conv.mode = mode
    ui.conv.turns.append(chat.Turn("agent", "Before I plan, two questions.", status=status, questions=[dict(q) for q in QUESTIONS]))
    return ui


def test_keys_one_to_four_answer_the_plan_questions_into_the_composer(project):
    ui = asking_ui(project)
    ui.key("1")
    assert ui.text == "Alignment answers: Run the tests first?: Yes"
    ui.key("1")
    assert ui.text.endswith("Run the tests first?: Only the diff")                            # a second press moves to the next option
    ui.key("2")
    assert ui.text == "Alignment answers: Run the tests first?: Only the diff; Isolate in a worktree?: Yes"
    ui.key("2"); ui.key("2"); ui.key("2")
    assert ui.text.endswith("Isolate in a worktree?: Yes")                                    # three options: it came back around
    ui.key("3")
    assert "there is no question 3" in ui.message and "Isolate" in ui.text                   # nothing changed
    rows = text(ui.compose(120, 30)[0])
    assert any("[Only the diff]" in r for r in rows) and any("Enter sends" in r or "answer" in r for r in rows)


def test_the_keys_do_not_steal_digits_from_a_normal_message(project):
    typed = asking_ui(project)
    for ch in "run 1":
        typed.key(ch)
    assert typed.text == "run 1" and not typed.qa_pick                                          # typing is untouched
    act = asking_ui(project, mode="act")
    act.key("1")
    assert act.text == "1"                                                                      # only Plan answers
    waiting = asking_ui(project, status="awaiting")
    waiting.key("1")
    assert waiting.text == "" or waiting.text != "Alignment answers: Run the tests first?: Yes"
    popup = asking_ui(project)
    popup.popup = "help"
    popup.key("1")
    assert popup.text == ""                                                                     # a popup keeps its own keys
    f2 = asking_ui(project)
    f2.key("f2")
    assert f2.view == "board"                                                                   # F1..F5 still switch views


def test_sending_clears_the_picks_so_the_next_question_starts_fresh(project):
    ui = asking_ui(project)
    ui.key("1")
    assert ui.qa_pick == {1: 0}
    ui.key("enter")
    assert ui.qa_pick == {} and ui.qa_text == "" and ui.text == ""


def test_picks_are_dropped_when_the_composer_is_edited_cleared_or_a_new_plan_turn_arrives(project):
    ui = asking_ui(project)
    ui.key("1")
    ui.key("esc")
    assert ui.text == ""
    ui.key("1")
    assert ui.text == "Alignment answers: Run the tests first?: Yes"                         # cleared with Esc: starts again at the first option
    ui.key("backspace")
    ui.key("1")
    assert ui.qa_pick == {} and ui.text.endswith("1")                                         # edited by hand: the digit is typing, not an answer
    again = asking_ui(project)
    again.key("1")
    again.conv.turns.append(SimpleNamespace(**{**vars(again.conv.turns[-1])}))               # a newer Plan turn with its own questions
    again.text = ""
    again.key("1")
    assert again.qa_pick == {1: 0}


def test_a_question_that_is_not_a_dict_is_ignored_when_drawing(project):
    ui = asking_ui(project)
    ui.conv.turns[-1].questions = ["just text", {"question": "Run the tests first?", "chips": ["Yes", "No"]}]
    rows = text(ui.compose(120, 30)[0])
    assert any("Run the tests first?" in r for r in rows)


def test_a_narrow_open_task_never_overflows_and_the_skills_split_closes_on_the_same_column(project):
    st = board_with_task(project)
    for h in (6, 8, 12):
        rows = text(board_view.compose(st, 132, h)[0])
        assert all(len(r) <= 132 for r in rows)
    st.detail_scroll = 9
    st.key("2")
    assert st.detail_scroll == 0
    st.detail_scroll = 9
    st.key("]")
    assert st.detail_scroll == 0
    done = {"clean": True, "scanned": 9, "issues": []}
    for w in (120, 132, 150):
        wide, _ = extra_views.compose_skills_share_tab(project, w, 30, 0, None, done, None, "")
        rows = text(wide)
        assert all(len(r) <= w for r in rows) and len(rows[0].rstrip()) == w - 1                # both boxes close on the last column but one


# ─ Tabs 3 and 4: the row you see is the row that acts ─

FAKE_OLLAMA = {"online": True, "hosts": [{"id": "local", "label": "Local", "url": "http://127.0.0.1:11434", "online": True, "models": ["a:1b"]}], "models": ["a:1b"], "details": []}


def test_tab_three_keys_act_on_the_row_that_is_selected_even_with_a_custom_gateway(project, monkeypatch):
    monkeypatch.setattr(providers, "probe_ollama", lambda hosts=None, timeout=1.2: FAKE_OLLAMA)
    providers.save_custom_provider({"id": "mygw", "name": "My Gateway", "base_url": "https://gw.example.test/v1", "kind": "openai", "api_key_env": "MYGW_API_KEY", "default_model": "gw-model"}, root=project.root)
    entries = extra_views.provider_entries(project, FAKE_OLLAMA, [{"id": "local"}])
    assert entries[0]["provider"] == "ollama" and entries[-1]["provider"] == "mygw" and len(entries) == 1 + len(providers.API) + 1
    shown = text(extra_views.compose_providers_tab(project, 120, 30, len(entries) - 1, None, None, "")[0])
    assert any("› ● My Gateway" in r or ("My Gateway" in r and "›" in r) for r in shown)       # the selected row is the gateway
    ui = tui.ChatUI(project, models=["a:1b"])
    ui.view = "providers"
    ui.extra_sel["providers"] = len(entries) - 1
    ui.key("enter")
    assert ui.view == "chat" and "mygw" in ui.message and "gw-model" in ui.message


def test_tab_four_keeps_the_selected_model_on_screen_and_degrades_it_with_its_provider(project):
    from caos_harness import metrics
    for i in range(14):
        metrics.record_run(project.root, "openrouter" if i == 11 else "ollama", f"model-{i:02d}", 100 + i, True)
    names = [m["model"] for m in metrics.snapshot(project, scope="project")["models"]]
    rows = text(extra_views.compose_metrics_tab(project, "project", 120, 14, names.index("model-11"), "")[0])
    assert names.index("model-11") > 3 and any("model-11" in r and "›" in r for r in rows)                                    # a row far down the table is still visible when selected
    ui = tui.ChatUI(project, models=["a:1b"])
    ui.view = "metrics"
    ui.extra_sel["metrics"] = names.index("model-11")
    ui.key("d")
    assert metrics.load_demotions(project.root)["openrouter:model-11"]["demoted"] is True and "model-11" not in metrics.load_demotions(project.root)
