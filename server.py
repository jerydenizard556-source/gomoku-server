import asyncio
import json
import random
import string
import time
import uuid
import os

import websockets


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 10000))

BOARD_SIZE = 20
START_TIME = 10 * 60

rooms = {}


def create_room_code():
    while True:
        code = "".join(
            random.choices(
                string.ascii_uppercase + string.digits,
                k=6
            )
        )

        if code not in rooms:
            return code


def create_session_token():
    return str(uuid.uuid4())


def create_room():
    room_code = create_room_code()

    rooms[room_code] = {
        "board": [
            [0 for _ in range(BOARD_SIZE)]
            for _ in range(BOARD_SIZE)
        ],

        "players": {},

        # 1 = Noir
        # 2 = Rouge
        "turn": 1,

        # Premier jeu: Noir kòmanse
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

        # Dènye kou a
        "last_move": None,

        # Rezilta dènye kou a te kreye
        "last_move_was_win": False,

        # Demande rejwe
        "rematch_request": None
    }

    return room_code


def check_win(board, row, col, player):
    directions = [
        (1, 0),
        (0, 1),
        (1, 1),
        (1, -1)
    ]

    for dr, dc in directions:

        count = 1

        r = row + dr
        c = col + dc

        while (
            0 <= r < BOARD_SIZE
            and 0 <= c < BOARD_SIZE
            and board[r][c] == player
        ):
            count += 1
            r += dr
            c += dc

        r = row - dr
        c = col - dc

        while (
            0 <= r < BOARD_SIZE
            and 0 <= c < BOARD_SIZE
            and board[r][c] == player
        ):
            count += 1
            r -= dr
            c -= dc

        # Egzakteman 5 sèlman
        # 6 oswa plis pa genyen
        if count == 5:
            return True

    return False


def board_is_full(board):
    for row in board:
        for cell in row:
            if cell == 0:
                return False

    return True


def update_timers(room):

    # Lè gen demann rejwe,
    # tan an rete kanpe pandan advèsè a ap reponn.
    if room["game_over"] or room["rematch_request"] is not None:
        room["last_timer_update"] = time.monotonic()
        return

    now = time.monotonic()

    elapsed = now - room["last_timer_update"]

    room["last_timer_update"] = now

    if elapsed <= 0:
        return

    if room["turn"] == 1:

        room["black_time"] -= elapsed

        if room["black_time"] <= 0:

            room["black_time"] = 0

            room["game_over"] = True
            room["winner"] = 2

            room["red_score"] += 1

    elif room["turn"] == 2:

        room["red_time"] -= elapsed

        if room["red_time"] <= 0:

            room["red_time"] = 0

            room["game_over"] = True
            room["winner"] = 1

            room["black_score"] += 1


def get_state(room):

    update_timers(room)

    rematch_request = room["rematch_request"]

    return {
        "type": "state",

        "board": room["board"],

        "turn": room["turn"],

        "starter": room["starter"],

        "black_time": max(
            0,
            room["black_time"]
        ),

        "red_time": max(
            0,
            room["red_time"]
        ),

        "game_over": room["game_over"],

        "winner": room["winner"],

        "draw": room["draw"],

        "black_score": room["black_score"],

        "red_score": room["red_score"],

        "game_number": room["game_number"],

        "last_move": room["last_move"],

        "rematch_request": rematch_request,

        "players": {
            str(player): {
                "connected": data.get(
                    "connected",
                    False
                )
            }
            for player, data in room["players"].items()
        }
    }


async def send_json(websocket, data):

    try:

        await websocket.send(
            json.dumps(data)
        )

    except Exception:

        pass


async def broadcast_state(room):

    state = get_state(room)

    for player_data in list(
        room["players"].values()
    ):

        websocket = player_data.get(
            "websocket"
        )

        connected = player_data.get(
            "connected",
            False
        )

        if websocket is not None and connected:

            await send_json(
                websocket,
                state
            )


def find_player_by_socket(websocket):

    for room_code, room in rooms.items():

        for player, data in room["players"].items():

            if data.get(
                "websocket"
            ) == websocket:

                return room_code, player

    return None, None


