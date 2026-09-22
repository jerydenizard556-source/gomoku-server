import asyncio
import json
import random
import string
import os
import time

import websockets


rooms = {}

START_TIME = 10 * 60
BOARD_SIZE = 20


def code_partie():
    while True:
        code = ''.join(
            random.choice(string.ascii_uppercase + string.digits)
            for _ in range(6)
        )

        if code not in rooms:
            return code


def check_win(board, row, col, color):
    directions = [
        (0, 1),
        (1, 0),
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
            and board.get(f"{r},{c}") == color
        ):
            count += 1
            r += dr
            c += dc

        r = row - dr
        c = col - dc

        while (
            0 <= r < BOARD_SIZE
            and 0 <= c < BOARD_SIZE
            and board.get(f"{r},{c}") == color
        ):
            count += 1
            r -= dr
            c -= dc

        if count >= 5:
            return True

    return False


def nouvelle_partie():
    return {
        "board": {},
        "players": {},
        "turn": 1,
        "winner": None,
        "game_over": False,
        "draw": False,
        "black_time": START_TIME,
        "red_time": START_TIME,
        "last_update": time.monotonic(),
        "moves": []
    }


def mettre_a_jour_temps(room):
    if room["game_over"]:
        room["last_update"] = time.monotonic()
        return

    maintenant = time.monotonic()
    elapsed = maintenant - room["last_update"]

    if room["turn"] == 1:
        room["black_time"] -= elapsed
    else:
        room["red_time"] -= elapsed

    room["last_update"] = maintenant


def temps_entier(value):
    return max(0, int(value))


async def envoyer_etat(room):
    mettre_a_jour_temps(room)

    if not room["game_over"]:
        if room["black_time"] <= 0:
            room["black_time"] = 0
            room["winner"] = 2
            room["game_over"] = True

        elif room["red_time"] <= 0:
            room["red_time"] = 0
            room["winner"] = 1
            room["game_over"] = True

    message = json.dumps({
        "type": "state",
        "board": room["board"],
        "players": len(room["players"]),
        "turn": room["turn"],
        "winner": room["winner"],
        "game_over": room["game_over"],
        "draw": room["draw"],
        "black_time": temps_entier(room["black_time"]),
        "red_time": temps_entier(room["red_time"]),
        "last_move": room["moves"][-1] if room["moves"] else None
    })

    for ws in list(room["players"].values()):
        try:
            await ws.send(message)
        except Exception:
            pass


async def timer_loop(room_code):
    while room_code in rooms:
        room = rooms.get(room_code)

        if room is None:
            break

        if room["game_over"]:
            break

        if len(room["players"]) < 2:
            await asyncio.sleep(0.5)
            continue

        await envoyer_etat(room)

        if room["game_over"]:
            break

        await asyncio.sleep(0.5)


