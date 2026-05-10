# 🤖 Smart Money Bot — دليل التشغيل على Railway

## الخطوة 1: أنشئ بوت تليغرام
1. افتح تليغرام وابحث عن `@BotFather`
2. أرسل `/newbot` واتبع التعليمات
3. احتفظ بـ **Token** اللي يعطيك إياه

## الخطوة 2: احصل على Chat ID
1. ابحث عن `@userinfobot` في تليغرام
2. أرسل له أي رسالة
3. سيعطيك **Your ID** — هذا هو الـ Chat ID

## الخطوة 3: المفاتيح الاختيارية (اختار اللي تريد)

### Whale Alert (تحركات الحيتان) — مجاني
- سجّل على https://whale-alert.io
- اذهب لـ API Keys وأنشئ مفتاح

### Etherscan (on-chain إيثيريوم) — مجاني
- سجّل على https://etherscan.io/apis
- أنشئ API Key مجاني

### CoinGlass (Open Interest) — مجاني محدود
- سجّل على https://coinglass.com

> ملاحظة: Binance يعمل بدون مفتاح تلقائياً ✅

## الخطوة 4: رفع المشروع على Railway
1. أنشئ حساب على https://railway.app
2. اضغط **New Project → Deploy from GitHub**
3. ارفع الملفات على GitHub repo جديد أو استخدم Railway CLI:
```bash
npm install -g @railway/cli
railway login
railway init
railway up
```

## الخطوة 5: إضافة المتغيرات في Railway
في لوحة Railway → **Variables** → أضف:

```
TELEGRAM_TOKEN   = TOKEN_من_BotFather
CHAT_ID          = رقمك_من_userinfobot
WHALE_ALERT_KEY  = (اختياري)
ETHERSCAN_KEY    = (اختياري)
COINGLASS_KEY    = (اختياري)
```

## الخطوة 6: تشغيل البوت
Railway سيشغّل البوت تلقائياً.
ستصلك رسالة على تليغرام:
> 🤖 Smart Money Bot شغّال!

---

## شكل التنبيهات

### 🐋 حركة حوت (Whale Alert)
```
🐋 حركة حوت كبيرة!
━━━━━━━━━━━━━━━━
🪙 العملة: ETH
💰 الكمية: 5,000 ETH
💵 القيمة: $12,500,000
📊 الإشارة: 🟢 تراكم محتمل
📝 سحب من بورصة Binance
⛓ الشبكة: ethereum
🕐 14:32 UTC
```

### ⚡️ Volume Spike (Binance)
```
⚡️ Volume Spike على Binance!
━━━━━━━━━━━━━━━━
🪙 العملة: INJUSDT
💲 السعر: $32.5400
📈 التغير 24h: +18.50% 🟢 صعود
📊 ارتفاع الحجم: 4.2x
💰 حجم الآن: $890,000,000
🕐 15:10 UTC
```

---

## تعديل الإعدادات
في ملف `config.py` أو متغيرات Railway:
- `CHECK_INTERVAL` — الفحص كل كم ثانية (افتراضي: 300 = 5 دقائق)
- `MIN_WHALE_USD` — أقل قيمة للحوت (افتراضي: مليون دولار)
- `VOLUME_SPIKE_MULTIPLIER` — نسبة ارتفاع الحجم (افتراضي: 3x)
