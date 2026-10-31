# TikTok Telegram Downloader — Flask + Render

بوت تيليجرام يعمل كـ Flask Web Service ويستقبل تحديثات Telegram عبر Webhook، ويستخدم Tikwm API.

## الوظائف
- تنزيل فيديو TikTok.
- تنزيل منشورات الصور (حتى 10 صور).
- إرسال الصوت إذا لم يتوفر فيديو/صور وكان رابط الصوت متاحاً من API.
- المفضلة باستخدام Telegram file IDs.
- سجل آخر 10 تحميلات.
- تخزين SQLite.

## النشر على Render

1. ارفع ملفات المشروع إلى GitHub.
2. في Render اختر **New → Blueprint** واربط المستودع الذي يحتوي `render.yaml`.
3. أضف قيمة `BOT_TOKEN` من BotFather.
4. أضف `WEBHOOK_URL` كرابط خدمة Render، مثال:
   `https://your-service-name.onrender.com`
5. `WEBHOOK_SECRET` يُنشأ تلقائياً من `render.yaml`.
6. انشر الخدمة. افتح رابط الخدمة في المتصفح؛ يجب أن ترى:
   `{"status":"ok","service":"TikTok Telegram Bot"}`

يمكن أيضاً إنشاء Web Service يدوياً:
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --workers 1 --threads 4 --timeout 120`
- Environment: `BOT_TOKEN`, `WEBHOOK_URL`, `WEBHOOK_SECRET`, `TIKWM_API`, `DATABASE_PATH`
- أضف Render Persistent Disk إلى `/var/data`، واجعل `DATABASE_PATH=/var/data/bot.db` حتى لا تضيع قاعدة البيانات عند إعادة النشر.

## تشغيل محلي

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

املأ المتغيرات ثم شغّل محلياً باستخدام عنوان HTTPS عام يصل إلى جهازك، لأن Telegram Webhook يحتاج عنواناً عاماً HTTPS:

```bash
gunicorn app:app --bind 0.0.0.0:10000
```

## متغيرات البيئة

| المتغير | الوصف |
|---|---|
| `BOT_TOKEN` | توكن Telegram من BotFather |
| `WEBHOOK_URL` | رابط Render الأساسي، دون `/` في النهاية |
| `WEBHOOK_SECRET` | سر عشوائي لمسار Webhook |
| `TIKWM_API` | عنوان Tikwm API |
| `DATABASE_PATH` | مسار قاعدة البيانات |
| `MAX_DOWNLOAD_MB` | الحد الأقصى لحجم الملف المؤقت |

## تنبيهات
- استخدم Render Persistent Disk لحفظ SQLite بين عمليات النشر وإعادة التشغيل. القرص الدائم قد لا يكون متاحاً في كل الخطط.
- إعداد `workers 1` مقصود لأن هذا المشروع يستخدم SQLite ومعالج Telegram واحداً؛ لا ترفع عدد workers دون إعادة تصميم إدارة التحديثات وقاعدة البيانات.
- خطة Render المجانية قد توقف الخدمة عند عدم النشاط، وبالتالي قد يتأخر وصول التحديثات حتى تستيقظ الخدمة.
- Tikwm API خدمة خارجية؛ بنية الاستجابة وتوفر روابط الصور/الفيديو/الصوت قد تتغير.
- حدود Telegram لحجم الملفات، وقيود Tikwm، والوقت المتاح للطلب قد تمنع بعض التنزيلات.
- لا تحفظ أو تعِد نشر محتوى لا تملك حق تنزيله أو مشاركته.