async def handle_create(websocket):

    room_code = create_room()

    room = rooms[room_code]

    session_token = create_session_token()

    room["players"][1] = {
        "websocket": websocket,
        "session_token": session_token,
        "connected": True
    }

    await send_json(
        websocket,
        {
            "type": "created",
            "room": room_code,
            "player": 1,
            "session_token": session_token,
            "black_score": room["black_score"],
            "red_score": room["red_score"],
            "game_number": room["game_number"],
            "starter": room["starter"]
        }
    )

    await broadcast_state(room)


async def handle_join(websocket, room_code):

    if room_code not in rooms:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Partie introuvable."
            }
        )

        return

    room = rooms[room_code]

    if 2 in room["players"]:

        player_two = room["players"][2]

        if player_two.get(
            "connected",
            False
        ):

            await send_json(
                websocket,
                {
                    "type": "error",
                    "message":
                        "Cette partie est déjà complète."
                }
            )

            return

        await send_json(
            websocket,
            {
                "type": "error",
                "message":
                    "Cette place est réservée à l'ancien joueur."
            }
        )

        return

    session_token = create_session_token()

    room["players"][2] = {
        "websocket": websocket,
        "session_token": session_token,
        "connected": True
    }

    await send_json(
        websocket,
        {
            "type": "joined",
            "room": room_code,
            "player": 2,
            "session_token": session_token,
            "black_score": room["black_score"],
            "red_score": room["red_score"],
            "game_number": room["game_number"],
            "starter": room["starter"]
        }
    )

    await broadcast_state(room)


async def handle_reconnect(
    websocket,
    room_code,
    player,
    session_token
):

    if room_code not in rooms:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Partie introuvable."
            }
        )

        return

    room = rooms[room_code]

    try:

        player = int(player)

    except Exception:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Joueur invalide."
            }
        )

        return

    if player not in room["players"]:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Session introuvable."
            }
        )

        return

    player_data = room["players"][player]

    if player_data.get(
        "session_token"
    ) != session_token:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Session invalide."
            }
        )

        return

    old_websocket = player_data.get(
        "websocket"
    )

    if (
        old_websocket is not None
        and old_websocket != websocket
    ):

        try:

            await old_websocket.close()

        except Exception:

            pass

    player_data["websocket"] = websocket
    player_data["connected"] = True

    await send_json(
        websocket,
        {
            "type": "reconnected",
            "room": room_code,
            "player": player,
            "session_token": session_token,
            "black_score":
                room["black_score"],
            "red_score":
                room["red_score"],
            "game_number":
                room["game_number"],
            "starter":
                room["starter"]
        }
    )

    await broadcast_state(room)


async def handle_move(websocket, data):

    room_code = data.get(
        "room"
    )

    if room_code not in rooms:
        return

    room = rooms[room_code]

    room_code_found, player = find_player_by_socket(
        websocket
    )

    if room_code_found != room_code:
        return

    if player is None:
        return

    # Si yon demann rejwe ap tann,
    # okenn nouvo kou pa kapab fèt.
    if room["rematch_request"] is not None:

        await send_json(
            websocket,
            {
                "type": "error",
                "message":
                    "Attendez la réponse à la demande de rejouer."
            }
        )

        return

    update_timers(room)

    if room["game_over"]:

        await send_json(
            websocket,
            {
                "type": "error",
                "message":
                    "La partie est terminée."
            }
        )

        return

    if player != room["turn"]:

        await send_json(
            websocket,
            {
                "type": "error",
                "message":
                    "Ce n'est pas votre tour."
            }
        )

        return

    try:

        row = int(
            data.get("row")
        )

        col = int(
            data.get("col")
        )

    except Exception:

        return

    if not (
        0 <= row < BOARD_SIZE
        and 0 <= col < BOARD_SIZE
    ):

        return

    if room["board"][row][col] != 0:

        await send_json(
            websocket,
            {
                "type": "error",
                "message":
                    "Cette case est déjà occupée."
            }
        )

        return

    # Enregistrer le pion
    room["board"][row][col] = player

    # Enregistrer le dernier coup
    room["last_move"] = {
        "row": row,
        "col": col,
        "player": player
    }

    room["last_move_was_win"] = False

    if check_win(
        room["board"],
        row,
        col,
        player
    ):

        room["game_over"] = True
        room["winner"] = player

        room["last_move_was_win"] = True

        if player == 1:

            room["black_score"] += 1

        else:

            room["red_score"] += 1

    elif board_is_full(
        room["board"]
    ):

        room["game_over"] = True
        room["draw"] = True
        room["winner"] = 0

    else:

        if player == 1:
            room["turn"] = 2
        else:
            room["turn"] = 1

    room["last_timer_update"] = time.monotonic()

    await broadcast_state(room)


