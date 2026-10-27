# -*- coding: utf-8 -*-
"""ATRON (آترون) - a Telegram bot for managing PasarGuard panels.

Version 1.0 (first public release - more updates coming)
Author: SYE - https://github.com/devsye
License: MIT

Configuration (environment variables, or a config.json inside DATA_DIR):
  BOT_TOKEN   Telegram bot token from @BotFather
  ADMIN_ID    numeric Telegram user id of the owner
  DATA_DIR    where runtime data is stored (default: ./data)
  CHART_LANG  "en" (default) or "fa" for chart labels
"""
import json, os, io, csv, time, uuid, html, random, threading, datetime, re, base64
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import requests, urllib3
import telebot
from telebot import types

urllib3.disable_warnings()
BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE, "data")
os.makedirs(DATA_DIR, exist_ok=True)


def _load_cfg():
    c = {}
    cf = os.path.join(DATA_DIR, "config.json")
    if os.path.exists(cf):
        try:
            c = json.load(open(cf, encoding="utf-8"))
        except Exception:
            c = {}
    if os.environ.get("BOT_TOKEN"):
        c["token"] = os.environ["BOT_TOKEN"].strip()
    if os.environ.get("ADMIN_ID"):
        c["admin_id"] = os.environ["ADMIN_ID"].strip()
    if os.environ.get("CHART_LANG"):
        c["chart_lang"] = os.environ["CHART_LANG"].strip()
    if not c.get("token") or not c.get("admin_id"):
        raise SystemExit("BOT_TOKEN and ADMIN_ID are required (set them in .env or as environment variables).")
    return c


cfg = _load_cfg()
OWNER = int(cfg["admin_id"])
bot = telebot.TeleBot(cfg["token"], parse_mode="HTML", num_threads=8)
GB = 1024 ** 3

DB = os.path.join(DATA_DIR, "panels.json")
SETF = os.path.join(DATA_DIR, "settings.json")
TRF = os.path.join(DATA_DIR, "trash.json")
TRASH_DAYS = 7
tlock = threading.RLock()
lock = threading.Lock()
tokens, CACHE, ST, LAST = {}, {}, {}, {}

SE = {"active": "🟢", "disabled": "🚫", "expired": "⏳", "limited": "📦", "on_hold": "⏸"}


# ================= storage =================
def _read(path, default):
    with lock:
        if not os.path.exists(path):
            return default
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return default


def _write(path, data):
    with lock:
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def load():
    return _read(DB, [])


def save(panels):
    _write(DB, panels)


def settings():
    return _read(SETF, {"alerts": True})


# ================= language / green buttons / emoji-free submenus =================
LANG = settings().get("lang", "fa")
_FA_CH = "[\u0600-\u06FF]"
_TR_MAP = {}
_TR_RE = None


def set_lang(code):
    global LANG
    LANG = code if code in ("fa", "en") else "fa"
    s = settings()
    s["lang"] = LANG
    _write(SETF, s)


def _build_tr():
    global _TR_RE
    _TR_MAP.update({k: v for k, v in EN_PAIRS})
    parts = []
    for k in sorted(_TR_MAP, key=len, reverse=True):
        pre = r"(?<![\u0600-\u06FF\u200c])" if re.match(_FA_CH, k[0]) else ""
        post = r"(?![\u0600-\u06FF\u200c])" if re.match(_FA_CH, k[-1]) else ""
        parts.append(pre + re.escape(k) + post)
    _TR_RE = re.compile("|".join(parts))


def tr(t):
    """Translate outgoing Persian text to English when the bot language is English."""
    if LANG != "en" or not isinstance(t, str) or _TR_RE is None:
        return t
    return _TR_RE.sub(lambda m: _TR_MAP[m.group(0)], t)


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u25A0-\u25FF\u2600-\u2712\u2714-\u2716"
    "\u2718-\u27BF\u2900-\u297F\u2B00-\u2BFF\u3030\u303D\u3297\u3299\u00A9\u00AE\uFE0F\u200D\u20E3]")


def no_emoji(t):
    t = re.sub(r"\s+", " ", _EMOJI_RE.sub("", t)).strip()
    return t or tr("برگشت")


class _Btn(types.InlineKeyboardButton):
    """Inline button: always green (Bot API button style) + translated.
    Sub-menu buttons are emoji-free; main-menu buttons (BM) keep their emoji."""

    def __init__(self, text, *a, keep_emoji=False, **k):
        text = tr(text)
        if not keep_emoji:
            text = no_emoji(text)
        super().__init__(text, *a, **k)

    def to_dict(self):
        d = super().to_dict()
        d["style"] = "success"
        return d

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False)


def B(text, *a, **k):
    return _Btn(text, *a, **k)


def BM(text, *a, **k):
    return _Btn(text, *a, keep_emoji=True, **k)


def _wrap_send(name, tpos):
    f = getattr(bot, name)

    def w(*a, **k):
        a = list(a)
        if tpos is not None and len(a) > tpos:
            a[tpos] = tr(a[tpos])
        for key in ("text", "caption"):
            if isinstance(k.get(key), str):
                k[key] = tr(k[key])
        return f(*a, **k)
    setattr(bot, name, w)


for _n, _p in (("send_message", 1), ("edit_message_text", 0), ("reply_to", 1), ("answer_callback_query", None),
               ("send_photo", None), ("send_document", None), ("edit_message_caption", 0)):
    _wrap_send(_n, _p)

