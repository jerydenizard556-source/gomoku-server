"""
MR Jery Gomoku — tournament extension (safe integration module)

This is an ADD-ON for the existing Python WebSocket server, not a replacement
for that server or for the Wallet API. It adds persistent tournament records,
payment-review state, prize/commission calculations, tournament chat, and
spectator microphone approval.

Important payment boundary:
- This module NEVER marks a Tranzak payment as paid based on a browser message.
- Tranzak must be confirmed by a signed Wallet API webhook/callback.
- MonCash/NatCash proof stays pending until an admin verifies it.
- A seat is confirmed only after mark_payment_verified() is called by a trusted
  server-side payment verification path.
- The module intentionally does not invent Tranzak/MonCash/NatCash API URLs.

Integration:
1. Add the SQL table creation in init_tournament_schema() at server startup.
2. Import the functions below into the existing WebSocket server.
3. Route the documented JSON event types in your existing handler.
4. Call mark_payment_verified() only from trusted server-side payment/admin
   verification code, never directly from an untrusted client event.
5. Enforce tournament board_size and duration_seconds in the existing game
   room/move/timer engine. This module returns those settings; it does not
   rewrite your existing room engine.

Environment:
TOURNAMENT_MIN_ENTRY_FEE=1
TOURNAMENT_MAX_ENTRY_FEE=1000
TOURNAMENT_MIN_COMMISSION_PERCENT=0
TOURNAMENT_MAX_COMMISSION_PERCENT=20
TOURNAMENT_ADMIN_SECRET=<long random secret>
DATABASE_URL=<PostgreSQL URL>

Dependencies: psycopg[binary]>=3.2, Python 3.10+
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ADMIN_SECRET = os.getenv("TOURNAMENT_ADMIN_SECRET", "").strip()

MIN_FEE = Decimal(os.getenv("TOURNAMENT_MIN_ENTRY_FEE", "1"))
MAX_FEE = Decimal(os.getenv("TOURNAMENT_MAX_ENTRY_FEE", "1000"))
MIN_COMMISSION = Decimal(os.getenv("TOURNAMENT_MIN_COMMISSION_PERCENT", "0"))
MAX_COMMISSION = Decimal(os.getenv("TOURNAMENT_MAX_COMMISSION_PERCENT", "20"))

PAYMENT_METHODS = {"tranzak", "moncash", "natcash"}
BOARD_SIZES = {15, 19, 20}
DURATIONS = {60, 120, 180, 300, 600, 900, 1200, 1800}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,80}$")


class TournamentError(Exception):
    """Expected validation or business-rule error."""


def _db():
    if not DATABASE_URL:
        raise TournamentError("DATABASE_URL is not configured.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def _money(value: Any, field: str) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise TournamentError(f"{field} must be a valid amount.")
    if not amount.is_finite():
        raise TournamentError(f"{field} is invalid.")
    return amount


def init_tournament_schema() -> None:
    """Create only additive tournament tables; safe to call at startup."""
    ddl = """
    CREATE TABLE IF NOT EXISTS gomoku_tournaments (
        tournament_id TEXT PRIMARY KEY,
        organizer_id TEXT NOT NULL,
        title TEXT NOT NULL,
        entry_fee NUMERIC(12,2) NOT NULL,
        currency TEXT NOT NULL DEFAULT 'USD',
        payment_method TEXT NOT NULL,
        commission_percent NUMERIC(5,2) NOT NULL,
        board_size INTEGER NOT NULL,
        duration_seconds INTEGER NOT NULL,
        prize_shares JSONB NOT NULL,
        status TEXT NOT NULL DEFAULT 'registration',
        created_at BIGINT NOT NULL,
        started_at BIGINT
    );
    CREATE TABLE IF NOT EXISTS gomoku_tournament_entries (
        entry_id TEXT PRIMARY KEY,
        tournament_id TEXT NOT NULL REFERENCES gomoku_tournaments(tournament_id),
        player_id TEXT NOT NULL,
        payment_reference TEXT,
        proof_data TEXT,
        payment_status TEXT NOT NULL DEFAULT 'pending',
        paid_amount NUMERIC(12,2) NOT NULL,
        created_at BIGINT NOT NULL,
        verified_at BIGINT,
        UNIQUE(tournament_id, player_id)
    );
    CREATE TABLE IF NOT EXISTS gomoku_tournament_chat (
        message_id TEXT PRIMARY KEY,
        tournament_id TEXT NOT NULL REFERENCES gomoku_tournaments(tournament_id),
        player_id TEXT NOT NULL,
        username TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at BIGINT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS gomoku_tournament_voice (
        tournament_id TEXT NOT NULL REFERENCES gomoku_tournaments(tournament_id),
        player_id TEXT NOT NULL,
        status TEXT NOT NULL,
        updated_at BIGINT NOT NULL,
        PRIMARY KEY(tournament_id, player_id)
    );
    CREATE INDEX IF NOT EXISTS idx_gomoku_tournament_entries_tournament
        ON gomoku_tournament_entries(tournament_id);
    CREATE INDEX IF NOT EXISTS idx_gomoku_tournament_chat_tournament
        ON gomoku_tournament_chat(tournament_id, created_at);
    """
    with _db() as conn:
        conn.execute(ddl)


def _get_tournament(conn, tournament_id: str):
    row = conn.execute(
        "SELECT * FROM gomoku_tournaments WHERE tournament_id=%s",
        (tournament_id,),
    ).fetchone()
    if not row:
        raise TournamentError("Tournament not found.")
    return row


def create_tournament(
    organizer_id: str,
    title: str,
    entry_fee: Any,
    payment_method: str,
    commission_percent: Any,
    board_size: int,
    duration_seconds: int,
    prize_shares: dict[str, Any],
    currency: str = "USD",
) -> dict:
    """Create a tournament with validated settings and a 100% prize split."""
    if not organizer_id or not title or len(title.strip()) > 100:
        raise TournamentError("Organizer and a title (max 100 characters) are required.")
    fee = _money(entry_fee, "Entry fee")
    commission = _money(commission_percent, "Commission")
    method = str(payment_method).lower().strip()
    if not MIN_FEE <= fee <= MAX_FEE:
        raise TournamentError(f"Entry fee must be between {MIN_FEE} and {MAX_FEE}.")
    if not MIN_COMMISSION <= commission <= MAX_COMMISSION:
        raise TournamentError(
            f"Commission must be between {MIN_COMMISSION}% and {MAX_COMMISSION}%."
        )
    if method not in PAYMENT_METHODS:
        raise TournamentError("Payment method must be Tranzak, MonCash or NatCash.")
    if board_size not in BOARD_SIZES:
        raise TournamentError(f"Board size must be one of {sorted(BOARD_SIZES)}.")
    if duration_seconds not in DURATIONS:
        raise TournamentError(f"Duration must be one of {sorted(DURATIONS)} seconds.")
    if not isinstance(prize_shares, dict) or not prize_shares:
        raise TournamentError("Prize distribution is required.")
    shares = {}
    total = Decimal("0")
    for place, raw in prize_shares.items():
        if place not in {"1", "2", "3"}:
            raise TournamentError("Prize places must be 1, 2 or 3.")
        pct = _money(raw, f"Prize share {place}")
        if pct < 0:
            raise TournamentError("Prize shares cannot be negative.")
        shares[place] = str(pct)
        total += pct
    if total != Decimal("100.00"):
        raise TournamentError("Prize shares must add up to exactly 100%.")
    if currency not in {"USD", "HTG"}:
        raise TournamentError("Currency must be USD or HTG.")

    tid = "tourn_" + secrets.token_urlsafe(12).replace("-", "_")
    now = int(time.time())
    with _db() as conn:
        conn.execute(
            """INSERT INTO gomoku_tournaments
            (tournament_id, organizer_id, title, entry_fee, currency,
             payment_method, commission_percent, board_size, duration_seconds,
             prize_shares, status, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,'registration',%s)""",
            (tid, organizer_id, title.strip(), fee, currency, method, commission,
             board_size, duration_seconds, json.dumps(shares), now),
        )
    return {
        "ok": True, "tournament_id": tid, "status": "registration",
        "entry_fee": str(fee), "currency": currency, "payment_method": method,
        "commission_percent": str(commission), "board_size": board_size,
        "duration_seconds": duration_seconds, "prize_shares": shares,
    }


def register_entry(
    tournament_id: str,
    player_id: str,
    payment_reference: str = "",
    proof_data: str = "",
) -> dict:
    """
    Create a PENDING entry. No seat is reserved/confirmed until payment verifies.
    proof_data should be a private storage key, not a public image URL.
    """
    if not player_id:
        raise TournamentError("Player ID is required.")
    if len(proof_data) > 500:
        raise TournamentError("Proof reference is too long.")
    with _db() as conn:
        t = _get_tournament(conn, tournament_id)
        if t["status"] != "registration":
            raise TournamentError("Registration is closed.")
        if not proof_data and t["payment_method"] in {"moncash", "natcash"}:
            raise TournamentError("A payment proof reference is required.")
        entry_id = "entry_" + secrets.token_urlsafe(12).replace("-", "_")
        try:
            conn.execute(
                """INSERT INTO gomoku_tournament_entries
                (entry_id,tournament_id,player_id,payment_reference,proof_data,
                 payment_status,paid_amount,created_at)
                VALUES (%s,%s,%s,%s,%s,'pending',%s,%s)""",
                (entry_id, tournament_id, player_id, payment_reference or None,
                 proof_data or None, t["entry_fee"], int(time.time())),
            )
        except psycopg.errors.UniqueViolation:
            raise TournamentError("Player already registered for this tournament.")
    return {"ok": True, "entry_id": entry_id, "payment_status": "pending",
            "seat_confirmed": False}


def mark_payment_verified(entry_id: str, trusted_reference: str = "") -> dict:
    """
    TRUSTED SERVER-ONLY function. Call after signed Tranzak webhook validation
    or explicit admin approval of MonCash/NatCash proof.
    """
    with _db() as conn:
        row = conn.execute(
            """SELECT * FROM gomoku_tournament_entries
               WHERE entry_id=%s FOR UPDATE""", (entry_id,)
        ).fetchone()
        if not row:
            raise TournamentError("Entry not found.")
        if row["payment_status"] == "verified":
            return {"ok": True, "entry_id": entry_id, "seat_confirmed": True,
                    "already_verified": True}
        if row["payment_status"] != "pending":
            raise TournamentError("Entry is not awaiting payment verification.")
        conn.execute(
            """UPDATE gomoku_tournament_entries
               SET payment_status='verified', verified_at=%s,
                   payment_reference=COALESCE(%s,payment_reference)
               WHERE entry_id=%s""",
            (int(time.time()), trusted_reference or None, entry_id),
        )
    return {"ok": True, "entry_id": entry_id, "seat_confirmed": True}


def admin_review_entry(entry_id: str, decision: str, admin_secret: str) -> dict:
    """Admin approval/rejection for manual MonCash/NatCash proof."""
    if not ADMIN_SECRET or not secrets.compare_digest(admin_secret, ADMIN_SECRET):
        raise TournamentError("Unauthorized admin.")
    if decision not in {"approved", "rejected"}:
        raise TournamentError("Decision must be approved or rejected.")
    if decision == "approved":
        return mark_payment_verified(entry_id, "manual_admin_approved")
    with _db() as conn:
        cur = conn.execute(
            """UPDATE gomoku_tournament_entries SET payment_status='rejected'
               WHERE entry_id=%s AND payment_status='pending'""", (entry_id,)
        )
        if cur.rowcount != 1:
            raise TournamentError("Pending entry not found.")
    return {"ok": True, "entry_id": entry_id, "payment_status": "rejected",
            "seat_confirmed": False}


def tournament_summary(tournament_id: str) -> dict:
    with _db() as conn:
        t = _get_tournament(conn, tournament_id)
        stats = conn.execute(
            """SELECT COUNT(*) FILTER (WHERE payment_status='verified') AS paid_count,
                      COUNT(*) FILTER (WHERE payment_status='pending') AS pending_count,
                      COALESCE(SUM(paid_amount) FILTER
                        (WHERE payment_status='verified'),0) AS gross
               FROM gomoku_tournament_entries WHERE tournament_id=%s""",
            (tournament_id,),
        ).fetchone()
        gross = Decimal(stats["gross"])
        commission = (gross * Decimal(t["commission_percent"]) / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        pool = gross - commission
        shares = t["prize_shares"]
        prizes = {
            place: str((pool * Decimal(pct) / 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ))
            for place, pct in shares.items()
        }
        return {
            "tournament_id": tournament_id, "status": t["status"],
            "paid_count": stats["paid_count"], "pending_count": stats["pending_count"],
            "gross_collected": str(gross), "commission": str(commission),
            "prize_pool": str(pool), "prizes": prizes,
            "board_size": t["board_size"], "duration_seconds": t["duration_seconds"],
        }


def start_tournament(tournament_id: str, organizer_id: str) -> dict:
    """Start only if organizer owns it and at least two paid players are confirmed."""
    with _db() as conn:
        t = _get_tournament(conn, tournament_id)
        if t["organizer_id"] != organizer_id:
            raise TournamentError("Only the organizer can start this tournament.")
        if t["status"] != "registration":
            raise TournamentError("Tournament is not open for starting.")
        count = conn.execute(
            """SELECT COUNT(*) AS n FROM gomoku_tournament_entries
               WHERE tournament_id=%s AND payment_status='verified'""",
            (tournament_id,),
        ).fetchone()["n"]
        if count < 2:
            raise TournamentError("At least two verified players are required.")
        conn.execute(
            "UPDATE gomoku_tournaments SET status='live', started_at=%s WHERE tournament_id=%s",
            (int(time.time()), tournament_id),
        )
    return {"ok": True, "status": "live", "board_size": t["board_size"],
            "duration_seconds": t["duration_seconds"],
            "instruction": "Apply these settings to every tournament match in the existing game engine."}


def tournament_chat(tournament_id: str, player_id: str, username: str,
                    message: str) -> dict:
    msg = str(message).strip()
    if not msg or len(msg) > 500:
        raise TournamentError("Chat message must contain 1–500 characters.")
    mid = "msg_" + secrets.token_urlsafe(10).replace("-", "_")
    with _db() as conn:
        _get_tournament(conn, tournament_id)
        conn.execute(
            """INSERT INTO gomoku_tournament_chat
               (message_id,tournament_id,player_id,username,message,created_at)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (mid, tournament_id, player_id, username[:60], msg, int(time.time())),
        )
    return {"ok": True, "message_id": mid, "message": msg}


