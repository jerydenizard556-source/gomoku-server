import asyncio
import json
import os
import secrets
import string
import time
import hashlib
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
import websockets

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "10000"))
BOARD_SIZE = 20
START_TIME = 10 * 60
TICK = 1

DATABASE_URL = os.getenv("DATABASE_URL")

rooms = {}
waiting = None
clients = set()
players_online = {}
connections = {}


def db():
    if not DATABASE_URL:
        return None
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    con = db()
    if not con:
        return
    try:
        with con:
            with con.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS players (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS player_stats (
                        player_id INTEGER PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
                        points INTEGER NOT NULL DEFAULT 0,
                        wins INTEGER NOT NULL DEFAULT 0,
                        losses INTEGER NOT NULL DEFAULT 0
                    )
                """)
    finally:
        con.close()


def clean_text(v, n=255):
    return str(v or "").strip()[:n]


def valid_email(v):
    return "@" in v and "." in v.rsplit("@", 1)[-1]


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return "pbkdf2_sha256$200000$" + salt.hex() + "$" + digest.hex()


def verify_password(password, stored):
    try:
        algo, iters, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return secrets.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def make_token():
    return secrets.token_urlsafe(32)


def make_room_code():
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(chars) for _ in range(6))
        if code not in rooms:
            return code


def empty_board():
    return {}


def room_base():
    return {
        "players": {},
        "spectators": set(),
        "board": empty_board(),
        "turn": 1,
        "starter": 1,
        "game_number": 1,
        "scores": {1: 0, 2: 0},
        "times": {1: START_TIME, 2: START_TIME},
        "last_tick": time.monotonic(),
        "active": False,
        "winner": None,
        "draw": False,
        "winning_line": None,
        "last_move": None,
        "rematch_request": None,
        "undo_request": None,
        "closed": False,
    }


def check_five(board, row, col, player):
    dirs = [(1, 0), (0, 1), (1, 1), (1, -1)]
    for dr, dc in dirs:
        cells = [(row, col)]
        for sign in (1, -1):
            r, c = row + dr * sign, col + dc * sign
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board.get(f"{r},{c}") == player:
                cells.append((r, c))
                r += dr * sign
                c += dc * sign
        if len(cells) >= 5:
            cells.sort()
            # Return exactly five around the newly played point when possible.
            if len(cells) == 5:
                return [{"row": r, "col": c} for r, c in cells]
            idx = cells.index((row, col))
            start = max(0, min(idx - 4, len(cells) - 5))
            chosen = cells[start:start + 5]
            return [{"row": r, "col": c} for r, c in chosen]
    return None


def player_name(room, n):
    p = room["players"].get(n)
    return p.get("username") if p else f"Joueur {n}"


def public_state(room):
    return {
        "board": room["board"],
        "turn": room["turn"],
        "starter": room["starter"],
        "game_number": room["game_number"],
        "black_score": room["scores"][1],
        "red_score": room["scores"][2],
        "black_time": max(0, int(room["times"][1])),
        "red_time": max(0, int(room["times"][2])),
        "active": room["active"],
        "winner": room["winner"],
        "draw": room["draw"],
        "winning_line": room["winning_line"],
        "last_move": room["last_move"],
        "rematch_request": room["rematch_request"],
        "undo_request": room["undo_request"],
        "black_name": player_name(room, 1),
        "red_name": player_name(room, 2),
        "spectator_count": len(room["spectators"]),
    }


async def send(ws, data):
    if ws and ws in clients:
        try:
            await ws.send(json.dumps(data, ensure_ascii=False))
        except Exception:
            pass


async def broadcast(room, data, include_spectators=True):
    targets = list(room["players"].values())
    if include_spectators:
        targets += list(room["spectators"])
    await asyncio.gather(*(send(w, data) for w in targets), return_exceptions=True)


async def state(room):
    await broadcast(room, {"type": "state", **public_state(room)})


def add_stats(player_id, win=False, loss=False, points=0):
    con = db()
    if not con:
        return
    try:
        with con:
            with con.cursor() as cur:
                cur.execute("""
                    INSERT INTO player_stats(player_id, points, wins, losses)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(player_id) DO UPDATE SET
                        points = player_stats.points + EXCLUDED.points,
                        wins = player_stats.wins + EXCLUDED.wins,
                        losses = player_stats.losses + EXCLUDED.losses
                """, (player_id, points, 1 if win else 0, 1 if loss else 0))
    finally:
        con.close()


def get_player(login):
    con = db()
    if not con:
        return None
    try:
        with con.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT p.id, p.username, p.email, p.password_hash,
                       COALESCE(s.points,0) points,
                       COALESCE(s.wins,0) wins,
                       COALESCE(s.losses,0) losses
                FROM players p
                LEFT JOIN player_stats s ON s.player_id=p.id
                WHERE LOWER(p.username)=LOWER(%s) OR LOWER(p.email)=LOWER(%s)
                LIMIT 1
            """, (login, login))
            return cur.fetchone()
    finally:
        con.close()


