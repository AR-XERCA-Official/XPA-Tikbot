# TikTok Telegram Bot — Flask + Render (Polling)

هذه النسخة لا تستخدم Webhook نهائياً. Flask يقدم مسار فحص صحة بسيط، والبوت يستقبل تحديثات Telegram باستخدام Long Polling.

## النشر على Render

1. ارفع ملفات هذا المجلد إلى مستودع GitHub.
2. من Render اختر **New → Web Service** ثم اربط المستودع.
3. اختر Runtime: Python.
4. Build Command:
   `pip install -r requirements.txt`
5. Start Command:
   `gunicorn app:app --workers 1 --threads 4 --timeout 120`
6. من Environment أضف متغيراً واحداً فقط:
   - Key: `BOT_TOKEN`
   - Value: توكن البوت من BotFather.
7. انشر الخدمة.

بعد أن تصبح الخدمة Live، افتح رابط Render. يجب أن يظهر JSON بحالة الخدمة. البوت يبدأ استقبال الرسائل تلقائياً عبر Polling.

## ملاحظات
- لا تضف WEBHOOK_URL أو WEBHOOK_SECRET؛ هذه النسخة لا تحتاجهما.
- استخدم Worker واحداً فقط لتجنب تشغيل أكثر من Polling process بنفس التوكن.
- قاعدة SQLite في هذا الإعداد تحفظ في مساحة الخدمة المحلية وقد تُفقد عند بعض عمليات إعادة النشر أو إعادة التشغيل. للحفظ الدائم أضف Persistent Disk يدوياً أو انقل قاعدة البيانات إلى خدمة تخزين دائمة.
- خطة Render المجانية قد توقف الخدمة عند عدم النشاط؛ هذا قد يقطع البوت أو يؤخر استجابته. تحقق من خطة Render الحالية.
- Tikwm API خدمة خارجية، وقد تتغير الحقول أو تتعطل بعض روابط التنزيل.
- بعض الصور/الأصوات/الفيديوهات قد لا تكون متاحة في API أو تتجاوز حدود Telegram/الخدمة.
- استخدم البوت لتنزيل المحتوى الذي تملك حق تنزيله أو مشاركته فقط.
