# 전체 코드 흐름 설명:
# - FastAPI 서버 및 CORS 설정
# - 업비트/바이비트 실시간 시세 수집 (코인리스트)
# - 한국수출입은행 API를 통한 환율 조회 함수 (87초 주기)
# - ws_kimp에서 1초마다 캐시된 환율과 최신 코인 시세/김프 데이터 전송
# - 서버 시작 시 백그라운드로 WebSocket 시세 수집 및 환율 캐시 업데이트


from dotenv import load_dotenv # 이 줄을 추가합니다.
import os # 환경변수를 읽기 위해 os 모듈 임포트

load_dotenv() # 이 줄을 추가합니다. (os 임포트 바로 아래, 다른 코드보다 먼저)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import websockets
import json
import httpx
from datetime import datetime, timedelta
import os # 환경변수를 읽기 위해 os 모듈 임포트

# import ssl # SSL 오류 해결을 위한 ssl 모듈은 httpx 내부적으로 처리될 수 있으므로 필요없을 수 있습니다.
               # 만약 여전히 CERTIFICATE_VERIFY_FAILED 에러가 발생하면 다시 추가를 고려하세요.

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 시세 저장소 및 코인리스트
price_dict = {}
coins = [
    "BTC", "ETH", "XRP", "LTC", "BCH",
    "1INCH", "A", "AAVE", "ADA"
]

# 환율 캐싱을 위한 전역 변수
# 초기값 설정 (서버 시작 시점에 바로 사용 가능하도록)
current_usdkrw_rate = 1350.0 # 초기 환율 값 (대략적인 값)
last_kexim_update_time = datetime.min # 마지막 환율 업데이트 시간 (최소값으로 초기화)

# =========================================================
# KEXIM API 키를 위한 전역 변수 선언
# 서버 시작 시 한 번만 읽어와서 저장합니다.
# =========================================================
KEXIM_API_KEY_GLOBAL = None # 전역에서 사용할 API 키 변수


# 업비트 WebSocket
async def upbit_ws(coin_list):
    url = "wss://api.upbit.com/websocket/v1"
    markets = [f"KRW-{c}" for c in coin_list]
    subscribe_fmt = [{"ticket": "test"}, {"type": "ticker", "codes": markets}]
    while True:
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps(subscribe_fmt))
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [업비트] 구독 시작: {markets}")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    coin = data["code"].replace("KRW-", "")
                    price = data["trade_price"]
                    price_dict.setdefault(coin, {})["upbit"] = price
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [가격] {coin} 업비트: {price} KRW") # 로그 활성화
        except Exception as e:
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [업비트 오류] {e}")
            await asyncio.sleep(5) # 오류 발생 시 대기 시간 증가

# 바이비트 WebSocket
async def bybit_ws(coin_list):
    url = "wss://stream.bybit.com/v5/public/spot"
    symbols = [f"{c.upper()}USDT" for c in coin_list]
    subscribe_fmt = {"op": "subscribe", "args": [f"tickers.{sym}" for sym in symbols]}
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [바이비트] 구독 시작: {symbols}")
    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                await ws.send(json.dumps(subscribe_fmt))
                async def ping_loop():
                    while True:
                        await asyncio.sleep(15)
                        await ws.send(json.dumps({"op": "ping"}))
                        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [바이비트] Ping") # 로그 활성화
                asyncio.create_task(ping_loop())
                while True:
                    msg = await ws.recv()
                    try:
                        data = json.loads(msg)
                    except:
                        continue
                    if isinstance(data, dict) and data.get("topic", "").startswith("tickers."):
                        t = data["data"]
                        coin = t["symbol"].replace("USDT", "")
                        price = float(t["lastPrice"])
                        price_dict.setdefault(coin, {})["bybit"] = price
                        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [가격] {coin} 바이비트: {price} USDT") # 로그 활성화
        except Exception as e:
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [바이비트 오류] {e}")
            await asyncio.sleep(5) # 오류 발생 시 대기 시간 증가

# =========================================================
# 한국수출입은행 환율 조회 및 전역 변수 업데이트 함수
# (이 함수는 KEXIM_API_KEY_GLOBAL을 인자로 받습니다)
# =========================================================
async def update_kexim_usdkrw(api_key: str):
    global current_usdkrw_rate
    global last_kexim_update_time
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    today_date = datetime.now().strftime('%Y%m%d')
    
    request_url = (
        f"https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"
        f"?authkey={api_key}&searchdate={today_date}&data=AP01"
    )

    try:
        # SSL 인증서 검증 옵션은 기존에 문제가 있었다면 verify=False 유지
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            resp = await client.get(request_url)
            resp.raise_for_status()

            data = resp.json()
            
            # API 응답 결과 코드 확인 (0: 결과 없음, 1: 성공, 2: DATA코드 오류, 3: 인증코드 오류, 4: 일일제한횟수 마감)
            # data가 비어있거나, result 필드가 없거나, result가 1이 아닌 경우 처리
            if not data or not isinstance(data, list) or not data[0].get('result') == 1:
                print(f"[{now_str}] [환율] KEXIM API 응답 오류 또는 데이터 없음. 코드: {data[0].get('result') if data and isinstance(data, list) else 'N/A'}, 응답: {data}. 캐시된 값 유지.")
                return 
            
            usdkrw_rate_found = None
            for item in data:
                if item.get('cur_unit') == 'USD':
                    # 매매 기준율 (deal_bas_r) 사용, 쉼표(,) 제거 후 float으로 변환
                    usdkrw_rate_found = float(item['deal_bas_r'].replace(',', ''))
                    break
            
            if usdkrw_rate_found:
                current_usdkrw_rate = usdkrw_rate_found # 전역 변수 업데이트
                last_kexim_update_time = datetime.now() # 업데이트 시간 기록
                print(f"[{now_str}] [환율] KEXIM API 조회 성공 및 업데이트: {current_usdkrw_rate:.2f} KRW/USD")
            else:
                print(f"[{now_str}] [환율] KEXIM API 응답에서 USD 환율을 찾을 수 없음. 캐시된 값 유지.")

    except httpx.HTTPStatusError as e:
        print(f"[{now_str}] [환율] KEXIM API HTTP 오류 {e.response.status_code}: {e}. 캐시된 값 유지.")
    except Exception as e:
        print(f"[{now_str}] [환율] KEXIM API 예외 발생: {e}. 캐시된 값 유지.")

