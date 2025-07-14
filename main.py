from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import websockets
import json
import httpx
import time
from datetime import datetime

app = FastAPI()

# CORS 설정: 모든 도메인에서 접근 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 실시간 가격 저장소
price_dict = {}
# 모니터링할 코인 리스트
coins = [
    "BTC", "ETH", "XRP", "LTC", "BCH", "1INCH", "A", "AAVE", "ADA"
]

# -----------------------------------------------------------------------------
# 1) 업비트 WebSocket으로 실시간 시세 수신
# -----------------------------------------------------------------------------
async def upbit_ws(coin_list):
    url = "wss://api.upbit.com/websocket/v1"
    markets = [f"KRW-{c}" for c in coin_list]
    subscribe_fmt = [{"ticket": "test"}, {"type": "ticker", "codes": markets}]

    while True:
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps(subscribe_fmt))
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [업비트] {markets} 구독 시작")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    coin = data["code"].replace("KRW-", "")
                    price = data["trade_price"]
                    # 가격 저장
                    price_dict.setdefault(coin, {})["upbit"] = price
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [가격] {coin} 업비트: {price} KRW")
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [UPBIT] WebSocket 오류: {e}")
            await asyncio.sleep(3)

# -----------------------------------------------------------------------------
# 2) 바이비트 WebSocket으로 실시간 시세 수신
# -----------------------------------------------------------------------------
async def bybit_ws(coin_list):
    url = "wss://stream.bybit.com/v5/public/spot"
    symbols = [f"{c.upper()}USDT" for c in coin_list]
    subscribe_fmt = {"op": "subscribe", "args": [f"tickers.{sym}" for sym in symbols]}
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [BYBIT] 구독 시작: {subscribe_fmt}")

    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                await ws.send(json.dumps(subscribe_fmt))

                # 15초마다 Ping 전송하여 연결 유지
                async def ping_loop():
                    while True:
                        await asyncio.sleep(15)
                        await ws.send(json.dumps({"op": "ping"}))
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [BYBIT] Ping 발송")

                asyncio.create_task(ping_loop())

                while True:
                    msg = await ws.recv()
                    try:
                        data = json.loads(msg)
                    except Exception as e:
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [BYBIT] JSON 파싱 실패: {e}")
                        continue

                    # 유효한 데이터 구조인지 확인
                    if (
                        isinstance(data, dict)
                        and data.get("topic", "").startswith("tickers.")
                        and isinstance(data.get("data"), dict)
                    ):
                        t = data["data"]
                        symbol = t["symbol"]
                        coin = symbol.replace("USDT", "")
                        price = float(t["lastPrice"])
                        # 가격 저장
                        price_dict.setdefault(coin, {})["bybit"] = price
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [가격] {coin} 바이비트: {price} USDT")
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [BYBIT] WebSocket 오류: {e}")
            await asyncio.sleep(3)

# -----------------------------------------------------------------------------
# 3) 환율 조회 함수 (캐싱 + 401 폴백 로직 포함)
# -----------------------------------------------------------------------------
usdkrw_cache = {"rate": 1400.0, "timestamp": 0}
CACHE_DURATION = 60  # 캐시 유지 시간(초)

async def get_usdkrw():
    now = time.time()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 캐시 만료 여부 확인
    if now - usdkrw_cache["timestamp"] > CACHE_DURATION:
        try:
            # 기본 API 호출
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("https://open.er-api.com/v6/latest/USD")
                resp.raise_for_status()
                fx = resp.json()
            rate = float(fx['rates']['KRW'])
            source = "open.er-api.com"
            print(f"[{now_str}] [환율] 조회 성공: {rate:.2f} KRW/USD (source: {source})")

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                try:
                    # 401 Unauthorized 시 대체 API 호출
                    async with httpx.AsyncClient(timeout=5) as client2:
                        fb = await client2.get(
                            "https://api.exchangerate.host/latest?base=USD&symbols=KRW"
                        )
                        fb.raise_for_status()
                        data2 = fb.json()
                    rate = float(data2['rates']['KRW'])
                    source = "exchangerate.host"
                    print(f"[{now_str}] [환율] HTTP 401 발생, 대체 API 조회 성공: {rate:.2f} KRW/USD (source: {source})")
                except Exception as e2:
                    print(f"[{now_str}] [환율] 대체 API 조회 실패: {e2}")
                    rate = usdkrw_cache['rate']
            else:
                print(f"[{now_str}] [환율] HTTP 오류 {e.response.status_code}, 이전 캐시 사용: {usdkrw_cache['rate']:.2f}")
                rate = usdkrw_cache['rate']

        except Exception as e:
            print(f"[{now_str}] [환율] 조회 중 예외 발생: {e}, 이전 캐시 사용: {usdkrw_cache['rate']:.2f}")
            rate = usdkrw_cache['rate']

        # 캐시 업데이트
        usdkrw_cache['rate'] = rate
        usdkrw_cache['timestamp'] = now
    else:
        print(f"[{now_str}] [환율] 캐시 사용: {usdkrw_cache['rate']:.2f} KRW/USD")

    return usdkrw_cache['rate']

# -----------------------------------------------------------------------------
# 4) 김프 계산 및 WebSocket 전송
# -----------------------------------------------------------------------------
@app.websocket("/ws/kimp")
async def ws_kimp(websocket: WebSocket):
    await websocket.accept()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ws_kimp] 클라이언트 연결 수락 완료")
    try:
        while True:
            await asyncio.sleep(1)
            # usdkrw = await get_usdkrw()
            usdkrw = 1400
            send_list = []

            # coins 리스트 복사본으로 루프
            for coin in coins[:]:
                try:
                    info = price_dict.get(coin, {})
                    # 업비트/바이비트 가격이 모두 있으면 계산
                    if 'upbit' in info and 'bybit' in info:
                        upbit_krw = info['upbit']
                        bybit_usdt = info['bybit']
                        bybit_krw = bybit_usdt * usdkrw
                        kimp = (upbit_krw / bybit_krw - 1) * 100

                        # 코인 가격 및 김프 상세 로그 출력
                        log_str = (
                            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                            f"[김프] {coin}: 업비트={upbit_krw}KRW, 바이비트(USDT)={bybit_usdt:.6f}, "
                            f"환율={usdkrw:.2f}, 바이비트(KRW)={bybit_krw:.2f}KRW, 김프={kimp:.2f}%"
                        )
                        print(log_str)

                        # 프론트엔드 전송용 데이터 구성
                        send_list.append({
                            "coin": coin,
                            "upbit_krw": upbit_krw,
                            "bybit_usdt": bybit_usdt,
                            "bybit_krw": round(bybit_krw, 2),
                            "kimp_percent": round(kimp, 2)
                        })
                    else:
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ws_kimp] {coin} 가격 정보 부족")
                except Exception as e:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ws_kimp] {coin} 처리 중 에러 발생: {e}")
                    coins.remove(coin)
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ws_kimp] {coin} 리스트에서 제거됨")

            # JSON 문자열로 클라이언트 전송
            await websocket.send_text(json.dumps(send_list))

    except WebSocketDisconnect:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [ws_kimp] 클라이언트 연결 종료")

# -----------------------------------------------------------------------------
# 5) 서버 시작 시 WebSocket 구독 백그라운드 태스크 실행
# -----------------------------------------------------------------------------
@app.on_event("startup")
async def start_ws():
    asyncio.create_task(upbit_ws(coins))
    asyncio.create_task(bybit_ws(coins))