# -*- coding: utf-8 -*-
# =====================================================
# Binance USDT 永续合约 · AB 并行量化监控 + 观察雷达 + 每日涨幅表
# =====================================================

import time
import requests
import smtplib
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import io
import csv

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

# ===== 新增（原脚本已有）：通知聚合 =====
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

# ================= 状态缓存 =================
state_a = defaultdict(lambda: {"last_alert": 0, "first_price": None, "second_done": False})
state_b = defaultdict(lambda: {
    "active": False, "last_high": None, "base_low": None,
    "push_count": 0, "day": None, "daily_round": 0, "start_pct": 0.0
})

# ===== 新增：观察模块状态 =====
state_watch = defaultdict(lambda: {
    "date": None,
    "alerted": False,
    "alert_time": None,
    "alert_price": None,
    "highest_price": 0.0,
    "priority": None
})

# ===== 新增：观察时间限制 =====
def in_watch_time(now_cn):
    h, m = now_cn.hour, now_cn.minute
    return not ((h == 23 and m >= 30) or (h < 7))

# ================= 启动 =================
symbols = get_symbols()
notify_all("监控启动", f"✅ AB 系统启动，共 {len(symbols)} 个 USDT 永续合约")

# ================= 主循环 =================
while True:
    try:
        now_cn = datetime.now(timezone(timedelta(hours=8)))
        today = date.today()

        for sym in symbols:
            try:
                # ================= 观察模块（提前雷达） =================
                sw = state_watch[sym]

                if sw["date"] != today:
                    sw.update({
                        "date": today,
                        "alerted": False,
                        "priority": None
                    })

                k = get_klines(sym, "1m", 10)
                opens = [float(x[1]) for x in k]
                closes = [float(x[4]) for x in k]
                lows = [float(x[3]) for x in k]
                volumes = [float(x[5]) for x in k]
                price_now = closes[-1]

                recent_low = min(lows)
                cond_a = (price_now - recent_low) / recent_low >= 0.012

                cond_b = (
                    (closes[-1] > opens[-1] and closes[-2] > opens[-2]) or
                    (closes[-1] - opens[-1]) > (closes[-2] - opens[-2]) or
                    closes[-1] > max(closes[-4:-1])
                )

                vol_avg = sum(volumes[:-1]) / (len(volumes) - 1)
                cond_c = volumes[-1] >= vol_avg * 1.1

                if not sw["alerted"] and cond_a and cond_b and cond_c:
                    score = 0
                    if (price_now - recent_low) / recent_low >= 0.02:
                        score += 1
                    if closes[-3] < closes[-2] < closes[-1]:
                        score += 1
                    if volumes[-1] >= vol_avg * 1.3:
                        score += 1

                    priority = "高" if score >= 2 else "中" if score == 1 else "低"

                    sw.update({
                        "alerted": True,
                        "priority": priority,
                        "alert_time": now_cn.strftime("%Y-%m-%d %H:%M"),
                        "alert_price": price_now,
                        "highest_price": price_now
                    })

                    if in_watch_time(now_cn):
                        msg = (
                            f"👀 观察信号（{priority}优先级）\n\n"
                            f"时间：{sw['alert_time']}\n"
                            f"币种：{sym}\n"
                            f"观察价：{price_now:.6f}"
                        )
                        send_tg(msg)
                        if priority == "高":
                            send_email("【高优先级观察信号】", msg)

                if sw["alerted"]:
                    sw["highest_price"] = max(sw["highest_price"], price_now)

            except:
                pass

        time.sleep(SCAN_INTERVAL)

    except:
        time.sleep(5)
