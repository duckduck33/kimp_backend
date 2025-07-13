import asyncio
import websockets
import json

async def bybit_ws_test():
    url = "wss://stream.bybit.com/v5/public/spot"
    subscribe_fmt = {
        "op": "subscribe",
        "args": ["tickers.BTCUSDT", "tickers.ETHUSDT"]
    }
    async with websockets.connect(url, ping_interval=None) as ws:
        await ws.send(json.dumps(subscribe_fmt))
        print("구독 전송")
        async def ping_loop():
            while True:
                await asyncio.sleep(15)
                await ws.send(json.dumps({"op": "ping"}))
                print("Ping 발송")
        asyncio.create_task(ping_loop())

        while True:
            msg = await ws.recv()
            print("수신:", msg)

asyncio.run(bybit_ws_test())
