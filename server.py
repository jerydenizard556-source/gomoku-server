import asyncio
import json
import random
import string
import time
import uuid

import websockets


# =========================================================
# CONFIGURATION
# =========================================================

HOST = "0.0.0.0"
PORT = 10000

BOARD_SIZE = 20
START_TIME = 10 * 60

rooms = {}


# =========================================================
# UTILITAIRES
# =========================================================

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
    return uuid.uuid4().hex


def make_key(row, col):
    return f"{row},{col}"


def valid_position(row, col):
    return (
        isinstance(row, int)
        and isinstance(col, int)
        and 0 <= row < BOARD_SIZE
        and 0 <= col < BOARD_SIZE
    )


# =========================================================
# EXACTEMENT 5
# =========================================================

def check_win(board, row, col, color):
    directions = [
        (1, 0),
        (0, 1),
        (1, 1),
        (1, -1)
    ]

    for dr, dc in directions:

        start_row = row
        start_col = col

        end_row = row
        end_col = col

        # -------------------------------------------------
        # Chercher le début de la ligne
        # -------------------------------------------------

        while True:

            next_row = start_row - dr
            next_col = start_col - dc

            if not valid_position(
                next_row,
                next_col
            ):
                break

            if board.get(
                make_key(
                    next_row,
                    next_col
                )
            ) != color:
                break

            start_row = next_row
            start_col = next_col

        # -------------------------------------------------
        # Chercher la fin de la ligne
        # -------------------------------------------------

        while True:

            next_row = end_row + dr
            next_col = end_col + dc

            if not valid_position(
                next_row,
                next_col
            ):
                break

            if board.get(
                make_key(
                    next_row,
                    next_col
                )
            ) != color:
                break

            end_row = next_row
            end_col = next_col

        # -------------------------------------------------
        # Longueur exacte
        # -------------------------------------------------

        run_length = (
            max(
                abs(end_row - start_row),
                abs(end_col - start_col)
            ) + 1
        )

        # IMPORTANT :
        # 5 exactement = victoire
        # 6 ou plus = PAS victoire

        if run_length != 5:
            continue

        # Vérifier qu'il n'y a pas le même pion
        # juste avant ou juste après.

        before_row = start_row - dr
        before_col = start_col - dc

        after_row = end_row + dr
        after_col = end_col + dc

        before_same = False
        after_same = False

        if valid_position(
            before_row,
            before_col
        ):
            before_same = (
                board.get(
                    make_key(
                        before_row,
                        before_col
                    )
                ) == color
            )

        if valid_position(
            after_row,
            after_col
        ):
            after_same = (
                board.get(
                    make_key(
                        after_row,
                        after_col
                    )
                ) == color
            )

        if not before_same and not after_same:
            return True

    return False


# =========================================================
# CREER ET REINITIALISER UNE PARTIE
# =========================================================

def new_game_state(room):
    room["board"] = {}

    room["turn"] = 1

    room["winner"] = None
    room["game_over"] = False
    room["draw"] = False

    room["black_time"] = float(START_TIME)
    room["red_time"] = float(START_TIME)

    room["last_update"] = time.monotonic()

    room["game_number"] += 1


# =========================================================
# TIMER SERVEUR
# =========================================================

def update_timer(room):
    if room["game_over"]:
        room["last_update"] = time.monotonic()
        return

    now = time.monotonic()

    elapsed = now - room["last_update"]

    if elapsed <= 0:
        return

    room["last_update"] = now

    if room["turn"] == 1:
        room["black_time"] = max(
            0,
            room["black_time"] - elapsed
        )

        if room["black_time"] <= 0:
            room["black_time"] = 0
            room["winner"] = 2
            room["game_over"] = True

            room["red_score"] += 1

    elif room["turn"] == 2:
        room["red_time"] = max(
            0,
            room["red_time"] - elapsed
        )

        if room["red_time"] <= 0:
            room["red_time"] = 0
            room["winner"] = 1
            room["game_over"] = True

            room["black_score"] += 1


# =========================================================
# ETAT DE LA PARTIE
# =========================================================

def get_state(room):
    update_timer(room)

    return {
        "type": "state",

        "board": room["board"],

        "turn": room["turn"],

        "winner": room["winner"],

        "game_over": room["game_over"],

        "draw": room["draw"],

        "black_time": room["black_time"],

        "red_time": room["red_time"],

        "black_score": room["black_score"],

        "red_score": room["red_score"],

        "game_number": room["game_number"]
    }


# =========================================================
# ENVOYER UN MESSAGE A UN JOUEUR
# =========================================================

async def send_json(websocket, data):
    try:
        await websocket.send(
            json.dumps(data)
        )
    except Exception:
        pass


# =========================================================
# ENVOYER L'ETAT A TOUT LE MONDE
# =========================================================

async def broadcast_state(room):
    state = get_state(room)

    players = list(
        room["players"].items()
    )

    for player_number, player_data in players:

        websocket = player_data.get(
            "websocket"
        )

        if websocket is None:
            continue

        await send_json(
            websocket,
            state
        )


# =========================================================
# TROUVER UN JOUEUR PAR WEBSOCKET
# =========================================================