EN_PAIRS = [
    ('🔙 برگشت', '🔙 Back'),
    ('حذف کاربر؛ اول نسخه\u200cی کاربر در سطل زباله ذخیره می\u200cشود.', 'User deletion: a copy of the user is saved in the trash first.'),
    ('در سطل زباله پیدا نشد (شاید بیشتر از ۷ روز گذشته).', 'Not found in trash (maybe older than 7 days).'),
    ('👥 همه کاربران', '👥 All users'),
    ('🟢 کاربران آنلاین (۳ دقیقه اخیر)', '🟢 Online users (last 3 min)'),
    ('⏳ منقضی\u200cشده\u200cها', '⏳ Expired'),
    ('📦 حجم\u200cتمام\u200cشده\u200cها', '📦 Data limit reached'),
    ('🔥 بیشترین مصرف', '🔥 Top usage'),
    ('⏰ نزدیک انقضا (۷ روز)', '⏰ Expiring soon (7 days)'),
    ('📉 نزدیک اتمام حجم (۸۰٪+)', '📉 Near data limit (80%+)'),
    ('💤 بدون مصرف', '💤 No usage'),
    ('🚫 غیرفعال\u200cها', '🚫 Disabled'),
    ('🕸 بی\u200cفعالیت (۳۰ روز+)', '🕸 Inactive (30+ days)'),
    ('🗑 حذف همه منقضی\u200cها', '🗑 Delete all expired'),
    ('📅 تمدید منقضی\u200cها +۳۰ روز', '📅 Extend expired +30 days'),
    ('📅 تمدید نزدیک\u200cانقضاها +۳۰ روز', '📅 Extend expiring soon +30 days'),
    ('♻️ ریست مصرف حجم\u200cتمام\u200cشده\u200cها', '♻️ Reset usage of limited users'),
    ('➕ +۱۰GB به نزدیک\u200cاتمام\u200cها', '➕ +10GB to near-limit users'),
    ('✅ فعال\u200cسازی غیرفعال\u200cها', '✅ Enable disabled users'),
    ('🚫 غیرفعال\u200cسازی بدون\u200cمصرف\u200cها', '🚫 Disable no-usage users'),
    (' | آخرین: ', ' | Last: '),
    (' کاربر — صفحه ', ' users — page '),
    ('— خالی —', '— empty —'),
    ('⬅️ قبلی', '⬅️ Prev'),
    ('بعدی ➡️', 'Next ➡️'),
    ('🔙 پنل', '🔙 Panel'),
    ('🏠 <b>ATRON · آترون</b>\nمدیریت پنل\u200cهای پاسارگارد\nیکی از گزینه\u200cها را انتخاب کن:', '🏠 <b>ATRON</b>\nPasarGuard panel manager\nChoose an option:'),
    ('📖 <b>راهنما</b>\n\n• «پنل\u200cهای من»: افزودن و مدیریت پنل\u200cها\n• داخل هر پنل: آنلاین\u200cها، منقضی\u200cها، حجم\u200cتمام\u200cشده\u200cها، بیشترین مصرف، نزدیک انقضا، نزدیک اتمام حجم، بدون مصرف، غیرفعال\u200cها، بی\u200cفعالیت\u200cها\n• روی هر کاربر بزن: فعال/غیرفعال، ریست مصرف، افزودن حجم، تمدید، لینک ساب، ریوک ساب، یادداشت، حذف\n• ساخت کاربر، جستجو، عملیات گروهی، نودها، ادمین\u200cها\n• 🗑 سطل زباله: کاربران حذف\u200cشده با ربات تا ۷ روز قابل بازگردانی\u200cاند\n• 💾 بکاپ: بکاپ کلی پنل (ZIP) و خروجی کاربران\n• 💰 حجم کلی فروخته\u200cشده در صفحه\u200cی هر پنل و گزارش کلی\n• 📈 نمودار مصرف: روند مصرف در بازه\u200cهای ۲۴ساعت/۷/۳۰/۹۰ روز، پرمصرف\u200cها، وضعیت، انقضا، فعالیت، فروش، سلامت؛ خروجی داشبورد کامل (یک عکس) یا گالری نمودارها\n• 🔀 مهاجرت: با لینک سابسکریپشن (تکی/گروهی) یا پنل به پنل (انتخابی)، با تاریخچه و بازگردانی\n• هشدار خودکار: هر ۳۰ دقیقه کاربران نزدیک اتمام/انقضا و قطعی پنل را اطلاع می\u200cدهد\n\nآنلاین = فعالیت در ۳ دقیقه اخیر. لغو هر مرحله: /cancel', '📖 <b>Help</b>\n\n• «My panels»: add and manage panels\n• Inside each panel: online, expired, limited, top usage, expiring soon, near limit, no usage, disabled, inactive\n• Tap any user: enable/disable, reset usage, add data, extend, sub link, revoke sub, note, delete\n• Create user, search, bulk actions, nodes, admins\n• 🗑 Trash: users deleted via the bot can be restored for up to 7 days\n• 💾 Backup: full panel backup (ZIP) and users export\n• 💰 Total sold volume on each panel page and in the overall report\n• 📈 Usage charts: usage trend over 24h/7/30/90 day ranges, top consumers, status, expiry, activity, sales, health; output as a full dashboard (one image) or a chart gallery\n• 🔀 Migration: via subscription link (single/bulk) or panel to panel (selective), with history and restore\n• Auto alerts: every 30 minutes notifies about users near limit/expiry and panel outages\n\nOnline = activity in the last 3 minutes. Cancel any step: /cancel'),
    ('📋 پنل\u200cهای من', '📋 My panels'),
    ('🔀 مهاجرت', '🔀 Migration'),
    ('📊 گزارش کلی', '📊 Overall report'),
    ('📖 راهنما', '📖 Help'),
    ('➕ افزودن پنل', '➕ Add panel'),
    ('🏠 منو', '🏠 Menu'),
    ('📋 <b>پنل\u200cهای ثبت\u200cشده</b>\nیکی را انتخاب کن یا پنل جدید اضافه کن:', '📋 <b>Registered panels</b>\nPick one or add a new panel:'),
    ('<b>📊 آمار</b>', '<b>📊 Stats</b>'),
    ('</b> | 🚫 غیرفعال: <b>', '</b> | 🚫 Disabled: <b>'),
    ('</b> | 🟢 فعال: <b>', '</b> | 🟢 Active: <b>'),
    ('👥 کل: <b>', '👥 Total: <b>'),
    ('</b> | ⏸ در انتظار: <b>', '</b> | ⏸ On hold: <b>'),
    ('</b> | 📦 حجم\u200cتمام: <b>', '</b> | 📦 Limited: <b>'),
    ('⏳ منقضی: <b>', '⏳ Expired: <b>'),
    ('🟢 آنلاین الان: <b>', '🟢 Online now: <b>'),
    ('📈 مجموع مصرف: <b>', '📈 Total usage: <b>'),
    ('💰 حجم کلی فروخته\u200cشده: <b>', '💰 Total sold volume: <b>'),
    ('</b> | ♾ نامحدود: <b>', '</b> | ♾ Unlimited: <b>'),
    ('</b> کاربر', '</b> users'),
    ('🧮 مانده از فروخته\u200cشده: <b>', '🧮 Remaining of sold: <b>'),
    ('\n<b>👑 ادمین</b>\n', '\n<b>👑 Admin</b>\n'),
    ('\n<b>🖥 سیستم</b>\n', '\n<b>🖥 System</b>\n'),
    ('👥 همه', '👥 All'),
    ('⏰ نزدیک انقضا', '⏰ Expiring soon'),
    ('🔥 پرمصرف', '🔥 Top usage'),
    ('📉 نزدیک اتمام', '📉 Near limit'),
    ('🕸 بی\u200cفعالیت', '🕸 Inactive'),
    ('➕ ساخت کاربر', '➕ Create user'),
    ('🔍 جستجو', '🔍 Search'),
    ('🛠 عملیات گروهی', '🛠 Bulk actions'),
    ('🛰 نودها', '🛰 Nodes'),
    ('👑 ادمین\u200cها', '👑 Admins'),
    ('💾 بکاپ', '💾 Backup'),
    ('🗂 گروه\u200cها', '🗂 Groups'),
    ('🗑 سطل زباله (', '🗑 Trash ('),
    ('📈 نمودار مصرف و گزارش تصویری', '📈 Usage charts & visual report'),
    ('🔄 بروزرسانی', '🔄 Refresh'),
    ('🗑 حذف پنل', '🗑 Delete panel'),
    ('🔙 پنل\u200cها', '🔙 Panels'),
    (' (منقضی)', ' (expired)'),
    (' روز)', ' days)'),
    ('نامحدود', 'Unlimited'),
    ('هرگز', 'Never'),
    ('🟢 آنلاین', '🟢 Online'),
    ('وضعیت: <code>', 'Status: <code>'),
    ('  (مانده: ', '  (remaining: '),
    ('📊 مصرف: <b>', '📊 Usage: <b>'),
    ('📅 انقضا: ', '📅 Expiry: '),
    ('👁 آخرین اتصال: ', '👁 Last seen: '),
    ('🗂 گروه\u200cها: <code>', '🗂 Groups: <code>'),
    ('✅ فعال\u200cسازی', '✅ Enable'),
    ('♻️ ریست مصرف', '♻️ Reset usage'),
    ('➕ افزودن حجم', '➕ Add data'),
    ('📅 تمدید', '📅 Extend'),
    ('🔗 لینک ساب', '🔗 Sub link'),
    ('🔄 ریوک ساب', '🔄 Revoke sub'),
    ('📝 یادداشت', '📝 Note'),
    ('🗑 حذف', '🗑 Delete'),
    ('🗂 تغییر گروه', '🗂 Change group'),
    ('⏳ در حال جمع\u200cآوری گزارش همه پنل\u200cها...', '⏳ Collecting report of all panels...'),
    ('📊 <b>گزارش کلی همه پنل\u200cها</b>\n', '📊 <b>Overall report of all panels</b>\n'),
    (' | ⏳ منقضی ', ' | ⏳ Expired '),
    (' | 🟢 فعال ', ' | 🟢 Active '),
    ('\n<b>جمع کل</b>: 👥 ', '\n<b>Total</b>: 👥 '),
    (' | 💰 فروخته ', ' | 💰 Sold '),
    (' | 🔵 آنلاین ', ' | 🔵 Online '),
    ('❌ لغو', '❌ Cancel'),
    ('🌐 <b>آدرس پنل</b> را بفرست\nمثال: <code>https://panel.example.com:8000</code>', '🌐 Send the <b>panel URL</b>\nExample: <code>https://panel.example.com:8000</code>'),
    ('📦 <b>حجم</b> را به گیگابایت بفرست (۰ = نامحدود):', '📦 Send the <b>volume</b> in GB (0 = unlimited):'),
    ('❌ ساخت کاربر ناموفق:\n<code>', '❌ User creation failed:\n<code>'),
    ('✅ کاربر ساخته شد\n\n', '✅ User created\n\n'),
    ('🔗 لینک ساب:\n<code>', '🔗 Sub link:\n<code>'),
    ('👤 <b>یوزرنیم</b> ادمین را بفرست:', '👤 Send the admin <b>username</b>:'),
    ('🔑 <b>پسورد</b> را بفرست (پیامت بعد از دریافت پاک می\u200cشود):', '🔑 Send the <b>password</b> (your message is deleted after it is received):'),
    ('⏳ در حال اتصال به پنل...', '⏳ Connecting to panel...'),
    ('❌ اتصال/ورود ناموفق:\n<code>', '❌ Connection/login failed:\n<code>'),
    ('✅ پنل ذخیره شد.', '✅ Panel saved.'),
    ('✅ ورود موفق. در حال دریافت اطلاعات...', '✅ Login successful. Fetching data...'),
    ('🔍 جستجوی جدید', '🔍 New search'),
    (' کاربر\n\n', ' users\n\n'),
    ('🔍 نتیجه «', '🔍 Result «'),
    ('📅 <b>مدت</b> را به روز بفرست (۰ = نامحدود):', '📅 Send the <b>duration</b> in days (0 = unlimited):'),
    ('⚠️ عدد معتبر بفرست.', '⚠️ Send a valid number.'),
    ('⚠️ خطا: <code>', '⚠️ Error: <code>'),
    ('🆕 کاربران جدید', '🆕 New users'),
    ('🏆 پرمصرف\u200cترین\u200cها', '🏆 Top consumers'),
    ('📈 روند مصرف', '📈 Usage trend'),
    ('⏳ پیش\u200cبینی انقضا', '⏳ Expiry forecast'),
    ('🍩 وضعیت کاربران', '🍩 User status'),
    ('📊 توزیع مصرف حجم', '📊 Usage distribution'),
    ('💰 فروش و مانده', '💰 Sales & remaining'),
    ('🟢 فعالیت کاربران', '🟢 User activity'),
    ('🩺 سلامت و هشدارها', '🩺 Health & alerts'),
    ('🗂 توزیع گروه\u200cها', '🗂 Group distribution'),
    ('۲۴ ساعت', '24 hours'),
    ('۳۰ روز', '30 days'),
    ('۷ روز', '7 days'),
    ('۹۰ روز', '90 days'),
    ('۲۴ ساعت اخیر', 'Last 24 hours'),
    ('۷ روز اخیر', 'Last 7 days'),
    ('۳۰ روز اخیر', 'Last 30 days'),
    ('۹۰ روز اخیر', 'Last 90 days'),
    ('matplotlib نصب نیست. نصب کن: pip install matplotlib pillow arabic-reshaper', 'matplotlib is not installed. install it: pip install matplotlib pillow arabic-reshaper'),
    ('\n\n⏱ بازه: <b>', '\n\n⏱ Range: <b>'),
    ('📈 <b>نمودار و گزارش تصویری</b>\n🌐 ', '📈 <b>Chart & visual report</b>\n🌐 '),
    ('</b>\n🧩 بخش\u200cهای انتخاب\u200cشده: <b>', '</b>\n🧩 Selected sections: <b>'),
    ('\n\nبازه و بخش\u200cها را انتخاب کن، بعد خروجی را بگیر:\n🖼 <b>گزارش کامل</b> = یک تصویر داشبورد با همه\u200cی آمار و نمودارهای انتخابی\n🎨 <b>گالری نمودارها</b> = هر نمودار یک تصویر مستقل', '\n\nPick the range and sections, then get the output:\n🖼 <b>Full report</b> = one dashboard image with all stats and selected charts\n🎨 <b>Chart gallery</b> = each chart as a separate image'),
    ('</b> از ', '</b> of '),
    ('\n\n⚠️ matplotlib نصب نیست؛ برای تصویر این را نصب کن: <code>pip install matplotlib pillow arabic-reshaper</code>', '\n\n⚠️ matplotlib is not installed; for images, install: <code>pip install matplotlib pillow arabic-reshaper</code>'),
    ('☑️ انتخاب همه', '☑️ Select all'),
    ('🧹 هیچ\u200cکدام', '🧹 None'),
    ('🖼 گزارش تصویری کامل (داشبورد)', '🖼 Full visual report (dashboard)'),
    ('🎨 گالری نمودارها', '🎨 Chart gallery'),
    ('📄 خلاصه متنی', '📄 Text summary'),
    ('📤 ارسال همه\u200cی انتخاب\u200cشده\u200cها (', '📤 Send all selected ('),
    ('🔙 نمودارها', '🔙 Charts'),
    ('🎨 <b>گالری نمودارها</b>\nروی هر نمودار بزن تا همان یک تصویر ارسال شود، یا همه\u200cی انتخاب\u200cشده\u200cها را یکجا بفرست.\n⏱ بازه: <b>', '🎨 <b>Chart gallery</b>\nTap a chart to get that single image, or send all selected at once.\n⏱ Range: <b>'),
    ('⏳ در حال ساخت گزارش تصویری... (ممکن است چند ثانیه طول بکشد)', '⏳ Building visual report... (may take a few seconds)'),
    ('\n🖼 گزارش کامل مدیریتی', '\n🖼 Full management report'),
    ('🖼 همان گزارش با کیفیت کامل (فایل)', '🖼 Same report in full quality (file)'),
    ('⏳ در حال ساخت ', '⏳ Building '),
    ('⚠️ هیچ بخشی انتخاب نشده.', '⚠️ No section selected.'),
    (' تصویر...', ' images...'),
    ('⏳ در حال ساخت تصویر ', '⏳ Building image '),
    ('⏳ در حال محاسبه...', '⏳ Calculating...'),
    ('📄 <b>خلاصه مدیریتی ', '📄 <b>Management summary '),
    ('</b> | ✅ فعال: <b>', '</b> | ✅ Active: <b>'),
    ('</b> | 🟢 آنلاین: <b>', '</b> | 🟢 Online: <b>'),
    ('</b> | 🆕 جدید در بازه: <b>', '</b> | 🆕 New in range: <b>'),
    ('نامشخص (تاریخچه کافی نیست)', 'Unknown (not enough history)'),
    ('📈 مصرف بازه: <b>', '📈 Range usage: <b>'),
    ('📊 مصرف کل: <b>', '📊 Total usage: <b>'),
    ('</b> | مانده: <b>', '</b> | Remaining: <b>'),
    ('</b> | نرخ استفاده: <b>', '</b> | Usage rate: <b>'),
    ('💰 فروخته\u200cشده: <b>', '💰 Sold: <b>'),
    ('\n<b>🩺 هشدارهای مدیریتی</b>', '\n<b>🩺 Management alerts</b>'),
    ('\n<b>🏆 پرمصرف\u200cترین\u200cها</b>', '\n<b>🏆 Top consumers</b>'),
    ('⚠️ برای ساخت تصویر باید matplotlib نصب باشد.\nاین را نصب کن:\n<code>pip install matplotlib pillow arabic-reshaper</code>\nو بعد ربات را ری‌استارت کن.', '⚠️ matplotlib must be installed to build images.\nInstall:\n<code>pip install matplotlib pillow arabic-reshaper</code>\nthen restart the bot.'),
    ('📤 بکاپ کامل (JSON)', '📤 Full backup (JSON)'),
    ('📤 خروجی CSV (قابل باز شدن در اکسل)', '📤 CSV export (opens in Excel)'),
    (') از سقف ارسال تلگرام بیشتر است.', ') exceeds the Telegram upload limit.'),
    ('⚠️ حجم بکاپ (', '⚠️ Backup size ('),
    (' کاربر + ', ' users + '),
    ('📦 بکاپ کلی ', '📦 Full backup '),
    ('\n⚠️ در دسترس نبود: ', '\n⚠️ Unavailable: '),
    ('\n🔒 حاوی اطلاعات حساس است؛ جای امن نگه\u200cدار.', '\n🔒 Contains sensitive data; keep it somewhere safe.'),
    ('⏸ در انتظار', '⏸ On hold'),
    ('📦 حجم\u200cتمام', '📦 Limited'),
    ('🟢 فعال', '🟢 Active'),
    ('⏳ منقضی', '⏳ Expired'),
    ('🚫 غیرفعال', '🚫 Disabled'),
    ('🔀 <b>مهاجرت</b>\n\n🔗 <b>با لینک سابسکریپشن</b>: لینک سرویس مشتری (از هر پنلی) را بده؛ حجم مانده، انقضا و کانفیگ\u200cها تحلیل می\u200cشود و در پنل مقصد ساخته می\u200cشود. چند لینک هم می\u200cشود داد.\n\n🔀 <b>پنل به پنل</b>: کاربران، گروه\u200cها و تمپلیت\u200cها را انتخابی از یک پنل به پنل دیگر منتقل می\u200cکند.', '🔀 <b>Migration</b>\n\n🔗 <b>Via subscription link</b>: give the customer service link (from any panel); remaining volume, expiry and configs are analyzed and the user is created on the destination panel. You can give several links.\n\n🔀 <b>Panel to panel</b>: migrates users, groups and templates selectively from one panel to another.'),
    ('🔗 مهاجرت با لینک سابسکریپشن', '🔗 Migrate via subscription link'),
    ('🔀 مهاجرت پنل به پنل', '🔀 Migrate panel to panel'),
    ('📜 تاریخچه\u200cی مهاجرت\u200cها', '📜 Migration history'),
    ('➕ افزودن پنل جدید', '➕ Add new panel'),
    ('لینک باید با http یا https شروع شود', 'Link must start with http or https'),
    ('پاسخ لینک خیلی بزرگ است', 'Link response is too large'),
    ('کانفیگی در لینک پیدا نشد؛ UUID حفظ نمی\u200cشود و کاربر با اطلاعات جدید ساخته می\u200cشود.', 'No config found in the link; UUID will not be preserved and the user will be created with new data.'),
    ('اطلاعات حجم/انقضا در لینک نبود؛ با دکمه\u200cهای ویرایش خودت وارد کن.', 'No volume/expiry info in the link; enter it yourself with the edit buttons.'),
    ('تاریخ انقضا گذشته است.', 'Expiry date has passed.'),
    ('حجم تمام شده است (با حجم باقی\u200cمانده، حداقل ۱MB ثبت می\u200cشود).', 'Data is used up (created with a minimum of 1MB remaining).'),
    ('اطلاعاتی از لینک خوانده نشد', 'No info could be read from the link'),
    ('منقضی', 'Expired'),
    ('نامحدود/نامشخص', 'Unlimited/unknown'),
    ('، ', ', '),
    ('</b> | مصرف: <b>', '</b> | Usage: <b>'),
    ('📦 کل: <b>', '📦 Total: <b>'),
    ('🔌 کانفیگ\u200cها: <b>', '🔌 Configs: <b>'),
    ('قابل حفظ ✅', 'Preservable ✅'),
    ('پیدا نشد ⚠️', 'Not found ⚠️'),
    ('🔑 هویت (UUID/پسورد): ', '🔑 Identity (UUID/password): '),
    ('⚠️ لینک معتبری پیدا نشد.', '⚠️ No valid link found.'),
    (' لینک...', ' links...'),
    ('⏳ در حال تحلیل ', '⏳ Analyzing '),
    ('🔍 <b>نتیجه\u200cی تحلیل لینک</b>\n\n', '🔍 <b>Link analysis result</b>\n\n'),
    ('✏️ حجم', '✏️ Volume'),
    ('✏️ نام', '✏️ Name'),
    ('✏️ روز', '✏️ Days'),
    ('🔍 <b>نتیجه\u200cی تحلیل</b>: ✅ ', '🔍 <b>Analysis result</b>: ✅ '),
    ('\n\n✅ همه\u200cچیز خوانده شد؛ پنل مقصد را انتخاب کن.', '\n\n✅ Everything was read; choose the destination panel.'),
    ('\n\n✅ موارد سالم آماده\u200cاند؛ موارد ناموفق نادیده گرفته می\u200cشوند.', '\n\n✅ Valid items are ready; failed items are ignored.'),
    ('➡️ ادامه (انتخاب پنل مقصد)', '➡️ Continue (choose destination panel)'),
    ('گروه #', 'Group #'),
    ('✅ پنل اضافه شد.', '✅ Panel added.'),
    ('⏳ در حال خواندن اطلاعات پنل...', '⏳ Reading panel info...'),
    (' کاربر | 🗂 ', ' users | 🗂 '),
    (' گروه | 🧩 ', ' groups | 🧩 '),
    ('✅ مبدأ: <b>', '✅ Source: <b>'),
    (' تمپلیت\n\n📥 <b>پنل مقصد</b> را انتخاب کن:', ' templates\n\n📥 Choose the <b>destination panel</b>:'),
    ('❌ خواندن پنل ناموفق: <code>', '❌ Failed to read panel: <code>'),
    (' سرویس آماده\n\n📦 حجم: <b>', ' services ready\n\n📦 Volume: <b>'),
    ('🔗 <b>مهاجرت با لینک</b>\n📥 مقصد: <b>', '🔗 <b>Link migration</b>\n📥 Destination: <b>'),
    ('</b>\n🔑 حفظ UUID/پسورد: <b>', '</b>\n🔑 Keep UUID/password: <b>'),
    ('مانده (کل − مصرف)', 'Remaining (total − used)'),
    ('کل حجم', 'Total volume'),
    ('</b>\n🗂 گروه: <b>', '</b>\n🗂 Group: <b>'),
    ('بله', 'Yes'),
    ('خیر', 'No'),
    ('</b>\n🧪 حالت آزمایشی: <b>', '</b>\n🧪 Test mode: <b>'),
    ('خاموش', 'Off'),
    ('روشن', 'On'),
    ('کل', 'Total'),
    ('📦 حجم: ', '📦 Volume: '),
    ('🔑 حفظ UUID', '🔑 Keep UUID'),
    ('🗂 انتخاب گروه', '🗂 Choose group'),
    ('🧪 آزمایشی', '🧪 Test'),
    ('همه گروه\u200cها', 'All groups'),
    ('\n\n👥 انتخاب\u200cشده: <b>', '\n\n👥 Selected: <b>'),
    ('🔀 <b>مهاجرت پنل به پنل</b>\n📤 ', '🔀 <b>Panel to panel migration</b>\n📤 '),
    (' | ⚠️ تکراری در مقصد: <b>', ' | ⚠️ Duplicates at destination: <b>'),
    ('</b>\n💰 حجم فروخته\u200cشده\u200cی انتخابی: <b>', '</b>\n💰 Selected sold volume: <b>'),
    ('</b>\n🗂 گروه\u200cهای مبدأ: ', '</b>\n🗂 Source groups: '),
    ('\n🧩 تمپلیت\u200cها: ', '\n🧩 Templates: '),
    (' | در مقصد نیست: <b>', ' | Not at destination: <b>'),
    ('\n🎯 فیلتر گروه مبدأ: <b>', '\n🎯 Source group filter: <b>'),
    ('</b>\n🗂 گروه پیش\u200cفرض مقصد: <b>', '</b>\n🗂 Destination default group: <b>'),
    ('</b>\n\nهر گزینه را بزن تا روشن/خاموش شود. چیزی که ✓ دارد منتقل می\u200cشود:', '</b>\n\nTap each option to toggle it. Items marked ✓ will be migrated:'),
    ('👥 کاربران', '👥 Users'),
    ('🧩 تمپلیت\u200cها', '🧩 Templates'),
    ('⏭ تکراری: رد شود', '⏭ Duplicate: skip'),
    ('♻️ تکراری: بازنویسی', '♻️ Duplicate: overwrite'),
    ('✏️ تکراری: تغییر نام', '✏️ Duplicate: rename'),
    ('🎯 فیلتر گروه مبدأ', '🎯 Source group filter'),
    ('🗂 گروه پیش\u200cفرض مقصد', '🗂 Destination default group'),
    ('🚫 غیرفعال در مبدأ', '🚫 Disable at source'),
    ('🚀 شروع انتقال', '🚀 Start migration'),
    ('⏹ توقف', '⏹ Stop'),
    ('🔗 لینک\u200cهای ساب جدید (برای ارسال به مشتری\u200cها)', '🔗 New sub links (to send to customers)'),
    ('❌ مهاجرت با خطا متوقف شد:\n<code>', '❌ Migration stopped with an error:\n<code>'),
    ('⏳ در حال انتقال... ', '⏳ Migrating... '),
    (' (متوقف شد)', ' (stopped)'),
    ('✅ <b>مهاجرت با لینک تمام شد</b>', '✅ <b>Link migration finished</b>'),
    ('📥 مقصد: <b>', '📥 Destination: <b>'),
    ('</b> | ❌ خطا: <b>', '</b> | ❌ Errors: <b>'),
    ('✅ ساخته\u200cشده: <b>', '✅ Created: <b>'),
    ('\nℹ️ UUID/پسورد حفظ شد؛ فقط آدرس سرور و لینک ساب عوض می\u200cشود. لینک جدید را به مشتری بده.', '\nℹ️ UUID/password preserved; only the server address and sub link change. Give the new link to the customer.'),
    ('📜 تاریخچه / بازگردانی', '📜 History / Restore'),
    ('لینک ساب', 'Sub link'),
    ('🔗 لینک ساب جدید:\n<code>', '🔗 New sub link:\n<code>'),
    ('❌ خطاهای مهاجرت', '❌ Migration errors'),
    ('✅ <b>مهاجرت پنل به پنل تمام شد</b>', '✅ <b>Panel to panel migration finished</b>'),
    ('</b> | ♻️ بازنویسی: <b>', '</b> | ♻️ Overwritten: <b>'),
    ('⏭ رد شده (تکراری): <b>', '⏭ Skipped (duplicate): <b>'),
    ('ساخته\u200cشده', 'Created'),
    ('قابل ساخت', 'Creatable'),
    ('🗂 گروه ', '🗂 Group '),
    ('🧩 تمپلیت: ✅ ', '🧩 Template: ✅ '),
    ('🚫 غیرفعال\u200cشده در مبدأ: ', '🚫 Disabled at source: '),
    ('\nℹ️ هویت (UUID) حفظ شد ولی لینک ساب و آدرس سرور جدید است؛ فایل لینک\u200cهای جدید را برایت می\u200cفرستم.', '\nℹ️ Identity (UUID) preserved but the sub link and server address are new; I will send you the new links file.'),
    ('این مهاجرت پیدا نشد یا قبلاً بازگردانی شده.', 'This migration was not found or was already restored.'),
    ('❌ پنل مقصد دیگر در ربات ثبت نیست.', '❌ The destination panel is no longer registered in the bot.'),
    ('⏳ بازگردانی... ', '⏳ Restoring... '),
    ('\n✅ در مبدأ دوباره فعال شد: ', '\n✅ Re-enabled at source: '),
    (' (در سطل زباله ربات هم هست) | ❌ ', ' (also in the bot trash) | ❌ '),
    ('↩️ <b>بازگردانی انجام شد</b>\n🗑 از مقصد حذف شد: ', '↩️ <b>Restore done</b>\n🗑 Deleted from destination: '),
    ('🔙 تاریخچه', '🔙 History'),
    ('🔗 <b>لینک سابسکریپشن</b> را بفرست.\nمی\u200cتوانی چند لینک بفرستی (هر خط یکی، حداکثر ۵۰ تا).', '🔗 Send the <b>subscription link</b>.\nYou can send several links (one per line, max 50).'),
    ('📤 <b>پنل مبدأ</b> را انتخاب کن:', '📤 Choose the <b>source panel</b>:'),
    ('🔙 مهاجرت', '🔙 Migration'),
    ('\n\nچیزی ثبت نشده.', '\n\nNothing recorded.'),
    ('📜 <b>تاریخچه\u200cی مهاجرت\u200cها</b>', '📜 <b>Migration history</b>'),
    ('پیدا نشد.', 'Not found.'),
    ('↩️ بازگردانی (حذف ساخته\u200cشده\u200cها از مقصد)', '↩️ Restore (delete created users from destination)'),
    ('📦 <b>مهاجرت ', '📦 <b>Migration '),
    ('\n✅ ساخته\u200cشده: ', '\n✅ Created: '),
    ('\n🚫 غیرفعال در مبدأ: ', '\n🚫 Disabled at source: '),
    ('\nوضعیت: ', '\nStatus: '),
    ('بازگردانی شده ↩️', 'Restored ↩️'),
    ('⏳ در حال بازگردانی...', '⏳ Restoring...'),
    ('⏹ در حال توقف...', '⏹ Stopping...'),
    ('📥 <b>پنل مقصد</b> را انتخاب کن:', '📥 Choose the <b>destination panel</b>:'),
    ('✏️ حجم کل (گیگ؛ ۰ = نامحدود):', '✏️ Total volume (GB; 0 = unlimited):'),
    ('✏️ نام کاربری جدید:', '✏️ New username:'),
    ('✏️ چند روز از الان تا انقضا (۰ = نامحدود):', '✏️ Days from now until expiry (0 = unlimited):'),
    ('🚫 کاربران منتقل\u200cشده در مبدأ غیرفعال می\u200cشوند.', '🚫 Migrated users will be disabled at the source.'),
    ('♻️ کاربران تکراری در مقصد بازنویسی می\u200cشوند.', '♻️ Duplicate users at destination will be overwritten.'),
    ('⚠️ هیچ گروهی انتخاب نشده؛ اگر پنل مقصد گروه را اجباری بداند، ساخت کاربر خطا می\u200cدهد.', '⚠️ No group selected; if the destination panel requires a group, user creation will fail.'),
    ('🧪 حالت آزمایشی: چیزی ساخته نمی\u200cشود، فقط گزارش می\u200cگیری.', '🧪 Test mode: nothing is created, you just get a report.'),
    ('✅ تأیید و شروع', '✅ Confirm and start'),
    ('🔙 تنظیمات', '🔙 Settings'),
    (' کاربر منتقل می\u200cشود.\n', ' users will be migrated.\n'),
    ('⚠️ <b>تأیید نهایی</b>\n', '⚠️ <b>Final confirmation</b>\n'),
    ('⏳ شروع شد...', '⏳ Started...'),
    ('🗂 <b>گروه کاربر جدید</b>', '🗂 <b>New user group</b>'),
    ('🗂 <b>گروه کاربران در پنل مقصد</b>', '🗂 <b>Users group on destination panel</b>'),
    ('🗂 <b>گروه پیش\u200cفرض پنل مقصد</b>\n(برای کاربرانی که گروهشان قابل نگاشت نیست)', '🗂 <b>Default group of destination panel</b>\n(for users whose group cannot be mapped)'),
    ('🗂 <b>تغییر گروه\u200cهای کاربر</b>', '🗂 <b>Change user groups</b>'),
    ('🎯 <b>فیلتر گروه\u200cهای مبدأ</b>\n(فقط کاربران این گروه\u200cها منتقل شوند)', '🎯 <b>Source group filter</b>\n(only users of these groups are migrated)'),
    ('\n\n⚠️ گروهی در این پنل پیدا نشد.', '\n\n⚠️ No group found in this panel.'),
    ('\n(شاید دسترسی ادمین به گروه\u200cها محدود است.)', '\n(The admin may have limited access to groups.)'),
    ('🔄 تلاش دوباره', '🔄 Retry'),
    ('➖ ادامه بدون گروه', '➖ Continue without group'),
    ('همه', 'All'),
    ('\n\n🌐 پنل: <b>', '\n\n🌐 Panel: <b>'),
    ('</b>\n📌 انتخاب فعلی: <b>', '</b>\n📌 Current selection: <b>'),
    ('</b>\n📚 تعداد گروه\u200cها: <b>', '</b>\n📚 Number of groups: <b>'),
    ('⚠️ مجوز groups.read ندارید؛ گروه\u200cها از روی کاربران فعلی استخراج شد.\n', '⚠️ You do not have groups.read permission; groups were extracted from current users.\n'),
    ('\nیکی از دو روش را انتخاب کن:', '\nChoose one of the two methods:'),
    ('✅ انتخاب همه (', '✅ Select all ('),
    ('🎯 انتخاب دلخواه', '🎯 Custom selection'),
    ('➡️ ادامه با انتخاب فعلی (', '➡️ Continue with current selection ('),
    ('➖ بدون گروه', '➖ No group'),
    ('🧹 پاک کردن همه', '🧹 Clear all'),
    ('✍️ وارد کردن ID گروه', '✍️ Enter group ID'),
    ('✅ تأیید (', '✅ Confirm ('),
    ('\n\n🎯 <b>انتخاب دلخواه</b>: روی هر گروه بزن تا انتخاب/لغو شود.\nانتخاب\u200cشده: <b>', '\n\n🎯 <b>Custom selection</b>: tap each group to select/deselect.\nSelected: <b>'),
    ('⏳ در حال ساخت کاربر...', '⏳ Creating user...'),
    ('✅ گروه\u200cها بروزرسانی شد\n\n', '✅ Groups updated\n\n'),
    ('\n\n<b>پاسخ پنل:</b>\n<code>', '\n\n<b>Panel response:</b>\n<code>'),
    ('\n\nپنل لیست خالی برگرداند (گروهی ساخته نشده).', '\n\nThe panel returned an empty list (no groups created).'),
    ('🗂 گروهی دریافت نشد.', '🗂 No groups received.'),
    ('🗂 <b>گروه\u200cها (', '🗂 <b>Groups ('),
    (' کاربر | 🔌 ', ' users | 🔌 '),
    (' | ⛔ غیرفعال', ' | ⛔ Disabled'),
    (' اینباند', ' inbounds'),
    ('\n⚠️ ادمین شما مجوز groups.read ندارد؛ این گروه\u200cها از روی کاربران فعلی شما استخراج شده\u200cاند (نام واقعی ممکن است نیاید). گروه جدید را با «✍️ وارد کردن ID» در ساخت کاربر اضافه کن.', '\n⚠️ Your admin lacks groups.read permission; these groups were extracted from your current users (real names may not appear). Add a new group with «✍️ Enter ID» in user creation.'),
    ('✍️ <b>ID عددی گروه</b> را بفرست (چند تا را با فاصله یا ویرگول جدا کن).\nID را از داشبورد پنل یا از «🗂 تغییر گروه» یک کاربر قدیمی می\u200cتوانی پیدا کنی.', '✍️ Send the group <b>numeric ID</b> (separate several with space or comma).\nYou can find the ID in the panel dashboard or from «🗂 Change group» of an old user.'),
    ('⏳ در حال دریافت اطلاعات...', '⏳ Fetching info...'),
    (' روز قابل بازگردانی است)', ' days)'),
    ('حذف (به سطل زباله می\u200cرود و تا ', 'Delete (goes to trash; restorable for up to '),
    ('ریست مصرف', 'Reset usage'),
    ('ریوک ساب (لینک قبلی از کار می\u200cافتد)', 'Revoke sub (the previous link stops working)'),
    ('✅ بله', '✅ Yes'),
    ('❌ نه', '❌ No'),
    (' برای <code>', ' for <code>'),
    ('</code> انجام شود؟', '</code> — proceed?'),
    ('↩️ بازگردانی', '↩️ Restore'),
    (' روز می\u200cتوانی بازگردانی کنی.', ' days.'),
    ('</code> حذف شد و به سطل زباله رفت.\nتا ', '</code> deleted and moved to trash.\nYou can restore it within '),
    ('✅ انجام شد\n\n', '✅ Done\n\n'),
    ('✍️ عدد دلخواه', '✍️ Custom number'),
    ('</code> اضافه شود؟', '</code>?'),
    ('➕ چند گیگ به <code>', '➕ How many GB to add to <code>'),
    ('✅ حجم اضافه شد\n\n', '✅ Volume added\n\n'),
    ('✍️ مقدار حجم (گیگ) را بفرست:', '✍️ Send the amount of volume (GB):'),
    (' روز', ' days'),
    ('📅 چند روز به <code>', '📅 How many days to add to <code>'),
    ('✅ تمدید شد\n\n', '✅ Extended\n\n'),
    ('✍️ تعداد روز را بفرست:', '✍️ Send the number of days:'),
    ('📝 متن یادداشت را بفرست:', '📝 Send the note text:'),
    ('موجود نیست', 'Not available'),
    ('🔗 لینک ساب <b>', '🔗 Sub link <b>'),
    ('🔍 بخشی از نام کاربری را بفرست:', '🔍 Send part of the username:'),
    ('➕ <b>نام کاربری</b> جدید را بفرست:', '➕ Send the new <b>username</b>:'),
    ('🎲 نام تصادفی', '🎲 Random name'),
    ('🛠 <b>عملیات گروهی</b>\nقبل از اجرا تأیید می\u200cگیرم:', '🛠 <b>Bulk actions</b>\nI ask for confirmation before running:'),
    ('✅ اجرا', '✅ Run'),
    ('\n🗑 کاربران حذف\u200cشده به سطل زباله می\u200cروند.', '\n🗑 Deleted users go to the trash.'),
    ('</b>\nروی <b>', '</b>\nWill run on <b>'),
    ('</b> کاربر اجرا می\u200cشود. مطمئنی؟', '</b> users. Are you sure?'),
    (' کاربر...', ' users...'),
    ('⏳ در حال اجرا روی ', '⏳ Running on '),
    (' | ناموفق: ', ' | Failed: '),
    ('</b>\nموفق: ', '</b>\nSucceeded: '),
    ('🔙 عملیات گروهی', '🔙 Bulk actions'),
    ('هر دو آدرس /api/nodes و /api/node خطای 405 دادند', 'Both /api/nodes and /api/node returned 405'),
    ('🛰 نودها دریافت نشد.\n\n<b>پاسخ پنل:</b>\n<code>', '🛰 Could not fetch nodes.\n\n<b>Panel response:</b>\n<code>'),
    ('🛰 <b>نودها (', '🛰 <b>Nodes ('),
    ('🛰 نودی پیدا نشد / دسترسی ندارد.', '🛰 No nodes found / no access.'),
    ('👑 ادمین\u200cها دریافت نشد.\n\n<b>پاسخ پنل:</b>\n<code>', '👑 Could not fetch admins.\n\n<b>Panel response:</b>\n<code>'),
    ('👑 <b>ادمین\u200cها (', '👑 <b>Admins ('),
    ('👑 دسترسی به لیست ادمین\u200cها ندارید.', '👑 You do not have access to the admins list.'),
    ('📝 بکاپ متنی', '📝 Text backup'),
    ('📦 بکاپ کلی (فایل کامل پنل)', '📦 Full backup (complete panel file)'),
    ('👥 خروجی کاربران (JSON/CSV)', '👥 Users export (JSON/CSV)'),
    ('💾 <b>بکاپ</b>\nیکی را انتخاب کن:', '💾 <b>Backup</b>\nChoose one:'),
    ('📝 <b>بکاپ متنی</b>\n\nاین بخش فعلاً غیرفعال است و بعداً فعال می\u200cشود.', '📝 <b>Text backup</b>\n\nThis section is currently disabled and will be enabled later.'),
    ('🔙 بکاپ', '🔙 Backup'),
    ('⏳ در حال ساخت بکاپ کلی... (بسته به تعداد کاربر ممکن است کمی طول بکشد)', '⏳ Building full backup... (may take a while depending on the number of users)'),
    ('✅ بکاپ کلی ارسال شد.', '✅ Full backup sent.'),
    ('⏳ در حال ساخت خروجی کاربران...', '⏳ Building users export...'),
    ('✅ ارسال شد.', '✅ Sent.'),
    (' روز قابل بازگردانی\u200cاند.\n', ' days.\n'),
    (')\nکاربرانی که با ربات حذف شده\u200cاند تا ', ')\nUsers deleted via the bot can be restored for up to '),
    ('🗑 <b>سطل زباله</b> (', '🗑 <b>Trash</b> ('),
    (' روز مانده', ' days left'),
    ('</code> — حذف: ', '</code> — deleted: '),
    ('↩️ بازگردانی ', '↩️ Restore '),
    ('🧹 خالی کردن سطل', '🧹 Empty trash'),
    ('🗑 <b>سطل زباله</b> خالی است.', '🗑 <b>Trash</b> is empty.'),
    ('✅ کاربر بازگردانی شد (مصرف قبلی قابل بازگردانی نیست؛ حجم باقی\u200cمانده تنظیم شده)\n\n', '✅ User restored (previous usage cannot be restored; remaining volume was set)\n\n'),
    ('✅ بله، خالی شود', '✅ Yes, empty it'),
    ('⚠️ همه کاربران سطل زباله برای همیشه پاک شوند؟', '⚠️ Permanently delete all users in the trash?'),
    ('🧹 سطل زباله خالی شد.', '🧹 Trash emptied.'),
    ('✅ بله، حذف شود', '✅ Yes, delete'),
    ('⚠️ پنل از ربات حذف شود؟ (از خود پنل چیزی پاک نمی\u200cشود)', '⚠️ Remove the panel from the bot? (nothing is deleted from the panel itself)'),
    ('🗑 حذف شد. پنلی ثبت نشده.', '🗑 Deleted. No panel registered.'),
    ('</b> در دسترس نیست:\n<code>', '</b> is unreachable:\n<code>'),
    ('🚨 پنل <b>', '🚨 Panel <b>'),
    ('📉 نزدیک اتمام حجم (۹۰٪+)', '📉 Near data limit (90%+)'),
    ('⏰ انقضا تا ۲ روز آینده', '⏰ Expiring within 2 days'),
    ('\n… و ', '\n… and '),
    (' مورد دیگر', ' more'),
    ('🌍 زبان', '🌍 Language'),
    ('برگشت', 'Back'),
    ('🔙 منو', '🔙 Menu'),
]
_build_tr()



