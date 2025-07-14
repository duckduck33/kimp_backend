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
coins = [
    "BTC", "ETH", "XRP", "LTC", "BCH",'1INCH', 'A', 'AAVE', 'ADA'
]



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
import time

usdkrw_cache = {
    "rate": 1400.0,     # 초기값
    "timestamp": 0      # 마지막 업데이트 시간(초)
}

CACHE_DURATION = 60  # 1분(60초)

async def get_usdkrw():
    now = time.time()
    # 캐시가 만료됐으면 새로 조회
    if now - usdkrw_cache["timestamp"] > CACHE_DURATION:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://open.er-api.com/v6/latest/USD", timeout=3)
                fx = resp.json()
            rate = float(fx['rates']['KRW'])
            print(f"[환율] 현재 원/달러 환율: {rate}")
            # 캐시에 저장
            usdkrw_cache["rate"] = rate
            usdkrw_cache["timestamp"] = now
        except Exception as e:
            print("[환율] 조회 오류:", e)
    else:
        print(f"[환율] 캐시 사용: {usdkrw_cache['rate']}")
    return usdkrw_cache["rate"]


# 실시간 김프 계산 및 전송
@app.websocket("/ws/kimp")
async def ws_kimp(websocket: WebSocket):
    await websocket.accept()
    global coins  # coins 리스트를 함수 내에서 수정하기 위해 global 선언
    print("[ws_kimp] 클라이언트 연결 수락 완료")
    try:
        while True:
            await asyncio.sleep(1)
            usdkrw = await get_usdkrw()
            send_list = []

            # 복사본으로 안전하게 루프
            for coin in coins[:]:  # coins[:]는 coins 리스트 복사본
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
                        print(kimp,"김프값!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                        send_list.append({
                            "coin": coin,
                            "upbit_krw": upbit_krw,
                            "bybit_usdt": bybit_usdt,
                            "usd_krw": usdkrw,
                            "bybit_krw": round(bybit_krw, 2),
                            "kimp_percent": round(kimp, 2)
                        })
                    else:
                        print(f"[ws_kimp] {coin} 가격 정보 부족")
                except Exception as e:
                    print(f"[ws_kimp] {coin} 처리 중 에러 발생: {e}")
                    # 에러 발생 시 coins 리스트에서 해당 코인 삭제
                    coins.remove(coin)
                    print(f"[ws_kimp] {coin} 리스트에서 제거됨")

            await websocket.send_text(json.dumps(send_list))

    except WebSocketDisconnect:
        print("[ws_kimp] 클라이언트 연결 종료")

# 서버 시작 시 비동기 태스크 실행
@app.on_event("startup")
async def start_ws():
    asyncio.create_task(upbit_ws(coins))
    asyncio.create_task(bybit_ws(coins))
