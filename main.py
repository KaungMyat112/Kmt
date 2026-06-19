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

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5536833682"))
DB_FILE = "users_db.json"

# --- 🛡️ SECURITY FILTER ---
DANGEROUS_KEYWORDS = [
    r"os\.system", r"subprocess\.", r"pty\.", r"shutil\.", r"open\(.*w.*?\)", r"open\(.*a.*?\)",
    r"chpasswd", r"useradd", r"usermod", r"passwd", r"rm\s+-", r"chmod", r"chown",
    r"socket", r"requests", r"urllib", r"builtins", r"eval\(", r"exec\(", r"__import__"
]

# running_processes[user_id][file_path] = {"process": p, "start_time": t, "pid": pid, "display_name": name}
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
    if user_id == ADMIN_ID: 
        return {"role": "admin", "expire_at": 0, "free_used_today": 0, "warnings": 0, "banned": False}
    
    if uid not in db:
        db[uid] = {"role": "free", "expire_at": 0, "free_used_today": 0, "last_free_reset": now, "warnings": 0, "banned": False}
        save_db(db)
        
    user = db[uid]
    if "warnings" not in user: user["warnings"] = 0
    if "banned" not in user: user["banned"] = False
        
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

# --- 🛡️ BACKGROUND THREAD TIMER ---
def start_background_timer(token):
    def loop_checker():
        bot_client = Bot(token=token)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            try:
                time.sleep(60)
                db = load_db()
                now = time.time()
                for user_id, files in list(running_processes.items()):
                    uid = str(user_id)
                    
                    # ⚠️ ပြင်ဆင်ချက်- Admin ဖြစ်ခဲ့ရင် Timer စစ်ဆေးမှုကနေ လုံးဝကျော်သွားစေရန် ပထမဆုံး စစ်ထုတ်ချက်ထားပါတယ်
                    if int(user_id) == ADMIN_ID:
                        continue
                    
                    # VIP သို့မဟုတ် Premium ဖြစ်နေရင်လည်း ၅ နာရီ Limit နဲ့ မဖြတ်ရန်
                    if uid in db and db[uid].get("role") in ["vip", "premium", "admin"]: 
                        continue
                        
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
                        try: loop.run_until_complete(bot_client.send_message(chat_id=int(user_id), text="⚠️ ယနေ့အတွက် Free ၅ နာရီ သုံးစွဲမှု ပြည့်သွားသဖြင့် Script များကို စနစ်မှ ရပ်ဆိုင်းလိုက်ပါပြီ။"))
                        except: pass
            except: pass
    threading.Thread(target=loop_checker, daemon=True).start()

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; db = load_db(); user = check_user_status(user_id, db)
    if user.get("banned"):
        await update.message.reply_text("❌ စနစ်စည်းကမ်း ဖောက်ဖျက်မှုကြောင့် သင့်အား အပြီးပိုင် Ban ထားပါသည်။"); return
        
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
    if user.get("banned"):
        await update.message.reply_text("❌ စနစ်စည်းကမ်း ဖောက်ဖျက်မှုကြောင့် သင့်အား အပြီးပိုင် Ban ထားပါသည်။"); return
        
    if not document or not document.file_name: return
    if not document.file_name.endswith('.py'):
        await update.message.reply_text("❌ ကျေးဇူးပြု၍ Python (.py) ဖိုင်ကိုသာ ပို့ပေးပါ။"); return
        
    active_count = sum(1 for p in running_processes.get(user_id, {}).values() if p["process"].poll() is None)
    if active_count >= get_max_allowed_files(user.get("role")):
        await update.message.reply_text("⚠️ သင့်အဆင့်၏ Limit ပြည့်နေပါသည်။ အဟောင်းကို အရင်ရပ်ပေးပါ။"); return
        
    file_name = f"{user_id}_{int(time.time())}_{document.file_name}"
    file = await context.bot.get_file(document.file_id); await file.download_to_drive(file_name)
    full_path = os.path.abspath(file_name)
    
    if user_id == ADMIN_ID: 
        is_safe, matched_pattern = True, None
    else: 
        is_safe, matched_pattern = is_code_safe(full_path)
        
    if not is_safe:
        if os.path.exists(full_path): os.remove(full_path)
        user["warnings"] += 1
        
        if user["warnings"] >= 2:
            user["banned"] = True; save_db(db)
            if user_id in running_processes:
                for fpath, p_info in list(running_processes[user_id].items()):
                    try: p_info["process"].terminate()
                    except: pass
                del running_processes[user_id]
            await update.message.reply_text("🚨 <b>စည်းကမ်းဖောက်ဖျက်မှု ဒုတိယအကြိမ်မြောက်ဖြစ်သဖြင့် သင့်အကောင့်အား အပြီးပိုင် BAN လိုက်ပါပြီ။</b>", parse_mode="HTML")
            try: await context.bot.send_message(chat_id=ADMIN_ID, text=f"🚨 <b>User Banned Noti</b>\nUser ID: <code>{user_id}</code> သည် အန္တရာယ်ရှိကုဒ် ၂ ကြိမ်တင်သဖြင့် စနစ်မှ အပြီးပိုင် BAN လိုက်ပါပြီ။", parse_mode="HTML")
            except: pass
        else:
            save_db(db)
            await update.message.reply_text("⚠️ <b>သတိပေးချက် (Warn 1)</b>\nသင့်ကုဒ်ထဲတွင် ခွင့်မပြုထားသော စနစ်ဖျက်ဆီးမည့် Code များ ပါဝင်နေသည်။ နောက်တစ်ကြိမ် ထပ်မံတင်ပါက Bot အသုံးပြုခွင့် လုံးဝပိတ် (BAN) ခံရမည်။", parse_mode="HTML")
            try: await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ <b>User Warning Noti</b>\nUser ID: <code>{user_id}</code> သည် အန္တရာယ်ရှိကုဒ်တင်သဖြင့် စနစ်မှ Warn 1 ကြိမ် ပေးလိုက်သည်။", parse_mode="HTML")
            except: pass
        return
        
    msg_file_key = f"file_{update.message.message_id}"
    context.user_data[msg_file_key] = full_path
    
    keyboard = [[InlineKeyboardButton("▶️ စတင်ရန်", callback_data=f"run__{update.message.message_id}")], [InlineKeyboardButton("🗑️ ဖျက်ရန်", callback_data=f"del__{update.message.message_id}")]]
    await update.message.reply_text(text=f"📄 ဖိုင်အမည်: `{document.file_name}`\n🔴 ရပ်နားထားသည်", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); user_id = query.from_user.id
    db = load_db(); user = check_user_status(user_id, db)
    if user.get("banned"): return

    data_parts = query.data.split("__")
    if len(data_parts) != 2: return
    action, target_msg_id = data_parts[0], data_parts[1]
    
    msg_file_key = f"file_{target_msg_id}"
    file_path = context.user_data.get(msg_file_key)
    
    if not file_path or not os.path.exists(file_path):
        await query.edit_message_text("❌ ဤဖိုင်ခလုတ်သည် သက်တမ်းကုန်သွားပါပြီ။ ဖိုင်ပြန်ပို့ပေးပါ။"); return
        
    display_name = os.path.basename(file_path).split("_", 2)[-1]
    if user_id not in running_processes: running_processes[user_id] = {}

    if action == "run":
        if user_id == ADMIN_ID: is_safe = True
        else: is_safe, _ = is_code_safe(file_path)
        if not is_safe: await query.edit_message_text("❌ စစ်ဆေးမှုအရ ဘေးကင်းမှုမရှိပါ။"); return
        
        log_path = f"{file_path}.log"; log_file = open(log_path, "w")
        try:
            process = subprocess.Popen(["python3", file_path], stdout=log_file, stderr=log_file)
            running_processes[user_id][file_path] = {"process": process, "start_time": time.time(), "pid": process.pid, "display_name": display_name}
            
            keyboard = [[InlineKeyboardButton("⏸️ ခေတ္တရပ်ရန်", callback_data=f"stop__{target_msg_id}")], [InlineKeyboardButton("📋 Log ဖိုင်ရယူရန်", callback_data=f"log__{target_msg_id}")]]
            await query.edit_message_text(text=f"📄 ဖိုင်အမည်: `{display_name}`\n🟢 အလုပ်လုပ်နေသည် (PID: <code>{process.pid}</code>)\n\n<i>(မှတ်ချက်။ ။ အကယ်၍ ဤခလုတ် အလုပ်မလုပ်တော့ပါက <code>/kill {process.pid}</code> ဟု ရိုက်၍ ရပ်နိုင်ပါသည်)</i>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e: await query.edit_message_text(f"❌ Error: {str(e)}")
        
    elif action == "stop":
        if user_id in running_processes and file_path in running_processes[user_id]:
            p_info = running_processes[user_id][file_path]
            try:
                p_info["process"].terminate(); p_info["process"].wait()
            except: pass
            if user.get("role") == "free": user["free_used_today"] += (time.time() - p_info["start_time"]); save_db(db)
            del running_processes[user_id][file_path]
            
            keyboard = [[InlineKeyboardButton("▶️ စတင်ရန်", callback_data=f"run__{target_msg_id}")], [InlineKeyboardButton("🗑️ ဖျက်ရန်", callback_data=f"del__{target_msg_id}")]]
            await query.edit_message_text(text=f"📄 ဖိုင်အမည်: `{display_name}`\n🔴 ရပ်နားထားသည်", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            
    elif action == "log":
        if os.path.exists(f"{file_path}.log"):
            try: await context.bot.send_document(chat_id=query.message.chat_id, document=open(f"{file_path}.log", 'rb'))
            except: pass
            
    elif action == "del":
        if user_id in running_processes and file_path in running_processes[user_id]:
            try: running_processes[user_id][file_path]["process"].terminate(); running_processes[user_id][file_path]["process"].wait()
            except: pass
            del running_processes[user_id][file_path]
        if os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(f"{file_path}.log"): os.remove(f"{file_path}.log")
        await query.edit_message_text("🗑️ ဖိုင်နှင့် Log များကို စနစ်မှ လုံးဝဖျက်သိမ်းပြီးပါပြီ။")

# --- 📋 STATUS & MONITORING SYSTEM ---
async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        db = load_db()
        user = check_user_status(user_id, db)
        if user.get("banned"): return

        total_users = len(db)
        active_scripts_text = ""
        global_active_count = 0
        
        for uid, files in running_processes.items():
            for fpath, p_info in list(files.items()):
                if p_info["process"].poll() is None:
                    global_active_count += 1
                    if user_id == ADMIN_ID or int(uid) == user_id:
                        active_scripts_text += f"🔹 <b>{p_info['display_name']}</b> (PID: <code>{p_info['pid']}</code>) - Owner ID: {uid}\n"

        text = "📊 <b>KRAW Server Global Statistics</b>\n"
        text += "----------------------------------\n"
        if user_id == ADMIN_ID:
            text += f"👥 Total Registered Users: {total_users} ဦး\n"
        text += f"🔥 Total Running Scripts on Server: {global_active_count} ခု\n\n"
        
        text += "📝 <b>သင့်ထံတွင် လည်ပတ်နေသော Active Scripts များ:</b>\n" if user_id != ADMIN_ID else "📝 <b>Server တစ်ခုလုံးတွင် လည်ပတ်နေသော Active Scripts များ:</b>\n"
        text += active_scripts_text if active_scripts_text != "" else "❌ လက်ရှိ မည်သည့် Script မျှ လည်ပတ်ခြင်းမရှိပါ။\n"
        
        if global_active_count > 0:
            text += "\n💡 <i>Script ကို အတင်းရပ်လိုပါက <code>/kill [PID]</code> ဟု ရိုက်ပို့ပါ။ (ဥပမာ- /kill 14)</i>"
            
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Stats Error: {str(e)}")

# --- ☠️ KILL COMMAND ---
async def kill_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        db = load_db(); user = check_user_status(user_id, db)
        if user.get("banned"): return

        if not context.args:
            await update.message.reply_text("❌ ကျေးဇူးပြု၍ ရပ်လိုသော PID ထည့်ပေးပါ။\nဥပမာ - <code>/kill 14</code>", parse_mode="HTML"); return
            
        try: target_pid = int(context.args[0])
        except: await update.message.reply_text("❌ PID သည် ကိန်းဂဏန်းအမှန် ဖြစ်ရပါမည်။"); return

        found = False
        for uid, files in list(running_processes.items()):
            for fpath, p_info in list(files.items()):
                if p_info["pid"] == target_pid:
                    if user_id == ADMIN_ID or int(uid) == user_id:
                        try:
                            p_info["process"].terminate()
                            p_info["process"].wait()
                        except: pass
                        
                        if db.get(str(uid), {}).get("role") == "free":
                            db[str(uid)]["free_used_today"] += (time.time() - p_info["start_time"])
                            save_db(db)
                            
                        del running_processes[uid][fpath]
                        found = True
                        await update.message.reply_text(f"✅ PID: <code>{target_pid}</code> ({p_info['display_name']}) ကို အောင်မြင်စွာ ရပ်ဆိုင်းလိုက်ပါပြီ။", parse_mode="HTML")
                        break
                    else:
                        await update.message.reply_text("❌ ဤ Script ကို ရပ်ပစ်ရန် Thint တွင် ခွင့်ပြုချက်မရှိပါ။"); return
            if found: break
            
        if not found:
            await update.message.reply_text(f"❌ သတ်မှတ်ထားသော PID: {target_pid} အား Active စာရင်းထဲတွင် မတွေ့ရပါ။")
    except Exception as e:
        await update.message.reply_text(f"❌ Kill Error: {str(e)}")

# --- 👑 ADMIN MANAGEMENT COMMANDS (ADD PREMIUM & ADD VIP) ---

# အသုံးပြုပုံ- /addpremium [User_ID] [ရက်အရေအတွက်] (ဥပမာ- /addpremium 5536833682 30)
async def add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ သင်သည် Admin မဟုတ်သဖြင့် ဤ Command ကို အသုံးပြုခွင့်မရှိပါ။")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("❌ အသုံးပြုပုံစံ မှားယွင်းနေပါသည်။\n✍️ ပုံစံ: `/addpremium [User_ID] [Days]`\n💡 ဥပမာ: `/addpremium 12345678 30`", parse_mode="Markdown")
        return
    
    try:
        target_uid = str(context.args[0])
        days = int(context.args[1])
        
        db = load_db()
        now = time.time()
        expire_time = now + (days * 86400)
        
        db[target_uid] = {
            "role": "premium",
            "expire_at": expire_time,
            "free_used_today": 0,
            "last_free_reset": now,
            "warnings": db.get(target_uid, {}).get("warnings", 0),
            "banned": False
        }
        save_db(db)
        
        await update.message.reply_text(f"✅ User ID: `{target_uid}` အား {days} ရက်စာ **PREMIUM** အဆင့်သို့ အောင်မြင်စွာ မြှင့်တင်ပေးလိုက်ပါပြီ။", parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=int(target_uid), text=f"🎉 🎉 ဂုဏ်ယူပါသည်! လူကြီးမင်း၏ အကောင့်အား Admin မှ {days} ရက်စာ **PREMIUM** အဆင့်သို့ မြှင့်တင်ပေးလိုက်ပါပြီ။\nယခုမှစ၍ Python Script ၁၀ ခုအထိ ပြိုင်တူ စက္ကန့်/နာရီ အကန့်အသတ်မရှိ Run နိုင်ပါပြီ။")
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# အသုံးပြုပုံ- /addvip [User_ID] [ရက်အရေအတွက်] (ဥပမာ- /addvip 5536833682 30)
async def add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ သင်သည် Admin မဟုတ်သဖြင့် ဤ Command ကို အသုံးပြုခွင့်မရှိပါ။")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("❌ အသုံးပြုပုံစံ မှားယွင်းနေပါသည်။\n✍️ ပုံစံ: `/addvip [User_ID] [Days]`\n💡 ဥပမာ: `/addvip 12345678 30`", parse_mode="Markdown")
        return
    
    try:
        target_uid = str(context.args[0])
        days = int(context.args[1])
        
        db = load_db()
        now = time.time()
        expire_time = now + (days * 86400)
        
        db[target_uid] = {
            "role": "vip",
            "expire_at": expire_time,
            "free_used_today": 0,
            "last_free_reset": now,
            "warnings": db.get(target_uid, {}).get("warnings", 0),
            "banned": False
        }
        save_db(db)
        
        await update.message.reply_text(f"✅ User ID: `{target_uid}` အား {days} ရက်စာ **VIP** အဆင့်သို့ အောင်မြင်စွာ မြှင့်တင်ပေးလိုက်ပါပြီ။", parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=int(target_uid), text=f"🎉 🎉 ဂုဏ်ယူပါသည်! လူကြီးမင်း၏ အကောင့်အား Admin မှ {days} ရက်စာ **VIP** အဆင့်သို့ မြှင့်တင်ပေးလိုက်ပါပြီ။\nယခုမှစ၍ Python Script ၅ ခုအထိ ပြိုင်တူ စက္ကန့်/နာရီ အကန့်အသတ်မရှိ Run နိုင်ပါပြီ။")
        except: pass
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

def main():
    if not BOT_TOKEN:
        print("❌ CRITICAL ERROR: BOT_TOKEN variable is missing in Railway Dashboard!")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    start_background_timer(BOT_TOKEN)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", admin_status))
    app.add_handler(CommandHandler("stats", admin_status))
    app.add_handler(CommandHandler("kill", kill_process))
    
    # Register Admin Commands
    app.add_handler(CommandHandler("addpremium", add_premium))
    app.add_handler(CommandHandler("addvip", add_vip))
    
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(button_click))
    
    print("🤖 KRAW Hosting Engine Active perfectly on Railway Server...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