def find_player_by_socket(room, websocket):

    for player_number, player_data in room["players"].items():

        if player_data.get("websocket") is websocket:
            return player_number

    return None


# =========================================================
# CREER UNE PARTIE
# =========================================================

async def handle_create(websocket):

    room_code = create_room_code()

    session_token = create_session_token()

    rooms[room_code] = {
        "board": {},

        "turn": 1,

        "winner": None,
        "game_over": False,
        "draw": False,

        "black_time": float(START_TIME),
        "red_time": float(START_TIME),

        "black_score": 0,
        "red_score": 0,

        "game_number": 1,

        "last_update": time.monotonic(),

        "players": {
            1: {
                "websocket": websocket,
                "session_token": session_token,
                "connected": True
            }
        }
    }

    await send_json(
        websocket,
        {
            "type": "created",

            "room": room_code,

            "player": 1,

            "session_token": session_token,

            "black_score": 0,

            "red_score": 0,

            "game_number": 1
        }
    )

    await broadcast_state(
        rooms[room_code]
    )


# =========================================================
# REJOINDRE UNE PARTIE
# =========================================================

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

    # Chercher joueur 2

    if 2 in room["players"]:

        player_two =
            room["players"][2]

        if player_two.get(
            "connected",
            False
        ):

            await send_json(
                websocket,
                {
                    "type": "error",
                    "message": "Cette partie est déjà complète."
                }
            )

            return

        # Si joueur 2 existait mais était déconnecté,
        # il reste réservé à son token.
        # Un nouveau téléphone ne doit pas prendre sa place.

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Cette place est réservée à l'ancien joueur."
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

            "game_number": room["game_number"]
        }
    )

    await broadcast_state(room)


# =========================================================
# RECONNEXION
# =========================================================

async def handle_reconnect(
    websocket,
    room_code,
    session_token,
    mode
):

    if room_code not in rooms:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "La partie n'existe plus."
            }
        )

        return False

    room = rooms[room_code]

    found_player = None

    for player_number, player_data in room["players"].items():

        if (
            player_data.get(
                "session_token"
            ) == session_token
        ):

            found_player = player_number
            break

    if found_player is None:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Session de joueur invalide."
            }
        )

        return False

    # Remplacer l'ancien websocket
    room["players"][found_player]["websocket"] = websocket

    room["players"][found_player]["connected"] = True

    await send_json(
        websocket,
        {
            "type": "reconnected",

            "room": room_code,

            "player": found_player,

            "session_token": session_token,

            "black_score": room["black_score"],

            "red_score": room["red_score"],

            "game_number": room["game_number"]
        }
    )

    await broadcast_state(room)

    return True


# =========================================================
# JOUER UN COUP
# =========================================================

async def handle_move(
    room,
    websocket,
    row,
    col
):

    update_timer(room)

    if room["game_over"]:
        await send_json(
            websocket,
            {
                "type": "error",
                "message": "La partie est terminée."
            }
        )

        return

    player = find_player_by_socket(
        room,
        websocket
    )

    if player is None:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Joueur non reconnu."
            }
        )

        return

    if player != room["turn"]:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Ce n'est pas votre tour."
            }
        )

        return

    if not valid_position(row, col):

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Position invalide."
            }
        )

        return

    key = make_key(row, col)

    if key in room["board"]:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Cette case est déjà occupée."
            }
        )

        return

    color = (
        "black"
        if player == 1
        else "red"
    )

    room["board"][key] = color

    # -----------------------------------------------------
    # VERIFICATION EXACTEMENT 5
    # -----------------------------------------------------

    if check_win(
        room["board"],
        row,
        col,
        color
    ):

        room["winner"] = player

        room["game_over"] = True

        if player == 1:
            room["black_score"] += 1
        else:
            room["red_score"] += 1

        await broadcast_state(room)

        return

    # -----------------------------------------------------
    # MATCH NUL
    # -----------------------------------------------------

    if len(room["board"]) >= BOARD_SIZE * BOARD_SIZE:

        room["draw"] = True

        room["game_over"] = True

        await broadcast_state(room)

        return

    # -----------------------------------------------------
    # CHANGER DE TOUR
    # -----------------------------------------------------

    room["turn"] = (
        2
        if room["turn"] == 1
        else 1
    )

    room["last_update"] = time.monotonic()

    await broadcast_state(room)


# =========================================================
# NOUVELLE PARTIE
# =========================================================

async def handle_reset(
    room,
    websocket
):

    update_timer(room)

    player = find_player_by_socket(
        room,
        websocket
    )

    if player is None:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Joueur non reconnu."
            }
        )

        return

    # Une nouvelle partie ne doit pas être lancée
    # avant que les deux joueurs soient présents.

    connected_players = 0

    for player_data in room["players"].values():

        if player_data.get(
            "connected",
            False
        ):
            connected_players += 1

    if connected_players < 2:

        await send_json(
            websocket,
            {
                "type": "error",
                "message": "Le deuxième joueur doit être connecté."
            }
        )

        return

    new_game_state(room)

    await broadcast_state(room)


