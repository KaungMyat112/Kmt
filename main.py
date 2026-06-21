import os
import json
import time
import subprocess
import re
import threading
import asyncio
import signal
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import TelegramError

# --- Configuration ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5536833682"))
DB_FILE = "users_db.json"

# လက်ရှိ Run နေဆဲ Process များကို သိမ်းဆည်းရန်
running_processes = {}

# --- 🔐 STRICT SECURITY CHECK (ADMIN ONLY) ---
def is_admin(user_id):
    return user_id == ADMIN_ID

# --- Database Functions ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

def save_db(db):
    with open(DB_FILE, "w") as f: json.dump(db, f, indent=4)

# --- 🛡️ BACKGROUND PROCESS CLEANER (Zombie & Resource Leak Killer) ---
def start_background_cleaner():
    def loop_checker():
        while True:
            try:
                time.sleep(30) # ၃၀ စက္ကန့်တစ်ကြိမ် မလိုအပ်တဲ့ data တွေ လိုက်ရှင်းမယ်
                for uid, files in list(running_processes.items()):
                    for fpath, p_info in list(files.items()):
                        # အကယ်၍ Process က ရပ်သွားခဲ့ရင် သို့မဟုတ် poll() က အဖြေပြန်ပေးရင် Data ထဲက ဖြုတ်ပစ်မယ်
                        if p_info["process"].poll() is not None:
                            try:
                                p_info["process"].wait() # ကောင်းကောင်းမွန်မွန် resource ပြန်လွှတ်ပေးရန်
                            except: pass
                            if uid in running_processes and fpath in running_processes[uid]:
                                del running_processes[uid][fpath]
            except: pass
    threading.Thread(target=loop_checker, daemon=True).start()

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # ❌ Admin မဟုတ်ရင် လုံးဝ အသုံးပြုခွင့်မပေးပါ
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <b>KRAW Bot Hosting [Private Mode]</b>\n\nဤ Bot သည် စနစ်ထိန်းသိမ်းသူ (Admin) သီးသန့်အသုံးပြုရန် ဖြစ်သောကြောင့် သင့်တွင် အသုံးပြုခွင့် မရှိပါဗျာ။", parse_mode="HTML")
        return
        
    await update.message.reply_text(
        f"👋 <b>KRAW Private Hosting မှ ကြိုဆိုပါတယ် Admin စော။</b>\n\n"
        f"👑 Role: <code>OWNER / ADMIN</code>\n"
        f"🚀 Server Limit: <code>အကန့်အသတ်မရှိ</code>\n\n"
        f"အသုံးပြုရန် Python (.py) ဖိုင်ကို တင်ပေးနိုင်ပါပြီခင်ဗျာ။", 
        parse_mode="HTML"
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # ❌ ဤနေရာတွင်လည်း တခြားသူ တင်လို့မရအောင် ထပ်ပိတ်ထားပါသည်
    if not is_admin(user_id):
        await update.message.reply_text("❌ ခွင့်ပြုချက်မရှိဘဲ ဖိုင်တင်ခွင့် မရှိပါ။")
        return
        
    document = update.message.document
    if not document or not document.file_name: return
    if not document.file_name.endswith('.py'):
        await update.message.reply_text("❌ ကျေးဇူးပြု၍ Python (.py) ဖိုင်ကိုသာ ပို့ပေးပါ။"); return
        
    file_name = f"admin_{int(time.time())}_{document.file_name}"
    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive(file_name)
    full_path = os.path.abspath(file_name)
        
    msg_file_key = f"file_{update.message.message_id}"
    context.user_data[msg_file_key] = full_path
    
    keyboard = [
        [InlineKeyboardButton("▶️ စတင် Run မည်", callback_data=f"run__{update.message.message_id}")], 
        [InlineKeyboardButton("🗑️ စနစ်ထဲမှ ဖျက်မည်", callback_data=f"del__{update.message.message_id}")]
    ]
    await update.message.reply_text(text=f"📄 ဖိုင်အမည်: `{document.file_name}`\n🔴 အခြေအနေ: ရပ်နားထားသည်", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # ❌ ခလုတ်များကိုပါ Admin မှလွဲ၍ နှိပ်ခွင့်ပိတ်
    if not is_admin(user_id): return

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
        log_path = f"{file_path}.log"
        log_file = open(log_path, "w")
        try:
            # Process Group (os.setsid) ဆောက်ပြီး Background တင်မယ်
            process = subprocess.Popen(["python3", file_path], stdout=log_file, stderr=log_file, preexec_fn=os.setsid)
            running_processes[user_id][file_path] = {"process": process, "start_time": time.time(), "pid": process.pid, "display_name": display_name}
            
            keyboard = [
                [InlineKeyboardButton("⏸️ အပြီးသတ် ရပ်မည် (Kill)", callback_data=f"stop__{target_msg_id}")], 
                [InlineKeyboardButton("📋 Log ကြည့်မည်", callback_data=f"log__{target_msg_id}")]
            ]
            await query.edit_message_text(text=f"📄 ဖိုင်အမည်: `{display_name}`\n🟢 အခြေအနေ: အလုပ်လုပ်နေသည် (PID: <code>{process.pid}</code>)", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e: await query.edit_message_text(f"❌ Error: {str(e)}")
        
    elif action == "stop":
        if user_id in running_processes and file_path in running_processes[user_id]:
            p_info = running_processes[user_id][file_path]
            try:
                # မလိုအပ်တဲ့ data တွေ မကျန်အောင် ရပ်လိုက်တာနဲ့ PID Group တစ်ခုလုံးကို အပြတ် Kill ပစ်မယ်
                os.killpg(os.getpgid(p_info["process"].pid), signal.SIGKILL)
                p_info["process"].wait()
            except: pass
            del running_processes[user_id][file_path]
            
            keyboard = [[InlineKeyboardButton("▶️ စတင် Run မည်", callback_data=f"run__{target_msg_id}")], [InlineKeyboardButton("🗑️ စနစ်ထဲမှ ဖျက်မည်", callback_data=f"del__{target_msg_id}")]]
            await query.edit_message_text(text=f"📄 ဖိုင်အမည်: `{display_name}`\n🔴 အခြေအနေ: အပြီးသတ် သတ် (Kill) ပြီးပါပြီ", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            
    elif action == "log":
        if os.path.exists(f"{file_path}.log"):
            try: await context.bot.send_document(chat_id=query.message.chat_id, document=open(f"{file_path}.log", 'rb'))
            except: pass
            
    elif action == "del":
        if user_id in running_processes and file_path in running_processes[user_id]:
            try:
                os.killpg(os.getpgid(running_processes[user_id][file_path]["process"].pid), signal.SIGKILL)
                running_processes[user_id][file_path]["process"].wait()
            except: pass
            del running_processes[user_id][file_path]
        if os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(f"{file_path}.log"): os.remove(f"{file_path}.log")
        await query.edit_message_text("🗑️ ဖိုင်နှင့် မလိုအပ်သော Log Data အားလုံးကို Server ပေါ်မှ အပြီးပိုင် ဖျက်ဆီးပြီးပါပြီ။")

# --- 📋 STATUS SYSTEM ---
async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id): return

    active_scripts_text = ""
    global_active_count = 0
    
    for uid, files in running_processes.items():
        for fpath, p_info in list(files.items()):
            if p_info["process"].poll() is None:
                global_active_count += 1
                active_scripts_text += f"🔹 <b>{p_info['display_name']}</b> (PID: <code>{p_info['pid']}</code>)\n"

    text = "📊 <b>Server Monitor (Admin Only)</b>\n----------------------------------\n"
    text += f"🔥 လည်ပတ်နေသော Script စုစုပေါင်း: {global_active_count} ခု\n\n"
    text += "📝 <b>Active Scripts List:</b>\n"
    text += active_scripts_text if active_scripts_text != "" else "❌ လက်ရှိ မည်သည့် Script မျှ Run မထားပါ။\n"
    
    await update.message.reply_text(text, parse_mode="HTML")

# --- ☠️ FORCE KILL COMMAND ---
async def kill_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id): return
    
    if not context.args:
        await update.message.reply_text("❌ ကျေးဇူးပြု၍ သတ်လိုသော PID ထည့်ပေးပါ။ ပုံစံ: <code>/kill [PID]</code>", parse_mode="HTML"); return
        
    try: target_pid = int(context.args[0])
    except: await update.message.reply_text("❌ PID သည် ဂဏန်းဖြစ်ရပါမည်။"); return

    found = False
    for uid, files in list(running_processes.items()):
        for fpath, p_info in list(files.items()):
            if p_info["pid"] == target_pid:
                try:
                    os.killpg(os.getpgid(target_pid), signal.SIGKILL)
                    p_info["process"].wait()
                except: pass
                del running_processes[uid][fpath]
                found = True
                await update.message.reply_text(f"💥 PID: <code>{target_pid}</code> နှင့် ၎င်းနှင့်ပတ်သက်သော Data အားလုံးကို Force Kill လုပ်ပြီးပါပြီ။", parse_mode="HTML")
                break
        if found: break
    if not found: 
        try:
            os.killpg(os.getpgid(target_pid), signal.SIGKILL)
            await update.message.reply_text(f"⚡ စာရင်းထဲမရှိသော်လည်း Background ရှိ PID: {target_pid} ကို အတင်းအကျပ် Kill လိုက်ပါပြီ။")
        except:
            await update.message.reply_text(f"❌ သတ်မှတ်ထားသော PID: {target_pid} အား Server ပေါ်တွင် ရှာမတွေ့ပါ။")

def main():
    if not BOT_TOKEN:
        print("❌ CRITICAL ERROR: BOT_TOKEN is missing!")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    
    # ၃၀ စက္ကန့်တစ်ကြိမ် မလိုအပ်တဲ့ data တွေ လိုက်သတ်မယ့် စနစ်ဖွင့်မယ်
    start_background_cleaner()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", admin_status))
    app.add_handler(CommandHandler("stats", admin_status))
    app.add_handler(CommandHandler("kill", kill_process))
    
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(button_click))
    
    print("🤖 KRAW Admin-Only Private Hosting Engine Active Perfectly...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
