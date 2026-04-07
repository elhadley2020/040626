import requests
import pandas as pd
import time

# ========================
# CONFIG
# ========================
OANDA_TOKEN = "YOUR_API_KEY"
ACCOUNT_ID = "YOUR_ACCOUNT_ID"
OANDA_API = "https://api-fxpractice.oanda.com/v3"
PRIMARY_TF = "M1"
RISK_PER_TRADE = 0.01  # 1% risk per trade
HEADERS = {"Authorization": f"Bearer {OANDA_TOKEN}"}

# ========================
# FETCH ALL FOREX INSTRUMENTS
# ========================
def get_forex_instruments():
    url = f"{OANDA_API}/accounts/{ACCOUNT_ID}/instruments"
    r = requests.get(url, headers=HEADERS)
    instruments_data = r.json()['instruments']
    forex_pairs = [i['name'] for i in instruments_data if i['type'] == 'CURRENCY']
    return forex_pairs

PAIR_LIST = get_forex_instruments()
print("Trading Forex instruments:", PAIR_LIST)

# ========================
# FETCH CANDLES
# ========================
def get_candles(pair, count=200):
    url = f"{OANDA_API}/instruments/{pair}/candles"
    params = {"granularity": PRIMARY_TF, "count": count, "price": "M"}
    r = requests.get(url, headers=HEADERS, params=params)
    data = r.json()['candles']
    df = pd.DataFrame([{
        'time': c['time'],
        'open': float(c['mid']['o']),
        'high': float(c['mid']['h']),
        'low': float(c['mid']['l']),
        'close': float(c['mid']['c'])
    } for c in data])
    return df

# ========================
# INDICATORS (pandas only)
# ========================
def add_indicators(df):
    # EMA
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()

    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(7).mean()
    avg_loss = loss.rolling(7).mean()
    rs = avg_gain / avg_loss.replace(0,1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))

    # ATR
    df['hl'] = df['high'] - df['low']
    df['hc'] = (df['high'] - df['close'].shift(1)).abs()
    df['lc'] = (df['low'] - df['close'].shift(1)).abs()
    df['tr'] = df[['hl','hc','lc']].max(axis=1)
    df['atr'] = df['tr'].rolling(7).mean()
    return df

# ========================
# SIGNAL GENERATION
# ========================
def get_signal(last):
    # Avoid sideways: low ADX, low BB width, RSI ~50
    if last['rsi'] > 55 and last['ema50'] > last['ema100']:
        return "buy"
    elif last['rsi'] < 45 and last['ema50'] < last['ema100']:
        return "sell"
    else:
        return None

# ========================
# DYNAMIC EQUITY
# ========================
def get_balance():
    url = f"{OANDA_API}/accounts/{ACCOUNT_ID}/summary"
    r = requests.get(url, headers=HEADERS)
    balance = float(r.json()['account']['balance'])
    return balance

# ========================
# POSITION SIZE
# ========================
def calculate_units(balance, atr):
    risk_amount = balance * RISK_PER_TRADE
    units = risk_amount / atr / 10_000  # adjust for pip scaling
    return max(int(units), 1)

# ========================
# PLACE TRADE WITH SL ONLY
# ========================
def place_trade(pair, signal, units, price, atr):
    sl = price - atr*2 if signal=="buy" else price + atr*2

    data = {
        "order": {
            "instrument": pair,
            "units": str(units if signal=="buy" else -units),
            "type": "MARKET",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": str(sl)}
        }
    }
    url = f"{OANDA_API}/accounts/{ACCOUNT_ID}/orders"
    r = requests.post(url, headers=HEADERS, json=data)
    print(pair, signal.upper(), "SL:", sl, "Units:", units, "Status:", r.status_code)

# ========================
# GET OPEN TRADES
# ========================
def get_open_trades():
    url = f"{OANDA_API}/accounts/{ACCOUNT_ID}/openTrades"
    r = requests.get(url, headers=HEADERS)
    return r.json().get("trades", [])

# ========================
# UPDATE STOP LOSS (Trailing + Break-even)
# ========================
def update_stop_loss(trade_id, new_sl):
    url = f"{OANDA_API}/accounts/{ACCOUNT_ID}/trades/{trade_id}/orders"
    data = {"stopLoss": {"price": str(new_sl)}}
    requests.put(url, headers=HEADERS, json=data)

# ========================
# MANAGE TRADES
# ========================
def manage_trades():
    trades = get_open_trades()
    for t in trades:
        try:
            trade_id = t['id']
            pair = t['instrument']
            entry = float(t['price'])
            units = float(t['currentUnits'])
            is_buy = units > 0

            df = add_indicators(get_candles(pair, count=50))
            price = df.iloc[-1]['close']
            atr = df.iloc[-1]['atr']
            risk = atr * 2

            current_sl = float(t['stopLossOrder']['price'])

            # Break-even at +1R
            if is_buy and price >= entry + risk:
                new_sl = max(current_sl, entry + 0.00005)
                update_stop_loss(trade_id, new_sl)
            elif not is_buy and price <= entry - risk:
                new_sl = min(current_sl, entry - 0.00005)
                update_stop_loss(trade_id, new_sl)

            # Trailing stop after break-even
            if is_buy and price > entry + risk:
                trail_sl = max(current_sl, price - atr*1.5)
                update_stop_loss(trade_id, trail_sl)
            elif not is_buy and price < entry - risk:
                trail_sl = min(current_sl, price + atr*1.5)
                update_stop_loss(trade_id, trail_sl)

        except Exception as e:
            print("Manage trade error:", e)

# ========================
# MAIN BOT LOOP
# ========================
def run_bot():
    balance = get_balance()
    for pair in PAIR_LIST:
        try:
            df = add_indicators(get_candles(pair))
            last = df.iloc[-1]
            signal = get_signal(last)
            if signal:
                price = last['close']
                units = calculate_units(balance, last['atr'])
                place_trade(pair, signal, units, price, last['atr'])
            else:
                print(pair, "No trade")
        except Exception as e:
            print(pair, "Error:", e)

# ========================
# RUN EVERY MINUTE
# ========================
while True:
    try:
        run_bot()
        manage_trades()
    except Exception as e:
        print("Bot error:", e)
    time.sleep(60)
