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

BITVAVO_TAKER_FEE = 0.0025
BINANCE_TAKER_FEE = 0.0010
MEXC_TAKER_FEE    = 0.0005

# Symbol mapping for mismatches
SYMBOL_MAP = {
    'LUNA': 'LUNC',
    'LUNA2': 'LUNA',
    'BTT': 'BTTC',
    'FUN': 'FUNTOKEN',
    'HNT': 'HNT',
    'UP': 'SUPERFORM'
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
                print("📤 Telegram message sent successfully! 🎉")
                return
            else:
                print(f"❗ Telegram send error: {resp.status_code}")
        except Exception as e:
            print(f"❗ Telegram send error (attempt {attempt + 1}): {e}")
        time.sleep(1 ** attempt)
    print("❌ Failed to send Telegram message after retries.")

def fetch_binance_usd_to_eur_rate():
    print("🔄 Fetching Binance EURUSDT rate first...")
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=EURUSDT", timeout=8)
            rate = 1.0 / float(r.json()['price'])
            print(f"✅ 1 USD ≈ {rate:.4f} EUR")
            return rate
        except Exception as e:
            print(f"❗ Rate fetch failed (attempt {attempt+1}): {e}")
        time.sleep(1 ** attempt)
    print("❌ Failed to get EURUSDT rate from Binance")
    return None

def fetch_bitvavo_ask():
    print("🔄 Fetching Bitvavo ASK (best offer) from orderbook...")
    prices = {}
    try:
        r = requests.get("https://api.bitvavo.com/v2/ticker/book", timeout=10)
        for d in r.json():
            market = d.get('market', '').upper()
            ask = float(d.get('ask') or 0)
            if ask > 0 and market.endswith('EUR'):
                base = market[:-3]
                prices[base] = ask
        print(f"✅ Fetched {len(prices)} Bitvavo ASK prices (EUR)")
        return prices
    except Exception as e:
        print(f"❗ Bitvavo fetch error: {e}")
        return {}

def fetch_mexc_bid():
    print("🔄 Fetching MEXC BID...")
    prices = {}
    try:
        r = requests.get("https://api.mexc.com/api/v3/ticker/bookTicker", timeout=10)
        for d in r.json():
            sym = d['symbol'].upper()
            if sym.endswith('USDT'):
                base = sym[:-4]
                bid = float(d.get('bidPrice') or 0)
                if bid > 0:
                    prices[base] = bid
        print(f"✅ Fetched {len(prices)} MEXC BID prices")
        return prices
    except Exception as e:
        print(f"❗ MEXC fetch error: {e}")
        return {}

def fetch_binance_bid():
    print("🔄 Fetching Binance BID...")
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
        print(f"✅ Fetched {len(prices)} Binance BID prices")
        return prices
    except Exception as e:
        print(f"❗ Binance fetch error: {e}")
        return {}

def normalize_base(s):
    s = s.upper().replace('-', '')
    if s in SYMBOL_MAP:
        s = SYMBOL_MAP[s]
    for old, new in SYMBOL_MAP.items():
        if s == old:
            s = new
    return s

def check_arbitrage():
    fiat_rate = fetch_binance_usd_to_eur_rate()
    if not fiat_rate:
        print("⚠️ No EUR rate available — skipping cycle")
        return

    bitvavo = fetch_bitvavo_ask()
    mexc    = fetch_mexc_bid()
    binance = fetch_binance_bid()

    found = 0
    all_bases = set(bitvavo.keys()) | set(mexc.keys()) | set(binance.keys())

    for base_raw in all_bases:
        base = normalize_base(base_raw)
        b_ask_eur = bitvavo.get(base)
        if not b_ask_eur:
            continue

        # === Bitvavo BUY → MEXC SELL ===
        m_bid = mexc.get(base)
        if m_bid:
            m_bid_eur = m_bid * fiat_rate
            profit = ((m_bid_eur * (1 - MEXC_TAKER_FEE)) - (b_ask_eur * (1 + BITVAVO_TAKER_FEE))) / (b_ask_eur * (1 + BITVAVO_TAKER_FEE)) * 100
            if profit >= THRESHOLD_PERCENT:
                found += 1
                msg = f"*🚀 Arb Alert!*\nBuy **{base}** on Bitvavo @ €{b_ask_eur:.6f}\nSell on MEXC @ €{m_bid_eur:.6f}\n→ Profit **{profit:.2f}%**"
                print(msg + "\n")
                send_telegram(msg)

        # === Bitvavo BUY → Binance SELL ===
        b_bid = binance.get(base)
        if b_bid:
            b_bid_eur = b_bid * fiat_rate
            profit = ((b_bid_eur * (1 - BINANCE_TAKER_FEE)) - (b_ask_eur * (1 + BITVAVO_TAKER_FEE))) / (b_ask_eur * (1 + BITVAVO_TAKER_FEE)) * 100
            if profit >= THRESHOLD_PERCENT:
                found += 1
                msg = f"*🚀 Arb Alert!*\nBuy **{base}** on Bitvavo @ €{b_ask_eur:.6f}\nSell on Binance @ €{b_bid_eur:.6f}\n→ Profit **{profit:.2f}%**"
                print(msg + "\n")
                send_telegram(msg)

    if found == 0:
        print(f"✅ No opportunities ≥ {THRESHOLD_PERCENT}% this cycle.\n")
    else:
        print(f"📊 Found {found} arbitrage opportunities!\n")

def signal_handler(sig, frame):
    print("\n🛑 Bot stopped.")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    print("🚀 Arb bot running — BUY Bitvavo ASK → SELL MEXC / Binance BID")
    print("Using original Telegram bot • No blacklist • No volume filters")
    while True:
        try:
            check_arbitrage()
            print(f"⏳ Next check in {CHECK_INTERVAL} seconds...\n")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❗ Error: {e}\nContinuing...")
            time.sleep(CHECK_INTERVAL)