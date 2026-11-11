"""What must hold before the repository is public: no private paths or names in the source, no stored keys, no invented figures."""
import json
import re
from pathlib import Path

import pytest
from caos_harness import app
from caos_harness.web.server import Api

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [p for pat in ("caos_harness/**/*.py", "web/src/**/*.ts*", "caos_harness/skills/**/*.md", "docs/*.md", "README*.md", "tools/*.py", "*.toml", "Makefile")
           for p in ROOT.glob(pat) if "dist" not in p.parts]
PRIVATE = re.compile(r"/home/(?!usuario\b)\w+|Proyecto_caos|B[oó]veda|claude-stack|go-boveda|teo-redactor|qa-sentinel|caosssj")
PRICE = re.compile(r"\$\s?\d+[.,]\d{2}")


@pytest.fixture
def api(tmp_path):
    app.init(tmp_path)
    return Api(app.load(tmp_path / "harness.toml"))


def test_no_private_paths_or_internal_names_in_the_source():
    hits = [f"{p.relative_to(ROOT)}:{i}: {line.strip()[:90]}" for p in SOURCES for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if PRIVATE.search(line)]
    assert not hits, "\n".join(hits)


def test_no_prices_in_the_source():
    """A price is a claim with a date and a source; the harness measures seconds and tokens and shows those."""
    hits = [f"{p.relative_to(ROOT)}:{i}" for p in SOURCES for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if PRICE.search(line)]
    assert not hits, hits


def test_a_key_is_refused_and_an_old_stored_key_is_never_returned(api):
    with pytest.raises(app.ConfigError, match="keys are not stored"):
        api.save_custom_provider({"name": "Gateway", "api_key": "sk-secret-value"})
    with pytest.raises(app.ConfigError, match="environment variable name"):
        api.save_custom_provider({"name": "Gateway", "api_key_env": "sk-secret-value"})
    f = api.p.root / ".harness" / "custom_providers.json"
    f.write_text(json.dumps([{"id": "old", "name": "Old", "api_key": "sk-left-by-an-older-version"}]))
    assert "sk-left" not in json.dumps(api.providers_info())
    saved = api.save_custom_provider({"name": "Gateway", "base_url": "https://example.test/v1", "api_key_env": "GATEWAY_API_KEY", "models": ["m"]})
    assert saved["api_key_env"] == "GATEWAY_API_KEY" and "sk-left" not in f.read_text()   # saving rewrites the file without the old key


def test_providers_claim_only_what_is_wired(api):
    info = api.providers_info()
    wired = [p["id"] for p in info["providers"] if p.get("wired")]
    assert wired == ["ollama"]
    for p in info["providers"]:
        if not p.get("wired"):
            assert p["models"] == [] and p["cost_per_m"] == "not measured"
    assert info["active_failover"]["enabled"] is False and info["active_failover"]["strategy"] == "not_implemented"
    assert api.save_failover({"enabled": True, "fallback_model": "m", "strategy": "magic"}) == {"fallback_model": "m", "enabled": False, "strategy": "not_implemented"}


def test_console_only_offers_the_project_it_was_started_in(api):
    assert api.repositories() == [{"name": api.p.root.name, "path": str(api.p.root), "current": True}]


def test_quality_figures_come_from_the_report_file(api):
    q = api.state()["quality"]
    report = ROOT / "reports" / "validation" / "mutation.md"
    caught, total = map(int, re.search(r"\*\*(\d+)/(\d+)\*\*", report.read_text()).groups())
    assert q["mutation"] == {"caught": caught, "total": total, "source": "make mutation"}
