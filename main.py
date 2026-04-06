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
RISK_PER_TRADE = 0.01  # 1% risk
HEADERS = {"Authorization": f"Bearer {OANDA_TOKEN}"}

# ========================
# GET ALL FOREX INSTRUMENTS
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
    
    # RSI (7)
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(7).mean()
    avg_loss = loss.rolling(7).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # ADX (7)
    df['tr'] = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    df['+dm'] = df['high'].diff()
    df['-dm'] = -df['low'].diff()
    df['+dm'] = df['+dm'].where((df['+dm'] > df['-dm']) & (df['+dm'] > 0), 0)
    df['-dm'] = df['-dm'].where((df['-dm'] > df['+dm']) & (df['-dm'] > 0), 0)
    tr7 = df['tr'].rolling(7).sum()
    plus_di = 100 * (df['+dm'].rolling(7).sum() / tr7)
    minus_di = 100 * (df['-dm'].rolling(7).sum() / tr7)
    df['adx'] = abs(plus_di - minus_di) / (plus_di + minus_di) * 100
    
    # Bollinger Bands (14, 2)
    df['bb_middle'] = df['close'].rolling(14).mean()
    df['bb_std'] = df['close'].rolling(14).std()
    df['bb_high'] = df['bb_middle'] + 2 * df['bb_std']
    df['bb_low'] = df['bb_middle'] - 2 * df['bb_std']
    df['bb_width'] = (df['bb_high'] - df['bb_low']) / df['close']
    
    # ATR (7)
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
    if last['adx'] < 20 or last['bb_width'] < 0.01 or 45 < last['rsi'] < 55:
        return None
    if last['ema50'] > last['ema100'] and last['rsi'] > 55 and last['close'] > last['bb_high']:
        return "buy"
    if last['ema50'] < last['ema100'] and last['rsi'] < 45 and last['close'] < last['bb_low']:
        return "sell"
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
    stop_loss_pips = atr * 2
    risk_amount = balance * RISK_PER_TRADE
    units = risk_amount / stop_loss_pips
    return int(units)

# ========================
# PLACE ORDER
# ========================
def place_trade(pair, signal, units, price, atr):
    stop_loss = price - atr*2 if signal=="buy" else price + atr*2
    data = {
        "order": {
            "instrument": pair,
            "units": str(units if signal=="buy" else -units),
            "type": "MARKET",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": str(stop_loss)}
        }
    }
    url = f"{OANDA_API}/accounts/{ACCOUNT_ID}/orders"
    r = requests.post(url, headers=HEADERS, json=data)
    print(pair, signal.upper(), "Units:", units, "SL:", stop_loss, "Status:", r.status_code)

# ========================
# MAIN BOT LOOP
# ========================
def run_bot():
    balance = get_balance()  # dynamic equity only
    for pair in PAIR_LIST:
        try:
            df = add_indicators(get_candles(pair))
            last = df.iloc[-1]
            signal = get_signal(last)
            if signal:
                atr = last['atr']
                price = last['close']
                units = calculate_units(balance, atr)
                place_trade(pair, signal, units, price, atr)
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
    except Exception as e:
        print("Bot error:", e)
    time.sleep(60)
