# -*- coding: utf-8 -*-
# =====================================================
# Binance USDT 永续合约 · AB 并行量化监控 + 观察C结合 + 每日涨幅表格
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
import math

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
    r = requests.get(f"{BINANCE_API}/fapi/v1/klines", params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
    r.raise_for_status()
    return r.json()

def get_24h_change(symbol):
    try:
        r = requests.get(f"{BINANCE_API}/fapi/v1/ticker/24hr", params={"symbol": symbol}, timeout=5).json()
        return float(r["priceChangePercent"])
    except:
        return 0.0

# ================= 状态缓存 =================
state_a = defaultdict(lambda: {"last_alert": 0, "first_price": None, "second_done": False})
state_b = defaultdict(lambda: {"active": False, "last_high": None, "base_low": None, "push_count": 0, "day": None, "daily_round": 0, "start_pct": 0.0})

# ================= 每日推送涨幅表格缓存 =================
push_day = None
push_table = []

def record_push(sym, price, now_cn):
    push_table.append({"symbol": sym, "time": now_cn.strftime("%Y-%m-%d %H:%M:%S"), "start_price": price, "high_price": price, "push_count": 1})

def update_high_price(sym, price):
    for r in push_table:
        if r["symbol"] == sym and price > r["high_price"]:
            r["high_price"] = price

def build_push_rank():
    rows = []
    for r in push_table:
        pct = (r["high_price"] - r["start_price"]) / r["start_price"] * 100
        rows.append({"symbol": r["symbol"], "time": r["time"], "start": r["start_price"], "high": r["high_price"], "pct": pct, "count": r["push_count"]})
    rows.sort(key=lambda x: x["pct"], reverse=True)
    return rows

def build_csv_text():
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t")
    writer.writerow(["排名", "代币", "提示时间", "提示价格", "最高价格", "最大涨幅百分比", "推送次数"])
    data = build_push_rank()
    for i, r in enumerate(data, 1):
        writer.writerow([i, r["symbol"], "'" + r["time"], round(r["start"], 6), round(r["high"], 6), round(r["pct"], 2), r["count"]])
    return output.getvalue()

def send_daily_report(subject, csv_content, report_day):
    msg = MIMEMultipart()
    msg["From"] = formataddr(("24H 行情日报", EMAIL_USER))
    msg["To"] = EMAIL_TO
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(f"附件为 {report_day.strftime('%Y-%m-%d')} 推送涨幅排行榜", "plain", "utf-8"))
    attachment = MIMEApplication(csv_content.encode("utf-8"))
    attachment.add_header("Content-Disposition", "attachment", filename=f"24H_涨幅排名_{report_day.strftime('%Y%m%d')}.csv")
    msg.attach(attachment)
    server = smtplib.SMTP_SSL("smtp.qq.com", 465)
    server.login(EMAIL_USER, EMAIL_PASS)
    server.sendmail(EMAIL_USER, [EMAIL_TO], msg.as_string())
    server.quit()

# ===================== 观察C模块 - 资金面API =====================
def get_real_fund_flow(symbol):
    try:
        r = requests.get(f"{BINANCE_API}/fapi/v1/ticker/24hr", params={"symbol": symbol}, timeout=5).json()
        quote_volume = float(r.get("quoteVolume", 0))
        price_change = float(r.get("priceChangePercent", 0))
        fund_flow = quote_volume * price_change / 100
        return round(fund_flow, 0)
    except:
        return 0

def get_long_ratio(symbol):
    try:
        r = requests.get(f"{BINANCE_API}/futures/data/openInterestHist", params={"symbol": symbol, "period": "5m", "limit": 1}, timeout=5).json()
        if r:
            oi = float(r[0].get("sumOpenInterest", 0))
            long_ratio = float(r[0].get("longAccount", 0)) / oi * 100 if oi > 0 else 50
            return round(long_ratio, 2)
        return 50
    except:
        return 50

def get_big_orders(symbol, threshold_ratio=0.01):
    try:
        trades = requests.get(f"{BINANCE_API}/fapi/v1/trades", params={"symbol": symbol, "limit": 100}, timeout=5).json()
        big_count = 0
        if trades:
            qtys = [float(t["qty"]) for t in trades]
            avg_qty = sum(qtys) / len(qtys) if qtys else 0
            threshold = avg_qty * (1 + threshold_ratio)
            big_count = sum(1 for q in qtys if q >= threshold)
        return big_count
    except:
        return 0

# ===================== 启动 =====================
symbols = get_symbols()
notify_all("监控启动", f"✅ AB 系统 + 观察C 启动，共 {len(symbols)} 个 USDT 永续合约")