# =========================================================


# 환율 업데이트를 위한 백그라운드 태스크
async def kexim_fx_updater(): # api_key 파라미터를 제거합니다.
    # 전역으로 선언된 KEXIM_API_KEY_GLOBAL 사용
    if not KEXIM_API_KEY_GLOBAL:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [환율업데이터] API 키가 설정되지 않아 환율 업데이트를 시작할 수 없습니다.")
        return # 키가 없으면 태스크 중단

    # 서버 시작 시 즉시 한 번 호출하여 초기 환율 설정
    await update_kexim_usdkrw(KEXIM_API_KEY_GLOBAL) # 전역 키 사용
    while True:
        # 87초마다 환율 업데이트 시도
        await asyncio.sleep(87) 
        await update_kexim_usdkrw(KEXIM_API_KEY_GLOBAL) # 전역 키 사용


# 김프 계산 & WebSocket 전송 엔드포인트
@app.websocket("/ws/kimp")
async def ws_kimp(websocket: WebSocket):
    await websocket.accept()
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] 클라이언트 연결 완료")
    
    # 이 부분에서 kexim_api_key 변수를 정의하는 코드를 제거합니다.
    # API 키는 이미 전역 변수 KEXIM_API_KEY_GLOBAL에 저장되어 있으므로,
    # ws_kimp 함수 내에서는 직접 사용하지 않아도 됩니다. (update_kexim_usdkrw에서 사용)

    try:
        while True:
            # 환율은 전역 변수에서 가져옵니다 (kexim_fx_updater 태스크가 주기적으로 업데이트)
            usdkrw = current_usdkrw_rate 

            send_list = []
            for coin in coins[:]:
                info = price_dict.get(coin, {})
                # 업비트와 바이비트 가격이 모두 있고, 환율도 유효할 때만 김프 계산
                if 'upbit' in info and 'bybit' in info and usdkrw is not None and usdkrw > 0:
                    upbit_krw = info['upbit']
                    bybit_usdt = info['bybit']
                    
                    # 0으로 나누는 오류 방지
                    bybit_krw = bybit_usdt * usdkrw
                    if bybit_krw == 0: 
                        kimp = 0.0
                    else:
                        kimp = (upbit_krw / bybit_krw - 1) * 100
                    
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [김프] {coin}: {kimp:.2f}%") # 로그 활성화
                    send_list.append({
                        "coin": coin,
                        "upbit_krw": upbit_krw,
                        "bybit_usdt": bybit_usdt,
                        "bybit_krw": round(bybit_krw, 2),
                        "kimp_percent": round(kimp, 2)
                    })
                else:
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] {coin} 정보 부족 또는 환율 없음") # 로그 활성화
            
            # 클라이언트에 전송할 데이터가 없으면 전송하지 않음
            if send_list:
                # 환율 정보와 코인/김프 데이터를 함께 전송
                await websocket.send_text(json.dumps({"exchange_rate": usdkrw, "coin_data": send_list}))
            else:
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] 전송할 코인 데이터 없음.") # 로그 활성화

            # 코인 가격 및 김프는 1초마다 프론트엔드로 전송
            await asyncio.sleep(1) 

    except WebSocketDisconnect:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] 클라이언트 연결 종료")
    except Exception as e:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] 오류 발생: {e}")


# 서버 시작 시 백그라운드 태스크 실행
@app.on_event("startup")
async def start_ws():
    global KEXIM_API_KEY_GLOBAL # 전역 변수를 수정하기 위해 global 선언

    # 서버 시작 시 환경 변수에서 딱 한 번만 API 키를 읽어옵니다.
    KEXIM_API_KEY_GLOBAL = os.getenv("KEXIM_API_KEY")
    if not KEXIM_API_KEY_GLOBAL:
        print("[ERROR] KEXIM_API_KEY 환경변수가 설정되지 않았습니다. 환율 업데이트가 제대로 작동하지 않을 수 있습니다.")
        # 로컬 테스트를 위해 임시로 기존 키 사용 (배포 전 반드시 제거/주석 처리!)


    asyncio.create_task(upbit_ws(coins))
    asyncio.create_task(bybit_ws(coins))
    
    # 환율 업데이트 태스크 시작 (이제 파라미터로 키를 전달할 필요 없음)
    asyncio.create_task(kexim_fx_updater())

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 초기 시세 수집 시작. 잠시 대기합니다...")
    await asyncio.sleep(5) # 5초 정도 대기
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 초기 시세 수집 대기 완료.")