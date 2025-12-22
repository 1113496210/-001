# -*- coding: utf-8 -*-
# =====================================================
# Binance USDT 永续合约 · AB 并行量化监控（Python 3.6 可用版）
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
SCAN_INTERVAL = 60

# ================= 系统 A 参数 =================
FIRST_TRIGGER = 1.8
SECOND_TRIGGER = 3.8
VOLUME_MULTIPLIER_1 = 1.5
VOLUME_MULTIPLIER_2 = 1.2
COOLDOWN = 180

# ================= 系统 B 参数 =================
HH_INIT_BARS = 3
HH_MIN_TOTAL_PCT = 3.0
DRAWDOWN_FAIL = 0.07
MAX_PUSH = 3
MAX_DAILY_ROUND = 2

# ================= 全市场同涨噪音 =================
MARKET_NOISE_PCT = 1.2
MARKET_NOISE_RATIO = 0.6

# ================= 通知配置 =================
BOT_TOKEN = "8557301222:AAHj1rSQ63zJGFXVxxuTniwRP2Y1tj3QsAs"
CHAT_ID = "5408890841"

EMAIL_USER = "1113496210@qq.com"
EMAIL_PASS = "hzshvazrbnyzfhdf"
EMAIL_TO = "1113496210@qq.com"

# ================= 通知模块 =================
def send_tg(text):
    try:
        url = "https://api.telegram.org/bot{}/sendMessage".format(BOT_TOKEN)
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

def notify_tg_only(content):
    send_tg(content)

# ================= Binance 工具 =================
def get_symbols():
    r = requests.get("{}/fapi/v1/exchangeInfo".format(BINANCE_API), timeout=10).json()
    return [
        s["symbol"] for s in r["symbols"]
        if s["contractType"] == "PERPETUAL"
        and s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
    ]

def get_klines(symbol, interval, limit):
    r = requests.get(
        "{}/fapi/v1/klines".format(BINANCE_API),
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10
    )
    r.raise_for_status()
    return r.json()

def get_24h_change(symbol):
    try:
        r = requests.get(
            "{}/fapi/v1/ticker/24hr".format(BINANCE_API),
            params={"symbol": symbol},
            timeout=5
        ).json()
        return float(r["priceChangePercent"])
    except:
        return 0.0

# ================= 状态缓存 =================
state_a = defaultdict(lambda: {
    "last_alert": 0,
    "first_price": None,
    "second_done": False
})

state_b = defaultdict(lambda: {
    "active": False,
    "last_high": None,
    "base_low": None,
    "push_count": 0,
    "day": None,
    "daily_round": 0,
    "start_pct": 0.0
})

# ================= 启动 =================
symbols = get_symbols()
notify_all("监控启动", "✅ AB 系统启动，共 {} 个 USDT 永续合约".format(len(symbols)))

