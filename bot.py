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

# ─── نظام النقاط ─────────────────────────────────────────────
# {symbol: {"score": int, "reasons": list, "last_update": datetime}}
SCORES: dict = {}

SCORE_WEIGHTS = {
    # المصدر
    "whale_alert":  3,
    "etherscan":    3,
    "binance":      2,
    "coinglass":    2,
    # الاتجاه
    "تراكم":        3,
    "تراكم محتمل":  2,
    "تراكم عقود":   2,
    "بيع محتمل":   -2,
    "بيع":         -3,
    "تصفية عقود":  -2,
    "تحويل":        1,
    "صعود":         2,
    "هبوط":        -2,
}

def add_score(symbol: str, source: str, direction: str, usd: float, reason: str):
    """أضف نقاط لعملة معينة"""
    sym = symbol.replace("USDT","").upper()
    if sym not in SCORES:
        SCORES[sym] = {"score": 0, "reasons": [], "last_update": utcnow()}

    pts = SCORE_WEIGHTS.get(source, 1) + SCORE_WEIGHTS.get(direction, 0)

    # مكافأة على الحجم
    if usd >= 10_000_000: pts += 2
    elif usd >= 5_000_000: pts += 1

    SCORES[sym]["score"] = max(-10, min(10, SCORES[sym]["score"] + pts))
    SCORES[sym]["last_update"] = utcnow()
    SCORES[sym]["reasons"].append(f"{reason} ({'+' if pts>0 else ''}{pts}pts)")
    # نحتفظ بآخر 5 أسباب فقط
    SCORES[sym]["reasons"] = SCORES[sym]["reasons"][-5:]

def get_top_scores(n: int = 5) -> list:
    """أعلى العملات نقاطاً (bullish)"""
    # نصفّر النقاط القديمة (+6 ساعات)
    now = utcnow()
    for sym in list(SCORES.keys()):
        if (now - SCORES[sym]["last_update"]).total_seconds() > 21600:
            SCORES[sym]["score"] = max(0, SCORES[sym]["score"] - 1)
    # نرجع الأعلى
    ranked = sorted(SCORES.items(), key=lambda x: x[1]["score"], reverse=True)
    return [(sym, data) for sym, data in ranked if data["score"] > 0][:n]

def score_bar(score: int) -> str:
    """شريط مرئي للنقاط من -10 إلى +10"""
    filled = max(0, score)
    empty  = max(0, 10 - filled)
    if score >= 7:   color = "🟢"
    elif score >= 4: color = "🟡"
    elif score >= 1: color = "🔵"
    else:            color = "🔴"
    return color + "█" * filled + "░" * empty + f" {score}/10"

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
        # ─── تحديث نظام النقاط ───
        add_score(
            symbol    = signal_data.get("symbol", "?"),
            source    = signal_data.get("source_key", "binance"),
            direction = signal_data.get("direction", ""),
            usd       = signal_data.get("usd", 0),
            reason    = signal_data.get("source", "?"),
        )
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
            await send_signal(bot, msg, {"symbol": symbol, "direction": direction, "usd": usd, "source": "Whale Alert", "source_key": "whale_alert"})
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
            await send_signal(bot, msg, {"symbol": sym, "direction": direction, "usd": vol_now, "source": "Binance", "source_key": "binance"})
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
                await send_signal(bot, msg, {"symbol": "ETH", "direction": direction, "usd": val*2500, "source": "Etherscan", "source_key": "etherscan"})
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
            await send_signal(bot, msg, {"symbol": symbol, "direction": direction, "usd": oi_usd, "source": "CoinGlass", "source_key": "coinglass"})
    except Exception as e:
        log.error(f"CoinGlass: {e}")


# ═══════════════════════════════════════════════
#  5. KUCOIN — Volume Spike
# ═══════════════════════════════════════════════
kucoin_volumes: dict = {}

