MR_JERY MORPION — SERVER V6

Koreksyon prensipal:
- Render HEAD/GET health checks pa antre kòm WebSocket handshake ankò.
- /health ak /healthz retounen JSON 200.
- WebSocket rete sou menm PORT Render la.
- Login/register, envitasyon, online players, move, dènye pion, rejwe/undo, rematch, spectateur ak chat rete nan server la.

RENDER:
Build Command:
pip install -r requirements.txt

Start Command:
python server.py

Environment:
DATABASE_URL = URL PostgreSQL ou

Frontend WebSocket URL dwe:
wss://NOM-SERVICE-RENDER.onrender.com

Pa mete https:// nan WebSocket URL la.
Pa itilize /health kòm WebSocket URL.

Apre deploy:
https://NOM-SERVICE-RENDER.onrender.com/health
oswa
https://NOM-SERVICE-RENDER.onrender.com/healthz

Li dwe bay:
{"ok":true,"service":"MR_Jery_Morpion_Game_Server","websocket":true}
