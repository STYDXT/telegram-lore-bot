from __future__ import annotations

import asyncio
import base64
import logging
import random
import re
import time
from collections import defaultdict
from io import BytesIO

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ChatType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from config import settings
from llm import ask_character

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("lore-bot")

bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

histories = defaultdict(list)
locks = defaultdict(asyncio.Lock)
idle_counts = defaultdict(int)
last_speak = defaultdict(float)
bot_username = ""
TG_LIMIT = 3900
TRIGGER_RE = re.compile(r"(?i)\b(пашк[ауие]?|паша|пашке|пашу|пашкой|pashka|pasha|бот)\w*")


def allowed(message):
    ids = settings.allowed_ids
    if not ids:
        return True
    user = message.from_user
    return bool(user and user.id in ids)


def trim_history(chat_id):
    limit = max(8, settings.history_limit)
    if len(histories[chat_id]) > limit:
        histories[chat_id] = histories[chat_id][-limit:]


def split_text(text):
    if len(text) <= TG_LIMIT:
        return [text]
    chunks = []
    rest = text
    while rest:
        if len(rest) <= TG_LIMIT:
            chunks.append(rest)
            break
        cut = rest.rfind("\n", 0, TG_LIMIT)
        if cut < 500:
            cut = TG_LIMIT
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return chunks


async def reply_long(message, text):
    for chunk in split_text(text):
        await message.reply(chunk)


def speaker_label(message):
    user = message.from_user
    if not user:
        return "кто-то"
    name = user.full_name or user.first_name or "кто-то"
    if user.username:
        return name + " @" + user.username
    return name


def is_private(message):
    return message.chat.type == ChatType.PRIVATE


def mentioned_bot(message):
    text = message.text or message.caption or ""
    if bot_username and ("@" + bot_username.lower()) in text.lower():
        return True
    return False


def replied_to_bot(message):
    reply = message.reply_to_message
    if not reply or not reply.from_user:
        return False
    return bool(reply.from_user.is_bot and reply.from_user.id == bot.id)


def should_answer(message):
    if is_private(message):
        return True
    if replied_to_bot(message) or mentioned_bot(message):
        return True
    text = message.text or ""
    return bool(TRIGGER_RE.search(text))


@dp.message(CommandStart())
async def cmd_start(message: Message):
    if not allowed(message):
        return
    await message.answer("Ну здарова. Я на месте, если шо.\n/reset — забыть этот чат.")


@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    if not allowed(message):
        return
    histories.pop(message.chat.id, None)
    await message.answer("Забыл.")


@dp.message(F.photo)
async def on_photo(message: Message):
    if not allowed(message):
        return
    caption = (message.caption or "").strip()
    text = speaker_label(message) + ": скинул фото"
    if caption:
        text = speaker_label(message) + ": " + caption + " [фото]"
    force = is_private(message) or replied_to_bot(message) or mentioned_bot(message) or bool(TRIGGER_RE.search(caption))
    photo = message.photo[-1]
    buf = BytesIO()
    await bot.download(photo, destination=buf)
    raw = buf.getvalue()
    if not raw:
        await message.reply("Фото не открылось.")
        return
    image_url = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
    await _talk(message, text, extra="Посмотри фото и скажи что там своим языком.", force=force, image_data_url=image_url)


@dp.message(F.text)
async def on_text(message: Message):
    if not allowed(message):
        return
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return
    await _talk(message, speaker_label(message) + ": " + text, force=False)


async def _talk(message, user_text, extra="", force=False, image_data_url=None):
    chat_id = message.chat.id
    async with locks[chat_id]:
        histories[chat_id].append({"role": "user", "content": user_text})
        trim_history(chat_id)
        want = force or should_answer(message)
        if not want:
            idle_counts[chat_id] += 1
            quiet = time.time() - last_speak[chat_id]
            if (not is_private(message) and idle_counts[chat_id] >= 8 and quiet > 300 and random.random() < 0.12):
                want = True
                extra = extra + " Сам коротко влезь в разговор. Без вопросов в конце."
            else:
                return
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        try:
            answer = await ask_character(histories[chat_id], extra_instruction=extra, image_data_url=image_data_url)
        except Exception as e:
            log.exception("LLM error")
            histories[chat_id].pop()
            await message.reply("Ошибка модели: " + str(e)[:300])
            return
        histories[chat_id].append({"role": "assistant", "content": answer})
        trim_history(chat_id)
        idle_counts[chat_id] = 0
        last_speak[chat_id] = time.time()
        await reply_long(message, answer)


async def main():
    global bot_username
    me = await bot.get_me()
    bot_username = me.username or ""
    log.info("Bot started as @%s", bot_username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
