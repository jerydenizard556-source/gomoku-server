import asyncio
import json
import unittest
from urllib.request import urlopen

import websockets
import server


class GomokuWebSocketSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_endpoint_and_websocket_tournament_list(self):
        async with websockets.serve(
            server.handler,
            "127.0.0.1",
            0,
            process_request=server.health_response,
            ping_interval=20,
            ping_timeout=20,
        ) as listener:
            port = listener.sockets[0].getsockname()[1]
            health = await asyncio.to_thread(
                lambda: urlopen(f"http://127.0.0.1:{port}/health", timeout=5).read()
            )
            self.assertIn(b'"ok":true', health)

            async with websockets.connect(
                f"ws://127.0.0.1:{port}",
                open_timeout=5,
            ) as ws:
                await ws.send(json.dumps({"type": "tournament_list"}))
                response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                self.assertEqual(response.get("type"), "tournament_list_result")
                self.assertIsInstance(response.get("tournaments"), list)


if __name__ == "__main__":
    unittest.main()
