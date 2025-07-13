from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import websockets
import json
import httpx

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

price_dict = {}
coins = ["BTC", "ETH", "XRP"]  # 추적할 코인 리스트

# 업비트 실시간 시세 수신
async def upbit_ws(coin_list):
    url = "wss://api.upbit.com/websocket/v1"
    markets = [f"KRW-{c}" for c in coin_list]
    subscribe_fmt = [{"ticket": "test"}, {"type": "ticker", "codes": markets}]

    while True:
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps(subscribe_fmt))
                print(f"[업비트] {markets} 구독 시작")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    coin = data["code"].replace("KRW-", "")
                    price = data["trade_price"]
                    # 실시간 가격 저장
                    if coin not in price_dict:
                        price_dict[coin] = {}
                    price_dict[coin]["upbit"] = price
                    print(f"[업비트] {coin} 가격: {price}")
        except Exception as e:
            print("[UPBIT] WebSocket 오류:", e)
            await asyncio.sleep(3)

# 바이비트 실시간 시세 수신
async def bybit_ws(coin_list):
    url = "wss://stream.bybit.com/v5/public/spot"
    symbols = [f"{c.upper()}USDT" for c in coin_list]
    subscribe_fmt = {
        "op": "subscribe",
        "args": [f"tickers.{sym}" for sym in symbols]
    }
    print(f"[BYBIT] 구독: {subscribe_fmt}")

    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                await ws.send(json.dumps(subscribe_fmt))

                async def ping_loop():
                    while True:
                        await asyncio.sleep(15)
                        await ws.send(json.dumps({"op": "ping"}))
                        print("[BYBIT] Ping 발송")

                asyncio.create_task(ping_loop())

                while True:
                    msg = await ws.recv()
                    try:
                        data = json.loads(msg)
                    except Exception as e:
                        print("[BYBIT] JSON 파싱 실패:", e, msg)
                        continue

                    if (
                        isinstance(data, dict)
                        and "topic" in data
                        and "data" in data
                        and isinstance(data["data"], dict)
                        and "symbol" in data["data"]
                        and "lastPrice" in data["data"]
                    ):
                        ticker = data["data"]
                        symbol = ticker["symbol"]
                        coin = symbol.replace("USDT", "")
                        price = float(ticker["lastPrice"])
                        if coin not in price_dict:
                            price_dict[coin] = {}
                        price_dict[coin]["bybit"] = price
                        print(f"[BYBIT] {coin} 가격: {price}")
        except Exception as e:
            print("[BYBIT] WebSocket 오류:", e)
            await asyncio.sleep(3)

# 환율 비동기 조회
async def get_usdkrw():
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.manana.kr/exchange/rate/KRW/USD.json", timeout=3)
            fx = resp.json()
        return float(fx[0]['rate'])
    except Exception as e:
        print("[환율] 조회 오류:", e)
        return 1400.0

# 실시간 김프 계산 및 전송
@app.websocket("/ws/kimp")
async def ws_kimp(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await asyncio.sleep(1)
            usdkrw = await get_usdkrw()
            send_list = []
            for coin in coins:
                try:
                    if (
                        coin in price_dict
                        and "upbit" in price_dict[coin]
                        and "bybit" in price_dict[coin]
                    ):
                        upbit_krw = price_dict[coin]["upbit"]
                        bybit_usdt = price_dict[coin]["bybit"]
                        bybit_krw = bybit_usdt * usdkrw
                        kimp = (upbit_krw / bybit_krw - 1) * 100
                        send_list.append({
                            "coin": coin,
                            "upbit_krw": upbit_krw,
                            "bybit_usdt": bybit_usdt,
                            "usd_krw": usdkrw,
                            "bybit_krw": round(bybit_krw, 2),
                            "kimp_percent": round(kimp, 2)
                        })
                except Exception as e:
                    print(f"[KIMP] {coin} 계산 에러:", e)
            await websocket.send_text(json.dumps(send_list))
    except WebSocketDisconnect:
        print("클라이언트 WebSocket 연결 종료")

# 서버 시작 시 비동기 태스크 실행
@app.on_event("startup")
async def start_ws():
    asyncio.create_task(upbit_ws(coins))
    asyncio.create_task(bybit_ws(coins))
