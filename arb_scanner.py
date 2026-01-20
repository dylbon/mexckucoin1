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

def fetch_mexc_tickers():
    # (unchanged)
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

# Other fetch_tickers functions unchanged: fetch_kraken_tickers, fetch_kucoin_tickers, fetch_bitvavo_tickers

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
            # First get list of currencies
            resp_currencies = requests.get("https://api.kucoin.com/api/v3/currencies", timeout=10)
            if resp_currencies.status_code == 200:
                currencies = resp_currencies.json().get('data', [])
                for curr in currencies:
                    coin = curr['currency']
                    norm_coin = SYMBOL_MAP.get(coin, coin)
                    if norm_coin in BLACKLIST:
                        continue
                    # Fetch details per currency
                    resp_detail = requests.get(f"https://api.kucoin.com/api/v3/currencies/{coin}", timeout=5)
                    if resp_detail.status_code == 200:
                        detail = resp_detail.json().get('data', {})
                        networks = []
                        for chain in detail.get('chains', []):
                            networks.append({
                                'chain': chain['chainName'].upper(),
                                'depositEnable': chain.get('isDepositEnabled', False),
                                'withdrawEnable': chain.get('isWithdrawEnabled', False)
                            })
                        if networks:
                            config[norm_coin] = networks
                print(f"✅ Fetched KuCoin config for {len(config)} assets.\n")
                return config
        except Exception as e:
            print(f"❗ KuCoin config error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    return {}

def fetch_kraken_config():
    print("🔄 Fetching Kraken asset config...")
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get("https://api.kraken.com/0/public/Assets", timeout=10)
            if resp.status_code == 200:
                data = resp.json().get('result', {})
                config = {}
                for coin, info in data.items():
                    norm_coin = SYMBOL_MAP.get(coin, coin).replace('XBT', 'BTC')  # Normalize
                    if norm_coin in BLACKLIST:
                        continue
                    status = info.get('status', 'enabled')
                    deposit_enable = status in ['enabled', 'deposit_only']
                    withdraw_enable = status in ['enabled', 'withdrawal_only']
                    config[norm_coin] = {
                        'depositEnable': deposit_enable,
                        'withdrawEnable': withdraw_enable
                    }  # No chains publicly
                print(f"✅ Fetched Kraken config for {len(config)} assets.\n")
                return config
        except Exception as e:
            print(f"❗ Kraken config error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    return {}

def fetch_bitvavo_config():
    print("🔄 Fetching Bitvavo asset config...")
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get("https://api.bitvavo.com/v2/assets", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                config = {}
                for item in data:
                    coin = item['symbol']
                    norm_coin = SYMBOL_MAP.get(coin, coin)
                    if norm_coin in BLACKLIST:
                        continue
                    deposit_status = item.get('depositStatus', 'OK')
                    withdrawal_status = item.get('withdrawalStatus', 'OK')
                    deposit_enable = deposit_status == 'OK'
                    withdraw_enable = withdrawal_status == 'OK'
                    config[norm_coin] = {
                        'depositEnable': deposit_enable,
                        'withdrawEnable': withdraw_enable
                    }  # No chains
                print(f"✅ Fetched Bitvavo config for {len(config)} assets.\n")
                return config
        except Exception as e:
            print(f"❗ Bitvavo config error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    return {}

def normalize_symbol(symbol):
    # (unchanged)

def get_conversion_rate(prices, from_quote, to_quote):
    # (unchanged)

def has_common_network(buy_config, sell_config):
    if not buy_config or not sell_config:
        return False
    buy_chains = {net['chain'] for net in buy_config if net['withdrawEnable']}
    sell_chains = {net['chain'] for net in sell_config if net['depositEnable']}
    common = buy_chains & sell_chains
    return bool(common), list(common)

def check_arbitrage(prices, configs):
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
    sell_exchanges = ['kraken', 'kucoin', 'bitvavo']
    fees = {
        'mexc': MEXC_TAKER_FEE,
        'kraken': KRAKEN_TAKER_FEE,
        'kucoin': KUCOIN_TAKER_FEE,
        'bitvavo': BITVAVO_TAKER_FEE
    }
    for base in all_bases:
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
                buy_ask = prices[buy_exch][buy_sym].get('ask')
                if buy_ask is None or buy_ask <= 0:
                    buy_ask = prices[buy_exch][buy_sym].get('last')
                    if buy_ask <= 0:
                        continue
                sell_bid = prices[sell_exch][sell_sym].get('bid')
                if sell_bid is None or sell_bid <= 0:
                    sell_bid = prices[sell_exch][sell_sym].get('last')
                    if sell_bid <= 0:
                        continue
                conv = get_conversion_rate(prices, buy_quote, sell_quote)
                if conv is None:
                    continue
                adjusted_buy = buy_ask * (1 + fees[buy_exch]) * conv
                adjusted_sell = sell_bid * (1 - fees[sell_exch])
                profit_pct = (adjusted_sell - adjusted_buy) / adjusted_buy * 100
                if profit_pct < THRESHOLD_PERCENT:
                    continue

                # Status checks
                buy_config = configs.get(buy_exch, {}).get(base)
                sell_config = configs.get(sell_exch, {}).get(base)
                if not buy_config or not buy_config.get('withdrawEnable', False):
                    continue  # Can't withdraw from buy
                if not sell_config or not sell_config.get('depositEnable', False):
                    continue  # Can't deposit to sell

                # Network match (only if both support detailed chains)
                network_note = ""
                if buy_exch in ['mexc', 'kucoin'] and sell_exch in ['mexc', 'kucoin']:
                    has_common, common_chains = has_common_network(buy_config if isinstance(buy_config, list) else [buy_config], 
                                                                   sell_config if isinstance(sell_config, list) else [sell_config])
                    if not has_common:
                        continue
                    network_note = f"\n🔗 Networks match: {', '.join(common_chains)}"
                else:
                    network_note = "\n⚠️ Network match not checked (limited public API for one/both exchanges)"

                found += 1
                msg = (
                    f"*🚀 Arbitrage Opportunity! 🚀*\n"
                    f"💸 *Buy {base}* on {buy_exch.upper()}: {buy_ask:.6f} {buy_quote}\n"
                    f"💰 *Sell on {sell_exch.upper()}*: {sell_bid:.6f} {sell_quote}\n"
                    f"📈 *Profit*: {profit_pct:.2f}% (after fees) 🎉{network_note}\n"
                    f"✅ Deposits/Withdrawals enabled on both."
                )
                print(msg + "\n")
                send_telegram(msg)

        # Bidirectional (similar checks, omitted for brevity; apply same logic)

    if found == 0:
        print(f"😴 No opportunities ≥ {THRESHOLD_PERCENT}% found this cycle.\n")
    else:
        print(f"🎉 Found {found} opportunities! 📊\n")

# signal_handler and main unchanged, but add configs fetch
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
