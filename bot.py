import os
import asyncio
import logging
from datetime import datetime
import anthropic
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID        = os.environ["CHAT_ID"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
INTERVAL_HOURS = int(os.environ.get("INTERVAL_HOURS", "4"))
BATCH_SIZE     = int(os.environ.get("BATCH_SIZE", "10"))
MODEL_NAME     = os.environ.get("MODEL_NAME", "claude-sonnet-4-6")

# ─────────────────────────────────────────────────────────────────────────────
# 500 عملة جادة — مستثنى: ميم كوين، ألعاب، قمار، أسواق توقعات
# ─────────────────────────────────────────────────────────────────────────────
ALL_COINS = [
    # الكبار
    "BTC","ETH","BNB","SOL","XRP","ADA","AVAX","DOT","NEAR","ATOM",
    "TRX","LTC","XMR","ETC","XLM","VET","EGLD","HBAR","FTM","KSM",
    # Layer 1
    "MINA","ZEC","DASH","DCR","ZIL","ONE","CELO","ZEN","RVN","ALGO",
    "IOTA","XDC","HOLO","NKN","CTSI","IOTX","WAN","HIVE","STEEM","NULS",
    "COTI","ASTR","GLMR","MOVR","REEF","CLV","TOMO","MTR","SKALE","CANTO",
    "KLAY","EVMOS","NTRN","COREUM","AZERO","OASIS","EVER","LISK","ARK","DGB",
    "SCRT","ROSE","SYS","CKB","LUNC","LUNA2","KAVA","THETA","QNT","XTZ",
    "ICP","STX","FLOW","OSMO","VENOM","MASSA","DIONE","ALEPH","TRAC","CESS",
    "SYNTROPY","HOPR","CUDOS","CHEQ","NYM","DVPN","SYLO","ORDI","HARMONY","VELAS",
    "THUNDERCORE","FUSE","AURORA","EMERALD","ROOTSTOCK","ELASTOS","PIVX","ENERGI","WAX","WAXP",
    # Layer 2 / Rollups
    "ARB","OP","MATIC","IMX","ZK","STRK","MANTA","SCROLL","METIS","BOBA",
    "LRC","STG","ZRO","HOP","ACROSS","SYN","MULTI","POND","STARGATE","TAIKO",
    "ALT","TIA","SEI","DYM","SAGA","PORTAL","ZETA","LINEA","SONIC","HYPER",
    "MOVE","BERA","MON","SUI","APT","INJ","BASE2","SCROLL2","NEON","LAYERZ",
    # DeFi Core
    "UNI","AAVE","MKR","CRV","COMP","SNX","YFI","SUSHI","BAL","CVX",
    "1INCH","DYDX","GMX","PERP","GNS","LYRA","DOPEX","PREMIA","HEGIC","OPYN",
    "PENDLE","ETHFI","EIGEN","ENA","LDO","RPL","SSV","RUNE","DEXE","HYPE",
    "LISTA","WOO","DODO","KYBER","BANCOR","COW","GNO","SAFE","BLUR","NFTX",
    "LOOKS","UFT","RAMP","ALPACA","BELT","CAKE","DDX","DERI","UMA","VOLT",
    "UNCX","FLOOR","SUDO","SPELL","CREAM","IDLE","BOND","HARV","PICKLE","POLS",
    "FRAX","FXS","LUSD","MIM","RAI","LQTY","TRIBE","FEI","ANGLE","MSTABLE",
    "INDEX","DPI","MVI","DRIFT","LEVEL","VELA","PIKA","CAP","GAINS","KWENTA",
    "MORPHO","EULER","SILO","RADIANT","GRANARY","NOTIONAL","EXACTLY","TERM","SPECTRA","PENDLE2",
    "PSTAKE","STAFI","SWISE","METH","RETH","WBTC","RENBTC","CBBTC","TBTC","BTCB",
    # Oracle / Data
    "LINK","BAND","API3","DIA","SUPRA","TELLOR","PYTH","GRT","TRB","NMR",
    "NEST","DOS","UMBRELLA","RAZOR","WITNET","FLUX2","CHRONICLE","DXFEED","BIRDEYE","STORK",
    # AI / Compute / DePIN
    "FET","AGIX","RNDR","WLD","TAO","AKT","OCEAN","GRASS","ATH","IO",
    "PRIME","VIRTUAL","AIXBT","PAAL","ORAI","MATRIX","CTXC","AIOZ","DATA","RSS3",
    "MASK","PHA","DESO","AUDIO","LPT","STORJ","AR","HNT","GEODNET","HONEY",
    "SLEEPLESS","CARV","DEAI","SWARMS","ORBIT","FREYSA","ELIZA","GOAT","ALLORA","RITUALS",
    "MORPHEUS","KOLIN","DAIN","DEPIN","BICO","ENS","SPACE","MYRIA","RENDER","AKASH",
    # RWA
    "ONDO","CFG","MPL","CPOOL","TRU","GFI","CRED","NAOS","MCB","POLYX",
    "PAXG","XAUT","DGX","CACHE","MCO2","NCT","KLIMA","BCT","TOUCAN","REGEN",
    "MOBILE","IOT","KREST","XCN","DFI","SWINGBY","C3","BACKED","SUPERSTATE","BUIDL",
    "STBT","HARBOR","ARCHBLOCK","ARCA","POLYMATH","SECURITIZE","MAPLE2","GOLDFINCH2","TINLAKE","CENTRIFUGE2",
    # Privacy
    "PHALA","PENUMBRA","NAMADA","IRONFISH","GRIN","MWC","DERO","OXEN","HAVEN","CONCEAL",
    "PARTICL","NAVCOIN","ALEO","ESPRESSO","NOCTURNE","SINDRI","POLYHEDRA","RAILGUN","TORN","AZTEC",
    # Infrastructure / Web3
    "FIL","SC","FLUX","BZZ","SWARM","POKT","STRONG","NODL","CERAMIC","CYBERCONNECT",
    "LIT","RALLY","THETA3","MEDIA","DTUBE","SYLO2","PUSH","XMTP","DISCO","SPRUCE",
    "SISMO","FARCASTER","LENS","AIRSTACK","LIVEPEER2","OCEAN2","BICO2","ENS2","SPACE2","IEXEC",
    # Exchange Tokens
    "OKB","KCS","GT","MX","LEO","HT","CRO","NEXO","CEL","BGB",
    "WRX","ZT","BTSE","PROBIT","BITGET","BYBIT","MEXC","LATOKEN","COINW","BKEX",
    # Liquid Staking
    "WSTETH","CBETH","FRXETH","SFRXETH","SWETH","OSETH","ANKRBNB","STKBNB","BSTKBNB","BNBX",
    "MATICX","STMATIC","STDOT","LDOT","SDOT","CDOT","PDOT","RDOT","ADOT","VDOT",
    # Cosmos Ecosystem
    "JUNO","STARS","COMDEX","UMEE","ACRE","SENTINEL","HARD","USDX","STRIDE","QUICKSILVER",
    "PERSISTENCE","AGORIC","SOMMELIER","LAVA","NOBLE","DYMENSION","FETCH2","SWING","HARVEST2","REBUS",
    # Polkadot Ecosystem
    "ACA","KARURA","BIFROST","INTERLAY","PARALLEL","PHALA2","ZEITGEIST","LITENTRY","DARWINIA","KINTSUGI",
    "TURING","MANGATA","BASILISK","HEIKO","ALTAIR","SUBSOCIAL","ROBONOMICS","TERNOA","UNIQUE","KILT",
    # Solana Ecosystem (non-meme)
    "RAY","ORCA","JUP","JTO","FIDA","MNGO","SERUM","SLND","PORT","SABER",
    "SUNNY","LARIX","STEP","TULIP","COPE","GRAPE","RATIO","WARP","PYTH","BONFIDA",
    # إضافي
    "HMSTR",
]

seen: set[str] = set()
COINS: list[str] = []
for c in ALL_COINS:
    if c not in seen:
        seen.add(c)
        COINS.append(c)
COINS = COINS[:500]
log.info(f"Loaded {len(COINS)} unique coins")

ai_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


async def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as http:
        r = await http.post(
            url,
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        if not r.is_success:
            log.error(f"Telegram {r.status_code}: {r.text[:200]}")


async def analyze_batch(batch: list[str]) -> list[dict]:
    prompt = (
        f"أنت محلل عملات رقمية خبير. حلل هذه العملات: {', '.join(batch)}\n\n"
        "لكل عملة أعطني سطراً واحداً بهذا التنسيق:\n"
        "SYMBOL|شراء أو بيع|السبب في 8 كلمات|عالي أو متوسط أو منخفض\n\n"
        "قواعد:\n"
        "- شراء أو بيع فقط، لا محايد\n"
        "- لا تكتب أي نص إضافي\n"
        "- مثال: BTC|شراء|اختراق مقاومة مع حجم تداول مرتفع|عالي"
    )
    response = ai_client.messages.create(
        model=MODEL_NAME,
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    results = []
    for line in response.content[0].text.strip().split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4 and parts[0]:
            results.append({
                "symbol":     parts[0],
                "direction":  parts[1],
                "reason":     parts[2],
                "confidence": parts[3],
            })
    return results


async def run_analysis() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    log.info(f"Analysis started — {len(COINS)} coins — {now}")

    await send_telegram(
        f"🔍 <b>بدأ تحليل {len(COINS)} عملة</b>\n"
        f"🕐 {now}\n"
        f"⭐ فقط توصيات الثقة العالية"
    )

    sent = 0
    for i in range(0, len(COINS), BATCH_SIZE):
        batch = COINS[i : i + BATCH_SIZE]
        try:
            results = await analyze_batch(batch)
            for r in results:
                if "عالي" not in r["confidence"]:
                    continue
                is_buy  = "شراء" in r["direction"]
                is_sell = "بيع"  in r["direction"]
                if not is_buy and not is_sell:
                    continue

                emoji = "🟢" if is_buy else "🔴"
                label = "شراء" if is_buy else "بيع"
                msg = (
                    f"{emoji} <b>{r['symbol']} — {label}</b>\n"
                    f"📊 {r['reason']}\n"
                    f"⭐ ثقة: عالية\n\n"
                    f"⚠️ تحليل تعليمي، ليس نصيحة مالية"
                )
                await send_telegram(msg)
                sent += 1
                await asyncio.sleep(0.4)

            done = min(i + BATCH_SIZE, len(COINS))
            log.info(f"{done}/{len(COINS)} — signals: {sent}")

        except Exception as exc:
            log.error(f"Batch error: {exc}")

        await asyncio.sleep(2)

    await send_telegram(
        f"✅ <b>اكتمل التحليل</b>\n"
        f"📨 أُرسل <b>{sent}</b> توصية من <b>{len(COINS)}</b> عملة\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    log.info(f"Done — {sent} signals sent")


async def main() -> None:
    log.info(f"Bot starting — {len(COINS)} coins")
    await send_telegram(
        f"🚀 <b>بوت التوصيات يعمل على Railway!</b>\n\n"
        f"📊 <b>{len(COINS)}</b> عملة مراقبة\n"
        f"🔁 كل <b>{INTERVAL_HOURS}</b> ساعة\n"
        f"⭐ شراء/بيع بثقة عالية فقط\n"
        f"🚫 بدون ميم كوين أو ألعاب أو قمار\n\n"
        f"يبدأ التحليل الآن..."
    )

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_analysis, "interval", hours=INTERVAL_HOURS, id="main")
    scheduler.start()

    await run_analysis()

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
