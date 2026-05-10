"""
Smart Money Tracker Bot 🤖 — النسخة الاحترافية
واجهة تحكم + تقارير + تصنيف بالذكاء الاصطناعي
"""

import asyncio
import aiohttp
import logging
import json
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from config import (
    TELEGRAM_TOKEN, CHAT_ID,
    WHALE_ALERT_KEY, BINANCE_ENABLED,
    ETHERSCAN_KEY, COINGLASS_KEY,
    CHECK_INTERVAL,
    MIN_WHALE_USD, MIN_ETH_TRANSFER,
    VOLUME_SPIKE_MULTIPLIER, MIN_PRICE_CHANGE,
    MIN_OI_CHANGE_PCT, COOLDOWN_HOURS,
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
#  الحالة العامة للبوت
# ═══════════════════════════════════════════════
STATE = {
    "running": True,
    "signals_today": [],       # كل إشارات اليوم
    "total_signals": 0,
    "start_time": datetime.now(timezone.utc),
    "last_check": None,
}

sent_ids: set = set()
last_volumes: dict = {}
cooldown_tracker: dict = {}

def is_on_cooldown(key: str) -> bool:
    last = cooldown_tracker.get(key)
    if last and datetime.now(timezone.utc) - last < timedelta(hours=COOLDOWN_HOURS):
        return True
    cooldown_tracker[key] = datetime.now(timezone.utc)
    return False

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def classify_signal(source: str, symbol: str, usd: float, direction: str) -> dict:
    """تصنيف قوة الإشارة"""
    score = 0
    if usd >= 10_000_000: score += 3
    elif usd >= 5_000_000: score += 2
    else: score += 1

    if direction in ("تراكم", "شراء", "سحب من بورصة"): score += 2
    if source == "whale_alert": score += 1
    if source == "etherscan": score += 2

    if score >= 5:
        return {"label": "🔥 قوية جداً", "emoji": "🔥", "level": 3}
    elif score >= 3:
        return {"label": "⚡️ قوية", "emoji": "⚡️", "level": 2}
    else:
        return {"label": "👁 متوسطة", "emoji": "👁", "level": 1}


# ═══════════════════════════════════════════════
#  إرسال الإشارات
# ═══════════════════════════════════════════════
async def send_signal(bot: Bot, text: str, signal_data: dict):
    if not STATE["running"]:
        return
    try:
        # زر تحليل سريع
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 تفاصيل", callback_data=f"detail_{signal_data.get('symbol','?')}"),
            InlineKeyboardButton("🔕 تجاهل", callback_data="dismiss"),
        ]])
        await bot.send_message(
            chat_id=CHAT_ID, text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        STATE["total_signals"] += 1
        STATE["signals_today"].append({
            **signal_data,
            "time": utcnow().strftime("%H:%M"),
            "text_preview": text[:60],
        })
        # نحتفظ بآخر 50 إشارة فقط
        if len(STATE["signals_today"]) > 50:
            STATE["signals_today"] = STATE["signals_today"][-50:]

        log.info(f"✅ إشارة: {signal_data.get('symbol','?')} | {signal_data.get('direction','?')}")
    except Exception as e:
        log.error(f"send_signal: {e}")


# ═══════════════════════════════════════════════
#  1. WHALE ALERT
# ═══════════════════════════════════════════════
async def check_whale_alert(session: aiohttp.ClientSession, bot: Bot):
    if not WHALE_ALERT_KEY: return
    try:
        async with session.get(
            "https://api.whale-alert.io/v1/transactions",
            params={"api_key": WHALE_ALERT_KEY, "min_value": MIN_WHALE_USD, "limit": 10},
            timeout=10
        ) as r:
            if r.status != 200: return
            data = await r.json()

        for tx in data.get("transactions", []):
            tx_id = tx.get("id")
            if tx_id in sent_ids: continue
            sent_ids.add(tx_id)

            symbol    = tx.get("symbol", "").upper()
            amount    = tx.get("amount", 0)
            usd       = tx.get("amount_usd", 0)
            from_type = tx.get("from", {}).get("owner_type", "unknown")
            to_type   = tx.get("to", {}).get("owner_type", "unknown")
            from_name = tx.get("from", {}).get("owner", "غير معروف")
            to_name   = tx.get("to", {}).get("owner", "غير معروف")
            blockchain= tx.get("blockchain", "")
            tx_hash   = tx.get("hash", "")[:18]

            if to_type == "exchange":
                direction, note = "بيع محتمل", f"إيداع في *{to_name}*"
                arrow = "🔴"
            elif from_type == "exchange":
                direction, note = "تراكم", f"سحب من *{from_name}*"
                arrow = "🟢"
            else:
                direction, note = "تحويل", "محفظة → محفظة"
                arrow = "⚪️"

            if is_on_cooldown(f"whale_{symbol}_{direction}"): continue

            sig = classify_signal("whale_alert", symbol, usd, direction)

            msg = (
                f"{sig['emoji']} *إشارة حوت — {sig['label']}*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 العملة:   `{symbol}`\n"
                f"💵 القيمة:   `${usd:,.0f}`\n"
                f"📦 الكمية:   `{amount:,.0f} {symbol}`\n"
                f"{arrow} الإشارة:  *{direction}*\n"
                f"📝 {note}\n"
                f"⛓ الشبكة:   `{blockchain}`\n"
                f"🔗 `{tx_hash}...`\n"
                f"🕐 `{utcnow().strftime('%H:%M UTC')}`"
            )
            await send_signal(bot, msg, {"symbol": symbol, "direction": direction, "usd": usd, "source": "Whale Alert"})
    except Exception as e:
        log.error(f"Whale Alert: {e}")


# ═══════════════════════════════════════════════
#  2. BINANCE — Volume Spike
# ═══════════════════════════════════════════════
async def check_binance_volume(session: aiohttp.ClientSession, bot: Bot):
    if not BINANCE_ENABLED: return
    try:
        async with session.get("https://api.binance.com/api/v3/ticker/24hr", timeout=15) as r:
            tickers = await r.json()

        if isinstance(tickers, dict):
            tickers = [tickers]

        for t in tickers:
            if not isinstance(t, dict): continue
            sym    = t.get("symbol", "")
            if not sym.endswith("USDT"): continue

            vol_now = float(t.get("quoteVolume", 0))
            change  = float(t.get("priceChangePercent", 0))
            price   = float(t.get("lastPrice", 0))
            high    = float(t.get("highPrice", 0))
            low     = float(t.get("lowPrice", 0))

            prev = last_volumes.get(sym)
            last_volumes[sym] = vol_now
            if not prev or prev == 0: continue

            ratio = vol_now / prev
            if ratio < VOLUME_SPIKE_MULTIPLIER or abs(change) < MIN_PRICE_CHANGE: continue
            if is_on_cooldown(f"binance_{sym}"): continue

            direction = "صعود" if change > 0 else "هبوط"
            arrow     = "🚀" if change > 0 else "📉"
            sig       = classify_signal("binance", sym.replace("USDT",""), vol_now, direction)

            msg = (
                f"{sig['emoji']} *Volume Spike — {sig['label']}*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 العملة:     `{sym}`\n"
                f"💲 السعر:      `${price:,.4f}`\n"
                f"{arrow} التغير:     `{change:+.2f}%`\n"
                f"📊 ارتفاع حجم: `{ratio:.1f}x`\n"
                f"💰 الحجم:      `${vol_now:,.0f}`\n"
                f"📉 النطاق:     `${low:,.4f} — ${high:,.4f}`\n"
                f"🕐 `{utcnow().strftime('%H:%M UTC')}`"
            )
            await send_signal(bot, msg, {"symbol": sym, "direction": direction, "usd": vol_now, "source": "Binance"})
    except Exception as e:
        log.error(f"Binance: {e}")


# ═══════════════════════════════════════════════
#  3. ETHERSCAN
# ═══════════════════════════════════════════════
EXCHANGE_WALLETS = {
    "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be": "Binance",
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance 2",
    "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8": "Binance Cold",
    "0xab5c66752a9e8167967685f1450532fb96d5d24f": "Huobi",
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "OKX",
}

async def check_etherscan(session: aiohttp.ClientSession, bot: Bot):
    if not ETHERSCAN_KEY: return
    for addr, name in EXCHANGE_WALLETS.items():
        try:
            async with session.get(
                "https://api.etherscan.io/api",
                params={"module": "account", "action": "txlist", "address": addr,
                        "page": 1, "offset": 5, "sort": "desc", "apikey": ETHERSCAN_KEY},
                timeout=10
            ) as r:
                data = await r.json()

            for tx in data.get("result", []):
                h = tx.get("hash", "")
                if h in sent_ids: continue
                val = int(tx.get("value", 0)) / 1e18
                if val < MIN_ETH_TRANSFER: continue
                sent_ids.add(h)

                is_in  = tx.get("to", "").lower() == addr.lower()
                direction = "بيع محتمل" if is_in else "تراكم محتمل"
                arrow  = "📥" if is_in else "📤"

                if is_on_cooldown(f"eth_{addr}_{is_in}"): continue
                sig = classify_signal("etherscan", "ETH", val * 2500, direction)

                msg = (
                    f"{sig['emoji']} *On-Chain ETH — {sig['label']}*\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"🪙 العملة:  `ETH`\n"
                    f"{arrow} {'وارد إلى' if is_in else 'صادر من'}: *{name}*\n"
                    f"💰 الكمية:  `{val:,.2f} ETH`\n"
                    f"📊 الإشارة: *{direction}*\n"
                    f"🔑 `{h[:20]}...`\n"
                    f"🕐 `{utcnow().strftime('%H:%M UTC')}`"
                )
                await send_signal(bot, msg, {"symbol": "ETH", "direction": direction, "usd": val*2500, "source": "Etherscan"})
        except Exception as e:
            log.error(f"Etherscan [{name}]: {e}")


# ═══════════════════════════════════════════════
#  4. COINGLASS — Open Interest
# ═══════════════════════════════════════════════
async def check_coinglass(session: aiohttp.ClientSession, bot: Bot):
    if not COINGLASS_KEY: return
    try:
        async with session.get(
            "https://open-api.coinglass.com/public/v2/open_interest",
            headers={"coinglassSecret": COINGLASS_KEY},
            params={"symbol": "BTC,ETH,SOL,BNB,ARB,OP,INJ,TIA,PYTH,JUP"},
            timeout=10
        ) as r:
            data = await r.json()

        for item in data.get("data", []):
            symbol   = item.get("symbol", "")
            oi_chg   = float(item.get("openInterestChangePercent", 0))
            oi_usd   = float(item.get("openInterest", 0))

            if abs(oi_chg) < MIN_OI_CHANGE_PCT: continue
            if is_on_cooldown(f"oi_{symbol}"): continue

            direction = "تراكم عقود" if oi_chg > 0 else "تصفية عقود"
            arrow     = "🟢" if oi_chg > 0 else "🔴"
            sig       = classify_signal("coinglass", symbol, oi_usd, direction)

            msg = (
                f"{sig['emoji']} *Open Interest — {sig['label']}*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 العملة:   `{symbol}`\n"
                f"{arrow} التغير:    `{oi_chg:+.2f}%`\n"
                f"📊 الإشارة:  *{direction}*\n"
                f"💰 OI الكلي: `${oi_usd:,.0f}`\n"
                f"🕐 `{utcnow().strftime('%H:%M UTC')}`"
            )
            await send_signal(bot, msg, {"symbol": symbol, "direction": direction, "usd": oi_usd, "source": "CoinGlass"})
    except Exception as e:
        log.error(f"CoinGlass: {e}")


# ═══════════════════════════════════════════════
#  أوامر التحكم
# ═══════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 الإشارات اليوم", callback_data="today"),
         InlineKeyboardButton("📈 الحالة", callback_data="status")],
        [InlineKeyboardButton("⏸ إيقاف مؤقت", callback_data="pause"),
         InlineKeyboardButton("▶️ تشغيل", callback_data="resume")],
        [InlineKeyboardButton("📋 تقرير يومي", callback_data="report")],
    ])
    await update.message.reply_text(
        "🤖 *Smart Money Bot*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "مرحباً! اختر من القائمة 👇",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_status(update.message.reply_text)

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_today(update.message.reply_text)

async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_report(update.message.reply_text)

async def cmd_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    STATE["running"] = False
    await update.message.reply_text("⏸ البوت متوقف مؤقتاً. أرسل /resume للتشغيل.")

async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    STATE["running"] = True
    await update.message.reply_text("▶️ البوت يعمل الآن!")

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *الأوامر المتاحة:*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "/start — القائمة الرئيسية\n"
        "/status — حالة البوت\n"
        "/today — إشارات اليوم\n"
        "/report — تقرير مفصل\n"
        "/pause — إيقاف مؤقت\n"
        "/resume — تشغيل\n"
        "/help — المساعدة",
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════
#  الأزرار التفاعلية
# ═══════════════════════════════════════════════
async def btn_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "status":
        await send_status(q.message.reply_text)
    elif data == "today":
        await send_today(q.message.reply_text)
    elif data == "report":
        await send_report(q.message.reply_text)
    elif data == "pause":
        STATE["running"] = False
        await q.message.reply_text("⏸ البوت متوقف مؤقتاً.")
    elif data == "resume":
        STATE["running"] = True
        await q.message.reply_text("▶️ البوت يعمل!")
    elif data == "dismiss":
        await q.message.edit_reply_markup(reply_markup=None)
    elif data.startswith("detail_"):
        sym = data.replace("detail_", "")
        related = [s for s in STATE["signals_today"] if s.get("symbol","").startswith(sym)]
        if related:
            lines = [f"• {s['time']} | {s['direction']} | {s['source']}" for s in related[-5:]]
            await q.message.reply_text(
                f"📊 *إشارات {sym} اليوم:*\n" + "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await q.message.reply_text(f"لا توجد إشارات سابقة لـ {sym} اليوم.")


# ═══════════════════════════════════════════════
#  دوال التقارير
# ═══════════════════════════════════════════════
async def send_status(reply_fn):
    uptime = utcnow() - STATE["start_time"]
    hours  = int(uptime.total_seconds() // 3600)
    mins   = int((uptime.total_seconds() % 3600) // 60)
    status = "✅ يعمل" if STATE["running"] else "⏸ متوقف"
    sources = []
    if WHALE_ALERT_KEY: sources.append("Whale Alert")
    if BINANCE_ENABLED: sources.append("Binance")
    if ETHERSCAN_KEY:   sources.append("Etherscan")
    if COINGLASS_KEY:   sources.append("CoinGlass")

    await reply_fn(
        f"📈 *حالة البوت*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"الحالة:        {status}\n"
        f"وقت التشغيل:  `{hours}h {mins}m`\n"
        f"إشارات اليوم:  `{len(STATE['signals_today'])}`\n"
        f"إجمالي الإشارات: `{STATE['total_signals']}`\n"
        f"المصادر:       `{', '.join(sources) or 'لا يوجد'}`\n"
        f"آخر فحص:      `{STATE['last_check'] or 'لم يبدأ'}`",
        parse_mode=ParseMode.MARKDOWN,
    )

async def send_today(reply_fn):
    sigs = STATE["signals_today"]
    if not sigs:
        await reply_fn("📭 لا توجد إشارات اليوم حتى الآن.")
        return

    # إحصائيات
    buy  = sum(1 for s in sigs if "تراكم" in s.get("direction","") or "شراء" in s.get("direction",""))
    sell = sum(1 for s in sigs if "بيع" in s.get("direction","") or "تصفية" in s.get("direction",""))

    lines = [f"• `{s['time']}` {s['symbol']} — {s['direction']} ({s['source']})" for s in sigs[-10:]]
    await reply_fn(
        f"📊 *إشارات اليوم ({len(sigs)})*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 تراكم: {buy}  |  🔴 بيع: {sell}\n\n"
        + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )

async def send_report(reply_fn):
    sigs = STATE["signals_today"]
    if not sigs:
        await reply_fn("📭 لا توجد بيانات كافية للتقرير.")
        return

    # أكثر العملات إشارة
    counter = defaultdict(int)
    for s in sigs:
        counter[s.get("symbol","?")] += 1
    top = sorted(counter.items(), key=lambda x: x[1], reverse=True)[:5]
    top_lines = "\n".join([f"  {i+1}. `{sym}` — {cnt} إشارة" for i,(sym,cnt) in enumerate(top)])

    # توزيع المصادر
    sources = defaultdict(int)
    for s in sigs:
        sources[s.get("source","?")] += 1
    src_lines = "\n".join([f"  • {k}: {v}" for k,v in sources.items()])

    uptime = utcnow() - STATE["start_time"]
    hours  = int(uptime.total_seconds() // 3600)

    await reply_fn(
        f"📋 *التقرير اليومي*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {utcnow().strftime('%Y-%m-%d')}\n"
        f"⏱ وقت التشغيل: `{hours} ساعة`\n"
        f"📡 إجمالي الإشارات: `{len(sigs)}`\n\n"
        f"🏆 *أكثر العملات إشارة:*\n{top_lines}\n\n"
        f"📊 *توزيع المصادر:*\n{src_lines}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════
#  التقرير اليومي التلقائي
# ═══════════════════════════════════════════════
async def daily_report_job(bot: Bot):
    """يرسل تقرير يومي كل 24 ساعة"""
    while True:
        await asyncio.sleep(86400)  # 24 ساعة
        await send_report(lambda text, **kw: bot.send_message(
            chat_id=CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN
        ))
        STATE["signals_today"] = []  # تصفير إشارات اليوم


# ═══════════════════════════════════════════════
#  حلقة الفحص الرئيسية
# ═══════════════════════════════════════════════
async def scan_loop(bot: Bot):
    async with aiohttp.ClientSession() as session:
        while True:
            if STATE["running"]:
                STATE["last_check"] = utcnow().strftime("%H:%M UTC")
                log.info(f"🔍 {STATE['last_check']}")
                await asyncio.gather(
                    check_whale_alert(session, bot),
                    check_binance_volume(session, bot),
                    check_etherscan(session, bot),
                    check_coinglass(session, bot),
                )
            await asyncio.sleep(CHECK_INTERVAL)


# ═══════════════════════════════════════════════
#  التشغيل الرئيسي
# ═══════════════════════════════════════════════
async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # تسجيل الأوامر
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("today",  cmd_today))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("pause",  cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CallbackQueryHandler(btn_handler))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    bot = app.bot

    # رسالة ترحيب
    await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "🤖 *Smart Money Bot — النسخة الاحترافية*\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "✅ يعمل الآن بكامل الميزات\n\n"
            "📌 *الأوامر:*\n"
            "/start — القائمة الرئيسية\n"
            "/status — الحالة والإحصائيات\n"
            "/today — إشارات اليوم\n"
            "/report — تقرير مفصل\n"
            "/pause — إيقاف مؤقت\n"
            "/resume — تشغيل\n"
            "/help — المساعدة"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    # تشغيل المهام بالتوازي
    await asyncio.gather(
        scan_loop(bot),
        daily_report_job(bot),
    )

if __name__ == "__main__":
    asyncio.run(main())
