# Premium OTP Bot with Admin Panel, Emoji Flags, aiogram
# Render 24/7 Compatible Version

import requests
from bs4 import BeautifulSoup
import time
import re
import sys
import signal
import sqlite3
import os
import threading
import hashlib
import queue
import json
import phonenumbers
from phonenumbers import region_code_for_number
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    Message, CallbackQuery
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import asyncio
from flask import Flask
from threading import Thread

# ============================================================
#  FLASK KEEP ALIVE (For 24/7 UptimeRobot Ping)
# ============================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ SPEEDX OTP Bot is Running!"

@app.route('/health')
def health():
    return {"status": "alive", "timestamp": datetime.now().isoformat()}

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

def keep_alive():
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("[*] Keep-alive server started on port", os.environ.get("PORT", 10000))

# ============================================================
#  ENVIRONMENT CONFIGURATION (Render Compatible)
# ============================================================
BOT_NAME = "OTP Bot"
USERNAME = os.getenv("API_USERNAME", "faysal91")
PASSWORD = os.getenv("API_PASSWORD", "faysal91")

# Database path (Render persistent disk or local)
DB_FILE = os.getenv("DB_FILE", "sms_database_np.db")

# Telegram Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8674187481:AAFgQ_5zlcy7TzA9WcfogNYFCcLp0-UarYg")
DM_CHAT_ID = os.getenv("DM_CHAT_ID", "7304865708")

# Admin IDs
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "7304865708")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip()]

# Group Chat IDs (comma separated in env var)
GROUP_CHAT_IDS_STR = os.getenv("GROUP_CHAT_IDS", "-1003008351067")
GROUP_CHAT_IDS = [x.strip() for x in GROUP_CHAT_IDS_STR.split(",") if x.strip()]

# Channel URLs
CHANNEL_1 = os.getenv("CHANNEL_1", "https://t.me/your_number_channel")
CHANNEL_2 = os.getenv("CHANNEL_2", "https://t.me/your_otp_channel")

# Footer Emoji IDs
LEFT_FOOTER_EMOJI_ID = os.getenv("LEFT_FOOTER_EMOJI_ID", "6010280017437661523")
RIGHT_FOOTER_EMOJI_ID = os.getenv("RIGHT_FOOTER_EMOJI_ID", "5888704237910627502")

# Profile URL
FAYSAL_PROFILE_URL = os.getenv("FAYSAL_PROFILE_URL", "https://t.me/mdfarukofficial22")

# API Endpoints
BASE_URL = os.getenv("BASE_URL", "http://91.232.105.47/ints")
DOMAIN_URL = os.getenv("DOMAIN_URL", "http://217.182.195.194")
LOGIN_PAGE_URL = f"{BASE_URL}/"
SMS_HTML_PAGE_URL = f"{BASE_URL}/agent/SMSCDRReports"

POTENTIAL_API_URLS = [
    f"{BASE_URL}/agent/res/data_smscdr.php",
    f"{DOMAIN_URL}/res/data_smscdr.php",
    f"{BASE_URL}/res/data_smscdr.php",
]

# ============================================================
#  EMOJI DATA
# ============================================================
EMOJI_DATA_FILE = os.path.join(os.path.dirname(__file__), "emoji_data.json")
SERVICE_EMOJIS: dict = {}
COUNTRY_EMOJIS: dict = {}

