from app import config

def test_weights_sum_to_one():
    assert abs(sum(config.WEIGHTS.values()) - 1.0) < 1e-9
    assert set(config.WEIGHTS) == {"domain", "name", "address"}

def test_thresholds_present():
    assert config.THRESHOLDS[3] == 0.82
    assert config.THRESHOLDS[2] == 0.90
