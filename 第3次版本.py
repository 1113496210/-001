# -*- coding: utf-8 -*-
# =====================================================
# Binance USDT 永续合约 · ABC 并行量化监控（最终版）
# =====================================================

import time
import requests
import smtplib
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

# ================= 基础配置 =================
BINANCE_API = "https://fapi.binance.com"
SCAN_INTERVAL = 60  # 秒

# ================= 系统参数 =================
# 系统 C
C_LOOKBACK_MIN = 30
C_VOL_MULTIPLIER = 2.3
C_THRESHOLD = 0.5

# 系统 A1 / A2
A1_TRIGGER = 1.8
A2_TRIGGER = 3.8
VOLUME_MULTIPLIER_1 = 1.5
VOLUME_MULTIPLIER_2 = 1.2
COOLDOWN = 900  # 15 分钟失效

# 系统 B
B_HH_LOOKBACK = 3
B_DRAWDOWN_FAIL = 0.07
MAX_PUSH = 5
MAX_DAILY_ROUND = 2

# ================= 通知配置 =================
BOT_TOKEN = "8557301222:AAHj1rSQ63zJGFXVxxuTniwRP2Y1tj3QsAs"
CHAT_ID = "5408890841"

EMAIL_USER = "1113496210@qq.com"
EMAIL_PASS = "hzshvazrbnyzfhdf"
EMAIL_TO = "1113496210@qq.com"

# ================= 通知模块 =================
def send_tg(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
    except:
        pass

def send_email(subject, content):
    try:
        msg = MIMEText(content, "plain", "utf-8")
        msg["From"] = formataddr(("盘面监控", EMAIL_USER))
        msg["To"] = EMAIL_TO
        msg["Subject"] = Header(subject, "utf-8")
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, [EMAIL_TO], msg.as_string())
        server.quit()
    except:
        pass

def notify_all(title, content):
    send_tg(content)
    send_email(title, content)

# ================= Binance 工具 =================
def get_symbols():
    r = requests.get(f"{BINANCE_API}/fapi/v1/exchangeInfo", timeout=10).json()
    return [
        s["symbol"] for s in r["symbols"]
        if s["contractType"] == "PERPETUAL"
        and s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
    ]

def get_klines(symbol, interval, limit):
    r = requests.get(
        f"{BINANCE_API}/fapi/v1/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10
    )
    r.raise_for_status()
    return r.json()

def get_klines_closed(symbol, interval, limit):
    klines = get_klines(symbol, interval, limit + 1)
    return klines[:-1]

def get_24h_change(symbol):
    try:
        r = requests.get(f"{BINANCE_API}/fapi/v1/ticker/24hr", params={"symbol": symbol}, timeout=5).json()
        return float(r["priceChangePercent"])
    except:
        return 0.0

# ================= 状态缓存 =================
STATE = defaultdict(dict)

# ================= 系统逻辑 =================
def check_C(symbol):
    now_cn = datetime.now(timezone(timedelta(hours=8)))
    klines = get_klines(symbol, "1m", C_LOOKBACK_MIN)
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    max_vol = max(volumes)
    avg_vol = sum(volumes) / len(volumes)
    
    if max_vol >= avg_vol * C_VOL_MULTIPLIER and (closes[-1]-min(closes))/min(closes)*100 >= C_THRESHOLD:
        STATE[symbol]["C_time"] = now_cn
        msg = (
            f"⚠️ C 系统 · 结构异常\n\n"
            f"时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n"
            f"币种：{symbol}\n"
            f"当前价格：{closes[-1]:.6f}\n"
            f"1M 涨幅：{(closes[-1]-closes[0])/closes[0]*100:.2f}%\n\n"
            f"结构变化：突破近 {C_LOOKBACK_MIN} 分钟箱体\n"
            f"结论：早期结构异常"
        )
        notify_tg_only(msg)

