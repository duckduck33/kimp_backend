# 전체 코드 흐름 설명:
# - FastAPI 서버 및 CORS 설정
# - 업비트/바이비트 실시간 시세 수집 (코인리스트, KRW-USDT 포함)
# - 한국수출입은행 환율 API 함수는 주석 처리하여 유지
# - ws_kimp에서 1초마다 업비트 USDT 가격 기반 김프 계산 및 클라 전송
# - 서버 시작 시 백그라운드로 WebSocket 시세 수집

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import websockets
import json
import httpx # httpx는 주석 처리된 환율 함수 때문에 필요
from datetime import datetime, timedelta

# KEXIM API 관련 모듈 (dotenv, os)은 주석 처리된 함수 때문에 필요하지만,
# load_dotenv()는 호출하지 않으므로 제거합니다.
# import os
# from dotenv import load_dotenv

# load_dotenv() # KEXIM API 관련이므로 호출 제거

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
    "1INCH", "DOGE", "AAVE", "ADA"
]

# 환율 캐싱을 위한 전역 변수 (이제 업비트 USDT 가격이 이 역할을 대신함)
# KEXIM API 관련이므로 주석 처리
# current_usdkrw_rate = 1350.0
# last_kexim_update_time = datetime.min

# =========================================================
# KEXIM API 키 관련 전역 변수 주석 처리
# KEXIM_API_KEY_GLOBAL = None
# =========================================================


# 업비트 WebSocket
async def upbit_ws(coin_list):
    url = "wss://api.upbit.com/websocket/v1"
    # KRW-USDT 마켓을 코인 리스트와 함께 구독
    markets = [f"KRW-{c}" for c in coin_list]
    markets.append("KRW-USDT") # USDT/KRW 가격을 가져오기 위해 추가
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
                    
                    try:
                        price = float(price) # 명시적으로 float으로 변환
                    except (ValueError, TypeError):
                        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [업비트 오류] {coin} 가격 파싱 실패: {price} (타입: {type(price)})")
                        continue

                    price_dict.setdefault(coin, {})["upbit"] = price
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [가격] {coin} 업비트: {price} KRW")
        except Exception as e:
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [업비트 오류] {e}")
            await asyncio.sleep(5)

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
                        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [바이비트] Ping")
                asyncio.create_task(ping_loop())
                while True:
                    msg = await ws.recv()
                    try:
                        data = json.loads(msg)
                    except:
                        continue
                    if isinstance(data, dict) and data.get("topic", "").startswith("tickers."):
                        t = data["data"]
                        price = float(t["lastPrice"])
                        coin = t["symbol"].replace("USDT", "")
                        price_dict.setdefault(coin, {})["bybit"] = price
                        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [가격] {coin} 바이비트: {price} USDT")
        except Exception as e:
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [바이비트 오류] {e}")
            await asyncio.sleep(5)

# =========================================================
# 한국수출입은행 환율 조회 함수 및 관련 백그라운드 태스크 주석 처리
# =========================================================
# async def update_kexim_usdkrw(api_key: str):
#     global current_usdkrw_rate
#     global last_kexim_update_time
    
#     now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
#     today_date = datetime.now().strftime('%Y%m%d')
    
#     request_url = (
#         f"https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"
#         f"?authkey={api_key}&searchdate={today_date}&data=AP01"
#     )

#     try:
#         async with httpx.AsyncClient(timeout=10, verify=False) as client:
#             resp = await client.get(request_url)
#             resp.raise_for_status()

#             data = resp.json()
            
#             if not data or not isinstance(data, list) or not data[0].get('result') == 1:
#                 print(f"[{now_str}] [환율] KEXIM API 응답 오류 또는 데이터 없음. 코드: {data[0].get('result') if data and isinstance(data, list) else 'N/A'}, 응답: {data}. 캐시된 값 유지.")
#                 current_usdkrw_rate = 1400.0
#                 last_kexim_update_time = datetime.now()
#                 print(f"[{now_str}] [환율] KEXIM API 오류로 인해 환율을 1400.0 KRW/USD로 하드코딩하여 사용합니다.")
#                 return 
            