# ===================== 主循环 =====================
while True:
    try:
        now_cn = datetime.now(timezone(timedelta(hours=8)))
        today = date.today()
        # 每日跨天发送报表
        if push_day is None:
            push_day = today
        elif today != push_day:
            csv_text = build_csv_text()
            send_daily_report("📊 当日推送涨幅排行榜", csv_text, push_day)
            push_table.clear()
            push_day = today

        # 全市场噪音判断
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

        top_scores = []

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
                        msg = f"🟢 主力启动\n时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n币种：{sym}\n当前价格：{c:.6f}\n1M 涨幅：+{pct:.2f}%\n成交量：明显放大\n判定：主力介入 / 吸筹"
                        notify_all("主力启动", msg)
                        record_push(sym, c, now_cn)
                if sa["first_price"] and not sa["second_done"]:
                    total_pct = (c - sa["first_price"]) / sa["first_price"] * 100
                    if total_pct >= SECOND_TRIGGER and vol_now >= vol_avg * VOLUME_MULTIPLIER_2:
                        sa["second_done"] = True
                        msg = f"🔥 二次启动\n时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n币种：{sym}\n当前价格：{c:.6f}\n累计涨幅：+{total_pct:.2f}%"
                        notify_all("二次启动", msg)
                        for r in reversed(push_table):
                            if r["symbol"] == sym:
                                r["push_count"] += 1
                                break
                update_high_price(sym, c)
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
                        msg = f"🟢 3M 拉盘启动（1）\n时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n币种：{sym}\n当前价格：{price_now:.6f}\n\n交易所 24h 涨跌幅：{change_24h:+.2f}%\n结构启动涨幅：+{start_pct:.2f}%\n当前结构涨幅：+{start_pct:.2f}%\n\n结构：3M HH 连续新高"
                        notify_all("3M 拉盘启动", msg)
                        record_push(sym, price_now, now_cn)
                else:
                    drawdown = (sb["last_high"] - lows[-1]) / sb["last_high"]
                    if drawdown >= DRAWDOWN_FAIL:
                        sb["active"] = False
                        continue
                    if highs[-1] > sb["last_high"] and sb["push_count"] < MAX_PUSH:
                        sb["last_high"] = highs[-1]
                        sb["push_count"] += 1
                        current_pct = (sb["last_high"] - sb["base_low"]) / sb["base_low"] * 100
                        msg = f"🚀 3M 拉盘推进（{sb['push_count']}）\n时间：{now_cn.strftime('%Y-%m-%d %H:%M')}\n币种：{sym}\n当前价格：{price_now:.6f}\n\n交易所 24h 涨跌幅：{change_24h:+.2f}%\n结构启动涨幅：+{sb['start_pct']:.2f}%\n当前结构涨幅：+{current_pct:.2f}%\n结构：3M HH 持续突破\n状态：第 {sb['push_count']} 次推进"
                        notify_all("3M 拉盘推进（{}）".format(sb["push_count"]), msg)
                        for r in reversed(push_table):
                            if r["symbol"] == sym:
                                r["push_count"] += 1
                                break
                update_high_price(sym, price_now)
            except:
                pass

            # ================= 观察C模块 =================
            try:
                k15 = get_klines(sym, "15m", 6)
                indicators_3m, indicators_15m = calc_indicators(k3, k15)  # 你已有函数
                fund_flow = get_real_fund_flow(sym)
                long_ratio = get_long_ratio(sym)
                big_orders = get_big_orders(sym)
                score = (fund_flow/1e6*0.3 + long_ratio*0.3 + big_orders*0.2 + indicators_3m["score"]*0.2)
                top_scores.append({
                    "symbol": sym, "score": score, "price": price_now,
                    "fund_flow": fund_flow, "long_ratio": long_ratio, "big_orders": big_orders,
                    "indicators_3m": indicators_3m, "indicators_15m": indicators_15m
                })
            except:
                pass

        # 推送前3高分币
        top_scores.sort(key=lambda x: x["score"], reverse=True)
        for i, r in enumerate(top_scores[:3], 1):
            msg = (
                "🟢 早期观察（{}）\n时间：{}\n币种：{}\n当前价格：{:.6f}\n\n交易所 24h 涨跌幅：{:+.2f}%\n\n"
                "3分周期指标：\nADX：{}   RSI：{}   MACD：{}\n波动性突破：{}   成交量确认：{}\n\n"
                "15分周期指标：\nADX：{}   RSI：{}   MACD：{}\n波动性突破：{}   成交量确认：{}\n\n"
                "资金流 / 大单 / 持仓：\n净流入资金：{}\n合约多头占比：{}%\n大单数量：{}\n\n综合评分：{:.2f}\n重点关注：是"
            ).format(
                i, now_cn.strftime("%Y-%m-%d %H:%M"), r["symbol"], r["price"],
                get_24h_change(r["symbol"]),
                r["indicators_3m"]["adx"], r["indicators_3m"]["rsi"], r["indicators_3m"]["macd"],
                r["indicators_3m"]["vol_break"], r["indicators_3m"]["vol_confirm"],
                r["indicators_15m"]["adx"], r["indicators_15m"]["rsi"], r["indicators_15m"]["macd"],
                r["indicators_15m"]["vol_break"], r["indicators_15m"]["vol_confirm"],
                r["fund_flow"], r["long_ratio"], r["big_orders"], r["score"]
            )
            notify_all("早期观察", msg)

        time.sleep(SCAN_INTERVAL)
    except Exception as e:
        time.sleep(5)

