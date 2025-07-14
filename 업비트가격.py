import httpx

def fetch_upbit_all_krw_tickers_and_prices():
    """
    업비트 KRW마켓의 모든 코인(티커)과 현재가(trade_price)를 리스트로 반환
    """
    # 1. 모든 KRW마켓 코인 코드 조회
    market_url = "https://api.upbit.com/v1/market/all"
    with httpx.Client() as client:
        resp = client.get(market_url)
        markets = resp.json()
        krw_tickers = [m['market'] for m in markets if m['market'].startswith('KRW-')]

        # 2. 전체 KRW마켓에 대해 가격 정보 한번에 조회 (최대 100개까지 동시 조회 가능)
        # 여러 개면 ,로 구분해서 한번에 요청
        tickers_str = ','.join(krw_tickers)
        price_url = f"https://api.upbit.com/v1/ticker?markets={tickers_str}"
        resp = client.get(price_url)
        prices = resp.json()

        # 3. 결과 리스트로 변환 (market, trade_price)
        result = []
        for item in prices:
            market = item.get('market', '')
            price = item.get('trade_price', None)
            result.append((market, price))
        return result

if __name__ == "__main__":
    tickers_prices = fetch_upbit_all_krw_tickers_and_prices()
    print(f"업비트 KRW마켓 전체 티커 개수: {len(tickers_prices)}")
    print("예시:", tickers_prices[:10])
    # 전체 출력
    for market, price in tickers_prices:
        print(f"{market} : {price}")
