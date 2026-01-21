import requests
import time
import signal
import sys

# === CONFIG ===
BOT_TOKEN = "8212674831:AAFQPexNzzYeprq3J8OuSSNBYsJQE6JM87s"
CHAT_ID = "7297679984"
THRESHOLD_PERCENT = 3.0
MIN_RAW_SPREAD_PCT = 4.0
MAX_RAW_SPREAD_PCT = 200.0
MIN_KRAKEN_24H_VOLUME_BASE = 10000.0   # minimum 24h volume in base asset units (e.g. 10k tokens/coins)
CHECK_INTERVAL = 60
MAX_RETRIES = 3

MEXC_TAKER_FEE    = 0.0005
KRAKEN_TAKER_FEE  = 0.0026
BITVAVO_TAKER_FEE = 0.0025

BLACKLIST = {
    'ALPHA', 'UTK', 'THETA', 'AERGO', 'MOVE',
    'SRM', 'ACA', 'TUSD', 'MICHI', 'ANLOG', 'EVAA', 'FOREST',
    'HOUSE', 'PDA', 'XL1', 'ELX', 'NEIRO', 'TANSSI', 'ETHW',
    'PIPE', 'FLOW',
    'TAKE', 'CHECK', 'SONIC', 'PORTAL', 'ART', 'UNITE', 'AIO',
    'L3', 'RVV', 'U2U'
}

SYMBOL_MAP = {
    'LUNA': 'LUNA',
    'LUNC': 'LUNA',
    'LUNA2': 'LUNA2',
    'BTT': 'BTTC',
}

QUOTE_CURRENCIES = ['USDT', 'USDC', 'USD', 'EUR']

FIAT_PAIR_ATTEMPTS = ['EURUSD', 'USDEUR', 'ZEURZUSD', 'ZUSDZEUR', 'EUR/USD', 'USD/EUR']

def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=5)
            if resp.ok:
                print("Telegram sent")
                return
        except Exception as e:
            print(f"Telegram error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    print("Telegram failed")

def fetch_kraken_usd_to_eur_rate():
    print("Fetching USD→EUR rate from Kraken...")
    for pair_try in FIAT_PAIR_ATTEMPTS:
        try:
            r = requests.get(f"https://api.kraken.com/0/public/Ticker?pair={pair_try}", timeout=8)
            data = r.json()
            if data.get('error'):
                continue
            result = data.get('result', {})
            if not result: continue
            key = next(iter(result))
            c = float(result[key]['c'][0])
            if 'EUR' in key.upper() and 'USD' in key.upper():
                rate = 1 / c if 'EUR' in key[:4] or 'ZEUR' in key else c
                if 0.5 < rate < 2.0:
                    print(f"1 USD ≈ {rate:.4f} EUR")
                    return rate
        except:
            pass
    print("No USD/EUR rate found")
    return None

def fetch_kraken_tickers():
    print("Kraken USD BID + 24h volume...")
    prices = {}
    fiat_rate = fetch_kraken_usd_to_eur_rate()
    try:
        r = requests.get("https://api.kraken.com/0/public/AssetPairs", timeout=12)
        pairs = [p for p in r.json()['result'] if 'USD' in p or 'ZUSD' in p]
        for i in range(0, len(pairs), 20):
            batch = ','.join(pairs[i:i+20])
            time.sleep(0.1)
            rt = requests.get(f"https://api.kraken.com/0/public/Ticker?pair={batch}", timeout=8)
            for sym, d in rt.json().get('result', {}).items():
                norm = sym.upper().replace('XBT','BTC').replace('XXBT','BTC').replace('ZUSD','USD')
                if norm.endswith('USD'):
                    base = norm[:-3]
                    bid = float(d['b'][0])
                    vol_24h = float(d['v'][1])  # last 24h volume in base currency
                    if bid > 0:
                        prices[base] = {
                            'bid_usd': bid,
                            'bid_eur': bid * fiat_rate if fiat_rate else None,
                            'vol_24h_base': vol_24h
                        }
        print(f"Kraken: {len(prices)} assets with volume")
        return prices, fiat_rate
    except Exception as e:
        print(f"Kraken error: {e}")
        return {}, None

def fetch_bitvavo_tickers():
    print("Bitvavo EUR ASK...")
    prices = {}
    try:
        for d in requests.get("https://api.bitvavo.com/v2/ticker/book", timeout=10).json():
            m = d['market'].upper()
            a = float(d.get('ask') or 0)
            if a > 0 and m.endswith('EUR'):
                prices[m[:-3]] = a
        print(f"Bitvavo: {len(prices)} pairs")
        return prices
    except Exception as e:
        print(f"Bitvavo error: {e}")
        return {}

def fetch_mexc_tickers():
    print("MEXC last prices...")
    prices = {}
    try:
        for d in requests.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=10).json():
            s = d['symbol'].upper()
            last = float(d['lastPrice'] or 0)
            if last <= 0: continue
            if s.endswith('EUR'):
                prices[s[:-3]] = {'eur': last}
            elif s.endswith(('USDT','USD')):
                base_len = -4 if s.endswith('USDT') else -3
                prices[s[:base_len]] = {'usd': last}
        print(f"MEXC: {len(prices)} assets")
        return prices
    except Exception as e:
        print(f"MEXC error: {e}")
        return {}