async def check_kucoin(session, bot):
    try:
        async with session.get("https://api.kucoin.com/api/v1/market/allTickers", timeout=15) as r:
            data = await r.json()
        tickers = data.get("data", {}).get("ticker", [])
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("-USDT"):
                continue
            vol_now = float(t.get("volValue", 0))
            change  = float(t.get("changeRate", 0)) * 100
            price   = float(t.get("last", 0))
            prev = kucoin_volumes.get(sym)
            kucoin_volumes[sym] = vol_now
            if not prev or prev == 0:
                continue
            ratio = vol_now / prev
            if ratio < VOLUME_SPIKE_MULTIPLIER or abs(change) < MIN_PRICE_CHANGE:
                continue
            if is_on_cooldown(f"kucoin_{sym}"):
                continue
            direction = "\u0635\u0639\u0648\u062f" if change > 0 else "\u0647\u0628\u0648\u0637"
            emoji = "\U0001f680" if change > 0 else "\U0001f4c9"
            clean = sym.replace("-USDT", "")
            sig = classify_signal("binance", clean, vol_now, direction)
            parts = [
                f"{emoji} *Volume Spike \u0639\u0644\u0649 KuCoin \u2014 {sig['label']}*",
                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
                f"\U0001f7e1 \u0627\u0644\u0645\u0646\u0635\u0629:     `KuCoin`",
                f"\U0001fab9 \u0627\u0644\u0639\u0645\u0644\u0629:     `{clean}`",
                f"\U0001f4b2 \u0627\u0644\u0633\u0639\u0631:      `${price:,.4f}`",
                f"\U0001f4c8 \u0627\u0644\u062a\u063a\u064a\u0631:     `{change:+.2f}%`",
                f"\U0001f4ca \u0627\u0631\u062a\u0641\u0627\u0639 \u062d\u062c\u0645: `{ratio:.1f}x`",
                f"\U0001f4b0 \u0627\u0644\u062d\u062c\u0645:      `${vol_now:,.0f}`",
                f"\U0001f550 `{utcnow().strftime('%H:%M UTC')}`",
            ]
            await send_signal(bot, "\n".join(parts), {
                "symbol": clean, "direction": direction,
                "usd": vol_now, "source": "KuCoin", "source_key": "binance"
            })
    except Exception as e:
        log.error(f"KuCoin: {e}")


# ═══════════════════════════════════════════════
#  6. MEXC — Volume Spike
# ═══════════════════════════════════════════════
mexc_volumes: dict = {}

async def check_mexc(session, bot):
    try:
        async with session.get("https://api.mexc.com/api/v3/ticker/24hr", timeout=15) as r:
            tickers = await r.json()
        if isinstance(tickers, dict):
            tickers = [tickers]
        for t in tickers:
            if not isinstance(t, dict):
                continue
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            vol_now = float(t.get("quoteVolume", 0))
            change  = float(t.get("priceChangePercent", 0))
            price   = float(t.get("lastPrice", 0))
            prev = mexc_volumes.get(sym)
            mexc_volumes[sym] = vol_now
            if not prev or prev == 0:
                continue
            ratio = vol_now / prev
            if ratio < VOLUME_SPIKE_MULTIPLIER or abs(change) < MIN_PRICE_CHANGE:
                continue
            if is_on_cooldown(f"mexc_{sym}"):
                continue
            direction = "\u0635\u0639\u0648\u062f" if change > 0 else "\u0647\u0628\u0648\u0637"
            emoji = "\U0001f680" if change > 0 else "\U0001f4c9"
            clean = sym.replace("USDT", "")
            sig = classify_signal("binance", clean, vol_now, direction)
            parts = [
                f"{emoji} *Volume Spike \u0639\u0644\u0649 MEXC \u2014 {sig['label']}*",
                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
                f"\U0001f535 \u0627\u0644\u0645\u0646\u0635\u0629:     `MEXC`",
                f"\U0001fab9 \u0627\u0644\u0639\u0645\u0644\u0629:     `{clean}`",
                f"\U0001f4b2 \u0627\u0644\u0633\u0639\u0631:      `${price:,.4f}`",
                f"\U0001f4c8 \u0627\u0644\u062a\u063a\u064a\u0631:     `{change:+.2f}%`",
                f"\U0001f4ca \u0627\u0631\u062a\u0641\u0627\u0639 \u062d\u062c\u0645: `{ratio:.1f}x`",
                f"\U0001f4b0 \u0627\u0644\u062d\u062c\u0645:      `${vol_now:,.0f}`",
                f"\U0001f550 `{utcnow().strftime('%H:%M UTC')}`",
            ]
            await send_signal(bot, "\n".join(parts), {
                "symbol": clean, "direction": direction,
                "usd": vol_now, "source": "MEXC", "source_key": "binance"
            })
    except Exception as e:
        log.error(f"MEXC: {e}")


