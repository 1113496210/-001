# -*- coding: utf-8 -*-
# =====================================================
# Binance USDT 永续合约 · AB 并行量化监控（优化日报 + 邮件发送）
# =====================================================

import time
import requests
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
from openpyxl import Workbook
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
from email.utils import formataddr
import os

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

# ================= 状态缓存 =================
state_a = defaultdict(lambda: {"last_alert": 0, "first_price": None, "second_done": False})
state_b = defaultdict(lambda: {"active": False, "last_high": None, "base_low": None,
                               "push_count": 0, "day": None, "daily_round": 0, "start_pct": 0.0})

# ================= 日报缓存 =================
daily_report = defaultdict(list)

# ================= Binance 工具 =================
def get_symbols():
    r = requests.get(f"{BINANCE_API}/fapi/v1/exchangeInfo", timeout=10).json()
    return [s["symbol"] for s in r["symbols"] if s["contractType"]=="PERPETUAL" and s["quoteAsset"]=="USDT" and s["status"]=="TRADING"]

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

# ================= 日报生成 & 邮件发送 =================
def generate_and_send_daily_report(report, report_date):
    wb = Workbook()
    # Sheet1: 信号明细
    ws1 = wb.active
    ws1.title = "信号明细"
    ws1.append(["日期","币种","提示时间","提示价格","最高价格","最大涨幅(%)","推送次数"])
    for sym, items in report.items():
        for item in items:
            max_pct = max((i["highest_price"]-i["trigger_price"])/i["trigger_price"]*100 for i in items)
            total_push = sum(i["push_count"] for i in items)
            ws1.append([report_date, sym, item["trigger_time"], item["trigger_price"],
                       item["highest_price"], round(max_pct,2), total_push])
    # Sheet2: 日报分析
    ws2 = wb.create_sheet(title="日报分析")
    ws2.append(["日期","总信号数","平均涨幅(%)","最大涨幅币种","最大涨幅(%)","总推送次数"])
    total_signals = 0
    total_pushes = 0
    total_pct_sum = 0
    max_pct_overall = 0
    max_pct_coin = ""
    for sym, items in report.items():
        for item in items:
            pct = (item["highest_price"]-item["trigger_price"])/item["trigger_price"]*100
            total_signals += 1
            total_pct_sum += pct
            total_pushes += item["push_count"]
            if pct > max_pct_overall:
                max_pct_overall = pct
                max_pct_coin = sym
    avg_pct = round(total_pct_sum/total_signals,2) if total_signals>0 else 0
    ws2.append([report_date, total_signals, avg_pct, max_pct_coin, round(max_pct_overall,2), total_pushes])
    # 保存到临时文件
    tmp_file = f"daily_report_{report_date}.xlsx"
    wb.save(tmp_file)
    # 发送到邮箱
    try:
        msg = MIMEMultipart()
        msg["From"] = formataddr(("盘面监控", EMAIL_USER))
        msg["To"] = EMAIL_TO
        msg["Subject"] = Header(f"{report_date} 日报", "utf-8")
        with open(tmp_file, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{tmp_file}"')
            msg.attach(part)
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, [EMAIL_TO], msg.as_string())
        server.quit()
    except Exception as e:
        print("发送日报失败:", e)
    # 删除临时文件，不在服务器留档
    if os.path.exists(tmp_file):
        os.remove(tmp_file)

# ================= 启动 =================
symbols = get_symbols()
notify_all("监控启动", f"✅ AB 系统启动，共 {len(symbols)} 个 USDT 永续合约")

