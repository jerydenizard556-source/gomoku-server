import asyncio
import hashlib
import json
import os
import re
import secrets
import string
import time
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
clients = {}          # websocket -> player_id
connections = {}      # player_id -> websocket
players_online = set()
invites = {}          # invitation_id -> invitation dict


def db_connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL manquant")
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = db_connect()
    try:
        with conn.cursor() as cur:
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
        conn.commit()
    finally:
        conn.close()


def make_password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return "pbkdf2_sha256$200000$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return secrets.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def get_player(player_id: int):
    conn = db_connect()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, username, email FROM players WHERE id=%s", (player_id,))
            return cur.fetchone()
    finally:
        conn.close()


def get_stats(player_id: int):
    conn = db_connect()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO player_stats(player_id) VALUES(%s)
                ON CONFLICT(player_id) DO NOTHING
            """, (player_id,))
            cur.execute("SELECT points, wins, losses FROM player_stats WHERE player_id=%s", (player_id,))
            row = cur.fetchone()
        conn.commit()
        return dict(row) if row else {"points": 0, "wins": 0, "losses": 0}
    finally:
        conn.close()


def update_stats(player_id: int, win: bool):
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO player_stats(player_id, points, wins, losses)
                VALUES(%s, %s, %s, %s)
                ON CONFLICT(player_id) DO UPDATE SET
                    points = player_stats.points + EXCLUDED.points,
                    wins = player_stats.wins + EXCLUDED.wins,
                    losses = player_stats.losses + EXCLUDED.losses
            """, (player_id, 3 if win else 0, 1 if win else 0, 0 if win else 1))
        conn.commit()
    finally:
        conn.close()


def valid_username(value):
    return bool(re.fullmatch(r"[A-Za-z0-9_À-ÿ .-]{2,50}", value or ""))


def valid_email(value):
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value or ""))


def new_room_code():
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if code not in rooms:
            return code


def blank_board():
    return [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]


def fresh_room(code):
    return {
        "room": code,
        "board": blank_board(),
        "players": {1: None, 2: None},
        "spectators": set(),
        "turn": 1,
        "starter": 1,
        "game_number": 1,
        "black_time": START_TIME,
        "red_time": START_TIME,
        "black_score": 0,
        "red_score": 0,
        "winner": None,
        "game_over": False,
        "draw": False,
        "abandonment": False,
        "winning_line": None,
        "last_move": None,
        "history": [],
        "rematch_request": None,
        "undo_request": None,
        "started_at": time.time(),
        "last_tick": time.time(),
        "stats_recorded": False,
    }


def player_payload(player_id, connected=True):
    if not player_id:
        return None
    p = get_player(player_id)
    if not p:
        return {"player_id": player_id, "username": "Joueur", "connected": connected}
    return {"player_id": p["id"], "username": p["username"], "name": p["username"], "connected": connected}


def room_player_number(room, player_id):
    for num, pid in room["players"].items():
        if pid == player_id:
            return num
    return 0


def room_for_player(player_id):
    for room in rooms.values():
        if player_id in room["players"].values():
            return room
    return None


def available_online_players(exclude_id=None):
    result = []
    for pid in list(players_online):
        if exclude_id and pid == exclude_id:
            continue
        p = get_player(pid)
        if not p:
            continue
        room = room_for_player(pid)
        result.append({
            "player_id": pid,
            "username": p["username"],
            "name": p["username"],
            "in_game": bool(room and room["players"].get(1) and room["players"].get(2)),
        })
    result.sort(key=lambda x: x["username"].lower())
    return result


