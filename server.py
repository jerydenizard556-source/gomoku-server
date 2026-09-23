import asyncio
import json
import secrets
import string
import time
import websockets

HOST = "0.0.0.0"
PORT = 10000

BOARD_SIZE = 20
START_TIME = 10 * 60

rooms = {}
matchmaking_queue = []


def create_room_code():
    while True:
        code = "".join(
            secrets.choice(
                string.ascii_uppercase + string.digits
            )
            for _ in range(6)
        )

        if code not in rooms:
            return code


def create_session_token():
    return secrets.token_urlsafe(32)


def new_room():
    code = create_room_code()

    rooms[code] = {
        "board": [
            [0 for _ in range(BOARD_SIZE)]
            for _ in range(BOARD_SIZE)
        ],

        "players": {},

        "turn": 1,
        "starter": 1,

        "black_time": START_TIME,
        "red_time": START_TIME,

        "last_timer_update": time.monotonic(),

        "game_over": False,
        "winner": 0,
        "draw": False,

        "black_score": 0,
        "red_score": 0,

        "game_number": 1,

        "last_move": None,
        "last_move_was_win": False,

        "winning_line": None,

        "rematch_request": None,
    }

    return code


def create_match_room(websocket1, websocket2):
    code = create_room_code()

    rooms[code] = {
        "board": [
            [0 for _ in range(BOARD_SIZE)]
            for _ in range(BOARD_SIZE)
        ],

        "players": {
            1: {
                "socket": websocket1,
                "connected": True,
                "session_token": create_session_token(),
                "room": code,
            },

            2: {
                "socket": websocket2,
                "connected": True,
                "session_token": create_session_token(),
                "room": code,
            },
        },

        "turn": 1,
        "starter": 1,

        "black_time": START_TIME,
        "red_time": START_TIME,

        "last_timer_update": time.monotonic(),

        "game_over": False,
        "winner": 0,
        "draw": False,

        "black_score": 0,
        "red_score": 0,

        "game_number": 1,

        "last_move": None,
        "last_move_was_win": False,

        "winning_line": None,

        "rematch_request": None,
    }

    print(
        f"ROOM ONLINE CREATED: {code}"
    )

    return code


def get_winning_line(board, row, col, player):
    directions = [
        (0, 1),
        (1, 0),
        (1, 1),
        (1, -1),
    ]

    for dr, dc in directions:

        line = [(row, col)]

        r = row - dr
        c = col - dc

        while (
            0 <= r < BOARD_SIZE
            and 0 <= c < BOARD_SIZE
            and board[r][c] == player
        ):
            line.insert(
                0,
                (r, c)
            )

            r -= dr
            c -= dc

        r = row + dr
        c = col + dc

        while (
            0 <= r < BOARD_SIZE
            and 0 <= c < BOARD_SIZE
            and board[r][c] == player
        ):
            line.append(
                (r, c)
            )

            r += dr
            c += dc

        # EXACTEMENT 5
        if len(line) == 5:
            return line

    return None


def board_is_full(board):
    for row in board:
        if 0 in row:
            return False

    return True


def update_timers(room):
    if room["game_over"]:
        room["last_timer_update"] = time.monotonic()
        return

    if room["rematch_request"] is not None:
        room["last_timer_update"] = time.monotonic()
        return

    now = time.monotonic()

    elapsed = (
        now -
        room["last_timer_update"]
    )

    if elapsed <= 0:
        return

    room["last_timer_update"] = now

    if room["turn"] == 1:

        room["black_time"] = max(
            0,
            room["black_time"] - elapsed
        )

        if room["black_time"] <= 0:

            room["black_time"] = 0

            room["game_over"] = True
            room["winner"] = 2
            room["draw"] = False

            room["winning_line"] = None

            room["red_score"] += 1

    else:

        room["red_time"] = max(
            0,
            room["red_time"] - elapsed
        )

        if room["red_time"] <= 0:

            room["red_time"] = 0

            room["game_over"] = True
            room["winner"] = 1
            room["draw"] = False

            room["winning_line"] = None

            room["black_score"] += 1


def get_state(room):
    update_timers(room)

    return {
        "type": "state",

        "board": room["board"],

        "turn": room["turn"],
        "starter": room["starter"],

        "black_time": room["black_time"],
        "red_time": room["red_time"],

        "game_over": room["game_over"],
        "winner": room["winner"],
        "draw": room["draw"],

        "black_score": room["black_score"],
        "red_score": room["red_score"],

        "game_number": room["game_number"],

        "last_move": room["last_move"],
        "last_move_was_win": room["last_move_was_win"],

        "winning_line": room["winning_line"],

        "rematch_request": room["rematch_request"],

        "players": {
            "1": {
                "connected": room["players"].get(
                    1,
                    {}
                ).get(
                    "connected",
                    False
                )
            },

            "2": {
                "connected": room["players"].get(
                    2,
                    {}
                ).get(
                    "connected",
                    False
                )
            },
        },
    }


