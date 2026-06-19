import os
import json
import time
import subprocess
import re
import threading
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- Configuration (ဒီနေရာမှာ ရာနှုန်းပြည့် မှန်ကန်အောင် ပြင်ဆင်ထားပါတယ်) ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8840868848:AAGdJEYmfQ1yk-Qyi8OfVqUWQKLH3WMRlr0")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5536833682"))

DB_FILE = "users_db.json"

# --- 🛡️ SECURITY FILTER FOR RAILWAY ---
DANGEROUS_KEYWORDS = [
    r"os\.system", r"subprocess\.", r"pty\.", r"shutil\.", r"open\(.*w.*?\)", r"open\(.*a.*?\)",
    r"chpasswd", r"useradd", r"usermod", r"passwd", r"rm\s+-", r"chmod", r"chown",
    r"socket", r"requests", r"urllib", r"builtins", r"eval\(", r"exec\(", r"__import__"
]

running_processes = {}

# --- Database Functions ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

def save_db(db):
    with open(DB_FILE, "w") as f: json.dump(db, f, indent=4)

def check_user_status(user_id, db):
    uid = str(user_id)
    now = time.time()
    if user_id == ADMIN_ID: return {"role": "admin", "expire_at": 0, "free_used_today": 0}
    if uid not in db:
        db[uid] = {"role": "free", "expire_at": 0, "free_used_today": 0, "last_free_reset": now}
        save_db(db)
    user = db[uid]
    if user.get("role") == "free" and (now - user.get("last_free_reset", 0)) >= 86400:
        user["free_used_today"] = 0
        user["last_free_reset"] = now
        save_db(db)
    if user.get("role") in ["vip", "premium"] and now > user.get("expire_at", 0):
        user["role"] = "free"; user["expire_at"] = 0; save_db(db)
    return user

def get_max_allowed_files(role):
    if role == "admin": return 999999
    if role == "premium": return 10
    if role == "vip": return 5
    return 1

