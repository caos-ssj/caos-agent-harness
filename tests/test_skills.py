import re

import pytest
from caos_harness.skills import known, load_all, load_packaged, parse



def test_every_skill_parses_and_names_when_to_use_it():
    skills = load_packaged()
    assert set(skills) == {
        "coder",
        "qa",
        "writer",
        "model-selection",
        "social-content",
        "source-research",
        "proposals",
        "ui-design",
        "webapp-testing",
        "mcp-builder",
        "context-engineering",
        "doc-converter",
    }
    assert not skills["social-content"].team_shareable
    assert not skills["proposals"].team_shareable
    assert skills["coder"].team_shareable and skills["ui-design"].team_shareable
    for s in skills.values():
        assert len(s.description) > 30 and len(s.body.splitlines()) <= 40, s.name  # short enough to be read every time


def test_public_skills_carry_no_private_paths_or_project_names():
    for s in load_packaged().values():
        assert not re.search(r"/home/|~/|Proyecto_caos|b[oó]veda|caos-stack|crypto-bot", s.body + s.description, re.I), s.name


def test_model_selection_points_to_the_router_instead_of_copying_its_table():
    body = load_packaged()["model-selection"].body
    assert "make route" in body and "llama" not in body and "qwen" not in body


def test_board_sends_the_skill_pointer_before_the_task():
    from caos_harness.board import Board

    class Disp:
        sent = []

        def is_idle(self, a):
            return True

        def send(self, a, t):
            self.sent.append(t)

    assert known("qa") and not known("astrology")
    b, d = Board(), Disp()
    t = b.add("check the report", skill="qa")
    b.assign(t, "a", d)
    assert d.sent[0] == "Load the skill 'qa' before starting. Task: check the report"
    b.deliver(t, "r")
    b.review(t, "redo", "no evidence")
    b.assign(t, "a", d)
    assert d.sent[1].startswith("Load the skill 'qa' before starting. Task: Returned by the reviewer")


@pytest.mark.parametrize("text,err", [("no front matter", "missing front matter"), ("---\nname: x\n---\nbody", "needs name and description"),
                                      ("---\nname: other\ndescription: d\n---\nbody", "does not match its folder")])
def test_malformed_skill_is_refused(tmp_path, text, err):
    d = tmp_path / "x"
    d.mkdir()
    (d / "SKILL.md").write_text(text)
    with pytest.raises(ValueError, match=err):
        parse(d / "SKILL.md")


def test_local_skills_join_the_packaged_ones_without_entering_the_repository(tmp_path, monkeypatch):
    own = tmp_path / "own" / "my-proposals"
    own.mkdir(parents=True)
    (own / "SKILL.md").write_text("---\nname: my-proposals\ndescription: How I write proposals: private rules.\nversion: 1.0.0\n---\n\nbody")
    broken = tmp_path / "own" / "broken"
    broken.mkdir()
    (broken / "SKILL.md").write_text("no front matter")
    override = tmp_path / "own" / "qa"
    override.mkdir()
    (override / "SKILL.md").write_text("---\nname: qa\ndescription: my own QA rules, replacing the packaged ones\n---\n\nmine")
    monkeypatch.chdir(tmp_path)                      # no project here: only the environment variable counts
    monkeypatch.setenv("CAOS_HARNESS_SKILLS", str(tmp_path / "own"))
    skills = load_all()
    assert skills["my-proposals"].local and skills["qa"].local and skills["qa"].body == "mine" and "broken" not in skills
    assert not skills["coder"].local and known("my-proposals")
    assert "my-proposals" not in load_packaged() and load_packaged()["qa"].body != "mine"


def test_project_local_skills_folder_is_found(tmp_path, monkeypatch):
    from caos_harness import app
    app.init(tmp_path)
    d = tmp_path / ".harness" / "skills" / "house-rules"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: house-rules\ndescription: rules of this project only\n---\n\nbody")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAOS_HARNESS_SKILLS", raising=False)
    assert load_all()["house-rules"].local
