"""
Smart Money Tracker Bot 🤖
تنبيهات الأموال الذكية — فقط عند إشارة قوية
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from telegram import Bot
from telegram.constants import ParseMode
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
bot = Bot(token=TELEGRAM_TOKEN)

# ─── حماية من التكرار ──────────────────────────────────────
sent_whale_ids: set = set()
last_volumes: dict  = {}
cooldown_tracker: dict = {}

def is_on_cooldown(key: str) -> bool:
    last = cooldown_tracker.get(key)
    if last and datetime.utcnow() - last < timedelta(hours=COOLDOWN_HOURS):
        return True
    cooldown_tracker[key] = datetime.utcnow()
    return False


# ══════════════════════════════════════════════
#  1. WHALE ALERT
# ══════════════════════════════════════════════
async def check_whale_alert(session: aiohttp.ClientSession):
    if not WHALE_ALERT_KEY:
        return
    try:
        async with session.get(
            "https://api.whale-alert.io/v1/transactions",
            params={"api_key": WHALE_ALERT_KEY, "min_value": MIN_WHALE_USD, "limit": 10},
            timeout=10
        ) as r:
            if r.status != 200:
                return
            data = await r.json()

        for tx in data.get("transactions", []):
            tx_id = tx.get("id")
            if tx_id in sent_whale_ids:
                continue
            sent_whale_ids.add(tx_id)

            symbol     = tx.get("symbol", "").upper()
            amount     = tx.get("amount", 0)
            usd        = tx.get("amount_usd", 0)
            from_type  = tx.get("from", {}).get("owner_type", "unknown")
            to_type    = tx.get("to", {}).get("owner_type", "unknown")
            from_name  = tx.get("from", {}).get("owner", "غير معروف")
            to_name    = tx.get("to", {}).get("owner", "غير معروف")
            blockchain = tx.get("blockchain", "")
            tx_hash    = tx.get("hash", "")[:18]

            if to_type == "exchange":
                signal, note, strength = "🔴 بيع محتمل", f"إيداع في بورصة *{to_name}*", "⚠️ تحذير"
            elif from_type == "exchange":
                signal, note, strength = "🟢 تراكم قوي", f"سحب من بورصة *{from_name}*", "✅ إشارة شراء"
            else:
                signal, note, strength = "⚪️ تحويل ضخم", "محفظة → محفظة", "👁 راقب"

            if is_on_cooldown(f"whale_{symbol}_{signal}"):
                continue

            await send(
                f"{strength} *إشارة أموال ذكية قوية!*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 العملة:  `{symbol}`\n"
                f"💰 الكمية:  `{amount:,.0f} {symbol}`\n"
                f"💵 القيمة:  `${usd:,.0f}`\n"
                f"📊 الإشارة: {signal}\n"
                f"📝 {note}\n"
                f"⛓ الشبكة:  `{blockchain}`\n"
                f"🔗 Hash:    `{tx_hash}...`\n"
                f"🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
            )
    except Exception as e:
        log.error(f"Whale Alert: {e}")


# ══════════════════════════════════════════════
#  2. BINANCE — Volume Spike قوي
# ══════════════════════════════════════════════
async def check_binance_volume(session: aiohttp.ClientSession):
    if not BINANCE_ENABLED:
        return
    try:
        async with session.get("https://api.binance.com/api/v3/ticker/24hr", timeout=15) as r:
            tickers = await r.json()

        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue

            vol_now = float(t.get("quoteVolume", 0))
            change  = float(t.get("priceChangePercent", 0))
            price   = float(t.get("lastPrice", 0))
            high    = float(t.get("highPrice", 0))
            low     = float(t.get("lowPrice", 0))

            prev = last_volumes.get(sym)
            last_volumes[sym] = vol_now
            if not prev or prev == 0:
                continue

            ratio = vol_now / prev
            if ratio < VOLUME_SPIKE_MULTIPLIER or abs(change) < MIN_PRICE_CHANGE:
                continue
            if is_on_cooldown(f"binance_{sym}"):
                continue

            direction = "🟢 صعود قوي" if change > 0 else "🔴 هبوط حاد"
            emoji = "🚀" if change > 0 else "📉"

            await send(
                f"{emoji} *Volume Spike قوي على Binance!*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 العملة:      `{sym}`\n"
                f"💲 السعر:       `${price:,.4f}`\n"
                f"📈 التغير 24h:  `{change:+.2f}%` {direction}\n"
                f"📊 ارتفاع حجم:  `{ratio:.1f}x` مقارنة بالسابق\n"
                f"💰 حجم الآن:    `${vol_now:,.0f}`\n"
                f"📉 نطاق اليوم:  `${low:,.4f} — ${high:,.4f}`\n"
                f"🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
            )
    except Exception as e:
        log.error(f"Binance: {e}")


# ══════════════════════════════════════════════
#  3. ETHERSCAN — تدفقات On-Chain ضخمة
# ══════════════════════════════════════════════
EXCHANGE_WALLETS = {
    "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be": "Binance",
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance 2",
    "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8": "Binance Cold",
    "0xab5c66752a9e8167967685f1450532fb96d5d24f": "Huobi",
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "OKX",
}

async def check_etherscan(session: aiohttp.ClientSession):
    if not ETHERSCAN_KEY:
        return
    for addr, exchange_name in EXCHANGE_WALLETS.items():
        try:
            async with session.get(
                "https://api.etherscan.io/api",
                params={"module": "account", "action": "txlist", "address": addr,
                        "page": 1, "offset": 5, "sort": "desc", "apikey": ETHERSCAN_KEY},
                timeout=10
            ) as r:
                data = await r.json()

            for tx in data.get("result", []):
                tx_hash = tx.get("hash", "")
                if tx_hash in sent_whale_ids:
                    continue
                value_eth = int(tx.get("value", 0)) / 1e18
                if value_eth < MIN_ETH_TRANSFER:
                    continue
                sent_whale_ids.add(tx_hash)

                is_inflow = tx.get("to", "").lower() == addr.lower()
                direction = "📥 وارد إلى" if is_inflow else "📤 صادر من"
                signal    = "🔴 بيع محتمل" if is_inflow else "🟢 تراكم محتمل"

                if is_on_cooldown(f"eth_{addr}_{is_inflow}"):
                    continue

                await send(
                    f"🔗 *تحرك On-Chain ضخم — Ethereum!*\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"🏦 {direction} `{exchange_name}`\n"
                    f"💰 الكمية: `{value_eth:,.2f} ETH`\n"
                    f"📊 الإشارة: {signal}\n"
                    f"🔑 Hash: `{tx_hash[:20]}...`\n"
                    f"🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
                )
        except Exception as e:
            log.error(f"Etherscan [{exchange_name}]: {e}")


# ══════════════════════════════════════════════
#  4. COINGLASS — Open Interest
# ══════════════════════════════════════════════
async def check_coinglass(session: aiohttp.ClientSession):
    if not COINGLASS_KEY:
        return
    try:
        async with session.get(
            "https://open-api.coinglass.com/public/v2/open_interest",
            headers={"coinglassSecret": COINGLASS_KEY},
            params={"symbol": "BTC,ETH,SOL,BNB,ARB,OP,INJ,TIA,PYTH,JUP"},
            timeout=10
        ) as r:
            data = await r.json()

        for item in data.get("data", []):
            symbol    = item.get("symbol", "")
            oi_change = float(item.get("openInterestChangePercent", 0))
            oi_usd    = float(item.get("openInterest", 0))

            if abs(oi_change) < MIN_OI_CHANGE_PCT:
                continue
            if is_on_cooldown(f"oi_{symbol}"):
                continue

            direction = "🟢 تراكم عقود — صعود محتمل" if oi_change > 0 else "🔴 تصفية عقود — هبوط محتمل"

            await send(
                f"📊 *تغير Open Interest قوي!*\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🪙 العملة:   `{symbol}`\n"
                f"📈 التغير:   `{oi_change:+.2f}%`\n"
                f"📊 الإشارة: {direction}\n"
                f"💰 OI الكلي: `${oi_usd:,.0f}`\n"
                f"🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
            )
    except Exception as e:
        log.error(f"CoinGlass: {e}")


# ══════════════════════════════════════════════
#  إرسال
# ══════════════════════════════════════════════
async def send(text: str):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=ParseMode.MARKDOWN)
        log.info(f"✅ أُرسل: {text[:50]}...")
    except Exception as e:
        log.error(f"Telegram send: {e}")


# ══════════════════════════════════════════════
#  الحلقة الرئيسية
# ══════════════════════════════════════════════
async def main_loop():
    log.info("🚀 Smart Money Bot — وضع الإشارات القوية فقط")
    await send(
        "🤖 *Smart Money Bot شغّال!*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📡 يراقب: Whale Alert + Binance + Etherscan + CoinGlass\n"
        "🔕 الوضع: إشارات قوية فقط — لا spam\n"
        "✅ يعمل 24/7"
    )
    async with aiohttp.ClientSession() as session:
        while True:
            log.info(f"🔍 {datetime.utcnow().strftime('%H:%M:%S UTC')}")
            await asyncio.gather(
                check_whale_alert(session),
                check_binance_volume(session),
                check_etherscan(session),
                check_coinglass(session),
            )
            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main_loop())
