import os
import json
import time
import subprocess
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- Configuration ---
BOT_TOKEN = "8840868848:AAE_-AZFJDe85lO2eL8zsX9kGn8UMG-wuAM"
ADMIN_ID = 5536833682  # ⚠️ သင့်ရဲ့ Telegram User ID ကို ဒီနေရာမှာ အမှန်ပြင်ထည့်ပါ

DB_FILE = "users_db.json"

# running_processes = { user_id: { file_path: { "process": process_object, "start_time": time_stamp } } }
running_processes = {}

# --- Database Functions ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=4)

def check_user_status(user_id, db):
    uid = str(user_id)
    now = time.time()
    
    if user_id == ADMIN_ID:
        return {"role": "admin", "expire_at": 0, "free_used_today": 0}
        
    if uid not in db:
        db[uid] = {
            "role": "free",
            "expire_at": 0,
            "free_used_today": 0,
            "last_free_reset": now
        }
        save_db(db)
        
    user = db[uid]
    
    # Free User အား ၂၄ နာရီပြည့်ပါက ၅ နာရီ (၁၈၀၀0 စက္ကန့်) ပြန် Reset ပေးခြင်း
    if user.get("role") == "free" and (now - user.get("last_free_reset", 0)) >= 86400:
        user["free_used_today"] = 0
        user["last_free_reset"] = now
        save_db(db)
        
    # VIP/Premium သက်တမ်းကုန်ဆုံးပါက Free သို့ ပြန်ချခြင်း
    if user.get("role") in ["vip", "premium"] and now > user.get("expire_at", 0):
        user["role"] = "free"
        user["expire_at"] = 0
        save_db(db)
        
    return user

def get_max_allowed_files(role):
    if role == "admin": return 999999
    if role == "premium": return 10
    if role == "vip": return 5
    return 1