# ═══════════════════════════════════════════════
#  7. SOLANA On-Chain
# ═══════════════════════════════════════════════
SOL_EXCHANGE_WALLETS = {
    "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Binance SOL",
    "5tzFkiKscXHK5ZXCGbGuykoa7GBW8hxrCQLFDZFXi3ij": "Coinbase SOL",
}

async def check_solana(session, bot):
    for addr, name in SOL_EXCHANGE_WALLETS.items():
        try:
            async with session.get(
                "https://public-api.solscan.io/account/transactions",
                params={"account": addr, "limit": 5},
                headers={"accept": "application/json"},
                timeout=10
            ) as r:
                if r.status != 200:
                    continue
                txs = await r.json()
            for tx in (txs if isinstance(txs, list) else []):
                sig_id = tx.get("txHash", tx.get("signature", ""))
                if sig_id in sent_ids:
                    continue
                sol_amt = abs(tx.get("lamport", 0)) / 1e9
                if sol_amt < 1000:
                    continue
                sent_ids.add(sig_id)
                usd_val = sol_amt * 150
                if is_on_cooldown(f"sol_{addr}"):
                    continue
                parts = [
                    "\U0001f7e3 *\u062a\u062d\u0631\u0643 On-Chain \u2014 Solana!*",
                    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
                    f"\U0001f3e6 \u0627\u0644\u0645\u062d\u0641\u0638\u0629: `{name}`",
                    f"\U0001f4b0 \u0627\u0644\u0643\u0645\u064a\u0629:  `{sol_amt:,.0f} SOL`",
                    f"\U0001f4b5 \u0627\u0644\u0642\u064a\u0645\u0629:  `~${usd_val:,.0f}`",
                    f"\U0001f511 `{sig_id[:20]}...`",
                    f"\U0001f550 `{utcnow().strftime('%H:%M UTC')}`",
                ]
                await send_signal(bot, "\n".join(parts), {
                    "symbol": "SOL", "direction": "\u062a\u062d\u0648\u064a\u0644",
                    "usd": usd_val, "source": "Solana On-Chain", "source_key": "etherscan"
                })
        except Exception as e:
            log.error(f"Solana [{name}]: {e}")


# ═══════════════════════════════════════════════
#  8. BASE On-Chain
# ═══════════════════════════════════════════════
BASE_EXCHANGE_WALLETS = {
    "0x3304e22DDaa22bCdC5fCa2269b418046aE7b566A": "Coinbase Base",
}

async def check_base(session, bot):
    if not ETHERSCAN_KEY:
        return
    for addr, name in BASE_EXCHANGE_WALLETS.items():
        try:
            async with session.get(
                "https://api.basescan.org/api",
                params={"module": "account", "action": "txlist", "address": addr,
                        "page": 1, "offset": 5, "sort": "desc", "apikey": ETHERSCAN_KEY},
                timeout=10
            ) as r:
                data = await r.json()
            for tx in data.get("result", []):
                if not isinstance(tx, dict):
                    continue
                h = tx.get("hash", "")
                if h in sent_ids:
                    continue
                val = int(tx.get("value", 0)) / 1e18
                if val < 100:
                    continue
                sent_ids.add(h)
                is_in = tx.get("to", "").lower() == addr.lower()
                direction = "\u0628\u064a\u0639 \u0645\u062d\u062a\u0645\u0644" if is_in else "\u062a\u0631\u0627\u0643\u0645 \u0645\u062d\u062a\u0645\u0644"
                arrow = "\U0001f4e5" if is_in else "\U0001f4e4"
                if is_on_cooldown(f"base_{addr}_{is_in}"):
                    continue
                label = "\u0648\u0627\u0631\u062f \u0625\u0644\u0649" if is_in else "\u0635\u0627\u062f\u0631 \u0645\u0646"
                parts = [
                    "\U0001f535 *\u062a\u062d\u0631\u0643 On-Chain \u2014 Base!*",
                    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
                    f"\U0001f3e6 {arrow} {label}: `{name}`",
                    f"\U0001f4b0 \u0627\u0644\u0643\u0645\u064a\u0629:  `{val:,.2f} ETH`",
                    f"\U0001f4ca \u0627\u0644\u0625\u0634\u0627\u0631\u0629: *{direction}*",
                    f"\U0001f511 `{h[:20]}...`",
                    f"\U0001f550 `{utcnow().strftime('%H:%M UTC')}`",
                ]
                await send_signal(bot, "\n".join(parts), {
                    "symbol": "ETH", "direction": direction,
                    "usd": val * 2500, "source": "Base On-Chain", "source_key": "etherscan"
                })
        except Exception as e:
            log.error(f"Base [{name}]: {e}")



