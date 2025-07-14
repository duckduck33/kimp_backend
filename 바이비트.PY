import httpx

def fetch_bybit_usdt_futures_tickers_and_prices():
    """
    바이비트 USDT Perpetual(선물) 마켓의 모든 심볼(티커명)과 현재가를 리스트로 반환
    """
    url = "https://api.bybit.com/v5/market/tickers?category=linear"
    with httpx.Client() as client:
        resp = client.get(url)
        data = resp.json()
        # 결과 구조: data['result']['list']에 심볼/가격이 모두 있음
        tickers = []
        for item in data.get('result', {}).get('list', []):
            symbol = item.get('symbol', '')
            price = item.get('lastPrice', '')
            # USDT Perpetual만
            if symbol.endswith('USDT'):
                tickers.append((symbol, price))
        return tickers

if __name__ == "__main__":
    tickers = fetch_bybit_usdt_futures_tickers_and_prices()
    print(f"USDT 선물 마켓 전체 티커 개수: {len(tickers)}")
    print("예시:", tickers[:10])
    # 전체 심볼명과 가격을 한 줄씩 출력
    for symbol, price in tickers:
        print(f"{symbol} : {price}")
