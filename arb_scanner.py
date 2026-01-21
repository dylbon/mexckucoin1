import requests
import time
import signal
import sys

# === CONFIG ===
BOT_TOKEN = "8212674831:AAFQPexNzzYeprq3J8OuSSNBYsJQE6JM87s"
CHAT_ID = "7297679984"
THRESHOLD_PERCENT = 4.0
MIN_RAW_SPREAD_PCT = 0.8      # ignore tiny differences before fees
CHECK_INTERVAL = 60
MAX_RETRIES = 3

MEXC_TAKER_FEE    = 0.0005
KRAKEN_TAKER_FEE  = 0.0026
BITVAVO_TAKER_FEE = 0.0025

BLACKLIST = {'ALPHA', 'UTK', 'THETA', 'AERGO', 'MOVE'}

# Legacy replacements + explicit LUNA / LUNC mapping
SYMBOL_MAP = {
    'LUNA': 'LUNA',      # Kraken & Bitvavo = Terra Classic
    'LUNC': 'LUNA',      # MEXC LUNC → map to same base as Kraken/Bitvavo
    'LUNA2': 'LUNA2',    # Terra 2.0 stays separate
    'BTT': 'BTTC',
}

QUOTE_CURRENCIES = ['USDT', 'USDC', 'USD', 'EUR']

FIAT_PAIR_ATTEMPTS = ['EURUSD', 'USDEUR', 'ZEURZUSD', 'ZUSDZEUR', 'EUR/USD', 'USD/EUR']

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
            c = float(ticker['c'][0])  # last price
            if 'EUR' in ticker_key.upper() and 'USD' in ticker_key.upper():
                if 'EUR' in ticker_key[:4] or 'ZEUR' in ticker_key:
                    rate = 1 / c if c > 0 else None
                else:
                    rate = c
                if rate and 0.5 < rate < 2.0:
                    print(f"→ 1 USD ≈ {rate:.4f} EUR (pair: {ticker_key})")
                    return rate
        except Exception as e:
            print(f"  Pair {pair_try} failed: {e}")
    print("❌ Failed to get USD/EUR rate from Kraken")
    return None

def fetch_kraken_tickers():
    print("Fetching Kraken BID prices (USD pairs only)...")
    prices = {}  # base → {'bid_usd': float, 'bid_eur': float or None}
    fiat_rate = fetch_kraken_usd_to_eur_rate()

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
                    if bid > 0:
                        prices[base] = {
                            'bid_usd': bid,
                            'bid_eur': bid * fiat_rate if fiat_rate else None
                        }
        print(f"Kraken: {len(prices)} USD-based assets loaded")
        return prices, fiat_rate
    except Exception as e:
        print(f"Kraken fetch failed: {e}")
        return {}, None

def fetch_bitvavo_tickers():
    print("Fetching Bitvavo ASK prices (EUR)...")
    prices = {}
    try:
        r = requests.get("https://api.bitvavo.com/v2/ticker/book", timeout=10)
        for d in r.json():
            market = d['market'].upper()
            ask = float(d.get('ask') or 0)
            if ask > 0 and market.endswith('EUR'):
                base = market[:-3]
                prices[base] = ask
        print(f"Bitvavo: {len(prices)} EUR pairs")
        return prices
    except Exception as e:
        print(f"Bitvavo fetch failed: {e}")
        return {}

def fetch_mexc_tickers():
    print("Fetching MEXC last prices...")
    prices = {}
    try:
        r = requests.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=10)
        data = r.json()
        for d in data:
            sym = d['symbol'].upper()
            if any(sym.endswith(q) for q in ['USDT', 'USD', 'EUR']):
                last = float(d['lastPrice'] or 0)
                if last > 0:
                    if sym.endswith('EUR'):
                        base = sym[:-3]
                        prices[base] = {'eur': last}
                    elif sym.endswith(('USDT', 'USD')):
                        base = sym[:-4] if sym.endswith('USDT') else sym[:-3]
                        prices[base] = {'usd': last}
        print(f"MEXC: {len(prices)} assets")
        return prices
    except Exception as e:
        print(f"MEXC fetch failed: {e}")
        return {}