def check_A1(symbol):
    now_cn = datetime.now(timezone(timedelta(hours=8)))
    k1 = get_klines(symbol, "1m", 3)
    o = float(k1[-1][1])
    c = float(k1[-1][4])
    pct = (c-o)/o*100
    vol_now = float(k1[-1][5])
    vol_avg = sum(float(x[5]) for x in k1[:-1])/2
    
    if pct >= A1_TRIGGER and vol_now >= vol_avg*VOLUME_MULTIPLIER_1:
        STATE[symbol]["A1_time"] = now_cn
        STATE[symbol]["A1_price"] = c
        msg = (
            f"🟢 A1 主力启动\n"
            f"时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n"
            f"币种：{symbol}\n"
            f"当前价格：{c:.6f}\n"
            f"涨幅：+{pct:.2f}%\n"
            f"成交量：明显放大"
        )
        notify_all("A1 主力启动", msg)

def check_A2(symbol):
    now_cn = datetime.now(timezone(timedelta(hours=8)))
    k1 = get_klines(symbol, "1m", 3)
    c = float(k1[-1][4])
    sa = STATE[symbol]
    if "A1_time" in sa and "A2_time" not in sa:
        total_pct = (c - sa["A1_price"])/sa["A1_price"]*100
        if total_pct >= A2_TRIGGER:
            STATE[symbol]["A2_time"] = now_cn
            msg = (
                f"🔥 A2 二次启动\n"
                f"时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n"
                f"币种：{symbol}\n"
                f"当前价格：{c:.6f}\n"
                f"累计涨幅：+{total_pct:.2f}%"
            )
            notify_all("A2 二次启动", msg)

def check_B(symbol):
    now_cn = datetime.now(timezone(timedelta(hours=8)))
    k3 = get_klines_closed(symbol, "3m", B_HH_LOOKBACK+1)
    highs = [float(x[2]) for x in k3]
    lows = [float(x[3]) for x in k3]
    closes = [float(x[4]) for x in k3]
    price_now = closes[-1]
    change_24h = get_24h_change(symbol)
    sb = STATE[symbol]

    if "B_active" not in sb:
        hh = highs[-3]<highs[-2]<highs[-1]
        if hh:
            sb["B_active"] = True
            sb["last_high"] = highs[-1]
            sb["base_low"] = lows[-3]
            sb["push_count"] = 1
            sb["start_pct"] = (highs[-1]-lows[-3])/lows[-3]*100
            sb["B_time"] = now_cn
            msg = (
                f"🟢 B 系统 · 3M 拉盘启动\n"
                f"时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n"
                f"币种：{symbol}\n"
                f"当前价格：{price_now:.6f}\n"
                f"24h 涨跌幅：{change_24h:+.2f}%\n"
                f"结构启动涨幅：+{sb['start_pct']:.2f}%"
            )
            notify_all("B 系统 · 3M 拉盘启动", msg)
    else:
        drawdown = (sb["last_high"]-lows[-1])/sb["last_high"]
        if drawdown >= B_DRAWDOWN_FAIL:
            sb["B_active"] = False
            return
        if highs[-1]>sb["last_high"] and sb["push_count"]<MAX_PUSH:
            sb["last_high"] = highs[-1]
            sb["push_count"] += 1
            current_pct = (sb["last_high"]-sb["base_low"])/sb["base_low"]*100
            msg = (
                f"🚀 B 系统 · 3M 拉盘推进（{sb['push_count']}）\n"
                f"时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n"
                f"币种：{symbol}\n"
                f"当前价格：{price_now:.6f}\n"
                f"24h 涨跌幅：{change_24h:+.2f}%\n"
                f"结构启动涨幅：+{sb['start_pct']:.2f}%\n"
                f"当前结构涨幅：+{current_pct:.2f}%"
            )
            notify_all("B 系统 · 3M 拉盘推进", msg)

# ================= 主程序 =================
def main():
    symbols = get_symbols()
    notify_all(
        "监控启动",
        f"✅ ABC 系统启动，共监控 {len(symbols)} 个 USDT 永续合约\n扫描间隔：{SCAN_INTERVAL} 秒"
    )
    while True:
        for symbol in symbols:
            try:
                if symbol not in STATE or "C_time" not in STATE[symbol]:
                    check_C(symbol)
                elif "A1_time" not in STATE[symbol]:
                    check_A1(symbol)
                elif "A2_time" not in STATE[symbol]:
                    check_A2(symbol)
                else:
                    check_B(symbol)
            except:
                pass
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
