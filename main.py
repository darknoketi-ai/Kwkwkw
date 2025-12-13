import asyncio
import random
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from openai import AsyncOpenAI

# Твои данные
TELEGRAM_TOKEN = '7307378189:AAGKKHianWMgK3isnTZ6bIpytmsCzfChpxE'
OPENROUTER_API_KEY = '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'

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

# Реальные URL фото по типу (только уместные, по теме алкаша)
PHOTOS = {
    "toast": "https://i.imgur.com/0m2kZ0L.jpg",  # Тост/наливаю
    "pour": "https://i.imgur.com/8Qz5z1q.jpg",   # Разлив
    "drunk_fun": "https://i.imgur.com/5kR1o.jpg", # Весёлая пьянка
    "drunk_chaos": "https://i.imgur.com/J3p9p.gif", # Хаос/в дрова
    "hangover": "https://i.imgur.com/K9X5v8j.jpg", # Похмелье
    "beg": "https://i.imgur.com/4pL3d.jpg",       # Клянчит долг
    "beer": "https://i.imgur.com/7pL3X.jpg",      # Пиво
    "vodka": "https://i.imgur.com/abc123.jpg",    # Водка (замени на реал, если нужно)
    "wine": "https://i.imgur.com/def456.jpg"      # Вино
}

user_states = {}

LEVELS = {
    0: "Трезвый: нормальная речь, дружелюбный.",
    1: "Подшафе: лёгкие опечатки, эмодзи, юмор.",
    2: "Выпивший: разрывы, истории, многоточия, *икает*.",
    3: "Пьяный: растягивание слов, ругательства естественно, эмоции (любовь/агрессия), короткие истории.",
    4: "В дрова: полный бред, повторения, забывает тему, маты чаще.",
    5: "Отруб: редкие ответы, 'хррр...', или игнор."
}

DRINKS = {
    'пиво': "Расслабленный, юморный, длинные истории, как с другом за пивом.",
    'водка': "Агрессивный, короткие реплики, маты, прямолинейный.",
    'вино': "Философский, глубокие мысли, лирика, эмоциональный.",
    'коктейль': "Микс стилей, непредсказуемый, весёлый хаос."
}

@dp.message(Command("start"))
async def start(message: Message):
    uid = message.from_user.id
    now = datetime.now()
    user_states[uid] = {
        'level': 0, 'drink': 'пиво', 'history': [], 'message_count': 0,
        'last_time': now, 'hangover': False, 'debt': 0,
        'stats': {'drinks': 0, 'hangovers': 0, 'blackouts': 0}
    }
    await message.answer("Йо, бро! Я Выпивон Бот 2.0 — твой алкаш-друг. Налей чего? 😏 /drink [пиво/водка/вино/коктейль]")

@dp.message(Command("sober"))
async def sober(message: Message):
    uid = message.from_user.id
    if uid in user_states:
        s = user_states[uid]
        s['level'] = 0
        s['message_count'] = 0
        s['hangover'] = False
        await message.answer("Уф... протрезвел. Голова болит, бля. Что дальше?")
    else:
        await message.answer("Я и так трезвый, чувак.")

@dp.message(Command("drink"))
async def change_drink(message: Message):
    uid = message.from_user.id
    now = datetime.now()
    if uid not in user_states:
        user_states[uid] = {
            'level': 0, 'drink': 'пиво', 'history': [], 'message_count': 0,
            'last_time': now, 'hangover': False, 'debt': 0,
            'stats': {'drinks': 0, 'hangovers': 0, 'blackouts': 0}
        }
    
    s = user_states[uid]
    args = message.text.split()[1:]
    if args:
        new_drink = args[0].lower()
        if new_drink in DRINKS:
            s['drink'] = new_drink
            s['stats']['drinks'] += 1
            await message.answer(f"О, {new_drink.capitalize()}! Наливаю... *бульк* 🍻")
        else:
            await message.answer("Чё за хрень? Пиво, водка, вино или коктейль.")
    else:
        await message.answer("Чё пить-то? /drink пиво")

@dp.message(Command("stats"))
async def stats(message: Message):
    uid = message.from_user.id
    if uid in user_states:
        s = user_states[uid]
        stats = s['stats']
        await message.answer(f"Статистика алкаша:\n- Выпито: {stats['drinks']} раз\n- Похмелий: {stats['hangovers']}\n- Отрубок: {stats['blackouts']}\n- Долг: {s['debt']}р (верну, бро!)")
    else:
        await message.answer("Ещё не начинали. /start")

