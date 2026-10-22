import os
import hmac
import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation

import requests
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import SQLAlchemyError

app = Flask(__name__)

# Render provides DATABASE_URL. Some providers use postgres://, while SQLAlchemy
# expects postgresql://.
database_url = os.getenv("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///mr_jery_wallet.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

TRANZAK_API_URL = os.getenv(
    "TRANZAK_API_URL", "https://api.tranzak.co/api/gateway/v1"
).rstrip("/")
TRANZAK_API_KEY = os.getenv("TRANZAK_API_KEY", "").strip()
TRANZAK_WEBHOOK_SECRET = os.getenv("TRANZAK_WEBHOOK_SECRET", "").strip()
AUTH_SHARED_SECRET = os.getenv("AUTH_SHARED_SECRET", "").strip()


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(120), unique=True, nullable=False, index=True)
    transaction_id = db.Column(db.String(80), unique=True, nullable=True, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    payment_method = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="created")
    payment_url = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)


class WebhookEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_key = db.Column(db.String(180), nullable=False, unique=True)
    event_name = db.Column(db.String(80), nullable=False)
    transaction_id = db.Column(db.String(80), nullable=True)
    received_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)


with app.app_context():
    db.create_all()


def shared_secret_ok():
    """Server-to-server protection. Never put AUTH_SHARED_SECRET in a browser app."""
    supplied = request.headers.get("X-Auth-Shared-Secret", "")
    return bool(AUTH_SHARED_SECRET and supplied and
                hmac.compare_digest(supplied, AUTH_SHARED_SECRET))


@app.get("/")
def home():
    return jsonify({
        "service": "MR Jery Wallet API",
        "status": "live",
        "health": "/health",
        "webhook": "/webhooks/tranzak"
    }), 200


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.get("/health/config")
def health_config():
    # Reports only whether values exist; never returns secret values.
    return jsonify({
        "database_configured": bool(database_url),
        "tranzak_api_key_configured": bool(TRANZAK_API_KEY),
        "tranzak_webhook_secret_configured": bool(TRANZAK_WEBHOOK_SECRET),
        "auth_shared_secret_configured": bool(AUTH_SHARED_SECRET)
    }), 200