def get_panel(pid):
    for p in load():
        if p["id"] == pid:
            return p


# ================= helpers =================
def esc(x):
    return html.escape(str(x))


def fmt_bytes(n):
    try:
        n = float(n)
    except Exception:
        return str(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{int(n)} B" if u == "B" else f"{n:.2f} {u}"
        n /= 1024
    return f"{n:.2f} PB"


def num(t):
    t = t.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    return float(t.replace(",", ".").replace("٫", "."))


def parse_time(v):
    if v in (None, "", 0):
        return None
    try:
        if isinstance(v, (int, float)):
            return float(v) / (1000 if v > 1e11 else 1)
        s = str(v).strip()
        try:
            return float(s)
        except ValueError:
            pass
        d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return d.timestamp()
    except Exception:
        return None


def fdate(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"


def norm_url(u):
    u = u.strip()
    if not u.startswith("http"):
        u = "https://" + u
    if "/dashboard" in u:
        u = u.split("/dashboard")[0]
    return u.rstrip("/")


def host(p):
    return p["url"].replace("https://", "").replace("http://", "")


def dump(d, limit=12, skip=("password", "token")):
    lines = []
    for k, v in d.items():
        if v is None or isinstance(v, (dict, list)) or k in skip:
            continue
        if (isinstance(v, (int, float)) and not isinstance(v, bool)
                and any(x in k for x in ("traffic", "bandwidth", "usage", "mem", "disk")) and "cpu" not in k):
            v = fmt_bytes(v)
        lines.append(f"▫️ <b>{esc(k)}</b>: <code>{esc(v)}</code>")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def edit(msg, text, kb=None):
    text = tr(text)[:4000]
    try:
        bot.edit_message_text(text, msg.chat.id, msg.message_id, reply_markup=kb)
    except Exception as e:
        if "not modified" in str(e):
            return
        bot.send_message(msg.chat.id, text, reply_markup=kb)


def back_kb(cbk="m", label="🔙 برگشت"):
    kb = types.InlineKeyboardMarkup()
    kb.add(B(label, callback_data=cbk))
    return kb


# ================= panel API =================
def login(p):
    r = requests.post(p["url"] + "/api/admin/token",
                      data={"username": p["username"], "password": p["password"]},
                      timeout=20, verify=False)
    r.raise_for_status()
    t = r.json()["access_token"]
    tokens[p["id"]] = t
    return t


def req(p, method, path, params=None, body=None):
    for attempt in (0, 1):
        t = tokens.get(p["id"]) or login(p)
        r = requests.request(method, p["url"] + path, params=params, json=body, timeout=40,
                             verify=False, headers={"Authorization": "Bearer " + t})
        if r.status_code == 401 and attempt == 0:
            tokens.pop(p["id"], None)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code}: {r.text[:250]}")
        try:
            return r.json()
        except Exception:
            return {}


def first_ok(p, paths, params=None):
    for path in paths:
        try:
            return req(p, "GET", path, params)
        except Exception:
            continue
    return None


def users_all(p, force=False):
    c = CACHE.get(p["id"])
    if c and not force and time.time() - c[0] < 20:
        return c[1]
    rows, off, size = [], 0, 500
    while off < 50000:
        d = req(p, "GET", "/api/users", {"offset": off, "limit": size})
        us = d.get("users", []) if isinstance(d, dict) else d
        total = d.get("total", 0) if isinstance(d, dict) else 0
        rows += us
        off += len(us)
        if not us or (total and len(rows) >= total) or (not total and len(us) < size):
            break
    CACHE[p["id"]] = (time.time(), rows)
    return rows


def uinfo(u):
    now = time.time()
    used = u.get("used_traffic") or 0
    lim = u.get("data_limit") or 0
    exp = parse_time(u.get("expire"))
    on = parse_time(u.get("online_at"))
    st = u.get("status", "")
    return {
        "raw": u, "name": u.get("username", "?"), "st": st, "used": used, "lim": lim,
        "exp": exp, "on": on, "online": bool(on and now - on <= 180),
        "expired": st == "expired" or bool(exp and exp < now and st != "on_hold"),
        "ratio": (used / lim) if lim else 0,
    }


def sold_stats(xs):
    sold = sum(x["lim"] for x in xs if x["lim"])
    left = sum(max(x["lim"] - x["used"], 0) for x in xs if x["lim"])
    unl = sum(1 for x in xs if not x["lim"])
    return sold, left, unl


def X(p, force=False):
    return [uinfo(u) for u in users_all(p, force)]


# ---- user operations ----
def u_get(p, name):
    return req(p, "GET", f"/api/user/{name}")


def u_modify(p, name, body):
    CACHE.pop(p["id"], None)
    return req(p, "PUT", f"/api/user/{name}", body=body)


def trash_all():
    with tlock:
        d = _read(TRF, {})
        cut = time.time() - TRASH_DAYS * 86400
        changed = False
        for pid in list(d):
            keep = [t for t in d[pid] if t.get("at", 0) >= cut]
            if len(keep) != len(d[pid]):
                changed = True
            if keep:
                d[pid] = keep
            else:
                del d[pid]
                changed = True
        if changed:
            _write(TRF, d)
        return d


def trash_list(pid):
    return sorted(trash_all().get(pid, []), key=lambda t: -t["at"])


def trash_add(pid, raw):
    with tlock:
        d = trash_all()
        name = raw.get("username")
        items = [t for t in d.get(pid, []) if t["name"] != name]
        items.append({"name": name, "at": time.time(), "raw": raw})
        d[pid] = items
        _write(TRF, d)


def trash_remove(pid, name=None):
    with tlock:
        d = trash_all()
        if name is None:
            d.pop(pid, None)
        else:
            d[pid] = [t for t in d.get(pid, []) if t["name"] != name]
        _write(TRF, d)


def u_delete(p, name, raw=None):
    """حذف کاربر؛ اول نسخه‌ی کاربر در سطل زباله ذخیره می‌شود."""
    CACHE.pop(p["id"], None)
    if raw is None:
        raw = u_get(p, name)
    trash_add(p["id"], raw)
    try:
        return req(p, "DELETE", f"/api/user/{name}")
    except Exception:
        trash_remove(p["id"], name)
        raise


def trash_restore(p, name):
    item = next((t for t in trash_list(p["id"]) if t["name"] == name), None)
    if not item:
        raise RuntimeError("در سطل زباله پیدا نشد (شاید بیشتر از ۷ روز گذشته).")
    r = item["raw"]
    used = r.get("used_traffic") or 0
    lim = r.get("data_limit") or 0
    body = {"username": name, "status": "disabled" if r.get("status") == "disabled" else "active"}
    if lim:
        body["data_limit"] = max(int(lim - used), 1024 * 1024)
    exp = parse_time(r.get("expire"))
    if exp:
        body["expire"] = int(exp)
    if r.get("group_ids"):
        body["group_ids"] = r["group_ids"]
    if r.get("note"):
        body["note"] = r["note"]
    if r.get("data_limit_reset_strategy"):
        body["data_limit_reset_strategy"] = r["data_limit_reset_strategy"]
    extra = {}
    for k in ("proxy_settings", "proxies"):
        if r.get(k):
            extra[k] = r[k]
            break
    try:
        req(p, "POST", "/api/user", body={**body, **extra})
    except Exception:
        if not extra:
            raise
        req(p, "POST", "/api/user", body=body)
    CACHE.pop(p["id"], None)
    trash_remove(p["id"], name)


def u_reset(p, name):
    CACHE.pop(p["id"], None)
    return req(p, "POST", f"/api/user/{name}/reset")


def u_revoke(p, name):
    CACHE.pop(p["id"], None)
    return req(p, "POST", f"/api/user/{name}/revoke_sub")


def body_extend(x, days):
    body = {"expire": int(max(time.time(), x["exp"] or 0) + days * 86400)}
    if x["st"] == "expired":
        body["status"] = "active"
    return body


def body_volume(x, gb):
    body = {"data_limit": int((x["lim"] or x["used"]) + gb * GB)}
    if x["st"] == "limited":
        body["status"] = "active"
    return body


# ================= filters =================
FILT = {
    "all": ("👥 همه کاربران", lambda x: True, lambda x: x["name"].lower()),
    "online": ("🟢 کاربران آنلاین (۳ دقیقه اخیر)", lambda x: x["online"], lambda x: -(x["on"] or 0)),
    "expired": ("⏳ منقضی‌شده‌ها", lambda x: x["expired"], lambda x: -(x["exp"] or 0)),
    "limited": ("📦 حجم‌تمام‌شده‌ها",
                lambda x: x["st"] == "limited" or bool(x["lim"] and x["used"] >= x["lim"]), lambda x: -x["used"]),
    "top": ("🔥 بیشترین مصرف", lambda x: x["used"] > 0, lambda x: -x["used"]),
    "soon": ("⏰ نزدیک انقضا (۷ روز)",
             lambda x: bool(x["exp"]) and not x["expired"] and 0 < x["exp"] - time.time() <= 7 * 86400,
             lambda x: x["exp"]),
    "near": ("📉 نزدیک اتمام حجم (۸۰٪+)",
             lambda x: x["st"] == "active" and bool(x["lim"]) and x["ratio"] >= 0.8, lambda x: -x["ratio"]),
    "unused": ("💤 بدون مصرف", lambda x: x["used"] == 0, lambda x: x["name"].lower()),
    "disabled": ("🚫 غیرفعال‌ها", lambda x: x["st"] == "disabled", lambda x: x["name"].lower()),
    "idle": ("🕸 بی‌فعالیت (۳۰ روز+)",
             lambda x: x["st"] == "active" and (not x["on"] or time.time() - x["on"] > 30 * 86400),
             lambda x: x["on"] or 0),
}

BULK = {
    "delexp": ("🗑 حذف همه منقضی‌ها", "expired", "del", 0),
    "ext30": ("📅 تمدید منقضی‌ها +۳۰ روز", "expired", "ext", 30),
    "soon30": ("📅 تمدید نزدیک‌انقضاها +۳۰ روز", "soon", "ext", 30),
    "reset": ("♻️ ریست مصرف حجم‌تمام‌شده‌ها", "limited", "reset", 0),
    "add10": ("➕ +۱۰GB به نزدیک‌اتمام‌ها", "near", "vol", 10),
    "enable": ("✅ فعال‌سازی غیرفعال‌ها", "disabled", "on", 0),
    "disunused": ("🚫 غیرفعال‌سازی بدون‌مصرف‌ها", "unused", "off", 0),
}
KIND_BULK = {"expired": "delexp", "limited": "reset", "disabled": "enable", "near": "add10",
             "soon": "soon30", "unused": "disunused"}


def line(i, x, kind):
    lim = fmt_bytes(x["lim"]) if x["lim"] else "∞"
    if x["exp"]:
        d = (x["exp"] - time.time()) / 86400
        exp = f"{int(d)}d" if d >= 0 else "منقضی"
    else:
        exp = "∞"
    extra = " 🟢" if x["online"] else ""
    if kind == "idle":
        extra = f" | آخرین: {fdate(x['on'])[:10] if x['on'] else 'هرگز'}"
    if kind == "near":
        extra = f" | {int(x['ratio'] * 100)}%"
    return (f"{i}. {SE.get(x['st'], '▫️')} <code>{esc(x['name'])}</code> — "
            f"{fmt_bytes(x['used'])}/{lim} — {exp}{extra}")


def users_kb(pid, items, start=1):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(*[B(f"{i}. {x['name']}"[:30], callback_data=f"U:{pid}:{x['name']}")
             for i, x in enumerate(items, start)])
    return kb


def list_view(p, kind, page):
    title, fl, key = FILT[kind]
    items = sorted([x for x in X(p) if fl(x)], key=key)
    if kind == "top":
        items = items[:50]
    size = 10
    total = len(items)
    pages = max(1, (total + size - 1) // size)
    page = max(0, min(page, pages - 1))
    chunk = items[page * size:(page + 1) * size]
    text = f"<b>{title}</b>\n{total} کاربر — صفحه {page + 1}/{pages}\n\n"
    text += "\n".join(line(page * size + i, x, kind) for i, x in enumerate(chunk, 1)) or "— خالی —"
    kb = users_kb(p["id"], chunk, page * size + 1)
    nav = []
    if page > 0:
        nav.append(B("⬅️ قبلی", callback_data=f"L:{p['id']}:{kind}:{page - 1}"))
    if page < pages - 1:
        nav.append(B("بعدی ➡️", callback_data=f"L:{p['id']}:{kind}:{page + 1}"))
    if nav:
        kb.row(*nav)
    if kind in KIND_BULK and total:
        kb.add(B(f"🛠 {BULK[KIND_BULK[kind]][0]} ({total})", callback_data=f"B:{p['id']}:{KIND_BULK[kind]}"))
    kb.add(B("🔙 پنل", callback_data=f"p:{p['id']}"))
    return text, kb


# ================= views =================
MENU_TXT = "🏠 <b>ATRON · آترون</b>\nمدیریت پنل‌های پاسارگارد\nیکی از گزینه‌ها را انتخاب کن:"
HELP = ("📖 <b>راهنما</b>\n\n"
        "• «پنل‌های من»: افزودن و مدیریت پنل‌ها\n"
        "• داخل هر پنل: آنلاین‌ها، منقضی‌ها، حجم‌تمام‌شده‌ها، بیشترین مصرف، نزدیک انقضا، "
        "نزدیک اتمام حجم، بدون مصرف، غیرفعال‌ها، بی‌فعالیت‌ها\n"
        "• روی هر کاربر بزن: فعال/غیرفعال، ریست مصرف، افزودن حجم، تمدید، لینک ساب، ریوک ساب، یادداشت، حذف\n"
        "• ساخت کاربر، جستجو، عملیات گروهی، نودها، ادمین‌ها\n"
        "• 🗑 سطل زباله: کاربران حذف‌شده با ربات تا ۷ روز قابل بازگردانی‌اند\n"
        "• 💾 بکاپ: بکاپ کلی پنل (ZIP) و خروجی کاربران\n"
        "• 💰 حجم کلی فروخته‌شده در صفحه‌ی هر پنل و گزارش کلی\n"
        "• 📈 نمودار مصرف: روند مصرف در بازه‌های ۲۴ساعت/۷/۳۰/۹۰ روز، پرمصرف‌ها، وضعیت، انقضا، فعالیت، فروش، سلامت؛ "
        "خروجی داشبورد کامل (یک عکس) یا گالری نمودارها\n"
        "• 🔀 مهاجرت: با لینک سابسکریپشن (تکی/گروهی) یا پنل به پنل (انتخابی)، با تاریخچه و بازگردانی\n"
        "• هشدار خودکار: هر ۳۰ دقیقه کاربران نزدیک اتمام/انقضا و قطعی پنل را اطلاع می‌دهد\n\n"
        "آنلاین = فعالیت در ۳ دقیقه اخیر. لغو هر مرحله: /cancel")


def main_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(BM("📋 پنل‌های من", callback_data="pl"), BM("🔀 مهاجرت", callback_data="MG"))
    kb.add(BM("📊 گزارش کلی", callback_data="ov"), BM("🌍 زبان", callback_data="lg"))
    kb.add(BM("📖 راهنما", callback_data="help"))
    return kb


def show_panels(chat, msg=None):
    if not load():
        return ask_url(chat)
    kb = types.InlineKeyboardMarkup(row_width=1)
    for p in load():
        kb.add(B(f"🌐 {host(p)} ({p['username']})", callback_data=f"p:{p['id']}"))
    kb.add(B("➕ افزودن پنل", callback_data="ao"))
    kb.add(B("🏠 منو", callback_data="m"))
    text = "📋 <b>پنل‌های ثبت‌شده</b>\nیکی را انتخاب کن یا پنل جدید اضافه کن:"
    if msg:
        edit(msg, text, kb)
    else:
        bot.send_message(chat, text, reply_markup=kb)


def panel_home(p):
    xs = X(p, True)
    c = {k: sum(1 for x in xs if FILT[k][1](x)) for k in FILT}
    st = lambda s: sum(1 for x in xs if x["st"] == s)
    sold, left, unl = sold_stats(xs)
    out = [f"🌐 <b>{esc(host(p))}</b>  👤 <code>{esc(p['username'])}</code>\n",
           "<b>📊 آمار</b>",
           f"👥 کل: <b>{len(xs)}</b> | 🟢 فعال: <b>{st('active')}</b> | 🚫 غیرفعال: <b>{st('disabled')}</b>",
           f"⏳ منقضی: <b>{c['expired']}</b> | 📦 حجم‌تمام: <b>{c['limited']}</b> | ⏸ در انتظار: <b>{st('on_hold')}</b>",
           f"🟢 آنلاین الان: <b>{c['online']}</b>",
           f"📈 مجموع مصرف: <b>{fmt_bytes(sum(x['used'] for x in xs))}</b>",
           f"💰 حجم کلی فروخته‌شده: <b>{fmt_bytes(sold)}</b>",
           f"🧮 مانده از فروخته‌شده: <b>{fmt_bytes(left)}</b> | ♾ نامحدود: <b>{unl}</b> کاربر"]
    admin = first_ok(p, ["/api/admin", "/api/admin/current"])
    if isinstance(admin, dict):
        out.append("\n<b>👑 ادمین</b>\n" + dump(admin, 6))
    system = first_ok(p, ["/api/system"])
    if isinstance(system, dict):
        out.append("\n<b>🖥 سیستم</b>\n" + dump(system, 10))
    return "\n".join(out), c


def panel_kb(p, c):
    pid = p["id"]
    kb = types.InlineKeyboardMarkup(row_width=2)

    def b(label, kind):
        return B(f"{label} ({c[kind]})", callback_data=f"L:{pid}:{kind}:0")

    kb.add(b("🟢 آنلاین", "online"), b("👥 همه", "all"))
    kb.add(b("⏳ منقضی", "expired"), b("📦 حجم‌تمام", "limited"))
    kb.add(b("🔥 پرمصرف", "top"), b("⏰ نزدیک انقضا", "soon"))
    kb.add(b("📉 نزدیک اتمام", "near"), b("💤 بدون مصرف", "unused"))
    kb.add(b("🚫 غیرفعال", "disabled"), b("🕸 بی‌فعالیت", "idle"))
    kb.add(B("🔍 جستجو", callback_data=f"SR:{pid}"), B("➕ ساخت کاربر", callback_data=f"CU:{pid}"))
    kb.add(B("🛠 عملیات گروهی", callback_data=f"BK:{pid}"), B("🛰 نودها", callback_data=f"ND:{pid}"))
    kb.add(B("👑 ادمین‌ها", callback_data=f"AD:{pid}"), B("💾 بکاپ", callback_data=f"BM:{pid}"))
    kb.add(B("🗂 گروه‌ها", callback_data=f"GL:{pid}"), B(f"🗑 سطل زباله ({len(trash_list(pid))})", callback_data=f"TR:{pid}"))
    kb.add(B("📈 نمودار مصرف و گزارش تصویری", callback_data=f"CH:{pid}"))
    kb.add(B("🔄 بروزرسانی", callback_data=f"p:{pid}"), B("🗑 حذف پنل", callback_data=f"PD:{pid}"))
    kb.add(B("🔙 پنل‌ها", callback_data="pl"))
    return kb


def sub_link(p, u):
    s = u.get("subscription_url") or ""
    if s.startswith("/"):
        s = p["url"] + s
    return s


def user_view(p, name):
    u = u_get(p, name)
    x = uinfo(u)
    lim = fmt_bytes(x["lim"]) if x["lim"] else "∞"
    rem = fmt_bytes(max(x["lim"] - x["used"], 0)) if x["lim"] else "∞"
    if x["exp"]:
        d = (x["exp"] - time.time()) / 86400
        exp = f"{fdate(x['exp'])[:10]} ({int(d)} روز)" if d >= 0 else f"{fdate(x['exp'])[:10]} (منقضی)"
    else:
        exp = "نامحدود"
    seen = "🟢 آنلاین" if x["online"] else (fdate(x["on"]) if x["on"] else "هرگز")
    out = [f"{SE.get(x['st'], '▫️')} <b>{esc(x['name'])}</b>",
           f"وضعیت: <code>{esc(x['st'])}</code>",
           f"📊 مصرف: <b>{fmt_bytes(x['used'])}</b> / {lim}  (مانده: {rem})",
           f"📅 انقضا: {exp}",
           f"👁 آخرین اتصال: {seen}"]
    grp = u.get("group_names")
    if not grp and u.get("group_ids"):
        try:
            gm = {g.get("id"): g.get("name") for g in groups_cached(p)}
            grp = [gm.get(i, i) for i in u["group_ids"]]
        except Exception:
            grp = u["group_ids"]
    if grp:
        out.append(f"🗂 گروه‌ها: <code>{esc('، '.join(map(str, grp)) if isinstance(grp, list) else grp)}</code>")
    if u.get("note"):
        out.append(f"📝 {esc(u['note'])}")
    pid = p["id"]
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(B("🚫 غیرفعال" if x["st"] != "disabled" else "✅ فعال‌سازی", callback_data=f"T:{pid}:{name}"),
           B("♻️ ریست مصرف", callback_data=f"Zr:{pid}:{name}"))
    kb.add(B("➕ افزودن حجم", callback_data=f"AV:{pid}:{name}"),
           B("📅 تمدید", callback_data=f"ED:{pid}:{name}"))
    kb.add(B("🔗 لینک ساب", callback_data=f"SL:{pid}:{name}"),
           B("🔄 ریوک ساب", callback_data=f"Zv:{pid}:{name}"))
    kb.add(B("📝 یادداشت", callback_data=f"NT:{pid}:{name}"),
           B("🗑 حذف", callback_data=f"Zd:{pid}:{name}"))
    kb.add(B("🗂 تغییر گروه", callback_data=f"GU:{pid}:{name}"))
    kb.add(B("🔙 برگشت", callback_data=f"LB:{pid}"))
    return "\n".join(out), kb


def overview(msg):
    edit(msg, "⏳ در حال جمع‌آوری گزارش همه پنل‌ها...")
    out = ["📊 <b>گزارش کلی همه پنل‌ها</b>\n"]
    tot = {"u": 0, "on": 0, "used": 0, "sold": 0}
    for p in load():
        try:
            xs = X(p, True)
            on = sum(1 for x in xs if x["online"])
            used = sum(x["used"] for x in xs)
            exp = sum(1 for x in xs if x["expired"])
            act = sum(1 for x in xs if x["st"] == "active")
            tot["u"] += len(xs)
            tot["on"] += on
            tot["used"] += used
            tot["sold"] += sold_stats(xs)[0]
            out.append(f"🌐 <b>{esc(host(p))}</b>\n   👥 {len(xs)} | 🟢 فعال {act} | 🔵 آنلاین {on} | ⏳ منقضی {exp} | 📈 {fmt_bytes(used)} | 💰 فروخته {fmt_bytes(sold_stats(xs)[0])}")
        except Exception as e:
            out.append(f"🌐 <b>{esc(host(p))}</b>\n   ❌ {esc(e)[:120]}")
    out.append(f"\n<b>جمع کل</b>: 👥 {tot['u']} | 🔵 آنلاین {tot['on']} | 📈 {fmt_bytes(tot['used'])} | 💰 فروخته {fmt_bytes(tot['sold'])}")
    edit(msg, "\n".join(out), back_kb("m", "🏠 منو"))


# ================= flows (text input) =================
def prompt(chat, text, extra=None):
    kb = types.InlineKeyboardMarkup()
    if extra:
        kb.add(extra)
    kb.add(B("❌ لغو", callback_data="m"))
    return bot.send_message(chat, text, reply_markup=kb)


def ask_url(chat, after=None):
    ST[chat] = {"step": "url", "after": after}
    prompt(chat, "🌐 <b>آدرس پنل</b> را بفرست\nمثال: <code>https://panel.example.com:8000</code>")


def ask_gb(chat):
    ST[chat]["step"] = "c_gb"
    prompt(chat, "📦 <b>حجم</b> را به گیگابایت بفرست (۰ = نامحدود):")


def ask_groups(chat):
    st = ST[chat]
    st["step"] = "c_group"
    grp_start(chat, st["pid"], "create")


def do_create(chat, gids):
    st = ST.pop(chat, None)
    if not st:
        return
    p = get_panel(st["pid"])
    body = {"username": st["username"], "status": "active"}
    if st["gb"]:
        body["data_limit"] = int(st["gb"] * GB)
    if st["days"]:
        body["expire"] = int(time.time() + st["days"] * 86400)
    if gids:
        body["group_ids"] = gids
    try:
        req(p, "POST", "/api/user", body=body)
        CACHE.pop(p["id"], None)
    except Exception as e:
        bot.send_message(chat, f"❌ ساخت کاربر ناموفق:\n<code>{esc(e)}</code>", reply_markup=back_kb(f"p:{p['id']}", "🔙 پنل"))
        return
    text, kb = user_view(p, st["username"])
    bot.send_message(chat, "✅ کاربر ساخته شد\n\n" + text, reply_markup=kb)
    try:
        link = sub_link(p, u_get(p, st["username"]))
        if link:
            bot.send_message(chat, f"🔗 لینک ساب:\n<code>{esc(link)}</code>")
    except Exception:
        pass


@bot.message_handler(commands=["start"], func=lambda m: m.from_user.id == OWNER)
def start(m):
    ST.pop(m.chat.id, None)
    try:
        t = bot.send_message(m.chat.id, "🔄", reply_markup=types.ReplyKeyboardRemove())
        bot.delete_message(m.chat.id, t.message_id)
    except Exception:
        pass
    bot.send_message(m.chat.id, MENU_TXT, reply_markup=main_kb())


@bot.message_handler(content_types=["text"], func=lambda m: m.from_user.id == OWNER)
def on_text(m):
    chat = m.chat.id
    t = (m.text or "").strip()
    st = ST.get(chat)
    if t == "/cancel" or not st:
        ST.pop(chat, None)
        return bot.send_message(chat, MENU_TXT, reply_markup=main_kb())
    step = st["step"]
    try:
        if step == "url":
            st["url"] = norm_url(t)
            st["step"] = "user"
            prompt(chat, "👤 <b>یوزرنیم</b> ادمین را بفرست:")
        elif step == "user":
            st["username"] = t
            st["step"] = "pw"
            prompt(chat, "🔑 <b>پسورد</b> را بفرست (پیامت بعد از دریافت پاک می‌شود):")
        elif step == "pw":
            try:
                bot.delete_message(chat, m.message_id)
            except Exception:
                pass
            ST.pop(chat, None)
            p = {"id": uuid.uuid4().hex[:8], "url": st["url"], "username": st["username"], "password": t}
            w = bot.send_message(chat, "⏳ در حال اتصال به پنل...")
            try:
                login(p)
            except Exception as e:
                return edit(w, f"❌ اتصال/ورود ناموفق:\n<code>{esc(e)}</code>", back_kb("pl", "🔙 پنل‌ها"))
            ps = load()
            ps.append(p)
            save(ps)
            if st.get("after") == "mig":
                edit(w, "✅ پنل ذخیره شد.")
                return mig_after_add(chat, p)
            edit(w, "✅ ورود موفق. در حال دریافت اطلاعات...")
            text, c = panel_home(p)
            edit(w, text, panel_kb(p, c))
        elif step == "search":
            ST.pop(chat, None)
            p = get_panel(st["pid"])
            d = req(p, "GET", "/api/users", {"search": t, "limit": 30})
            xs = [uinfo(u) for u in (d.get("users", []) if isinstance(d, dict) else d)]
            kb = users_kb(p["id"], xs)
            kb.add(B("🔍 جستجوی جدید", callback_data=f"SR:{p['id']}"), B("🔙 پنل", callback_data=f"p:{p['id']}"))
            bot.send_message(chat, f"🔍 نتیجه «{esc(t)}»: {len(xs)} کاربر\n\n" +
                             "\n".join(line(i, x, "all") for i, x in enumerate(xs, 1)), reply_markup=kb)
        elif step == "mig_links":
            ST.pop(chat, None)
            mig_analyze_links(chat, t)
        elif step == "mig_edit":
            ST.pop(chat, None)
            mig_apply_edit(chat, st["field"], t)
        elif step == "g_manual":
            G = GP.get(chat)
            prev = G.pop("prev_step", None) if G else None
            if prev:
                st["step"] = prev
            else:
                ST.pop(chat, None)
            if not G:
                return bot.send_message(chat, MENU_TXT, reply_markup=main_kb())
            ids = [int(x) for x in re.findall(r"\d+", t.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))]
            if not ids:
                return bot.send_message(chat, "⚠️ عدد معتبر بفرست.")
            have = {g.get("id") for g in G["groups"]}
            for gid in ids:
                if gid not in have:
                    G["groups"].append({"id": gid, "name": f"گروه #{gid}", "inbound_tags": [], "derived": True})
                if gid not in G["sel"]:
                    G["sel"].append(gid)
            w = bot.send_message(chat, "⏳")
            grp_custom(chat, w)
        elif step == "c_user":
            st["username"] = t.replace(" ", "_")
            ask_gb(chat)
        elif step == "c_gb":
            st["gb"] = num(t)
            st["step"] = "c_days"
            prompt(chat, "📅 <b>مدت</b> را به روز بفرست (۰ = نامحدود):")
        elif step == "c_days":
            st["days"] = num(t)
            ask_groups(chat)
        elif step in ("cust_av", "cust_ed", "note"):
            ST.pop(chat, None)
            p = get_panel(st["pid"])
            name = st["user"]
            if step == "note":
                u_modify(p, name, {"note": t})
            else:
                x = uinfo(u_get(p, name))
                u_modify(p, name, body_volume(x, num(t)) if step == "cust_av" else body_extend(x, num(t)))
            text, kb = user_view(p, name)
            bot.send_message(chat, "✅ انجام شد\n\n" + text, reply_markup=kb)
    except ValueError:
        bot.send_message(chat, "⚠️ عدد معتبر بفرست.")
    except Exception as e:
        ST.pop(chat, None)
        bot.send_message(chat, f"⚠️ خطا: <code>{esc(e)}</code>", reply_markup=main_kb())


# ================= charts / management reports =================
HISTF = os.path.join(DATA_DIR, "usage_history.json")
plock = threading.Lock()
CHS = {}
try:
    import matplotlib
    from matplotlib.figure import Figure
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    from matplotlib.patches import Rectangle
    from matplotlib import font_manager
    MPL = True
except Exception:
    MPL = False
try:
    import arabic_reshaper
    FA = cfg.get("chart_lang", "en") == "fa"
except Exception:
    FA = False

if MPL:
    _fn = "DejaVu Sans"
    for _f in ("Vazirmatn.ttf", "Vazirmatn-Bold.ttf"):
        _fp = next((p for p in (os.path.join(DATA_DIR, _f), os.path.join(BASE, "assets", _f), os.path.join(BASE, _f)) if os.path.exists(p)), "")
        if _fp:
            try:
                font_manager.fontManager.addfont(_fp)
                _fn = font_manager.FontProperties(fname=_fp).get_name()
            except Exception:
                pass
    matplotlib.rcParams["font.family"] = [_fn, "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False

C = {"bg": "#0a1020", "card": "#121a2f", "line": "#1e2a47", "txt": "#e9eefb", "mut": "#8996b5",
     "cy": "#22d3ee", "vi": "#a78bfa", "gr": "#34d399", "am": "#fbbf24", "rd": "#f87171",
     "bl": "#60a5fa", "pk": "#f472b6", "or": "#fb923c"}
PAL = [C["cy"], C["vi"], C["gr"], C["am"], C["bl"], C["pk"], C["or"], C["rd"]]

CH_ORDER = ["trend", "top", "newusers", "status", "dist", "expiry", "activity", "sold", "health", "groups"]
CH_WIDE = {"trend"}
CH_NAMES = {"trend": "📈 روند مصرف", "top": "🏆 پرمصرف‌ترین‌ها", "newusers": "🆕 کاربران جدید",
            "status": "🍩 وضعیت کاربران", "dist": "📊 توزیع مصرف حجم", "expiry": "⏳ پیش‌بینی انقضا",
            "activity": "🟢 فعالیت کاربران", "sold": "💰 فروش و مانده", "health": "🩺 سلامت و هشدارها",
            "groups": "🗂 توزیع گروه‌ها"}
CH_RANGES = [(1, "۲۴ ساعت"), (7, "۷ روز"), (30, "۳۰ روز"), (90, "۹۰ روز")]
RANGE_L = {1: ("۲۴ ساعت اخیر", "Last 24 hours"), 7: ("۷ روز اخیر", "Last 7 days"),
           30: ("۳۰ روز اخیر", "Last 30 days"), 90: ("۹۰ روز اخیر", "Last 90 days")}

_AR = re.compile(r"[\u0600-\u06FF]")
_LAT = re.compile(r"[A-Za-z0-9\u06F0-\u06F9%][A-Za-z0-9\u06F0-\u06F9 .,:/%@#_\-]*[A-Za-z0-9\u06F0-\u06F9%]"
                  r"|[A-Za-z0-9\u06F0-\u06F9%]")
_BR = str.maketrans("()[]", ")(][")


def P(s):
    """متن فارسی را برای نمایش در نمودار (راست‌به‌چپ) آماده می‌کند."""
    s = str(s)
    if not FA or not _AR.search(s):
        return s
    r = arabic_reshaper.reshape(s)[::-1].translate(_BR)
    return _LAT.sub(lambda m: m.group(0)[::-1], r)


def T(fa, en):
    return P(fa) if FA else en


def short(v):
    for u, d in (("T", 1024 ** 4), ("G", 1024 ** 3), ("M", 1024 ** 2), ("K", 1024)):
        if abs(v) >= d:
            return f"{v / d:.1f}".rstrip("0").rstrip(".") + u
    return str(int(v))


def iso(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- history (snapshots) ----------
def snapshot(p, xs):
    with tlock:
        H = _read(HISTF, {})
        h = H.setdefault(p["id"], {"tot": [], "days": {}})
        now = time.time()
        if not h["tot"] or now - h["tot"][-1][0] >= 20 * 60:
            h["tot"].append([int(now), int(sum(x["used"] for x in xs))])
        h["tot"] = [r for r in h["tot"] if r[0] >= now - 100 * 86400]
        today = datetime.date.today().isoformat()
        if today not in h["days"]:
            h["days"][today] = {x["name"]: int(x["used"]) for x in xs}
        h["days"] = {k: h["days"][k] for k in sorted(h["days"])[-100:]}
        with lock:
            json.dump(H, open(HISTF, "w", encoding="utf-8"), separators=(",", ":"))


def snapshot_loop():
    time.sleep(25)
    while True:
        try:
            for p in load():
                try:
                    snapshot(p, X(p, True))
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(1800)


# ---------- data ----------
def parse_series(d):
    pts = {}

    def tkey(o):
        for k in ("period_start", "time", "date", "timestamp", "start"):
            if k in o:
                t = parse_time(o[k])
                if t is not None:
                    return t

    def val(o):
        for k in ("total_traffic", "traffic", "used_traffic", "usage", "value", "total"):
            if isinstance(o.get(k), (int, float)) and not isinstance(o.get(k), bool):
                return o[k]
        if isinstance(o.get("uplink"), (int, float)) or isinstance(o.get("downlink"), (int, float)):
            return (o.get("uplink") or 0) + (o.get("downlink") or 0)

    def walk(x):
        if isinstance(x, list):
            for i in x:
                if isinstance(i, dict):
                    t, v = tkey(i), val(i)
                    if t is not None and v is not None:
                        pts[t] = pts.get(t, 0) + v
                        continue
                walk(i)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)

    walk(d)
    return sorted(pts.items())


def usage_series(p, days):
    now = time.time()
    nb, step = (24, 3600) if days == 1 else (days, 86400)
    start = now - nb * step
    fmt = "%H:00" if days == 1 else "%m/%d"
    labels = [datetime.datetime.fromtimestamp(start + (k + 1) * step).strftime(fmt) for k in range(nb)]
    params = {"start": iso(start), "end": iso(now), "period": "hour" if days == 1 else "day"}
    for path in ("/api/users/usage", "/api/nodes/usage", "/api/node/usage", "/api/system/usage"):
        try:
            d = req(p, "GET", path, params)
        except Exception:
            continue
        vals = [0] * nb
        for t, v in parse_series(d):
            i = int((t - start) // step)
            if 0 <= i < nb:
                vals[i] += v
        if sum(vals) > 0:
            return {"labels": labels, "vals": vals, "src": "panel"}
    tot = (_read(HISTF, {}).get(p["id"]) or {}).get("tot") or []
    if len(tot) >= 2:
        bs = [start + k * step for k in range(nb + 1)]

        def at(t):
            v = None
            for ts, val in tot:
                if ts <= t:
                    v = val
                else:
                    break
            return v

        vals = []
        for k in range(nb):
            a, b = at(bs[k]), at(bs[k + 1])
            vals.append(None if a is None or b is None else max(b - a, 0))
        if any(v is not None for v in vals):
            return {"labels": labels, "vals": vals, "src": "bot", "since": tot[0][0]}
    return None


def top_users(p, days, xs):
    now = time.time()
    try:
        d = req(p, "GET", "/api/users/usage", {"start": iso(now - days * 86400), "end": iso(now)})
        lst = d.get("usages") if isinstance(d, dict) else d
        agg = {}
        for it in lst or []:
            if isinstance(it, dict) and it.get("username") and isinstance(it.get("used_traffic"), (int, float)):
                agg[it["username"]] = agg.get(it["username"], 0) + it["used_traffic"]
        if agg and sum(agg.values()) > 0:
            return {"rows": sorted(agg.items(), key=lambda r: -r[1])[:10], "src": "range"}
    except Exception:
        pass
    h = _read(HISTF, {}).get(p["id"]) or {}
    dd = h.get("days") or {}
    if dd:
        keys = sorted(dd)
        target = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        base_k = max([k for k in keys if k <= target], default=keys[0])
        base = dd[base_k]
        rows = [(x["name"], max(x["used"] - base.get(x["name"], 0), 0)) for x in xs]
        rows = sorted([r for r in rows if r[1] > 0], key=lambda r: -r[1])[:10]
        if rows:
            return {"rows": rows, "src": "range" if base_k <= target else "since:" + base_k}
    rows = sorted([(x["name"], x["used"]) for x in xs if x["used"] > 0], key=lambda r: -r[1])[:10]
    return {"rows": rows, "src": "alltime"}


def group_counts(p, xs):
    try:
        rows, _ = fetch_groups(p, derive=True)
    except Exception:
        rows = []
    names = {g.get("id"): g.get("name") for g in rows}
    cnt, nog, has = {}, 0, False
    for x in xs:
        ids = x["raw"].get("group_ids") or []
        if ids:
            has = True
        else:
            nog += 1
        for i in ids:
            cnt[i] = cnt.get(i, 0) + 1
    out = sorted([(str(names.get(i, f"#{i}")), c) for i, c in cnt.items()], key=lambda r: -r[1])
    if nog and has:
        out.append((None, nog))
    return out


def chart_data(p, days):
    xs = X(p, True)
    try:
        snapshot(p, xs)
    except Exception:
        pass
    sold, left, unl = sold_stats(xs)
    D = {"p": p, "days": days, "xs": xs, "now": time.time(), "n": len(xs),
         "used": sum(x["used"] for x in xs), "sold": sold, "left": left, "unl": unl,
         "lim_used": sum(min(x["used"], x["lim"]) for x in xs if x["lim"]),
         "unl_used": sum(x["used"] for x in xs if not x["lim"]),
         "online": sum(1 for x in xs if x["online"]),
         "active": sum(1 for x in xs if x["st"] == "active" and not x["expired"]),
         "expired": sum(1 for x in xs if x["expired"]),
         "limited": sum(1 for x in xs if FILT["limited"][1](x))}
    for k, fn in (("series", lambda: usage_series(p, days)), ("top", lambda: top_users(p, days, xs)),
                  ("groups", lambda: group_counts(p, xs))):
        try:
            D[k] = fn()
        except Exception:
            D[k] = None
    if not D["top"]:
        D["top"] = {"rows": [], "src": "alltime"}
    D["groups"] = D["groups"] or []
    cut = D["now"] - days * 86400
    D["new"] = sum(1 for x in xs if (parse_time(x["raw"].get("created_at")) or 0) >= cut)
    D["range_total"] = sum(v for v in D["series"]["vals"] if v) if D["series"] else None
    return D


def health_items(D):
    xs, now = D["xs"], D["now"]

    def created(x):
        return parse_time(x["raw"].get("created_at"))

    return [
        ("نزدیک اتمام حجم 80%", "Near data limit 80%", sum(1 for x in xs if FILT["near"][1](x)), C["am"]),
        ("انقضا تا 7 روز آینده", "Expiring in 7 days", sum(1 for x in xs if FILT["soon"][1](x)), C["or"]),
        ("منقضی در 30 روز اخیر", "Expired last 30 days",
         sum(1 for x in xs if x["expired"] and x["exp"] and now - x["exp"] <= 30 * 86400), C["rd"]),
        ("حجم تمام‌شده", "Data used up", D["limited"], C["pk"]),
        ("بدون مصرف (قدیمی‌تر از 7 روز)", "Never used (7d+)",
         sum(1 for x in xs if x["used"] == 0 and x["st"] != "on_hold"
             and (created(x) is None or now - created(x) > 7 * 86400)), C["bl"]),
        ("بی‌فعالیت 30 روز+", "Inactive 30d+", sum(1 for x in xs if FILT["idle"][1](x)), C["vi"]),
    ]


# ---------- drawing helpers ----------
def style(ax, fa, en, grid="y"):
    ax.set_facecolor(C["card"])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=C["mut"], labelsize=9, length=0)
    ax.set_title(T(fa, en), color=C["txt"], fontsize=14, pad=14, fontweight="bold")
    if grid:
        ax.grid(axis=grid, color=C["line"], linewidth=0.8)
        ax.set_axisbelow(True)


def empty(ax, *lines):
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for i, t in enumerate(lines):
        ax.text(0.5, 0.56 - i * 0.12, t, ha="center", va="center", color=C["mut"],
                fontsize=11, transform=ax.transAxes)


def vbars(ax, labels, vals, colors, fs=9):
    ix = list(range(len(vals)))
    ax.bar(ix, vals, color=colors, width=0.62)
    ax.set_xticks(ix)
    ax.set_xticklabels(labels, color=C["txt"], fontsize=fs)
    top = max(vals) if vals else 0
    for i, v in enumerate(vals):
        ax.text(i, v + top * 0.02, str(v), ha="center", va="bottom", color=C["txt"], fontsize=10, fontweight="bold")
    ax.set_ylim(0, top * 1.2 if top else 1)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))


