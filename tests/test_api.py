from fastapi.testclient import TestClient

from paymentshield.api import create_app


def payment(transaction_id: str = "txn-1") -> dict:
    return {
        "transaction_id": transaction_id,
        "account_id": "account-1",
        "device_id": "device-1",
        "beneficiary_id": "beneficiary-1",
        "amount_usd": 250,
        "account_age_days": 400,
        "velocity_10m": 2,
        "device_novel": False,
        "beneficiary_novel": False,
        "impossible_travel": False,
        "shared_risky_device": False
    }


def test_health_and_recommendation_mode(tmp_path):
    with TestClient(create_app(str(tmp_path / "decisions.db"))) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").json()["mode"] == "recommendation-only"


def test_decision_never_auto_executes(tmp_path):
    with TestClient(create_app(str(tmp_path / "decisions.db"))) as client:
        result = client.post("/v1/decisions", json=payment()).json()
        assert result["recommendation"] == "approve"
        assert not result["auto_execute"]
        assert len(result["receipt_sha256"]) == 64


def test_duplicate_is_suppressed(tmp_path):
    with TestClient(create_app(str(tmp_path / "decisions.db"))) as client:
        first = client.post("/v1/decisions", json=payment()).json()
        second = client.post("/v1/decisions", json=payment()).json()
        assert first["decision_id"] == second["decision_id"]
        assert second["duplicate_suppressed"]


def test_idempotency_key_payload_conflict_fails(tmp_path):
    with TestClient(create_app(str(tmp_path / "decisions.db"))) as client:
        client.post("/v1/decisions", json=payment())
        changed = payment()
        changed["amount_usd"] = 999
        assert client.post("/v1/decisions", json=changed).status_code == 409


def test_production_fails_closed_without_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("PAYMENTSHIELD_ENV", "production")
    monkeypatch.delenv("PAYMENTSHIELD_API_TOKEN", raising=False)
    with TestClient(create_app(str(tmp_path / "decisions.db"))) as client:
        assert client.post("/v1/decisions", json=payment()).status_code == 503