@app.post("/api/payments")
def create_payment():
    # This endpoint is intended for calls from a trusted backend, not directly
    # from a public browser/mobile client, because the shared secret is private.
    if not shared_secret_ok():
        return jsonify({"error": "unauthorized"}), 401
    if not TRANZAK_API_KEY:
        return jsonify({"error": "TRANZAK_API_KEY is not configured"}), 503

    body = request.get_json(silent=True) or {}
    try:
        amount = Decimal(str(body.get("amount", "")))
    except (InvalidOperation, ValueError):
        return jsonify({"error": "amount must be a valid number"}), 400

    currency = str(body.get("currency", "HTG")).upper()
    method = str(body.get("payment_method", "")).lower()
    customer_name = str(body.get("customer_name", "")).strip()
    if amount < Decimal("1") or amount > Decimal("100000000"):
        return jsonify({"error": "amount is outside allowed range"}), 400
    if currency not in {"HTG", "USD"}:
        return jsonify({"error": "currency must be HTG or USD"}), 400
    if method not in {"moncash", "natcash", "card"}:
        return jsonify({"error": "payment_method must be moncash, natcash, or card"}), 400
    if not customer_name:
        return jsonify({"error": "customer_name is required"}), 400

    reference = str(body.get("reference") or f"MRJ-{uuid.uuid4().hex[:20]}")[:120]
    if Payment.query.filter_by(reference=reference).first():
        return jsonify({"error": "reference already exists; use a new reference"}), 409

    payload = {
        "amount": float(amount),
        "currency": currency,
        "payment_method": method,
        "customer_name": customer_name,
        "reference": reference,
        "description": str(body.get("description", "MR Jery Wallet payment"))[:250],
        "metadata": body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    }
    for optional in ("customer_email", "customer_phone"):
        value = body.get(optional)
        if value:
            payload[optional] = str(value)[:200]

    try:
        response = requests.post(
            f"{TRANZAK_API_URL}/payments",
            headers={"X-Api-Key": TRANZAK_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=20
        )
    except requests.RequestException:
        app.logger.exception("Could not reach Tranzak API")
        return jsonify({"error": "payment provider unavailable; try again later"}), 502

    try:
        result = response.json()
    except ValueError:
        result = {}

    if response.status_code not in (200, 201):
        # Do not return credentials or full request headers to the client.
        app.logger.warning("Tranzak payment creation failed with HTTP %s", response.status_code)
        return jsonify({
            "error": "Tranzak could not create the payment",
            "provider_status": response.status_code,
            "details": result.get("message") or result.get("error") or "See server logs"
        }), 502

    payment = Payment(
        reference=reference,
        transaction_id=str(result.get("transaction_id") or "") or None,
        amount=Decimal(str(result.get("amount", amount))),
        currency=str(result.get("currency", currency)).upper(),
        payment_method=method,
        status=str(result.get("status", "processing")),
        payment_url=result.get("payment_url")
    )
    try:
        db.session.add(payment)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not save payment record")
        return jsonify({"error": "payment was created but could not be saved; contact support"}), 500

    # Return only the fields the wallet needs.
    return jsonify({
        "reference": payment.reference,
        "transaction_id": payment.transaction_id,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "status": payment.status,
        "payment_url": payment.payment_url,
        "client_secret": result.get("client_secret"),
        "publishable_key": result.get("publishable_key"),
        "payment_intent_id": result.get("payment_intent_id")
    }), 201


@app.get("/api/payments/<reference>")
def get_payment(reference):
    if not shared_secret_ok():
        return jsonify({"error": "unauthorized"}), 401
    payment = Payment.query.filter_by(reference=reference).first()
    if not payment:
        return jsonify({"error": "payment not found"}), 404
    return jsonify({
        "reference": payment.reference,
        "transaction_id": payment.transaction_id,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "payment_method": payment.payment_method,
        "status": payment.status,
        "payment_url": payment.payment_url,
        "created_at": payment.created_at.isoformat() if payment.created_at else None
    }), 200


@app.post("/webhooks/tranzak")
def tranzak_webhook():
    if not TRANZAK_WEBHOOK_SECRET:
        app.logger.error("TRANZAK_WEBHOOK_SECRET is not configured")
        return jsonify({"error": "webhook not configured"}), 503

    raw_body = request.get_data(cache=False)
    received_signature = request.headers.get("X-Tranzak-Signature", "").strip()
    expected_signature = hmac.new(
        TRANZAK_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    if not received_signature or not hmac.compare_digest(expected_signature, received_signature):
        return jsonify({"error": "invalid signature"}), 403

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return jsonify({"error": "invalid JSON"}), 400

    event_name = str(event.get("event", ""))
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    transaction_id = str(data.get("transaction_id") or "") or None

    if event_name not in {"payment.success", "payment.failed"} or not transaction_id:
        # Acknowledge valid but unrecognized event formats to avoid pointless retries.
        return jsonify({"received": True, "processed": False}), 200

    event_key = f"{event_name}:{transaction_id}"
    if WebhookEvent.query.filter_by(event_key=event_key).first():
        return jsonify({"received": True, "duplicate": True}), 200

    try:
        record = WebhookEvent(
            event_key=event_key,
            event_name=event_name,
            transaction_id=transaction_id
        )
        db.session.add(record)
        payment = Payment.query.filter_by(transaction_id=transaction_id).first()
        if payment:
            # Only a verified Tranzak webhook can change the local payment status.
            if event_name == "payment.success" and str(data.get("status", "")).lower() == "completed":
                payment.status = "completed"
            elif event_name == "payment.failed" and str(data.get("status", "")).lower() == "failed":
                payment.status = "failed"
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not save webhook event")
        return jsonify({"error": "could not store event"}), 500

    return jsonify({"received": True}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