async def handle_rematch_request(
    websocket,
    data
):

    room_code = data.get(
        "room"
    )

    if room_code not in rooms:
        return

    room = rooms[room_code]

    room_code_found, player = find_player_by_socket(
        websocket
    )

    if room_code_found != room_code:
        return

    if player is None:
        return

    # Fòk gen yon dènye kou
    if room["last_move"] is None:

        await send_json(
            websocket,
            {
                "type": "error",
                "message":
                    "Aucun coup à rejouer."
            }
        )

        return

    # Se sèlman moun ki fè dènye kou a
    # ki kapab mande rejwe.
    if room["last_move"]["player"] != player:

        await send_json(
            websocket,
            {
                "type": "error",
                "message":
                    "Seul le joueur qui vient de jouer peut demander à rejouer."
            }
        )

        return

    # Pa gen 2 demann an menm tan
    if room["rematch_request"] is not None:

        await send_json(
            websocket,
            {
                "type": "error",
                "message":
                    "Une demande de rejouer est déjà en attente."
            }
        )

        return

    room["rematch_request"] = player

    # Timer la kanpe
    room["last_timer_update"] = time.monotonic()

    await broadcast_state(room)


async def handle_rematch_response(
    websocket,
    data
):

    room_code = data.get(
        "room"
    )

    if room_code not in rooms:
        return

    room = rooms[room_code]

    room_code_found, player = find_player_by_socket(
        websocket
    )

    if room_code_found != room_code:
        return

    if player is None:
        return

    requester = room["rematch_request"]

    if requester is None:

        await send_json(
            websocket,
            {
                "type": "error",
                "message":
                    "Aucune demande de rejouer."
            }
        )

        return

    # Moun ki mande a pa kapab aksepte/refize
    if player == requester:

        await send_json(
            websocket,
            {
                "type": "error",
                "message":
                    "L'adversaire doit répondre à la demande."
            }
        )

        return

    accepted = bool(
        data.get("accepted", False)
    )

    if not accepted:

        # Refize
        room["rematch_request"] = None
        room["last_timer_update"] = time.monotonic()

        await broadcast_state(room)

        return

    # ACCEPTÉ
    last_move = room["last_move"]

    if last_move is None:

        room["rematch_request"] = None

        await broadcast_state(room)

        return

    row = last_move["row"]
    col = last_move["col"]
    last_player = last_move["player"]

    # Retire dènye pion an
    room["board"][row][col] = 0

    # Si dènye kou a te bay viktwa,
    # retire pwen li te pran an.
    if room["last_move_was_win"]:

        if last_player == 1:

            if room["black_score"] > 0:
                room["black_score"] -= 1

        else:

            if room["red_score"] > 0:
                room["red_score"] -= 1

    # Jwèt la tounen nan eta anvan dènye kou a
    room["game_over"] = False
    room["winner"] = 0
    room["draw"] = False

    # Se moun ki te mande rejwe a ki jwenn tou li ankò.
    room["turn"] = last_player

    room["last_move"] = None
    room["last_move_was_win"] = False
    room["rematch_request"] = None

    room["last_timer_update"] = time.monotonic()

    await broadcast_state(room)


