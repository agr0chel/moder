import asyncio
import logging
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8977762737:AAH41De5wenqnI7qTCAk2D1YeJXSJPyBEKU"
SUPERGROUP_ID = -1004292550506
LOG_TOPIC_ID = 136
CREATOR_ID = 6542186960
# ---------------------

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Список ID пользователей, которым разрешено модерировать
allowed_moderators = {CREATOR_ID}

# Хранилище варнов. Формат: {user_id: [datetime_expire1, datetime_expire2, ...]}
moderator_warns = {}

def parse_duration(time_str: str) -> timedelta:
    """Парсит время из текста команды"""
    digits_match = re.search(r'\d+', time_str)
    digits = int(digits_match.group()) if digits_match else 1
    
    if 'час' in time_str:
        return timedelta(hours=digits)
    elif 'мин' in time_str:
        return timedelta(minutes=digits)
    elif 'ден' in time_str or 'дня' in time_str or 'дне' in time_str:
        return timedelta(days=digits)
    return timedelta(hours=digits)

def clean_expired_warns(user_id: int):
    """Удаляет истекшие варны у пользователя"""
    if user_id in moderator_warns:
        now = datetime.now()
        moderator_warns[user_id] = [expire for expire in moderator_warns[user_id] if expire > now]
        if not moderator_warns[user_id]:
            del moderator_warns[user_id]

async def wait_and_remove_warn(user_id: int, expire_time: datetime, target_username: str, duration_seconds: float):
    """Фоновая задача, которая ждет окончания варна и уведомляет об этом"""
    await asyncio.sleep(duration_seconds)
    
    # Проверяем, существует ли еще этот варн (его могли снять вручную командой анварн)
    if user_id in moderator_warns and expire_time in moderator_warns[user_id]:
        moderator_warns[user_id].remove(expire_time)
        
        # Считаем, сколько осталось активных
        clean_expired_warns(user_id)
        remains = len(moderator_warns.get(user_id, []))
        
        log_message = f"⏱ Время предупреждения {target_username} истекло, предупреждение снято. Осталось предупреждений: **{remains}**."
        try:
            # ИСПРАВЛЕНО: явная отправка в топик супергруппы
            await bot.send_message(
                chat_id=SUPERGROUP_ID, 
                message_thread_id=LOG_TOPIC_ID, 
                text=log_message, 
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Ошибка при отправке лога об истечении варна: {e}")

# Управление списком модераторов через ЛС бота
@dp.message(F.chat.type == "private")
async def handle_private_config(message: types.Message):
    if message.from_user.id != CREATOR_ID:
        return
    
    if message.text and message.text.isdigit():
        new_mod_id = int(message.text)
        allowed_moderators.add(new_mod_id)
        if new_mod_id in moderator_warns:
            del moderator_warns[new_mod_id]
        await message.answer(f"✅ Пользователь {new_mod_id} добавлен в список модераторов бота.")
    else:
        await message.answer("Пришли мне числовой Telegram ID пользователя, чтобы разрешить ему использовать команды мута/бана/варна.")

# Обработка команд модерации в супергруппе
@dp.message(F.chat.id == SUPERGROUP_ID)
async def handle_moderation_commands(message: types.Message):
    clean_expired_warns(message.from_user.id)
    
    if message.from_user.id not in allowed_moderators:
        return

    text = message.text.lower() if message.text else ""
    if not (text.startswith("мут") or text.startswith("бан") or text.startswith("варн") or text.startswith("анварн")):
        return

    target_user_id = None
    target_username = "Пользователь"

    # Определяем, кого наказывать (через reply или упоминание)
    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
        user = message.reply_to_message.from_user
        target_username = f"@{user.username}" if user.username else f"[{user.first_name}](tg://user?id={user.id})"
    elif message.entities:
        for entity in message.entities:
            if entity.type == "text_mention":
                target_user_id = entity.user.id
                target_username = f"[{entity.user.first_name}](tg://user?id={entity.user.id})"
                break

    if not target_user_id:
        return

    admin_username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    try:
        # --- ЛОГИКА АНВАРНА ---
        if text.startswith("анварн"):
            clean_expired_warns(target_user_id)
            
            if target_user_id not in moderator_warns or not moderator_warns[target_user_id]:
                # ИСПРАВЛЕНО: ответ в тот же топик, откуда пришла команда
                await message.reply("У этого пользователя нет активных предупреждений.")
                return
                
            # Удаляем последний выданный варн
            moderator_warns[target_user_id].pop()
            remains = len(moderator_warns[target_user_id])
            
            if remains == 0:
                del moderator_warns[target_user_id]
                
            log_message = f"🔓 {admin_username} снял предупреждение с {target_username}. Осталось предупреждений: **{remains}**."
            # ИСПРАВЛЕНО: отправка в лог-ветку
            await bot.send_message(
                chat_id=SUPERGROUP_ID, 
                message_thread_id=LOG_TOPIC_ID, 
                text=log_message, 
                parse_mode="Markdown"
            )
            return

        # Извлекаем время для остальных команд
        time_match = re.search(r'\d+\s*(час|мин|ден|дня|дне)', text)
        duration_str = time_match.group() if time_match else "1 час"
        duration = parse_duration(duration_str)
        until_date = datetime.now() + duration

        # --- ЛОГИКА МУТА ---
        if text.startswith("мут"):
            await bot.restrict_chat_member(
                chat_id=SUPERGROUP_ID,
                user_id=target_user_id,
                permissions=types.ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            log_message = f"🛡 {admin_username} выдал **мут** глобально на **{duration_str}** пользователю {target_username}."
            await bot.send_message(chat_id=SUPERGROUP_ID, message_thread_id=LOG_TOPIC_ID, text=log_message, parse_mode="Markdown")

        # --- ЛОГИКА БАНА ---
        elif text.startswith("бан"):
            await bot.ban_chat_member(
                chat_id=SUPERGROUP_ID,
                user_id=target_user_id,
                until_date=until_date
            )
            log_message = f"❌ {admin_username} выдал **бан** глобально на **{duration_str}** пользователю {target_username}."
            await bot.send_message(chat_id=SUPERGROUP_ID, message_thread_id=LOG_TOPIC_ID, text=log_message, parse_mode="Markdown")

        # --- ЛОГИКА ВАРНА ---
        elif text.startswith("варн"):
            clean_expired_warns(target_user_id)
            
            if target_user_id not in moderator_warns:
                moderator_warns[target_user_id] = []
                
            moderator_warns[target_user_id].append(until_date)
            current_warns = len(moderator_warns[target_user_id])
            
            log_message = f"⚠️ {admin_username} выдал предупреждение {target_username} на **{duration_str}**. Количество предупреждений {target_username}: **{current_warns}**."
            
            if current_warns >= 3:
                if target_user_id in allowed_moderators:
                    allowed_moderators.remove(target_user_id)
                if target_user_id in moderator_warns:
                    del moderator_warns[target_user_id]
                
                log_message += f"\n\n🚨 Пользователь {target_username} набрал **3/3 варнов** и был **удален из списка модераторов**!"
            else:
                # Запускаем таймер на снятие варна в фоновом режиме
                asyncio.create_task(
                    wait_and_remove_warn(
                        user_id=target_user_id, 
                        expire_time=until_date, 
                        target_username=target_username, 
                        duration_seconds=duration.total_seconds()
                    )
                )

            await bot.send_message(chat_id=SUPERGROUP_ID, message_thread_id=LOG_TOPIC_ID, text=log_message, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Ошибка при выполнении команды: {e}")

async def main():
    print("Бот успешно запущен и защищает чат!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
