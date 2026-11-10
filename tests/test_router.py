import json

from caos_harness.router.route import Profile, choose, load_profiles, load_tiers


def P(system, lo, cov=0.9, cost=1000.0, n=50, p95=2.0):
    return Profile(system, "2026-01-01", n, min(1.0, lo + 0.08), lo, cov, cost / 1000, p95, cost, None)


def test_picks_the_cheapest_system_that_qualifies_not_the_best():
    d = choose([P("small", 0.80, cost=1400), P("big", 0.92, cost=2900)], 0.75)
    assert d.action == "route" and d.system == "small"


def test_a_cheap_system_below_the_bar_is_skipped_with_its_reason():
    d = choose([P("small", 0.80, cost=1400), P("big", 0.92, cost=2900)], 0.90)
    assert d.system == "big" and d.rejected == (("small", "precision lower bound 0.8 < 0.9"),)


def test_nothing_qualifies_goes_to_a_person_never_to_the_best_available():
    d = choose([P("small", 0.80), P("big", 0.92)], 0.95)
    assert d.action == "human_review" and d.system is None and len(d.rejected) == 2


def test_uses_the_interval_lower_bound_not_the_point_estimate():
    lucky = Profile("lucky", "2026-01-01", 5, 1.0, 0.57, 1.0, 1.0, 1.0, 500.0, None)  # 5/5 right: precision 1.0, but a wide interval
    assert choose([lucky], 0.90).action == "human_review"


def test_a_system_that_answers_nothing_or_too_little_never_qualifies():
    silent = Profile("silent", "2026-01-01", 0, 0.0, 0.0, 0.0, 1.0, 1.0, 100.0, None)
    d = choose([silent, P("shy", 0.99, cov=0.2, cost=200)], 0.0)
    assert d.action == "human_review" and dict(d.rejected) == {"silent": "answered nothing", "shy": "coverage 0.2 < 0.5"}


def test_latency_limit_and_tie_break():
    assert choose([P("slow", 0.95, p95=9.0)], 0.9, max_p95_s=5.0).action == "human_review"
    assert choose([P("b", 0.95, cov=0.8), P("a", 0.95, cov=0.9)], 0.9).system == "a"   # same cost: more coverage wins


def row(lo, p50=1.0, extra=None):
    return {"answered": 60, "precision": 0.95, "precision_ci95": [lo, 0.99], "coverage": 0.9, "latency_p50_s": p50, "latency_p95_s": 2.0, **(extra or {})}


def test_load_profiles_keeps_the_latest_measurement_and_the_right_split(tmp_path):
    (tmp_path / "benchmark-2026-11-04-m.json").write_text(json.dumps({"m|all": row(0.80), "m|test": row(0.10)}))
    (tmp_path / "benchmark-2026-11-10-m.json").write_text(json.dumps({"m|all": row(0.85, extra={"seconds_per_1000": 1234.5, "tokens_in_per_1000": 900, "tokens_out_per_1000": 100})}))
    (tmp_path / "baseline.json").write_text("{}")
    [p] = load_profiles(tmp_path)
    assert (p.system, p.measured, p.precision_lo, p.cost, p.tokens_per_1000) == ("m", "2026-11-10", 0.85, 1234.5, 1000)


def test_cost_falls_back_to_p50_for_reports_without_measured_seconds(tmp_path):
    (tmp_path / "benchmark-2026-11-04-m.json").write_text(json.dumps({"m|all": row(0.80, p50=1.41)}))
    assert load_profiles(tmp_path)[0].cost == 1410.0


def test_repo_tiers_are_ordered_and_the_real_reports_route():
    tiers = load_tiers()
    assert list(tiers.values()) == sorted(tiers.values()) and "_" not in tiers
    profiles = load_profiles()
    assert profiles and choose(profiles, tiers["low"]).action == "route"
    assert choose(profiles, 1.0).action == "human_review"