# ================= 主循环 =================
while True:
    try:
        now_cn = datetime.now(timezone(timedelta(hours=8)))
        today = date.today()

        # === 全市场噪音判断（保持原逻辑） ===
        up_count = 0
        for sym in symbols[:50]:
            try:
                k = get_klines(sym, "1m", 2)
                o = float(k[-1][1])
                c = float(k[-1][4])
                if (c-o)/o*100 >= MARKET_NOISE_PCT:
                    up_count +=1
            except:
                pass
        if up_count/50 >= MARKET_NOISE_RATIO:
            time.sleep(SCAN_INTERVAL)
            continue

        # === 系统 A/B 原有逻辑 ===
        for sym in symbols:
            # 系统 A
            try:
                k1 = get_klines(sym, "1m", 3)
                o = float(k1[-1][1])
                c = float(k1[-1][4])
                pct = (c-o)/o*100
                vol_now = float(k1[-1][5])
                vol_avg = sum(float(x[5]) for x in k1[:-1])/2
                sa = state_a[sym]
                now_ts = time.time()
                if pct >= FIRST_TRIGGER and vol_now >= vol_avg*VOLUME_MULTIPLIER_1:
                    if now_ts - sa["last_alert"]>COOLDOWN and not sa["first_price"]:
                        sa["first_price"]=c
                        sa["last_alert"]=now_ts
                        msg=f"🟢 主力启动\n时间:{now_cn}\n币种:{sym}\n当前价格:{c:.6f}\n涨幅:+{pct:.2f}%"
                        notify_all("主力启动", msg)
                        daily_report[sym].append({"trigger_time": now_cn.strftime("%Y-%m-%d %H:%M"),
                                                  "trigger_price": c,
                                                  "highest_price": c,
                                                  "push_count":1})
                if sa["first_price"] and not sa["second_done"]:
                    total_pct = (c - sa["first_price"])/sa["first_price"]*100
                    if total_pct >= SECOND_TRIGGER and vol_now >= vol_avg*VOLUME_MULTIPLIER_2:
                        sa["second_done"]=True
                        msg=f"🔥 二次启动\n时间:{now_cn}\n币种:{sym}\n当前价格:{c:.6f}\n累计涨幅:+{total_pct:.2f}%"
                        notify_all("二次启动", msg)
                        daily_report[sym][-1]["highest_price"]=max(daily_report[sym][-1]["highest_price"], c)
                        daily_report[sym][-1]["push_count"]+=1
            except:
                pass

            # 系统 B
            try:
                sb = state_b[sym]
                if sb["day"] != today:
                    sb["day"]=today
                    sb["daily_round"]=0
                    sb["active"]=False
                    sb["push_count"]=0
                if sb["daily_round"] >= MAX_DAILY_ROUND:
                    continue
                k3 = get_klines(sym, "3m", 6)
                highs = [float(x[2]) for x in k3]
                lows = [float(x[3]) for x in k3]
                price_now = float(k3[-1][4])
                change_24h = get_24h_change(sym)
                if not sb["active"]:
                    hh = highs[-3]<highs[-2]<highs[-1]
                    start_pct = (highs[-1]-lows[-3])/lows[-3]*100
                    if hh and start_pct>=HH_MIN_TOTAL_PCT:
                        sb["active"]=True
                        sb["last_high"]=highs[-1]
                        sb["base_low"]=lows[-3]
                        sb["push_count"]=1
                        sb["daily_round"]+=1
                        sb["start_pct"]=start_pct
                        msg=f"🟢 3M 拉盘启动\n时间:{now_cn}\n币种:{sym}\n当前价格:{price_now:.6f}\n24h涨幅:{change_24h:+.2f}%"
                        notify_all("3M 拉盘启动", msg)
                        daily_report[sym].append({"trigger_time": now_cn.strftime("%Y-%m-%d %H:%M"),
                                                  "trigger_price": price_now,
                                                  "highest_price": price_now,
                                                  "push_count":1})
                else:
                    drawdown = (sb["last_high"]-lows[-1])/sb["last_high"]
                    if drawdown>=DRAWDOWN_FAIL:
                        sb["active"]=False
                        continue
                    if highs[-1]>sb["last_high"] and sb["push_count"]<MAX_PUSH:
                        sb["last_high"]=highs[-1]
                        sb["push_count"]+=1
                        msg=f"🚀 3M 拉盘推进({sb['push_count']})\n时间:{now_cn}\n币种:{sym}\n当前价格:{price_now:.6f}\n24h涨幅:{change_24h:+.2f}%"
                        notify_tg_only(msg)
                        daily_report[sym][-1]["highest_price"]=max(daily_report[sym][-1]["highest_price"], highs[-1])
                        daily_report[sym][-1]["push_count"]+=1
            except:
                pass

        # === 每天凌晨生成 & 邮件发送报表 ===
        if now_cn.hour==0 and now_cn.minute<SCAN_INTERVAL:
            report_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
            generate_and_send_daily_report(daily_report, report_date)
            daily_report.clear()

        time.sleep(SCAN_INTERVAL)
    except Exception as e:
        time.sleep(5)
