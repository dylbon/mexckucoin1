import requests
import time
import signal
import sys

# === CONFIG ===
BOT_TOKEN = "8212674831:AAFQPexNzzYeprq3J8OuSSNBYsJQE6JM87s"
CHAT_ID = "7297679984"
THRESHOLD_PERCENT = 3.0
CHECK_INTERVAL = 60
MAX_RETRIES = 3

MEXC_TAKER_FEE    = 0.0005
KRAKEN_TAKER_FEE  = 0.0026
BITVAVO_TAKER_FEE = 0.0025

BLACKLIST = {'ALPHA', 'UTK', 'THETA', 'AERGO', 'MOVE'}

SYMBOL_MAP = {
    'LUNA': 'LUNC',
    'LUNA2': 'LUNA',
    'BTT': 'BTTC',
    'NANO': 'XNO',
}

QUOTE_CURRENCIES = ['USDT', 'USDC', 'USD', 'EUR']

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

def fetch_mexc_tickers():
    print("Fetching MEXC last prices...")
    try:
        r = requests.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=10)
        data = r.json()
        prices = {}
        for d in data:
            sym = d['symbol'].upper()
            if any(sym.endswith(q) for q in QUOTE_CURRENCIES):
                last = float(d['lastPrice'] or 0)
                if last > 0:
                    prices[sym] = last
        print(f"MEXC: {len(prices)} valid pairs")
        return prices
    except Exception as e:
        print(f"MEXC fetch failed: {e}")
        return {}

def fetch_kraken_tickers():
    print("Fetching Kraken BID prices...")
    prices = {}
    try:
        r = requests.get("https://api.kraken.com/0/public/AssetPairs", timeout=10)
        pairs = list(r.json()['result'].keys())
        batch_size = 20
        for i in range(0, len(pairs), batch_size):
            batch = ','.join(pairs[i:i+batch_size])
            time.sleep(0.1)
            rt = requests.get(f"https://api.kraken.com/0/public/Ticker?pair={batch}", timeout=8)
            res = rt.json().get('result', {})
            for sym, d in res.items():
                norm = sym.upper().replace('XBT', 'BTC').replace('XXBT', 'BTC')
                if any(norm.endswith(q) for q in QUOTE_CURRENCIES):
                    bid = float(d['b'][0])
                    if bid > 0:
                        prices[norm] = bid
        print(f"Kraken: {len(prices)} valid BID prices")
        return prices
    except Exception as e:
        print(f"Kraken fetch failed: {e}")
        return {}

def fetch_bitvavo_tickers():
    print("Fetching Bitvavo ASK prices...")
    prices = {}
    try:
        r = requests.get("https://api.bitvavo.com/v2/ticker/book", timeout=10)
        for d in r.json():
            market = d['market'].upper()
            ask = float(d.get('ask') or 0)
            if ask > 0 and any(market.endswith(q) for q in QUOTE_CURRENCIES):
                prices[market] = ask
        print(f"Bitvavo: {len(prices)} valid ASK prices")
        return prices
    except Exception as e:
        print(f"Bitvavo fetch failed: {e}")
        return {}

def normalize_symbol(s):
    s = s.upper().replace('-', '').replace('XXBT', 'BTC').replace('XBT', 'BTC')
    for q in sorted(QUOTE_CURRENCIES, key=len, reverse=True):
        if s.endswith(q):
            base = SYMBOL_MAP.get(s[:-len(q)], s[:-len(q)])
            return f"{base}{q}"
    return s

def check_opportunity(buy_price, buy_fee, sell_price, sell_fee, base, quote, buy_exch, sell_exch):
    if not buy_price or not sell_price or buy_price <= 0 or sell_price <= 0:
        return None
    adj_buy = buy_price * (1 + buy_fee)
    adj_sell = sell_price * (1 - sell_fee)
    profit_pct = (adj_sell - adj_buy) / adj_buy * 100
    if profit_pct >= THRESHOLD_PERCENT:
        return {
            'profit': profit_pct,
            'buy_exch': buy_exch,
            'sell_exch': sell_exch,
            'buy_price': buy_price,
            'sell_price': sell_price,
            'quote': quote
        }
    return None

