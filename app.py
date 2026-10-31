import json
import logging
import os
import re
import sqlite3
import threading
from io import BytesIO

import requests
import telebot
from flask import Flask, jsonify

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TIKWM_API = os.getenv("TIKWM_API", "https://www.tikwm.com/api/").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
MAX_DOWNLOAD_MB = int(os.getenv("MAX_DOWNLOAD_MB", "48"))
MAX_DOWNLOAD_BYTES = MAX_DOWNLOAD_MB * 1024 * 1024

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tiktok-flask-bot")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
db_lock = threading.Lock()
polling_started = False
polling_lock = threading.Lock()

URL_RE = re.compile(
    r"https?://(?:www\.|vt\.|vm\.)?tiktok\.com/\S+",
    re.I
)


def connect_db():
    conn = sqlite3.connect(DATABASE_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = connect_db()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT,
                    media_type TEXT NOT NULL,
                    file_ids TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending (
                    user_id INTEGER PRIMARY KEY,
                    title TEXT,
                    media_type TEXT,
                    file_ids TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT,
                    media_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            conn.close()


def main_keyboard():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("⭐ المفضلة", callback_data="favorites"),
        telebot.types.InlineKeyboardButton("🕘 سجل التحميلات", callback_data="history"),
    )
    kb.add(telebot.types.InlineKeyboardButton("ℹ️ طريقة الاستخدام", callback_data="help"))
    return kb


def api_lookup(url):
    response = requests.get(
        TIKWM_API,
        params={"url": url, "hd": 1},
        timeout=45,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
        reason = payload.get("msg", "Tikwm API returned an unexpected response") if isinstance(payload, dict) else "Invalid API response"
        raise RuntimeError(str(reason))
    return payload["data"]


def download_bytes(url):
    if not url:
        raise RuntimeError("رابط الملف غير متوفر.")
    with requests.get(url, stream=True, timeout=(15, 90), headers={"User-Agent": "Mozilla/5.0"}) as response:
        response.raise_for_status()
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("حجم الملف أكبر من الحد المسموح.")
        chunks, total = [], 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("حجم الملف أكبر من الحد المسموح.")
            chunks.append(chunk)
        return b"".join(chunks)


def save_download(user_id, title, media_type):
    with db_lock:
        conn = connect_db()
        try:
            conn.execute(
                "INSERT INTO downloads(user_id,title,media_type) VALUES(?,?,?)",
                (user_id, title, media_type),
            )
            conn.commit()
        finally:
            conn.close()


def remember_favorite(user_id, title, media_type, file_ids):
    with db_lock:
        conn = connect_db()
        try:
            conn.execute(
                "INSERT INTO favorites(user_id,title,media_type,file_ids) VALUES(?,?,?,?)",
                (user_id, title, media_type, json.dumps(file_ids)),
            )
            conn.commit()
        finally:
            conn.close()


def send_download(message, data):
    title = (data.get("title") or "TikTok media").strip()[:900]
    images = data.get("images") or []
    file_ids = []
    media_type = ""

    if isinstance(images, list) and images:
        photo_urls = []
        for item in images[:10]:
            if isinstance(item, str):
                photo_urls.append(item)
            elif isinstance(item, dict):
                candidate = item.get("url") or item.get("url_list")
                if isinstance(candidate, list) and candidate:
                    photo_urls.append(candidate[0])
                elif isinstance(candidate, str):
                    photo_urls.append(candidate)
        if not photo_urls:
            raise RuntimeError("لم أجد روابط الصور في استجابة Tikwm.")
        media_type = "photos"
        for index, photo_url in enumerate(photo_urls):
            photo = BytesIO(download_bytes(photo_url))
            photo.name = f"tiktok_{index + 1}.jpg"
            sent = bot.send_photo(
                message.chat.id,
                photo,
                caption=title[:1024] if index == 0 else None,
            )
            if sent.photo:
                file_ids.append(sent.photo[-1].file_id)
    else:
        video_url = data.get("play") or data.get("hdplay") or data.get("wmplay")
        audio_url = data.get("music")
        if video_url:
            media_type = "video"
            media = BytesIO(download_bytes(video_url))
            media.name = "tiktok.mp4"
            sent = bot.send_video(
                message.chat.id, media, caption=title[:1024], supports_streaming=True
            )
            file_ids = [sent.video.file_id]
        elif audio_url:
            media_type = "audio"
            media = BytesIO(download_bytes(audio_url))
            media.name = "tiktok_audio.mp3"
            sent = bot.send_audio(message.chat.id, media, title=title[:64])
            file_ids = [sent.audio.file_id]
        else:
            raise RuntimeError("لم أجد فيديو أو صوراً أو صوتاً لهذا الرابط.")

    save_download(message.from_user.id, title, media_type)
    with db_lock:
        conn = connect_db()
        try:
            conn.execute(
                """INSERT INTO pending(user_id,title,media_type,file_ids)
                   VALUES(?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                   title=excluded.title, media_type=excluded.media_type, file_ids=excluded.file_ids""",
                (message.from_user.id, title, media_type, json.dumps(file_ids)),
            )
            conn.commit()
        finally:
            conn.close()

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("⭐ أضف إلى المفضلة", callback_data="save"))
    bot.send_message(message.chat.id, "تم التحميل بنجاح. ✨", reply_markup=markup)


@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        "أهلاً بك في بوت تحميل TikTok! 🎬\n\n"
        "أرسل رابط فيديو أو منشور صور من TikTok.\n"
        "يمكنك حفظ المحتوى في المفضلة واستعراض سجل التحميلات.",
        reply_markup=main_keyboard(),
    )


