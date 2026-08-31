from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    account_id: str
    device_id: str
    beneficiary_id: str
    amount_usd: float
    account_age_days: int
    velocity_10m: int
    device_novel: bool
    beneficiary_novel: bool
    impossible_travel: bool
    shared_risky_device: bool
    fraud: bool


def evaluate(config: dict[str, Any]) -> dict[str, Any]:
    _validate(config)
    transactions = _generate(config)
    candidates = [_score_threshold(transactions, threshold, config) for threshold in config["candidate_thresholds"]]
    eligible = [item for item in candidates if item["fraud_recall_pct"] >= config["constraints"]["min_recall_pct"] and item["modeled_p99_ms"] <= config["constraints"]["max_p99_ms"]]
    selected = max(eligible, key=lambda item: item["modeled_net_contribution_usd"]) if eligible else None
    drift = _drift(config)
    report: dict[str, Any] = {
        "schema_version": "paymentshield/v1",
        "scenario": config["scenario"],
        "evidence_level": "deterministic-synthetic-shadow-evaluation",
        "transactions": len(transactions),
        "fraud_transactions": sum(item.fraud for item in transactions),
        "threshold_candidates": candidates,
        "selected_policy": selected,
        "drift": drift,
        "degraded_mode": {
            "feature_store_unavailable": "deterministic rules plus step-up authentication",
            "model_unavailable": "rules remain active; high-risk or feature-incomplete transactions step up",
            "auto_freeze_account": False,
        },
        "production_control": {
            "mode": "shadow-only",
            "auto_decline": False,
            "required_gates": ["calibration", "fairness review", "fraud operations approval", "model risk approval", "canary", "rollback drill"],
        },
        "claim_boundary": [
            "No bank, card network, payment processor, customer identity or production transaction was accessed",
            "Transactions, labels, latency, fraud loss, approval value and operating cost are synthetic",
            "Adapter and payment-network terms describe target contracts, not certification",
            "Modeled recovered sales are not profit; contribution is calculated separately",
        ],
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"))
    report["receipt_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return report


def _generate(config: dict[str, Any]) -> list[Transaction]:
    rng = random.Random(config["seed"])
    result = []
    for index in range(config["transaction_count"]):
        fraud = rng.random() < config["fraud_rate"]
        mule_ring = fraud and index % 3 == 0
        result.append(Transaction(
            transaction_id=f"txn-{index:07d}",
            account_id=f"acct-{index % config['account_count']:05d}",
            device_id=f"device-{index % 7000 if not mule_ring else index % 17:05d}",
            beneficiary_id=f"beneficiary-{index % 9000 if not mule_ring else index % 11:05d}",
            amount_usd=round(rng.lognormvariate(3.7 if not fraud else 4.8, 0.7), 2),
            account_age_days=rng.randint(1, 2500) if not fraud else rng.randint(0, 90),
            velocity_10m=rng.randint(1, 4) if not fraud else rng.randint(3, 15),
            device_novel=rng.random() < (0.08 if not fraud else 0.7),
            beneficiary_novel=rng.random() < (0.12 if not fraud else 0.75),
            impossible_travel=rng.random() < (0.002 if not fraud else 0.25),
            shared_risky_device=mule_ring,
            fraud=fraud,
        ))
    return result


def _risk(item: Transaction) -> float:
    score = 0.0
    score += min(item.velocity_10m / 15, 1) * 0.22
    score += item.device_novel * 0.16
    score += item.beneficiary_novel * 0.14
    score += item.impossible_travel * 0.24
    score += item.shared_risky_device * 0.2
    score += (item.account_age_days < 30) * 0.08
    score += min(item.amount_usd / 1000, 1) * 0.08
    return min(score, 1.0)


def _score_threshold(items: list[Transaction], threshold: float, config: dict[str, Any]) -> dict[str, Any]:
    scores = [_risk(item) for item in items]
    predicted = [score >= threshold for score in scores]
    tp = sum(pred and item.fraud for pred, item in zip(predicted, items))
    fp = sum(pred and not item.fraud for pred, item in zip(predicted, items))
    fn = sum(not pred and item.fraud for pred, item in zip(predicted, items))
    tn = sum(not pred and not item.fraud for pred, item in zip(predicted, items))
    fraud_loss = sum(item.amount_usd for pred, item in zip(predicted, items) if not pred and item.fraud)
    false_declined_volume = sum(item.amount_usd for pred, item in zip(predicted, items) if pred and not item.fraud)
    contribution_lost = false_declined_volume * config["gross_contribution_pct"]
    review_cost = sum(threshold - config["step_up_band"] <= score < threshold for score in scores) * config["step_up_cost_usd"]
    infrastructure = len(items) * config["cost_per_decision_usd"]
    approved_contribution = sum(item.amount_usd * config["gross_contribution_pct"] for pred, item in zip(predicted, items) if not pred and not item.fraud)
    net = approved_contribution - fraud_loss - review_cost - infrastructure
    return {
        "threshold": threshold,
        "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
        "fraud_recall_pct": round(tp / (tp + fn) * 100, 2) if tp + fn else 0,
        "precision_pct": round(tp / (tp + fp) * 100, 2) if tp + fp else 0,
        "false_positive_pct": round(fp / (fp + tn) * 100, 2),
        "approval_rate_pct": round((tn + fn) / len(items) * 100, 2),
        "fraud_loss_usd": round(fraud_loss, 2),
        "false_declined_payment_volume_usd": round(false_declined_volume, 2),
        "contribution_lost_to_false_declines_usd": round(contribution_lost, 2),
        "step_up_and_review_cost_usd": round(review_cost, 2),
        "decision_infrastructure_cost_usd": round(infrastructure, 2),
        "modeled_net_contribution_usd": round(net, 2),
        "modeled_p99_ms": round(8 + len(items) / 100000, 2),
    }


def _drift(config: dict[str, Any]) -> dict[str, Any]:
    baseline = config["baseline_feature_distribution"]
    current = config["current_feature_distribution"]
    psi = sum((current[key] - baseline[key]) * __import__("math").log(current[key] / baseline[key]) for key in baseline)
    return {"population_stability_index": round(psi, 4), "status": "review-required" if psi >= 0.2 else "within-envelope", "auto_retrain": False}


def _validate(config: dict[str, Any]) -> None:
    required = {"scenario", "seed", "transaction_count", "account_count", "fraud_rate", "candidate_thresholds", "constraints", "gross_contribution_pct", "step_up_band", "step_up_cost_usd", "cost_per_decision_usd", "baseline_feature_distribution", "current_feature_distribution"}
    missing = sorted(required - config.keys())
    if missing:
        raise ValueError(f"missing keys: {', '.join(missing)}")
    if config["transaction_count"] < 1000 or not 0 < config["fraud_rate"] < 0.5:
        raise ValueError("transaction count or fraud rate outside evaluation bounds")
    if any(not 0 < threshold < 1 for threshold in config["candidate_thresholds"]):
        raise ValueError("thresholds must be between zero and one")