def create_player(username, email, password):
    con = db()
    if not con:
        return None, "Base de données indisponible."
    try:
        with con:
            with con.cursor() as cur:
                cur.execute("SELECT 1 FROM players WHERE LOWER(username)=LOWER(%s)", (username,))
                if cur.fetchone():
                    return None, "Ce nom d'utilisateur existe déjà."
                cur.execute("SELECT 1 FROM players WHERE LOWER(email)=LOWER(%s)", (email,))
                if cur.fetchone():
                    return None, "Cet email est déjà utilisé."
                cur.execute("""
                    INSERT INTO players(username,email,password_hash)
                    VALUES(%s,%s,%s) RETURNING id
                """, (username, email, hash_password(password)))
                pid = cur.fetchone()[0]
                cur.execute("INSERT INTO player_stats(player_id) VALUES(%s) ON CONFLICT DO NOTHING", (pid,))
                return pid, None
    except Exception:
        return None, "Impossible de créer le compte."
    finally:
        con.close()


async def register(ws, c):
    username = clean_text(c.get("username"), 50)
    email = clean_text(c.get("email"), 255).lower()
    password = str(c.get("password") or "")
    confirmation = str(c.get("password_confirmation") or "")
    if len(username) < 3:
        await send(ws, {"type": "register_result", "success": False, "message": "Nom d'utilisateur trop court."})
        return
    if not valid_email(email):
        await send(ws, {"type": "register_result", "success": False, "message": "Email invalide."})
        return
    if len(password) < 6:
        await send(ws, {"type": "register_result", "success": False, "message": "Mot de passe trop court."})
        return
    if password != confirmation:
        await send(ws, {"type": "register_result", "success": False, "message": "Les mots de passe ne correspondent pas."})
        return
    pid, err = create_player(username, email, password)
    if err:
        await send(ws, {"type": "register_result", "success": False, "message": err})
        return
    token = make_token()
    connections[ws] = {"player_id": pid, "username": username, "email": email, "token": token}
    players_online[pid] = ws
    await send(ws, {"type": "register_result", "success": True, "message": "Compte créé avec succès.", "player_id": pid, "username": username, "email": email, "account_token": token})
    await send_online_list()


async def login(ws, c):
    login_value = clean_text(c.get("login"), 255)
    password = str(c.get("password") or "")
    p = get_player(login_value)
    if not p or not verify_password(password, p["password_hash"]):
        await send(ws, {"type": "login_result", "success": False, "message": "Identifiants incorrects."})
        return
    token = make_token()
    connections[ws] = {"player_id": p["id"], "username": p["username"], "email": p["email"], "token": token}
    players_online[p["id"]] = ws
    await send(ws, {"type": "login_result", "success": True, "message": "Connexion réussie.", "player_id": p["id"], "username": p["username"], "email": p["email"], "account_token": token, "points": p["points"], "wins": p["wins"], "losses": p["losses"]})
    await send_online_list()


async def send_online_list():
    arr = []
    for pid, ws in list(players_online.items()):
        info = connections.get(ws)
        if info:
            arr.append({"player_id": pid, "username": info["username"]})
    msg = {"type": "online_players", "players": arr}
    await asyncio.gather(*(send(ws, msg) for ws in list(clients)), return_exceptions=True)


async def require_account(ws):
    info = connections.get(ws)
    if not info or not info.get("player_id"):
        await send(ws, {"type": "error", "message": "Connectez-vous à votre compte."})
        return False
    return True


async def create_room(ws):
    if not await require_account(ws): return
    code = make_room_code()
    r = room_base()
    r["players"][1] = ws
    rooms[code] = r
    info = connections[ws]
    info["room"] = code
    info["player"] = 1
    await send(ws, {"type": "created", "room": code, "player": 1, "session_token": info["token"], "username": info["username"]})
    await send(ws, {"type": "waiting_for_player"})
    await state(r)


