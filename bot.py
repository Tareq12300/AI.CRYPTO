import os
import asyncio
import logging
from datetime import datetime

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

INTERVAL_HOURS = int(os.environ.get("INTERVAL_HOURS", "4"))
TIMEFRAME = os.environ.get("TIMEFRAME", "4h")
LIMIT = int(os.environ.get("LIMIT", "120"))

COINS = [
    "BTC","ETH","BNB","SOL","XRP","ADA","AVAX","DOT","NEAR","ATOM",
    "TRX","LTC","XLM","HBAR","ALGO","LINK","UNI","AAVE","MKR","CRV",
    "ARB","OP","MATIC","IMX","INJ","SUI","APT","SEI","TIA","JUP",
    "FET","RENDER","RNDR","TAO","AKT","IO","AIOZ","STORJ","AR","FIL",
    "ONDO","POLYX","PAXG","PYTH","GRT","RUNE","PENDLE","ENA","LDO","EIGEN",
]

SYMBOL_MAP = {
    "RNDR": "RENDER"
}


async def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as http:
        r = await http.post(
            url,
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=20,
        )
        if not r.is_success:
            log.error(f"Telegram error {r.status_code}: {r.text[:300]}")


def normalize_symbol(symbol: str) -> str:
    return SYMBOL_MAP.get(symbol, symbol)


def tf_okx(tf):
    return {
        "1h": "1H",
        "4h": "4H",
        "1d": "1D",
    }.get(tf, "4H")


def tf_gate(tf):
    return {
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }.get(tf, "4h")


async def fetch_okx(symbol):
    s = normalize_symbol(symbol)
    pair = f"{s}-USDT"

    url = "https://www.okx.com/api/v5/market/candles"
    params = {
        "instId": pair,
        "bar": tf_okx(TIMEFRAME),
        "limit": str(LIMIT),
    }

    async with httpx.AsyncClient() as http:
        r = await http.get(url, params=params, timeout=20)

    if r.status_code != 200:
        log.warning(f"OKX failed for {symbol}: {r.status_code}")
        return None

    data = r.json().get("data", [])
    if not data:
        return None

    data = list(reversed(data))

    candles = [
        {
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        }
        for k in data
    ]

    return {
        "exchange": "OKX",
        "pair": pair,
        "candles": candles,
    }


async def fetch_gate(symbol):
    s = normalize_symbol(symbol)
    pair = f"{s}_USDT"

    url = "https://api.gateio.ws/api/v4/spot/candlesticks"
    params = {
        "currency_pair": pair,
        "interval": tf_gate(TIMEFRAME),
        "limit": LIMIT,
    }

    async with httpx.AsyncClient() as http:
        r = await http.get(url, params=params, timeout=20)

    if r.status_code != 200:
        log.warning(f"Gate failed for {symbol}: {r.status_code}")
        return None

    data = r.json()
    if not data:
        return None

    candles = [
        {
            "open": float(k[5]),
            "high": float(k[3]),
            "low": float(k[4]),
            "close": float(k[2]),
            "volume": float(k[1]),
        }
        for k in data
    ]

    return {
        "exchange": "Gate",
        "pair": pair,
        "candles": candles,
    }


async def fetch_market_data(symbol):
    fetchers = [
        fetch_okx,
        fetch_gate,
    ]

    results = await asyncio.gather(
        *[f(symbol) for f in fetchers],
        return_exceptions=True,
    )

    clean = []
    for r in results:
        if isinstance(r, dict) and r.get("candles"):
            clean.append(r)

    return clean


