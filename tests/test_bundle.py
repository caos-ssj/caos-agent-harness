"""What a `pip install` must carry: the demo, the router and the skills run outside a checkout."""
from pathlib import Path

import caos_harness

PKG = Path(caos_harness.__file__).parent


def test_bundled_files_live_inside_the_package():
    for rel in ("data/golden.jsonl", "thresholds.json", "router.json", "skills/coder/SKILL.md"):
        assert (PKG / rel).is_file(), rel
    assert list((PKG / "measured").glob("benchmark-*.json"))