async def join_room(ws, code):
    if not await require_account(ws): return
    code = clean_text(code, 6).upper()
    r = rooms.get(code)
    if not r or r.get("closed"):
        await send(ws, {"type": "error", "message": "Salle introuvable."})
        return
    if 2 in r["players"]:
        await send(ws, {"type": "error", "message": "Cette salle est déjà pleine."})
        return
    r["players"][2] = ws
    info = connections[ws]
    info["room"] = code
    info["player"] = 2
    r["active"] = True
    r["last_tick"] = time.monotonic()
    await send(ws, {"type": "joined", "room": code, "player": 2, "session_token": info["token"], "username": info["username"]})
    await broadcast(r, {"type": "match_found", "room": code, "message": "🎮 Adversaire trouvé ! Le match va commencer."})
    await state(r)


async def find_match(ws):
    global waiting
    if not await require_account(ws): return
    if waiting and waiting in clients and waiting is not ws:
        other = waiting
        waiting = None
        code = make_room_code()
        r = room_base()
        r["players"][1] = other
        r["players"][2] = ws
        r["active"] = True
        r["last_tick"] = time.monotonic()
        rooms[code] = r
        for sock, num in ((other, 1), (ws, 2)):
            info = connections.get(sock, {})
            info["room"] = code
            info["player"] = num
            await send(sock, {"type": "match_found", "room": code, "player": num, "session_token": info.get("token"), "message": "🎮 Adversaire trouvé ! Le match va commencer."})
        await state(r)
    else:
        waiting = ws
        await send(ws, {"type": "searching"})


async def cancel_match(ws):
    global waiting
    if waiting is ws:
        waiting = None
    await send(ws, {"type": "search_cancelled"})


async def move(ws, c):
    info = connections.get(ws, {})
    code = clean_text(c.get("room"), 6).upper()
    r = rooms.get(code)
    if not r or info.get("room") != code or info.get("player") not in (1, 2): return
    if not r["active"] or r["winner"] or r["draw"]: return
    if r["undo_request"] is not None: return
    p = info["player"]
    if r["turn"] != p: return
    try:
        row, col = int(c.get("row")), int(c.get("col"))
    except Exception:
        return
    if not (0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE): return
    key = f"{row},{col}"
    if key in r["board"]: return
    r["board"][key] = p
    r["last_move"] = {"row": row, "col": col, "player": p}
    win_line = check_five(r["board"], row, col, p)
    if win_line:
        r["winner"] = p
        r["winning_line"] = win_line
        r["active"] = False
        r["scores"][p] += 1
        pid_win = connections.get(r["players"][p], {}).get("player_id")
        pid_loss = connections.get(r["players"][3-p], {}).get("player_id")
        if pid_win: add_stats(pid_win, win=True, points=10)
        if pid_loss: add_stats(pid_loss, loss=True)
    elif len(r["board"]) >= BOARD_SIZE * BOARD_SIZE:
        r["draw"] = True
        r["active"] = False
    else:
        r["turn"] = 3 - p
    r["last_tick"] = time.monotonic()
    await state(r)


async def undo_request(ws, c):
    info = connections.get(ws, {})
    r = rooms.get(clean_text(c.get("room"), 6).upper())
    if not r or not r["active"] or r["undo_request"] is not None: return
    p = info.get("player")
    if p not in (1, 2) or r["last_move"] is None or r["last_move"]["player"] != p: return
    r["undo_request"] = p
    await state(r)
    opponent = r["players"].get(3-p)
    await send(opponent, {"type": "undo_request", "message": "L'adversaire demande de rejouer son dernier pion."})


async def undo_response(ws, c, accepted):
    info = connections.get(ws, {})
    r = rooms.get(clean_text(c.get("room"), 6).upper())
    if not r or r["undo_request"] is None: return
    requester = r["undo_request"]
    if info.get("player") != 3 - requester: return
    if accepted:
        lm = r["last_move"]
        if lm:
            r["board"].pop(f"{lm['row']},{lm['col']}", None)
            r["turn"] = requester
            r["last_move"] = None
            r["winner"] = None
            r["draw"] = False
            r["winning_line"] = None
    r["undo_request"] = None
    r["last_tick"] = time.monotonic()
    await state(r)


async def rematch_request(ws, c):
    info = connections.get(ws, {})
    r = rooms.get(clean_text(c.get("room"), 6).upper())
    if not r or r["active"] or not (r["winner"] or r["draw"]): return
    p = info.get("player")
    if p not in (1, 2): return
    # Only the losing player can request a rematch after a win; on draw either may request.
    if r["winner"] and p == r["winner"]: return
    if r["rematch_request"] is not None: return
    r["rematch_request"] = p
    await state(r)
    await send(r["players"].get(3-p), {"type": "rematch_request", "message": "🔄 L'adversaire demande une revanche."})


