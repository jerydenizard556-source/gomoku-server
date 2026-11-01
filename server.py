import os
import json
import time
import hmac
import hashlib
import base64
import uuid
import re

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    UploadFile,
    File,
    Form,
    Header
)

from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials
)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field


# =====================================================
# CONFIGURATION
# =====================================================

DATABASE_URL = (
    os.getenv("GAME_DATABASE_URL")
    or os.getenv("DATABASE_URL")
)

# Optional, separate connection for the wallet database. This API only inspects
# wallet schema/counts; it does not write to or replace the wallet service.
WALLET_DATABASE_URL = os.getenv("WALLET_DATABASE_URL", "").strip()

ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME", ""
).strip()

ADMIN_EMAIL = os.getenv(
    "ADMIN_EMAIL", ""
).strip()

ADMIN_PASSWORD = os.getenv(
    "ADMIN_PASSWORD", ""
)

ADMIN_IDENTIFIERS = {
    value.lower()
    for value in [ADMIN_USERNAME, ADMIN_EMAIL]
    if value
}

ADMIN_CANONICAL = ADMIN_USERNAME or ADMIN_EMAIL

TOKEN_SECRET = (
    os.getenv("ADMIN_TOKEN_SECRET")
    or os.getenv("ADMIN_SESSION_SECRET")
    or ""
)

GAME_SECRET = (
    os.getenv("GAME_SECRET")
    or os.getenv("GAME_API_SECRET")
    or ""
)

FRONTEND_ORIGIN = os.getenv(
    "FRONTEND_ORIGIN",
    "https://mrjerygomoku.netlify.app"
).rstrip("/")

ADMIN_ORIGIN = os.getenv(
    "ADMIN_ORIGIN",
    "https://mr-jery-control-center.vercel.app"
).rstrip("/")

ALLOWED_ORIGINS = {
    FRONTEND_ORIGIN,
    ADMIN_ORIGIN,
    "https://mrjerygomoku.netlify.app",
    "https://mrjerygomoku.vercel.app",
    "https://mr-jery-control-center.vercel.app"
}


# =====================================================
# APPLICATION
# =====================================================

app = FastAPI(
    title="MR_Jery Control Center",
    description="Official MR_Jery Morpion Administration API",
    version="2.3.0"
)

# CORS ajoute en enveloppe ASGI externe tout en bas du fichier.

security = HTTPBearer(
    auto_error=False,
    scheme_name="AdminBearerAuth"
)


# =====================================================
# DATABASE
# =====================================================

def normalize_database_url(value):

    url = value.strip()

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)

    return url


def database_url():

    if not DATABASE_URL:
        raise HTTPException(
            status_code=503,
            detail="GAME_DATABASE_URL pa konfigire"
        )

    return normalize_database_url(DATABASE_URL)


@contextmanager
def get_db():

    with psycopg.connect(
        database_url(),
        row_factory=dict_row,
        connect_timeout=15
    ) as conn:

        yield conn


