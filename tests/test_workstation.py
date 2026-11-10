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