# =========================================================
# DECONNEXION
# =========================================================

def mark_disconnected(room, websocket):

    player = find_player_by_socket(
        room,
        websocket
    )

    if player is None:
        return

    room["players"][player]["websocket"] = None

    room["players"][player]["connected"] = False


# =========================================================
# BOUCLE TIMER
# =========================================================

async def timer_loop():

    while True:

        await asyncio.sleep(0.5)

        empty_rooms = []

        for room_code, room in list(
            rooms.items()
        ):

            update_timer(room)

            # Envoyer l'état régulièrement
            # afin que les deux appareils restent synchronisés.

            if room["players"]:

                await broadcast_state(room)

            # -------------------------------------------------
            # Supprimer une room uniquement si aucun joueur
            # n'est connecté ET qu'aucune session active
            # n'est encore présente.
            #
            # Pour permettre la reconnexion, on conserve
            # la room pendant un certain temps.
            # -------------------------------------------------

            connected = any(
                player_data.get(
                    "connected",
                    False
                )
                for player_data
                in room["players"].values()
            )

            if not connected:

                empty_rooms.append(
                    room_code
                )

        # On ne supprime pas immédiatement les rooms ici.
        # Les sessions sont conservées afin de permettre
        # une reconnexion.


# =========================================================
# GESTION CLIENT
# =========================================================

async def client_handler(websocket):

    current_room = None

    try:

        async for message in websocket:

            try:

                data = json.loads(message)

            except json.JSONDecodeError:

                await send_json(
                    websocket,
                    {
                        "type": "error",
                        "message": "Message invalide."
                    }
                )

                continue

            action = data.get(
                "action"
            )

            # -------------------------------------------------
            # CREATE
            # -------------------------------------------------

            if action == "create":

                if current_room is not None:
                    continue

                await handle_create(
                    websocket
                )

                # Trouver la room créée

                for room_code, room in rooms.items():

                    if (
                        room["players"].get(1, {}).get(
                            "websocket"
                        ) is websocket
                    ):

                        current_room = room_code
                        break

                continue

            # -------------------------------------------------
            # JOIN
            # -------------------------------------------------

            if action == "join":

                if current_room is not None:
                    continue

                room_code = str(
                    data.get(
                        "room",
                        ""
                    )
                ).strip().upper()

                if len(room_code) != 6:

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Code de partie invalide."
                        }
                    )

                    continue

                await handle_join(
                    websocket,
                    room_code
                )

                if room_code in rooms:

                    player = find_player_by_socket(
                        rooms[room_code],
                        websocket
                    )

                    if player is not None:
                        current_room = room_code

                continue

            # -------------------------------------------------
            # RECONNECT
            # -------------------------------------------------

            if action == "reconnect":

                room_code = str(
                    data.get(
                        "room",
                        ""
                    )
                ).strip().upper()

                session_token = str(
                    data.get(
                        "session_token",
                        ""
                    )
                ).strip()

                mode = str(
                    data.get(
                        "mode",
                        ""
                    )
                ).strip()

                if not room_code or not session_token:

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Informations de reconnexion manquantes."
                        }
                    )

                    continue

                success = await handle_reconnect(
                    websocket,
                    room_code,
                    session_token,
                    mode
                )

                if success:

                    current_room = room_code

                continue

            # -------------------------------------------------
            # MOVE
            # -------------------------------------------------

            if action == "move":

                if current_room is None:

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Vous n'êtes dans aucune partie."
                        }
                    )

                    continue

                if current_room not in rooms:

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "La partie n'existe plus."
                        }
                    )

                    continue

                row = data.get("row")
                col = data.get("col")

                if (
                    not isinstance(row, int)
                    or not isinstance(col, int)
                ):

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Coordonnées invalides."
                        }
                    )

                    continue

                await handle_move(
                    rooms[current_room],
                    websocket,
                    row,
                    col
                )

                continue

            # -------------------------------------------------
            # RESET
            # -------------------------------------------------

            if action == "reset":

                if current_room is None:
                    continue

                if current_room not in rooms:
                    continue

                await handle_reset(
                    rooms[current_room],
                    websocket
                )

                continue

            # -------------------------------------------------
            # ACTION INCONNUE
            # -------------------------------------------------

            await send_json(
                websocket,
                {
                    "type": "error",
                    "message": "Action inconnue."
                }
            )

    except websockets.exceptions.ConnectionClosed:

        pass

    except Exception as error:

        print(
            "Erreur client :",
            error
        )

    finally:

        if current_room is not None:

            if current_room in rooms:

                room = rooms[current_room]

                mark_disconnected(
                    room,
                    websocket
                )

                # Ne pas supprimer la room.
                # Cela permet au joueur de revenir avec
                # son session_token.

                print(
                    "Joueur déconnecté de la room",
                    current_room
                )


# =========================================================
# SERVEUR
# =========================================================

async def main():

    print(
        "========================================"
    )

    print(
        "   GOMOKU SERVER"
    )

    print(
        "========================================"
    )

    print(
        f"Serveur lancé sur {HOST}:{PORT}"
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

        await asyncio.Future()


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