#             usdkrw_rate_found = None
#             for item in data:
#                 if item.get('cur_unit') == 'USD':
#                     usdkrw_rate_found = float(item['deal_bas_r'].replace(',', ''))
#                     break
            
#             if usdkrw_rate_found:
#                 current_usdkrw_rate = usdkrw_rate_found
#                 last_kexim_update_time = datetime.now()
#                 print(f"[{now_str}] [환율] KEXIM API 조회 성공 및 업데이트: {current_usdkrw_rate:.2f} KRW/USD")
#             else:
#                 print(f"[{now_str}] [환율] KEXIM API 응답에서 USD 환율을 찾을 수 없음. 캐시된 값 유지.")
#                 current_usdkrw_rate = 1400.0
#                 last_kexim_update_time = datetime.now()
#                 print(f"[{now_str}] [환율] USD 환율을 찾을 수 없어 1400.0 KRW/USD로 하드코딩하여 사용합니다.")


#     except httpx.HTTPStatusError as e:
#         print(f"[{now_str}] [환율] KEXIM API HTTP 오류 {e.response.status_code}: {e}. 캐시된 값 유지.")
#         current_usdkrw_rate = 1400.0
#         last_kexim_update_time = datetime.now()
#         print(f"[{now_str}] [환율] KEXIM API HTTP 오류로 인해 환율을 1400.0 KRW/USD로 하드코딩하여 사용합니다.")
#     except Exception as e:
#         print(f"[{now_str}] [환율] KEXIM API 예외 발생: {e}. 캐시된 값 유지.")
#         current_usdkrw_rate = 1400.0
#         last_kexim_update_time = datetime.now()
#         print(f"[{now_str}] [환율] KEXIM API 예외로 인해 환율을 1400.0 KRW/USD로 하드코딩하여 사용합니다.")

# async def kexim_fx_updater():
#     # 전역으로 선언된 KEXIM_API_KEY_GLOBAL 사용 (주석 처리)
#     # if not KEXIM_API_KEY_GLOBAL:
#     #     print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [환율업데이터] API 키가 설정되지 않아 환율 업데이트를 시작할 수 없습니다.")
#     #     global current_usdkrw_rate
#     #     global last_kexim_update_time
#     #     current_usdkrw_rate = 1400.0
#     #     last_kexim_update_time = datetime.now()
#     #     print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [환율업데이터] API 키 없음. 초기 환율 1400.0 KRW/USD로 설정.")
#     #     # return # 키가 없어도 계속 진행하여 하드코딩된 값이라도 사용하도록 변경 (주석 처리)
#     # else:
#     #     await update_kexim_usdkrw(KEXIM_API_KEY_GLOBAL)

#     while True:
#         await asyncio.sleep(87)
#         # if KEXIM_API_KEY_GLOBAL: # 주석 처리
#         #     await update_kexim_usdkrw(KEXIM_API_KEY_GLOBAL) # 주석 처리
#         # else: # 주석 처리
#         #     print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [환율업데이터] API 키 없음. 87초마다 환율 1400.0 KRW/USD로 유지.") # 주석 처리


