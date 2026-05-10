"""
إعدادات البوت — اعدّل هنا فقط
"""
import os

# ─── تليغرام ───────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")   # من @BotFather
CHAT_ID        = os.getenv("CHAT_ID", "")           # معرفك الشخصي

# ─── مصادر البيانات (اتركها فارغة لو ما عندك) ──
WHALE_ALERT_KEY = os.getenv("WHALE_ALERT_KEY", "")  # whale-alert.io
ETHERSCAN_KEY   = os.getenv("ETHERSCAN_KEY", "")    # etherscan.io/apis
COINGLASS_KEY   = os.getenv("COINGLASS_KEY", "")    # coinglass.com/pricing

# ─── Binance (مجاني بدون مفتاح) ────────────────
BINANCE_ENABLED = True

# ─── إعدادات الإشارات ───────────────────────────
CHECK_INTERVAL       = 60 * 5    # فحص كل 5 دقائق (ثواني)

# 🐋 Whale Alert — إشارة قوية فقط
MIN_WHALE_USD        = 5_000_000  # حركة أكبر من 5 مليون دولار

# ⚡ Binance — إشارة قوية فقط
VOLUME_SPIKE_MULTIPLIER = 5.0    # حجم الآن = 5x المعدل الطبيعي
MIN_PRICE_CHANGE        = 5.0    # تحرك سعر +5% على الأقل

# 🔗 Etherscan — إشارة قوية فقط
MIN_ETH_TRANSFER        = 500    # أقل حد = 500 ETH (~مليون دولار+)

# 📊 CoinGlass — إشارة قوية فقط
MIN_OI_CHANGE_PCT       = 15.0   # تغير Open Interest أكبر من 15%

# 🔕 منع التكرار — لا يُرسل نفس الإشارة مرتين خلال ساعات
COOLDOWN_HOURS          = 4      # نفس العملة لا تتكرر قبل 4 ساعات
