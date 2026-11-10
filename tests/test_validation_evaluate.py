from caos_harness.validation.evaluate import run


def test_eval_passes_with_default_thresholds():
    res = run(seed=7)
    assert res["passed"], res["checks"]


def test_eval_is_reproducible():
    assert run(seed=7)["metrics"] == run(seed=7)["metrics"]


def test_gate_fails_when_threshold_impossible():
    res = run(seed=7, thresholds={"min_coverage": 1.01, "min_precision": 0.9})
    assert not res["passed"]
    assert not res["checks"]["coverage_on_answerable >= min"]


def test_no_record_lost_across_seeds():
    for seed in range(20):
        m = run(seed=seed)["metrics"]
        assert m["faulty_lost_records"] == 0
        assert m["faulty_silent_failures"] == 0
        assert m["faulty_max_attempts"] <= 3