def load_emoji_data():
    global SERVICE_EMOJIS, COUNTRY_EMOJIS
    try:
        with open(EMOJI_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        SERVICE_EMOJIS = data.get("service_emojis", {})
        COUNTRY_EMOJIS = data.get("country_emojis", {})
        print(f"[*] Loaded {len(SERVICE_EMOJIS)} service emojis, {len(COUNTRY_EMOJIS)} country emojis")
    except FileNotFoundError:
        print(f"[!] {EMOJI_DATA_FILE} not found, using defaults")
        SERVICE_EMOJIS = {
            "whatsapp": "5334998226636390258",
            "telegram": "5330237710655306682",
            "facebook": "5323261730283863478",
            "tiktok": "5327982530702359565",
            "instagram": "5319160079465857105"
        }
        COUNTRY_EMOJIS = {}

def save_emoji_data():
    data = {"service_emojis": SERVICE_EMOJIS, "country_emojis": COUNTRY_EMOJIS}
    with open(EMOJI_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

load_emoji_data()

# Region mapping
REGION_TO_COUNTRY_KEY = {
    "AF": "afganistan", "AO": "angola", "BJ": "benin", "BO": "bolivia",
    "BF": "burkina faso", "BI": "burundi", "KH": "cambodia", "CF": "central africa",
    "CM": "cameroon", "EG": "egypt", "ET": "ethiopia", "GE": "georgia",
    "GT": "guatemala", "GN": "guinea", "GW": "guinea-bissau", "HT": "haiti",
    "HN": "honduras", "HU": "hungary", "IR": "iran", "IQ": "iraq",
    "IT": "italy", "CI": "cote d'ivoire", "LB": "lebanon", "LY": "libya",
    "MG": "madagascar", "ML": "mali", "GH": "ghana", "TZ": "tanzania",
    "TL": "timor-leste", "YE": "yemen",
}

# Global state
db_connection = None
stop_event = threading.Event()
reported_sms_hashes_cache = set()
working_api_url = None

# aiogram setup
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
bot: Bot = None

# ============================================================
#  FSM STATES
# ============================================================
class AdminStates(StatesGroup):
    waiting_service_emoji = State()
    waiting_country_emoji = State()

# ============================================================
#  HELPERS
# ============================================================
def get_custom_emoji_tag(emoji_id: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">⭐</tg-emoji>'

def detect_country_and_service(phone: str, message: str):
    region_code = "XX"
    country_emoji = None

    clean = re.sub(r"[^\d+]", "", phone)
    if not clean.startswith("+"):
        clean = "+" + clean

    try:
        parsed = phonenumbers.parse(clean, None)
        region_code = region_code_for_number(parsed)
        country_key = REGION_TO_COUNTRY_KEY.get(region_code)
        if country_key:
            eid = COUNTRY_EMOJIS.get(country_key)
            if eid:
                country_emoji = get_custom_emoji_tag(eid)
    except Exception as e:
        pass

    service_emoji = None
    msg_lower = message.lower()
    service_map = {
        "whatsapp": ["whatsapp"],
        "telegram": ["telegram"],
        "facebook": ["facebook", "fb"],
        "tiktok": ["tiktok", "tik tok"],
        "instagram": ["instagram", "insta"],
    }
    for svc, keywords in service_map.items():
        if any(kw in msg_lower for kw in keywords):
            eid = SERVICE_EMOJIS.get(svc)
            if eid:
                service_emoji = get_custom_emoji_tag(eid)
            break

    return region_code, service_emoji, country_emoji

def mask_phone_number(phone_number: str) -> str:
    clean = phone_number.replace("+", "").strip()
    if len(clean) <= 8:
        return f"+{clean}"
    suffix = clean[-4:]
    prefix = clean[:-8]
    return f"+{prefix}SPEEDX{suffix}"

def build_message_and_keyboard(recipient_number: str, sender_name: str,
                                message: str, otp: str, sms_time: str):
    masked = mask_phone_number(recipient_number)
    region_code, service_emoji, country_emoji = detect_country_and_service(
        recipient_number, message
    )

    left_emoji = get_custom_emoji_tag(LEFT_FOOTER_EMOJI_ID)
    right_emoji = get_custom_emoji_tag(RIGHT_FOOTER_EMOJI_ID)

    flag_part = f"{country_emoji}" if country_emoji else "🌐"
    country_tag = f"#<b>{region_code}</b>" if region_code != "XX" else ""
    service_part = f"  {service_emoji}" if service_emoji else ""

    text = (
        f"{flag_part}  {country_tag}{service_part}   {masked}\n\n"
        f"{left_emoji} POWERED BY <a href=\"{FAYSAL_PROFILE_URL}\"><b>FAYSAL</b></a> {right_emoji}"
    )

    # Build keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"🔑  {otp}",
                callback_data=f"copy_otp:{otp}"
            )
        ],
        [
            InlineKeyboardButton(text="🤖 𝐍𝐔𝐌𝐁𝐄𝐑", url=CHANNEL_1),
            InlineKeyboardButton(text="📭 𝐂𝐇𝐀𝐍𝐍𝐄𝐋", url=CHANNEL_2)
        ]
    ])

    return text, keyboard

# ============================================================
#  ADMIN PANEL
# ============================================================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Service Emoji", callback_data="admin_add_service")],
        [InlineKeyboardButton(text="🌍 Add Country Emoji", callback_data="admin_add_country")],
        [InlineKeyboardButton(text="📊 Bot Status", callback_data="admin_status")],
    ])