async def handler(websocket):
    room_code = None
    player = None
    timer_task = None

    try:
        async for raw in websocket:

            try:
                data = json.loads(raw)
            except Exception:
                continue

            action = data.get("action")

            if action == "create":

                if room_code:
                    continue

                room_code = code_partie()
                room = nouvelle_partie()

                rooms[room_code] = room

                player = 1
                room["players"][player] = websocket

                await websocket.send(
                    json.dumps({
                        "type": "created",
                        "room": room_code,
                        "player": 1
                    })
                )

                await envoyer_etat(room)

                timer_task = asyncio.create_task(
                    timer_loop(room_code)
                )

            elif action == "join":

                code = str(
                    data.get("room", "")
                ).strip().upper()

                if code not in rooms:
                    await websocket.send(
                        json.dumps({
                            "type": "error",
                            "message": "Partie introuvable."
                        })
                    )
                    continue

                room = rooms[code]

                if len(room["players"]) >= 2:
                    await websocket.send(
                        json.dumps({
                            "type": "error",
                            "message": "Partie complète."
                        })
                    )
                    continue

                room_code = code
                player = 2
                room["players"][player] = websocket

                await websocket.send(
                    json.dumps({
                        "type": "joined",
                        "room": code,
                        "player": 2
                    })
                )

                await envoyer_etat(room)

                if timer_task is None:
                    timer_task = asyncio.create_task(
                        timer_loop(room_code)
                    )

            elif action == "move":

                if not room_code or not player:
                    await websocket.send(
                        json.dumps({
                            "type": "error",
                            "message": "Non connecté."
                        })
                    )
                    continue

                room = rooms.get(room_code)

                if room is None:
                    continue

                if len(room["players"]) < 2:
                    await websocket.send(
                        json.dumps({
                            "type": "error",
                            "message": "En attente du deuxième joueur."
                        })
                    )
                    continue

                if room["game_over"]:
                    await websocket.send(
                        json.dumps({
                            "type": "error",
                            "message": "La partie est terminée."
                        })
                    )
                    continue

                mettre_a_jour_temps(room)

                if room["turn"] == 1 and room["black_time"] <= 0:
                    room["black_time"] = 0
                    room["winner"] = 2
                    room["game_over"] = True
                    await envoyer_etat(room)
                    continue

                if room["turn"] == 2 and room["red_time"] <= 0:
                    room["red_time"] = 0
                    room["winner"] = 1
                    room["game_over"] = True
                    await envoyer_etat(room)
                    continue

                if room["turn"] != player:
                    await websocket.send(
                        json.dumps({
                            "type": "error",
                            "message": "Ce n'est pas ton tour."
                        })
                    )
                    continue

                try:
                    row = int(data.get("row"))
                    col = int(data.get("col"))
                except Exception:
                    await websocket.send(
                        json.dumps({
                            "type": "error",
                            "message": "Coup invalide."
                        })
                    )
                    continue

                if not (
                    0 <= row < BOARD_SIZE
                    and 0 <= col < BOARD_SIZE
                ):
                    await websocket.send(
                        json.dumps({
                            "type": "error",
                            "message": "Coup invalide."
                        })
                    )
                    continue

                key = f"{row},{col}"

                if key in room["board"]:
                    await websocket.send(
                        json.dumps({
                            "type": "error",
                            "message": "Case déjà occupée."
                        })
                    )
                    continue

                color = "black" if player == 1 else "red"

                room["board"][key] = color

                room["moves"].append({
                    "row": row,
                    "col": col,
                    "color": color,
                    "player": player
                })

                if check_win(
                    room["board"],
                    row,
                    col,
                    color
                ):
                    room["winner"] = player
                    room["game_over"] = True

                elif len(room["board"]) >= BOARD_SIZE * BOARD_SIZE:
                    room["draw"] = True
                    room["game_over"] = True
                    room["winner"] = None

                else:
                    room["turn"] = 2 if room["turn"] == 1 else 1
                    room["last_update"] = time.monotonic()

                await envoyer_etat(room)

            elif action == "state":

                if room_code and room_code in rooms:
                    await envoyer_etat(
                        rooms[room_code]
                    )

            elif action == "reset":

                if not room_code or not player:
                    continue

                room = rooms.get(room_code)

                if room is None:
                    continue

                room["board"] = {}
                room["turn"] = 1
                room["winner"] = None
                room["game_over"] = False
                room["draw"] = False
                room["black_time"] = START_TIME
                room["red_time"] = START_TIME
                room["last_update"] = time.monotonic()
                room["moves"] = []

                await envoyer_etat(room)

                if timer_task is None or timer_task.done():
                    timer_task = asyncio.create_task(
                        timer_loop(room_code)
                    )

    except Exception:
        pass

    finally:

        if timer_task is not None:
            timer_task.cancel()

        if room_code in rooms:

            room = rooms[room_code]

            if player in room["players"]:
                del room["players"][player]

            if not room["players"]:
                del rooms[room_code]

            else:
                await envoyer_etat(room)


async def main():

    port = int(
        os.environ.get("PORT", "8765")
    )

    async with websockets.serve(
        handler,
        "0.0.0.0",
        port
    ):
        print(
            f"Gomoku server running on port {port}"
        )

        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
