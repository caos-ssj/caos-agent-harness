"""Model router by cost of error, driven by measured results instead of by model names.

The question it answers: *given what a wrong answer costs here, which is the cheapest system I have measured that is good enough,
and if none is, say so and send the task to a person.*

  * "Good enough" uses the **lower bound of the 95 % interval** of precision, not the point estimate: a system measured on few
    cases has a wide interval and does not qualify for the expensive-error tiers just because it happened to score well.
  * "Cheapest" is measured compute: seconds per 1,000 records on this machine (falls back to p50 latency for older reports).
  * No system qualifies -> `human_review`. The router never picks "the best available" for a tier it cannot meet.

    python -m caos_harness.router.route            # table for every tier in router.json
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATE_RE = re.compile(r"benchmark-(\d{4}-\d{2}-\d{2})-")


@dataclass(frozen=True)
class Profile:
    system: str
    measured: str            # date of the benchmark the numbers come from
    n_answered: int
    precision: float
    precision_lo: float      # lower bound of the Wilson 95 % interval
    coverage: float
    p50_s: float
    p95_s: float
    seconds_per_1000: float | None = None
    tokens_per_1000: int | None = None

    @property
    def cost(self) -> float:
        return self.seconds_per_1000 if self.seconds_per_1000 is not None else self.p50_s * 1000


@dataclass(frozen=True)
class Decision:
    action: str              # "route" | "human_review"
    system: str | None
    reason: str
    rejected: tuple = ()     # (system, why) for every system that did not qualify


def load_profiles(reports: Path | None = None, split: str = "all") -> list[Profile]:
    """Latest measurement of each system on the given split."""
    reports = reports or ROOT / "reports" / "validation"
    latest: dict[str, Profile] = {}
    for f in sorted(reports.glob("benchmark-*.json")):
        m = DATE_RE.search(f.name)
        if not m:
            continue
        for key, v in json.loads(f.read_text(encoding="utf-8")).items():
            system, _, sp = key.partition("|")
            if sp != split:
                continue
            tin, tout = v.get("tokens_in_per_1000"), v.get("tokens_out_per_1000")
            p = Profile(system, m.group(1), v["answered"], v["precision"], v["precision_ci95"][0], v["coverage"], v["latency_p50_s"], v["latency_p95_s"],
                        v.get("seconds_per_1000"), (tin + tout) if tin is not None and tout is not None else None)
            if system not in latest or p.measured >= latest[system].measured:
                latest[system] = p
    return sorted(latest.values(), key=lambda p: p.system)


def load_tiers(path: Path | None = None) -> dict[str, float]:
    data = json.loads((path or ROOT / "router.json").read_text(encoding="utf-8"))
    return {k: float(v) for k, v in data.items() if not k.startswith("_")}


def choose(profiles: list[Profile], min_precision_lo: float, min_coverage: float = 0.5, max_p95_s: float | None = None) -> Decision:
    ok, rejected = [], []
    for p in profiles:
        if p.n_answered == 0:
            rejected.append((p.system, "answered nothing"))
        elif p.precision_lo < min_precision_lo:
            rejected.append((p.system, f"precision lower bound {p.precision_lo} < {min_precision_lo}"))
        elif p.coverage < min_coverage:
            rejected.append((p.system, f"coverage {p.coverage} < {min_coverage}"))
        elif max_p95_s is not None and p.p95_s > max_p95_s:
            rejected.append((p.system, f"p95 {p.p95_s}s > {max_p95_s}s"))
        else:
            ok.append(p)
    if not ok:
        return Decision("human_review", None, f"no measured system reaches a precision lower bound of {min_precision_lo}", tuple(rejected))
    best = min(ok, key=lambda p: (p.cost, -p.coverage, p.system))
    return Decision("route", best.system, f"cheapest of {len(ok)} that qualify (precision lower bound {best.precision_lo}, coverage {best.coverage})", tuple(rejected))


def main() -> int:
    profiles, tiers = load_profiles(), load_tiers()
    print("| System | Measured | Precision (lower bound) | Coverage | Seconds per 1,000 | Tokens per 1,000 |\n|---|---|---|---|---|---|")
    for p in profiles:
        print(f"| `{p.system}` | {p.measured} | {p.precision} ({p.precision_lo}) | {p.coverage} | {round(p.cost)} | {p.tokens_per_1000 if p.tokens_per_1000 is not None else '—'} |")
    print("\n| Cost of an error | Needs precision lower bound | Decision |\n|---|---|---|")
    for tier, need in tiers.items():
        d = choose(profiles, need)
        print(f"| {tier} | ≥ {need} | {'`' + d.system + '`' if d.system else 'human review'} — {d.reason} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