def is_code_safe(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f: content = f.read()
        for pattern in DANGEROUS_KEYWORDS:
            if re.search(pattern, content, re.IGNORECASE): return False, pattern
        return True, None
    except: return False, "Cannot read file"

# --- 🛡️ BACKGROUND THREAD TIMER (Crash ဖြစ်စေတတ်သော Job Queue နေရာတွင် အစားထိုးသည်) ---
def start_background_timer(token):
    def loop_checker():
        bot_client = Bot(token=token)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            try:
                time.sleep(60) # ၁ မိနစ်တစ်ခါ စစ်ဆေးမည်
                db = load_db()
                now = time.time()
                for user_id, files in list(running_processes.items()):
                    uid = str(user_id)
                    if uid in db and db[uid].get("role") in ["admin", "vip", "premium"]: continue
                    user = db.setdefault(uid, {"role": "free", "expire_at": 0, "free_used_today": 0, "last_free_reset": now})
                    already_used = user.get("free_used_today", 0)
                    current_running_time = 0
                    for fpath, p_info in list(files.items()):
                        if p_info["process"].poll() is None:
                            current_running_time += (now - p_info["start_time"])
                    if (already_used + current_running_time) >= 18000:
                        for fpath, p_info in list(files.items()):
                            if p_info["process"].poll() is None:
                                try: p_info["process"].terminate(); p_info["process"].wait()
                                except: pass
                        user["free_used_today"] = 18000; save_db(db)
                        if user_id in running_processes: del running_processes[user_id]
                        try: loop.run_until_complete(bot_client.send_message(chat_id=int(user_id), text="⚠️ ယနေ့အတွက် Free ၅ နာရီ သုံးစွဲမှု ပြည့်သွားပါပြီ။ Script များကို စနစ်မှ ရပ်ဆိုင်းလိုက်ပါပြီ။"))
                        except: pass
            except: pass
    threading.Thread(target=loop_checker, daemon=True).start()

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; db = load_db(); user = check_user_status(user_id, db)
    role_text = str(user.get("role", "free")).upper()
    if user.get("role") == "admin": expire_text = "အကန့်အသတ်မရှိ (ADMIN)"
    elif user.get("role") == "free":
        already_used = user.get("free_used_today", 0); current_running_time = 0
        for fpath, p_info in list(running_processes.get(user_id, {}).items()):
            if p_info["process"].poll() is None: current_running_time += (time.time() - p_info["start_time"])
        left_seconds = max(0, 18000 - (already_used + current_running_time))
        expire_text = f"Free (ယနေ့ကျန်ရှိချိန်: {int(left_seconds // 3600)} နာရီ {int((left_seconds % 3600) // 60)} မိနစ်)"
    else: expire_text = datetime.fromtimestamp(user.get("expire_at", 0)).strftime('%Y-%m-%d %H:%M:%S')
    max_files = get_max_allowed_files(user.get("role"))
    await update.message.reply_text(f"👋 KRAW Bot Hosting မှ ကြိုဆိုပါတယ်။\n\n📊 သင့်အဆင့်: *{role_text}*\n⏳ သက်တမ်းကုန်ရက်: `{expire_text}`\n🚀 ပြိုင်တူ Run ခွင့်: `{max_files if max_files != 999999 else 'အကန့်အသတ်မရှိ'}`\n\nPython (.py) ဖိုင် တင်ပေးပါ။", parse_mode="Markdown")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; document = update.message.document; db = load_db(); user = check_user_status(user_id, db)
    if not document or not document.file_name: return
    if not document.file_name.endswith('.py'):
        await update.message.reply_text("❌ ကျေးဇူးပြု၍ Python (.py) ဖိုင်ကိုသာ ပို့ပေးပါ။"); return
    active_count = sum(1 for p in running_processes.get(user_id, {}).values() if p["process"].poll() is None)
    if active_count >= get_max_allowed_files(user.get("role")):
        await update.message.reply_text("⚠️ သင့်အဆင့်၏ Limit ပြည့်နေပါသည်။ အဟောင်းကို အရင်ရပ်ပေးပါ။"); return
    file_name = f"{user_id}_{int(time.time())}_{document.file_name}"
    file = await context.bot.get_file(document.file_id); await file.download_to_drive(file_name)
    full_path = os.path.abspath(file_name)
    
    if user_id == ADMIN_ID: is_safe, matched_pattern = True, None
    else: is_safe, matched_pattern = is_code_safe(full_path)
        
    if not is_safe:
        if os.path.exists(full_path): os.remove(full_path)
        await update.message.reply_text(f"❌ **လုံခြုံရေးအရ ငြင်းပယ်ခြင်း ခံရပါသည်!**\nခွင့်မပြုထားသော စကားလုံး (`{matched_pattern}`) ပါဝင်နေပါသည်။"); return
        
    context.user_data['current_file'] = full_path
    keyboard = [[InlineKeyboardButton("▶️ စတင်ရန်", callback_data="run_script")], [InlineKeyboardButton("🗑️ ဖျက်ရန်", callback_data="delete_file")]]
    await update.message.reply_text(text=f"📄 ဖိုင်အမည်: `{document.file_name}`\n🔴 ရပ်နားထားသည်", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); user_id = query.from_user.id
    file_path = context.user_data.get('current_file'); db = load_db(); user = check_user_status(user_id, db)
    if not file_path or not os.path.exists(file_path):
        await query.edit_message_text("❌ စနစ်ထဲမှာ ဖိုင်မတွေ့တော့ပါ။"); return
    display_name = os.path.basename(file_path).split("_", 2)[-1]
    if user_id not in running_processes: running_processes[user_id] = {}

    if query.data == "run_script":
        if user_id == ADMIN_ID: is_safe = True
        else: is_safe, _ = is_code_safe(file_path)
        if not is_safe: await query.edit_message_text("❌ စစ်ဆေးမှုအရ ဤကုဒ်သည် ဘေးကင်းမှုမရှိပါ။"); return
        log_path = f"{file_path}.log"; log_file = open(log_path, "w")
        try:
            process = subprocess.Popen(["python3", file_path], stdout=log_file, stderr=log_file)
            running_processes[user_id][file_path] = {"process": process, "start_time": time.time()}
            keyboard = [[InlineKeyboardButton("⏸️ ခေတ္တရပ်ရန်", callback_data="stop_script")], [InlineKeyboardButton("📋 Log ဖိုင်ရယူရန်", callback_data="get_log")]]
            await query.edit_message_text(text=f"📄 ဖိုင်အမည်: `{display_name}`\n🟢 အလုပ်လုပ်နေသည် (PID: {process.pid})", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e: await query.edit_message_text(f"❌ Error: {str(e)}")
    elif query.data == "stop_script":
        if user_id in running_processes and file_path in running_processes[user_id]:
            p_info = running_processes[user_id][file_path]; p_info["process"].terminate(); p_info["process"].wait()
            if user.get("role") == "free": user["free_used_today"] += (time.time() - p_info["start_time"]); save_db(db)
            del running_processes[user_id][file_path]
            keyboard = [[InlineKeyboardButton("▶️ စတင်ရန်", callback_data="run_script")], [InlineKeyboardButton("🗑️ ဖျက်ရန်", callback_data="delete_file")]]
            await query.edit_message_text(text=f"📄 ဖိုင်အမည်: `{display_name}`\n🔴 ရပ်နားထားသည်", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data == "get_log":
        if os.path.exists(f"{file_path}.log"):
            try: await context.bot.send_document(chat_id=query.message.chat_id, document=open(f"{file_path}.log", 'rb'))
            except: pass
    elif query.data == "delete_file":
        if user_id in running_processes and file_path in running_processes[user_id]:
            running_processes[user_id][file_path]["process"].terminate(); running_processes[user_id][file_path]["process"].wait()
            del running_processes[user_id][file_path]
        if os.path.exists(file_path): os.remove(file_path)
        await query.edit_message_text("🗑️ ဖိုင်ကို ဖျက်သိမ်းပြီးပါပြီ။")

# --- Admin Commands ---
async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    db = load_db(); text = f"📊 **Global Statistics**\nTotal Users: {len(db)}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

def main():
    # Token ချိတ်ဆက်မှုစနစ်အား အမှန်ကန်ဆုံး ပုံစံဖြင့် တည်ဆောက်ထားပါသည်
    app = Application.builder().token(BOT_TOKEN).build()
    start_background_timer(BOT_TOKEN)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", admin_status))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(button_click))
    
    print("🤖 KRAW Hosting Engine Active perfectly on Railway...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
