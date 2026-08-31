from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field
from starlette.responses import Response

from .engine import Transaction, _risk


DECISIONS = Counter("paymentshield_decisions_total", "Payment decision recommendations", ["recommendation"])
LATENCY = Histogram("paymentshield_decision_seconds", "Decision latency")
DUPLICATES = Counter("paymentshield_duplicates_total", "Duplicate requests suppressed")


class PaymentInput(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    account_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    beneficiary_id: str = Field(min_length=1, max_length=128)
    amount_usd: float = Field(gt=0, le=1_000_000)
    account_age_days: int = Field(ge=0, le=50000)
    velocity_10m: int = Field(ge=0, le=10000)
    device_novel: bool
    beneficiary_novel: bool
    impossible_travel: bool
    shared_risky_device: bool


def decide(payload: PaymentInput, threshold: float, step_up_band: float, policy_version: str) -> dict[str, Any]:
    started = time.perf_counter()
    transaction = Transaction(**payload.model_dump(), fraud=False)
    score = _risk(transaction)
    if score >= threshold:
        recommendation = "decline-review"
    elif score >= threshold - step_up_band:
        recommendation = "step-up"
    else:
        recommendation = "approve"
    canonical = json.dumps({"transaction_id": payload.transaction_id, "score": round(score, 6), "recommendation": recommendation, "policy_version": policy_version}, sort_keys=True, separators=(",", ":"))
    result = {
        "decision_id": str(uuid.uuid4()),
        "transaction_id": payload.transaction_id,
        "risk_score": round(score, 6),
        "recommendation": recommendation,
        "policy_version": policy_version,
        "auto_execute": False,
        "receipt_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }
    LATENCY.observe(time.perf_counter() - started)
    DECISIONS.labels(recommendation).inc()
    return result


def create_app(database_path: str | None = None) -> FastAPI:
    path = database_path or os.getenv("PAYMENTSHIELD_DB", "paymentshield.db")
    if os.getenv("PAYMENTSHIELD_ENV", "development") == "production" and path == "paymentshield.db":
        raise RuntimeError("production requires explicit durable storage")
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.execute("CREATE TABLE IF NOT EXISTS decisions (transaction_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, result TEXT NOT NULL)")
    connection.commit()
    threshold = float(os.getenv("PAYMENTSHIELD_THRESHOLD", "0.35"))
    step_up_band = float(os.getenv("PAYMENTSHIELD_STEP_UP_BAND", "0.08"))
    policy_version = os.getenv("PAYMENTSHIELD_POLICY_VERSION", "shadow-v1")
    app = FastAPI(title="PaymentShield Real-Time Decision API", version="1.0.0")

    def authorize(authorization: str | None) -> None:
        expected = os.getenv("PAYMENTSHIELD_API_TOKEN")
        if os.getenv("PAYMENTSHIELD_ENV", "development") == "production" and not expected:
            raise HTTPException(503, "decision API authentication is not configured")
        if expected and authorization != f"Bearer {expected}":
            raise HTTPException(401, "invalid bearer token")

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> dict[str, Any]:
        connection.execute("SELECT 1").fetchone()
        return {"status": "ready", "policy_version": policy_version, "mode": "recommendation-only"}

    @app.get("/metrics")
    def metrics(authorization: str | None = Header(default=None)) -> Response:
        authorize(authorization)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/decisions", status_code=202)
    def decision(payload: PaymentInput, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authorize(authorization)
        value = payload.model_dump()
        payload_hash = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        row = connection.execute("SELECT payload_hash, result FROM decisions WHERE transaction_id = ?", (payload.transaction_id,)).fetchone()
        if row:
            if row[0] != payload_hash:
                raise HTTPException(409, "transaction_id reused with different payload")
            DUPLICATES.inc()
            return {**json.loads(row[1]), "duplicate_suppressed": True}
        result = decide(payload, threshold, step_up_band, policy_version)
        connection.execute("INSERT INTO decisions VALUES (?, ?, ?)", (payload.transaction_id, payload_hash, json.dumps(result, sort_keys=True)))
        connection.commit()
        return {**result, "duplicate_suppressed": False}

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=None)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    uvicorn.run(create_app(args.database), host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