def init_database():

    with get_db() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_requests (

                id UUID PRIMARY KEY,

                user_id TEXT NOT NULL,

                username TEXT,

                premium_type TEXT NOT NULL,

                payment_method TEXT,

                payment_reference TEXT,

                screenshot BYTEA,

                screenshot_type TEXT,

                status TEXT DEFAULT 'pending',

                admin_note TEXT,

                created_at TIMESTAMPTZ DEFAULT NOW(),

                reviewed_at TIMESTAMPTZ
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS premium_subscriptions (

                user_id TEXT PRIMARY KEY,

                premium_type TEXT NOT NULL,

                active BOOLEAN DEFAULT TRUE,

                starts_at TIMESTAMPTZ DEFAULT NOW(),

                expires_at TIMESTAMPTZ NOT NULL
            )
        """)

        conn.commit()


@app.on_event("startup")
def startup():

    if DATABASE_URL:
        init_database()


# =====================================================
# HOME
# =====================================================

@app.get("/")
def home():

    return {
        "ok": True,
        "service": "MR_Jery Control Center",
        "version": app.version,
        "status": "running",
        "docs": "/docs"
    }


# =====================================================
# HEALTH
# =====================================================

@app.get("/health")
def health():

    db_ok = False
    db_error = None

    if DATABASE_URL:

        try:
            with get_db() as conn:
                conn.execute("SELECT 1")
                db_ok = True

        except Exception as exc:
            db_error = str(exc)[:250]

    return {
        "ok": True,
        "service": "MR_Jery Control Center",
        "database_configured": bool(DATABASE_URL),
        "database_connected": db_ok,
        "database_error": db_error,
        "admin_configured": bool(
            ADMIN_IDENTIFIERS and ADMIN_PASSWORD
        ),
        "token_configured": bool(TOKEN_SECRET),
        "game_secret_configured": bool(GAME_SECRET)
    }


# =====================================================
# AUTHENTICATION
# =====================================================

def create_token(username):

    payload = {
        "username": username,
        "role": "admin",
        "exp": int(time.time()) + 86400
    }

    encoded = base64.urlsafe_b64encode(
        json.dumps(
            payload,
            separators=(",", ":")
        ).encode()
    ).decode().rstrip("=")

    signature = hmac.new(
        TOKEN_SECRET.encode(),
        encoded.encode(),
        hashlib.sha256
    ).hexdigest()

    return encoded + "." + signature


def verify_token(token):

    try:

        encoded, signature = token.split(".", 1)

        expected = hmac.new(
            TOKEN_SECRET.encode(),
            encoded.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            signature,
            expected
        ):
            return None

        payload = json.loads(
            base64.urlsafe_b64decode(
                encoded + "=" * (-len(encoded) % 4)
            )
        )

        if int(payload.get("exp", 0)) < int(time.time()):
            return None

        if payload.get("role") != "admin":
            return None

        token_username = str(
            payload.get("username", "")
        ).strip().lower()

        if not ADMIN_CANONICAL:
            return None

        if token_username != ADMIN_CANONICAL.lower():
            return None

        return payload

    except Exception:
        return None


def require_admin(
    credentials: Optional[
        HTTPAuthorizationCredentials
    ] = Depends(security)
):

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Admin authentication required"
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication scheme"
        )

    admin = verify_token(
        credentials.credentials
    )

    if not admin:
        raise HTTPException(
            status_code=401,
            detail="Admin token invalid or expired"
        )

    return admin


# =====================================================
# ADMIN LOGIN
# =====================================================

class AdminLogin(BaseModel):

    username: Optional[str] = None
    email: Optional[str] = None
    password: str


@app.post("/admin/login", tags=["Authentication"])
@app.post("/api/admin/login", tags=["Authentication"])
def admin_login(data: AdminLogin):

    if not ADMIN_IDENTIFIERS or not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=503,
            detail="Admin account pa konfigire sou Render"
        )

    if not TOKEN_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Admin token secret pa konfigire"
        )

    login = (
        data.username or data.email or ""
    ).strip().lower()

    valid_user = login in ADMIN_IDENTIFIERS

    valid_password = hmac.compare_digest(
        data.password,
        ADMIN_PASSWORD
    )

    if not valid_user or not valid_password:
        raise HTTPException(
            status_code=401,
            detail="Admin account not found or invalid credentials"
        )

    token = create_token(ADMIN_CANONICAL)

    return {
        "ok": True,
        "success": True,
        "message": "Admin login successful",
        "access_token": token,
        "token": token,
        "token_type": "bearer",
        "expires_in": 86400,
        "admin": {
            "username": ADMIN_CANONICAL,
            "role": "admin"
        }
    }


# =====================================================
# ADMIN PROFILE
# =====================================================

@app.get("/admin/me", tags=["Admin"])
def admin_me(admin=Depends(require_admin)):

    return {
        "ok": True,
        "authenticated": True,
        "admin": admin
    }


# =====================================================
# PREMIUM REQUEST
# =====================================================

def get_player_from_account_token(account_token: Optional[str]):
    """Resolve a real game account from the hashed session token."""
    if not account_token or len(account_token) < 20:
        raise HTTPException(401, "Konekte sou kont jwèt ou an avan.")
    token_hash = hashlib.sha256(account_token.encode()).hexdigest()
    with get_db() as conn:
        player = conn.execute("""
            SELECT p.id, p.username, p.email
            FROM account_sessions s
            JOIN players p ON p.id = s.player_id
            WHERE s.token_hash = %s
            LIMIT 1
        """, (token_hash,)).fetchone()
    if not player:
        raise HTTPException(401, "Sesyon kont jwèt la pa valab. Rekonekte.")
    return player


@app.post("/premium/request", tags=["Premium"])
async def premium_request(
    premium_type: str = Form(...),
    payment_method: str = Form(""),
    payment_reference: str = Form(""),
    screenshot: UploadFile = File(...),
    x_account_token: Optional[str] = Header(None, alias="X-Account-Token")
):
    # Never trust a user_id/username supplied by the browser. Resolve identity
    # from the same hashed account session used by the Gomoku game server.
    player = get_player_from_account_token(x_account_token)
    premium_type = premium_type.strip().lower()
    if premium_type not in ["bronze", "silver", "diamond", "freestyle", "pro", "swap", "all"]:
        raise HTTPException(400, "Invalid premium type")
    if screenshot.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(400, "Invalid screenshot format")
    image_data = await screenshot.read(5 * 1024 * 1024 + 1)
    if not image_data or len(image_data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Screenshot must be under 5 MB")
    request_id = str(uuid.uuid4())
    with get_db() as conn:
        pending = conn.execute("""
            SELECT id FROM premium_requests
            WHERE user_id = %s AND status = 'pending'
            ORDER BY created_at DESC LIMIT 1
        """, (str(player["id"]),)).fetchone()
        if pending:
            raise HTTPException(409, "Ou deja gen yon demann Premium k ap tann verifikasyon.")
        conn.execute("""
            INSERT INTO premium_requests (
                id, user_id, username, premium_type, payment_method,
                payment_reference, screenshot, screenshot_type, status
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')
        """, (
            request_id, str(player["id"]), player["username"], premium_type,
            payment_method.strip(), payment_reference.strip(), image_data,
            screenshot.content_type
        ))
        conn.commit()
    return {"ok": True, "success": True, "request_id": request_id,
            "status": "pending", "username": player["username"],
            "message": "Premium request received"}


@app.get("/premium/my-status", tags=["Premium"])
def premium_my_status(
    x_account_token: Optional[str] = Header(None, alias="X-Account-Token")
):
    player = get_player_from_account_token(x_account_token)
    user_id = str(player["id"])
    now = datetime.now(timezone.utc)
    with get_db() as conn:
        sub = conn.execute("""
            SELECT premium_type, active, starts_at, expires_at
            FROM premium_subscriptions WHERE user_id = %s
        """, (user_id,)).fetchone()
        latest = conn.execute("""
            SELECT id, premium_type, status, admin_note, created_at
            FROM premium_requests WHERE user_id = %s
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,)).fetchone()
    active = bool(sub and sub["active"] and sub["expires_at"] and sub["expires_at"] > now)
    return {
        "ok": True,
        "username": player["username"],
        "premium": active,
        "premium_type": sub["premium_type"] if active else None,
        "expires_at": sub["expires_at"].isoformat() if active else None,
        "latest_request": ({
            "request_id": str(latest["id"]),
            "premium_type": latest["premium_type"],
            "status": latest["status"],
            "admin_note": latest["admin_note"] or "",
            "created_at": latest["created_at"].isoformat() if latest["created_at"] else None
        } if latest else None)
    }