# 김프 계산 & WebSocket 전송 엔드포인트
@app.websocket("/ws/kimp")
async def ws_kimp(websocket: WebSocket):
    await websocket.accept()
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] 클라이언트 연결 완료")
    
    try:
        while True:
            # 업비트 USDT/KRW 가격을 환율 대신 사용
            upbit_usdt_krw_rate = price_dict.get("USDT", {}).get("upbit")
            
            # USDT 가격이 유효하지 않으면 데이터 전송 대기 (김프 계산 불가)
            if upbit_usdt_krw_rate is None or upbit_usdt_krw_rate <= 0:
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] 업비트 USDT 가격(환율) 미수신 또는 유효하지 않음. 데이터 전송 대기.")
                await asyncio.sleep(1) # 1초 대기 후 재시도
                continue # 다음 루프로 바로 넘어감

            # 환율 변수는 이제 업비트 USDT/KRW 가격이 됩니다.
            usdkrw_equivalent = upbit_usdt_krw_rate 

            # --- 디버깅용 로그 추가 시작 ---
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [DEBUG_WS] ws_kimp 루프 시작. 현재 업비트 USDT/KRW 가격: {usdkrw_equivalent}", flush=True)
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [DEBUG_WS] price_dict keys: {price_dict.keys()}", flush=True)
            # --- 디버깅용 로그 추가 끝 ---

            send_list = []
            for coin in coins[:]:
                info = price_dict.get(coin, {})
                # 업비트와 바이비트 가격이 모두 있고, 업비트 USDT 가격(환율)도 유효할 때만 김프 계산
                if 'upbit' in info and 'bybit' in info: # usdkrw_equivalent는 이미 위에서 검증되었으므로 조건에서 제거
                    upbit_krw = info['upbit']
                    bybit_usdt = info['bybit']
                    
                    # 바이비트 USDT 가격을 업비트 USDT/KRW 가격으로 환산
                    bybit_krw_equivalent = bybit_usdt * usdkrw_equivalent
                    
                    # 0으로 나누는 오류 방지
                    if bybit_krw_equivalent == 0: 
                        kimp = 0.0
                    else:
                        kimp = (upbit_krw / bybit_krw_equivalent - 1) * 100
                    
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [김프] {coin}: {kimp:.2f}%") # 로그 활성화
                    send_list.append({
                        "coin": coin,
                        "upbit_krw": upbit_krw,
                        "bybit_usdt": bybit_usdt,
                        "bybit_krw": round(bybit_krw_equivalent, 2), # KRW 환산값도 변경
                        "kimp_percent": round(kimp, 2)
                    })
                else:
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] {coin} 정보 부족. 현재 info: {info}", flush=True) # 로그 상세화 및 flush

            # --- 디버깅용 로그 추가 시작 ---
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [DEBUG_WS] send_list 길이: {len(send_list)}", flush=True)
            # --- 디버깅용 로그 추가 끝 ---

            if send_list:
                # 'exchange_rate' 필드에 업비트 USDT/KRW 가격을 전송
                await websocket.send_text(json.dumps({"exchange_rate": usdkrw_equivalent, "coin_data": send_list}))
            else:
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] 전송할 코인 데이터 없음. 현재 price_dict: {price_dict}", flush=True)

            await asyncio.sleep(1) 

    except WebSocketDisconnect:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] 클라이언트 연결 종료")
    except Exception as e:
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S'}] [ws_kimp] 오류 발생: {e}", flush=True)


# 서버 시작 시 백그라운드 태스크 실행
@app.on_event("startup")
async def start_ws():
    # KEXIM API 키 관련 로직 주석 처리
    # global KEXIM_API_KEY_GLOBAL
    # KEXIM_API_KEY_GLOBAL = os.getenv("KEXIM_API_KEY")
    # if not KEXIM_API_KEY_GLOBAL:
    #     print("[ERROR] KEXIM_API_KEY 환경변수가 설정되지 않았습니다. 환율 업데이트가 제대로 작동하지 않을 수 있습니다.")
    #     global current_usdkrw_rate
    #     global last_kexim_update_time
    #     current_usdkrw_rate = 1400.0
    #     last_kexim_update_time = datetime.now()
    #     print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [start_ws] API 키 없음. 초기 환율 1400.0 KRW/USD로 설정.")

    asyncio.create_task(upbit_ws(coins))
    asyncio.create_task(bybit_ws(coins))
    
    # KEXIM 환율 업데이트 태스크 주석 처리
    # asyncio.create_task(kexim_fx_updater())

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 초기 시세 수집 시작. 잠시 대기합니다...")
    await asyncio.sleep(5)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 초기 시세 수집 대기 완료.")