async def send_json(websocket, data):
    try:

        await websocket.send(
            json.dumps(data)
        )

    except Exception as e:

        print(
            "SEND ERROR:",
            repr(e)
        )


async def broadcast_state(room):
    state = get_state(room)

    for player_data in room["players"].values():

        websocket = player_data.get(
            "socket"
        )

        if websocket is not None:

            await send_json(
                websocket,
                state
            )


def find_player_by_socket(room, websocket):
    for player, data in room["players"].items():

        if data.get("socket") == websocket:
            return player

    return None


async def handle_create(websocket):

    room_code = new_room()

    room = rooms[room_code]

    token = create_session_token()

    room["players"][1] = {
        "socket": websocket,
        "connected": True,
        "session_token": token,
        "room": room_code,
    }

    print(
        f"ROOM CREATED: {room_code}"
    )

    await send_json(
        websocket,
        {
            "type": "created",

            "room": room_code,

            "player": 1,

            "session_token": token,
        }
    )

    await broadcast_state(room)


async def handle_join(websocket, room_code):

    room_code = str(
        room_code
    ).upper().strip()

    if room_code not in rooms:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Room introuvable.",
            }
        )

        return

    room = rooms[room_code]

    if 2 in room["players"]:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Room sa deja gen 2 jwè.",
            }
        )

        return

    token = create_session_token()

    room["players"][2] = {
        "socket": websocket,
        "connected": True,
        "session_token": token,
        "room": room_code,
    }

    print(
        f"PLAYER 2 JOINED ROOM: {room_code}"
    )

    await send_json(
        websocket,
        {
            "type": "joined",

            "room": room_code,

            "player": 2,

            "session_token": token,
        }
    )

    await broadcast_state(room)


async def handle_find_match(websocket):

    # Retire doublon
    matchmaking_queue[:] = [
        item
        for item in matchmaking_queue
        if item["socket"] is not websocket
    ]

    # Si gen yon lòt jwè k ap tann
    if matchmaking_queue:

        opponent = matchmaking_queue.pop(0)

        websocket2 = opponent["socket"]

        room_code = create_match_room(
            websocket2,
            websocket
        )

        room = rooms[room_code]

        player1_token = (
            room["players"][1]["session_token"]
        )

        player2_token = (
            room["players"][2]["session_token"]
        )

        print(
            f"MATCH FOUND: {room_code}"
        )

        await send_json(
            websocket2,
            {
                "type": "match_found",

                "room": room_code,

                "player": 1,

                "session_token": player1_token,
            }
        )

        await send_json(
            websocket,
            {
                "type": "match_found",

                "room": room_code,

                "player": 2,

                "session_token": player2_token,
            }
        )

        await broadcast_state(room)

    else:

        matchmaking_queue.append(
            {
                "socket": websocket
            }
        )

        print(
            "PLAYER ADDED TO MATCHMAKING QUEUE"
        )

        await send_json(
            websocket,
            {
                "type": "searching",

                "message": "Ap chèche yon adversè...",
            }
        )


async def handle_cancel_match(websocket):

    matchmaking_queue[:] = [
        item
        for item in matchmaking_queue
        if item["socket"] is not websocket
    ]

    print(
        "MATCHMAKING CANCELLED"
    )

    await send_json(
        websocket,
        {
            "type": "match_cancelled"
        }
    )


async def handle_reconnect(
    websocket,
    room_code,
    player,
    session_token
):

    room_code = str(
        room_code
    ).upper().strip()

    try:

        player = int(player)

    except Exception:

        return

    if room_code not in rooms:

        await send_json(
            websocket,
            {
                "type": "error",

                "message": "Room pa egziste.",
            }
        )

        return

    room = rooms[room_code]

    if player not in room["players"]:
        return

    player_data = room["players"][player]

    if (
        player_data.get(
            "session_token"
        )
        != session_token
    ):

        await send_json(
            websocket,
            {
                "type": "error",

                "message": "Session token invalid.",
            }
        )

        return

    player_data["socket"] = websocket
    player_data["connected"] = True

    print(
        f"PLAYER RECONNECTED: room={room_code} player={player}"
    )

    await send_json(
        websocket,
        {
            "type": "reconnected",

            "room": room_code,

            "player": player,

            "session_token": session_token,
        }
    )

    await broadcast_state(room)