def check_arbitrage():
    mexc    = fetch_mexc_tickers()
    kraken  = fetch_kraken_tickers()
    bitvavo = fetch_bitvavo_tickers()

    if not (mexc or kraken or bitvavo):
        print("No usable data → skipping cycle")
        return

    all_pairs = set(mexc.keys()) | set(kraken.keys()) | set(bitvavo.keys())
    found = 0

    for pair in all_pairs:
        norm_pair = normalize_symbol(pair)
        base, quote = None, None
        for q in QUOTE_CURRENCIES:
            if norm_pair.endswith(q):
                base = norm_pair[:-len(q)]
                quote = q
                break
        if not base or base in BLACKLIST:
            continue

        p_mexc    = mexc.get(norm_pair) or mexc.get(pair)
        p_kraken  = kraken.get(norm_pair) or kraken.get(pair)
        p_bitvavo = bitvavo.get(norm_pair) or bitvavo.get(pair)

        opps = []

        # ── MEXC / Kraken ───────────────────────────────────────
        if p_mexc and p_kraken:
            # Buy MEXC → Sell Kraken (most realistic)
            opp = check_opportunity(p_mexc, MEXC_TAKER_FEE, p_kraken, KRAKEN_TAKER_FEE,
                                    base, quote, "MEXC", "Kraken")
            if opp: opps.append(opp)

        if p_kraken and p_mexc:
            # Buy Kraken → Sell MEXC (usually less attractive, but kept)
            opp = check_opportunity(p_kraken, KRAKEN_TAKER_FEE, p_mexc, MEXC_TAKER_FEE,
                                    base, quote, "Kraken", "MEXC")
            if opp: opps.append(opp)

        # ── MEXC / Bitvavo ──────────────────────────────────────
        if p_bitvavo and p_mexc:
            # Buy Bitvavo ASK → Sell MEXC last  ← ONLY THIS DIRECTION KEPT
            opp = check_opportunity(p_bitvavo, BITVAVO_TAKER_FEE, p_mexc, MEXC_TAKER_FEE,
                                    base, quote, "Bitvavo", "MEXC")
            if opp: opps.append(opp)

        # ── Bitvavo / Kraken ────────────────────────────────────
        if p_bitvavo and p_kraken:
            # Buy Bitvavo ASK → Sell Kraken BID  ← usually best direction
            opp = check_opportunity(p_bitvavo, BITVAVO_TAKER_FEE, p_kraken, KRAKEN_TAKER_FEE,
                                    base, quote, "Bitvavo", "Kraken")
            if opp: opps.append(opp)

        if p_kraken and p_bitvavo:
            # Buy Kraken BID → Sell Bitvavo ASK  ← usually worse
            opp = check_opportunity(p_kraken, KRAKEN_TAKER_FEE, p_bitvavo, BITVAVO_TAKER_FEE,
                                    base, quote, "Kraken", "Bitvavo")
            if opp: opps.append(opp)

        for opp in opps:
            found += 1
            msg = (
                f"*🚀 Arb Alert!*\n"
                f"Buy **{base}** on {opp['buy_exch']} @ {opp['buy_price']:.6f} {quote}\n"
                f"Sell on {opp['sell_exch']} @ {opp['sell_price']:.6f} {quote}\n"
                f"→ Profit **{opp['profit']:.2f}%** (after taker fees)"
            )
            print(msg + "\n")
            send_telegram(msg)

    if found == 0:
        print(f"No ≥ {THRESHOLD_PERCENT}% opportunities this run")
    else:
        print(f"Found {found} opportunities!")

def signal_handler(sig, frame):
    print("\nBot stopped.")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    print("Arb bot running: Bitvavo→MEXC + Kraken↔MEXC + Bitvavo↔Kraken\n")
    while True:
        try:
            check_arbitrage()
            print(f"Next check in {CHECK_INTERVAL}s...\n")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}\nContinuing anyway...")
            time.sleep(CHECK_INTERVAL)