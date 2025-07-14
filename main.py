from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import websockets
import json
import httpx
import time
from contextlib import asynccontextmanager

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
    "BTC", "ETH", "XRP", "LTC", "BCH", "1INCH", "A", "AAVE", "ADA"
]


# ─────────────────────────────────────────────────────────────────────────────
# 1) 헬스체크 HTTP 엔드포인트 추가 (GET /health)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    """
    배포 환경에서 외부 환율 API 상태를 빠르게 점검하기 위한 엔드포인트
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # 기본 환율 API 호출
            resp = await client.get("https://open.er-api.com/v6/latest/USD")
            resp.raise_for_status()
            fx = resp.json()
            rate = fx["rates"].get("KRW")
        return {"ok": True, "rate": rate, "source": "open.er-api.com"}
    except httpx.HTTPStatusError as e:
        # 401 Unauthorized 등 HTTP 에러 처리
        if e.response.status_code == 401:
            try:
                # 401 발생 시 대체 API로 폴백
                async with httpx.AsyncClient(timeout=5) as client2:
                    fallback = await client2.get(
                        "https://api.exchangerate.host/latest?base=USD&symbols=KRW"
                    )
                    fallback.raise_for_status()
                    jr = fallback.json()
                    rate2 = jr["rates"]["KRW"]
                return {"ok": True, "rate": rate2, "source": "exchangerate.host"}
            except Exception as e2:
                return {"ok": False, "error": f"Fallback failed: {e2}"}
        return {"ok": False, "error": f"HTTP error {e.response.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 2) 업비트 실시간 시세 수신
# ─────────────────────────────────────────────────────────────────────────────
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
                    price_dict.setdefault(coin, {})["upbit"] = price
                    print(f"[업비트] {coin} 가격: {price}")
        except Exception as e:
            print("[UPBIT] WebSocket 오류:", e)
            await asyncio.sleep(3)


# ─────────────────────────────────────────────────────────────────────────────
# 3) 바이비트 실시간 시세 수신
# ─────────────────────────────────────────────────────────────────────────────
async def bybit_ws(coin_list):
    url = "wss://stream.bybit.com/v5/public/spot"
    symbols = [f"{c.upper()}USDT" for c in coin_list]
    subscribe_fmt = {"op": "subscribe", "args": [f"tickers.{s}" for s in symbols]}
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
                        and isinstance(data["data"], dict)
                    ):
                        t = data["data"]
                        symbol = t["symbol"]
                        coin = symbol.replace("USDT", "")
                        price = float(t["lastPrice"])
                        price_dict.setdefault(coin, {})["bybit"] = price
                        print(f"[BYBIT] {coin} 가격: {price}")
        except Exception as e:
            print("[BYBIT] WebSocket 오류:", e)
            await asyncio.sleep(3)


# ─────────────────────────────────────────────────────────────────────────────
# 4) 환율 조회 함수 (401 폴백 로직 포함)
# ─────────────────────────────────────────────────────────────────────────────
usdkrw_cache = {"rate": 1400.0, "timestamp": 0}
CACHE_DURATION = 60  # seconds

async def get_usdkrw():
    now = time.time()
    if now - usdkrw_cache["timestamp"] > CACHE_DURATION:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("https://open.er-api.com/v6/latest/USD")
                resp.raise_for_status()
                fx = resp.json()
                rate = float(fx["rates"]["KRW"])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                # 401 시 폴백
                async with httpx.AsyncClient(timeout=5) as client2:
                    fb = await client2.get(
                        "https://api.exchangerate.host/latest?base=USD&symbols=KRW"
                    )
                    fb.raise_for_status()
                    rate = float(fb.json()["rates"]["KRW"])
            else:
                rate = usdkrw_cache["rate"]
        except Exception:
            rate = usdkrw_cache["rate"]
        usdkrw_cache.update(rate=rate, timestamp=now)
    return usdkrw_cache["rate"]


# ─────────────────────────────────────────────────────────────────────────────
# 5) 실시간 김프 계산 및 전송 (웹소켓)
# ─────────────────────────────────────────────────────────────────────────────
@app.websocket("/ws/kimp")
async def ws_kimp(websocket: WebSocket):
    await websocket.accept()
    print("[ws_kimp] 클라이언트 연결 수락 완료")
    try:
        while True:
            await asyncio.sleep(1)
            usdkrw = await get_usdkrw()
            send_list = []
            for coin in coins[:]:
                info = price_dict.get(coin, {})
                if "upbit" in info and "bybit" in info:
                    upkrw = info["upbit"]
                    byusdt = info["bybit"]
                    bykrw = byusdt * usdkrw
                    kimp = (upkrw / bykrw - 1) * 100
                    send_list.append({
                        "coin": coin,
                        "upbit_krw": upkrw,
                        "bybit_usdt": byusdt,
                        "usd_krw": usdkrw,
                        "bybit_krw": round(bykrw, 2),
                        "kimp_percent": round(kimp, 2),
                    })
                else:
                    print(f"[ws_kimp] {coin} 가격 정보 부족")
            await websocket.send_text(json.dumps(send_list))
    except WebSocketDisconnect:
        print("[ws_kimp] 클라이언트 연결 종료")


# ─────────────────────────────────────────────────────────────────────────────
# 6) 서버 시작 시 백그라운드 태스크 실행
#    (lifespan 이벤트 핸들러로 권장)
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시
    t1 = asyncio.create_task(upbit_ws(coins))
    t2 = asyncio.create_task(bybit_ws(coins))
    yield
    # 서버 종료 시
    t1.cancel()
    t2.cancel()

# FastAPI 인스턴스에 lifespan 등록
app.router.lifespan_context = lifespan  # if using FastAPI <0.95 adjust accordingly
