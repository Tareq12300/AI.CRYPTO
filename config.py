"""
إعدادات البوت
"""
import os

# ─── تليغرام ───────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID        = os.getenv("CHAT_ID", "")

# ─── مصادر البيانات ──────────────────────────────
WHALE_ALERT_KEY = os.getenv("WHALE_ALERT_KEY", "")
ETHERSCAN_KEY   = os.getenv("ETHERSCAN_KEY", "")
COINGLASS_KEY   = os.getenv("COINGLASS_KEY", "")
BINANCE_ENABLED = True

# ─── إعدادات الإشارات ─────────────────────────────
CHECK_INTERVAL          = 60 * 5   # كل 5 دقائق

# 🐋 Whale Alert
MIN_WHALE_USD           = 1_000_000  # مليون دولار+

# ⚡ Volume Spike
VOLUME_SPIKE_MULTIPLIER = 2.0        # ضعفان على الأقل
MIN_PRICE_CHANGE        = 4.0        # 4% تحرك سعر

# 🔗 Etherscan / Base
MIN_ETH_TRANSFER        = 100        # 100 ETH+

# 📊 CoinGlass
MIN_OI_CHANGE_PCT       = 8.0        # 8%+

# 🔕 Cooldown
COOLDOWN_HOURS          = 2