# --- Background Job (၅ နာရီပြည့်ကွက်တိ ပိတ်ချမည့်စနစ်) ---
async def auto_stop_free_users(context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    now = time.time()
    
    for user_id, files in list(running_processes.items()):
        uid = str(user_id)
        
        if uid in db and db[uid].get("role") in ["admin", "vip", "premium"]:
            continue
            
        user = db.setdefault(uid, {"role": "free", "expire_at": 0, "free_used_today": 0, "last_free_reset": now})
        already_used = user.get("free_used_today", 0)
        
        current_running_time = 0
        for fpath, p_info in list(files.items()):
            proc = p_info["process"]
            if proc.poll() is None:
                current_running_time += (now - p_info["start_time"])
        
        if (already_used + current_running_time) >= 18000:
            for fpath, p_info in list(files.items()):
                proc = p_info["process"]
                if proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait()
                    except Exception as e:
                        print(f"Auto-stop error for user {user_id}: {e}")
            
            user["free_used_today"] = 18000
            save_db(db)
            
            if user_id in running_processes:
                del running_processes[user_id]
                
            try:
                await context.bot.send_message(
                    chat_id=int(user_id),
                    text="⚠️ **ယနေ့အတွက် Free ၅ နာရီ သုံးစွဲမှု အချိန်ပြည့်သွားသဖြင့် သင်မောင်းနှင်ထားသော Script များအားလုံးကို စနစ်မှ အလိုအလျောက် ရပ်တန့်လိုက်ပါပြီ။**\nနောက်ရက်မှ ပြန်လည်အသုံးပြုနိုင်ပါမည်။"
                )
            except TelegramError:
                pass

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db = load_db()
    user = check_user_status(user_id, db)
    
    role_text = str(user.get("role", "free")).upper()
    
    if user.get("role") == "admin":
        expire_text = "အကန့်အသတ်မရှိ (ADMIN)"
    elif user.get("role") == "free":
        already_used = user.get("free_used_today", 0)
        current_running_time = 0
        user_active_processes = running_processes.get(user_id, {})
        
        for fpath, p_info in list(user_active_processes.items()):
            if p_info["process"].poll() is None:
                current_running_time += (time.time() - p_info["start_time"])
        
        total_used = already_used + current_running_time
        left_seconds = max(0, 18000 - total_used)
        
        hours = int(left_seconds // 3600)
        minutes = int((left_seconds % 3600) // 60)
        expire_text = f"Free (ယနေ့ကျန်ရှိချိန်: {hours} နာရီ {minutes} မိနစ်)"
    else:
        expire_text = datetime.fromtimestamp(user.get("expire_at", 0)).strftime('%Y-%m-%d %H:%M:%S')
    
    max_files = get_max_allowed_files(user.get("role"))
    max_files_text = "အကန့်အသတ်မရှိ" if max_files == 999999 else f"{max_files} ဖိုင်"

    await update.message.reply_text(
        f"👋 KRAW Bot Hosting မှ ကြိုဆိုပါတယ်။\n\n"
        f"📊 သင့်အဆင့်: *{role_text}*\n"
        f"⏳ သက်တမ်းကုန်ရက်: `{expire_text}`\n"
        f"🚀 ပြိုင်တူ Run  ခွင့်: `{max_files_text}`\n\n"
        f"ကျေးဇူးပြု၍ သင် Run ချင်သော `.py` ဖိုင်ကို တင်ပေးပါ။",
        parse_mode="Markdown"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    document = update.message.document
    
    db = load_db()
    user = check_user_status(user_id, db)
    
    if not document or not document.file_name: return

    if not document.file_name.endswith('.py'):
        await update.message.reply_text("❌ ကျေးဇူးပြု၍ Python (.py) ဖိုင်ကိုသာ ပို့ပေးပါ။")
        return

    user_active_processes = running_processes.get(user_id, {})
    active_count = sum(1 for p in user_active_processes.values() if p["process"].poll() is None)
    max_allowed = get_max_allowed_files(user.get("role"))
    
    if active_count >= max_allowed:
        await update.message.reply_text(
            f"⚠️ သင့်အဆင့်၏ Limit ပြည့်နေပါသည်။ ({active_count}/{max_allowed} ဖိုင်)\n"
            f"ဖိုင်အသစ်ထပ်မောင်းရန် အဟောင်းကို အရင် Close/Stop လုပ်ပေးပါ။"
        )
        return

    file_name = f"{user_id}_{int(time.time())}_{document.file_name}"
    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive(file_name)
    
    context.user_data['current_file'] = os.path.abspath(file_name)

    keyboard = [[InlineKeyboardButton("▶️ စတင်ရန်", callback_data="run_script")], [InlineKeyboardButton("🗑️ ဖျက်ရန်", callback_data="delete_file")]]
    await update.message.reply_text(text=f"📄 ဖိုင်အမည်: `{document.file_name}`\n🔴 ရပ်နားထားသည်", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    file_path = context.user_data.get('current_file')
    db = load_db()
    user = check_user_status(user_id, db)

    if not file_path or not os.path.exists(file_path):
        await query.edit_message_text("❌ စနစ်ထဲမှာ ဖိုင်မတွေ့တော့ပါ။ ဖိုင်ပြန်ပို့ပေးပါ။")
        return

    raw_name = os.path.basename(file_path)
    display_name = raw_name.split("_", 2)[-1] if len(raw_name.split("_", 2)) >= 3 else raw_name

    if user_id not in running_processes: running_processes[user_id] = {}

    if query.data == "run_script":
        already_used = user.get("free_used_today", 0)
        current_running = 0
        for fpath, p_info in list(running_processes[user_id].items()):
            if p_info["process"].poll() is None:
                current_running += (time.time() - p_info["start_time"])
                
        if user.get("role") == "free" and (already_used + current_running) >= 18000:
            await query.edit_message_text("❌ ယနေ့အတွက် Free 5 နာရီ သုံးစွဲမှု ကုန်ဆုံးသွားပါပြီ။")
            return
            
        active_count = sum(1 for p in running_processes[user_id].values() if p["process"].poll() is None)
        max_allowed = get_max_allowed_files(user.get("role"))
        if active_count >= max_allowed:
            await query.edit_message_text(f"⚠️ သင့်အဆင့်၏ အများဆုံး Run ခွင့်ပြုချက် ({max_allowed} ဖိုင်) ပြည့်သွားပါပြီ။")
            return

        log_path = f"{file_path}.log"
        log_file = open(log_path, "w")
        
        try:
            process = subprocess.Popen(["python3", file_path], stdout=log_file, stderr=log_file)
            running_processes[user_id][file_path] = {
                "process": process,
                "start_time": time.time()
            }

            keyboard = [[InlineKeyboardButton("⏸️ ခေတ္တရပ်ရန်", callback_data="stop_script")], [InlineKeyboardButton("📋 Log ဖိုင်ရယူရန်", callback_data="get_log")]]
            await query.edit_message_text(text=f"📄 ဖိုင်အမည်: `{display_name}`\n🟢 အလုပ်လုပ်နေသည် (PID: {process.pid})", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {str(e)}")

    elif query.data == "stop_script":
        if user_id in running_processes and file_path in running_processes[user_id]:
            p_info = running_processes[user_id][file_path]
            process = p_info["process"]
            process.terminate()
            process.wait()
            
            if user.get("role") == "free":
                user["free_used_today"] += (time.time() - p_info["start_time"])
                save_db(db)
                
            del running_processes[user_id][file_path]
            
            keyboard = [[InlineKeyboardButton("▶️ စတင်ရန်", callback_data="run_script")], [InlineKeyboardButton("🗑️ ဖျက်ရန်", callback_data="delete_file")]]
            await query.edit_message_text(text=f"📄 ဖိုင်အမည်: `{display_name}`\n🔴 ရပ်နားထားသည်", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "get_log":
        if os.path.exists(f"{file_path}.log"):
            await context.bot.send_document(chat_id=query.message.chat_id, document=open(f"{file_path}.log", 'rb'))

    elif query.data == "delete_file":
        if user_id in running_processes and file_path in running_processes[user_id]:
            running_processes[user_id][file_path]["process"].terminate()
            running_processes[user_id][file_path]["process"].wait()
            del running_processes[user_id][file_path]
        if os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(f"{file_path}.log"): os.remove(f"{file_path}.log")
        await query.edit_message_text("🗑️ ဖိုင်ကို ဖျက်သိမ်းပြီးပါပြီ။")

# --- Admin Commands ---

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("❌ အသုံးပြုပုံ: `/broadcast <စာသား>`")
        return
    broadcast_msg = "📢 **KRAW HOSTING ANNOUNCEMENT**\n\n" + " ".join(context.args)
    db = load_db()
    success_count, fail_count = 0, 0
    status_msg = await update.message.reply_text("⏳ Broadcast ပို့နေပါပြီ...")
    for uid in db.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=broadcast_msg, parse_mode="Markdown")
            success_count += 1
            time.sleep(0.05)
        except: fail_count += 1
    await status_msg.edit_text(f"✅ ပို့ဆောင်မှု ပြီးဆုံးပါပြီ။\n\n🟢 အောင်မြင်: `{success_count}` ဦး\n🔴 ကျရှုံး: `{fail_count}` ဦး")

def parse_duration(duration_str):
    now = time.time()
    if duration_str.endswith('d'): return now + (int(duration_str.replace('d', '')) * 86400)
    if duration_str.endswith('h'): return now + (int(duration_str.replace('h', '')) * 3600)
    return None

async def admin_add_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = context.args[0]
        expire_at = parse_duration(context.args[1])
        db = load_db()
        db[str(target_id)] = {"role": "vip", "expire_at": expire_at, "free_used_today": 0, "last_free_reset": time.time()}
        save_db(db)
        await update.message.reply_text(f"✅ User `{target_id}` အား VIP သတ်မှတ်ပြီးပါပြီ။ (ပြိုင်တူ ၅ ဖိုင်)")
        await context.bot.send_message(chat_id=int(target_id), text="🎉 သင့်အကောင့်အား VIP အဆင့်သို့ မြှင့်တင်ပေးလိုက်ပါပြီ။ (ပြိုင်တူ ၅ ဖိုင်)")
    except: await update.message.reply_text("❌ အသုံးပြုပုံ: `/add <user_id> <7d/15d/30d>`")

async def admin_add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = context.args[0]
        expire_at = parse_duration(context.args[1])
        db = load_db()
        db[str(target_id)] = {"role": "premium", "expire_at": expire_at, "free_used_today": 0, "last_free_reset": time.time()}
        save_db(db)
        await update.message.reply_text(f"✅ User `{target_id}` အား Premium သတ်မှတ်ပြီးပါပြီ။ (ပြိုင်တူ ၁၀ ဖိုင်)")
        await context.bot.send_message(chat_id=int(target_id), text="🎉 သင့်အကောင့်အား PREMIUM အဆင့်သို့ မြှင့်တင်ပေးလိုက်ပါပြီ။ (ပြိုင်တူ ၁၀ ဖိုင်)")
    except: await update.message.reply_text("❌ အသုံးပြုပုံ: `/addPremium <user_id> <7d/15d/30d>`")

# --- [🛠️ ADMIN STATUS BUG FIXES] ---
async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    db = load_db()
    now = time.time()
    
    total_users = len(db)
    free_users = sum(1 for u in db.values() if u.get("role") == "free")
    vip_users = sum(1 for u in db.values() if u.get("role") == "vip")
    premium_users = sum(1 for u in db.values() if u.get("role") == "premium")
    
    active_processes_count = 0
    for uid, files in running_processes.items():
        active_processes_count += sum(1 for p in files.values() if p["process"].poll() is None)

    text = "📊 **KRAW Server Global Statistics**\n"
    text += "----------------------------------\n"
    text += f"👥 Total Users DB: `{total_users}` ဦး\n"
    text += f"🆓 FREE Users: `{free_users}` | 👑 VIP: `{vip_users}` | 🚀 PREMIUM: `{premium_users}`\n"
    text += f"🔥 Total Active Running Scripts: `{active_processes_count}` ခု\n\n"
    text += "📝 **Active Process Details:**\n"
    text += "----------------------------------\n"
    
    has_running = False
    
    for uid_str, files in list(running_processes.items()):
        uid_int = int(uid_str)
        
        # Admin ဖြစ်ခဲ့လျှင် Default Role သတ်မှတ်ပေးရန် (Bug Fixed)
        if uid_int == ADMIN_ID:
            user_info = {"role": "admin", "expire_at": 0, "free_used_today": 0}
        else:
            user_info = db.get(str(uid_str), {"role": "free", "expire_at": 0, "free_used_today": 0})
            
        role = str(user_info.get("role", "free")).upper()
        
        try:
            chat = await context.bot.get_chat(uid_int)
            user_name = chat.full_name if chat.full_name else "Unknown User"
        except:
            user_name = "Unknown User"

        if role == "ADMIN":
            time_left_text = "အကန့်အသတ်မရှိ (ADMIN)"
        elif role == "FREE":
            already_used = user_info.get("free_used_today", 0)
            current_running_time = 0
            
            for fpath, p_info in list(files.items()):
                if p_info["process"].poll() is None:
                    current_running_time += (now - p_info["start_time"])
            
            total_used = already_used + current_running_time
            left_seconds = max(0, 18000 - total_used)
            hours = int(left_seconds // 3600)
            minutes = int((left_seconds % 3600) // 60)
            time_left_text = f"ယနေ့ကျန်ချိန် {hours} နာရီ {minutes} မိနစ်"
        else:
            expire_at = user_info.get("expire_at", 0)
            if now > expire_at:
                time_left_text = "သက်တမ်းကုန်ဆုံး"
            else:
                diff = expire_at - now
                days = int(diff // 86400)
                hours = int((diff % 86400) // 3600)
                time_left_text = f"သက်တမ်းကျန် {days} ရက် {hours} နာရီ"

        for fpath, p_info in list(files.items()):
            proc = p_info["process"]
            if proc.poll() is None:
                has_running = True
                fname = os.path.basename(fpath).split("_", 2)[-1] if len(os.path.basename(fpath).split("_", 2)) >= 3 else os.path.basename(fpath)
                
                text += f"👤 **Name:** {user_name}\n"
                text += f"🆔 **User ID:** `{uid_str}`\n"
                text += f"🎖️ **Role:** *{role}*\n"
                text += f"📄 **File:** `{fname}`\n"
                text += f"🔢 **PID:** `{proc.pid}`\n"
                text += f"⏳ **Status:** {time_left_text}\n"
                text += "------------------------\n"
                
    if not has_running: 
        text += "လက်ရှိ Run နေသော Active Script တစ်ခုမှမရှိပါ။"
        
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target = context.args[0]
        killed = False
        target_int = int(target)
        
        for uid, files in list(running_processes.items()):
            for fpath, p_info in list(files.items()):
                proc = p_info["process"]
                if proc.pid == target_int:
                    proc.terminate()
                    proc.wait()
                    del running_processes[uid][fpath]
                    killed = True
                    break
            if killed: break
            
        if not killed and target_int in running_processes:
            for fpath, p_info in list(running_processes[target_int].items()):
                proc = p_info["process"]
                proc.terminate()
                proc.wait()
            del running_processes[target_int]
            killed = True
            
        if killed: 
            await update.message.reply_text(f"✅ သတ်မှတ်ထားသော Target (`{target}`) အား ပိတ်ချ/ဖျက်သိမ်း ပြီးပါပြီ။")
        else: 
            await update.message.reply_text("❌ သတ်မှတ်ထားသော PID သို့မဟုတ် User ID ကို အလုပ်လုပ်နေဆဲ စာရင်းထဲတွင် မတွေ့ပါ။")
    except Exception as e: 
        await update.message.reply_text("❌ အသုံးပြုပုံ: `/kill <PID သို့မဟုတ် User_ID>`")

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    job_queue = app.job_queue
    job_queue.run_repeating(auto_stop_free_users, interval=60, first=10)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", admin_add_vip))
    app.add_handler(CommandHandler("addPremium", admin_add_premium))
    app.add_handler(CommandHandler("status", admin_status))
    app.add_handler(CommandHandler("kill", admin_kill))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(button_click))

    print("🤖 OVps Engine Started 100% Fully Functional...")
    app.run_polling()

if __name__ == "__main__":
    main()
