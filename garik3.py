import telebot
from telebot import types
import re
import logging
import threading
import time
from datetime import datetime, timedelta

# ==========================================
# КОНФИГУРАЦИЯ БОТА
# ==========================================
TOKEN = "8910350436:AAHDUFMDFOAxIWulycNbVKhIVFQtY7kor5s"
MAIN_CHAT_ID = -1004292550506  # ID твоего суперчата с темами

# Настройка логирования для Termux
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[logging.StreamHandler()]
)

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# База данных для активных комнат (тем)
# { thread_id: { "creator_id": int, "creator_username": str, "last_activity": datetime, "voice_active": bool } }
active_rooms = {}
rooms_lock = threading.Lock()

user_cooldowns = {}
COOLDOWN_SECONDS = 4

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def is_spamming(user_id):
    current_time = time.time()
    if user_id in user_cooldowns:
        if current_time - user_cooldowns[user_id] < COOLDOWN_SECONDS:
            return True
    user_cooldowns[user_id] = current_time
    return False

def parse_usernames(text, creator_username):
    clean_text = re.sub(r'^(комната|рум|room|\/room|\/create)\s*', '', text, flags=re.IGNORECASE)
    usernames = re.findall(r'@([\w_]+)', clean_text)
    
    unique_usernames = []
    seen = set()
    
    if creator_username:
        creator_lower = creator_username.lower()
        unique_usernames.append(f"@{creator_username}")
        seen.add(creator_lower)
        
    for u in usernames:
        u_lower = u.lower()
        if u_lower not in seen:
            seen.add(u_lower)
            unique_usernames.append(f"@{u}")
            
    return unique_usernames

def get_room_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    btn_extend = types.InlineKeyboardButton(text="⏳ Продлить (30м)", callback_data="room_extend")
    btn_delete = types.InlineKeyboardButton(text="🗑 Удалить рум", callback_data="room_delete")
    keyboard.row(btn_extend, btn_delete)
    return keyboard

# ==========================================
# ЛОГИКА СОЗДАНИЯ РУМЫ (ТОПИКА)
# ==========================================

@bot.message_handler(func=lambda m: m.chat.id == MAIN_CHAT_ID and m.message_thread_id is not None)
def handle_room_topic_creation(message):
    text = (message.text or "").strip()
    user = message.from_user
    
    trigger_words = ["room", "комната", "рум", "/room", "/create"]
    if not any(text.lower().startswith(word) for word in trigger_words):
        return

    if is_spamming(user.id):
        return

    logging.info(f"Запрос на создание топика от @{user.username}: '{text}'")

    usernames_list = parse_usernames(text, user.username)
    
    if len(usernames_list) == 0 or (user.username and len(usernames_list) == 1 and usernames_list[0] == f"@{user.username}"):
        reply = bot.reply_to(message, "❌ <b>Неправильный формат!</b>\nПример:\n<code>комната @user1 @user2</code>")
        threading.Thread(target=lambda: (time.sleep(7), bot.delete_message(MAIN_CHAT_ID, reply.message_id))).start()
        return

    try:
        bot.delete_message(MAIN_CHAT_ID, message.message_id)
    except:
        pass

    try:
        # Создаем тему на форуме
        topic_title = f"🎮 Brawl | @{user.username}"
        new_topic = bot.create_forum_topic(chat_id=MAIN_CHAT_ID, name=topic_title)
        new_thread_id = new_topic.message_thread_id
        
        players_mentions = ", ".join(usernames_list)
        
        welcome_text = f"""🎮 <b>Brawl Stars Рума #{new_thread_id}</b>

👤 <b>Создатель:</b> @{user.username}
👥 <b>Состав:</b> {players_mentions}

────────────────

🎤 <b>Как запустить войс:</b>
Создатель нажимает на телефоне сверху справа <b>три точки -> Начать видеочат</b>.

🕒 <i>Автоудаление:</i> Через 30 минут, если в теме никто не пишет И в войсе пусто."""

        bot.send_message(
            chat_id=MAIN_CHAT_ID,
            text=welcome_text,
            message_thread_id=new_thread_id,
            reply_markup=get_room_keyboard()
        )

        with rooms_lock:
            active_rooms[new_thread_id] = {
                "creator_id": user.id,
                "creator_username": user.username,
                "last_activity": datetime.now(),
                "voice_active": False
            }
            
        logging.info(f"Успешно создана тема #{new_thread_id} для @{user.username}")

    except Exception as e:
        logging.error(f"Ошибка создания топика: {e}")
        bot.send_message(MAIN_CHAT_ID, f"❌ Не удалось создать тему. Ошибка: {e}. Убедись, что бот — АДМИН чата с правом управления темами!")