def hbars(ax, labels, vals, colors, texts=None):
    n = len(vals)
    ys = list(range(n))[::-1]
    ax.barh(ys, vals, color=colors, height=0.58)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, color=C["txt"], fontsize=10)
    mx = max(vals) if vals else 0
    for y, v, t in zip(ys, vals, texts or [str(v) for v in vals]):
        ax.text(v + mx * 0.015, y, t, va="center", ha="left", color=C["txt"], fontsize=10, fontweight="bold")
    ax.set_xlim(0, mx * 1.32 if mx else 1)
    ax.set_xticks([])
    ax.grid(False)


def sparse_ticks(ax, labels, n=12):
    st = max(1, len(labels) // n)
    ax.set_xticks(list(range(0, len(labels), st)))
    ax.set_xticklabels([labels[i] for i in range(0, len(labels), st)], color=C["mut"], fontsize=9)
    ax.set_xlim(-0.8, len(labels) - 0.2)


# ---------- charts ----------
def draw_trend(ax, D):
    style(ax, "روند مصرف ترافیک", "Traffic usage trend")
    s = D["series"]
    if not s:
        return empty(ax, T("هنوز تاریخچه‌ای ثبت نشده", "No usage history yet"),
                     T("ربات از الان هر 30 دقیقه مصرف را ثبت می‌کند؛ چند ساعت بعد دوباره بزن",
                       "The bot records usage every 30 min. Check again later."))
    vals = s["vals"]
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    mx = max(v for _, v in pts)
    ax.bar([i for i, _ in pts], [v for _, v in pts], width=0.72,
           color=[C["am"] if (v == mx and mx > 0) else C["cy"] for _, v in pts])
    if len(pts) >= 4:
        w = 3 if len(vals) <= 14 else 7
        avg = []
        for j in range(len(pts)):
            seg = [vv for _, vv in pts[max(0, j - w + 1):j + 1]]
            avg.append(sum(seg) / len(seg))
        ax.plot([i for i, _ in pts], avg, color=C["vi"], linewidth=2.4, label=T("میانگین متحرک", "Moving average"))
        ax.legend(loc="upper right", frameon=False, labelcolor=C["mut"], fontsize=9)
    tot = sum(v for _, v in pts)
    ax.set_ylim(0, mx * 1.35 if mx else 1)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: short(v)))
    sparse_ticks(ax, s["labels"])
    ax.text(0.012, 0.95, T(f"جمع: {fmt_bytes(tot)}     میانگین: {fmt_bytes(tot / len(pts))}     اوج: {fmt_bytes(mx)}",
                           f"Total: {fmt_bytes(tot)}    Avg: {fmt_bytes(tot / len(pts))}    Peak: {fmt_bytes(mx)}"),
            transform=ax.transAxes, va="top", ha="left", color=C["txt"], fontsize=11, fontweight="bold")
    src = (T("منبع: آمار پنل", "Source: panel stats") if s["src"] == "panel"
           else T("منبع: ثبت ربات از " + time.strftime("%Y-%m-%d", time.localtime(s["since"])),
                  "Source: bot history since " + time.strftime("%Y-%m-%d", time.localtime(s["since"]))))
    ax.text(0.99, 0.02, src, transform=ax.transAxes, ha="right", va="bottom", color=C["mut"], fontsize=8)


