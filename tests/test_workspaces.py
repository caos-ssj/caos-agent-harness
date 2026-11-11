"""Switching between project folders: only folders the operator listed, only a real harness.toml, never during a run."""
import pytest
from caos_harness import app, workspaces
from caos_harness.web.server import Api


@pytest.fixture
def two(tmp_path, monkeypatch):
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / "home"))
    a, b = tmp_path / "alpha", tmp_path / "beta"
    for d in (a, b):
        d.mkdir()
        app.init(d)
    return Api(app.load(a / "harness.toml")), a, b


def test_a_folder_is_added_listed_switched_to_and_forgotten(two):
    api, a, b = two
    assert [w["name"] for w in api.workspaces()["items"]] == ["alpha"]
    out = api.workspace_add({"path": str(b)})
    assert [w["name"] for w in out["items"]] == ["alpha", "beta"] and out["current"] == str(a.resolve())
    api.p.board.add("in alpha", queue="echo")
    out = api.workspace_switch({"path": str(b)})
    assert out["current"] == str(b.resolve()) and api.state()["project"] == "beta" and api.state()["stats"]["tasks"] == 0   # beta has its own board
    api.workspace_switch({"path": str(a)})
    assert api.state()["stats"]["tasks"] == 1
    api.workspace_remove({"path": str(b)})
    assert [w["name"] for w in api.workspaces()["items"]] == ["alpha"]


def test_only_listed_real_folders_with_a_project_file_are_accepted(two, tmp_path):
    api, a, b = two
    with pytest.raises(app.ConfigError, match="not in the list"):
        api.workspace_switch({"path": str(b)})                      # beta exists but was never added
    with pytest.raises(app.ConfigError, match="absolute"):
        api.workspace_add({"path": "relative/dir"})
    with pytest.raises(app.ConfigError, match="not a folder"):
        api.workspace_add({"path": str(tmp_path / "missing")})
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(app.ConfigError, match="no harness.toml"):
        api.workspace_add({"path": str(empty)})
    out = api.workspace_add({"path": str(empty), "initialize": True})   # the operator asked for it
    assert (empty / "harness.toml").is_file() and any(w["name"] == "empty" for w in out["items"])
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "harness.toml").write_text("[agents.x]\ncommand = 'cat'\n")
    with pytest.raises(app.ConfigError, match="non-empty list"):
        api.workspace_add({"path": str(bad)})


def test_switching_waits_for_a_run_turns_commands_off_and_keeps_the_current_one(two):
    api, a, b = two
    api.workspace_add({"path": str(b)})
    api.commands_on.add("sess-1")
    api.running.acquire()
    with pytest.raises(app.ConfigError, match="running"):
        api.workspace_switch({"path": str(b)})
    api.running.release()
    api.workspace_switch({"path": str(b)})
    assert api.commands_on == set()                                  # shell commands start off again in the new folder
    with pytest.raises(app.ConfigError, match="in use"):
        api.workspace_remove({"path": str(b)})


def test_the_list_holds_paths_only(two):
    api, a, b = two
    api.workspace_add({"path": str(b)})
    assert (workspaces.home() / "workspaces.json").read_text().count("alpha") == 0
    assert str(b.resolve()) in (workspaces.home() / "workspaces.json").read_text()