def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyze_exchange(symbol, item):
    candles = item["candles"]

    if len(candles) < 60:
        return None

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    volumes = [c["volume"] for c in candles]

    current_price = closes[-1]
    previous_price = closes[-2]

    resistance = max(highs[-51:-1])
    avg_volume = sum(volumes[-21:-1]) / 20
    current_volume = volumes[-1]

    if avg_volume <= 0:
        return None

    volume_ratio = current_volume / avg_volume
    current_rsi = calculate_rsi(closes)

    breakout_ok = current_price > resistance
    volume_ok = volume_ratio >= 1.8
    rsi_ok = current_rsi is not None and 35 <= current_rsi <= 72
    momentum_ok = current_price > previous_price

    # حماية من المقاومات الوهمية مثل: السعر 1.9 والمقاومة 8.5
    if resistance > current_price * 1.25:
        return None

    if breakout_ok and volume_ok and rsi_ok and momentum_ok:
        return {
            "symbol": symbol,
            "exchange": item["exchange"],
            "pair": item["pair"],
            "price": current_price,
            "resistance": resistance,
            "rsi": current_rsi,
            "volume_ratio": volume_ratio,
        }

    return None


def choose_best_signal(signals):
    if not signals:
        return None

    return sorted(signals, key=lambda x: x["volume_ratio"], reverse=True)[0]


async def analyze_symbol(symbol):
    market_data = await fetch_market_data(symbol)
    signals = []

    for item in market_data:
        signal = analyze_exchange(symbol, item)
        if signal:
            signals.append(signal)

    return choose_best_signal(signals)


async def run_analysis():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    await send_telegram(
        f"🔍 <b>بدأ تحليل {len(COINS)} عملة</b>\n"
        f"🏦 المنصات: <b>OKX / Gate</b>\n"
        f"⏱ الفريم: <b>{TIMEFRAME}</b>\n"
        f"🕐 {now}\n"
        f"⭐ فقط الاختراقات المؤكدة ببيانات حقيقية"
    )

    sent = 0

    for i, symbol in enumerate(COINS, start=1):
        try:
            log.info(f"[{i}/{len(COINS)}] تحليل {symbol}")

            signal = await analyze_symbol(symbol)

            if not signal:
                continue

            msg = (
                f"🟢 <b>{signal['symbol']} — شراء</b>\n\n"
                f"🏦 المنصة: <b>{signal['exchange']}</b>\n"
                f"📊 الزوج: <b>{signal['pair']}</b>\n"
                f"💵 السعر الحالي: <b>{signal['price']:.4f}</b>\n"
                f"🧱 المقاومة: <b>{signal['resistance']:.4f}</b>\n"
                f"📈 RSI: <b>{signal['rsi']:.1f}</b>\n"
                f"🔥 الفوليوم: <b>{signal['volume_ratio']:.1f}x</b>\n\n"
                f"📋 <b>سبب الشراء:</b>\n"
                f"➤ اختراق مقاومة حقيقية مع حجم تداول مرتفع و RSI صاعد.\n\n"
                f"⭐⭐ الثقة: عالية جداً\n"
                f"🕐 {datetime.now().strftime('%H:%M')}\n\n"
                f"⚠️ تحليل تعليمي، ليس نصيحة مالية"
            )

            await send_telegram(msg)
            sent += 1
            await asyncio.sleep(0.5)

        except Exception as e:
            log.error(f"{symbol} error: {e}")

        await asyncio.sleep(0.2)

    await send_telegram(
        f"✅ <b>اكتمل التحليل</b>\n"
        f"📨 أُرسل <b>{sent}</b> توصية من <b>{len(COINS)}</b> عملة\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )


async def main():
    log.info("Bot starting")

    await send_telegram(
        f"🚀 <b>بوت مراقبة العملات يعمل</b>\n\n"
        f"📊 عدد العملات: <b>{len(COINS)}</b>\n"
        f"🏦 المنصات: <b>OKX / Gate</b>\n"
        f"⏱ الفريم: <b>{TIMEFRAME}</b>\n"
        f"🔁 كل <b>{INTERVAL_HOURS}</b> ساعة\n"
        f"🟢 إشارات شراء فقط ببيانات سوق حقيقية\n\n"
        f"يبدأ التحليل الآن..."
    )

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_analysis, "interval", hours=INTERVAL_HOURS, id="main")
    scheduler.start()

    await run_analysis()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
