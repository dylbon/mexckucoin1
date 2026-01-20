```python
import requests
import time
import signal
import sys

# === CONFIG ===
BOT_TOKEN = "8212674831:AAFQPexNzzYeprq3J8OuSSNBYsJQE6JM87s"  # New bot
CHAT_ID = "7297679984"  # Confirmed chat
THRESHOLD_PERCENT = 3.0  # 3% profit threshold
CHECK_INTERVAL = 60  # Check every 60 seconds
MAX_RETRIES = 3
MEXC_TAKER_FEE = 0.0005
KRAKEN_TAKER_FEE = 0.0026
KUCOIN_TAKER_FEE = 0.001
BLACKLIST = {'ALPHA', 'UTK', 'THETA', 'AERGO', 'MOVE'}  # Applied globally
SYMBOL_MAP = {
    'LUNA': 'LUNC',
    'LUNA2': 'LUNA',
    'BTT': 'BTTC',
    'NANO': 'XNO',
}
QUOTE_CURRENCIES = ['USDT', 'USD']  # Removed 'EUR'

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                url,
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
                timeout=5
            )
            if resp.ok:
                print("📤 Telegram message sent! 🎉")
                return
        except Exception as e:
            print(f"❗ Telegram error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    print("❌ Failed to send Telegram message. 😔")

def fetch_mexc_tickers():
    print("🔄 Fetching ALL MEXC tickers...")
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                prices = {}
                for d in data:
                    symbol = d['symbol']
                    norm_sym = normalize_symbol(symbol)
                    if norm_sym.endswith('EUR'):
                        continue
                    if any(norm_sym.endswith(q) for q in QUOTE_CURRENCIES):
                        prices[norm_sym] = {
                            'bid': float(d.get('bidPrice') or 0),
                            'ask': float(d.get('askPrice') or 0),
                            'last': float(d['lastPrice'])
                        }
                print(f"✅ Fetched {len(prices)} MEXC listings. 🎯\n")
                return prices
        except Exception as e:
            print(f"❗ MEXC error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    print("❌ Failed to fetch MEXC after retries. 😔")
    return {}

def fetch_kraken_tickers():
    print("🔄 Fetching ALL Kraken tickers...")
    prices = {}
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get("https://api.kraken.com/0/public/AssetPairs", timeout=10)
            if resp.status_code == 200:
                pairs = list(resp.json()['result'].keys())
                print(f"Kraken has {len(pairs)} pairs. Scanning...")
                batch_size = 20
                for i in range(0, len(pairs), batch_size):
                    batch = ','.join(pairs[i:i+batch_size])
                    time.sleep(0.05)
                    resp_t = requests.get(f"https://api.kraken.com/0/public/Ticker?pair={batch}", timeout=5)
                    if resp_t.status_code == 200:
                        result = resp_t.json()['result']
                        for sym, d in result.items():
                            norm_sym = normalize_symbol(sym)
                            if norm_sym.endswith('EUR'):
                                continue
                            if any(norm_sym.endswith(q) for q in QUOTE_CURRENCIES):
                                bid_price = float(d['b'][0])
                                if bid_price > 0:
                                    prices[norm_sym] = {
                                        'bid': bid_price,
                                        'ask': float(d['a'][0]),
                                        'last': float(d['c'][0])
                                    }
                print(f"✅ Fetched {len(prices)} Kraken listings (USD/USDT only). 🎯\n")
                return prices
        except Exception as e:
            print(f"❗ Kraken error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    print("❌ Failed to fetch Kraken after retries. 😔")
    return {}

def fetch_kucoin_tickers():
    print("🔄 Fetching ALL KuCoin tickers...")
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=10)
            if resp.status_code == 200:
                data = resp.json().get('data', {}).get('ticker', [])
                prices = {}
                for d in data:
                    symbol = d['symbol']
                    norm_sym = normalize_symbol(symbol)
                    if norm_sym.endswith('EUR'):
                        continue
                    if any(norm_sym.endswith(q) for q in QUOTE_CURRENCIES):
                        buy_str = d.get('buy') or '0'
                        sell_str = d.get('sell') or '0'
                        last_str = d.get('last') or '0'
                        prices[norm_sym] = {
                            'bid': float(buy_str),
                            'ask': float(sell_str),
                            'last': float(last_str)
                        }
                print(f"✅ Fetched {len(prices)} KuCoin listings. 🎯\n")
                return prices
        except Exception as e:
            print(f"❗ KuCoin error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    print("❌ Failed to fetch KuCoin after retries. 😔")
    return {}

def normalize_symbol(symbol):
    symbol = symbol.replace('-', '').upper()
    symbol = symbol.replace('XXBT', 'BTC').replace('XBT', 'BTC').replace('ZUSD', 'USD').replace('ZEUR', 'EUR')
    for q in sorted(QUOTE_CURRENCIES, key=len, reverse=True):
        if symbol.endswith(q):
            base = SYMBOL_MAP.get(symbol[:-len(q)], symbol[:-len(q)])
            return f"{base}{q}"
    return symbol

def get_conversion_rate(prices, from_quote, to_quote):
    if from_quote == to_quote:
        return 1.0
    for exch in ['kraken', 'mexc', 'kucoin']:
        pair = f"{from_quote}{to_quote}"
        if pair in prices.get(exch, {}) and prices[exch][pair]['last'] > 0:
            return prices[exch][pair]['last']
        inv_pair = f"{to_quote}{from_quote}"
        if inv_pair in prices.get(exch, {}) and prices[exch][inv_pair]['last'] > 0:
            return 1.0 / prices[exch][inv_pair]['last']
    return None

def check_arbitrage(prices):
    found = 0
    all_bases = set()
    for exch_prices in prices.values():
        for sym in exch_prices:
            for q in sorted(QUOTE_CURRENCIES, key=len, reverse=True):
                if sym.endswith(q):
                    base = sym[:-len(q)]
                    if base in BLACKLIST:
                        continue
                    all_bases.add(base)
                    break
    buy_exchanges = ['mexc']
    sell_exchanges = ['kraken', 'kucoin']
    fees = {
        'mexc': MEXC_TAKER_FEE,
        'kraken': KRAKEN_TAKER_FEE,
        'kucoin': KUCOIN_TAKER_FEE
    }
    for base in all_bases:
        # Main direction: Buy on MEXC → Sell on Kraken/KuCoin
        for buy_exch in buy_exchanges:
            for sell_exch in sell_exchanges:
                buy_sym = buy_quote = sell_sym = sell_quote = None
                for q in QUOTE_CURRENCIES:
                    cand = f"{base}{q}"
                    if cand in prices.get(buy_exch, {}):
                        if buy_sym is None:
                            buy_sym = cand
                            buy_quote = q
                    if cand in prices.get(sell_exch, {}):
                        if sell_sym is None:
                            sell_sym = cand
                            sell_quote = q
                if not buy_sym or not sell_sym:
                    continue
                buy_ask = prices[buy_exch][buy_sym].get('ask') or prices[buy_exch][buy_sym]['last']
                sell_bid = prices[sell_exch][sell_sym].get('bid') or prices[sell_exch][sell_sym]['last']
                if buy_ask <= 0 or sell_bid <= 0:
                    continue
                conv = get_conversion_rate(prices, buy_quote, sell_quote)
                if conv is None:
                    continue
                adjusted_buy = buy_ask * (1 + fees[buy_exch]) * conv
                adjusted_sell = sell_bid * (1 - fees[sell_exch])
                profit_pct = (adjusted_sell - adjusted_buy) / adjusted_buy * 100
                if profit_pct >= THRESHOLD_PERCENT:
                    found += 1
                    msg = (
                        f"*🚀 Arbitrage Opportunity! 🚀*\n"
                        f"💸 *Buy {base}* on {buy_exch.upper()}: {buy_ask:.6f} {buy_quote}\n"
                        f"💰 *Sell on {sell_exch.upper()}*: {sell_bid:.6f} {sell_quote}\n"
                        f"📈 *Profit*: {profit_pct:.2f}% (after fees) 🎉"
                    )
                    print(msg + "\n")
                    send_telegram(msg)
        # Bidirectional MEXC ↔ KuCoin
        for buy_exch, sell_exch in [('mexc', 'kucoin'), ('kucoin', 'mexc')]:
            buy_sym = buy_quote = sell_sym = sell_quote = None
            for q in QUOTE_CURRENCIES:
                cand = f"{base}{q}"
                if cand in prices.get(buy_exch, {}):
                    if buy_sym is None:
                        buy_sym = cand
                        buy_quote = q
                if cand in prices.get(sell_exch, {}):
                    if sell_sym is None:
                        sell_sym = cand
                        sell_quote = q
            if not buy_sym or not sell_sym:
                continue
            buy_ask = prices[buy_exch][buy_sym].get('ask') or prices[buy_exch][buy_sym]['last']
            sell_bid = prices[sell_exch][sell_sym].get('bid') or prices[sell_exch][sell_sym]['last']
            if buy_ask <= 0 or sell_bid <= 0:
                continue
            conv = get_conversion_rate(prices, buy_quote, sell_quote)
            if conv is None:
                continue
            adjusted_buy = buy_ask * (1 + fees[buy_exch]) * conv
            adjusted_sell = sell_bid * (1 - fees[sell_exch])
            profit_pct = (adjusted_sell - adjusted_buy) / adjusted_buy * 100
            if profit_pct >= THRESHOLD_PERCENT:
                found += 1
                msg = (
                    f"*🚀 Arbitrage Opportunity! 🚀*\n"
                    f"💸 *Buy {base}* on {buy_exch.upper()}: {buy_ask:.6f} {buy_quote}\n"
                    f"💰 *Sell on {sell_exch.upper()}*: {sell_bid:.6f} {sell_quote}\n"
                    f"📈 *Profit*: {profit_pct:.2f}% (after fees) 🎉"
                )
                print(msg + "\n")
                send_telegram(msg)
    if found == 0:
        print(f"😴 No opportunities ≥ {THRESHOLD_PERCENT}% found this cycle.\n")
    else:
        print(f"🎉 Found {found} opportunities! 📊\n")

def signal_handler(sig, frame):
    print("\n🛑 Stopping bot... 👋")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    print("🚀 Starting arbitrage bot (Only MEXC + Kraken + KuCoin bidirectional) 🌟\n")
    while True:
        try:
            prices = {
                'mexc': fetch_mexc_tickers(),
                'kraken': fetch_kraken_tickers(),
                'kucoin': fetch_kucoin_tickers()
            }
            check_arbitrage(prices)
            print(f"⏳ Waiting {CHECK_INTERVAL} seconds... 😴\n")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            print("\n🛑 Stopped by user. 👋")
            break
        except Exception as e:
            print(f"❗ Unexpected error: {e}\nContinuing... 😔")
            time.sleep(CHECK_INTERVAL)
```
