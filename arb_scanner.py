import requests
import time
import signal
import sys

# === CONFIG ===
BOT_TOKEN = "8212674831:AAFQPexNzzYeprq3J8OuSSNBYsJQE6JM87s"
CHAT_ID = "7297679984"
THRESHOLD_PERCENT = 0
MIN_RAW_SPREAD_PCT = 5.0
MAX_RAW_SPREAD_PCT = 200.0

MIN_KRAKEN_24H_VOLUME_BASE = 10000.0   # min 24h volume in base units for Kraken
MIN_MEXC_24H_VOLUME_USDT   = 50000.0   # min 24h USDT volume for MEXC

CHECK_INTERVAL = 60
MAX_RETRIES = 3

BITVAVO_TAKER_FEE = 0.0025
MEXC_TAKER_FEE    = 0.0005
BINANCE_TAKER_FEE = 0.0010
KRAKEN_TAKER_FEE  = 0.0026

# BLACKLIST HAS BEEN REMOVED

SYMBOL_MAP = {
    'LUNA': 'LUNA',
    'LUNC': 'LUNA',
    'LUNA2': 'LUNA2',
    'BTT': 'BTTC',
}

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
                print("📤 Telegram sent!")
                return
        except Exception as e:
            print(f"Telegram error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    print("❌ Telegram failed.")

def fetch_kraken_usd_to_eur_rate():
    print("Fetching Kraken USD → EUR rate...")
    FIAT_PAIR_ATTEMPTS = ['EURUSD', 'USDEUR', 'ZEURZUSD', 'ZUSDZEUR', 'EUR/USD', 'USD/EUR']
    for pair_try in FIAT_PAIR_ATTEMPTS:
        try:
            url = f"https://api.kraken.com/0/public/Ticker?pair={pair_try}"
            r = requests.get(url, timeout=8)
            data = r.json()
            if 'error' in data and data['error']:
                continue
            result = data.get('result', {})
            if not result:
                continue
            ticker_key = next(iter(result))
            ticker = result[ticker_key]
            c = float(ticker['c'][0])
            if 'EUR' in ticker_key.upper() and 'USD' in ticker_key.upper():
                rate = 1 / c if ('EUR' in ticker_key[:4] or 'ZEUR' in ticker_key) else c
                if rate and 0.5 < rate < 2.0:
                    print(f"→ 1 USD ≈ {rate:.4f} EUR")
                    return rate
        except Exception:
            continue
    print("❌ Failed to get USD/EUR rate from Kraken")
    return None

def fetch_bitvavo_tickers():
    print("Fetching Bitvavo ASK (best offer) from orderbook...")
    prices = {}
    try:
        r = requests.get("https://api.bitvavo.com/v2/ticker/book", timeout=10)
        for d in r.json():
            market = d['market'].upper()
            ask = float(d.get('ask') or 0)
            if ask > 0 and market.endswith('EUR'):
                base = market[:-3]
                prices[base] = ask
        print(f"Bitvavo: {len(prices)} EUR pairs (ASK prices)")
        return prices
    except Exception as e:
        print(f"Bitvavo fetch failed: {e}")
        return {}

def fetch_mexc_bid_and_volume():
    print("Fetching MEXC BID + 24h volume...")
    prices = {}
    try:
        # Real BID
        r = requests.get("https://api.mexc.com/api/v3/ticker/bookTicker", timeout=10)
        for d in r.json():
            sym = d['symbol'].upper()
            if sym.endswith('USDT'):
                base = sym[:-4]
                bid = float(d.get('bidPrice') or 0)
                if bid > 0:
                    prices[base] = {'bid': bid}
        
        # 24h volume filter
        vol_r = requests.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=10)
        for d in vol_r.json():
            sym = d['symbol'].upper()
            if sym.endswith('USDT') and 'quoteVolume' in d:
                base = sym[:-4]
                vol = float(d.get('quoteVolume') or 0)
                if base in prices:
                    prices[base]['vol_usdt'] = vol
        print(f"MEXC: {len(prices)} assets with BID")
        return prices
    except Exception as e:
        print(f"MEXC fetch failed: {e}")
        return {}

def fetch_binance_bid():
    print("Fetching Binance BID...")
    prices = {}
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/bookTicker", timeout=12)
        for d in r.json():
            sym = d['symbol'].upper()
            if sym.endswith('USDT'):
                base = sym[:-4]
                bid = float(d.get('bidPrice') or 0)
                if bid > 0:
                    prices[base] = bid
        print(f"Binance: {len(prices)} USDT pairs (BID prices)")
        return prices
    except Exception as e:
        print(f"Binance fetch failed: {e}")
        return {}

def fetch_kraken_tickers(fiat_rate):
    print("Fetching Kraken BID + 24h volume...")
    prices = {}
    try:
        r = requests.get("https://api.kraken.com/0/public/AssetPairs", timeout=12)
        all_pairs = r.json()['result']
        usd_pairs = [p for p in all_pairs if 'USD' in p or 'ZUSD' in p]

        batch_size = 20
        for i in range(0, len(usd_pairs), batch_size):
            batch = ','.join(usd_pairs[i:i+batch_size])
            time.sleep(0.1)
            rt = requests.get(f"https://api.kraken.com/0/public/Ticker?pair={batch}", timeout=8)
            res = rt.json().get('result', {})
            for sym, d in res.items():
                norm = sym.upper().replace('XBT', 'BTC').replace('XXBT', 'BTC').replace('ZUSD', 'USD')
                if norm.endswith('USD'):
                    base = norm[:-3]
                    bid = float(d['b'][0])
                    vol_24h = float(d['v'][1])
                    if bid > 0:
                        prices[base] = {
                            'bid_eur': bid * fiat_rate if fiat_rate else None,
                            'vol_24h_base': vol_24h
                        }
        print(f"Kraken: {len(prices)} assets with BID")
        return prices
    except Exception as e:
        print(f"Kraken fetch failed: {e}")
        return {}

