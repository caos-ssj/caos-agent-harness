import threading
import time

from caos_harness.engines.workstation import Run


class ScriptedModel:
    def __init__(self):
        self.messages = []

    def chat(self, messages, tools):
        self.messages = list(messages)
        if not any(m['role'] == 'tool' for m in messages):
            return {'role': 'assistant', 'content': '', 'tool_calls': [{'function': {'name': 'run_command', 'arguments': {'command': 'printf real-output'}}}]}
        return {'role': 'assistant', 'content': 'Done.'}


def wait_for(run, status):
    for _ in range(100):
        state = run.snapshot()
        if state['status'] == status:
            return state
        time.sleep(.02)
    raise AssertionError(run.snapshot())


def test_command_requires_approval_and_reports_real_output(tmp_path):
    model = ScriptedModel()
    run = Run(tmp_path, 'test', 'model', 'act', 'coder', llm=model)
    thread = threading.Thread(target=run.execute)
    thread.start()
    state = wait_for(run, 'awaiting_approval')
    assert state['steps'][0]['input'] == 'printf real-output'
    run.decide(0, True)
    thread.join(3)
    state = run.snapshot()
    assert state['status'] == 'finishing'
    assert state['steps'][0]['status'] == 'completed'
    assert state['steps'][0]['exit_code'] == 0
    assert 'real-output' in state['steps'][0]['output']
    assert any(m['role'] == 'tool' and 'real-output' in m['content'] for m in model.messages)
    assert 'Role: coder' in model.messages[0]['content']


def test_rejection_never_executes_command(tmp_path):
    marker = tmp_path / 'created'
    class Model(ScriptedModel):
        def chat(self, messages, tools):
            result = super().chat(messages, tools)
            if result.get('tool_calls'):
                result['tool_calls'][0]['function']['arguments']['command'] = f'touch {marker}'
            return result
    run = Run(tmp_path, 'test', 'model', 'act', 'auto', llm=Model())
    thread = threading.Thread(target=run.execute)
    thread.start()
    wait_for(run, 'awaiting_approval')
    run.decide(0, False)
    thread.join(3)
    assert not marker.exists()
    assert run.snapshot()['steps'][0]['status'] == 'denied'


def test_plan_never_executes_model_tool_calls(tmp_path):
    run = Run(tmp_path, 'test', 'model', 'plan', 'auto', llm=ScriptedModel())
    run.execute()
    assert run.snapshot()['status'] == 'finishing'
    assert run.snapshot()['error']
    assert run.snapshot()['steps'] == []


def _alive(pid: int) -> bool:
    import os
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:                                   # a zombie that nobody reaped still answers kill(0)
        return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _gone(pid: int, wait: float = 3.0) -> bool:
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if not _alive(pid):
            return True
        time.sleep(.05)
    return False


class SpawnModel(ScriptedModel):
    """Asks for a command that starts a background child and prints its pid before waiting."""
    def __init__(self, pidfile):
        super().__init__()
        self.cmd = f"sleep 300 & echo $! > {pidfile}; wait"

    def chat(self, messages, tools):
        result = super().chat(messages, tools)
        if result.get('tool_calls'):
            result['tool_calls'][0]['function']['arguments']['command'] = self.cmd
        return result


def _pid(pidfile) -> int:
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            return int(pidfile.read_text())
        time.sleep(.05)
    raise AssertionError("the command never started its child")


def test_a_timed_out_command_leaves_no_process_group_alive(tmp_path, monkeypatch):
    from caos_harness.engines import workstation
    monkeypatch.setattr(workstation, "COMMAND_TIMEOUT", 1)
    pidfile = tmp_path / "child.pid"
    run = Run(tmp_path, 'test', 'model', 'act', 'auto', llm=SpawnModel(pidfile))
    thread = threading.Thread(target=run.execute)
    thread.start()
    wait_for(run, 'awaiting_approval')
    run.decide(0, True)
    thread.join(15)
    assert not thread.is_alive()
    child = _pid(pidfile)
    assert _gone(child), "the background child outlived the timeout"
    step = run.snapshot()['steps'][0]
    assert step['status'] == 'failed' and 'Timed out' in step['output']


def test_cancel_stops_a_running_command_and_its_children(tmp_path):
    pidfile = tmp_path / "child.pid"
    run = Run(tmp_path, 'test', 'model', 'act', 'auto', llm=SpawnModel(pidfile))
    thread = threading.Thread(target=run.execute)
    thread.start()
    wait_for(run, 'awaiting_approval')
    run.decide(0, True)
    child = _pid(pidfile)
    t0 = time.monotonic()
    run.cancel()
    thread.join(10)
    assert not thread.is_alive() and time.monotonic() - t0 < 8
    assert _gone(child), "the background child outlived the cancel"
    state = run.snapshot()
    assert state['steps'][0]['status'] == 'failed' and 'Stopped by the operator' in state['steps'][0]['output']
    assert state['status'] == 'finishing' and 'stopped by the operator' in state['error']
    assert run._proc is None


def test_cancel_while_awaiting_approval_releases_the_gate_and_denies_the_step(tmp_path):
    marker = tmp_path / "ran"
    class Model(ScriptedModel):
        def chat(self, messages, tools):
            result = super().chat(messages, tools)
            if result.get('tool_calls'):
                result['tool_calls'][0]['function']['arguments']['command'] = f'touch {marker}'
            return result
    run = Run(tmp_path, 'test', 'model', 'act', 'auto', llm=Model())
    thread = threading.Thread(target=run.execute)
    thread.start()
    wait_for(run, 'awaiting_approval')
    run.cancel()
    thread.join(5)
    assert not thread.is_alive() and not marker.exists()
    assert run.snapshot()['steps'][0]['status'] == 'denied'
    import pytest
    with pytest.raises(ValueError):
        run.decide(0, True)