def normalize_base(s):
    s = s.upper().replace('-', '')
    # First apply explicit symbol remapping (handles LUNC → LUNA etc.)
    if s in SYMBOL_MAP:
        s = SYMBOL_MAP[s]
    # Then any additional legacy replacements if needed
    for old, new in SYMBOL_MAP.items():
        if s == old:
            s = new
    return s

def check_opportunity(buy_price, buy_fee, sell_price, sell_fee, base, buy_exch, sell_exch):
    if not buy_price or not sell_price or buy_price <= 0 or sell_price <= 0:
        return None
    raw_spread_pct = (sell_price - buy_price) / buy_price * 100
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
    mexc    = fetch_mexc_tickers()
    kraken_data, fiat_rate = fetch_kraken_tickers()
    bitvavo = fetch_bitvavo_tickers()

    if not fiat_rate:
        print("No fiat conversion available → skipping Kraken comparisons")
        return

    found = 0
    all_bases = set()
    for d in [mexc, kraken_data, bitvavo]:
        all_bases.update(d.keys())

    for base_raw in all_bases:
        base = normalize_base(base_raw)
        if base in BLACKLIST:
            continue

        # Kraken (converted to EUR)
        k_data = kraken_data.get(base)
        k_eur = k_data['bid_eur'] if k_data and 'bid_eur' in k_data else None

        # Bitvavo (EUR)
        b_eur = bitvavo.get(base)

        # MEXC — prefer EUR if available, else convert USDT≈USD using fiat_rate
        m_data = mexc.get(base)
        m_eur = None
        if m_data:
            if 'eur' in m_data:
                m_eur = m_data['eur']
            elif 'usd' in m_data and fiat_rate:
                m_eur = m_data['usd'] * fiat_rate

        opps = []

        # Bitvavo (EUR ASK) → MEXC (EUR last)
        if b_eur and m_eur:
            opp = check_opportunity(b_eur, BITVAVO_TAKER_FEE, m_eur, MEXC_TAKER_FEE,
                                    base, "Bitvavo", "MEXC")
            if opp: opps.append(opp)

        # Bitvavo (EUR ASK) → Kraken (EUR BID)
        if b_eur and k_eur:
            opp = check_opportunity(b_eur, BITVAVO_TAKER_FEE, k_eur, KRAKEN_TAKER_FEE,
                                    base, "Bitvavo", "Kraken")
            if opp: opps.append(opp)

        # MEXC (EUR) → Kraken (EUR BID)
        if m_eur and k_eur:
            opp = check_opportunity(m_eur, MEXC_TAKER_FEE, k_eur, KRAKEN_TAKER_FEE,
                                    base, "MEXC", "Kraken")
            if opp: opps.append(opp)

        # Kraken (EUR BID) → MEXC (EUR)
        if k_eur and m_eur:
            opp = check_opportunity(k_eur, KRAKEN_TAKER_FEE, m_eur, MEXC_TAKER_FEE,
                                    base, "Kraken", "MEXC")
            if opp: opps.append(opp)

        # Kraken (EUR BID) → Bitvavo (EUR ASK)
        if k_eur and b_eur:
            opp = check_opportunity(k_eur, KRAKEN_TAKER_FEE, b_eur, BITVAVO_TAKER_FEE,
                                    base, "Kraken", "Bitvavo")
            if opp: opps.append(opp)

        for opp in opps:
            found += 1
            msg = (
                f"*🚀 Arb Alert!*\n"
                f"Buy **{opp['base']}** on {opp['buy_exch']} @ €{opp['buy_p']:.6f}\n"
                f"Sell on {opp['sell_exch']} @ €{opp['sell_p']:.6f}\n"
                f"→ Profit **{opp['profit']:.2f}%** (raw spread was {opp['raw']:.2f}%)"
            )
            print(msg + "\n")
            send_telegram(msg)

    if found == 0:
        print(f"No ≥ {THRESHOLD_PERCENT}% opportunities (EUR basis)")
    else:
        print(f"Found {found} opportunities!")

def signal_handler(sig, frame):
    print("\nBot stopped.")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    print("Arb bot running — Kraken USD → EUR converted + Bitvavo/MEXC EUR comparison\n")
    print("LUNA / LUNC normalized to 'LUNA' for cross-exchange matching\n")
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