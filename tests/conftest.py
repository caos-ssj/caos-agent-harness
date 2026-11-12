import pytest


@pytest.fixture(autouse=True)
def _isolated_caos_home(tmp_path, monkeypatch):
    """Keeps every unit test isolated from real user configuration and telemetry."""
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / ".caos-home"))
