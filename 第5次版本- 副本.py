# -*- coding: utf-8 -*-
# =====================================================
# Binance USDT 永续合约 · ABC 并行量化监控（C系统优化版）
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

# ================= 系统 C 参数（冷启动雷达优化版） =================
C_INTERVAL = "5m"           # K线周期调整为5分钟
C_LOOKBACK_MINUTES = 60
C_VOLUME_MULTIPLIER = 3.0   # 放量倍数
C_MIN_MOVE_PCT = 1.5        # 最小涨幅门槛
C_COOLDOWN = 180            # 冷却时间（秒）

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
state_b = defaultdict(lambda: {"active": False, "last_high": None, "base_low": None, "push_count": 0, "day": None, "daily_round": 0, "start_pct": 0.0})
state_c = defaultdict(lambda: {"last_alert": 0})

# ================= 启动 =================
symbols = get_symbols()
notify_all("监控启动", f"✅ ABC 系统启动，共 {len(symbols)} 个 USDT 永续合约")

# ================= 主循环 =================
while True:
    try:
        now_cn = datetime.now(timezone(timedelta(hours=8)))
        today = date.today()

        for sym in symbols:
            # ========= 系统 A =========
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
                            f"🟢 A1 主力启动\n时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n币种：{sym}\n当前价格：{c:.6f}\n"
                            f"1M 涨幅：+{pct:.2f}%\n成交量：明显放大\n24H 涨幅：{get_24h_change(sym):+.2f}%"
                        )
                        notify_all("A1 主力启动", msg)

                if sa["first_price"] and not sa["second_done"]:
                    total_pct = (c - sa["first_price"]) / sa["first_price"] * 100
                    if total_pct >= SECOND_TRIGGER and vol_now >= vol_avg * VOLUME_MULTIPLIER_2:
                        sa["second_done"] = True
                        msg = (
                            f"🔥 A2 二次启动\n时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n币种：{sym}\n"
                            f"当前价格：{c:.6f}\n累计涨幅：+{total_pct:.2f}%\n24H 涨幅：{get_24h_change(sym):+.2f}%"
                        )
                        notify_all("A2 二次启动", msg)
            except:
                pass

            # ========= 系统 B =========
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
                            f"🟢 B 系统 3M 拉盘启动\n时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n币种：{sym}\n"
                            f"当前价格：{price_now:.6f}\n24H 涨幅：{change_24h:+.2f}%\n结构启动涨幅：+{start_pct:.2f}%"
                        )
                        notify_all("B 系统启动", msg)
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
                            f"🚀 B 系统 3M 拉盘推进（{sb['push_count']}）\n时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n币种：{sym}\n"
                            f"当前价格：{price_now:.6f}\n24H 涨幅：{change_24h:+.2f}%\n"
                            f"结构启动涨幅：+{sb['start_pct']:.2f}%\n当前结构涨幅：+{current_pct:.2f}%"
                        )
                        notify_tg_only(msg)
            except:
                pass

            # ========= 系统 C（冷启动雷达优化版） =========
            try:
                sc = state_c[sym]
                k_c = get_klines(sym, C_INTERVAL, C_LOOKBACK_MINUTES)
                opens = [float(x[1]) for x in k_c]
                closes = [float(x[4]) for x in k_c]
                volumes = [float(x[5]) for x in k_c]
                price_now = closes[-1]
                change_24h = get_24h_change(sym)

                # 背景振幅和平均量
                max_move = max(closes) - min(opens)
                avg_vol = sum(volumes) / len(volumes)
                recent_vol = volumes[-1]

                # 判断冷启动异常
                if max_move / min(opens) * 100 >= C_MIN_MOVE_PCT and recent_vol >= avg_vol * C_VOLUME_MULTIPLIER:
                    if time.time() - sc["last_alert"] > C_COOLDOWN:
                        sc["last_alert"] = time.time()
                        msg = (
                            f"⚠️ C 系统 · 冷启动异常预警\n"
                            f"时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n币种：{sym}\n"
                            f"当前价格：{price_now:.6f}\n24H 涨幅：{change_24h:+.2f}%\n"
                            f"过去 {C_LOOKBACK_MINUTES} 分钟最大振幅：{max_move:.4f}\n"
                            f"平均成交量：{avg_vol:.4f}，近期成交量：{recent_vol:.4f}\n"
                            f"结论：⚠️ 仅第一次异常触发，进入观察池"
                        )
                        notify_all("C 系统冷启动异常预警", msg)  # <-- 改这里，TG + 邮箱
            except:
                pass

        time.sleep(SCAN_INTERVAL)
    except Exception as e:
        time.sleep(5)