# ==========================================
# МОНИТОРИНГ АКТИВНОСТИ И ВОЙСА
# ==========================================

@bot.message_handler(func=lambda m: m.chat.id == MAIN_CHAT_ID and m.message_thread_id in active_rooms)
def track_room_messages(message):
    thread_id = message.message_thread_id
    with rooms_lock:
        if thread_id in active_rooms:
            active_rooms[thread_id]["last_activity"] = datetime.now()
            logging.info(f"Активность (сообщение) в руме #{thread_id}")

@bot.message_handler(content_types=['video_chat_started'])
def voice_started(message):
    thread_id = message.message_thread_id
    with rooms_lock:
        if thread_id in active_rooms:
            active_rooms[thread_id]["voice_active"] = True
            active_rooms[thread_id]["last_activity"] = datetime.now()
            logging.info(f"В руме #{thread_id} запущен войс чат!")

@bot.message_handler(content_types=['video_chat_ended'])
def voice_ended(message):
    thread_id = message.message_thread_id
    with rooms_lock:
        if thread_id in active_rooms:
            active_rooms[thread_id]["voice_active"] = False
            active_rooms[thread_id]["last_activity"] = datetime.now()
            logging.info(f"В руме #{thread_id} войс чат закрыт.")

# ==========================================
# УПРАВЛЕНИЕ КНОПКАМИ
# ==========================================

@bot.callback_query_handler(func=lambda call: call.data in ["room_extend", "room_delete"])
def handle_room_buttons(call):
    thread_id = call.message.message_thread_id
    user_id = call.from_user.id
    
    with rooms_lock:
        if thread_id not in active_rooms:
            bot.answer_callback_query(call.id, "❌ Рума не найдена.", show_alert=True)
            return
        room_data = active_rooms[thread_id]

    if user_id != room_data["creator_id"]:
        bot.answer_callback_query(call.id, "⚠️ Только создатель румы может нажимать кнопки!", show_alert=True)
        return

    if call.data == "room_extend":
        with rooms_lock:
            active_rooms[thread_id]["last_activity"] = datetime.now()
        bot.answer_callback_query(call.id, "⏳ Продлено на 30 минут!", show_alert=True)
        
    elif call.data == "room_delete":
        bot.answer_callback_query(call.id, "🗑 Удаление румы...")
        delete_room_topic(thread_id)

def delete_room_topic(thread_id):
    try:
        bot.delete_forum_topic(MAIN_CHAT_ID, thread_id)
        logging.info(f"Тема #{thread_id} удалена.")
    except Exception as e:
        logging.error(f"Не удалось удалить тему #{thread_id}: {e}")
        
    with rooms_lock:
        if thread_id in active_rooms:
            del active_rooms[thread_id]

# ==========================================
# ПОТОК АВТООЧИСТКИ
# ==========================================

def auto_cleaner_thread():
    logging.info("Поток очистки запущен.")
    while True:
        time.sleep(30)
        now = datetime.now()
        rooms_to_delete = []
        
        with rooms_lock:
            for thread_id, data in list(active_rooms.items()):
                # Если люди общаются голосом — НЕ удаляем
                if data["voice_active"]:
                    continue
                # Если войса нет и тишина в чате > 30 минут — удаляем
                if now - data["last_activity"] > timedelta(minutes=30):
                    rooms_to_delete.append(thread_id)
                    
        for thread_id in rooms_to_delete:
            logging.info(f"Рума #{thread_id} неактивна. Удаляем...")
            delete_room_topic(thread_id)

if __name__ == "__main__":
    cleaner = threading.Thread(target=auto_cleaner_thread, daemon=True)
    cleaner.start()
    
    logging.info("Бот перезапущен на базе Форум-Топиков...")
    
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            logging.error(f"Ошибка сети: {e}. Рестарт через 5 сек...")
            time.sleep(5)