async def rematch_response(ws, c, accepted):
    info = connections.get(ws, {})
    r = rooms.get(clean_text(c.get("room"), 6).upper())
    if not r or r["rematch_request"] is None: return
    requester = r["rematch_request"]
    if info.get("player") != 3-requester: return
    if not accepted:
        r["rematch_request"] = None
        await state(r)
        await send(r["players"].get(requester), {"type": "rematch_refused", "message": "❌ Revanche refusée."})
        return
    r["game_number"] += 1
    r["starter"] = 3 - r["starter"]
    r["turn"] = r["starter"]
    r["board"] = {}
    r["times"] = {1: START_TIME, 2: START_TIME}
    r["active"] = True
    r["winner"] = None
    r["draw"] = False
    r["winning_line"] = None
    r["last_move"] = None
    r["rematch_request"] = None
    r["undo_request"] = None
    r["last_tick"] = time.monotonic()
    await broadcast(r, {"type": "rematch_accepted", "message": "🔄 Nouvelle partie ! Le starter alterne."})
    await state(r)


async def reset_room(ws, c):
    info = connections.get(ws, {})
    r = rooms.get(clean_text(c.get("room"), 6).upper())
    if not r: return
    if info.get("player") not in (1,2): return
    r["game_number"] += 1
    r["starter"] = 3-r["starter"]
    r["turn"] = r["starter"]
    r["board"] = {}
    r["times"] = {1: START_TIME, 2: START_TIME}
    r["active"] = len(r["players"]) == 2
    r["winner"] = None
    r["draw"] = False
    r["winning_line"] = None
    r["last_move"] = None
    r["rematch_request"] = None
    r["undo_request"] = None
    r["last_tick"] = time.monotonic()
    await state(r)


async def spectate_list(ws):
    result = []
    for code, r in rooms.items():
        if r.get("closed") or len(r["players"]) < 2: continue
        result.append({"room": code, "black_name": player_name(r,1), "red_name": player_name(r,2), "active": r["active"], "spectator_count": len(r["spectators"])})
    await send(ws, {"type": "spectator_matches", "matches": result})


async def spectate_join(ws, c):
    code = clean_text(c.get("room"), 6).upper()
    r = rooms.get(code)
    if not r or len(r["players"]) < 2:
        await send(ws, {"type": "error", "message": "Match introuvable."})
        return
    r["spectators"].add(ws)
    connections.setdefault(ws, {})["spectating"] = code
    await send(ws, {"type": "spectator_joined", "room": code, "message": "👀 Vous regardez le match."})
    await send(ws, {"type": "state", **public_state(r), "spectator": True})
    await broadcast(r, {"type": "spectator_count", "count": len(r["spectators"])})


async def direct_invite(ws, c):
    if not await require_account(ws): return
    try: target_id = int(c.get("player_id"))
    except Exception: return
    target = players_online.get(target_id)
    if not target or target not in clients:
        await send(ws, {"type": "invite_result", "success": False, "message": "Ce joueur n'est plus en ligne."})
        return
    sender = connections[ws]
    await send(target, {"type": "game_invitation", "from_player_id": sender["player_id"], "from_username": sender["username"]})
    await send(ws, {"type": "invite_result", "success": True, "message": "Invitation envoyée."})


async def direct_invite_response(ws, c, accepted):
    if not await require_account(ws): return
    try: sender_id = int(c.get("from_player_id"))
    except Exception: return
    sender = players_online.get(sender_id)
    if not sender or sender not in clients:
        await send(ws, {"type": "error", "message": "Le joueur n'est plus en ligne."})
        return
    if not accepted:
        await send(sender, {"type": "game_invitation_response", "accepted": False, "message": "Invitation refusée."})
        return
    code = make_room_code()
    r = room_base()
    r["players"][1] = sender
    r["players"][2] = ws
    r["active"] = True
    rooms[code] = r
    for sock, num in ((sender,1),(ws,2)):
        info = connections[sock]
        info["room"] = code
        info["player"] = num
    await broadcast(r, {"type": "match_found", "room": code, "message": "🎮 Invitation acceptée ! Le match va commencer."})
    await state(r)


async def chat(ws, c):
    info = connections.get(ws, {})
    text_value = clean_text(c.get("message"), 500)
    if not text_value: return
    code = info.get("room")
    r = rooms.get(code) if code else None
    if not r: return
    payload = {"type":"chat_message", "username": info.get("username","Joueur"), "message": text_value}
    await broadcast(r, payload)


