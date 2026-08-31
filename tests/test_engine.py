import json
from pathlib import Path

import pytest

from paymentshield.engine import evaluate

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def report():
    scenario = json.loads((ROOT / "examples/payment-network/shadow-evaluation.json").read_text())
    return evaluate(scenario)


def test_evaluates_one_hundred_thousand_transactions(report):
    assert report["transactions"] == 100000
    assert report["fraud_transactions"] > 0


def test_selects_policy_inside_recall_and_latency_envelope(report):
    assert report["selected_policy"] is not None
    assert report["selected_policy"]["fraud_recall_pct"] >= 70
    assert report["selected_policy"]["modeled_p99_ms"] <= 100


def test_false_declines_are_expressed_as_volume_and_contribution(report):
    policy = report["selected_policy"]
    assert policy["false_declined_payment_volume_usd"] >= policy["contribution_lost_to_false_declines_usd"]


def test_drift_requires_review(report):
    assert report["drift"]["status"] == "review-required"
    assert not report["drift"]["auto_retrain"]


def test_degraded_mode_never_freezes_accounts(report):
    assert not report["degraded_mode"]["auto_freeze_account"]


def test_runs_in_shadow_only(report):
    assert report["production_control"]["mode"] == "shadow-only"
    assert not report["production_control"]["auto_decline"]


def test_receipt_is_deterministic():
    scenario = json.loads((ROOT / "examples/payment-network/shadow-evaluation.json").read_text())
    assert evaluate(scenario)["receipt_sha256"] == evaluate(scenario)["receipt_sha256"]


def test_invalid_threshold_fails_closed():
    scenario = json.loads((ROOT / "examples/payment-network/shadow-evaluation.json").read_text())
    scenario["candidate_thresholds"] = [1.2]
    with pytest.raises(ValueError):
        evaluate(scenario)
