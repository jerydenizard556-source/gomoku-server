import asyncio
import json
import random
import string
import websockets

rooms = {}


def generate_room_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in rooms:
            return code


async def send_state(room):
    data = {
        "type": "state",
        "board": room["board"],
        "players": len(room["players"]),
    }

    message = json.dumps(data)

    for player in room["players"]:
        try:
            await player.send(message)
        except:
            pass


async def handle_client(websocket):
    room_code = None
    player_number = None

    try:
        async for message in websocket:

            data = json.loads(message)
            action = data.get("action")

            # -----------------------------
            # CREER UNE PARTIE
            # -----------------------------
            if action == "create":

                room_code = generate_room_code()

                rooms[room_code] = {
                    "board": {},
                    "players": []
                }

                rooms[room_code]["players"].append(websocket)
                player_number = 1

                await websocket.send(json.dumps({
                    "type": "created",
                    "room": room_code,
                    "player": player_number
                }))

                await send_state(rooms[room_code])

            # -----------------------------
            # REJOINDRE UNE PARTIE
            # -----------------------------
            elif action == "join":

                room_code = data.get("room")

                if room_code not in rooms:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Partie introuvable."
                    }))
                    continue

                room = rooms[room_code]

                if len(room["players"]) >= 2:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Cette partie est déjà pleine."
                    }))
                    continue

                room["players"].append(websocket)
                player_number = 2

                await websocket.send(json.dumps({
                    "type": "joined",
                    "room": room_code,
                    "player": player_number
                }))

                await send_state(room)

            # -----------------------------
            # JOUER UN PION
            # -----------------------------
            elif action == "move":

                if room_code not in rooms:
                    continue

                room = rooms[room_code]

                row = data.get("row")
                col = data.get("col")

                position = f"{row},{col}"

                # Case déjà occupée
                if position in room["board"]:
                    await websocket.send(json.dumps({
                        "type": "invalid",
                        "message": "Cette position est déjà occupée."
                    }))
                    continue

                # Noir = joueur 1
                # Rouge = joueur 2
                color = "black" if player_number == 1 else "red"

                room["board"][position] = color

                # Envoyer le nouveau plateau
                await send_state(room)

            # -----------------------------
            # DEMANDE ETAT
            # -----------------------------
            elif action == "state":

                if room_code in rooms:
                    await send_state(rooms[room_code])

    except websockets.exceptions.ConnectionClosed:
        pass

    finally:

        if room_code in rooms:

            room = rooms[room_code]

            if websocket in room["players"]:
                room["players"].remove(websocket)

            # Si tout moun soti, efase pati a
            if len(room["players"]) == 0:
                del rooms[room_code]


async def main():

    print("====================================")
    print("       SERVEUR GOMOKU DEMARRE")
    print("====================================")
    print("En attente des joueurs...")
    print("Serveur: ws://localhost:8765")
    print()

    async with websockets.serve(
        handle_client,
        "0.0.0.0",
        8765
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())