async def abandon(ws, r):
    if not r or not r["active"]: return
    p = connections.get(ws, {}).get("player")
    if p not in (1,2): return
    winner = 3-p
    r["winner"] = winner
    r["active"] = False
    r["draw"] = False
    r["winning_line"] = None
    r["rematch_request"] = None
    r["undo_request"] = None
    r["scores"][winner] += 1
    pidw = connections.get(r["players"].get(winner), {}).get("player_id")
    pidx = connections.get(ws, {}).get("player_id")
    if pidw: add_stats(pidw, win=True, points=10)
    if pidx: add_stats(pidx, loss=True)
    await broadcast(r, {"type": "abandoned", "winner": winner, "message": f"🏆 Joueur {winner} gagne par abandon."})
    await state(r)


async def disconnect(ws):
    global waiting
    if waiting is ws:
        waiting = None
    clients.discard(ws)
    info = connections.pop(ws, None)
    if not info:
        return
    pid = info.get("player_id")
    if pid and players_online.get(pid) is ws:
        players_online.pop(pid, None)
    code = info.get("room")
    if code and code in rooms:
        r = rooms[code]
        r["spectators"].discard(ws)
        if info.get("player") in (1,2):
            await abandon(ws, r)
            r["players"].pop(info["player"], None)
            if not r["players"]:
                r["closed"] = True
                rooms.pop(code, None)
            else:
                await state(r)
        elif info.get("spectating"):
            await broadcast(r, {"type": "spectator_count", "count": len(r["spectators"])})
    await send_online_list()


async def timer_loop():
    while True:
        now = time.monotonic()
        for code, r in list(rooms.items()):
            if not r.get("active") or r.get("undo_request") is not None:
                r["last_tick"] = now
                continue
            elapsed = now - r.get("last_tick", now)
            if elapsed < 1:
                continue
            r["last_tick"] = now
            p = r["turn"]
            r["times"][p] -= elapsed
            if r["times"][p] <= 0:
                r["times"][p] = 0
                r["winner"] = 3-p
                r["active"] = False
                r["scores"][3-p] += 1
                win_sock = r["players"].get(3-p)
                loss_sock = r["players"].get(p)
                if win_sock:
                    pid = connections.get(win_sock, {}).get("player_id")
                    if pid: add_stats(pid, win=True, points=10)
                if loss_sock:
                    pid = connections.get(loss_sock, {}).get("player_id")
                    if pid: add_stats(pid, loss=True)
                await broadcast(r, {"type":"timeout", "winner":3-p, "message":f"⏱️ Joueur {p} n'a plus de temps."})
            await state(r)
        await asyncio.sleep(TICK)


async def handler(ws):
    clients.add(ws)
    connections.setdefault(ws, {})
    try:
        async for raw in ws:
            try:
                c = json.loads(raw)
            except Exception:
                await send(ws, {"type":"error","message":"Message invalide."})
                continue
            typ = c.get("type")
            if typ == "register": await register(ws,c)
            elif typ == "login": await login(ws,c)
            elif typ == "create": await create_room(ws)
            elif typ == "join": await join_room(ws,c.get("room",""))
            elif typ == "find_match": await find_match(ws)
            elif typ == "cancel_match": await cancel_match(ws)
            elif typ == "move": await move(ws,c)
            elif typ == "undo_request": await undo_request(ws,c)
            elif typ == "undo_response": await undo_response(ws,c,bool(c.get("accepted")))
            elif typ == "rematch_request": await rematch_request(ws,c)
            elif typ == "rematch_response": await rematch_response(ws,c,bool(c.get("accepted")))
            elif typ == "reset": await reset_room(ws,c)
            elif typ in ("spectator_list","list_spectator_matches","get_spectator_matches"): await spectate_list(ws)
            elif typ in ("spectate","spectator_join","watch_match"): await spectate_join(ws,c)
            elif typ in ("game_invitation","invite_player","play_request"): await direct_invite(ws,c)
            elif typ in ("game_invitation_response","invite_response","play_request_response"): await direct_invite_response(ws,c,bool(c.get("accepted")))
            elif typ == "chat": await chat(ws,c)
            elif typ == "abandon":
                info=connections.get(ws,{})
                r=rooms.get(info.get("room"))
                await abandon(ws,r)
            elif typ == "ping": await send(ws,{"type":"pong"})
            else: await send(ws,{"type":"error","message":"Commande inconnue."})
    except websockets.ConnectionClosed:
        pass
    finally:
        await disconnect(ws)


async def main():
    init_db()
    asyncio.create_task(timer_loop())
    print(f"MR JERY MOPION server listening on {HOST}:{PORT}")
    async with websockets.serve(handler, HOST, PORT, ping_interval=20, ping_timeout=20, max_size=1024*1024):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
