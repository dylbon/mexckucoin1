import ccxt
import time
import telegram
from telegram.ext import Application

# Configuration
TELEGRAM_BOT_TOKEN = '8443986784:AAE7fP0iMoiZZmMSn7AJkT4CvrB2k52ygEE'
TELEGRAM_CHAT_ID = '7297679984'

MIN_SPREAD = 0.01  # % threshold for alert
SCAN_INTERVAL = 30  # seconds between scans

# Initialize exchanges (public endpoints, no API keys)
exchanges = {
    'mexc': ccxt.mexc({'enableRateLimit': True}),
    'kucoin': ccxt.kucoin({'enableRateLimit': True}),
    'binance': ccxt.binance({'enableRateLimit': True})
}

# Telegram setup
app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
bot = app.bot
bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="Bot started! Testing Telegram locally at 2025-10-24 16:39 CEST.")

def send_alert(message):
    """Send Telegram alert"""
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        print(f"Alert sent: {message}")
    except Exception as e:
        print(f"Telegram error: {e}")

def load_common_stable_pairs():
    """Fetch all spot pairs ending with /USDT or /USDC for MEXC and KuCoin"""
    try:
        markets = {}
        mexc_kucoin_pairs = set()
        for name, ex in exchanges.items():
            markets[name] = ex.load_markets()
            pairs = {symbol for symbol, market in markets[name].items() 
                     if market['spot'] and (symbol.endswith('/USDT') or symbol.endswith('/USDC'))}
            if name in ['mexc', 'kucoin']:
                mexc_kucoin_pairs.update(pairs)
            print(f"{name.capitalize()} loaded {len(pairs)} stable spot pairs.")
        
        common_pairs = sorted(mexc_kucoin_pairs)
        print(f"Scanning {len(common_pairs)} total stable spot pairs (MEXC/KuCoin).")
        return common_pairs, markets
    
    except Exception as e:
        print(f"Error loading pairs: {e}")
        return [], {}

# Known fast-chain tokens
FAST_CHAIN_TOKENS = {
    'BONK': 'Solana', 'JUP': 'Solana', 'BOSS': 'Solana',
    'GATA': 'BNB', 'OPEN': 'BNB',
    'SNORT': 'Base/Solana',
    'SOL': 'Solana', 'BNB': 'BNB'
}

def get_chain_hint(pair):
    """Suggest fast chain for a pair"""
    token = pair.split('/')[0]
    return FAST_CHAIN_TOKENS.get(token, 'Unknown (check for SOL/BNB/Base support)')

# Load pairs and markets once at startup
PAIRS, MARKETS = load_common_stable_pairs()

def check_arbitrage():
    """Check for arb opportunities, prioritizing Binance for buys"""
    prices = {}
    for name, ex in exchanges.items():
        prices[name] = {}
        for pair in PAIRS:
            if pair in MARKETS[name]:
                try:
                    ticker = ex.fetch_ticker(pair)
                    prices[name][pair] = ticker['last']
                except Exception as e:
                    prices[name][pair] = None
    
    for pair in PAIRS:
        mexc_price = prices['mexc'].get(pair)
        kucoin_price = prices['kucoin'].get(pair)
        binance_price = prices['binance'].get(pair)
        
        available_prices = []
        if mexc_price and mexc_price > 0:
            available_prices.append(('mexc', mexc_price))
        if kucoin_price and kucoin_price > 0:
            available_prices.append(('kucoin', kucoin_price))
        if binance_price and binance_price > 0:
            available_prices.append(('binance', binance_price))
        
        if len(available_prices) >= 2:
            prices_sorted = sorted(available_prices, key=lambda x: x[1])
            buy_ex, buy_price = prices_sorted[0]
            sell_ex, sell_price = prices_sorted[-1]
            
            # Prioritize Binance for buying if within 5% of lowest
            if binance_price and buy_ex != 'binance':
                binance_spread = ((sell_price - binance_price) / binance_price) * 100
                if binance_spread > MIN_SPREAD and binance_price <= buy_price * 1.05:
                    buy_ex, buy_price = 'binance', binance_price
            
            spread = ((sell_price - buy_price) / buy_price) * 100
            if spread > MIN_SPREAD:
                chain_hint = get_chain_hint(pair)
                binance_note = " (Funds on Binance ready)" if buy_ex == 'binance' else " (Transfer from Binance if needed)"
                message = (f"🚨 ARB ALERT: Buy {pair} on {buy_ex.upper()} (${buy_price:.6f}), "
                          f"Sell on {sell_ex.upper()} (${sell_price:.6f})\n"
                          f"Spread: {spread:.2f}%{binance_note}\n"
                          f"Chain: {chain_hint}\n"
                          f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                send_alert(message)
                print(f"Opportunity: {pair} ({buy_ex} → {sell_ex}) - {spread:.2f}%")
    
    print(f"Scan complete at {time.strftime('%Y-%m-%d %H:%M:%S')}. Next in {SCAN_INTERVAL}s...")

if __name__ == "__main__":
    if not PAIRS:
        print("No pairs found. Check network or exchange APIs.")
    else:
        print(f"Starting MEXC-KuCoin-Binance All Stable Pairs Arb Scanner ({len(PAIRS)} pairs)...")
        while True:
            check_arbitrage()
            time.sleep(SCAN_INTERVAL)
