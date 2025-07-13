import websockets
import asyncio
import json

async def upbit_ws(coin_list=["BTC", "ETH"]):
    url = "wss://api.upbit.com/websocket/v1"
    markets = [f"KRW-{c}" for c in coin_list]
    subscribe_fmt = [{"ticket":"test"}, {"type":"ticker", "codes":markets}]

    while True:  # 연결 끊길 경우를 대비한 재접속 루프
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps(subscribe_fmt))
                print(f"[업비트] {markets} 구독 시작")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    print(data["code"], data["trade_price"])
        except Exception as e:
            print(f"[업비트] WebSocket 오류: {e}, 3초 후 재접속 시도")
            await asyncio.sleep(3)
if __name__ == "__main__":
    import asyncio
    asyncio.run(upbit_ws(["BTC", "ETH"]))