def draw_top(ax, D):
    style(ax, "پرمصرف‌ترین کاربران", "Top consumers", grid=None)
    t = D["top"]
    rows = [r for r in t["rows"] if r[1] > 0][:10]
    if not rows:
        return empty(ax, T("مصرفی ثبت نشده", "No usage recorded"))
    names = [P(n[:20]) for n, _ in rows]
    vals = [v for _, v in rows]
    hbars(ax, names, vals, [PAL[i % len(PAL)] for i in range(len(rows))], [fmt_bytes(v) for v in vals])
    if t["src"] == "range":
        note = T(f"مصرف در {RANGE_L[D['days']][0]}", f"Usage in {RANGE_L[D['days']][1].lower()}")
    elif t["src"].startswith("since:"):
        note = T("مصرف از " + t["src"][6:] + " (شروع ثبت ربات)", "Usage since " + t["src"][6:] + " (bot tracking)")
    else:
        note = T("مصرف کل از ابتدا", "All-time usage")
    ax.text(0.99, 0.01, note, transform=ax.transAxes, ha="right", va="bottom", color=C["mut"], fontsize=8)


def draw_newusers(ax, D):
    style(ax, "کاربران جدید", "New users")
    n = max(D["days"], 7)
    today = datetime.date.fromtimestamp(D["now"])
    dates = [today - datetime.timedelta(days=n - 1 - i) for i in range(n)]
    cnt = {d: 0 for d in dates}
    seen = 0
    for x in D["xs"]:
        t = parse_time(x["raw"].get("created_at"))
        if t:
            seen += 1
            d = datetime.date.fromtimestamp(t)
            if d in cnt:
                cnt[d] += 1
    if not seen:
        return empty(ax, T("تاریخ ساخت کاربران در پنل موجود نیست", "No creation dates available"))
    vals = [cnt[d] for d in dates]
    ax.bar(range(n), vals, color=C["gr"], width=0.7)
    sparse_ticks(ax, [d.strftime("%m/%d") for d in dates], 10)
    mx = max(vals)
    ax.set_ylim(0, mx * 1.35 if mx else 1)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    tot = sum(vals)
    ax.text(0.015, 0.95, T(f"جمع: {tot} کاربر     میانگین روزانه: {tot / n:.1f}",
                           f"Total: {tot}    Daily avg: {tot / n:.1f}"),
            transform=ax.transAxes, va="top", ha="left", color=C["txt"], fontsize=11, fontweight="bold")


def draw_status(ax, D):
    style(ax, "وضعیت کاربران", "User status", grid=None)
    order = [("active", "فعال", "Active", C["gr"]), ("on_hold", "در انتظار", "On hold", C["bl"]),
             ("limited", "حجم‌تمام‌شده", "Data used up", C["am"]), ("expired", "منقضی", "Expired", C["rd"]),
             ("disabled", "غیرفعال", "Disabled", C["mut"])]
    cnt = {}
    for x in D["xs"]:
        k = "expired" if x["expired"] else x["st"]
        cnt[k] = cnt.get(k, 0) + 1
    items = [(fa, en, c, cnt[k]) for k, fa, en, c in order if cnt.get(k)]
    if not items:
        return empty(ax, T("کاربری نیست", "No users"))
    n = sum(i[3] for i in items)
    ax.pie([i[3] for i in items], colors=[i[2] for i in items], startangle=90, counterclock=False,
           center=(-0.55, 0), radius=1, wedgeprops=dict(width=0.4, edgecolor=C["card"], linewidth=2))
    ax.text(-0.55, 0.07, str(D["n"]), ha="center", va="center", color=C["txt"], fontsize=26, fontweight="bold")
    ax.text(-0.55, -0.25, T("کاربر", "users"), ha="center", va="center", color=C["mut"], fontsize=11)
    ax.set_xlim(-1.75, 2.1)
    ax.set_ylim(-1.3, 1.3)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xticks([])
    ax.set_yticks([])
    for i, (fa, en, c, v) in enumerate(items):
        y = (len(items) - 1) / 2 * 0.42 - i * 0.42
        ax.scatter([0.75], [y], marker="s", s=110, color=c)
        ax.text(0.92, y, T(f"{fa}   {v}  ({v * 100 / n:.0f}%)", f"{en}   {v}  ({v * 100 / n:.0f}%)"),
                ha="left", va="center", color=C["txt"], fontsize=11)


def draw_dist(ax, D):
    style(ax, "توزیع مصرف حجم کاربران", "Data usage distribution")
    cats = [0] * 7
    for x in D["xs"]:
        if not x["lim"]:
            cats[6] += 1
        elif x["used"] == 0:
            cats[0] += 1
        else:
            r = x["ratio"]
            cats[1 if r < .25 else 2 if r < .5 else 3 if r < .8 else 4 if r < 1 else 5] += 1
    labs = [T("بدون مصرف", "Unused"), T("زیر 25%", "<25%"), T("25 تا 50%", "25-50%"), T("50 تا 80%", "50-80%"),
            T("80 تا 100%", "80-100%"), T("تمام‌شده", "Depleted"), T("نامحدود", "Unlimited")]
    vbars(ax, labs, cats, [C["mut"], C["gr"], "#86efac", C["am"], C["or"], C["rd"], C["vi"]], fs=8.5)


def draw_expiry(ax, D):
    style(ax, "پیش‌بینی انقضا و تمدید", "Expiry & renewal pipeline")
    now = D["now"]
    cats = [0] * 8
    old = 0
    for x in D["xs"]:
        e = x["exp"]
        if not e:
            cats[7] += 1
            continue
        d = (e - now) / 86400
        if x["expired"] or d < 0:
            if -d <= 30:
                cats[0] += 1
            else:
                old += 1
            continue
        cats[1 if d <= 3 else 2 if d <= 7 else 3 if d <= 14 else 4 if d <= 30 else 5 if d <= 60 else 6] += 1
    labs = [T("منقضی 30روز", "Expired 30d"), T("0 تا 3 روز", "0-3d"), T("4 تا 7", "4-7d"), T("8 تا 14", "8-14d"),
            T("15 تا 30", "15-30d"), T("31 تا 60", "31-60d"), T("60+", "60d+"), T("بدون انقضا", "No expiry")]
    vbars(ax, labs, cats, [C["rd"], C["or"], C["am"], "#fde047", "#86efac", C["gr"], C["cy"], C["mut"]], fs=8)
    if old:
        ax.text(0.99, 0.95, T(f"منقضی قدیمی‌تر از 30 روز: {old}", f"Expired 30d+ ago: {old}"),
                transform=ax.transAxes, ha="right", va="top", color=C["mut"], fontsize=9)


def draw_activity(ax, D):
    style(ax, "فعالیت کاربران", "User activity", grid=None)
    xs, now, n = D["xs"], D["now"], max(D["n"], 1)
    th = [("آنلاین الان", "Online now", 180, C["gr"]), ("یک ساعت اخیر", "Last hour", 3600, C["cy"]),
          ("24 ساعت اخیر", "Last 24h", 86400, C["bl"]), ("7 روز اخیر", "Last 7 days", 7 * 86400, C["vi"]),
          ("30 روز اخیر", "Last 30 days", 30 * 86400, C["pk"])]
    labs, vals, cols = [], [], []
    for fa, en, s, c in th:
        labs.append(T(fa, en))
        vals.append(sum(1 for x in xs if x["on"] and now - x["on"] <= s))
        cols.append(c)
    never = sum(1 for x in xs if not x["on"])
    labs += [T("بیش از 30 روز", "Over 30 days"), T("هرگز وصل نشده", "Never connected")]
    vals += [D["n"] - vals[-1] - never, never]
    cols += [C["or"], C["mut"]]
    hbars(ax, labs, vals, cols, [f"{v}  ({v * 100 / n:.0f}%)" for v in vals])


def draw_sold(ax, D):
    style(ax, "حجم فروخته‌شده و مانده", "Sold volume & remaining", grid=None)
    if not D["sold"] and not D["unl_used"]:
        return empty(ax, T("کاربر دارای سقف حجم نیست", "No users with data limits"))
    labs = [T("فروخته‌شده", "Sold"), T("مصرف‌شده", "Used"),
            T("مانده", "Remaining"), T("مصرف نامحدودها", "Unlimited")]
    vals = [D["sold"], D["lim_used"], D["left"], D["unl_used"]]
    hbars(ax, labs, vals, [C["bl"], C["am"], C["gr"], C["vi"]], [fmt_bytes(v) for v in vals])
    util = D["lim_used"] * 100 / D["sold"] if D["sold"] else 0
    ax.text(0.99, 0.02, T(f"نرخ استفاده: {util:.0f}%     کاربر نامحدود: {D['unl']}",
                          f"Utilization: {util:.0f}%    Unlimited users: {D['unl']}"),
            transform=ax.transAxes, ha="right", va="bottom", color=C["txt"], fontsize=10, fontweight="bold")


def draw_health(ax, D):
    style(ax, "سلامت پنل و هشدارها", "Health & alerts", grid=None)
    it = health_items(D)
    hbars(ax, [T(a, b) for a, b, _, _ in it], [c for _, _, c, _ in it], [col for *_, col in it])


def draw_groups(ax, D):
    style(ax, "توزیع کاربران در گروه‌ها", "Users per group", grid=None)
    g = D["groups"][:10]
    if not g:
        return empty(ax, T("اطلاعات گروه موجود نیست", "No group data"))
    hbars(ax, [P(n[:20]) if n else T("بدون گروه", "No group") for n, _ in g], [c for _, c in g],
          [PAL[i % len(PAL)] for i in range(len(g))])


CHARTS = {"trend": draw_trend, "top": draw_top, "newusers": draw_newusers, "status": draw_status,
          "dist": draw_dist, "expiry": draw_expiry, "activity": draw_activity, "sold": draw_sold,
          "health": draw_health, "groups": draw_groups}


def draw_header(ax, D):
    ax.set_facecolor(C["bg"])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    rl = RANGE_L[D["days"]]
    ax.text(0.5, 0.93, T("گزارش مدیریتی پنل", "Panel Management Report"), ha="center", va="center",
            color=C["txt"], fontsize=27, fontweight="bold")
    ax.text(0.5, 0.80, f"{host(D['p'])}    |    " + T(*rl) + "    |    " + time.strftime("%Y-%m-%d  %H:%M"),
            ha="center", va="center", color=C["mut"], fontsize=13)
    rt = D["range_total"]
    util = D["lim_used"] * 100 / D["sold"] if D["sold"] else 0
    cards = [
        (T("کل کاربران", "Users"), str(D["n"]), C["bl"]),
        (T("آنلاین الان", "Online now"), str(D["online"]), C["gr"]),
        (T("فعال", "Active"), str(D["active"]), C["cy"]),
        (T("منقضی", "Expired"), str(D["expired"]), C["rd"]),
        (T("حجم تمام‌شده", "Depleted"), str(D["limited"]), C["am"]),
        (T("مصرف بازه", "Period usage"), fmt_bytes(rt) if rt is not None else "—", C["vi"]),
        (T("مصرف کل", "Total usage"), fmt_bytes(D["used"]), C["pk"]),
        (T("حجم فروخته‌شده", "Sold volume"), fmt_bytes(D["sold"]), C["bl"]),
        (T("مانده از فروخته‌شده", "Remaining"), fmt_bytes(D["left"]), C["gr"]),
        (T("نرخ استفاده", "Utilization"), f"{util:.0f}%", C["or"]),
    ]
    gap, w, h = 0.012, (1 - 4 * 0.012) / 5, 0.30
    for i, (lab, val, col) in enumerate(cards):
        r, c = divmod(i, 5)
        x, y = c * (w + gap), 0.37 - r * (h + 0.04)
        ax.add_patch(Rectangle((x, y), w, h, facecolor=C["card"], edgecolor=C["line"], linewidth=1))
        ax.add_patch(Rectangle((x, y), 0.004, h, facecolor=col, edgecolor="none"))
        ax.text(x + w / 2, y + h * 0.70, lab, ha="center", va="center", color=C["mut"], fontsize=11)
        ax.text(x + w / 2, y + h * 0.31, val, ha="center", va="center", color=col, fontsize=19, fontweight="bold")


def _png(fig, dpi):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=C["bg"])
    buf.seek(0)
    return buf


def render_dashboard(D, keys):
    if not MPL:
        raise RuntimeError("matplotlib نصب نیست. نصب کن: pip install matplotlib pillow arabic-reshaper")
    keys = [k for k in CH_ORDER if k in keys]
    rows, pend = [], []
    for k in keys:
        if k in CH_WIDE:
            if pend:
                rows.append(pend)
                pend = []
            rows.append([k])
        else:
            pend.append(k)
            if len(pend) == 2:
                rows.append(pend)
                pend = []
    if pend:
        rows.append(pend)
    with plock:
        fig = Figure(figsize=(16, 3.4 + 4.7 * len(rows) + 0.6), dpi=110)
        fig.patch.set_facecolor(C["bg"])
        gs = fig.add_gridspec(len(rows) + 2, 2, height_ratios=[3.4] + [4.7] * len(rows) + [0.6],
                              hspace=0.5, wspace=0.26, left=0.07, right=0.975, top=0.985, bottom=0.005)
        draw_header(fig.add_subplot(gs[0, :]), D)
        for r, row in enumerate(rows, 1):
            if len(row) == 1:
                CHARTS[row[0]](fig.add_subplot(gs[r, :]), D)
            else:
                for c, k in enumerate(row):
                    CHARTS[k](fig.add_subplot(gs[r, c]), D)
        fa = fig.add_subplot(gs[-1, :])
        fa.axis("off")
        fa.text(0.5, 0.5, "ATRON  ·  " + time.strftime("%Y-%m-%d %H:%M"), ha="center",
                va="center", color=C["mut"], fontsize=10)
        return _png(fig, 110)


def render_single(D, key):
    if not MPL:
        raise RuntimeError("matplotlib نصب نیست. نصب کن: pip install matplotlib pillow arabic-reshaper")
    with plock:
        fig = Figure(figsize=(10.5, 6), dpi=130)
        fig.patch.set_facecolor(C["bg"])
        ax = fig.add_subplot(111)
        fig.subplots_adjust(left=0.2 if key in ("top", "activity", "sold", "health", "groups") else 0.08,
                            right=0.96, top=0.87, bottom=0.12)
        CHARTS[key](ax, D)
        rl = RANGE_L[D["days"]]
        fig.text(0.5, 0.025, f"{host(D['p'])}   |   " + T(*rl) + "   |   " + time.strftime("%Y-%m-%d %H:%M"),
                 ha="center", color=C["mut"], fontsize=9)
        return _png(fig, 130)


# ---------- telegram flow ----------
def ch_state(chat, pid):
    S = CHS.get(chat)
    if not S or S["pid"] != pid:
        S = CHS[chat] = {"pid": pid, "range": 7, "sel": list(CH_ORDER)}
    return S


def ch_menu(chat, msg, p):
    S = ch_state(chat, p["id"])
    pid = p["id"]
    rl = dict(CH_RANGES)
    text = (f"📈 <b>نمودار و گزارش تصویری</b>\n🌐 {esc(host(p))}\n\n"
            f"⏱ بازه: <b>{rl[S['range']]}</b>\n"
            f"🧩 بخش‌های انتخاب‌شده: <b>{len(S['sel'])}</b> از {len(CH_ORDER)}\n\n"
            "بازه و بخش‌ها را انتخاب کن، بعد خروجی را بگیر:\n"
            "🖼 <b>گزارش کامل</b> = یک تصویر داشبورد با همه‌ی آمار و نمودارهای انتخابی\n"
            "🎨 <b>گالری نمودارها</b> = هر نمودار یک تصویر مستقل")
    if not MPL:
        text += "\n\n⚠️ matplotlib نصب نیست؛ برای تصویر این را نصب کن: <code>pip install matplotlib pillow arabic-reshaper</code>"
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(*[B(("✓ " if S["range"] == d else "") + lbl, callback_data=f"CHr:{pid}:{d}") for d, lbl in CH_RANGES])
    kb.add(*[B(tg(CH_NAMES[k], k in S["sel"]), callback_data=f"CHt:{pid}:{k}") for k in CH_ORDER])
    kb.add(B("☑️ انتخاب همه", callback_data=f"CHa:{pid}"), B("🧹 هیچ‌کدام", callback_data=f"CHn:{pid}"))
    kb.add(B("🖼 گزارش تصویری کامل (داشبورد)", callback_data=f"CHd:{pid}"))
    kb.add(B("🎨 گالری نمودارها", callback_data=f"CHi:{pid}"), B("📄 خلاصه متنی", callback_data=f"CHx:{pid}"))
    kb.add(B("🔙 پنل", callback_data=f"p:{pid}"))
    edit(msg, text, kb)


def ch_images_menu(chat, msg, p):
    S = ch_state(chat, p["id"])
    pid = p["id"]
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(*[B(CH_NAMES[k], callback_data=f"CHg:{pid}:{k}") for k in CH_ORDER])
    kb.add(B(f"📤 ارسال همه‌ی انتخاب‌شده‌ها ({len(S['sel'])})", callback_data=f"CHs:{pid}"))
    kb.add(B("🔙 نمودارها", callback_data=f"CH:{pid}"))
    edit(msg, "🎨 <b>گالری نمودارها</b>\nروی هر نمودار بزن تا همان یک تصویر ارسال شود، یا همه‌ی انتخاب‌شده‌ها را یکجا بفرست.\n"
              f"⏱ بازه: <b>{dict(CH_RANGES)[S['range']]}</b>", kb)


def ch_caption(D, extra=""):
    return f"📈 {host(D['p'])} — {RANGE_L[D['days']][0]}{extra}"


def ch_run_dashboard(chat, msg, p, S):
    edit(msg, "⏳ در حال ساخت گزارش تصویری... (ممکن است چند ثانیه طول بکشد)")
    D = chart_data(p, S["range"])
    img = render_dashboard(D, S["sel"])
    stamp = time.strftime("%Y%m%d-%H%M")
    try:
        bot.send_photo(chat, img, caption=ch_caption(D, "\n🖼 گزارش کامل مدیریتی"))
    except Exception:
        pass
    img.seek(0)
    bot.send_document(chat, img, visible_file_name=f"report-{host(p).replace(':', '_')}-{stamp}.png",
                      caption="🖼 همان گزارش با کیفیت کامل (فایل)")
    ch_menu(chat, msg, p)


def ch_send_one(chat, p, D, key):
    img = render_single(D, key)
    bot.send_photo(chat, img, caption=ch_caption(D, "\n" + CH_NAMES[key]))


def ch_run_one(chat, msg, p, S, key):
    edit(msg, f"⏳ در حال ساخت {CH_NAMES[key]} ...")
    D = chart_data(p, S["range"])
    ch_send_one(chat, p, D, key)
    ch_images_menu(chat, msg, p)


def ch_run_all(chat, msg, p, S):
    keys = [k for k in CH_ORDER if k in S["sel"]]
    if not keys:
        return edit(msg, "⚠️ هیچ بخشی انتخاب نشده.", back_kb(f"CH:{p['id']}", "🔙 نمودارها"))
    edit(msg, f"⏳ در حال ساخت {len(keys)} تصویر...")
    D = chart_data(p, S["range"])
    for i, k in enumerate(keys, 1):
        edit_quiet(msg, f"⏳ در حال ساخت تصویر {i}/{len(keys)} ...")
        ch_send_one(chat, p, D, k)
    ch_images_menu(chat, msg, p)


def ch_text(chat, msg, p, S):
    edit(msg, "⏳ در حال محاسبه...")
    D = chart_data(p, S["range"])
    hi = health_items(D)
    util = D["lim_used"] * 100 / D["sold"] if D["sold"] else 0
    rt = D["range_total"]
    out = [f"📄 <b>خلاصه مدیریتی {esc(host(p))}</b> — {RANGE_L[S['range']][0]}\n",
           f"👥 کل: <b>{D['n']}</b> | 🟢 آنلاین: <b>{D['online']}</b> | ✅ فعال: <b>{D['active']}</b>",
           f"⏳ منقضی: <b>{D['expired']}</b> | 📦 حجم‌تمام: <b>{D['limited']}</b> | 🆕 جدید در بازه: <b>{D['new']}</b>",
           f"📈 مصرف بازه: <b>{fmt_bytes(rt) if rt is not None else 'نامشخص (تاریخچه کافی نیست)'}</b>",
           f"📊 مصرف کل: <b>{fmt_bytes(D['used'])}</b>",
           f"💰 فروخته‌شده: <b>{fmt_bytes(D['sold'])}</b> | مانده: <b>{fmt_bytes(D['left'])}</b> | نرخ استفاده: <b>{util:.0f}%</b>",
           "\n<b>🩺 هشدارهای مدیریتی</b>"]
    out += [f"{'🔴' if c else '⚪️'} {fa}: <b>{c}</b>" for fa, _, c, _ in hi]
    rows = [r for r in D["top"]["rows"] if r[1] > 0][:5]
    if rows:
        out.append("\n<b>🏆 پرمصرف‌ترین‌ها</b>")
        out += [f"{i}. <code>{esc(n)}</code> — {fmt_bytes(v)}" for i, (n, v) in enumerate(rows, 1)]
    edit(msg, "\n".join(out), back_kb(f"CH:{p['id']}", "🔙 نمودارها"))


def ch_route(act, a, msg, chat):
    p = get_panel(a[1]) if len(a) > 1 else None
    if not p:
        return show_panels(chat, msg)
    S = ch_state(chat, p["id"])
    bg = lambda fn: threading.Thread(target=lambda: _safe(chat, fn), daemon=True).start()
    if act == "CH":
        return ch_menu(chat, msg, p)
    if act == "CHr":
        S["range"] = int(a[2])
        return ch_menu(chat, msg, p)
    if act == "CHt":
        if a[2] in S["sel"]:
            S["sel"].remove(a[2])
        else:
            S["sel"].append(a[2])
        return ch_menu(chat, msg, p)
    if act == "CHa":
        S["sel"] = list(CH_ORDER)
        return ch_menu(chat, msg, p)
    if act == "CHn":
        S["sel"] = []
        return ch_menu(chat, msg, p)
    if act == "CHi":
        return ch_images_menu(chat, msg, p)
    if act == "CHx":
        return bg(lambda: ch_text(chat, msg, p, S))
    if not MPL:
        return edit(msg, "⚠️ برای ساخت تصویر باید matplotlib نصب باشد.\nاین را نصب کن:\n"
                         "<code>pip install matplotlib pillow arabic-reshaper</code>\nو بعد ربات را ری‌استارت کن.",
                    back_kb(f"CH:{p['id']}", "🔙 نمودارها"))
    if act == "CHd":
        return bg(lambda: ch_run_dashboard(chat, msg, p, S))
    if act == "CHg":
        return bg(lambda: ch_run_one(chat, msg, p, S, a[2]))
    if act == "CHs":
        return bg(lambda: ch_run_all(chat, msg, p, S))


# ================= callbacks =================
def apply_op(p, x, op, arg):
    n = x["name"]
    if op == "del":
        u_delete(p, n, x["raw"])
    elif op == "reset":
        u_reset(p, n)
    elif op == "ext":
        u_modify(p, n, body_extend(x, arg))
    elif op == "vol":
        u_modify(p, n, body_volume(x, arg))
    elif op == "on":
        u_modify(p, n, {"status": "active"})
    elif op == "off":
        u_modify(p, n, {"status": "disabled"})


