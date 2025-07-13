import asyncio
import websockets

async def test_ws():
    uri = "ws://localhost:8000/ws/kimp"
    async with websockets.connect(uri) as ws:
        for _ in range(5):  # 5번만 받아봄
            msg = await ws.recv()
            print(msg)

if __name__ == "__main__":
    asyncio.run(test_ws())