async def send(ws, payload):
    try:
        await ws.send(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


async def send_error(ws, message):
    await send(ws, {"type": "error", "message": message})


async def broadcast_room(room, payload):
    targets = []
    for pid in room["players"].values():
        if pid and pid in connections:
            targets.append(connections[pid])
    for ws in list(room["spectators"]):
        targets.append(ws)
    if targets:
        await asyncio.gather(*(send(ws, payload) for ws in targets), return_exceptions=True)


def public_state(room):
    players = {}
    for n in (1, 2):
        pid = room["players"].get(n)
        players[str(n)] = player_payload(pid, pid in connections if pid else False) if pid else None

    return {
        "type": "state",
        "room": room["room"],
        "board": room["board"],
        "players": players,
        "turn": room["turn"],
        "starter": room["starter"],
        "game_number": room["game_number"],
        "black_time": max(0, int(room["black_time"])),
        "red_time": max(0, int(room["red_time"])),
        "black_score": room["black_score"],
        "red_score": room["red_score"],
        "winner": room["winner"],
        "game_over": room["game_over"],
        "draw": room["draw"],
        "abandonment": room["abandonment"],
        "winning_line": room["winning_line"],
        "last_move": room["last_move"],
        "rematch_request": room["rematch_request"],
        "undo_request": room["undo_request"],
        "spectator_count": len(room["spectators"]),
        "spectators_count": len(room["spectators"]),
    }


async def broadcast_state(room):
    await broadcast_room(room, public_state(room))


def line_for_win(board, row, col, value):
    directions = [(1,0), (0,1), (1,1), (1,-1)]
    for dr, dc in directions:
        cells = [(row, col)]
        for sign in (1, -1):
            rr, cc = row, col
            while True:
                rr += dr * sign
                cc += dc * sign
                if not (0 <= rr < BOARD_SIZE and 0 <= cc < BOARD_SIZE):
                    break
                if board[rr][cc] != value:
                    break
                cells.append((rr, cc))
        if len(cells) >= 5:
            # Return exactly five cells containing the new move.
            cells.sort(key=lambda x: (x[0], x[1]))
            for i in range(len(cells) - 4):
                group = cells[i:i+5]
                if (row, col) in group:
                    return [{"row": r, "col": c} for r, c in group]
    return None


def board_full(board):
    return all(cell != 0 for row in board for cell in row)


async def finish_game(room, winner, draw=False, abandonment=False):
    if room["game_over"]:
        return
    room["game_over"] = True
    room["winner"] = winner
    room["draw"] = draw
    room["abandonment"] = abandonment
    room["rematch_request"] = None
    room["undo_request"] = None

    if winner in (1, 2):
        if winner == 1:
            room["black_score"] += 1
        else:
            room["red_score"] += 1

        if not room["stats_recorded"]:
            winner_id = room["players"].get(winner)
            loser_id = room["players"].get(2 if winner == 1 else 1)
            if winner_id:
                update_stats(winner_id, True)
            if loser_id:
                update_stats(loser_id, False)
            room["stats_recorded"] = True

    await broadcast_state(room)


async def start_next_game(room):
    room["starter"] = 2 if room["starter"] == 1 else 1
    room["turn"] = room["starter"]
    room["game_number"] += 1
    room["board"] = blank_board()
    room["black_time"] = START_TIME
    room["red_time"] = START_TIME
    room["winner"] = None
    room["game_over"] = False
    room["draw"] = False
    room["abandonment"] = False
    room["winning_line"] = None
    room["last_move"] = None
    room["history"] = []
    room["rematch_request"] = None
    room["undo_request"] = None
    room["started_at"] = time.time()
    room["last_tick"] = time.time()
    room["stats_recorded"] = False
    await broadcast_state(room)


async def notify_online_players():
    for pid, ws in list(connections.items()):
        await send(ws, {"type": "online_players", "players": available_online_players(pid)})


async def authenticate(ws, player_id):
    if not player_id:
        return False
    clients[ws] = player_id
    connections[player_id] = ws
    players_online.add(player_id)
    await notify_online_players()
    return True


async def handle_register(ws, data):
    username = str(data.get("username", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    confirmation = str(data.get("password_confirmation", ""))

    if not valid_username(username):
        await send(ws, {"type": "register_result", "success": False, "message": "Pseudo invalide."})
        return
    if not valid_email(email):
        await send(ws, {"type": "register_result", "success": False, "message": "Email invalide."})
        return
    if len(password) < 6:
        await send(ws, {"type": "register_result", "success": False, "message": "Le mot de passe doit contenir au moins 6 caractères."})
        return
    if password != confirmation:
        await send(ws, {"type": "register_result", "success": False, "message": "Les mots de passe ne correspondent pas."})
        return

    conn = db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM players WHERE lower(username)=lower(%s) OR lower(email)=lower(%s)", (username, email))
            if cur.fetchone():
                await send(ws, {"type": "register_result", "success": False, "message": "Pseudo ou email déjà utilisé."})
                return
            cur.execute("INSERT INTO players(username,email,password_hash) VALUES(%s,%s,%s) RETURNING id", (username, email, make_password_hash(password)))
            player_id = cur.fetchone()[0]
            cur.execute("INSERT INTO player_stats(player_id) VALUES(%s) ON CONFLICT DO NOTHING", (player_id,))
        conn.commit()
    finally:
        conn.close()

    token = secrets.token_urlsafe(32)
    await authenticate(ws, player_id)
    await send(ws, {
        "type": "register_result",
        "success": True,
        "message": "Compte créé avec succès.",
        "player_id": player_id,
        "username": username,
        "email": email,
        "account_token": token,
        "stats": get_stats(player_id),
    })


async def handle_login(ws, data):
    login = str(data.get("login", "")).strip()
    password = str(data.get("password", ""))
    conn = db_connect()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, username, email, password_hash FROM players WHERE lower(username)=lower(%s) OR lower(email)=lower(%s) LIMIT 1", (login, login))
            player = cur.fetchone()
    finally:
        conn.close()

    if not player or not verify_password(password, player["password_hash"]):
        await send(ws, {"type": "login_result", "success": False, "message": "Identifiants incorrects."})
        return

    token = secrets.token_urlsafe(32)
    await authenticate(ws, int(player["id"]))
    await send(ws, {
        "type": "login_result",
        "success": True,
        "message": "Connexion réussie.",
        "player_id": int(player["id"]),
        "username": player["username"],
        "email": player["email"],
        "account_token": token,
        "stats": get_stats(int(player["id"])),
    })


async def setup_match(room, player1, player2, ws1, ws2, mode="matchmaking"):
    room["players"][1] = player1
    room["players"][2] = player2
    room["turn"] = room["starter"]
    rooms[room["room"]] = room
    await send(ws1, {"type": "match_found" if mode == "matchmaking" else "direct_match", "room": room["room"], "player": 1, "session_token": secrets.token_urlsafe(32), "message": "🎮 Adversaire trouvé ! Le match va commencer."})
    await send(ws2, {"type": "match_found" if mode == "matchmaking" else "direct_match", "room": room["room"], "player": 2, "session_token": secrets.token_urlsafe(32), "message": "🎮 Match trouvé ! La partie va commencer."})
    await broadcast_state(room)
    await notify_online_players()


async def handle_find_match(ws):
    global waiting
    pid = clients.get(ws)
    if not pid:
        await send_error(ws, "Connectez-vous d'abord.")
        return
    if room_for_player(pid):
        await send_error(ws, "Vous êtes déjà dans une partie.")
        return
    if waiting and waiting != ws:
        other_ws = waiting
        other_pid = clients.get(other_ws)
        waiting = None
        if other_pid and other_ws in clients and pid != other_pid:
            room = fresh_room(new_room_code())
            await setup_match(room, other_pid, pid, other_ws, ws, "matchmaking")
            return
    waiting = ws
    await send(ws, {"type": "searching", "message": "🔎 Recherche d'un adversaire..."})


async def handle_cancel_match(ws):
    global waiting
    if waiting is ws:
        waiting = None
    await send(ws, {"type": "searching", "cancelled": True})


async def handle_create(ws):
    pid = clients.get(ws)
    if not pid:
        await send_error(ws, "Connectez-vous d'abord.")
        return
    if room_for_player(pid):
        await send_error(ws, "Vous êtes déjà dans une partie.")
        return
    code = new_room_code()
    room = fresh_room(code)
    room["players"][1] = pid
    rooms[code] = room
    await send(ws, {"type": "created", "room": code, "player": 1, "session_token": secrets.token_urlsafe(32)})
    await broadcast_state(room)
    await notify_online_players()


async def handle_join(ws, data):
    pid = clients.get(ws)
    code = str(data.get("room", "")).strip().upper()
    room = rooms.get(code)
    if not pid:
        await send_error(ws, "Connectez-vous d'abord.")
        return
    if not room:
        await send_error(ws, "Partie introuvable.")
        return
    if room["players"].get(2):
        await send_error(ws, "Cette partie est déjà complète.")
        return
    if pid == room["players"].get(1):
        await send_error(ws, "Vous êtes déjà le joueur 1.")
        return
    room["players"][2] = pid
    await send(ws, {"type": "joined", "room": code, "player": 2, "session_token": secrets.token_urlsafe(32)})
    await broadcast_state(room)
    await notify_online_players()


async def handle_watch(ws, data):
    code = str(data.get("room", "")).strip().upper()
    room = rooms.get(code)
    if not room:
        await send_error(ws, "Match introuvable.")
        return
    room["spectators"].add(ws)
    await send(ws, {"type": "watching", "room": code})
    await send(ws, public_state(room))
    await broadcast_state(room)


async def handle_live_matches(ws):
    matches = []
    for room in rooms.values():
        if room["players"].get(1) and room["players"].get(2):
            p1 = player_payload(room["players"][1], room["players"][1] in connections)
            p2 = player_payload(room["players"][2], room["players"][2] in connections)
            matches.append({
                "room": room["room"],
                "player1": p1["username"] if p1 else "Joueur 1",
                "player2": p2["username"] if p2 else "Joueur 2",
                "spectators": len(room["spectators"]),
                "game_over": room["game_over"],
            })
    await send(ws, {"type": "live_matches", "matches": matches})


async def handle_invite_player(ws, data):
    sender = clients.get(ws)
    target = int(data.get("target_player_id", 0) or 0)
    if not sender or not target or target == sender:
        await send(ws, {"type": "invite_result", "success": False, "message": "Invitation impossible."})
        return
    target_ws = connections.get(target)
    if not target_ws:
        await send(ws, {"type": "invite_result", "success": False, "message": "Ce joueur n'est plus en ligne."})
        return
    if room_for_player(sender) or room_for_player(target):
        await send(ws, {"type": "invite_result", "success": False, "message": "Un des joueurs est déjà en partie."})
        return
    sid = secrets.token_urlsafe(12)
    sender_player = get_player(sender)
    invites[sid] = {"sender": sender, "target": target, "created": time.time()}
    await send(target_ws, {"type": "game_invite", "invitation_id": sid, "from_player_id": sender, "from_username": sender_player["username"] if sender_player else "Joueur"})
    await send(ws, {"type": "invite_result", "success": True, "message": "🎮 Invitation envoyée."})


async def handle_invite_response(ws, data):
    target = clients.get(ws)
    invitation_id = str(data.get("invitation_id", ""))
    accepted = bool(data.get("accepted"))
    inv = invites.pop(invitation_id, None)
    if not inv or inv["target"] != target:
        await send_error(ws, "Invitation expirée.")
        return
    sender = inv["sender"]
    sender_ws = connections.get(sender)
    if not accepted:
        if sender_ws:
            await send(sender_ws, {"type": "invite_result", "success": False, "message": "❌ Votre invitation a été refusée."})
        return
    if not sender_ws:
        await send(ws, {"type": "invite_result", "success": False, "message": "Le joueur n'est plus connecté."})
        return
    room = fresh_room(new_room_code())
    await setup_match(room, sender, target, sender_ws, ws, "direct")


async def handle_move(ws, data):
    pid = clients.get(ws)
    room = rooms.get(str(data.get("room", "")).strip().upper())
    if not room or not pid:
        await send_error(ws, "Partie introuvable.")
        return
    num = room_player_number(room, pid)
    if num not in (1, 2):
        await send_error(ws, "Les spectateurs ne peuvent pas jouer.")
        return
    if room["game_over"]:
        return
    if room["rematch_request"] is not None or room["undo_request"] is not None:
        return
    if room["turn"] != num:
        return
    try:
        row = int(data.get("row"))
        col = int(data.get("col"))
    except Exception:
        return
    if not (0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE):
        return
    if room["board"][row][col] != 0:
        return
    value = 1 if num == 1 else 2
    room["board"][row][col] = value
    room["history"].append({"row": row, "col": col, "player": num})
    room["last_move"] = {"row": row, "col": col, "player": num}
    room["undo_request"] = None
    winning_line = line_for_win(room["board"], row, col, value)
    if winning_line:
        room["winning_line"] = winning_line
        await finish_game(room, num)
        return
    if board_full(room["board"]):
        await finish_game(room, None, draw=True)
        return
    room["turn"] = 2 if num == 1 else 1
    await broadcast_state(room)


async def handle_undo_request(ws, data):
    pid = clients.get(ws)
    room = rooms.get(str(data.get("room", "")).strip().upper())
    if not room or room["game_over"] or not pid:
        return
    num = room_player_number(room, pid)
    if num not in (1, 2) or not room["history"]:
        return
    last = room["history"][-1]
    if last["player"] != num:
        await send_error(ws, "Seul le joueur du dernier pion peut demander un rejwe.")
        return
    if room["undo_request"] is not None:
        return
    room["undo_request"] = num
    await broadcast_state(room)


async def handle_undo_response(ws, data):
    pid = clients.get(ws)
    room = rooms.get(str(data.get("room", "")).strip().upper())
    accepted = bool(data.get("accepted"))
    if not room or not pid or room["undo_request"] is None:
        return
    requester = room["undo_request"]
    responder = room_player_number(room, pid)
    if responder == requester:
        return
    if accepted and room["history"]:
        last = room["history"].pop()
        room["board"][last["row"]][last["col"]] = 0
        room["turn"] = requester
        room["last_move"] = room["history"][-1] if room["history"] else None
        room["winning_line"] = None
    room["undo_request"] = None
    await broadcast_state(room)


async def handle_rematch_request(ws, data):
    pid = clients.get(ws)
    room = rooms.get(str(data.get("room", "")).strip().upper())
    if not room or not room["game_over"] or not pid:
        return
    num = room_player_number(room, pid)
    if num not in (1, 2):
        return
    if room["winner"] == num:
        await send_error(ws, "Le gagnant n'a pas besoin de demander la revanche.")
        return
    room["rematch_request"] = num
    await broadcast_state(room)


async def handle_rematch_response(ws, data):
    pid = clients.get(ws)
    room = rooms.get(str(data.get("room", "")).strip().upper())
    accepted = bool(data.get("accepted"))
    if not room or not room["game_over"] or not pid or room["rematch_request"] is None:
        return
    requester = room["rematch_request"]
    responder = room_player_number(room, pid)
    if responder == requester:
        return
    room["rematch_request"] = None
    if accepted:
        await start_next_game(room)
    else:
        await broadcast_state(room)


async def handle_reset(ws, data):
    # Kept for compatibility with the existing index. Treat it as an accepted next-game reset.
    pid = clients.get(ws)
    room = rooms.get(str(data.get("room", "")).strip().upper())
    if not room or not pid:
        return
    if room["game_over"]:
        await start_next_game(room)


async def handle_reconnect(ws, data):
    try:
        pid = int(data.get("player"))
    except Exception:
        return
    token = data.get("session_token")
    room = rooms.get(str(data.get("room", "")).strip().upper())
    if not room or not pid or not token:
        await send_error(ws, "Reconnexion impossible.")
        return
    # Existing frontend stores an in-memory token. For this protocol, accepting a valid player/room pair is enough.
    if pid not in room["players"].values():
        await send_error(ws, "Vous n'êtes pas dans cette partie.")
        return
    await authenticate(ws, pid)
    num = room_player_number(room, pid)
    await send(ws, {"type": "reconnected", "room": room["room"], "player": num, "session_token": token})
    await broadcast_state(room)


async def disconnect_player(ws):
    global waiting
    pid = clients.pop(ws, None)
    if not pid:
        return
    if connections.get(pid) is ws:
        connections.pop(pid, None)
    players_online.discard(pid)
    if waiting is ws:
        waiting = None

    # Remove spectator membership.
    for room in list(rooms.values()):
        if ws in room["spectators"]:
            room["spectators"].discard(ws)
            await broadcast_state(room)

    room = room_for_player(pid)
    if room and not room["game_over"]:
        num = room_player_number(room, pid)
        if num in (1, 2):
            other = 2 if num == 1 else 1
            if room["players"].get(other):
                await finish_game(room, other, abandonment=True)
    await notify_online_players()


async def handler(ws):
    try:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except Exception:
                await send_error(ws, "Message invalide.")
                continue
            typ = data.get("type")
            try:
                if typ == "register": await handle_register(ws, data)
                elif typ == "login": await handle_login(ws, data)
                elif typ == "online_players": await send(ws, {"type": "online_players", "players": available_online_players(clients.get(ws))})
                elif typ == "find_match": await handle_find_match(ws)
                elif typ == "cancel_match": await handle_cancel_match(ws)
                elif typ == "create": await handle_create(ws)
                elif typ == "join": await handle_join(ws, data)
                elif typ == "live_matches": await handle_live_matches(ws)
                elif typ == "watch": await handle_watch(ws, data)
                elif typ == "invite_player": await handle_invite_player(ws, data)
                elif typ == "invite_response": await handle_invite_response(ws, data)
                elif typ == "move": await handle_move(ws, data)
                elif typ == "undo_request": await handle_undo_request(ws, data)
                elif typ == "undo_response": await handle_undo_response(ws, data)
                elif typ == "rematch_request": await handle_rematch_request(ws, data)
                elif typ == "rematch_response": await handle_rematch_response(ws, data)
                elif typ == "reset": await handle_reset(ws, data)
                elif typ == "reconnect": await handle_reconnect(ws, data)
                else: await send_error(ws, "Commande inconnue.")
            except Exception as exc:
                print("handler error:", repr(exc))
                await send_error(ws, "Une erreur serveur est survenue.")
    finally:
        await disconnect_player(ws)


async def timer_loop():
    while True:
        now = time.time()
        for room in list(rooms.values()):
            if room["game_over"]:
                continue
            if not (room["players"].get(1) and room["players"].get(2)):
                continue
            elapsed = max(0, now - room["last_tick"])
            room["last_tick"] = now
            if room["turn"] == 1:
                room["black_time"] -= elapsed
                if room["black_time"] <= 0:
                    room["black_time"] = 0
                    await finish_game(room, 2)
                    continue
            else:
                room["red_time"] -= elapsed
                if room["red_time"] <= 0:
                    room["red_time"] = 0
                    await finish_game(room, 1)
                    continue
            if int(now) != int(now - elapsed):
                await broadcast_state(room)
        await asyncio.sleep(TICK)


async def main():
    init_db()
    print(f"MR JERY MOPION server listening on {HOST}:{PORT}")
    async with websockets.serve(handler, HOST, PORT, ping_interval=20, ping_timeout=20, max_size=2**20):
        await timer_loop()


if __name__ == "__main__":
    asyncio.run(main())