def get_tournament_chat(tournament_id: str, limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    with _db() as conn:
        _get_tournament(conn, tournament_id)
        rows = conn.execute(
            """SELECT player_id,username,message,created_at
               FROM gomoku_tournament_chat WHERE tournament_id=%s
               ORDER BY created_at DESC LIMIT %s""", (tournament_id, limit)
        ).fetchall()
    return list(reversed(rows))


def request_spectator_mic(tournament_id: str, player_id: str) -> dict:
    with _db() as conn:
        t = _get_tournament(conn, tournament_id)
        if t["status"] != "live":
            raise TournamentError("Voice requests are available during live matches.")
        conn.execute(
            """INSERT INTO gomoku_tournament_voice
               (tournament_id,player_id,status,updated_at)
               VALUES (%s,%s,'requested',%s)
               ON CONFLICT (tournament_id,player_id)
               DO UPDATE SET status='requested',updated_at=EXCLUDED.updated_at""",
            (tournament_id, player_id, int(time.time())),
        )
    return {"ok": True, "status": "requested"}


def decide_spectator_mic(tournament_id: str, player_id: str,
                         organizer_id: str, approved: bool) -> dict:
    with _db() as conn:
        t = _get_tournament(conn, tournament_id)
        if t["organizer_id"] != organizer_id:
            raise TournamentError("Only the organizer can approve microphone access.")
        status = "approved" if approved else "denied"
        cur = conn.execute(
            """UPDATE gomoku_tournament_voice SET status=%s,updated_at=%s
               WHERE tournament_id=%s AND player_id=%s AND status='requested'""",
            (status, int(time.time()), tournament_id, player_id),
        )
        if cur.rowcount != 1:
            raise TournamentError("No pending microphone request for this player.")
    return {"ok": True, "player_id": player_id, "status": status}


def tournament_members(tournament_id: str) -> list[dict]:
    with _db() as conn:
        _get_tournament(conn, tournament_id)
        rows = conn.execute(
            """SELECT player_id,payment_status,created_at,verified_at
               FROM gomoku_tournament_entries WHERE tournament_id=%s
               ORDER BY created_at""", (tournament_id,)
        ).fetchall()
    return rows


def admin_config() -> dict:
    """Safe values to show in admin UI; never expose the admin secret."""
    return {
        "min_entry_fee": str(MIN_FEE), "max_entry_fee": str(MAX_FEE),
        "min_commission_percent": str(MIN_COMMISSION),
        "max_commission_percent": str(MAX_COMMISSION),
        "payment_methods": sorted(PAYMENT_METHODS),
        "board_sizes": sorted(BOARD_SIZES),
        "durations_seconds": sorted(DURATIONS),
        "manual_review_methods": ["moncash", "natcash"],
        "tranzak_requires_signed_wallet_webhook": True,
    }


# Suggested event routing inside the existing async WebSocket handler:
#
# if kind == "tournament_create":
#     result = await asyncio.to_thread(create_tournament, player_id, ...)
# elif kind == "tournament_register":
#     result = await asyncio.to_thread(register_entry, tournament_id, player_id, ...)
# elif kind == "tournament_chat":
#     result = await asyncio.to_thread(tournament_chat, tournament_id, player_id, username, message)
# elif kind == "tournament_voice_request":
#     result = await asyncio.to_thread(request_spectator_mic, tournament_id, player_id)
# elif kind == "tournament_voice_decision":
#     result = await asyncio.to_thread(decide_spectator_mic, tournament_id, player_id,
#                                     organizer_id, approved)
#
# Do NOT expose mark_payment_verified() or admin_review_entry() to ordinary
# player websocket messages. Call them only from trusted payment/admin code.


# ---- Additive WebSocket integration helpers / tournament bracket ----

def list_tournaments(limit: int = 30) -> list[dict]:
    limit=max(1,min(int(limit),100))
    with _db() as conn:
        rows=conn.execute(
            "SELECT tournament_id FROM gomoku_tournaments ORDER BY created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
    result=[]
    for row in rows:
        tid=row["tournament_id"]
        result.append({**tournament_summary(tid), **_public_tournament(tid)})
    return result


def _public_tournament(tournament_id: str) -> dict:
    with _db() as conn:
        t=_get_tournament(conn,tournament_id)
        entries=conn.execute(
            """SELECT e.player_id,e.payment_status,e.created_at,p.username
               FROM gomoku_tournament_entries e
               LEFT JOIN players p ON p.id::text=e.player_id
               WHERE e.tournament_id=%s ORDER BY e.created_at""",
            (tournament_id,),
        ).fetchall()
        matches=conn.execute(
            """SELECT m.match_id,m.round_no,m.match_no,m.player1_id,
                      p1.username AS player1_name,m.player2_id,p2.username AS player2_name,
                      m.winner_id,m.room_code,m.status
               FROM gomoku_tournament_matches m
               LEFT JOIN players p1 ON p1.id::text=m.player1_id
               LEFT JOIN players p2 ON p2.id::text=m.player2_id
               WHERE m.tournament_id=%s ORDER BY m.round_no,m.match_no""",
            (tournament_id,),
        ).fetchall() if _table_exists(conn,"gomoku_tournament_matches") else []
        organizer=conn.execute("SELECT username FROM players WHERE id::text=%s",(str(t["organizer_id"]),)).fetchone()
        return {
            "tournament_id":tournament_id,"title":t["title"],
            "organizer":organizer["username"] if organizer else "Organisateur",
            "organizer_id":str(t["organizer_id"]),"entry_fee":str(t["entry_fee"]),
            "currency":t["currency"],"payment_method":t["payment_method"],
            "commission_percent":str(t["commission_percent"]),
            "board_size":t["board_size"],"duration_seconds":t["duration_seconds"],
            "prize_shares":t["prize_shares"],"status":t["status"],
            "players":[{"player_id":str(x["player_id"]),"username":x["username"],
                        "payment_status":x["payment_status"]} for x in entries],
            "matches":[dict(x) for x in matches],
        }


def _table_exists(conn, table_name: str) -> bool:
    return bool(conn.execute(
        "SELECT to_regclass(%s) AS name",(f"public.{table_name}",)
    ).fetchone()["name"])


def admin_entries(tournament_id: str, admin_secret: str) -> list[dict]:
    if not ADMIN_SECRET or not secrets.compare_digest(admin_secret,ADMIN_SECRET):
        raise TournamentError("Unauthorized admin.")
    with _db() as conn:
        rows=conn.execute(
            """SELECT entry_id,player_id,payment_reference,proof_data,
                      payment_status,paid_amount,created_at
               FROM gomoku_tournament_entries WHERE tournament_id=%s
               ORDER BY created_at""",(tournament_id,)
        ).fetchall()
    return [dict(x) for x in rows]


def init_bracket_schema() -> None:
    with _db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS gomoku_tournament_matches (
          match_id TEXT PRIMARY KEY,
          tournament_id TEXT NOT NULL REFERENCES gomoku_tournaments(tournament_id),
          round_no INTEGER NOT NULL,
          match_no INTEGER NOT NULL,
          player1_id TEXT,
          player2_id TEXT,
          winner_id TEXT,
          room_code TEXT,
          status TEXT NOT NULL DEFAULT 'waiting',
          UNIQUE(tournament_id,round_no,match_no)
        );
        CREATE INDEX IF NOT EXISTS idx_gomoku_tournament_matches
          ON gomoku_tournament_matches(tournament_id,round_no,match_no);
        """)


def _make_round(conn,tournament_id,round_no,players):
    import random
    players=list(players)
    random.SystemRandom().shuffle(players)
    for idx in range(0,len(players),2):
        p1=str(players[idx]); p2=str(players[idx+1]) if idx+1<len(players) else None
        mid="tm_"+secrets.token_urlsafe(10).replace("-","_")
        conn.execute(
            """INSERT INTO gomoku_tournament_matches
               (match_id,tournament_id,round_no,match_no,player1_id,player2_id,
                winner_id,status)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (mid,tournament_id,round_no,idx//2+1,p1,p2,p1 if p2 is None else None,
             "finished" if p2 is None else "waiting"),
        )


def advance_bracket(tournament_id: str) -> dict:
    init_bracket_schema()
    with _db() as conn:
        last=conn.execute(
            """SELECT round_no,COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE winner_id IS NOT NULL) AS done
               FROM gomoku_tournament_matches WHERE tournament_id=%s
               GROUP BY round_no ORDER BY round_no DESC LIMIT 1""",
            (tournament_id,),
        ).fetchone()
        if not last or last["total"]!=last["done"]:
            return {"advanced":False}
        winners=conn.execute(
            """SELECT winner_id FROM gomoku_tournament_matches
               WHERE tournament_id=%s AND round_no=%s ORDER BY match_no""",
            (tournament_id,last["round_no"]),
        ).fetchall()
        winners=[x["winner_id"] for x in winners if x["winner_id"]]
        if len(winners)<=1:
            conn.execute("UPDATE gomoku_tournaments SET status='finished' WHERE tournament_id=%s",(tournament_id,))
            return {"advanced":True,"finished":True,"champion":winners[0] if winners else None}
        next_round=last["round_no"]+1
        exists=conn.execute(
            "SELECT 1 FROM gomoku_tournament_matches WHERE tournament_id=%s AND round_no=%s LIMIT 1",
            (tournament_id,next_round),
        ).fetchone()
        if not exists:_make_round(conn,tournament_id,next_round,winners)
        return {"advanced":True,"finished":False,"round":next_round}


def record_match_result(tournament_id: str, match_id: str, winner_id: str) -> dict:
    init_bracket_schema()
    with _db() as conn:
        match=conn.execute(
            "SELECT * FROM gomoku_tournament_matches WHERE match_id=%s AND tournament_id=%s FOR UPDATE",
            (match_id,tournament_id),
        ).fetchone()
        if not match: raise TournamentError("Tournament match not found.")
        if str(winner_id) not in {str(match["player1_id"]),str(match["player2_id"])}:
            raise TournamentError("Winner is not a participant in this match.")
        conn.execute(
            "UPDATE gomoku_tournament_matches SET winner_id=%s,status='finished' WHERE match_id=%s",
            (str(winner_id),match_id),
        )
    return advance_bracket(tournament_id)


def attach_match_room(tournament_id: str, match_id: str, room_code: str,
                      player_id: str) -> dict:
    init_bracket_schema()
    with _db() as conn:
        t=_get_tournament(conn,tournament_id)
        if t["status"]!="live": raise TournamentError("Tournament is not live.")
        m=conn.execute(
            "SELECT * FROM gomoku_tournament_matches WHERE match_id=%s AND tournament_id=%s FOR UPDATE",
            (match_id,tournament_id),
        ).fetchone()
        if not m: raise TournamentError("Match not found.")
        if str(player_id) not in {str(m["player1_id"]),str(m["player2_id"])}:
            raise TournamentError("You are not assigned to this match.")
        if m["status"] not in {"waiting","playing"}:
            raise TournamentError("This match is already finished.")
        if m["room_code"] and m["room_code"]!=room_code:
            raise TournamentError("A room is already assigned to this match.")
        conn.execute(
            "UPDATE gomoku_tournament_matches SET room_code=%s,status='playing' WHERE match_id=%s",
            (room_code,match_id),
        )
        return {"ok":True,"board_size":t["board_size"],
                "duration_seconds":t["duration_seconds"],"room_code":room_code}


def revoke_spectator_mic(tournament_id: str, player_id: str,
                         organizer_id: str) -> dict:
    with _db() as conn:
        t=_get_tournament(conn,tournament_id)
        if str(t["organizer_id"])!=str(organizer_id):
            raise TournamentError("Only the organizer can revoke microphone access.")
        conn.execute(
            """UPDATE gomoku_tournament_voice SET status='revoked',updated_at=%s
               WHERE tournament_id=%s AND player_id=%s""",
            (int(time.time()),tournament_id,str(player_id)),
        )
    return {"ok":True,"status":"revoked"}


def delete_tournament_message(message_id: str, admin_secret: str) -> dict:
    if not ADMIN_SECRET or not secrets.compare_digest(admin_secret,ADMIN_SECRET):
        raise TournamentError("Unauthorized moderator.")
    with _db() as conn:
        cur=conn.execute("DELETE FROM gomoku_tournament_chat WHERE message_id=%s",(message_id,))
        if cur.rowcount!=1: raise TournamentError("Message not found.")
    return {"ok":True}


def list_tournament_messages(tournament_id: str, player_id: str) -> list[dict]:
    with _db() as conn:
        t=_get_tournament(conn,tournament_id)
        is_organizer=str(t["organizer_id"])==str(player_id)
        is_confirmed=conn.execute(
            """SELECT 1 FROM gomoku_tournament_entries
               WHERE tournament_id=%s AND player_id=%s AND payment_status='verified'""",
            (tournament_id,str(player_id)),
        ).fetchone()
        if not is_organizer and not is_confirmed:
            raise TournamentError("Chat is for verified players and organizer only.")
        rows=conn.execute(
            """SELECT message_id,player_id,username,message,created_at
               FROM gomoku_tournament_chat WHERE tournament_id=%s
               ORDER BY created_at DESC LIMIT 60""",(tournament_id,)
        ).fetchall()
    return [dict(x) for x in reversed(rows)]


# Final overrides and read helpers used by the WebSocket adapter.
def start_tournament(tournament_id: str, organizer_id: str) -> dict:
    init_bracket_schema()
    with _db() as conn:
        t=_get_tournament(conn,tournament_id)
        if str(t["organizer_id"])!=str(organizer_id):
            raise TournamentError("Only the organizer can start this tournament.")
        if t["status"]!="registration":
            raise TournamentError("Tournament is not open for starting.")
        players=conn.execute(
            """SELECT player_id FROM gomoku_tournament_entries
               WHERE tournament_id=%s AND payment_status='verified' ORDER BY created_at""",
            (tournament_id,),
        ).fetchall()
        ids=[str(x["player_id"]) for x in players]
        if len(ids)<2:
            raise TournamentError("At least two verified players are required.")
        conn.execute("UPDATE gomoku_tournaments SET status='live',started_at=%s WHERE tournament_id=%s",
                     (int(time.time()),tournament_id))
        _make_round(conn,tournament_id,1,ids)
    return {"ok":True,"status":"live","tournament_id":tournament_id,
            "matches_created":(len(ids)+1)//2}


def get_tournament_match(tournament_id: str, match_id: str) -> dict:
    init_bracket_schema()
    with _db() as conn:
        t=_get_tournament(conn,tournament_id)
        m=conn.execute(
            "SELECT * FROM gomoku_tournament_matches WHERE tournament_id=%s AND match_id=%s",
            (tournament_id,match_id),
        ).fetchone()
        if not m: raise TournamentError("Tournament match not found.")
        return {"match_id":m["match_id"],"round_no":m["round_no"],
                "player1_id":m["player1_id"],"player2_id":m["player2_id"],
                "winner_id":m["winner_id"],"room_code":m["room_code"],
                "status":m["status"],"organizer_id":str(t["organizer_id"]),
                "board_size":t["board_size"],"duration_seconds":t["duration_seconds"],
                "tournament_status":t["status"]}


def tournament_organizer(tournament_id: str) -> str:
    with _db() as conn:
        t=_get_tournament(conn,tournament_id)
        return str(t["organizer_id"])


def can_spectator_use_mic(tournament_id: str, player_id: str) -> bool:
    with _db() as conn:
        row=conn.execute(
            """SELECT status FROM gomoku_tournament_voice
               WHERE tournament_id=%s AND player_id=%s""",
            (tournament_id,str(player_id)),
        ).fetchone()
    return bool(row and row["status"]=="approved")


# Security/UX refinements for the integrated server.
def register_entry(tournament_id: str, player_id: str,
                   payment_reference: str = "", proof_data: str = "") -> dict:
    if not player_id: raise TournamentError("Player ID is required.")
    if len(proof_data)>900000: raise TournamentError("Payment proof image exceeds the 650 KB limit.")
    with _db() as conn:
        t=_get_tournament(conn,tournament_id)
        if t["status"]!="registration": raise TournamentError("Registration is closed.")
        if not proof_data and t["payment_method"] in {"moncash","natcash"}:
            raise TournamentError("A payment proof image is required for this payment method.")
        entry_id="entry_"+secrets.token_urlsafe(12).replace("-","_")
        try:
            conn.execute(
                """INSERT INTO gomoku_tournament_entries
                   (entry_id,tournament_id,player_id,payment_reference,proof_data,
                    payment_status,paid_amount,created_at)
                   VALUES (%s,%s,%s,%s,%s,'pending',%s,%s)""",
                (entry_id,tournament_id,str(player_id),payment_reference or None,
                 proof_data or None,t["entry_fee"],int(time.time())),
            )
        except psycopg.errors.UniqueViolation:
            raise TournamentError("Player already registered for this tournament.")
    return {"ok":True,"entry_id":entry_id,"payment_status":"pending","seat_confirmed":False}


def admin_review_entry(entry_id: str, decision: str, admin_secret: str) -> dict:
    if not ADMIN_SECRET or not secrets.compare_digest(admin_secret,ADMIN_SECRET):
        raise TournamentError("Unauthorized admin.")
    if decision not in {"approved","rejected"}: raise TournamentError("Decision must be approved or rejected.")
    with _db() as conn:
        row=conn.execute(
            """SELECT e.payment_status,t.payment_method FROM gomoku_tournament_entries e
               JOIN gomoku_tournaments t ON t.tournament_id=e.tournament_id
               WHERE e.entry_id=%s FOR UPDATE""",(entry_id,)
        ).fetchone()
        if not row: raise TournamentError("Entry not found.")
        if row["payment_status"]!="pending": raise TournamentError("Entry is not pending.")
        if row["payment_method"]=="tranzak":
            raise TournamentError("Tranzak must be confirmed by its signed Wallet webhook, not manual browser approval.")
        if decision=="rejected":
            conn.execute("UPDATE gomoku_tournament_entries SET payment_status='rejected' WHERE entry_id=%s",(entry_id,))
            return {"ok":True,"entry_id":entry_id,"payment_status":"rejected","seat_confirmed":False}
    return mark_payment_verified(entry_id,"manual_admin_approved")


def record_match_draw(tournament_id: str, match_id: str) -> dict:
    init_bracket_schema()
    with _db() as conn:
        conn.execute(
            """UPDATE gomoku_tournament_matches
               SET status='waiting',room_code=NULL,winner_id=NULL
               WHERE tournament_id=%s AND match_id=%s""",
            (tournament_id,match_id),
        )
    return {"ok":True,"status":"waiting","message":"Match nil; li dwe rejwe."}


def tournament_chat(tournament_id: str, player_id: str, username: str, message: str) -> dict:
    msg=str(message).strip()
    if not msg or len(msg)>300: raise TournamentError("Chat message must contain 1–300 characters.")
    with _db() as conn:
        t=_get_tournament(conn,tournament_id)
        organizer=str(t["organizer_id"])==str(player_id)
        confirmed=conn.execute(
            """SELECT 1 FROM gomoku_tournament_entries
               WHERE tournament_id=%s AND player_id=%s AND payment_status='verified'""",
            (tournament_id,str(player_id)),
        ).fetchone()
        if not organizer and not confirmed:
            raise TournamentError("Chat la rezève pou jwè ki gen peman verifye ak òganizatè a.")
        mid="msg_"+secrets.token_urlsafe(10).replace("-","_")
        conn.execute(
            """INSERT INTO gomoku_tournament_chat
               (message_id,tournament_id,player_id,username,message,created_at)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (mid,tournament_id,str(player_id),username[:50],msg,int(time.time())),
        )
    return {"ok":True,"message_id":mid,"message":msg}



def rename_tournament(tournament_id: str, organizer_id: str, title: str) -> dict:
    """Rename a tournament only by its organizer before it starts."""
    clean_title = str(title or "").strip()
    if not clean_title or len(clean_title) > 100:
        raise TournamentError("Non tournoi a obligatwa (1 a 100 karaktè).")
    with _db() as conn:
        t = _get_tournament(conn, str(tournament_id))
        if str(t["organizer_id"]) != str(organizer_id):
            raise TournamentError("Se òganizatè a sèlman ki ka modifye non tournoi a.")
        if t["status"] != "registration":
            raise TournamentError("Ou ka modifye non an sèlman anvan tournoi a kòmanse.")
        conn.execute(
            "UPDATE gomoku_tournaments SET title=%s WHERE tournament_id=%s",
            (clean_title, str(tournament_id)),
        )
    return {"ok": True, "title": clean_title, "message": "Non tournoi a modifye avèk siksè."}