# ================= 主循环 =================
while True:
    try:
        now_cn = datetime.now(timezone(timedelta(hours=8)))
        today = date.today()

        # ===== 全市场噪音判断 =====
        up_count = 0
        for sym in symbols[:50]:
            try:
                k = get_klines(sym, "1m", 2)
                o = float(k[-1][1])
                c = float(k[-1][4])
                if (c - o) / o * 100 >= MARKET_NOISE_PCT:
                    up_count += 1
            except:
                pass

        if up_count / 50 >= MARKET_NOISE_RATIO:
            time.sleep(SCAN_INTERVAL)
            continue

        for sym in symbols:
            # ================= 系统 A =================
            try:
                k1 = get_klines(sym, "1m", 3)
                o = float(k1[-1][1])
                c = float(k1[-1][4])
                pct = (c - o) / o * 100

                vol_now = float(k1[-1][5])
                vol_avg = sum(float(x[5]) for x in k1[:-1]) / 2

                sa = state_a[sym]
                now_ts = time.time()

                if pct >= FIRST_TRIGGER and vol_now >= vol_avg * VOLUME_MULTIPLIER_1:
                    if now_ts - sa["last_alert"] > COOLDOWN and not sa["first_price"]:
                        sa["first_price"] = c
                        sa["last_alert"] = now_ts
                        msg = (
                            "🟢 主力启动\n"
                            "时间：{}\n"
                            "币种：{}\n"
                            "当前价格：{:.6f}\n"
                            "1M 涨幅：+{:.2f}%\n"
                            "成交量：明显放大\n"
                            "判定：主力介入 / 吸筹"
                        ).format(now_cn.strftime("%Y-%m-%d %H:%M"), sym, c, pct)
                        notify_all("主力启动", msg)

                if sa["first_price"] and not sa["second_done"]:
                    total_pct = (c - sa["first_price"]) / sa["first_price"] * 100
                    if total_pct >= SECOND_TRIGGER and vol_now >= vol_avg * VOLUME_MULTIPLIER_2:
                        sa["second_done"] = True
                        msg = (
                            "🔥 二次启动\n"
                            "时间：{}\n"
                            "币种：{}\n"
                            "当前价格：{:.6f}\n"
                            "累计涨幅：+{:.2f}%"
                        ).format(now_cn.strftime("%Y-%m-%d %H:%M"), sym, c, total_pct)
                        notify_all("二次启动", msg)
            except:
                pass

            # ================= 系统 B =================
            try:
                sb = state_b[sym]

                if sb["day"] != today:
                    sb["day"] = today
                    sb["daily_round"] = 0
                    sb["active"] = False
                    sb["push_count"] = 0

                if sb["daily_round"] >= MAX_DAILY_ROUND:
                    continue

                k3 = get_klines(sym, "3m", 6)
                highs = [float(x[2]) for x in k3]
                lows = [float(x[3]) for x in k3]
                price_now = float(k3[-1][4])
                change_24h = get_24h_change(sym)

                if not sb["active"]:
                    hh = highs[-3] < highs[-2] < highs[-1]
                    start_pct = (highs[-1] - lows[-3]) / lows[-3] * 100

                    if hh and start_pct >= HH_MIN_TOTAL_PCT:
                        sb["active"] = True
                        sb["last_high"] = highs[-1]
                        sb["base_low"] = lows[-3]
                        sb["push_count"] = 1
                        sb["daily_round"] += 1
                        sb["start_pct"] = start_pct

                        msg = (
                            "🟢 3M 拉盘启动（1）\n"
                            "时间：{}\n"
                            "币种：{}\n"
                            "当前价格：{:.6f}\n\n"
                            "交易所 24h 涨跌幅：{:+.2f}%\n"
                            "结构启动涨幅：+{:.2f}%\n"
                            "当前结构涨幅：+{:.2f}%\n\n"
                            "结构：3M HH 连续新高"
                        ).format(now_cn.strftime("%Y-%m-%d %H:%M"), sym, price_now, change_24h, start_pct, start_pct)
                        notify_all("3M 拉盘启动", msg)

                else:
                    drawdown = (sb["last_high"] - lows[-1]) / sb["last_high"]
                    if drawdown >= DRAWDOWN_FAIL:
                        sb["active"] = False
                        continue

                    if highs[-1] > sb["last_high"] and sb["push_count"] < MAX_PUSH:
                        sb["last_high"] = highs[-1]
                        sb["push_count"] += 1
                        current_pct = (sb["last_high"] - sb["base_low"]) / sb["base_low"] * 100

                        msg = (
                            "🚀 3M 拉盘推进（{}）\n"
                            "时间：{}\n"
                            "币种：{}\n"
                            "当前价格：{:.6f}\n\n"
                            "交易所 24h 涨跌幅：{:+.2f}%\n"
                            "结构启动涨幅：+{:.2f}%\n"
                            "当前结构涨幅：+{:.2f}%\n\n"
                            "结构：3M HH 持续突破\n"
                            "状态：第 {} 次推进"
                        ).format(sb["push_count"], now_cn.strftime("%Y-%m-%d %H:%M"), sym, price_now, change_24h, sb["start_pct"], current_pct, sb["push_count"])
                        notify_tg_only(msg)
            except:
                pass

        time.sleep(SCAN_INTERVAL)

    except Exception as e:
        time.sleep(5)