# =====================================================
# ADMIN PREMIUM REQUESTS
# =====================================================

@app.get(
    "/admin/premium-requests",
    tags=["Premium Admin"]
)
def premium_requests(

    status: str = "pending",

    limit: int = 50,

    admin=Depends(require_admin)

):

    if status not in [
        "pending",
        "approved",
        "rejected",
        "all"
    ]:
        raise HTTPException(
            400,
            "Invalid status"
        )

    limit = max(1, min(limit, 100))

    with get_db() as conn:

        if status == "all":

            rows = conn.execute("""
                SELECT
                    id,
                    user_id,
                    username,
                    premium_type,
                    payment_method,
                    payment_reference,
                    screenshot_type,
                    status,
                    admin_note,
                    created_at,
                    reviewed_at
                FROM premium_requests
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,)).fetchall()

        else:

            rows = conn.execute("""
                SELECT
                    id,
                    user_id,
                    username,
                    premium_type,
                    payment_method,
                    payment_reference,
                    screenshot_type,
                    status,
                    admin_note,
                    created_at,
                    reviewed_at
                FROM premium_requests
                WHERE status = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (status, limit)).fetchall()

    requests = []

    for row in rows:

        item = dict(row)
        item["id"] = str(item["id"])

        for key in [
            "created_at",
            "reviewed_at"
        ]:
            if item.get(key):
                item[key] = item[key].isoformat()

        requests.append(item)

    return {
        "ok": True,
        "count": len(requests),
        "requests": requests
    }


