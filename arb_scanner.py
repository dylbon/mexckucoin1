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
MEXC_TAKER_FEE = 0.0005
KRAKEN_TAKER_FEE = 0.0026
KUCOIN_TAKER_FEE = 0.001
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
                print("📤 Telegram message sent! 🎉")
                return
        except Exception as e:
            print(f"❗ Telegram error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    print("❌ Failed to send Telegram message. 😔")

# fetch_mexc_tickers unchanged...

# fetch_kraken_tickers unchanged...

# fetch_kucoin_tickers unchanged...

# fetch_bitvavo_tickers unchanged...

def fetch_mexc_config():
    print("🔄 Fetching MEXC asset config...")
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get("https://api.mexc.com/api/v3/capital/config/getall", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                config = {}
                for item in data:
                    coin = item['coin']
                    norm_coin = SYMBOL_MAP.get(coin, coin)
                    if norm_coin in BLACKLIST:
                        continue
                    networks = []
                    for net in item.get('networkList', []):
                        networks.append({
                            'chain': net['network'].upper(),
                            'depositEnable': net.get('depositEnable', False),
                            'withdrawEnable': net.get('withdrawEnable', False)
                        })
                    if networks:
                        config[norm_coin] = networks
                print(f"✅ Fetched MEXC config for {len(config)} assets.\n")
                return config
        except Exception as e:
            print(f"❗ MEXC config error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    return {}

def fetch_kucoin_config():
    print("🔄 Fetching KuCoin asset config...")
    config = {}
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get("https://api.kucoin.com/api/v3/currencies", timeout=10)
            if resp.status_code != 200:
                print(f"❗ KuCoin currencies list status {resp.status_code}")
                continue

            data_json = resp.json()
            currencies = data_json.get('data', [])

            if not isinstance(currencies, list):
                print(f"❗ KuCoin 'data' not list (type: {type(currencies).__name__})")
                continue

            print(f"→ Found {len(currencies)} currencies in list")

            # To avoid 2000+ requests: only fetch details for coins we actually care about
            # (we'll populate this later from prices, but for now assume we need many)
            processed = 0
            failed = 0

            for curr in currencies:
                coin = curr.get('currency')
                if not coin or not isinstance(coin, str):
                    continue

                norm_coin = SYMBOL_MAP.get(coin, coin)
                if norm_coin in BLACKLIST:
                    continue

                # Rate limit friendly sleep
                time.sleep(0.3)  # ~3 req/s - safe for public limits

                try:
                    detail_resp = requests.get(
                        f"https://api.kucoin.com/api/v3/currencies/{coin}",
                        timeout=8
                    )
                    if detail_resp.status_code != 200:
                        failed += 1
                        continue

                    detail_json = detail_resp.json()
                    detail_data = detail_json.get('data', {})

                    chains = detail_data.get('chains', [])
                    if not isinstance(chains, list):
                        failed += 1
                        continue

                    networks = []
                    for chain_item in chains:
                        chain_name = chain_item.get('chainName', '').upper()
                        if chain_name:
                            networks.append({
                                'chain': chain_name,
                                'depositEnable': chain_item.get('isDepositEnabled', False),
                                'withdrawEnable': chain_item.get('isWithdrawEnabled', False)
                            })

                    if networks:
                        config[norm_coin] = networks
                        processed += 1

                    if processed % 100 == 0 and processed > 0:
                        print(f"  → Processed {processed} coins successfully")

                except Exception as detail_err:
                    failed += 1
                    print(f"  ⚠️ Detail fetch failed for {coin}: {detail_err}")

            print(f"→ Processed {processed} / attempted many | Failed {failed}")
            if config:
                print(f"✅ Fetched KuCoin config for {len(config)} assets\n")
                return config
            else:
                print("⚠️ No KuCoin networks fetched\n")
                return {}

        except Exception as e:
            print(f"❗ KuCoin config error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)

    print("❌ KuCoin config failed after retries – using empty\n")
    return {}

def fetch_kraken_config():
    # unchanged...

def fetch_bitvavo_config():
    # unchanged...

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
    for exch in ['kraken', 'mexc', 'kucoin', 'bitvavo']:
        pair = f"{from_quote}{to_quote}"
        if pair in prices.get(exch, {}) and prices[exch][pair]['last'] > 0:
            return prices[exch][pair]['last']
        inv_pair = f"{to_quote}{from_quote}"
        if inv_pair in prices.get(exch, {}) and prices[exch][inv_pair]['last'] > 0:
            return 1.0 / prices[exch][inv_pair]['last']
    return None

def has_common_network(buy_networks, sell_networks):
    buy_chains = {net['chain'] for net in buy_networks if net['withdrawEnable']}
    sell_chains = {net['chain'] for net in sell_networks if net['depositEnable']}
    common = buy_chains & sell_chains
    return bool(common), list(common)

def check_arbitrage(prices, configs):
    # unchanged from previous version (full logic as before)...

    # ... (the rest of check_arbitrage remains the same)

def signal_handler(sig, frame):
    print("\n🛑 Stopping bot... 👋")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    print("🚀 Starting arbitrage bot (MEXC + Kraken + KuCoin + Bitvavo) 🌟\n")
    while True:
        try:
            prices = {
                'mexc': fetch_mexc_tickers(),
                'kraken': fetch_kraken_tickers(),
                'kucoin': fetch_kucoin_tickers(),
                'bitvavo': fetch_bitvavo_tickers()
            }
            configs = {
                'mexc': fetch_mexc_config(),
                'kraken': fetch_kraken_config(),
                'kucoin': fetch_kucoin_config(),
                'bitvavo': fetch_bitvavo_config()
            }
            check_arbitrage(prices, configs)
            print(f"⏳ Waiting {CHECK_INTERVAL} seconds... 😴\n")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            print("\n🛑 Stopped by user. 👋")
            break
        except Exception as e:
            print(f"❗ Unexpected error: {e}\nContinuing... 😔")
            time.sleep(CHECK_INTERVAL)