@dp.message(Command("start"))
async def cmd_start(msg: Message):
    if is_admin(msg.from_user.id):
        await msg.answer(
            "👑 <b>Admin Panel</b>\nWhat do you want to do?",
            parse_mode="HTML",
            reply_markup=admin_main_keyboard()
        )
    else:
        await msg.answer("👋 OTP Bot is running.")

@dp.message(Command("admin"))
async def cmd_admin(msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.answer("❌ You are not authorized!")
        return
    await msg.answer(
        "👑 <b>Admin Panel</b>\nWhat do you want to do?",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard()
    )

@dp.callback_query(lambda c: c.data == "admin_add_service")
async def cb_add_service(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized!", show_alert=True)
        return
    await call.message.answer(
        "💠 <b>Send Service Name and Emoji ID:</b>\n"
        "<code>ServiceName=EmojiID</code>\n\n"
        "Example: <code>whatsapp=5334998226636390258</code>",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_service_emoji)
    await call.answer()

@dp.callback_query(lambda c: c.data == "admin_add_country")
async def cb_add_country(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized!", show_alert=True)
        return
    await call.message.answer(
        "💠 <b>Send Country Name and Emoji ID:</b>\n"
        "<code>CountryName=EmojiID</code>\n\n"
        "Example: <code>Germany=5221656175445424141</code>",
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_country_emoji)
    await call.answer()

@dp.callback_query(lambda c: c.data == "admin_status")
async def cb_status(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized!", show_alert=True)
        return
    
    status_text = (
        f"📊 <b>Bot Status</b>\n\n"
        f"🟢 Database: {'Connected' if db_connection else 'Disconnected'}\n"
        f"📱 Groups: {len(GROUP_CHAT_IDS)}\n"
        f"👮 Admins: {len(ADMIN_IDS)}\n"
        f"🎨 Services: {len(SERVICE_EMOJIS)}\n"
        f"🌍 Countries: {len(COUNTRY_EMOJIS)}\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await call.message.answer(status_text, parse_mode="HTML")
    await call.answer()

@dp.message(AdminStates.waiting_service_emoji)
async def handle_service_emoji_input(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    text = msg.text.strip() if msg.text else ""
    if "=" not in text:
        await msg.answer("❌ Wrong format. Use: <code>ServiceName=EmojiID</code>", parse_mode="HTML")
        return
    name, emoji_id = text.split("=", 1)
    name = name.strip().lower()
    emoji_id = emoji_id.strip()
    if not name or not emoji_id.isdigit():
        await msg.answer("❌ Invalid. Name must be text, EmojiID must be digits only.")
        return
    SERVICE_EMOJIS[name] = emoji_id
    save_emoji_data()
    await state.clear()
    await msg.answer(
        f"✅ Service emoji saved!\n<b>{name}</b> → <code>{emoji_id}</code>\n\n"
        f"Preview: <tg-emoji emoji-id=\"{emoji_id}\">⭐</tg-emoji>",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard()
    )

@dp.message(AdminStates.waiting_country_emoji)
async def handle_country_emoji_input(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    text = msg.text.strip() if msg.text else ""
    if "=" not in text:
        await msg.answer("❌ Wrong format. Use: <code>CountryName=EmojiID</code>", parse_mode="HTML")
        return
    name, emoji_id = text.split("=", 1)
    name = name.strip().lower()
    emoji_id = emoji_id.strip()
    if not name or not emoji_id.isdigit():
        await msg.answer("❌ Invalid. Name must be text, EmojiID must be digits only.")
        return
    COUNTRY_EMOJIS[name] = emoji_id
    save_emoji_data()
    await state.clear()
    await msg.answer(
        f"✅ Country emoji saved!\n<b>{name}</b> → <code>{emoji_id}</code>\n\n"
        f"Preview: <tg-emoji emoji-id=\"{emoji_id}\">⭐</tg-emoji>",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard()
    )

@dp.callback_query(lambda c: c.data.startswith("copy_otp:"))
async def cb_copy_otp(call: CallbackQuery):
    otp = call.data.split(":", 1)[1]
    await call.answer(f"OTP: {otp}", show_alert=True)

# ============================================================
#  TELEGRAM SENDER
# ============================================================
def _keyboard_to_reply_markup(keyboard: InlineKeyboardMarkup) -> dict:
    rows = []
    for row in keyboard.inline_keyboard:
        btn_row = []
        for btn in row:
            b: dict = {"text": btn.text}
            if btn.url:
                b["url"] = btn.url
            elif btn.callback_data:
                b["callback_data"] = btn.callback_data
            btn_row.append(b)
        rows.append(btn_row)
    return {"inline_keyboard": rows}

class TelegramSender:
    def __init__(self, stop_signal: threading.Event):
        self.queue = queue.Queue()
        self.stop_event = stop_signal
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self._session = requests.Session()

    def start(self):
        self.thread.start()
        print("[*] Telegram Sender thread started.")

    def _worker(self):
        while not self.stop_event.is_set():
            try:
                item = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            chat_id, text, keyboard, sms_hash = item
            success = self._send(chat_id, text, keyboard)
            if success:
                add_sms_to_reported_db(sms_hash)
            self.queue.task_done()

    def _send(self, chat_id: str, text: str, keyboard: InlineKeyboardMarkup) -> bool:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": _keyboard_to_reply_markup(keyboard),
        }
        try:
            r = self._session.post(url, json=payload, timeout=20)
            if not r.ok:
                print(f"[!] Telegram send error ({chat_id}): {r.status_code} {r.text[:200]}")
                return False
            return True
        except Exception as e:
            print(f"[!] Telegram send error ({chat_id}): {e}")
            return False

    def queue_message(self, chat_id: str, text: str, keyboard: InlineKeyboardMarkup, sms_hash: str):
        self.queue.put((chat_id, text, keyboard, sms_hash))

telegram_sender = TelegramSender(stop_event)

# ============================================================
#  DATABASE
# ============================================================
def setup_database() -> bool:
    global db_connection, reported_sms_hashes_cache
    try:
        # Ensure directory exists
        db_dir = os.path.dirname(DB_FILE)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            
        db_connection = sqlite3.connect(DB_FILE, check_same_thread=False)
        cursor = db_connection.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS reported_sms (hash TEXT PRIMARY KEY)")
        reported_sms_hashes_cache = {
            row[0] for row in cursor.execute("SELECT hash FROM reported_sms")
        }
        db_connection.commit()
        print(f"[*] Database connected. Loaded {len(reported_sms_hashes_cache)} hashes.")
        return True
    except sqlite3.Error as e:
        print(f"[!!!] DATABASE ERROR: {e}")
        return False

def add_sms_to_reported_db(sms_hash: str):
    try:
        with db_connection:
            db_connection.execute("INSERT INTO reported_sms (hash) VALUES (?)", (sms_hash,))
    except sqlite3.Error:
        pass

# ============================================================
#  UTILITY
# ============================================================
def send_operational_message(chat_id: str, text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
    except Exception:
        pass

def graceful_shutdown(signum, frame):
    print("\n[!!!] Shutdown signal. Stopping...")
    stop_event.set()
    time.sleep(1)
    if db_connection:
        db_connection.close()
    sys.exit(0)

def solve_math_captcha(captcha_text: str):
    m = re.search(r"(\d+)\s*([+*])\s*(\d+)", captcha_text)
    if not m:
        return None
    n1, op, n2 = int(m.group(1)), m.group(2), int(m.group(3))
    result = n1 + n2 if op == "+" else n1 * n2
    print(f"[*] Captcha solved: {n1} {op} {n2} = {result}")
    return result

# ============================================================
#  SMS WATCHER
# ============================================================
def start_watching_sms(session: requests.Session, destination_chat_ids: list):
    global working_api_url
    polling_interval = int(os.getenv("POLLING_INTERVAL", "5"))  # seconds

    print(f"[SUCCESS] Watching SMS → {len(destination_chat_ids)} group(s).")
    print(f"[*] Polling interval: {polling_interval}s")

    while not stop_event.is_set():
        try:
            print(f"[*] Fetching SMS... ({time.strftime('%H:%M:%S')})")

            if not working_api_url:
                for url in POTENTIAL_API_URLS:
                    try:
                        r = session.get(url, timeout=20, params={"sEcho": "1"})
                        if r.status_code != 404:
                            print(f"[SUCCESS] API URL: {url}")
                            working_api_url = url
                            break
                    except requests.exceptions.RequestException:
                        pass
                if not working_api_url:
                    print("[!!!] No working API URL found. Retrying in 60s...")
                    time.sleep(60)
                    continue

            now = datetime.now()
            params = {
                "fdate1": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                "fdate2": now.strftime("%Y-%m-%d %H:%M:%S"),
            }
            headers = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": SMS_HTML_PAGE_URL,
            }
            resp = session.get(working_api_url, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            json_data = resp.json()

            if "aaData" not in json_data or not isinstance(json_data["aaData"], list):
                print("[!] Unexpected API response format.")
                time.sleep(polling_interval)
                continue

            new_sms_count = 0
            for sms in reversed(json_data["aaData"]):
                if len(sms) <= 5:
                    continue
                dt = str(sms[0])
                rc = str(sms[2])
                sn = str(sms[3])
                msg = str(sms[5])

                if not msg or not rc or rc.strip() == "0" or len(rc.strip()) < 6:
                    continue

                h = hashlib.md5(f"{dt}-{rc}-{msg}".encode()).hexdigest()
                if h in reported_sms_hashes_cache:
                    continue

                reported_sms_hashes_cache.add(h)
                new_sms_count += 1
                print(f"    [+] New SMS for: {rc}")

                otp_match = re.search(r"\b(\d{3}[-\s]\d{3})\b|\b(\d{4,8})\b", msg)
                otp = (
                    otp_match.group(0).replace(" ", "").replace("-", "")
                    if otp_match else "N/A"
                )

                text, keyboard = build_message_and_keyboard(rc, sn, msg, otp, dt)

                for chat_id in destination_chat_ids:
                    telegram_sender.queue_message(chat_id, text, keyboard, h)

            if new_sms_count > 0:
                print(f"[*] Processed {new_sms_count} new SMS")

            time.sleep(polling_interval)

        except requests.exceptions.RequestException as e:
            print(f"[!] Network error: {e}. Retry in 30s...")
            time.sleep(30)
        except Exception as e:
            print(f"[!!!] Critical error: {e}")
            time.sleep(30)

# ============================================================
#  MAIN
# ============================================================
async def run_bot():
    global bot
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await dp.start_polling(bot)

def main():
    # Start keep-alive server first
    keep_alive()
    
    signal.signal(signal.SIGINT, graceful_shutdown)

    print("=" * 60)
    print("--- SPEEDX OTP Bot (Render 24/7 Edition) ---")
    print("=" * 60)
    print(f"[*] Version: 2.0")
    print(f"[*] Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not setup_database():
        print("[!!!] Database setup failed. Exiting.")
        return

    # Start aiogram bot in separate thread
    def _bot_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_bot())
        except Exception as e:
            print(f"[!] Bot thread error: {e}")

    threading.Thread(target=_bot_thread, daemon=True).start()
    print("[*] Admin panel bot started.")

    try:
        with requests.Session() as session:
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/114.0.0.0 Safari/537.36"
                )
            })

            print("\n[*] Step 1: Logging in...")
            r = session.get(LOGIN_PAGE_URL, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            form = soup.find("form")
            if not form:
                raise Exception("Login form not found.")

            post_url = form.get("action", "")
            if not post_url.startswith("http"):
                post_url = f"{BASE_URL}/{post_url.lstrip('/')}"

            payload = {}
            for tag in form.find_all("input"):
                n = tag.get("name")
                v = tag.get("value", "")
                p = tag.get("placeholder", "").lower()
                if not n:
                    continue
                if "user" in p:
                    payload[n] = USERNAME
                elif "pass" in p:
                    payload[n] = PASSWORD
                elif "ans" in p:
                    el = soup.find(string=re.compile(r"What is \d+ \s*[+*]\s* \d+"))
                    if not el:
                        raise Exception("Captcha text not found.")
                    payload[n] = solve_math_captcha(el)
                else:
                    payload[n] = v

            r = session.post(post_url, data=payload, headers={"Referer": LOGIN_PAGE_URL})

            if "dashboard" in r.url.lower() or "Logout" in r.text:
                print("[SUCCESS] Logged in!")
                telegram_sender.start()
                send_operational_message(
                    DM_CHAT_ID,
                    "✅ *SPEEDX OTP Bot Started*\\n\\n"
                    f"🟢 Status: Online\\n"
                    f"📊 Groups: {len(GROUP_CHAT_IDS)}\\n"
                    f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                start_watching_sms(session, GROUP_CHAT_IDS)
            else:
                print("[!!!] Authentication failed.")
                send_operational_message(DM_CHAT_ID, "❌ *Bot Failed to Login*")

    except Exception as e:
        print(f"[!!!] Startup error: {e}")
        send_operational_message(DM_CHAT_ID, f"❌ *Bot Error:* `{str(e)[:100]}`")

if __name__ == "__main__":
    main()