# =====================================================
# VIEW SCREENSHOT
# =====================================================

@app.get(
    "/admin/premium-requests/{request_id}/screenshot",
    tags=["Premium Admin"]
)
def premium_screenshot(

    request_id: str,

    admin=Depends(require_admin)

):

    try:
        parsed_id = uuid.UUID(request_id)

    except ValueError:
        raise HTTPException(
            400,
            "Invalid request ID"
        )

    with get_db() as conn:

        row = conn.execute("""
            SELECT screenshot, screenshot_type
            FROM premium_requests
            WHERE id = %s
        """, (parsed_id,)).fetchone()

    if not row or not row["screenshot"]:
        raise HTTPException(
            404,
            "Screenshot not found"
        )

    return Response(
        content=bytes(row["screenshot"]),
        media_type=(
            row["screenshot_type"]
            or "application/octet-stream"
        ),
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff"
        }
    )


# =====================================================
# APPROVE / REJECT PREMIUM
# =====================================================

class PremiumReview(BaseModel):

    decision: Optional[str] = None

    action: Optional[str] = None

    admin_note: str = Field(
        default="",
        max_length=1000
    )


@app.post(
    "/admin/premium-requests/{request_id}/review",
    tags=["Premium Admin"]
)
def review_premium(

    request_id: str,

    data: PremiumReview,

    admin=Depends(require_admin)

):

    decision = (
        data.decision or data.action or ""
    ).strip().lower()

    if decision not in [
        "approve",
        "reject"
    ]:
        raise HTTPException(
            400,
            "Invalid decision"
        )

    try:
        parsed_id = uuid.UUID(request_id)

    except ValueError:
        raise HTTPException(
            400,
            "Invalid request ID"
        )

    with get_db() as conn:

        row = conn.execute("""
            SELECT *
            FROM premium_requests
            WHERE id = %s
            FOR UPDATE
        """, (parsed_id,)).fetchone()

        if not row:
            raise HTTPException(
                404,
                "Premium request not found"
            )

        if row["status"] != "pending":
            raise HTTPException(
                409,
                "Request already processed"
            )

        new_status = (
            "approved"
            if decision == "approve"
            else "rejected"
        )

        if decision == "approve":

            expires = (
                datetime.now(timezone.utc)
                + timedelta(days=30)
            )

            conn.execute("""
                INSERT INTO premium_subscriptions (
                    user_id,
                    premium_type,
                    active,
                    starts_at,
                    expires_at
                )
                VALUES (
                    %s,%s,TRUE,NOW(),%s
                )
                ON CONFLICT (user_id)
                DO UPDATE SET
                    premium_type = EXCLUDED.premium_type,
                    active = TRUE,
                    starts_at = NOW(),
                    expires_at = EXCLUDED.expires_at
            """, (
                row["user_id"],
                row["premium_type"],
                expires
            ))

        conn.execute("""
            UPDATE premium_requests
            SET
                status = %s,
                admin_note = %s,
                reviewed_at = NOW()
            WHERE id = %s
        """, (
            new_status,
            data.admin_note.strip(),
            parsed_id
        ))

        conn.commit()

    return {
        "ok": True,
        "success": True,
        "request_id": str(parsed_id),
        "status": new_status,
        "message": (
            "Premium activated for 30 days"
            if decision == "approve"
            else "Premium request rejected"
        )
    }