def normalize_base(s):
    s = s.upper().replace('-', '')
    if s in SYMBOL_MAP:
        s = SYMBOL_MAP[s]
    for old, new in SYMBOL_MAP.items():
        if s == old:
            s = new
    return s

def check_opportunity(buy_price, buy_fee, sell_price, sell_fee, base, buy_exch, sell_exch):
    if not buy_price or not sell_price or buy_price <= 0 or sell_price <= 0:
        return None

    raw_spread_pct = (sell_price - buy_price) / buy_price * 100

    if raw_spread_pct > MAX_RAW_SPREAD_PCT or raw_spread_pct < -MAX_RAW_SPREAD_PCT:
        print(f"Ignored extreme spread {raw_spread_pct:.1f}% on {base} ({buy_exch}→{sell_exch})")
        return None

    if raw_spread_pct < MIN_RAW_SPREAD_PCT:
        return None

    adj_buy = buy_price * (1 + buy_fee)
    adj_sell = sell_price * (1 - sell_fee)
    profit_pct = (adj_sell - adj_buy) / adj_buy * 100

    if profit_pct >= THRESHOLD_PERCENT:
        return {
            'profit': profit_pct,
            'raw': raw_spread_pct,
            'buy_exch': buy_exch,
            'sell_exch': sell_exch,
            'buy_p': buy_price,
            'sell_p': sell_price,
            'base': base
        }
    return None

def check_arbitrage():
    bitvavo = fetch_bitvavo_tickers()
    mexc    = fetch_mexc_bid_and_volume()
    binance = fetch_binance_bid()
    fiat_rate = fetch_kraken_usd_to_eur_rate()
    kraken  = fetch_kraken_tickers(fiat_rate) if fiat_rate else {}

    if not fiat_rate:
        print("⚠️ No USD→EUR rate available — some comparisons skipped")

    found = 0
    all_bases = set(bitvavo.keys()) | set(mexc.keys()) | set(binance.keys()) | set(kraken.keys())

    for base_raw in all_bases:
        base = normalize_base(base_raw)

        b_ask_eur = bitvavo.get(base)
        if not b_ask_eur:
            continue

        # === Bitvavo BUY → MEXC SELL ===
        m_data = mexc.get(base)
        if m_data and 'bid' in m_data and m_data.get('vol_usdt', 0) >= MIN_MEXC_24H_VOLUME_USDT:
            m_bid_eur = m_data['bid'] * fiat_rate
            opp = check_opportunity(b_ask_eur, BITVAVO_TAKER_FEE, m_bid_eur, MEXC_TAKER_FEE,
                                    base, "Bitvavo", "MEXC")
            if opp:
                found += 1
                msg = f"*🚀 Arb Alert!*\nBuy **{opp['base']}** on {opp['buy_exch']} @ €{opp['buy_p']:.6f}\nSell on {opp['sell_exch']} @ €{opp['sell_p']:.6f}\n→ Profit **{opp['profit']:.2f}%** (raw {opp['raw']:.2f}%)"
                print(msg + "\n")
                send_telegram(msg)

        # === Bitvavo BUY → Binance SELL ===
        b_bid = binance.get(base)
        if b_bid:
            b_bid_eur = b_bid * fiat_rate
            opp = check_opportunity(b_ask_eur, BITVAVO_TAKER_FEE, b_bid_eur, BINANCE_TAKER_FEE,
                                    base, "Bitvavo", "Binance")
            if opp:
                found += 1
                msg = f"*🚀 Arb Alert!*\nBuy **{opp['base']}** on {opp['buy_exch']} @ €{opp['buy_p']:.6f}\nSell on {opp['sell_exch']} @ €{opp['sell_p']:.6f}\n→ Profit **{opp['profit']:.2f}%** (raw {opp['raw']:.2f}%)"
                print(msg + "\n")
                send_telegram(msg)

        # === Bitvavo BUY → Kraken SELL ===
        k_data = kraken.get(base)
        if k_data and k_data.get('vol_24h_base', 0) >= MIN_KRAKEN_24H_VOLUME_BASE:
            k_bid_eur = k_data.get('bid_eur')
            if k_bid_eur:
                opp = check_opportunity(b_ask_eur, BITVAVO_TAKER_FEE, k_bid_eur, KRAKEN_TAKER_FEE,
                                        base, "Bitvavo", "Kraken")
                if opp:
                    found += 1
                    msg = f"*🚀 Arb Alert!*\nBuy **{opp['base']}** on {opp['buy_exch']} @ €{opp['buy_p']:.6f}\nSell on {opp['sell_exch']} @ €{opp['sell_p']:.6f}\n→ Profit **{opp['profit']:.2f}%** (raw {opp['raw']:.2f}%)"
                    print(msg + "\n")
                    send_telegram(msg)

    if found == 0:
        print(f"No ≥ {THRESHOLD_PERCENT}% opportunities found (Bitvavo BUY → MEXC/Binance/Kraken SELL)")
    else:
        print(f"Found {found} opportunities!")

def signal_handler(sig, frame):
    print("\nBot stopped.")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    print("🚀 Arb bot running — Buy Bitvavo ASK → Sell MEXC / Binance / Kraken BID")
    print("Blacklist: REMOVED (all coins are now considered)")
    while True:
        try:
            check_arbitrage()
            print(f"Next check in {CHECK_INTERVAL}s...\n")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}\nContinuing...")
            time.sleep(CHECK_INTERVAL)