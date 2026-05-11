"""
إعدادات البوت — اعدّل هنا فقط
"""
import os

# ─── تليغرام ───────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID        = os.getenv("CHAT_ID", "")

# ─── مصادر البيانات ──────────────────────────────
WHALE_ALERT_KEY = os.getenv("WHALE_ALERT_KEY", "")
ETHERSCAN_KEY   = os.getenv("ETHERSCAN_KEY", "")
COINGLASS_KEY   = os.getenv("COINGLASS_KEY", "")

# ─── Binance/KuCoin/MEXC (مجاني بدون مفتاح) ─────
BINANCE_ENABLED = True

# ─── إعدادات الإشارات (مخففة لتشتغل) ─────────────
CHECK_INTERVAL          = 60 * 3    # فحص كل 3 دقائق

# 🐋 Whale Alert
MIN_WHALE_USD           = 1_000_000  # مليون دولار (كان 5M)

# ⚡ Volume Spike — البورصات
VOLUME_SPIKE_MULTIPLIER = 1.5        # 1.5x كافي (كان 5x — كان صعب جداً)
MIN_PRICE_CHANGE        = 3.0        # 3% (كان 5%)

# 🔗 Etherscan / Base
MIN_ETH_TRANSFER        = 50         # 50 ETH (كان 500)

# 📊 CoinGlass
MIN_OI_CHANGE_PCT       = 5.0        # 5% (كان 15%)

# 🔕 منع التكرار
COOLDOWN_HOURS          = 2          # ساعتان (كان 4)
