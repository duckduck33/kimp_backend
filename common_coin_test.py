import httpx

def fetch_bybit_usdt_futures_tickers_and_prices():
    """
    바이비트 USDT Perpetual(선물) 마켓의 모든 심볼(티커명)과 현재가를 리스트로 반환
    """
    url = "https://api.bybit.com/v5/market/tickers?category=linear"
    with httpx.Client() as client:
        resp = client.get(url)
        data = resp.json()
        tickers = []
        for item in data.get('result', {}).get('list', []):
            symbol = item.get('symbol', '')
            price = item.get('lastPrice', '')
            if symbol.endswith('USDT'):
                coin = symbol[:-4]   # 'BTCUSDT' -> 'BTC'
                tickers.append((coin, price))
        return tickers

def fetch_upbit_all_krw_tickers_and_prices():
    """
    업비트 KRW마켓의 모든 코인(티커)과 현재가(trade_price)를 리스트로 반환
    """
    market_url = "https://api.upbit.com/v1/market/all"
    with httpx.Client() as client:
        resp = client.get(market_url)
        markets = resp.json()
        krw_tickers = [m['market'] for m in markets if m['market'].startswith('KRW-')]

        tickers_str = ','.join(krw_tickers)
        price_url = f"https://api.upbit.com/v1/ticker?markets={tickers_str}"
        resp = client.get(price_url)
        prices = resp.json()

        result = []
        for item in prices:
            market = item.get('market', '')
            if market.startswith('KRW-'):
                coin = market[4:]  # 'KRW-BTC' -> 'BTC'
                price = item.get('trade_price', None)
                result.append((coin, price))
        return result

if __name__ == "__main__":
    # 1. 데이터 수집
    bybit_list = fetch_bybit_usdt_futures_tickers_and_prices()
    upbit_list = fetch_upbit_all_krw_tickers_and_prices()

    # 2. 딕셔너리 변환: {코인명: 가격}
    bybit_dict = dict(bybit_list)
    upbit_dict = dict(upbit_list)

    # 3. 공통 코인 추출 (양쪽 모두 존재하는 코인명)
    common_coins = sorted(set(bybit_dict.keys()) & set(upbit_dict.keys()))

    print(f"공통 코인 개수: {len(common_coins)}")
    print("코인명 | 업비트 가격 | 바이비트 USDT선물 가격")
    print("-" * 40)
    for coin in common_coins:
        upbit_price = upbit_dict[coin]
        bybit_price = bybit_dict[coin]
        print(f"{coin:8} | {upbit_price} | {bybit_price}")

    # 공통 코인 리스트를 마지막에 출력
    print("\n=== 공통 코인 리스트 ===")
    print(common_coins)