def export(p, chat):
    rows = users_all(p, True)
    stamp = time.strftime("%Y%m%d-%H%M")
    bot.send_document(chat, io.BytesIO(json.dumps(rows, ensure_ascii=False, indent=1).encode()),
                      visible_file_name=f"users-{stamp}.json", caption="📤 بکاپ کامل (JSON)")
    s = io.StringIO()
    w = csv.writer(s)
    w.writerow(["username", "status", "used_bytes", "limit_bytes", "expire", "online_at", "note", "sub_url"])
    for u in rows:
        w.writerow([u.get("username"), u.get("status"), u.get("used_traffic"), u.get("data_limit"),
                    u.get("expire"), u.get("online_at"), u.get("note"), sub_link(p, u)])
    bot.send_document(chat, io.BytesIO(("\ufeff" + s.getvalue()).encode("utf-8")),
                      visible_file_name=f"users-{stamp}.csv", caption="📤 خروجی CSV (قابل باز شدن در اکسل)")


def full_backup(p, chat):
    import zipfile
    j = lambda o: json.dumps(o, ensure_ascii=False, indent=1)
    stamp = time.strftime("%Y%m%d-%H%M")
    rows = users_all(p, True)
    parts = [("admins", "/api/admins"), ("nodes", "/api/nodes"), ("groups", "/api/groups"),
             ("hosts", "/api/hosts"), ("cores", "/api/cores"), ("user_templates", "/api/user_templates"),
             ("client_templates", "/api/client_templates"), ("admin_roles", "/api/admin_roles"),
             ("settings", "/api/settings"), ("system", "/api/system")]
    buf = io.BytesIO()
    got, miss = [], []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("users.json", j(rows))
        s = io.StringIO()
        w = csv.writer(s)
        w.writerow(["username", "status", "used_bytes", "limit_bytes", "expire", "online_at", "note", "sub_url"])
        for u in rows:
            w.writerow([u.get("username"), u.get("status"), u.get("used_traffic"), u.get("data_limit"),
                        u.get("expire"), u.get("online_at"), u.get("note"), sub_link(p, u)])
        z.writestr("users.csv", "\ufeff" + s.getvalue())
        for label, path in parts:
            d = None
            for params in ({"offset": 0, "limit": 1000}, None):
                try:
                    d = req(p, "GET", path, params)
                    break
                except Exception:
                    continue
            if d is None:
                miss.append(label)
                continue
            got.append(label)
            z.writestr(f"{label}.json", j(d))
        tr = trash_list(p["id"])
        if tr:
            z.writestr("trash.json", j(tr))
        z.writestr("info.json", j({"panel": p["url"], "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                                   "users": len(rows), "included": ["users"] + got, "not_available": miss}))
    size = buf.tell()
    if size > 49 * 1024 * 1024:
        return bot.send_message(chat, f"⚠️ حجم بکاپ ({fmt_bytes(size)}) از سقف ارسال تلگرام بیشتر است.")
    buf.seek(0)
    cap = (f"📦 بکاپ کلی {host(p)}\n👥 {len(rows)} کاربر + {', '.join(got) or '—'}"
           + (f"\n⚠️ در دسترس نبود: {', '.join(miss)}" if miss else "")
           + "\n🔒 حاوی اطلاعات حساس است؛ جای امن نگه‌دار.")
    bot.send_document(chat, buf, visible_file_name=f"pg-backup-{host(p).replace(':', '_')}-{stamp}.zip",
                      caption=cap[:1000])


# ================= migration =================
MGF = os.path.join(DATA_DIR, "migrations.json")
MIG = {}
SUB_UA = {"User-Agent": "v2rayN/6.42"}
STL = [("active", "🟢 فعال"), ("limited", "📦 حجم‌تمام"), ("on_hold", "⏸ در انتظار"),
       ("disabled", "🚫 غیرفعال"), ("expired", "⏳ منقضی")]
MG_TXT = ("🔀 <b>مهاجرت</b>\n\n"
          "🔗 <b>با لینک سابسکریپشن</b>: لینک سرویس مشتری (از هر پنلی) را بده؛ حجم مانده، انقضا و "
          "کانفیگ‌ها تحلیل می‌شود و در پنل مقصد ساخته می‌شود. چند لینک هم می‌شود داد.\n\n"
          "🔀 <b>پنل به پنل</b>: کاربران، گروه‌ها و تمپلیت‌ها را انتخابی از یک پنل به پنل دیگر منتقل می‌کند.")


def tg(label, flag):
    return f"{'✓' if flag else '✗'} {label}"


def show(chat, msg, text, kb=None):
    if msg:
        edit(msg, text, kb)
    else:
        bot.send_message(chat, text[:4000], reply_markup=kb)


def edit_quiet(msg, text, kb=None):
    try:
        bot.edit_message_text(text[:4000], msg.chat.id, msg.message_id, reply_markup=kb)
    except Exception:
        pass


def mig_log_all():
    return _read(MGF, [])


def mig_log_save(entry):
    with tlock:
        L = _read(MGF, [])
        for i, e in enumerate(L):
            if e["id"] == entry["id"]:
                L[i] = entry
                break
        else:
            L.append(entry)
        _write(MGF, L[-100:])


def mig_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(B("🔗 مهاجرت با لینک سابسکریپشن", callback_data="MS"),
           B("🔀 مهاجرت پنل به پنل", callback_data="MP"),
           B("📜 تاریخچه‌ی مهاجرت‌ها", callback_data="Mh"),
           B("🏠 منو", callback_data="m"))
    return kb


def pick_kb(role, exclude=None):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for p in load():
        if p["id"] == exclude:
            continue
        kb.add(B(f"🌐 {host(p)} ({p['username']})", callback_data=f"Mpick:{role}:{p['id']}"))
    kb.add(B("➕ افزودن پنل جدید", callback_data=f"MA:{role}"))
    kb.add(B("❌ لغو", callback_data="m"))
    return kb


# ---------- subscription parsing ----------
def b64(s):
    s = s.strip().replace("\n", "").replace("\r", "")
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def extract_links(body):
    txt = body.strip()
    if "://" not in txt[:300]:
        try:
            txt = b64(txt).decode("utf-8", "ignore")
        except Exception:
            pass
    return [l.strip() for l in txt.splitlines()
            if re.match(r"^(vless|vmess|trojan|ss|hysteria2?|hy2|tuic|wireguard)://", l.strip(), re.I)]


def parse_link(l):
    try:
        proto = l.split("://", 1)[0].lower()
        if proto == "vmess":
            d = json.loads(b64(l[8:]).decode("utf-8", "ignore"))
            return {"proto": "vmess", "remark": d.get("ps", ""), "host": d.get("add"),
                    "port": d.get("port"), "secret": d.get("id", ""), "extra": {}}
        if proto == "ss":
            remark = urllib.parse.unquote(l.split("#", 1)[1]) if "#" in l else ""
            main = l[5:].split("#", 1)[0].split("?", 1)[0]
            if "@" in main:
                ui, hp = main.rsplit("@", 1)
                ui = urllib.parse.unquote(ui)
                dec = ui if ":" in ui else b64(ui).decode()
            else:
                dec, hp = b64(main).decode().rsplit("@", 1)
            method, _, pw = dec.partition(":")
            h, _, port = hp.rpartition(":")
            return {"proto": "ss", "remark": remark, "host": h, "port": port, "secret": pw,
                    "extra": {"method": method}}
        u = urllib.parse.urlsplit(l)
        return {"proto": proto, "remark": urllib.parse.unquote(u.fragment), "host": u.hostname,
                "port": u.port, "secret": urllib.parse.unquote(u.username or ""),
                "extra": dict(urllib.parse.parse_qsl(u.query))}
    except Exception:
        return None


def creds_from(cfgs):
    ps = {}
    for c in cfgs:
        sec = c.get("secret")
        if not sec:
            continue
        if c["proto"] == "vless" and "vless" not in ps:
            ps["vless"] = {"id": sec}
            if c["extra"].get("flow"):
                ps["vless"]["flow"] = c["extra"]["flow"]
        elif c["proto"] == "vmess" and "vmess" not in ps:
            ps["vmess"] = {"id": sec}
        elif c["proto"] == "trojan" and "trojan" not in ps:
            ps["trojan"] = {"password": sec}
        elif c["proto"] == "ss" and "shadowsocks" not in ps:
            ps["shadowsocks"] = {"password": sec}
            if c["extra"].get("method"):
                ps["shadowsocks"]["method"] = c["extra"]["method"]
    return ps


def clean_name(n):
    n = re.sub(r"[^A-Za-z0-9_]", "_", str(n or "")).strip("_")[:32]
    if len(n.replace("_", "")) < 3:
        n = "mig_" + uuid.uuid4().hex[:6]
    return n


def analyze_sub(url):
    it = {"url": url, "ok": False, "err": "", "name": "", "used": 0, "total": 0, "exp": None,
          "status": "", "configs": [], "creds": {}, "note": "", "warn": []}
    try:
        if not re.match(r"^https?://", url, re.I):
            raise ValueError("لینک باید با http یا https شروع شود")
        base = url.split("?")[0].rstrip("/")
        info = None
        try:
            r = requests.get(base + "/info", headers=SUB_UA, timeout=20, verify=False)
            if r.ok and "json" in r.headers.get("content-type", "").lower():
                info = r.json()
        except Exception:
            info = None
        r = requests.get(url, headers=SUB_UA, timeout=25, verify=False)
        r.raise_for_status()
        if len(r.content) > 3_000_000:
            raise ValueError("پاسخ لینک خیلی بزرگ است")
        hdr = {}
        for part in r.headers.get("subscription-userinfo", "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                try:
                    hdr[k] = int(float(v))
                except ValueError:
                    pass
        cfgs = [c for c in (parse_link(l) for l in extract_links(r.text)) if c]
        if isinstance(info, dict) and info.get("username"):
            it["name"] = info["username"]
            it["used"] = info.get("used_traffic") or 0
            it["total"] = info.get("data_limit") or 0
            it["exp"] = parse_time(info.get("expire"))
            it["status"] = info.get("status", "")
            it["note"] = info.get("note") or ""
        else:
            it["used"] = hdr.get("upload", 0) + hdr.get("download", 0)
            it["total"] = hdr.get("total", 0)
            it["exp"] = parse_time(hdr.get("expire"))
        if not it["name"]:
            m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", r.headers.get("content-disposition", ""), re.I)
            if m:
                it["name"] = urllib.parse.unquote(m.group(1))
        if not it["name"] and cfgs:
            it["name"] = cfgs[0]["remark"]
        it["name"] = clean_name(it["name"])
        it["configs"] = cfgs[:30]
        it["creds"] = creds_from(cfgs)
        if not cfgs:
            it["warn"].append("کانفیگی در لینک پیدا نشد؛ UUID حفظ نمی‌شود و کاربر با اطلاعات جدید ساخته می‌شود.")
        if not (it["total"] or it["exp"] or it["used"]) and "subscription-userinfo" not in r.headers:
            it["warn"].append("اطلاعات حجم/انقضا در لینک نبود؛ با دکمه‌های ویرایش خودت وارد کن.")
        if it["exp"] and it["exp"] < time.time():
            it["warn"].append("تاریخ انقضا گذشته است.")
        if it["total"] and it["used"] >= it["total"]:
            it["warn"].append("حجم تمام شده است (با حجم باقی‌مانده، حداقل ۱MB ثبت می‌شود).")
        it["ok"] = bool(cfgs) or bool(it["total"] or it["exp"] or it["used"])
        if not it["ok"]:
            it["err"] = "اطلاعاتی از لینک خوانده نشد"
    except Exception as e:
        it["err"] = str(e)[:150]
    return it


def sub_amount(it, o):
    if not it["total"]:
        return 0
    if o["vol"] == "rem":
        return max(int(it["total"] - it["used"]), 1024 * 1024)
    return int(it["total"])


def fexp(it):
    if not it["exp"]:
        return "∞"
    d = (it["exp"] - time.time()) / 86400
    return f"{int(d)}d" if d >= 0 else "منقضی"


def item_text(it):
    if not it["ok"]:
        return f"❌ <code>{esc(it['url'][:70])}</code>\n   {esc(it['err'])}"
    total = fmt_bytes(it["total"]) if it["total"] else "نامحدود/نامشخص"
    rem = fmt_bytes(max(it["total"] - it["used"], 0)) if it["total"] else "—"
    if it["exp"]:
        d = (it["exp"] - time.time()) / 86400
        exp = f"{fdate(it['exp'])[:10]} ({int(d)} روز)" if d >= 0 else f"{fdate(it['exp'])[:10]} (منقضی)"
    else:
        exp = "نامحدود/نامشخص"
    cnt = {}
    for c in it["configs"]:
        cnt[c["proto"]] = cnt.get(c["proto"], 0) + 1
    protos = "، ".join(f"{k}×{v}" for k, v in cnt.items()) or "—"
    out = [f"👤 <b>{esc(it['name'])}</b>" + (f"  ({esc(it['status'])})" if it["status"] else ""),
           f"📦 کل: <b>{total}</b> | مصرف: <b>{fmt_bytes(it['used'])}</b> | مانده: <b>{rem}</b>",
           f"📅 انقضا: {exp}",
           f"🔌 کانفیگ‌ها: <b>{len(it['configs'])}</b> ({protos})",
           f"🔑 هویت (UUID/پسورد): {'قابل حفظ ✅' if it['creds'] else 'پیدا نشد ⚠️'}"]
    out += [f"⚠️ {esc(w)}" for w in it["warn"]]
    return "\n".join(out)


def mig_analyze_links(chat, text):
    urls = []
    for u in re.split(r"\s+", text):
        if u.startswith("http") and u not in urls:
            urls.append(u)
    urls = urls[:50]
    if not urls:
        return bot.send_message(chat, "⚠️ لینک معتبری پیدا نشد.", reply_markup=back_kb("MG", "🔙 مهاجرت"))
    w = bot.send_message(chat, f"⏳ در حال تحلیل {len(urls)} لینک...")
    with ThreadPoolExecutor(max_workers=8) as ex:
        items = list(ex.map(analyze_sub, urls))
    MIG[chat] = {"mode": "sub", "stage": "analysis", "items": items,
                 "opts": {"vol": "rem", "uuid": True, "groups": [], "dry": False}}
    mig_show_analysis(chat, w)


def mig_show_analysis(chat, msg):
    S = MIG[chat]
    items = S["items"]
    ok = [i for i in items if i["ok"]]
    kb = types.InlineKeyboardMarkup(row_width=3)
    if len(items) == 1:
        text = "🔍 <b>نتیجه‌ی تحلیل لینک</b>\n\n" + item_text(items[0])
        if ok:
            kb.add(B("✏️ نام", callback_data="Med:name"), B("✏️ حجم", callback_data="Med:gb"),
                   B("✏️ روز", callback_data="Med:days"))
    else:
        lines = []
        for i, it in enumerate(items, 1):
            if it["ok"]:
                total = fmt_bytes(it["total"]) if it["total"] else "∞"
                lines.append(f"{i}. ✅ <code>{esc(it['name'])}</code> — {fmt_bytes(it['used'])}/{total} — {fexp(it)}")
            else:
                lines.append(f"{i}. ❌ {esc(it['err'])[:70]}")
        text = f"🔍 <b>نتیجه‌ی تحلیل</b>: ✅ {len(ok)} | ❌ {len(items) - len(ok)}\n\n" + "\n".join(lines[:40])
    if ok:
        text += ("\n\n✅ همه‌چیز خوانده شد؛ پنل مقصد را انتخاب کن." if len(ok) == len(items)
                 else "\n\n✅ موارد سالم آماده‌اند؛ موارد ناموفق نادیده گرفته می‌شوند.")
        kb2 = types.InlineKeyboardMarkup()
        for row in kb.keyboard:
            kb2.row(*row)
        kb2.add(B("➡️ ادامه (انتخاب پنل مقصد)", callback_data="Mnext"))
        kb = kb2
    kb.add(B("❌ لغو", callback_data="m"))
    show(chat, msg, text, kb)


def mig_apply_edit(chat, field, t):
    S = MIG.get(chat)
    if not S:
        return bot.send_message(chat, MG_TXT, reply_markup=mig_menu_kb())
    it = S["items"][0]
    try:
        if field == "name":
            it["name"] = clean_name(t)
        elif field == "gb":
            it["total"] = int(num(t) * GB)
        elif field == "days":
            d = num(t)
            it["exp"] = (time.time() + d * 86400) if d > 0 else None
    except ValueError:
        bot.send_message(chat, "⚠️ عدد معتبر بفرست.")
    mig_show_analysis(chat, None)


# ---------- panels data ----------
GP = {}
GCACHE = {}


def fetch_groups(p, derive=False):
    """لیست گروه‌های پنل؛ برمی‌گرداند (rows, error)."""
    err = ""
    for path in ("/api/groups", "/api/group"):
        for paged in (True, False):
            rows, off = [], 0
            try:
                while off < 5000:
                    d = req(p, "GET", path, {"offset": off, "limit": 200} if paged else None)
                    gl = d.get("groups") if isinstance(d, dict) else d
                    if gl is None and isinstance(d, dict):
                        gl = next((v for v in d.values() if isinstance(v, list)), [])
                    gl = [g for g in (gl or []) if isinstance(g, dict)]
                    have = {r.get("id") for r in rows}
                    new = [g for g in gl if g.get("id") not in have]
                    if not new:
                        break
                    rows += new
                    off += len(gl)
                    total = d.get("total") if isinstance(d, dict) else None
                    if not paged or (total and len(rows) >= total) or len(gl) < 200:
                        break
                if rows:
                    return sorted(rows, key=lambda g: str(g.get("name", "")).lower()), ""
            except Exception as e:
                msg_ = f"{path}: {str(e)[:150]}"
                if "405" not in msg_ and msg_ not in err:
                    err = (err + "\n" + msg_).strip()
    if derive:
        rows = derive_groups(p)
        if rows:
            return rows, "derived"
    return [], err


def derive_groups(p):
    """وقتی ادمین مجوز groups.read ندارد: گروه‌ها از روی کاربران/تمپلیت‌هایی که خودش می‌بیند استخراج می‌شود."""
    names, cnt = {}, {}
    try:
        for u in users_all(p):
            ids = u.get("group_ids") or []
            gn = u.get("group_names") or []
            for i, gid in enumerate(ids):
                cnt[gid] = cnt.get(gid, 0) + 1
                if len(gn) == len(ids) and gn[i]:
                    names[gid] = gn[i]
    except Exception:
        pass
    try:
        for t in get_templates(p):
            for gid in (t.get("group_ids") or []):
                cnt.setdefault(gid, 0)
    except Exception:
        pass
    return sorted([{"id": g, "name": names.get(g) or f"گروه #{g}", "inbound_tags": [], "derived": True}
                   for g in cnt], key=lambda g: str(g["name"]).lower())


def get_groups(p):
    return fetch_groups(p)[0]


def groups_cached(p, force=False):
    c = GCACHE.get(p["id"])
    if c and not force and time.time() - c[0] < 60:
        return c[1]
    rows, _ = fetch_groups(p)
    GCACHE[p["id"]] = (time.time(), rows)
    return rows


def get_templates(p):
    d = first_ok(p, ["/api/user_templates"])
    tl = (d.get("templates") or d.get("user_templates") or []) if isinstance(d, dict) else (d or [])
    return [t for t in tl if isinstance(t, dict)]


def panel_opts():
    return {"users": True, "groups": True, "templates": False,
            "st": {"active": True, "limited": True, "on_hold": True, "disabled": True, "expired": False},
            "vol": "rem", "uuid": True, "conflict": "skip", "disable_src": False, "dry": False,
            "defgroup": [], "srcgroups": []}


def mig_selected(S):
    o = S["opts"]
    if not o["users"]:
        return []
    rows = [r for r in S["src_rows"] if o["st"].get(r.get("status"), False)]
    sg = set(o.get("srcgroups") or [])
    if sg:
        rows = [r for r in rows if set(r.get("group_ids") or []) & sg]
    return rows


def mig_after_add(chat, p):
    S = MIG.get(chat)
    role = S.pop("await", None) if S else None
    if not role:
        return bot.send_message(chat, "✅ پنل اضافه شد.", reply_markup=main_kb())
    mig_set_panel(chat, None, role, p["id"])


def mig_set_panel(chat, msg, role, pid):
    S = MIG.get(chat)
    if not S:
        return bot.send_message(chat, MG_TXT, reply_markup=mig_menu_kb())
    p = get_panel(pid)
    w = msg or bot.send_message(chat, "⏳")
    edit_quiet(w, "⏳ در حال خواندن اطلاعات پنل...")
    try:
        if role == "src":
            S["src"] = pid
            S["src_rows"] = users_all(p, True)
            S["src_groups"] = get_groups(p)
            S["src_templates"] = get_templates(p)
            S["stage"] = "pick_dst"
            edit(w, f"✅ مبدأ: <b>{esc(host(p))}</b>\n👥 {len(S['src_rows'])} کاربر | 🗂 {len(S['src_groups'])} گروه | "
                    f"🧩 {len(S['src_templates'])} تمپلیت\n\n📥 <b>پنل مقصد</b> را انتخاب کن:",
                 pick_kb("dst", exclude=pid))
        else:
            S["dst"] = pid
            S["dst_names"] = {u.get("username") for u in users_all(p, True)}
            S["dst_groups"] = get_groups(p)
            S["stage"] = "opts"
            mig_show_opts(chat, w)
    except Exception as e:
        edit(w, f"❌ خواندن پنل ناموفق: <code>{esc(e)}</code>", back_kb("MG", "🔙 مهاجرت"))


def mig_show_opts(chat, msg):
    S = MIG[chat]
    o = S["opts"]
    dst = get_panel(S["dst"])
    kb = types.InlineKeyboardMarkup(row_width=2)
    if S["mode"] == "sub":
        ok = [i for i in S["items"] if i["ok"]]
        gn = {g.get("id"): g.get("name") for g in S["dst_groups"]}
        gnames = "، ".join(str(gn.get(g, g)) for g in o["groups"]) or "—"
        text = (f"🔗 <b>مهاجرت با لینک</b>\n📥 مقصد: <b>{esc(host(dst))}</b>\n👥 {len(ok)} سرویس آماده\n\n"
                f"📦 حجم: <b>{'مانده (کل − مصرف)' if o['vol'] == 'rem' else 'کل حجم'}</b>\n"
                f"🔑 حفظ UUID/پسورد: <b>{'بله' if o['uuid'] else 'خیر'}</b>\n"
                f"🗂 گروه: <b>{esc(gnames)}</b>\n"
                f"🧪 حالت آزمایشی: <b>{'روشن' if o['dry'] else 'خاموش'}</b>")
        kb.add(B("📦 حجم: " + ("مانده" if o["vol"] == "rem" else "کل"), callback_data="Mo:vol"),
               B(tg("🔑 حفظ UUID", o["uuid"]), callback_data="Mo:uuid"))
        kb.add(B("🗂 انتخاب گروه", callback_data="Mg"), B(tg("🧪 آزمایشی", o["dry"]), callback_data="Mo:dry"))
    else:
        src = get_panel(S["src"])
        sel = mig_selected(S)
        dup = sum(1 for r in sel if r.get("username") in S["dst_names"])
        sold = sum(r.get("data_limit") or 0 for r in sel)
        dg = {g.get("name") for g in S["dst_groups"]}
        miss = [str(g.get("name")) for g in S["src_groups"] if g.get("name") not in dg]
        miss_txt = f" ({esc(', '.join(miss[:5]))})" if miss else ""
        sgn = {g.get("id"): g.get("name") for g in S["src_groups"]}
        sg_txt = "، ".join(str(sgn.get(i, i)) for i in o.get("srcgroups", [])) or "همه گروه‌ها"
        dgn = {g.get("id"): g.get("name") for g in S["dst_groups"]}
        dg_txt = "، ".join(str(dgn.get(i, i)) for i in o.get("defgroup", [])) or "—"
        text = (f"🔀 <b>مهاجرت پنل به پنل</b>\n📤 {esc(host(src))} ← 📥 {esc(host(dst))}\n\n"
                f"👥 انتخاب‌شده: <b>{len(sel)}</b> از {len(S['src_rows'])} | ⚠️ تکراری در مقصد: <b>{dup}</b>\n"
                f"💰 حجم فروخته‌شده‌ی انتخابی: <b>{fmt_bytes(sold)}</b>\n"
                f"🗂 گروه‌های مبدأ: {len(S['src_groups'])} | در مقصد نیست: <b>{len(miss)}</b>{miss_txt}\n"
                f"🧩 تمپلیت‌ها: {len(S['src_templates'])}\n"
                f"🎯 فیلتر گروه مبدأ: <b>{esc(sg_txt)}</b>\n"
                f"🗂 گروه پیش‌فرض مقصد: <b>{esc(dg_txt)}</b>\n\n"
                "هر گزینه را بزن تا روشن/خاموش شود. چیزی که ✓ دارد منتقل می‌شود:")
        kb.add(B(tg("👥 کاربران", o["users"]), callback_data="Mo:users"),
               B(tg("🗂 گروه‌ها", o["groups"]), callback_data="Mo:groups"))
        kb.add(B(tg("🧩 تمپلیت‌ها", o["templates"]), callback_data="Mo:templates"))
        kb.add(*[B(tg(lbl, o["st"][k]), callback_data=f"Mo:st:{k}") for k, lbl in STL])
        kb.add(B("📦 حجم: " + ("مانده" if o["vol"] == "rem" else "کل"), callback_data="Mo:vol"),
               B(tg("🔑 حفظ UUID", o["uuid"]), callback_data="Mo:uuid"))
        cl = {"skip": "⏭ تکراری: رد شود", "rename": "✏️ تکراری: تغییر نام", "update": "♻️ تکراری: بازنویسی"}
        kb.add(B(cl[o["conflict"]], callback_data="Mo:conf"))
        kb.add(B("🎯 فیلتر گروه مبدأ", callback_data="Mgf"), B("🗂 گروه پیش‌فرض مقصد", callback_data="Mg"))
        kb.add(B(tg("🚫 غیرفعال در مبدأ", o["disable_src"]), callback_data="Mo:disable_src"),
               B(tg("🧪 آزمایشی", o["dry"]), callback_data="Mo:dry"))
    kb.add(B("🚀 شروع انتقال", callback_data="Mgo"), B("❌ لغو", callback_data="m"))
    edit(msg, text, kb)


# ---------- execution ----------
def create_user(p, body, creds=None):
    tries = []
    if creds:
        tries += [{**body, "proxy_settings": creds}, {**body, "proxies": creds}]
    tries.append(body)
    last = None
    for b in tries:
        try:
            return req(p, "POST", "/api/user", body=b)
        except Exception as e:
            last = e
            if "409" in str(e) or "already" in str(e).lower() or "exist" in str(e).lower():
                break
    raise last


def stop_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(B("⏹ توقف", callback_data="Mstop"))
    return kb


def send_links_csv(chat, dst, names, fname):
    rows = {u.get("username"): u for u in users_all(dst, True)}
    s = io.StringIO()
    w = csv.writer(s)
    w.writerow(["username", "sub_url"])
    for n in names:
        if n in rows:
            w.writerow([n, sub_link(dst, rows[n])])
    bot.send_document(chat, io.BytesIO(("\ufeff" + s.getvalue()).encode("utf-8")),
                      visible_file_name=fname, caption="🔗 لینک‌های ساب جدید (برای ارسال به مشتری‌ها)")


def send_text_doc(chat, text, fname, caption):
    bot.send_document(chat, io.BytesIO(text.encode("utf-8")), visible_file_name=fname, caption=caption)


def mig_runner(chat, msg):
    S = MIG.get(chat)
    if not S or S.get("running"):
        return
    S["running"] = True
    try:
        if S["mode"] == "sub":
            mig_run_sub(chat, msg, S)
        else:
            mig_run_panel(chat, msg, S)
    except Exception as e:
        edit(msg, f"❌ مهاجرت با خطا متوقف شد:\n<code>{esc(e)}</code>", back_kb("MG", "🔙 مهاجرت"))
    finally:
        S["running"] = False


def mig_run_sub(chat, msg, S):
    o = S["opts"]
    dst = get_panel(S["dst"])
    items = [i for i in S["items"] if i["ok"]]
    S["cancel"] = False
    names = {u.get("username") for u in users_all(dst, True)}
    created, fails = [], []
    last = 0
    for n, it in enumerate(items, 1):
        if S["cancel"]:
            break
        name = it["name"]
        if name in names:
            k = 2
            while f"{name[:28]}_{k}" in names:
                k += 1
            name = f"{name[:28]}_{k}"
        body = {"username": name, "status": "active"}
        amount = sub_amount(it, o)
        if amount:
            body["data_limit"] = amount
        if it["exp"]:
            body["expire"] = int(it["exp"])
        if it.get("note"):
            body["note"] = it["note"]
        if o["groups"]:
            body["group_ids"] = o["groups"]
        try:
            if not o["dry"]:
                create_user(dst, body, it["creds"] if o["uuid"] else None)
            names.add(name)
            created.append(name)
        except Exception as e:
            fails.append((it["name"], str(e)[:140]))
        if time.time() - last > 3:
            last = time.time()
            edit_quiet(msg, f"⏳ در حال انتقال... {n}/{len(items)}\n✅ {len(created)} | ❌ {len(fails)}", stop_kb())
    CACHE.pop(dst["id"], None)
    stopped = S["cancel"]
    out = [f"{'🧪 ' if o['dry'] else ''}✅ <b>مهاجرت با لینک تمام شد</b>" + (" (متوقف شد)" if stopped else ""),
           f"📥 مقصد: <b>{esc(host(dst))}</b>",
           f"✅ ساخته‌شده: <b>{len(created)}</b> | ❌ خطا: <b>{len(fails)}</b>"]
    for nm, er in fails[:8]:
        out.append(f"▫️ <code>{esc(nm)}</code>: {esc(er)}")
    if created and not o["dry"]:
        out.append("\nℹ️ UUID/پسورد حفظ شد؛ فقط آدرس سرور و لینک ساب عوض می‌شود. لینک جدید را به مشتری بده.")
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(B("📜 تاریخچه / بازگردانی", callback_data="Mh"), B("🏠 منو", callback_data="m"))
    edit(msg, "\n".join(out), kb)
    if created and not o["dry"]:
        mig_log_save({"id": uuid.uuid4().hex[:8], "at": time.time(), "mode": "sub", "src": "لینک ساب",
                      "dst": host(dst), "dst_id": dst["id"], "src_id": None, "created": created,
                      "disabled": [], "undone": False})
        if len(created) == 1:
            try:
                link = sub_link(dst, u_get(dst, created[0]))
                bot.send_message(chat, f"🔗 لینک ساب جدید:\n<code>{esc(link)}</code>")
            except Exception:
                pass
        else:
            send_links_csv(chat, dst, created, "new-sub-links.csv")
    if fails:
        send_text_doc(chat, "\n".join(f"{a}\t{b}" for a, b in fails), "migration-errors.txt", "❌ خطاهای مهاجرت")


def build_gmap(S, dst):
    o = S["opts"]
    dg = {g.get("name"): g.get("id") for g in S["dst_groups"]}
    res, created, errs = {}, [], []
    for g in S["src_groups"]:
        nm, gid = g.get("name"), g.get("id")
        if nm in dg:
            res[gid] = dg[nm]
        elif o["groups"]:
            if o["dry"]:
                created.append(nm)
                continue
            try:
                r = req(dst, "POST", "/api/group", body={"name": nm, "inbound_tags": g.get("inbound_tags", []),
                                                         "is_disabled": g.get("is_disabled", False)})
                res[gid] = r.get("id")
                created.append(nm)
            except Exception as e:
                errs.append(f"{nm}: {str(e)[:100]}")
    return res, created, errs


def panel_user_body(r, name, o, gids):
    x = uinfo(r)
    st = r.get("status")
    body = {"username": name, "status": st if st in ("disabled", "on_hold") else "active"}
    if x["lim"]:
        body["data_limit"] = max(int(x["lim"] - x["used"]), 1024 * 1024) if o["vol"] == "rem" else int(x["lim"])
    if st == "on_hold":
        for k in ("on_hold_expire_duration", "on_hold_timeout"):
            if r.get(k) is not None:
                body[k] = r[k]
    elif x["exp"]:
        body["expire"] = int(x["exp"])
    if r.get("note"):
        body["note"] = r["note"]
    if r.get("data_limit_reset_strategy"):
        body["data_limit_reset_strategy"] = r["data_limit_reset_strategy"]
    if gids:
        body["group_ids"] = gids
    return body


def mig_run_panel(chat, msg, S):
    o = S["opts"]
    src, dst = get_panel(S["src"]), get_panel(S["dst"])
    S["cancel"] = False
    sel = mig_selected(S)
    dnames = {u.get("username") for u in users_all(dst, True)}
    gmap, gnew, gerr = ({}, [], [])
    if o["users"] or o["templates"] or o["groups"]:
        gmap, gnew, gerr = build_gmap(S, dst)
    tok = tfail = 0
    terr = ""
    if o["templates"] and not o["dry"]:
        for t in S["src_templates"]:
            b = {k: v for k, v in t.items() if k != "id"}
            if b.get("group_ids"):
                b["group_ids"] = [gmap[g] for g in b["group_ids"] if g in gmap]
            try:
                req(dst, "POST", "/api/user_template", body=b)
                tok += 1
            except Exception as e:
                tfail += 1
                terr = terr or str(e)[:100]
    created, updated, skipped, failed, disabled = [], [], [], [], []
    last = 0
    for n, r in enumerate(sel, 1):
        if S["cancel"]:
            break
        orig = r.get("username")
        name = orig
        try:
            is_update = False
            if name in dnames:
                if o["conflict"] == "skip":
                    skipped.append(name)
                    continue
                if o["conflict"] == "rename":
                    k = 2
                    while f"{orig[:28]}_{k}" in dnames:
                        k += 1
                    name = f"{orig[:28]}_{k}"
                else:
                    is_update = True
            gids = [gmap[g] for g in (r.get("group_ids") or []) if g in gmap] or list(o["defgroup"])
            body = panel_user_body(r, name, o, gids)
            creds = (r.get("proxy_settings") or r.get("proxies")) if o["uuid"] else None
            if not o["dry"]:
                if is_update:
                    body.pop("username", None)
                    req(dst, "PUT", f"/api/user/{name}", body=body)
                else:
                    create_user(dst, body, creds)
                if o["disable_src"]:
                    u_modify(src, orig, {"status": "disabled"})
                    disabled.append(orig)
            (updated if is_update else created).append(name)
            dnames.add(name)
        except Exception as e:
            failed.append((name, str(e)[:140]))
        if time.time() - last > 3:
            last = time.time()
            edit_quiet(msg, f"⏳ در حال انتقال... {n}/{len(sel)}\n✅ {len(created)} | ♻️ {len(updated)} | "
                            f"⏭ {len(skipped)} | ❌ {len(failed)}", stop_kb())
    CACHE.pop(dst["id"], None)
    stopped = S["cancel"]
    out = [f"{'🧪 ' if o['dry'] else ''}✅ <b>مهاجرت پنل به پنل تمام شد</b>" + (" (متوقف شد)" if stopped else ""),
           f"📤 {esc(host(src))} ← 📥 {esc(host(dst))}\n",
           f"✅ ساخته‌شده: <b>{len(created)}</b> | ♻️ بازنویسی: <b>{len(updated)}</b>",
           f"⏭ رد شده (تکراری): <b>{len(skipped)}</b> | ❌ خطا: <b>{len(failed)}</b>"]
    if o["groups"]:
        out.append(f"🗂 گروه {'قابل ساخت' if o['dry'] else 'ساخته‌شده'}: {len(gnew)}" +
                   (f" | ❌ {len(gerr)}" if gerr else ""))
    if o["templates"]:
        out.append(f"🧩 تمپلیت: ✅ {tok} | ❌ {tfail}" + (f"\n<code>{esc(terr)}</code>" if terr else ""))
    if disabled:
        out.append(f"🚫 غیرفعال‌شده در مبدأ: {len(disabled)}")
    for nm, er in failed[:6]:
        out.append(f"▫️ <code>{esc(nm)}</code>: {esc(er)}")
    if created and not o["dry"]:
        out.append("\nℹ️ هویت (UUID) حفظ شد ولی لینک ساب و آدرس سرور جدید است؛ فایل لینک‌های جدید را برایت می‌فرستم.")
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(B("📜 تاریخچه / بازگردانی", callback_data="Mh"), B("🏠 منو", callback_data="m"))
    edit(msg, "\n".join(out), kb)
    if (created or updated) and not o["dry"]:
        mig_log_save({"id": uuid.uuid4().hex[:8], "at": time.time(), "mode": "panel", "src": host(src),
                      "dst": host(dst), "dst_id": dst["id"], "src_id": src["id"], "created": created,
                      "disabled": disabled, "undone": False})
        send_links_csv(chat, dst, created + updated, "new-sub-links.csv")
    if failed or gerr:
        send_text_doc(chat, "\n".join([f"{a}\t{b}" for a, b in failed] + [f"group\t{e}" for e in gerr]),
                      "migration-errors.txt", "❌ خطاهای مهاجرت")


def mig_undo(chat, msg, eid):
    L = mig_log_all()
    e = next((x for x in L if x["id"] == eid), None)
    if not e or e.get("undone"):
        return edit(msg, "این مهاجرت پیدا نشد یا قبلاً بازگردانی شده.", back_kb("Mh", "🔙 تاریخچه"))
    dst = get_panel(e["dst_id"])
    src = get_panel(e["src_id"]) if e.get("src_id") else None
    if not dst:
        return edit(msg, "❌ پنل مقصد دیگر در ربات ثبت نیست.", back_kb("Mh", "🔙 تاریخچه"))
    ok = fail = 0
    for i, n in enumerate(e["created"], 1):
        try:
            u_delete(dst, n)
            ok += 1
        except Exception:
            fail += 1
        if i % 10 == 0:
            edit_quiet(msg, f"⏳ بازگردانی... {i}/{len(e['created'])}")
    back = 0
    for n in e.get("disabled", []):
        try:
            if src:
                u_modify(src, n, {"status": "active"})
                back += 1
        except Exception:
            pass
    e["undone"] = True
    mig_log_save(e)
    edit(msg, f"↩️ <b>بازگردانی انجام شد</b>\n🗑 از مقصد حذف شد: {ok} (در سطل زباله ربات هم هست) | ❌ {fail}\n"
              f"✅ در مبدأ دوباره فعال شد: {back}", back_kb("Mh", "🔙 تاریخچه"))


# ---------- router ----------
def mig_route(act, a, msg, chat):
    S = MIG.get(chat)
    if act == "MG":
        return edit(msg, MG_TXT, mig_menu_kb())
    if act == "MS":
        MIG.pop(chat, None)
        ST[chat] = {"step": "mig_links"}
        return prompt(chat, "🔗 <b>لینک سابسکریپشن</b> را بفرست.\nمی‌توانی چند لینک بفرستی (هر خط یکی، حداکثر ۵۰ تا).")
    if act == "MP":
        MIG[chat] = {"mode": "panel", "stage": "pick_src", "opts": panel_opts()}
        return edit(msg, "📤 <b>پنل مبدأ</b> را انتخاب کن:", pick_kb("src"))
    if act == "Mh":
        L = mig_log_all()[-10:][::-1]
        kb = types.InlineKeyboardMarkup(row_width=1)
        for e in L:
            kb.add(B(f"{'↩️' if e.get('undone') else '📦'} {e['src'][:16]}→{e['dst'][:16]} ({len(e['created'])}) "
                     f"{fdate(e['at'])[:10]}", callback_data=f"Mu:{e['id']}"))
        kb.add(B("🔙 مهاجرت", callback_data="MG"))
        return edit(msg, "📜 <b>تاریخچه‌ی مهاجرت‌ها</b>" + ("" if L else "\n\nچیزی ثبت نشده."), kb)
    if act == "Mu":
        e = next((x for x in mig_log_all() if x["id"] == a[1]), None)
        if not e:
            return edit(msg, "پیدا نشد.", back_kb("Mh", "🔙 تاریخچه"))
        kb = types.InlineKeyboardMarkup(row_width=1)
        if not e.get("undone") and e["created"]:
            kb.add(B("↩️ بازگردانی (حذف ساخته‌شده‌ها از مقصد)", callback_data=f"Muc:{e['id']}"))
        kb.add(B("🔙 تاریخچه", callback_data="Mh"))
        return edit(msg, f"📦 <b>مهاجرت {esc(e['id'])}</b>\n{fdate(e['at'])}\n"
                         f"{esc(e['src'])} ← {esc(e['dst'])}\n✅ ساخته‌شده: {len(e['created'])}"
                         f"\n🚫 غیرفعال در مبدأ: {len(e.get('disabled', []))}"
                         f"\nوضعیت: {'بازگردانی شده ↩️' if e.get('undone') else 'فعال'}", kb)
    if act == "Muc":
        edit(msg, "⏳ در حال بازگردانی...")
        threading.Thread(target=lambda: _safe(chat, lambda: mig_undo(chat, msg, a[1])), daemon=True).start()
        return
    if act == "Mstop":
        if S:
            S["cancel"] = True
        return edit_quiet(msg, "⏹ در حال توقف...")
    if not S:
        return edit(msg, MG_TXT, mig_menu_kb())
    if act == "Mpick":
        return mig_set_panel(chat, msg, a[1], a[2])
    if act == "MA":
        S["await"] = a[1]
        return ask_url(chat, "mig")
    if act == "Mnext":
        S["stage"] = "pick_dst"
        return edit(msg, "📥 <b>پنل مقصد</b> را انتخاب کن:", pick_kb("dst"))
    if act == "Med":
        ST[chat] = {"step": "mig_edit", "field": a[1]}
        return prompt(chat, {"name": "✏️ نام کاربری جدید:", "gb": "✏️ حجم کل (گیگ؛ ۰ = نامحدود):",
                             "days": "✏️ چند روز از الان تا انقضا (۰ = نامحدود):"}[a[1]])
    if act == "Mo":
        o = S["opts"]
        k = a[1]
        if k == "st":
            o["st"][a[2]] = not o["st"][a[2]]
        elif k == "vol":
            o["vol"] = "total" if o["vol"] == "rem" else "rem"
        elif k == "conf":
            o["conflict"] = {"skip": "rename", "rename": "update", "update": "skip"}[o["conflict"]]
        else:
            o[k] = not o[k]
        return mig_show_opts(chat, msg)
    if act == "Mg":
        return grp_start(chat, S["dst"], "sub" if S["mode"] == "sub" else "def", msg)
    if act == "Mgf":
        return grp_start(chat, S["src"], "srcf", msg)
    if act == "Mb":
        return mig_show_opts(chat, msg)
    if act == "Mgo":
        o = S["opts"]
        n = len([i for i in S["items"] if i["ok"]]) if S["mode"] == "sub" else len(mig_selected(S))
        warn = []
        if S["mode"] == "panel" and o["disable_src"] and not o["dry"]:
            warn.append("🚫 کاربران منتقل‌شده در مبدأ غیرفعال می‌شوند.")
        if S["mode"] == "panel" and o["conflict"] == "update":
            warn.append("♻️ کاربران تکراری در مقصد بازنویسی می‌شوند.")
        if S["mode"] == "sub" and not o["groups"] and S["dst_groups"]:
            warn.append("⚠️ هیچ گروهی انتخاب نشده؛ اگر پنل مقصد گروه را اجباری بداند، ساخت کاربر خطا می‌دهد.")
        if o["dry"]:
            warn.append("🧪 حالت آزمایشی: چیزی ساخته نمی‌شود، فقط گزارش می‌گیری.")
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(B("✅ تأیید و شروع", callback_data="Mrun"), B("🔙 تنظیمات", callback_data="Mb"))
        return edit(msg, f"⚠️ <b>تأیید نهایی</b>\n{n} کاربر منتقل می‌شود.\n" + "\n".join(warn), kb)
    if act == "Mrun":
        edit(msg, "⏳ شروع شد...", stop_kb())
        threading.Thread(target=mig_runner, args=(chat, msg), daemon=True).start()
        return


def _safe(chat, fn):
    try:
        fn()
    except Exception as e:
        bot.send_message(chat, f"⚠️ خطا: <code>{esc(e)}</code>")


# ================= group picker =================
GP_TITLES = {
    "create": "🗂 <b>گروه کاربر جدید</b>",
    "sub": "🗂 <b>گروه کاربران در پنل مقصد</b>",
    "def": "🗂 <b>گروه پیش‌فرض پنل مقصد</b>\n(برای کاربرانی که گروهشان قابل نگاشت نیست)",
    "user": "🗂 <b>تغییر گروه‌های کاربر</b>",
    "srcf": "🎯 <b>فیلتر گروه‌های مبدأ</b>\n(فقط کاربران این گروه‌ها منتقل شوند)",
}


def grp_cancel_cb(G):
    if G["ctx"] == "create":
        return "m"
    if G["ctx"] == "user":
        return f"U:{G['pid']}:{G['extra'].get('name')}"
    return "Mb"


def grp_start(chat, pid, ctx, msg=None, extra=None):
    p = get_panel(pid)
    rows, err = fetch_groups(p, derive=True)
    GCACHE[pid] = (time.time(), rows)
    sel = []
    if ctx in ("sub", "def", "srcf") and MIG.get(chat):
        key = {"sub": "groups", "def": "defgroup", "srcf": "srcgroups"}[ctx]
        sel = list(MIG[chat]["opts"].get(key, []))
    elif ctx == "user":
        sel = list((extra or {}).get("gids", []))
    GP[chat] = {"pid": pid, "ctx": ctx, "groups": rows, "sel": sel, "page": 0, "extra": extra or {}, "err": err}
    grp_main(chat, msg)


def grp_main(chat, msg):
    G = GP[chat]
    rows = G["groups"]
    p = get_panel(G["pid"])
    kb = types.InlineKeyboardMarkup(row_width=2)
    if not rows:
        text = (GP_TITLES[G["ctx"]] + "\n\n⚠️ گروهی در این پنل پیدا نشد."
                + (f"\n<code>{esc(G['err'])}</code>" if G["err"] else "")
                + "\n(شاید دسترسی ادمین به گروه‌ها محدود است.)")
        kb.add(B("🔄 تلاش دوباره", callback_data="Gretry"), B("✍️ وارد کردن ID گروه", callback_data="Gman"))
        if G["ctx"] != "srcf":
            kb.add(B("➖ ادامه بدون گروه", callback_data="Gnone"))
    else:
        names = {g.get("id"): g.get("name") for g in rows}
        cur = "، ".join(str(names.get(i, i)) for i in G["sel"]) or ("همه" if G["ctx"] == "srcf" else "—")
        text = (GP_TITLES[G["ctx"]] + f"\n\n🌐 پنل: <b>{esc(host(p))}</b>\n📚 تعداد گروه‌ها: <b>{len(rows)}</b>\n"
                f"📌 انتخاب فعلی: <b>{esc(cur)}</b>\n"
                + ("⚠️ مجوز groups.read ندارید؛ گروه‌ها از روی کاربران فعلی استخراج شد.\n" if G["err"] == "derived" else "")
                + "\nیکی از دو روش را انتخاب کن:")
        kb.add(B(f"✅ انتخاب همه ({len(rows)})", callback_data="Gall"),
               B("🎯 انتخاب دلخواه", callback_data="Gcus"))
        if G["sel"]:
            kb.add(B(f"➡️ ادامه با انتخاب فعلی ({len(G['sel'])})", callback_data="Gok"))
        kb.add(B("✍️ وارد کردن ID گروه", callback_data="Gman"))
        if G["ctx"] != "srcf":
            kb.add(B("➖ بدون گروه", callback_data="Gnone"))
    kb.add(B("❌ لغو", callback_data=grp_cancel_cb(G)))
    show(chat, msg, text, kb)


def grp_custom(chat, msg):
    G = GP[chat]
    rows, sel = G["groups"], G["sel"]
    per = 16
    pages = max(1, (len(rows) + per - 1) // per)
    pg = max(0, min(G["page"], pages - 1))
    G["page"] = pg
    chunk = rows[pg * per:(pg + 1) * per]
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(*[B(("✓ " if g.get("id") in sel else "✗ ") + str(g.get("name"))[:22], callback_data=f"Gt:{g.get('id')}")
             for g in chunk])
    if pages > 1:
        nav = []
        if pg > 0:
            nav.append(B("⬅️ قبلی", callback_data=f"Gpg:{pg - 1}"))
        nav.append(B(f"{pg + 1}/{pages}", callback_data="Gnoop"))
        if pg < pages - 1:
            nav.append(B("بعدی ➡️", callback_data=f"Gpg:{pg + 1}"))
        kb.row(*nav)
    kb.add(B("☑️ انتخاب همه", callback_data="Gsa"), B("🧹 پاک کردن همه", callback_data="Gcl"))
    kb.add(B("✍️ وارد کردن ID گروه", callback_data="Gman"))
    kb.add(B(f"✅ تأیید ({len(sel)})", callback_data="Gok"), B("🔙 برگشت", callback_data="Gback"))
    edit(msg, GP_TITLES[G["ctx"]] + f"\n\n🎯 <b>انتخاب دلخواه</b>: روی هر گروه بزن تا انتخاب/لغو شود.\n"
              f"انتخاب‌شده: <b>{len(sel)}</b> از {len(rows)}", kb)


def grp_finish(chat, msg, gids):
    G = GP.pop(chat, None)
    if not G:
        return
    ctx = G["ctx"]
    if ctx == "create":
        edit_quiet(msg, "⏳ در حال ساخت کاربر...")
        return do_create(chat, gids)
    if ctx == "user":
        p = get_panel(G["pid"])
        name = G["extra"]["name"]
        u_modify(p, name, {"group_ids": gids})
        text, kb = user_view(p, name)
        return edit(msg, "✅ گروه‌ها بروزرسانی شد\n\n" + text, kb)
    S = MIG.get(chat)
    if not S:
        return edit(msg, MG_TXT, mig_menu_kb())
    if ctx == "srcf":
        S["opts"]["srcgroups"] = [] if len(gids) == len(G["groups"]) else gids
    elif ctx == "sub":
        S["opts"]["groups"] = gids
        S["dst_groups"] = G["groups"] or S.get("dst_groups", [])
    else:
        S["opts"]["defgroup"] = gids
        S["dst_groups"] = G["groups"] or S.get("dst_groups", [])
    mig_show_opts(chat, msg)


def grp_route(act, a, msg, chat):
    if act == "GL":
        p = get_panel(a[1])
        rows, gerr = fetch_groups(p, derive=True)
        GCACHE[p["id"]] = (time.time(), rows)
        if not rows:
            why = f"\n\n<b>پاسخ پنل:</b>\n<code>{esc(gerr)}</code>" if gerr else "\n\nپنل لیست خالی برگرداند (گروهی ساخته نشده)."
            return edit(msg, "🗂 گروهی دریافت نشد." + why, back_kb(f"p:{p['id']}", "🔙 پنل"))
        cnt = {}
        for u in users_all(p):
            for gid in (u.get("group_ids") or []):
                cnt[gid] = cnt.get(gid, 0) + 1
        out = [f"🗂 <b>گروه‌ها ({len(rows)})</b>\n"]
        for g in rows:
            out.append(f"▫️ <b>{esc(g.get('name'))}</b> — 👥 {cnt.get(g.get('id'), 0)} کاربر | "
                       f"🔌 {len(g.get('inbound_tags') or [])} اینباند" + (" | ⛔ غیرفعال" if g.get("is_disabled") else ""))
        if gerr == "derived":
            out.append("\n⚠️ ادمین شما مجوز groups.read ندارد؛ این گروه‌ها از روی کاربران فعلی شما استخراج شده‌اند "
                       "(نام واقعی ممکن است نیاید). گروه جدید را با «✍️ وارد کردن ID» در ساخت کاربر اضافه کن.")
        return edit(msg, "\n".join(out), back_kb(f"p:{p['id']}", "🔙 پنل"))
    if act == "GU":
        p = get_panel(a[1])
        u = u_get(p, a[2])
        return grp_start(chat, p["id"], "user", msg, {"name": a[2], "gids": u.get("group_ids") or []})
    G = GP.get(chat)
    if not G:
        return edit(msg, MENU_TXT, main_kb())
    rows = G["groups"]
    if act == "Gall":
        return grp_finish(chat, msg, [g["id"] for g in rows])
    if act == "Gnone":
        return grp_finish(chat, msg, [])
    if act == "Gok":
        return grp_finish(chat, msg, list(G["sel"]))
    if act == "Gcus":
        G["page"] = 0
        return grp_custom(chat, msg)
    if act == "Gback":
        return grp_main(chat, msg)
    if act == "Gretry":
        return grp_start(chat, G["pid"], G["ctx"], msg, G["extra"])
    if act == "Gnoop":
        return
    if act == "Gman":
        st = ST.setdefault(chat, {})
        G["prev_step"] = st.get("step")
        st["step"] = "g_manual"
        return prompt(chat, "✍️ <b>ID عددی گروه</b> را بفرست (چند تا را با فاصله یا ویرگول جدا کن).\n"
                            "ID را از داشبورد پنل یا از «🗂 تغییر گروه» یک کاربر قدیمی می‌توانی پیدا کنی.")
    if act == "Gt":
        gid = next((g["id"] for g in rows if str(g.get("id")) == a[1]), None)
        if gid is not None:
            if gid in G["sel"]:
                G["sel"].remove(gid)
            else:
                G["sel"].append(gid)
    elif act == "Gsa":
        G["sel"] = [g["id"] for g in rows]
    elif act == "Gcl":
        G["sel"] = []
    elif act == "Gpg":
        G["page"] = int(a[1])
    return grp_custom(chat, msg)


def route(act, a, msg, chat):
    if act == "m":
        ST.pop(chat, None)
        return edit(msg, MENU_TXT, main_kb())
    if act == "help":
        return edit(msg, HELP, back_kb("m", "🏠 منو"))
    if act == "lg":
        if len(a) > 1 and a[1] in ("en", "fa"):
            set_lang(a[1])
            return edit(msg, MENU_TXT, main_kb())
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(B(("✓ " if LANG == "en" else "") + "English", callback_data="lg:en"),
               B(("✓ " if LANG == "fa" else "") + "فارسی", callback_data="lg:fa"))
        kb.add(B("🔙 منو", callback_data="m"))
        return edit(msg, "🌍 <b>Language / زبان</b>", kb)
    if act == "al":
        s = settings()
        s["alerts"] = not s.get("alerts", True)
        _write(SETF, s)
        return edit(msg, MENU_TXT, main_kb())
    if act == "pl":
        return show_panels(chat, msg)
    if act[:2] == "CH":
        return ch_route(act, a, msg, chat)
    if act == "ao":
        return ask_url(chat)
    if act[:1] == "M":
        return mig_route(act, a, msg, chat)
    if act[:1] == "G":
        return grp_route(act, a, msg, chat)
    if act == "ov":
        return overview(msg)
    if act == "crand":
        if ST.get(chat, {}).get("step") == "c_user":
            ST[chat]["username"] = "u" + uuid.uuid4().hex[:7]
            ask_gb(chat)
        return
    if act == "cg":
        if ST.get(chat, {}).get("step") != "c_group":
            return
        g = a[1]
        gids = ST[chat]["groups"] if g == "all" else ([] if g == "none" else [int(g) if g.isdigit() else g])
        return do_create(chat, gids)

    p = get_panel(a[1]) if len(a) > 1 else None
    if not p:
        return show_panels(chat, msg)
    pid = p["id"]
    name = a[2] if len(a) > 2 else None

    if act == "p":
        edit(msg, "⏳ در حال دریافت اطلاعات...")
        tokens.pop(pid, None)
        text, c = panel_home(p)
        edit(msg, text, panel_kb(p, c))
    elif act == "L":
        LAST[chat] = (a[2], int(a[3]))
        text, kb = list_view(p, a[2], int(a[3]))
        edit(msg, text, kb)
    elif act == "LB":
        k, pg = LAST.get(chat, (None, 0))
        if k:
            text, kb = list_view(p, k, pg)
            edit(msg, text, kb)
        else:
            text, c = panel_home(p)
            edit(msg, text, panel_kb(p, c))
    elif act == "U":
        text, kb = user_view(p, name)
        edit(msg, text, kb)
    elif act == "T":
        x = uinfo(u_get(p, name))
        u_modify(p, name, {"status": "active" if x["st"] == "disabled" else "disabled"})
        text, kb = user_view(p, name)
        edit(msg, text, kb)
    elif act in ("Zr", "Zv", "Zd"):
        what = {"Zr": "ریست مصرف", "Zv": "ریوک ساب (لینک قبلی از کار می‌افتد)", "Zd": f"حذف (به سطل زباله می‌رود و تا {TRASH_DAYS} روز قابل بازگردانی است)"}[act]
        kb = types.InlineKeyboardMarkup()
        kb.add(B("✅ بله", callback_data="Y" + act[1] + f":{pid}:{name}"),
               B("❌ نه", callback_data=f"U:{pid}:{name}"))
        edit(msg, f"⚠️ {what} برای <code>{esc(name)}</code> انجام شود؟", kb)
    elif act in ("Yr", "Yv", "Yd"):
        if act == "Yr":
            u_reset(p, name)
        elif act == "Yv":
            u_revoke(p, name)
        else:
            u_delete(p, name)
            kb = types.InlineKeyboardMarkup()
            kb.add(B("↩️ بازگردانی", callback_data=f"TRR:{pid}:{name}"))
            kb.add(B("🔙 برگشت", callback_data=f"LB:{pid}"))
            edit(msg, f"🗑 <code>{esc(name)}</code> حذف شد و به سطل زباله رفت.\nتا {TRASH_DAYS} روز می‌توانی بازگردانی کنی.", kb)
            return
        text, kb = user_view(p, name)
        edit(msg, "✅ انجام شد\n\n" + text, kb)
    elif act == "AV":
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(*[B(f"+{g}GB", callback_data=f"av:{pid}:{name}:{g}") for g in (5, 10, 20, 50, 100)])
        kb.add(B("✍️ عدد دلخواه", callback_data=f"avc:{pid}:{name}"), B("🔙 برگشت", callback_data=f"U:{pid}:{name}"))
        edit(msg, f"➕ چند گیگ به <code>{esc(name)}</code> اضافه شود؟", kb)
    elif act == "av":
        u_modify(p, name, body_volume(uinfo(u_get(p, name)), float(a[3])))
        text, kb = user_view(p, name)
        edit(msg, "✅ حجم اضافه شد\n\n" + text, kb)
    elif act == "avc":
        ST[chat] = {"step": "cust_av", "pid": pid, "user": name}
        prompt(chat, "✍️ مقدار حجم (گیگ) را بفرست:")
    elif act == "ED":
        kb = types.InlineKeyboardMarkup(row_width=3)
        kb.add(*[B(f"+{d} روز", callback_data=f"ed:{pid}:{name}:{d}") for d in (7, 30, 60, 90, 180)])
        kb.add(B("✍️ عدد دلخواه", callback_data=f"edc:{pid}:{name}"), B("🔙 برگشت", callback_data=f"U:{pid}:{name}"))
        edit(msg, f"📅 چند روز به <code>{esc(name)}</code> اضافه شود؟", kb)
    elif act == "ed":
        u_modify(p, name, body_extend(uinfo(u_get(p, name)), float(a[3])))
        text, kb = user_view(p, name)
        edit(msg, "✅ تمدید شد\n\n" + text, kb)
    elif act == "edc":
        ST[chat] = {"step": "cust_ed", "pid": pid, "user": name}
        prompt(chat, "✍️ تعداد روز را بفرست:")
    elif act == "NT":
        ST[chat] = {"step": "note", "pid": pid, "user": name}
        prompt(chat, "📝 متن یادداشت را بفرست:")
    elif act == "SL":
        link = sub_link(p, u_get(p, name))
        bot.send_message(chat, f"🔗 لینک ساب <b>{esc(name)}</b>:\n<code>{esc(link or 'موجود نیست')}</code>")
    elif act == "SR":
        ST[chat] = {"step": "search", "pid": pid}
        prompt(chat, "🔍 بخشی از نام کاربری را بفرست:")
    elif act == "CU":
        ST[chat] = {"step": "c_user", "pid": pid}
        prompt(chat, "➕ <b>نام کاربری</b> جدید را بفرست:", B("🎲 نام تصادفی", callback_data="crand"))
    elif act == "BK":
        xs = X(p)
        kb = types.InlineKeyboardMarkup(row_width=1)
        for k, (label, kind, op, arg) in BULK.items():
            n = sum(1 for x in xs if FILT[kind][1](x))
            kb.add(B(f"{label} ({n})", callback_data=f"B:{pid}:{k}"))
        kb.add(B("🔙 پنل", callback_data=f"p:{pid}"))
        edit(msg, "🛠 <b>عملیات گروهی</b>\nقبل از اجرا تأیید می‌گیرم:", kb)
    elif act == "B":
        label, kind, op, arg = BULK[name]
        n = sum(1 for x in X(p) if FILT[kind][1](x))
        kb = types.InlineKeyboardMarkup()
        kb.add(B("✅ اجرا", callback_data=f"BC:{pid}:{name}"), B("❌ لغو", callback_data=f"BK:{pid}"))
        note = "\n🗑 کاربران حذف‌شده به سطل زباله می‌روند." if op == "del" else ""
        edit(msg, f"⚠️ <b>{label}</b>\nروی <b>{n}</b> کاربر اجرا می‌شود. مطمئنی؟{note}", kb)
    elif act == "BC":
        label, kind, op, arg = BULK[name]
        targets = [x for x in X(p, True) if FILT[kind][1](x)]
        edit(msg, f"⏳ در حال اجرا روی {len(targets)} کاربر...")
        ok, fail, err = 0, 0, ""
        for x in targets:
            try:
                apply_op(p, x, op, arg)
                ok += 1
            except Exception as e:
                fail += 1
                err = err or str(e)[:150]
        CACHE.pop(pid, None)
        edit(msg, f"✅ <b>{label}</b>\nموفق: {ok} | ناموفق: {fail}" + (f"\n<code>{esc(err)}</code>" if err else ""),
             back_kb(f"BK:{pid}", "🔙 عملیات گروهی"))
    elif act == "ND":
        d, nerr = None, ""
        for npath in ("/api/nodes", "/api/node"):
            try:
                d = req(p, "GET", npath)
                break
            except Exception as e:
                if "405" not in str(e):
                    nerr = (nerr + "\n" + npath + ": " + str(e)[:200]).strip()
        if d is None:
            return edit(msg, "🛰 نودها دریافت نشد.\n\n<b>پاسخ پنل:</b>\n<code>" + esc(nerr or "هر دو آدرس /api/nodes و /api/node خطای 405 دادند") + "</code>",
                        back_kb(f"p:{pid}", "🔙 پنل"))
        nl = d.get("nodes", []) if isinstance(d, dict) else (d or [])
        out = [f"🛰 <b>نودها ({len(nl)})</b>\n"]
        for n in nl[:30]:
            usage = n.get("uplink", 0) + n.get("downlink", 0) if isinstance(n.get("uplink"), (int, float)) else None
            out.append(f"▫️ <b>{esc(n.get('name', '?'))}</b> — <code>{esc(n.get('status', '?'))}</code>"
                       + (f" — {fmt_bytes(usage)}" if usage else "")
                       + (f"\n   <code>{esc(n['address'])}</code>" if n.get("address") else ""))
        edit(msg, "\n".join(out) if nl else "🛰 نودی پیدا نشد / دسترسی ندارد.", back_kb(f"p:{pid}", "🔙 پنل"))
    elif act == "AD":
        d, aerr = None, ""
        try:
            d = req(p, "GET", "/api/admins")
        except Exception as e:
            aerr = str(e)[:250]
        if d is None:
            return edit(msg, "👑 ادمین‌ها دریافت نشد.\n\n<b>پاسخ پنل:</b>\n<code>" + esc(aerr) + "</code>",
                        back_kb(f"p:{pid}", "🔙 پنل"))
        al = d.get("admins", []) if isinstance(d, dict) else (d or [])
        out = [f"👑 <b>ادمین‌ها ({len(al)})</b>\n"]
        for ad in al[:30]:
            tr = ad.get("used_traffic") or ad.get("users_usage")
            out.append(f"▫️ <b>{esc(ad.get('username', '?'))}</b>" + (" 👑" if ad.get("is_sudo") else "")
                       + (f" — {fmt_bytes(tr)}" if tr else ""))
        edit(msg, "\n".join(out) if al else "👑 دسترسی به لیست ادمین‌ها ندارید.", back_kb(f"p:{pid}", "🔙 پنل"))
    elif act == "BM":
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(B("📝 بکاپ متنی", callback_data=f"BT:{pid}"),
               B("📦 بکاپ کلی (فایل کامل پنل)", callback_data=f"BF:{pid}"),
               B("👥 خروجی کاربران (JSON/CSV)", callback_data=f"EX:{pid}"),
               B("🔙 پنل", callback_data=f"p:{pid}"))
        edit(msg, "💾 <b>بکاپ</b>\nیکی را انتخاب کن:", kb)
    elif act == "BT":
        edit(msg, "📝 <b>بکاپ متنی</b>\n\nاین بخش فعلاً غیرفعال است و بعداً فعال می‌شود.",
             back_kb(f"BM:{pid}", "🔙 بکاپ"))
    elif act == "BF":
        edit(msg, "⏳ در حال ساخت بکاپ کلی... (بسته به تعداد کاربر ممکن است کمی طول بکشد)")
        full_backup(p, chat)
        edit(msg, "✅ بکاپ کلی ارسال شد.", back_kb(f"BM:{pid}", "🔙 بکاپ"))
    elif act == "EX":
        edit(msg, "⏳ در حال ساخت خروجی کاربران...")
        export(p, chat)
        edit(msg, "✅ ارسال شد.", back_kb(f"BM:{pid}", "🔙 بکاپ"))
    elif act == "TR":
        items = trash_list(pid)
        out = [f"🗑 <b>سطل زباله</b> ({len(items)})\nکاربرانی که با ربات حذف شده‌اند تا {TRASH_DAYS} روز قابل بازگردانی‌اند.\n"]
        kb = types.InlineKeyboardMarkup(row_width=1)
        for t in items[:30]:
            left = TRASH_DAYS - (time.time() - t["at"]) / 86400
            out.append(f"▫️ <code>{esc(t['name'])}</code> — حذف: {fdate(t['at'])[:10]} — {max(1, int(left) + 1)} روز مانده")
            kb.add(B(f"↩️ بازگردانی {t['name']}"[:40], callback_data=f"TRR:{pid}:{t['name']}"))
        if items:
            kb.add(B("🧹 خالی کردن سطل", callback_data=f"TRE:{pid}"))
        kb.add(B("🔙 پنل", callback_data=f"p:{pid}"))
        edit(msg, "\n".join(out) if items else "🗑 <b>سطل زباله</b> خالی است.", kb)
    elif act == "TRR":
        trash_restore(p, name)
        text, kb = user_view(p, name)
        edit(msg, "✅ کاربر بازگردانی شد (مصرف قبلی قابل بازگردانی نیست؛ حجم باقی‌مانده تنظیم شده)\n\n" + text, kb)
    elif act == "TRE":
        kb = types.InlineKeyboardMarkup()
        kb.add(B("✅ بله، خالی شود", callback_data=f"TREC:{pid}"), B("❌ نه", callback_data=f"TR:{pid}"))
        edit(msg, "⚠️ همه کاربران سطل زباله برای همیشه پاک شوند؟", kb)
    elif act == "TREC":
        trash_remove(pid)
        edit(msg, "🧹 سطل زباله خالی شد.", back_kb(f"p:{pid}", "🔙 پنل"))
    elif act == "PD":
        kb = types.InlineKeyboardMarkup()
        kb.add(B("✅ بله، حذف شود", callback_data=f"PDC:{pid}"), B("❌ نه", callback_data=f"p:{pid}"))
        edit(msg, "⚠️ پنل از ربات حذف شود؟ (از خود پنل چیزی پاک نمی‌شود)", kb)
    elif act == "PDC":
        save([x for x in load() if x["id"] != pid])
        trash_remove(pid)
        tokens.pop(pid, None)
        CACHE.pop(pid, None)
        if load():
            show_panels(chat, msg)
        else:
            edit(msg, "🗑 حذف شد. پنلی ثبت نشده.", back_kb("pl", "➕ افزودن پنل"))


@bot.callback_query_handler(func=lambda c: c.from_user.id == OWNER)
def cb(c):
    try:
        bot.answer_callback_query(c.id)
    except Exception:
        pass
    try:
        route(c.data.split(":")[0], c.data.split(":"), c.message, c.message.chat.id)
    except Exception as e:
        try:
            bot.send_message(c.message.chat.id, f"⚠️ خطا: <code>{esc(e)}</code>")
        except Exception:
            pass


# ================= auto alerts =================
def alert_loop():
    sent = set()
    time.sleep(60)
    while True:
        try:
            trash_all()
            if settings().get("alerts", True):
                today = datetime.date.today().isoformat()
                sent = {k for k in sent if k[-1] == today}
                for p in load():
                    try:
                        xs = X(p, True)
                    except Exception as e:
                        k = (p["id"], "down", today)
                        if k not in sent:
                            sent.add(k)
                            bot.send_message(OWNER, f"🚨 پنل <b>{esc(host(p))}</b> در دسترس نیست:\n<code>{esc(e)[:200]}</code>")
                        continue
                    groups = [
                        ("📉 نزدیک اتمام حجم (۹۰٪+)", "near",
                         [x for x in xs if x["st"] == "active" and x["lim"] and x["ratio"] >= 0.9]),
                        ("⏰ انقضا تا ۲ روز آینده", "soon",
                         [x for x in xs if x["exp"] and not x["expired"] and 0 < x["exp"] - time.time() <= 2 * 86400]),
                    ]
                    for title, kind, items in groups:
                        new = [x for x in items if (p["id"], kind, x["name"], today) not in sent]
                        if not new:
                            continue
                        for x in new:
                            sent.add((p["id"], kind, x["name"], today))
                        body = "\n".join(line(i, x, kind) for i, x in enumerate(new[:15], 1))
                        more = f"\n… و {len(new) - 15} مورد دیگر" if len(new) > 15 else ""
                        bot.send_message(OWNER, f"🔔 <b>{esc(host(p))}</b>\n{title}: {len(new)}\n\n{body}{more}")
        except Exception:
            pass
        time.sleep(1800)


if __name__ == "__main__":
    threading.Thread(target=alert_loop, daemon=True).start()
    threading.Thread(target=snapshot_loop, daemon=True).start()
    print("Bot is running...")
    bot.infinity_polling(skip_pending=True, timeout=30)