# =====================================================
# PREMIUM STATUS FOR GAME SERVER
# =====================================================

@app.get(
    "/premium/status/{user_id}",
    tags=["Premium"]
)
def premium_status(

    user_id: str,

    x_game_secret: Optional[str] = Header(
        None,
        alias="X-Game-Secret"
    )

):

    if not GAME_SECRET:
        raise HTTPException(
            503,
            "Game secret not configured"
        )

    if not x_game_secret or not hmac.compare_digest(
        x_game_secret,
        GAME_SECRET
    ):
        raise HTTPException(
            403,
            "Unauthorized game server"
        )

    with get_db() as conn:

        row = conn.execute("""
            SELECT
                premium_type,
                active,
                expires_at
            FROM premium_subscriptions
            WHERE user_id = %s
        """, (user_id,)).fetchone()

    if not row:
        return {
            "ok": True,
            "premium": False,
            "user_id": user_id
        }

    active = (
        row["active"]
        and row["expires_at"] > datetime.now(timezone.utc)
    )

    return {
        "ok": True,
        "premium": active,
        "user_id": user_id,
        "premium_type": (
            row["premium_type"] if active else None
        ),
        "expires_at": (
            row["expires_at"].isoformat()
            if active else None
        )
    }


# =====================================================
# ADMIN OVERVIEW
# =====================================================

@app.get(
    "/admin/overview",
    tags=["Admin"]
)
def admin_overview(
    admin=Depends(require_admin)
):

    with get_db() as conn:

        result = conn.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE status = 'pending'
                ) AS pending,
                COUNT(*) FILTER (
                    WHERE status = 'approved'
                ) AS approved,
                COUNT(*) FILTER (
                    WHERE status = 'rejected'
                ) AS rejected
            FROM premium_requests
        """).fetchone()

        subscriptions = conn.execute("""
            SELECT COUNT(*) AS total
            FROM premium_subscriptions
            WHERE active = TRUE
            AND expires_at > NOW()
        """).fetchone()

    return {
        "ok": True,
        "players": None,
        "matches": None,
        "transactions": None,
        "premium_requests": result["total"],
        "pending": result["pending"],
        "approved": result["approved"],
        "rejected": result["rejected"],
        "active_subscriptions": subscriptions["total"]
    }


# =====================================================
# DATABASE SCHEMA DETECTION
# =====================================================

def table_columns(conn, table_name):

    return conn.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
        AND table_name = %s
    """, (table_name,)).fetchall()


# =====================================================
# ADMIN PLAYERS
# =====================================================

@app.get(
    "/admin/players",
    tags=["Admin"]
)
def admin_players(
    admin=Depends(require_admin)
):

    candidate_tables = [
        "users",
        "players",
        "game_users",
        "player_accounts"
    ]

    with get_db() as conn:

        for table in candidate_tables:

            cols = {
                row["column_name"]
                for row in table_columns(conn, table)
            }

            if not cols:
                continue

            id_col = next(
                (
                    x for x in [
                        "id",
                        "user_id",
                        "uid"
                    ] if x in cols
                ),
                None
            )

            name_col = next(
                (
                    x for x in [
                        "username",
                        "pseudo",
                        "name"
                    ] if x in cols
                ),
                None
            )

            email_col = (
                "email" if "email" in cols else None
            )

            wins_col = next(
                (
                    x for x in [
                        "wins",
                        "victories",
                        "total_wins"
                    ] if x in cols
                ),
                None
            )

            points_col = next(
                (
                    x for x in [
                        "points",
                        "score",
                        "rating",
                        "elo"
                    ] if x in cols
                ),
                None
            )

            if not id_col and not name_col:
                continue

            selections = []

            fields = [
                (id_col, "id"),
                (name_col, "username"),
                (email_col, "email"),
                (wins_col, "wins"),
                (points_col, "points")
            ]

            for source, alias in fields:

                if source:
                    selections.append(
                        f'"{source}" AS "{alias}"'
                    )

                else:
                    selections.append(
                        f'NULL AS "{alias}"'
                    )

            rows = conn.execute(
                f'''
                SELECT {", ".join(selections)}
                FROM "{table}"
                LIMIT 500
                '''
            ).fetchall()

            return {
                "ok": True,
                "source_table": table,
                "count": len(rows),
                "players": [
                    dict(row) for row in rows
                ]
            }

    return {
        "ok": True,
        "count": 0,
        "players": [],
        "message": "Aucune table joueurs reconnue dans cette base."
    }