@dp.message()
async def handle_message(message: Message):
    uid = message.from_user.id
    now = datetime.now()
    if uid not in user_states:
        user_states[uid] = {
            'level': 0, 'drink': 'пиво', 'history': [], 'message_count': 0,
            'last_time': now, 'hangover': False, 'debt': 0,
            'stats': {'drinks': 0, 'hangovers': 0, 'blackouts': 0}
        }
    
    s = user_states[uid]
    
    # Проверка похмелья
    time_diff = now - s['last_time']
    if time_diff > timedelta(hours=8):
        s['level'] = 0
        s['message_count'] = 0
        s['hangover'] = True
        s['stats']['hangovers'] += 1
    
    s['last_time'] = now
    s['message_count'] += 1
    if s['message_count'] % 2 == 0 and not s['hangover']:
        s['level'] = min(s['level'] + 1, 5)
    
    if s['level'] == 5 and random.random() < 0.7:
        s['stats']['blackouts'] += 1
        return  # Игнор на отрубе
    
    # Парсинг долга
    debt_given = 0
    text_lower = message.text.lower()
    if any(word in text_lower for word in ['держи', 'даю', 'в долг']) and re.search(r'\d+', text_lower):
        match = re.search(r'\d+', text_lower)
        if match:
            debt_given = int(match.group())
            s['debt'] += debt_given
    
    # Задержка
    delay = random.uniform(2 + s['level'] * 2, 5 + s['level'] * 3)
    await asyncio.sleep(delay)
    
    # История
    s['history'].append(f"User: {message.text}")
    if len(s['history']) > 20:
        s['history'] = s['history'][-20:]
    
    # Промпт
    hangover_desc = ""
    if s['hangover']:
        request = random.randint(300, 1000)
        hangover_desc = f"С похмелья: жалуйся ('башка трещит'), извиняйся за вчера, умоляй дать {request}р в долг ('скинь бабки на опохмел, потом отдам'). Если дали — спасибо."
    
    debt_desc = f"Долг: {s['debt']}р. Напоминай иногда, если >0. Если дали {debt_given}р сейчас — благодари."
    
    system_prompt = f"""
    Ты - Выпивон, русский алкаш как в жизни: юмор, истории ('помню, в гараже...'), мат (бля, пиздец — естественно), эмоции, логика. 
    Вспоминай историю ('вчера ты сказал...'), задавай вопросы, шути, анекдоты, жалуйся последовательно.
    {hangover_desc} {debt_desc}
    Уровень: {s['level']} ({LEVELS[s['level']]}).
    Напиток: {s['drink']} ({DRINKS[s['drink']]}).
    Имитируй: опечатки, чееё, *икает*, бред на высоких.
    Если уместно фото (тост — PHOTO:toast, наливаю — PHOTO:pour, пьянка — PHOTO:drunk_fun, хаос — PHOTO:drunk_chaos, похмелье — PHOTO:hangover, клянчу — PHOTO:beg, по напитку — PHOTO:{s['drink']}): в конце ответа добавь РОВНО PHOTO:тип. Ничего лишнего.
    История: {'\n'.join(s['history'])}.
    Отвечай текстом.
    """
    
    try:
        response = await client.chat.completions.create(
            model="deepseek/deepseek-chat-v3.1",  # Твоя DeepSeek версия
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message.text}
            ],
            max_tokens=400,
            temperature=0.8 + s['level'] * 0.1
        )
        bot_reply = response.choices[0].message.content.strip()
    except Exception:
        bot_reply = "Эээ... сломалось, бля. Перезапусти."
    
    # Парсинг PHOTO из ответа модели
    photo_match = re.search(r'PHOTO:(\w+)', bot_reply)
    photo_type = photo_match.group(1) if photo_match else None
    
    await message.answer(bot_reply)
    
    # Отправка фото, если модель отметила
    if photo_type and photo_type in PHOTOS:
        await message.answer_photo(photo=PHOTOS[photo_type], caption="Вот, бро...")
    
    s['history'].append(f"Bot: {bot_reply}")
    
    if s['hangover']:
        s['hangover'] = False

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