async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 الإشارات اليوم", callback_data="today"),
         InlineKeyboardButton("📈 الحالة", callback_data="status")],
        [InlineKeyboardButton("⏸ إيقاف مؤقت", callback_data="pause"),
         InlineKeyboardButton("▶️ تشغيل", callback_data="resume")],
        [InlineKeyboardButton("📋 تقرير يومي", callback_data="report")],
        [InlineKeyboardButton("🏆 أقوى العملات (نقاط)", callback_data="scores")],
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

async def cmd_scores(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_scores(update.message.reply_text)

async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_scores(update.message.reply_text)

async def send_scores(reply_fn):
    top = get_top_scores(8)
    if not top:
        no_data = (
            "📊 *نظام النقاط*\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "لا توجد بيانات كافية بعد.\n"
            "انتظر حتى تتراكم الإشارات 🕐"
        )
        await reply_fn(no_data, parse_mode=ParseMode.MARKDOWN)
        return

    lines_out = []
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"]
    for i, (sym, data) in enumerate(top):
        bar     = score_bar(data["score"])
        reasons = " | ".join(data["reasons"][-2:])
        entry = medals[i] + " *" + sym + "*\n`" + bar + "`\n_" + reasons + "_\n"
        lines_out.append(entry)

    header = (
        "🏆 *أقوى العملات الآن — نظام النقاط*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "النقاط تُجمع من كل المصادر تلقائياً\n\n"
    )
    ts     = utcnow().strftime('%H:%M UTC')
    footer = "\n🕐 `" + ts + "`\n_⚠️ ليس نصيحة مالية_"
    msg = header + "\n".join(lines_out) + footer
    await reply_fn(msg, parse_mode=ParseMode.MARKDOWN)

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
    elif data == "scores":
        await send_scores(q.message.reply_text)
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
ALERTED_SCORES: set = set()   # عملات أُرسل تنبيه نقاطها

async def check_score_alerts(bot: Bot):
    """تنبيه تلقائي حين عملة تتجاوز 7 نقاط"""
    top = get_top_scores(10)
    for sym, data in top:
        score = data["score"]
        key   = f"{sym}_{score // 2}"   # تنبّه كل مجموعتين
        if score >= 7 and key not in ALERTED_SCORES:
            ALERTED_SCORES.add(key)
            bar     = score_bar(score)
            reasons = "\n".join([f"  • {r}" for r in data["reasons"]])
            msg = (
                f"🚨 *تنبيه نقاط عالية!*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 العملة: *{sym}*\n"
                f"`{bar}`\n\n"
                f"📋 *الأسباب:*\n{reasons}\n\n"
                f"⚠️ _تجمّعت إشارات متعددة — راقب هذه العملة_\n"
                f"🕐 `{utcnow().strftime('%H:%M UTC')}`"
            )
            try:
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                log.error(f"score_alert: {e}")

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
                    check_kucoin(session, bot),
                    check_mexc(session, bot),
                    check_solana(session, bot),
                    check_base(session, bot),
                )
                await check_score_alerts(bot)
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
    app.add_handler(CommandHandler("scores", cmd_scores))
    app.add_handler(CommandHandler("top",    cmd_top))
    app.add_handler(CallbackQueryHandler(btn_handler))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    bot = app.bot

    # إشعار بسيط بدون قائمة الأوامر
    await bot.send_message(
        chat_id=CHAT_ID,
        text="🤖 *Smart Money Bot* — يعمل الآن ✅",
        parse_mode=ParseMode.MARKDOWN,
    )

    # تشغيل المهام بالتوازي
    await asyncio.gather(
        scan_loop(bot),
        daily_report_job(bot),
    )

if __name__ == "__main__":
    asyncio.run(main())