async def handle_move(
    websocket,
    room_code,
    row,
    col
):

    room_code = str(
        room_code
    ).upper().strip()

    if room_code not in rooms:
        return

    room = rooms[room_code]

    player = find_player_by_socket(
        room,
        websocket
    )

    if player is None:

        print(
            "MOVE REFUSED: player not found"
        )

        return

    if room["game_over"]:

        print(
            "MOVE REFUSED: game already over"
        )

        return

    if room["rematch_request"] is not None:

        print(
            "MOVE REFUSED: rematch pending"
        )

        return

    if player != room["turn"]:

        print(
            f"MOVE REFUSED: wrong turn "
            f"player={player} "
            f"turn={room['turn']}"
        )

        return

    try:

        row = int(row)
        col = int(col)

    except Exception:

        print(
            "MOVE REFUSED: invalid coordinates"
        )

        return

    if not (
        0 <= row < BOARD_SIZE
        and
        0 <= col < BOARD_SIZE
    ):

        print(
            f"MOVE REFUSED: coordinates "
            f"row={row} col={col}"
        )

        return

    if room["board"][row][col] != 0:

        print(
            f"MOVE REFUSED: cell occupied "
            f"row={row} col={col}"
        )

        return

    # IMPORTANT:
    # Men sa a server la resevwa mouvman an.
    print(
        f"MOVE RECU: "
        f"room={room_code} "
        f"player={player} "
        f"row={row} "
        f"col={col}"
    )

    update_timers(room)

    if room["game_over"]:

        await broadcast_state(room)

        return

    # Mete pion an
    room["board"][row][col] = player

    room["last_move"] = {
        "row": row,
        "col": col,
        "player": player,
    }

    room["last_move_was_win"] = False

    room["winning_line"] = None

    winning_line = get_winning_line(
        room["board"],
        row,
        col,
        player
    )

    if winning_line is not None:

        room["game_over"] = True

        room["winner"] = player

        room["draw"] = False

        room["winning_line"] = [
            {
                "row": r,
                "col": c,
            }
            for r, c in winning_line
        ]

        room["last_move_was_win"] = True

        if player == 1:

            room["black_score"] += 1

        else:

            room["red_score"] += 1

        print(
            f"WIN: room={room_code} "
            f"player={player}"
        )

    elif board_is_full(
        room["board"]
    ):

        room["game_over"] = True

        room["winner"] = 0

        room["draw"] = True

        print(
            f"DRAW: room={room_code}"
        )

    else:

        room["turn"] = (
            2
            if player == 1
            else 1
        )

    room["last_timer_update"] = (
        time.monotonic()
    )

    await broadcast_state(room)


async def handle_rematch_request(
    websocket,
    room_code
):

    room_code = str(
        room_code
    ).upper().strip()

    if room_code not in rooms:
        return

    room = rooms[room_code]

    player = find_player_by_socket(
        room,
        websocket
    )

    if player is None:
        return

    if room["last_move"] is None:
        return

    if room["rematch_request"] is not None:
        return

    last_player = (
        room["last_move"]["player"]
    )

    if player != last_player:
        return

    room["rematch_request"] = player

    room["last_timer_update"] = (
        time.monotonic()
    )

    print(
        f"REMATCH REQUEST: "
        f"room={room_code} "
        f"player={player}"
    )

    await broadcast_state(room)


async def handle_rematch_response(
    websocket,
    room_code,
    accepted
):

    room_code = str(
        room_code
    ).upper().strip()

    if room_code not in rooms:
        return

    room = rooms[room_code]

    player = find_player_by_socket(
        room,
        websocket
    )

    if player is None:
        return

    requester = room["rematch_request"]

    if requester is None:
        return

    if player == requester:
        return

    if accepted:

        last_move = room["last_move"]

        if last_move is not None:

            row = last_move["row"]

            col = last_move["col"]

            last_player = (
                last_move["player"]
            )

            room["board"][row][col] = 0

            if room["last_move_was_win"]:

                if last_player == 1:

                    room["black_score"] = max(
                        0,
                        room["black_score"] - 1
                    )

                else:

                    room["red_score"] = max(
                        0,
                        room["red_score"] - 1
                    )

            room["game_over"] = False

            room["winner"] = 0

            room["draw"] = False

            room["winning_line"] = None

            room["turn"] = last_player

            room["last_move"] = None

            room["last_move_was_win"] = False

            print(
                f"REMATCH ACCEPTED: "
                f"room={room_code}"
            )

    else:

        print(
            f"REMATCH REFUSED: "
            f"room={room_code}"
        )

    room["rematch_request"] = None

    room["last_timer_update"] = (
        time.monotonic()
    )

    await broadcast_state(room)


