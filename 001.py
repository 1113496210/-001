# ==========================================
# AltCoin Futures Signal Monitor
# Version: V2.0 Strict Trigger (Core + Auxiliary)
# ==========================================

import requests
import time
import datetime
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header
from email.utils import formataddr

# ========== 通知配置 ==========
TG_BOT_TOKEN = "8557301222:AAHj1rSQ63zJGFXVxxuTniwRP2Y1tj3QsAs"
TG_CHAT_ID = "5408890841"

SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
EMAIL_SENDER = "1113496210@qq.com"
EMAIL_AUTH = "hzshvazrbnyzfhdf"
EMAIL_RECEIVER = "1113496210@qq.com"

# ========== 系统参数 ==========
BINANCE_API = "https://fapi.binance.com"
TIMEFRAME_SIGNAL = "1h"
TIMEFRAME_REPORT = "5m"
SCAN_INTERVAL = 60

EXCLUDE_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT",
    "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"
}

# 核心+辅助指标严格触发
AUXILIARY_REQUIRED = 4  # 至少 N 个辅助指标满足

# 去重冷却
SIGNAL_COOLDOWN_MINUTES = 60
GLOBAL_COOLDOWN_MINUTES = 30
sent_signals = {}  # {(symbol,direction): datetime}
last_global_alert = None

# 日报记录
daily_log = []

# ========== 通知函数 ==========
def send_tg(msg: str):
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": msg}, timeout=10)
    except:
        pass

def send_email(subject: str, content: str):
    try:
        msg = MIMEText(content, "plain", "utf-8")
        msg["From"] = formataddr(("盘面监控", EMAIL_SENDER))
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = Header(subject, "utf-8")
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_SENDER, EMAIL_AUTH)
            server.sendmail(EMAIL_SENDER, [EMAIL_RECEIVER], msg.as_string())
    except:
        pass

def notify_all(msg):
    send_tg(msg)
    send_email("趋势提示", msg)

# ========== Binance 永续合约工具 ==========
def get_symbols():
    try:
        r = requests.get(f"{BINANCE_API}/fapi/v1/exchangeInfo", timeout=10).json()
        return [
            s["symbol"] for s in r["symbols"]
            if s["contractType"]=="PERPETUAL"
            and s["quoteAsset"]=="USDT"
            and s["status"]=="TRADING"
            and s["symbol"] not in EXCLUDE_SYMBOLS
        ]
    except:
        return []