@bot.message_handler(commands=["help"])
def help_command(message):
    bot.send_message(
        message.chat.id,
        "طريقة الاستخدام:\n"
        "1) انسخ رابط منشور TikTok.\n"
        "2) أرسله هنا.\n"
        "3) سيحاول البوت إرسال الفيديو أو الصور المتاحة.\n\n"
        "الأوامر: /start — /favorites — /history\n"
        "الصوت متاح حسب ما يرجعه Tikwm API.",
    )


def show_favorites(chat_id, user_id):
    with db_lock:
        conn = connect_db()
        try:
            rows = conn.execute(
                "SELECT id,title FROM favorites WHERE user_id=? ORDER BY id DESC LIMIT 20",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
    if not rows:
        bot.send_message(chat_id, "⭐ لا توجد عناصر في المفضلة بعد.")
        return
    markup = telebot.types.InlineKeyboardMarkup()
    for row in rows:
        markup.add(telebot.types.InlineKeyboardButton(
            f"⭐ {(row['title'] or 'محتوى')[:35]}",
            callback_data=f"favopen:{row['id']}",
        ))
    bot.send_message(chat_id, "مفضلتك:", reply_markup=markup)


@bot.message_handler(commands=["favorites"])
def favorites_command(message):
    show_favorites(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["history"])
def history_command(message):
    with db_lock:
        conn = connect_db()
        try:
            rows = conn.execute(
                "SELECT title,media_type,created_at FROM downloads "
                "WHERE user_id=? ORDER BY id DESC LIMIT 10",
                (message.from_user.id,),
            ).fetchall()
        finally:
            conn.close()
    if not rows:
        bot.send_message(message.chat.id, "سجل التحميلات فارغ حالياً.")
        return
    lines = ["🕘 آخر التحميلات:"]
    for row in rows:
        lines.append(f"• {row['title'] or 'بدون عنوان'} — {row['media_type']} ({row['created_at']})")
    bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(func=lambda message: bool(message.text))
def handle_text(message):
    match = URL_RE.search(message.text.strip())
    if not match:
        bot.send_message(message.chat.id, "أرسل رابط TikTok صحيحاً.")
        return
    status = bot.send_message(message.chat.id, "⏳ جاري جلب المحتوى وتحضيره...")
    try:
        url = match.group(0).rstrip(").,،")
        data = api_lookup(url)
        send_download(message, data)
        bot.delete_message(message.chat.id, status.message_id)
    except Exception as exc:
        log.exception("Download error")
        bot.edit_message_text(
            f"تعذر التحميل: {str(exc)[:700]}",
            message.chat.id,
            status.message_id,
        )


@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    data = call.data or ""
    user_id, chat_id = call.from_user.id, call.message.chat.id

    if data == "help":
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "أرسل رابط منشور TikTok هنا.")
    elif data == "favorites":
        bot.answer_callback_query(call.id)
        show_favorites(chat_id, user_id)
    elif data == "history":
        bot.answer_callback_query(call.id)
        with db_lock:
            conn = connect_db()
            try:
                rows = conn.execute(
                    "SELECT title,media_type,created_at FROM downloads "
                    "WHERE user_id=? ORDER BY id DESC LIMIT 10",
                    (user_id,),
                ).fetchall()
            finally:
                conn.close()
        if not rows:
            bot.send_message(chat_id, "سجل التحميلات فارغ حالياً.")
        else:
            bot.send_message(chat_id, "\n".join(
                ["🕘 آخر التحميلات:"] +
                [f"• {r['title'] or 'بدون عنوان'} — {r['media_type']} ({r['created_at']})" for r in rows]
            ))
    elif data == "save":
        with db_lock:
            conn = connect_db()
            try:
                row = conn.execute(
                    "SELECT title,media_type,file_ids FROM pending WHERE user_id=?",
                    (user_id,),
                ).fetchone()
            finally:
                conn.close()
        if not row:
            bot.answer_callback_query(call.id, "لا يوجد محتوى حديث لحفظه.", show_alert=True)
            return
        remember_favorite(user_id, row["title"], row["media_type"], json.loads(row["file_ids"]))
        bot.answer_callback_query(call.id, "تمت الإضافة إلى المفضلة ⭐", show_alert=True)
    elif data.startswith("favopen:"):
        try:
            fav_id = int(data.split(":", 1)[1])
        except ValueError:
            bot.answer_callback_query(call.id, "عنصر غير صالح.", show_alert=True)
            return
        with db_lock:
            conn = connect_db()
            try:
                row = conn.execute(
                    "SELECT title,media_type,file_ids FROM favorites WHERE id=? AND user_id=?",
                    (fav_id, user_id),
                ).fetchone()
            finally:
                conn.close()
        if not row:
            bot.answer_callback_query(call.id, "العنصر غير موجود.", show_alert=True)
            return
        ids = json.loads(row["file_ids"])
        try:
            if row["media_type"] == "video":
                bot.send_video(chat_id, ids[0], caption=(row["title"] or "")[:1024])
            elif row["media_type"] == "audio":
                bot.send_audio(chat_id, ids[0], title=(row["title"] or "")[:64])
            else:
                for file_id in ids:
                    bot.send_photo(chat_id, file_id)
            bot.answer_callback_query(call.id, "تم إرسال العنصر.")
        except Exception:
            bot.answer_callback_query(call.id, "تعذر إعادة إرسال العنصر.", show_alert=True)


@app.get("/")
def health():
    return jsonify({"status": "ok", "service": "TikTok Telegram Bot", "mode": "polling"}), 200


def start_polling():
    global polling_started
    with polling_lock:
        if polling_started:
            return
        polling_started = True

    def runner():
        try:
            # Remove any old webhook so long polling can receive updates.
            bot.delete_webhook(drop_pending_updates=False)
            log.info("Starting Telegram long polling")
            bot.infinity_polling(
                timeout=25,
                long_polling_timeout=20,
                skip_pending=False,
                allowed_updates=["message", "callback_query"],
            )
        except Exception:
            log.exception("Telegram polling stopped")

    thread = threading.Thread(target=runner, name="telegram-polling", daemon=True)
    thread.start()


init_db()
start_polling()