async def handle_reset(websocket, data):

    room_code = data.get(
        "room"
    )

    if room_code not in rooms:
        return

    room = rooms[room_code]

    room_code_found, player = find_player_by_socket(
        websocket
    )

    if room_code_found != room_code:
        return

    if player is None:
        return

    # Si pati a fini, starter la chanje.
    # 1 = Noir
    # 2 = Rouge
    #
    # Game 1 = Noir
    # Game 2 = Rouge
    # Game 3 = Noir
    # Game 4 = Rouge

    if room["game_over"]:

        if room["starter"] == 1:
            room["starter"] = 2
        else:
            room["starter"] = 1

        room["game_number"] += 1

    room["board"] = [
        [0 for _ in range(BOARD_SIZE)]
        for _ in range(BOARD_SIZE)
    ]

    room["turn"] = room["starter"]

    room["black_time"] = START_TIME
    room["red_time"] = START_TIME

    room["last_timer_update"] = time.monotonic()

    room["game_over"] = False
    room["winner"] = 0
    room["draw"] = False

    room["last_move"] = None
    room["last_move_was_win"] = False

    room["rematch_request"] = None

    # Score yo pa efase.

    await broadcast_state(room)


async def mark_disconnected(websocket):

    room_code, player = find_player_by_socket(
        websocket
    )

    if room_code is None:
        return

    room = rooms[room_code]

    if player not in room["players"]:
        return

    player_data = room["players"][player]

    if player_data.get(
        "websocket"
    ) == websocket:

        player_data["connected"] = False


async def timer_loop():

    while True:

        await asyncio.sleep(0.5)

        for room in list(
            rooms.values()
        ):

            if room["game_over"]:
                continue

            if room["rematch_request"] is not None:
                continue

            before_black = room["black_time"]
            before_red = room["red_time"]
            before_game_over = room["game_over"]

            update_timers(room)

            changed = (
                int(before_black)
                != int(room["black_time"])
                or
                int(before_red)
                != int(room["red_time"])
                or
                before_game_over
                != room["game_over"]
            )

            if changed:

                await broadcast_state(room)


async def client_handler(websocket):

    try:

        async for message in websocket:

            try:

                data = json.loads(
                    message
                )

            except Exception:

                await send_json(
                    websocket,
                    {
                        "type": "error",
                        "message":
                            "Message invalide."
                    }
                )

                continue

            message_type = data.get(
                "type"
            )

            if message_type == "create":

                await handle_create(
                    websocket
                )

            elif message_type == "join":

                room_code = str(
                    data.get(
                        "room",
                        ""
                    )
                ).upper()

                await handle_join(
                    websocket,
                    room_code
                )

            elif message_type == "reconnect":

                room_code = str(
                    data.get(
                        "room",
                        ""
                    )
                ).upper()

                player = data.get(
                    "player"
                )

                session_token = data.get(
                    "session_token"
                )

                await handle_reconnect(
                    websocket,
                    room_code,
                    player,
                    session_token
                )

            elif message_type == "move":

                await handle_move(
                    websocket,
                    data
                )

            elif message_type == "rematch_request":

                await handle_rematch_request(
                    websocket,
                    data
                )

            elif message_type == "rematch_response":

                await handle_rematch_response(
                    websocket,
                    data
                )

            elif message_type == "reset":

                await handle_reset(
                    websocket,
                    data
                )

            else:

                await send_json(
                    websocket,
                    {
                        "type": "error",
                        "message":
                            "Commande inconnue."
                    }
                )

    except websockets.exceptions.ConnectionClosed:
        pass

    except Exception as error:

        print(
            "Erreur:",
            error
        )

    finally:

        await mark_disconnected(
            websocket
        )


async def main():

    print(
        f"Gomoku server starting on {HOST}:{PORT}"
    )

    asyncio.create_task(
        timer_loop()
    )

    async with websockets.serve(
        client_handler,
        HOST,
        PORT
    ):

        print(
            "Gomoku server is running."
        )

        await asyncio.Future()


if __name__ == "__main__":

    asyncio.run(
        main()
    )