async def handle_reset(
    websocket,
    room_code
):

    room_code = str(
        room_code
    ).upper().strip()

    if room_code not in rooms:
        return

    room = rooms[room_code]

    player = find_player_by_socket(
        room,
        websocket
    )

    if player is None:
        return

    if not room["game_over"]:
        return

    room["starter"] = (
        2
        if room["starter"] == 1
        else 1
    )

    room["turn"] = room["starter"]

    room["game_number"] += 1

    room["board"] = [
        [0 for _ in range(BOARD_SIZE)]
        for _ in range(BOARD_SIZE)
    ]

    room["black_time"] = START_TIME

    room["red_time"] = START_TIME

    room["last_timer_update"] = (
        time.monotonic()
    )

    room["game_over"] = False

    room["winner"] = 0

    room["draw"] = False

    room["last_move"] = None

    room["last_move_was_win"] = False

    room["winning_line"] = None

    room["rematch_request"] = None

    print(
        f"NEW GAME: "
        f"room={room_code} "
        f"game={room['game_number']} "
        f"starter={room['starter']}"
    )

    await broadcast_state(room)


async def mark_disconnected(websocket):

    # Retire nan matchmaking queue
    matchmaking_queue[:] = [
        item
        for item in matchmaking_queue
        if item["socket"] is not websocket
    ]

    for room in list(
        rooms.values()
    ):

        player = find_player_by_socket(
            room,
            websocket
        )

        if player is not None:

            room["players"][player][
                "connected"
            ] = False

            room["players"][player][
                "socket"
            ] = None

            print(
                f"PLAYER DISCONNECTED: "
                f"room={room.get('players', {}).get(player, {}).get('room')} "
                f"player={player}"
            )

            await broadcast_state(room)

            return


async def timer_loop():

    while True:

        await asyncio.sleep(1)

        for room in list(
            rooms.values()
        ):

            if room["game_over"]:
                continue

            if room["rematch_request"] is not None:
                continue

            old_black = room["black_time"]

            old_red = room["red_time"]

            old_over = room["game_over"]

            update_timers(room)

            changed = (
                old_black
                != room["black_time"]
                or
                old_red
                != room["red_time"]
                or
                old_over
                != room["game_over"]
            )

            if changed:

                await broadcast_state(room)


async def client_handler(websocket):

    print(
        "NEW CLIENT CONNECTED"
    )

    try:

        async for message in websocket:

            print(
                "MESSAGE RECEIVED:",
                message
            )

            try:

                data = json.loads(
                    message
                )

            except Exception:

                await send_json(
                    websocket,
                    {
                        "type": "error",

                        "message": "JSON invalid.",
                    }
                )

                continue

            message_type = data.get(
                "type"
            )

            print(
                "MESSAGE TYPE:",
                message_type
            )

            if message_type == "create":

                await handle_create(
                    websocket
                )

            elif message_type == "join":

                await handle_join(
                    websocket,
                    data.get(
                        "room",
                        ""
                    )
                )

            elif message_type == "find_match":

                await handle_find_match(
                    websocket
                )

            elif message_type == "cancel_match":

                await handle_cancel_match(
                    websocket
                )

            elif message_type == "reconnect":

                await handle_reconnect(
                    websocket,

                    data.get(
                        "room",
                        ""
                    ),

                    data.get(
                        "player"
                    ),

                    data.get(
                        "session_token",
                        ""
                    )
                )

            elif message_type == "move":

                await handle_move(
                    websocket,

                    data.get(
                        "room",
                        ""
                    ),

                    data.get(
                        "row"
                    ),

                    data.get(
                        "col"
                    )
                )

            elif message_type == "rematch_request":

                await handle_rematch_request(
                    websocket,

                    data.get(
                        "room",
                        ""
                    )
                )

            elif message_type == "rematch_response":

                await handle_rematch_response(
                    websocket,

                    data.get(
                        "room",
                        ""
                    ),

                    bool(
                        data.get(
                            "accepted",
                            False
                        )
                    )
                )

            elif message_type == "reset":

                await handle_reset(
                    websocket,

                    data.get(
                        "room",
                        ""
                    )
                )

            else:

                await send_json(
                    websocket,
                    {
                        "type": "error",

                        "message": (
                            "Type de message inconnu."
                        ),
                    }
                )

    except websockets.exceptions.ConnectionClosed:

        print(
            "CLIENT DISCONNECTED"
        )

    except Exception as e:

        print(
            "ERREUR CLIENT:",
            repr(e)
        )

    finally:

        await mark_disconnected(
            websocket
        )


async def main():

    print(
        f"Serveur Gomoku lancé sur "
        f"{HOST}:{PORT}"
    )

    asyncio.create_task(
        timer_loop()
    )

    async with websockets.serve(
        client_handler,

        HOST,

        PORT,

        ping_interval=20,

        ping_timeout=20
    ):

        print(
            "WebSocket server prêt."
        )

        await asyncio.Future()


if __name__ == "__main__":

    asyncio.run(
        main()
    )
