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
                            if any(norm_sym.endswith(q) for q in QUOTE_CURRENCIES):
                                bid_price = float(d['b'][0])
                                if bid_price > 0:
                                    prices[norm_sym] = {
                                        'bid': bid_price,
                                        'ask': float(d['a'][0]),
                                        'last': float(d['c'][0])
                                    }
                print(f"✅ Fetched {len(prices)} Kraken listings. 🎯\n")
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

def fetch_bitvavo_tickers():
    print("🔄 Fetching ALL Bitvavo tickers...")
    prices = {}
    for attempt in range(MAX_RETRIES):
        try:
            resp_book = requests.get("https://api.bitvavo.com/v2/ticker/book", timeout=10)
            if resp_book.status_code == 200:
                data_book = resp_book.json()
                for d in data_book:
                    symbol = d['market']
                    norm_sym = normalize_symbol(symbol)
                    if any(norm_sym.endswith(q) for q in QUOTE_CURRENCIES):
                        bid = float(d.get('bid') or 0)
                        ask = float(d.get('ask') or 0)
                        if bid > 0 and ask > 0:
                            prices[norm_sym] = {
                                'bid': bid,
                                'ask': ask,
                                'last': 0
                            }
            resp_price = requests.get("https://api.bitvavo.com/v2/ticker/price", timeout=10)
            if resp_price.status_code == 200:
                data_price = resp_price.json()
                for d in data_price:
                    symbol = d['market']
                    norm_sym = normalize_symbol(symbol)
                    if norm_sym in prices:
                        prices[norm_sym]['last'] = float(d.get('price') or 0)
            print(f"✅ Fetched {len(prices)} Bitvavo listings (with valid bid/ask). 🎯\n")
            return prices
        except Exception as e:
            print(f"❗ Bitvavo error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
    print("❌ Failed to fetch Bitvavo after retries. 😔")
    return {}

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
                print(f"❗ KuCoin currencies endpoint returned status {resp.status_code}")
                time.sleep(2 ** attempt)
                continue

            data_json = resp.json()
            currencies_data = data_json.get('data')

            if currencies_data is None:
                print("❗ KuCoin /currencies returned 'data': null or missing")
                time.sleep(2 ** attempt)
                continue

            if not isinstance(currencies_data, list):
                print(f"❗ KuCoin 'data' is not a list (got {type(currencies_data).__name__})")
                time.sleep(2 ** attempt)
                continue

            currencies = currencies_data

            print(f"→ Found {len(currencies)} currencies to process")

            for curr in currencies:
                coin = curr.get('currency')
                if not coin or not isinstance(coin, str):
                    continue

                norm_coin = SYMBOL_MAP.get(coin, coin)
                if norm_coin in BLACKLIST:
                    continue

                try:
                    detail_resp = requests.get(
                        f"https://api.kucoin.com/api/v3/currencies/{coin}",
                        timeout=5
                    )
                    if detail_resp.status_code != 200:
                        continue

                    detail_json = detail_resp.json()
                    detail_data = detail_json.get('data', {})

                    chains = detail_data.get('chains', [])
                    if not isinstance(chains, list):
                        continue

                    networks = []
                    for chain_item in chains:
                        chain_name = chain_item.get('chainName', '').upper()
                        if not chain_name:
                            continue
                        networks.append({
                            'chain': chain_name,
                            'depositEnable': chain_item.get('isDepositEnabled', False),
                            'withdrawEnable': chain_item.get('isWithdrawEnabled', False)
                        })

                    if networks:
                        config[norm_coin] = networks

                except Exception as detail_err:
                    print(f"  ⚠️ Failed to fetch details for {coin}: {detail_err}")

            if config:
                print(f"✅ Successfully fetched KuCoin config for {len(config)} assets\n")
                return config
            else:
                print("⚠️ No valid network data collected from KuCoin\n")
                return {}

        except Exception as e:
            print(f"❗ KuCoin config fetch error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)

    print("❌ All attempts to fetch KuCoin config failed – using empty config\n")
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
                    norm_coin = SYMBOL_MAP.get(coin, coin).replace('XBT', 'BTC')
                    if norm_coin in BLACKLIST:
                        continue
                    status = info.get('status', 'enabled')
                    deposit_enable = status in ['enabled', 'deposit_only']
                    withdraw_enable = status in ['enabled', 'withdrawal_only']
                    config[norm_coin] = {
                        'depositEnable': deposit_enable,
                        'withdrawEnable': withdraw_enable
                    }
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
                    }
                print(f"✅ Fetched Bitvavo config for {len(config)} assets.\n")
                return config
        except Exception as e:
            print(f"❗ Bitvavo config error (attempt {attempt+1}): {e}")
        time.sleep(2 ** attempt)
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

                buy_cfg = configs.get(buy_exch, {}).get(base)
                sell_cfg = configs.get(sell_exch, {}).get(base)

                if not buy_cfg or not buy_cfg.get('withdrawEnable', False):
                    continue
                if not sell_cfg or not sell_cfg.get('depositEnable', False):
                    continue

                network_note = ""
                skip = False
                if buy_exch in ['mexc', 'kucoin'] and sell_exch in ['mexc', 'kucoin']:
                    buy_networks = buy_cfg if isinstance(buy_cfg, list) else [buy_cfg]
                    sell_networks = sell_cfg if isinstance(sell_cfg, list) else [sell_cfg]
                    has_common, common_chains = has_common_network(buy_networks, sell_networks)
                    if not has_common:
                        skip = True
                    else:
                        network_note = f"\n🔗 Networks match: {', '.join(common_chains)}"
                else:
                    network_note = "\n⚠️ Network match not checked (limited public API for one/both exchanges)"

                if skip:
                    continue

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

        # Bidirectional part (same logic)
        bidirectional_pairs = [
            ('mexc', 'kucoin'), ('kucoin', 'mexc'),
            ('mexc', 'bitvavo'), ('bitvavo', 'mexc'),
            ('kucoin', 'bitvavo'), ('bitvavo', 'kucoin')
        ]
        for buy_exch, sell_exch in bidirectional_pairs:
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

            buy_cfg = configs.get(buy_exch, {}).get(base)
            sell_cfg = configs.get(sell_exch, {}).get(base)

            if not buy_cfg or not buy_cfg.get('withdrawEnable', False):
                continue
            if not sell_cfg or not sell_cfg.get('depositEnable', False):
                continue

            network_note = ""
            skip = False
            if buy_exch in ['mexc', 'kucoin'] and sell_exch in ['mexc', 'kucoin']:
                buy_networks = buy_cfg if isinstance(buy_cfg, list) else [buy_cfg]
                sell_networks = sell_cfg if isinstance(sell_cfg, list) else [sell_cfg]
                has_common, common_chains = has_common_network(buy_networks, sell_networks)
                if not has_common:
                    skip = True
                else:
                    network_note = f"\n🔗 Networks match: {', '.join(common_chains)}"
            else:
                network_note = "\n⚠️ Network match not checked (limited public API for one/both exchanges)"

            if skip:
                continue

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

    if found == 0:
        print(f"😴 No opportunities ≥ {THRESHOLD_PERCENT}% found this cycle.\n")
    else:
        print(f"🎉 Found {found} opportunities! 📊\n")

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