def normalize_base(s):
    s = s.upper().replace('-','')
    return SYMBOL_MAP.get(s, s)

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
    mexc = fetch_mexc_tickers()
    kraken_data, fiat_rate = fetch_kraken_tickers()
    bitvavo = fetch_bitvavo_tickers()

    if not fiat_rate:
        print("No USD→EUR rate → skipping Kraken")
        return

    found = 0
    all_bases = set(mexc) | set(kraken_data) | set(bitvavo)

    for base_raw in all_bases:
        base = normalize_base(base_raw)
        if base in BLACKLIST:
            continue

        k = kraken_data.get(base)
        if not k:
            continue  # no Kraken data → skip (most comparisons involve Kraken)

        vol_24h = k.get('vol_24h_base', 0)
        if vol_24h < MIN_KRAKEN_24H_VOLUME_BASE:
            # print(f"Skipped low-volume {base}: {vol_24h:.1f} base units")
            continue

        k_eur = k['bid_eur'] if 'bid_eur' in k else None

        b_eur = bitvavo.get(base)

        m = mexc.get(base)
        m_eur = None
        if m:
            if 'eur' in m:
                m_eur = m['eur']
            elif 'usd' in m and fiat_rate:
                m_eur = m['usd'] * fiat_rate

        opps = []

        if b_eur and m_eur:
            o = check_opportunity(b_eur, BITVAVO_TAKER_FEE, m_eur, MEXC_TAKER_FEE, base, "Bitvavo", "MEXC")
            if o: opps.append(o)

        if b_eur and k_eur:
            o = check_opportunity(b_eur, BITVAVO_TAKER_FEE, k_eur, KRAKEN_TAKER_FEE, base, "Bitvavo", "Kraken")
            if o: opps.append(o)

        if m_eur and k_eur:
            o = check_opportunity(m_eur, MEXC_TAKER_FEE, k_eur, KRAKEN_TAKER_FEE, base, "MEXC", "Kraken")
            if o: opps.append(o)

        if k_eur and m_eur:
            o = check_opportunity(k_eur, KRAKEN_TAKER_FEE, m_eur, MEXC_TAKER_FEE, base, "Kraken", "MEXC")
            if o: opps.append(o)

        if k_eur and b_eur:
            o = check_opportunity(k_eur, KRAKEN_TAKER_FEE, b_eur, BITVAVO_TAKER_FEE, base, "Kraken", "Bitvavo")
            if o: opps.append(o)

        for o in opps:
            found += 1
            msg = (
                f"*🚀 Arb!*\n"
                f"Buy {o['base']} on {o['buy_exch']} @ €{o['buy_p']:.6f}\n"
                f"Sell on {o['sell_exch']} @ €{o['sell_p']:.6f}\n"
                f"→ **{o['profit']:.2f}%** profit (raw {o['raw']:.2f}%)"
            )
            print(msg + "\n")
            send_telegram(msg)

    print(f"Found {found} opportunities" if found else f"No ≥{THRESHOLD_PERCENT}% ops (with Kraken vol filter)")

def signal_handler(sig, frame):
    print("\nStopped.")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    print("Running — Kraken USD→EUR + 24h volume filter ≥", MIN_KRAKEN_24H_VOLUME_BASE, "base units")
    print("Blacklisted:", ', '.join(sorted(BLACKLIST)))
    while True:
        try:
            check_arbitrage()
            print(f"Waiting {CHECK_INTERVAL}s...\n")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(CHECK_INTERVAL)