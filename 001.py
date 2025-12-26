# -*- coding: utf-8 -*-
# =====================================================
# Binance USDT 永续合约 · AB + C 早期观察（最终整合版）
# =====================================================

import time
import requests
import smtplib
from collections import defaultdict, deque
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

# ================= 系统 C 参数（高胜率观察） =================
C_COOLDOWN = 1800        # 单币 30 分钟冷却
C_MAX_NOTIFY = 5        # 前 5
C_MIN_EXPAND = 1.2      # 推进有效性 %
C_MAX_MINUTES = 25      # 启动最大时间
C_MIN_TOTAL_PCT = 2.5   # 启动后最小涨幅

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

def notify_all(title, content):
    send_tg(content)
    send_email(title, content)

def notify_tg_only(content):
    send_tg(content)

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

def get_24h_change(symbol):
    try:
        r = requests.get(
            f"{BINANCE_API}/fapi/v1/ticker/24hr",
            params={"symbol": symbol},
            timeout=5
        ).json()
        return float(r["priceChangePercent"])
    except:
        return 0.0

# ================= 状态缓存 =================
state_a = defaultdict(lambda: {"last_alert": 0, "first_price": None, "second_done": False})
state_b = defaultdict(lambda: {"active": False, "last_high": None, "base_low": None,
                               "push_count": 0, "day": None, "daily_round": 0, "start_pct": 0.0})
state_c = defaultdict(lambda: {
    "start_time": None,
    "base_price": None,
    "last_high": None,
    "last_notify": 0,
    "scores": deque(maxlen=5)
})

# ================= 启动 =================
symbols = get_symbols()
notify_all("监控启动", f"✅ AB + C 系统启动，共 {len(symbols)} 个 USDT 永续合约")

# ================= 主循环 =================
while True:
    try:
        now_cn = datetime.now(timezone(timedelta(hours=8)))
        today = date.today()

        # ===== 市场噪音过滤 =====
        up = 0
        for s in symbols[:50]:
            k = get_klines(s, "1m", 2)
            o = float(k[-1][1])
            c = float(k[-1][4])
            if (c - o) / o * 100 >= MARKET_NOISE_PCT:
                up += 1
        if up / 50 >= MARKET_NOISE_RATIO:
            time.sleep(SCAN_INTERVAL)
            continue

        # ================= 系统 A + B（原样保留） =================
        for sym in symbols:
            try:
                # -------- 系统 A --------
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
                        notify_all("主力启动",
                                   f"🟢 主力启动\n时间：{now_cn:%Y-%m-%d %H:%M}\n币种：{sym}\n价格：{c:.6f}")

                if sa["first_price"] and not sa["second_done"]:
                    total = (c - sa["first_price"]) / sa["first_price"] * 100
                    if total >= SECOND_TRIGGER and vol_now >= vol_avg * VOLUME_MULTIPLIER_2:
                        sa["second_done"] = True
                        notify_all("二次启动",
                                   f"🔥 二次启动\n时间：{now_cn:%Y-%m-%d %H:%M}\n币种：{sym}\n涨幅：+{total:.2f}%")

                # -------- 系统 B --------
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
                    if highs[-3] < highs[-2] < highs[-1]:
                        start_pct = (highs[-1] - lows[-3]) / lows[-3] * 100
                        if start_pct >= HH_MIN_TOTAL_PCT:
                            sb["active"] = True
                            sb["last_high"] = highs[-1]
                            sb["base_low"] = lows[-3]
                            sb["push_count"] = 1
                            sb["daily_round"] += 1
                            sb["start_pct"] = start_pct
                            notify_all("3M 拉盘启动",
                                       f"🟢 3M 拉盘启动\n币种：{sym}\n涨幅：+{start_pct:.2f}%")
                else:
                    drawdown = (sb["last_high"] - lows[-1]) / sb["last_high"]
                    if drawdown >= DRAWDOWN_FAIL:
                        sb["active"] = False
                        continue
                    if highs[-1] > sb["last_high"] and sb["push_count"] < MAX_PUSH:
                        sb["last_high"] = highs[-1]
                        sb["push_count"] += 1
                        notify_all("3M 拉盘推进",
                                   f"🚀 3M 拉盘推进（{sb['push_count']}）\n币种：{sym}")

            except:
                pass

        # ================= 系统 C（高胜率观察） =================
        candidates = []
        for sym in symbols:
            try:
                k3 = get_klines(sym, "3m", 6)
                highs = [float(x[2]) for x in k3]
                lows = [float(x[3]) for x in k3]
                price = float(k3[-1][4])
                sc = state_c[sym]

                if sc["start_time"] is None:
                    if highs[-3] < highs[-2] < highs[-1]:
                        sc["start_time"] = now_cn
                        sc["base_price"] = lows[-3]
                        sc["last_high"] = highs[-1]
                    else:
                        continue

                minutes = (now_cn - sc["start_time"]).seconds / 60
                total_pct = (price - sc["base_price"]) / sc["base_price"] * 100
                if minutes > C_MAX_MINUTES or total_pct < C_MIN_TOTAL_PCT:
                    continue

                expand = (highs[-1] - sc["last_high"]) / sc["last_high"] * 100
                if expand < C_MIN_EXPAND:
                    continue
                sc["last_high"] = highs[-1]

                score = round(min(total_pct / 5, 1), 2)
                if score >= 0.85:
                    candidates.append((sym, score, price, total_pct))

            except:
                pass

        candidates.sort(key=lambda x: x[1], reverse=True)
        notify = []
        for c in candidates:
            if time.time() - state_c[c[0]]["last_notify"] > C_COOLDOWN:
                notify.append(c)
                state_c[c[0]]["last_notify"] = time.time()
            if len(notify) >= C_MAX_NOTIFY:
                break

        if notify:
            lines = ["📈 早期观察 C（高胜率）"]
            for i, (s, sc, p, pct) in enumerate(notify, 1):
                lines.append(f"\n{i}. {s}\n评分：{sc}\n价格：{p:.6f}\n涨幅：+{pct:.2f}%")
            notify_all("📈 早期观察 C", "\n".join(lines))

        time.sleep(SCAN_INTERVAL)

    except:
        time.sleep(5)