# =====================================================
# ADMIN WALLET SUMMARY
# =====================================================

@app.get(
    "/admin/wallet-summary",
    tags=["Admin"]
)
def admin_wallet_summary(
    admin=Depends(require_admin)
):
    """Read-only wallet schema summary from its own database connection."""

    if not WALLET_DATABASE_URL:
        return {
            "ok": True,
            "available": False,
            "database_configured": False,
            "message": "WALLET_DATABASE_URL pa konfigire. Bous la rete nan baz done apa li.",
            "tables": {}
        }

    found = {}

    try:
        with psycopg.connect(
            normalize_database_url(WALLET_DATABASE_URL),
            row_factory=dict_row,
            connect_timeout=10,
            options="-c default_transaction_read_only=on"
        ) as conn:
            for table in [
                "wallet_accounts",
                "wallet_transactions",
                "wallets",
                "transactions",
                "wallet_webhook_events"
            ]:
                columns = conn.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = %s
                    ORDER BY ordinal_position
                """, (table,)).fetchall()

                if not columns:
                    continue

                # Table names come only from the fixed allow-list above.
                count = conn.execute(
                    f'SELECT COUNT(*) AS total FROM "{table}"'
                ).fetchone()["total"]

                found[table] = {
                    "rows": count,
                    "columns": [row["column_name"] for row in columns]
                }

        return {
            "ok": True,
            "available": bool(found),
            "database_configured": True,
            "database_connected": True,
            "tables": found,
            "read_only": True,
            "message": (
                "Baze done Wallet apa konekte; rezime a se lekti sèlman."
                if found else
                "Koneksyon Wallet la mache, men pa gen tab Wallet rekonèt."
            )
        }

    except Exception as exc:
        # Avoid returning connection strings or credentials to the browser.
        return {
            "ok": False,
            "available": False,
            "database_configured": True,
            "database_connected": False,
            "tables": {},
            "message": "Koneksyon ak baz done Wallet la echwe. Verifye WALLET_DATABASE_URL ak dwa SELECT yo."
        }



# =====================================================
# ADMIN PREMIUM SUBSCRIPTIONS
# =====================================================

@app.get(
    "/admin/premium-subscriptions",
    tags=["Premium Admin"]
)
def premium_subscriptions(
    admin=Depends(require_admin)
):

    with get_db() as conn:

        rows = conn.execute("""
            SELECT
                user_id,
                premium_type,
                active,
                starts_at,
                expires_at
            FROM premium_subscriptions
            ORDER BY starts_at DESC
            LIMIT 200
        """).fetchall()

    subscriptions = []

    for row in rows:

        item = dict(row)

        for key in [
            "starts_at",
            "expires_at"
        ]:

            if item.get(key):
                item[key] = item[key].isoformat()

        subscriptions.append(item)

    return {
        "ok": True,
        "count": len(subscriptions),
        "subscriptions": subscriptions
    }


# =====================================================
# END
# =====================================================

# =====================================================
# GLOBAL CORS WRAPPER (MUST STAY AT THE VERY END)
# =====================================================
# The player website is deployed on changing Vercel preview URLs. The premium
# submission endpoint is public and carries no cookies. Admin endpoints remain
# protected by the Bearer token checked by require_admin(). A wildcard origin
# is therefore appropriate here; credentials remain disabled. Wrapping the
# whole FastAPI app also adds CORS headers to unhandled error responses.
fastapi_app = app
app = CORSMiddleware(
    app=fastapi_app,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
    max_age=600,
)