def get_klines(symbol, interval, limit):
    try:
        r = requests.get(f"{BINANCE_API}/fapi/v1/klines",
                         params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        r.raise_for_status()
        df = pd.DataFrame(r.json(), columns=["ts","open","high","low","close","volume","c7","c8","c9","c10","c11","c12"])
        df = df[["ts","open","high","low","close","volume"]].astype(float)
        return df
    except:
        return pd.DataFrame()

# ========== 技术指标计算 ==========
def calc_indicators(df):
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma30"] = df["close"].rolling(30).mean()

    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    df["macd"] = ema12 - ema26
    df["macd_hist"] = df["macd"] - df["macd"].ewm(span=9).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    df["std"] = df["close"].rolling(20).std()
    df["boll_up"] = df["close"].rolling(20).mean() + 2*df["std"]
    df["boll_down"] = df["close"].rolling(20).mean() - 2*df["std"]

    df["typical"] = (df["high"] + df["low"] + df["close"])/3
    df["cci"] = (df["typical"] - df["typical"].rolling(20).mean())/(0.015*df["typical"].rolling(20).std())

    df["bias"] = (df["close"] - df["close"].rolling(6).mean())/df["close"].rolling(6).mean()*100

    df["atr"] = df["high"].rolling(14).max() - df["low"].rolling(14).min()

    df["obv"] = (df["volume"] * (df["close"].diff().fillna(0).apply(lambda x: 1 if x>0 else -1 if x<0 else 0))).cumsum()

    return df

# ========== 信号判断 ==========
def check_signal(symbol):
    df = get_klines(symbol, TIMEFRAME_SIGNAL, 120)
    if df.empty:
        return None, None, None
    df = calc_indicators(df)
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # 核心指标
    long_core = last["close"] > last["ma30"] and last["ma10"] > last["ma30"] and last["macd_hist"] > prev["macd_hist"] and 40 < last["rsi"] < 60
    short_core = last["close"] < last["ma30"] and last["ma10"] < last["ma30"] and last["macd_hist"] < prev["macd_hist"] and 40 < last["rsi"] < 60

    if not long_core and not short_core:
        return None, None, None

    direction = "LONG" if long_core else "SHORT"

    # 辅助指标计数
    aux_count = 0
    if direction=="LONG":
        if last["close"] > last["boll_up"]: aux_count +=1
        if last["rsi"]<30: aux_count +=1
        if last["macd_hist"]>prev["macd_hist"]: aux_count +=1
        if last["bias"]>20: aux_count +=1
        if last["cci"]>100: aux_count +=1
        if last["atr"]>0: aux_count +=1  # 可调阈值
        if last["obv"]>prev["obv"]: aux_count +=1
    else:
        if last["close"] < last["boll_down"]: aux_count +=1
        if last["rsi"]>70: aux_count +=1
        if last["macd_hist"]<prev["macd_hist"]: aux_count +=1
        if last["bias"]<-20: aux_count +=1
        if last["cci"]<-100: aux_count +=1
        if last["atr"]>0: aux_count +=1
        if last["obv"]<prev["obv"]: aux_count +=1

    if aux_count < AUXILIARY_REQUIRED:
        return None, None, None

    return direction, last["close"], df

# ========== 日内最大波幅 ==========
def calc_intraday_move(symbol, signal_price, direction, signal_ts):
    df = get_klines(symbol, TIMEFRAME_REPORT, 500)
    if df.empty:
        return None, None
    if direction=="LONG":
        best = df["high"].max()
        pct = (best - signal_price)/signal_price*100
    else:
        best = df["low"].min()
        pct = (signal_price - best)/signal_price*100
    return round(best,6), round(pct,2)

# ========== 提示文本 ==========
def build_alert(symbol, direction, price):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    title = "🚀 山寨合约 · 多头趋势提示" if direction=="LONG" else "🔻 山寨合约 · 空头趋势提示"
    return f"""{title}

交易对：{symbol}
方向：{direction}
信号价：{price}
时间：{now}

⚠️ 核心+辅助指标严格触发
⚠️ 仅作趋势提示，不自动下单
"""

# ========== 日报 ==========
def send_daily_report():
    if not daily_log:
        return
    today = datetime.date.today()
    lines = ["币安 · 山寨合约趋势信号日报", f"日期：{today}",""]
    lines.append("交易对 | 方向 | 信号价 | 当日最优价 | 最大有利幅度")
    lines.append("------------------------------------------------")
    for item in daily_log:
        best, pct = calc_intraday_move(item["symbol"], item["price"], item["direction"], item["ts"])
        lines.append(f"{item['symbol']} | {item['direction']} | {item['price']} | {best or '--'} | {pct or '--'}%")
    lines.append("------------------------------------------------")
    send_email(f"【山寨合约信号日报】{today}", "\n".join(lines))

# ========== 主循环 ==========
def main():
    symbols = get_symbols()
    notify_all(f"✅ 技术指标严格触发版启动，共 {len(symbols)} 个山寨永续合约")

    last_report_day = None

    while True:
        now = datetime.datetime.now()
        global last_global_alert

        for symbol in symbols:
            direction, price, df = check_signal(symbol)
            if not direction:
                continue

            key = (symbol, direction)
            last_time = sent_signals.get(key)
            if last_time and (now - last_time).total_seconds()<SIGNAL_COOLDOWN_MINUTES*60:
                continue

            if last_global_alert and (now - last_global_alert).total_seconds()<GLOBAL_COOLDOWN_MINUTES*60:
                continue

            msg = build_alert(symbol, direction, price)
            notify_all(msg)

            sent_signals[key] = now
            last_global_alert = now
            daily_log.append({"symbol": symbol,"direction": direction,"price": price,"ts": now})

        # 每天 00:05 发送日报
        if now.hour==0 and now.minute<5:
            if last_report_day!=now.date():
                send_daily_report()
                daily_log.clear()
                last_report_day = now.date()

        time.sleep(SCAN_INTERVAL)

if __name__=="__main__":
    main()

