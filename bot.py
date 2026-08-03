#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Бот для Telegram-канала @neiro_dusha.
Генерация постов по схеме: Хук → Лид → Тело → Вывод → CTA → Темы → Хештеги.
Поддержка файла posts.txt, RSS, автопостинг каждые 6 часов.
"""

import os
import io
import json
import time
import logging
import random
import re
import requests
import threading
import schedule
import feedparser
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

# ---------- НАСТРОЙКИ ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PIXAZO_API_KEY = os.getenv("PIXAZO_API_KEY")   # не используется, но оставим
POLLINATIONS_BASE_URL = os.getenv("POLLINATIONS_BASE_URL")
IMAGE_NEGATIVE_PROMPT = os.getenv("IMAGE_NEGATIVE_PROMPT", "ugly, deformed, blurry...")
RSS_SOURCES_JSON = os.getenv("RSS_SOURCES", '[]')
RSS_ENABLED = os.getenv("RSS_ENABLED", "false").lower() == "true"
DATA_DIR = os.getenv("DATA_DIR", "./data")

if not TELEGRAM_TOKEN or not CHANNEL_ID:
    raise ValueError("TELEGRAM_TOKEN и CHANNEL_ID обязательны!")

os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(DATA_DIR, "post_state.json")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("bot")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ---------- ЗАГРУЗКА ПОСТОВ ИЗ ФАЙЛА ----------
POSTS_FILE = "posts.txt"

def load_posts_from_file():
    posts = []
    if not os.path.exists(POSTS_FILE):
        return None
    try:
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        blocks = re.split(r'\n===', content)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            if block.startswith('==='):
                block = block[3:].strip()
            lines = block.split('\n')
            if not lines:
                continue
            title = lines[0].strip()
            text = '\n'.join(lines[1:]).strip()
            if title and text:
                posts.append({'title': title, 'text': text})
        if posts:
            logger.info(f"✅ Загружено {len(posts)} готовых постов из {POSTS_FILE}")
            return posts
    except Exception as e:
        logger.error(f"Ошибка чтения {POSTS_FILE}: {e}")
    return None

# ---------- RSS ПАРСИНГ ----------
def get_rss_entries(sources_json):
    sources = json.loads(sources_json) if sources_json else []
    entries = []
    for src in sources:
        url = src.get("url")
        if not url:
            continue
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if title:
                    entries.append(title)
            logger.info(f"RSS {url}: получено {len(entries)} заголовков")
        except Exception as e:
            logger.error(f"Ошибка парсинга RSS {url}: {e}")
    return entries

# ---------- ЗАПАСНЫЕ ТЕМЫ (AI) ----------
def load_topics():
    try:
        with open("topics.txt", "r", encoding="utf-8") as f:
            topics = [line.strip() for line in f if line.strip()]
        if topics:
            return topics
    except FileNotFoundError:
        pass
    return [
        "Искусственный интеллект в бизнесе",
        "Нейросети в медицине",
        "Обучение с подкреплением",
        "Этика ИИ",
        "Генеративные модели",
        "Обработка естественного языка",
        "Компьютерное зрение",
        "Робототехника и ИИ",
        "Будущее работы с ИИ",
        "ИИ в творчестве"
    ]

# ---------- TELEGRAM ----------
def send_message(chat_id, text, photo_bytes=None):
    if photo_bytes:
        files = {"photo": ("image.jpg", photo_bytes, "image/jpeg")}
        data = {"chat_id": chat_id, "caption": text}
        return requests.post(f"{BASE_URL}/sendPhoto", data=data, files=files).json()
    else:
        return requests.post(f"{BASE_URL}/sendMessage", json={"chat_id": chat_id, "text": text}).json()

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    return requests.get(f"{BASE_URL}/getUpdates", params=params).json().get("result", [])

# ======================================================================
#  ГЕНЕРАЦИЯ ПОСТА ПО СХЕМЕ (AI ТЕМАТИКА)
# ======================================================================

def generate_post_by_schema(topic: str) -> str:
    if AGNES_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
            prompt = f"""
Тема: {topic}.

Напиши пост для Telegram-канала о нейросетях и искусственном интеллекте строго по схеме:

1. **Заголовок (хук):** максимум 5–7 слов, цепляющий, бьёт в боль или интерес. Начинай с эмодзи 🔥, ⚡, 🚀, 😤, 💥.

2. **Вступление (лид):** 3–4 предложения, которые раскрывают проблему. Используй риторический вопрос или жизненную ситуацию. Читатель должен узнать себя.

3. **Тело (основной блок):** 3–6 пунктов. Каждый пункт:
   - Начинается с эмодзи (🔥, 😤, 🧘, 💪, 📌, 💡, ⚡, 🚀).
   - Короткий заголовок (2–4 слова).
   - 2–3 предложения пояснения с примером или конкретной рекомендацией.

4. **Вывод / мораль:** 2–3 коротких предложения, которые подводят итог. Без воды. Дают надежду или вдохновение.

5. **CTA (призыв к действию):** конкретный вопрос к аудитории. Формула: «А у тебя было такое?», «Как ты с этим справляешься?» и т.п.

6. **Темы для комментариев (3 штуки):** три конкретных вопроса для разгона дискуссии.

7. **Хештеги:** 7–12 хештегов по теме (без спама).

Пост должен быть живым, эмоциональным, без канцелярита. Используй эмодзи, разбивай на абзацы. 
"""
            data = {
                "model": "agnes-v1",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800,
                "temperature": 0.85
            }
            resp = requests.post("https://apihub.agnes-ai.cn/v1/chat/completions", json=data, headers=headers, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                if text and len(text) > 100:
                    logger.info("✅ Agnes сгенерировал пост по схеме")
                    return text.strip()
        except Exception as e:
            logger.warning(f"Agnes не сработал: {e}")

    return build_post_from_templates(topic)

def build_post_from_templates(topic: str) -> str:
    # 1. Хуки (заголовки)
    hooks = [
        f"🔥 {topic.upper()} – ЭТО НЕ ПРОГНОЗ, А РЕАЛЬНОСТЬ",
        f"⚡ {topic.upper()} МЕНЯЕТ ВСЁ. ТЫ ГОТОВ?",
        f"🚀 {topic.upper()} – ТВОЙ ШАНС ИЗМЕНИТЬ ЖИЗНЬ",
        f"😤 {topic.upper()} – ВОТ ПОЧЕМУ ТЫ ОТСТАЁШЬ",
        f"💥 {topic.upper()} – ЭТО БОЛЬШЕ, ЧЕМ ТЫ ДУМАЕШЬ"
    ]
    hook = random.choice(hooks)

    # 2. Лиды (вступления)
    leads = [
        f"Ты когда-нибудь задумывался, почему {topic} вызывает столько споров? Одни говорят, что это будущее, другие – что это пустышка. Но факты упрямы: уже сегодня тысячи компаний внедряют ИИ и получают результат.",
        f"Представь: ты просыпаешься, а твой помощник уже спланировал день, нашёл лучшие решения, сэкономил часы работы. Звучит как фантастика? А это уже реальность. {topic} врывается в нашу жизнь.",
        f"Почему мы боимся {topic}? Потому что не понимаем. Но давай разберёмся – это просто инструмент. И как любой инструмент, его можно использовать во благо или во вред."
    ]
    lead = random.choice(leads)

    # 3. Тело – пункты (AI)
    body_pool = [
        ("🔥", "Автоматизация рутины", "ИИ берёт на себя скучные задачи: от обработки документов до планирования. Ты освобождаешь время для творчества."),
        ("💡", "Анализ данных", "Нейросети находят закономерности, которые человек не видит. Это помогает принимать решения быстрее и точнее."),
        ("🧘", "Этика и безопасность", "Важно помнить: ИИ – это не замена человека, а помощник. Вопросы приватности и ответственности уже решаются."),
        ("⚡", "Скорость внедрения", "Технологии развиваются экспоненциально. То, что казалось фантастикой вчера, сегодня – реальность."),
        ("📌", "Обучение и адаптация", "Чтобы быть в тренде, нужно постоянно учиться. Нейросети уже помогают в образовании и переквалификации."),
        ("🚀", "Инновации и стартапы", "ИИ открывает новые рынки. Стартапы на базе AI растут быстрее и привлекают инвестиции."),
        ("💪", "Конкурентоспособность", "Компании, которые внедряют AI, увеличивают прибыль на 30–40%."),
        ("🔍", "Прогнозирование", "ИИ помогает предсказывать тренды, спрос, риски – это даёт преимущество."),
        ("🛡️", "Кибербезопасность", "Нейросети защищают от атак быстрее человека."),
        ("🌍", "Глобальные решения", "ИИ помогает решать проблемы экологии, медицины, логистики – меняет мир к лучшему.")
    ]
    random.shuffle(body_pool)
    selected = body_pool[:random.randint(3, 6)]
    body = "\n".join([f"{emoji} **{title}**\n{desc}" for emoji, title, desc in selected])

    # 4. Вывод
    conclusions = [
        f"Итог прост: {topic} – это не будущее, это уже настоящее. Начни использовать его сегодня, чтобы не отстать завтра.",
        "Главное – не бояться, а учиться. ИИ – это инструмент, который делает нас сильнее.",
        "Технологии приходят, чтобы помочь. От нас зависит, как мы их используем."
    ]
    conclusion = random.choice(conclusions)

    # 5. CTA
    cta_questions = [
        f"👇 А ты уже используешь {topic} в работе или жизни? Как?",
        f"👇 Что тебе мешает внедрить {topic}? Страх? Незнание?",
        f"👇 Согласен, что {topic} меняет правила игры? Почему да или нет?"
    ]
    cta = random.choice(cta_questions)

    # 6. Темы для комментариев
    comments_themes = [
        "1. «Какие сферы, по-твоему, ИИ изменит больше всего?» – обсудим перспективы.",
        "2. «Ты бы доверил ИИ принимать важные решения?» – поделитесь опытом.",
        "3. «Какой инструмент на базе ИИ ты используешь чаще всего?» – дайте рекомендации."
    ]
    themes = "\n".join(comments_themes)

    # 7. Хештеги
    base_hashtags = ["#искусственныйинтеллект", "#нейросети", "#технологии", "#будущее", "#инновации", "#ai", "#digital", "#automatization"]
    extra = [f"#{topic.replace(' ', '').lower()}" for _ in range(3)]
    hashtags = list(set(base_hashtags + extra))[:10]
    hashtag_str = " ".join(hashtags)

    post = f"{hook}\n\n{lead}\n\n{body}\n\n{conclusion}\n\n{cta}\n\nТемы для обсуждения:\n{themes}\n\n{hashtag_str}"
    return post

# ======================================================================
#  КАРТИНКИ
# ======================================================================

def search_pexels_relevant_photo(topic):
    if not PEXELS_API_KEY:
        return None
    queries = [f"artificial intelligence {topic}", f"technology {topic}", f"innovation {topic}"]
    random.shuffle(queries)
    for query in queries[:3]:
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": query, "per_page": 3, "orientation": "landscape"}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                photos = data.get("photos", [])
                if photos:
                    return random.choice(photos)["src"]["large2x"]
        except:
            pass
    return None

def download_photo(url):
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            return resp.content
    except:
        pass
    return None

def generate_image(topic):
    if PEXELS_API_KEY:
        photo_url = search_pexels_relevant_photo(topic)
        if photo_url:
            img = download_photo(photo_url)
            if img:
                return img, "Pexels"
    # Баннер
    img = Image.new('RGB', (1024, 1024), color='#0a0a2e')
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
    except:
        font = ImageFont.load_default()
    draw.text((50, 400), topic[:20], fill='#FFD700', font=font)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue(), "баннер"

# ---------- ПУБЛИКАЦИЯ В КАНАЛ ----------
def publish_to_channel(text, image_bytes):
    try:
        if image_bytes:
            resp = send_message(CHANNEL_ID, text, photo_bytes=image_bytes)
        else:
            resp = send_message(CHANNEL_ID, text)
        if resp.get("ok"):
            return "✅ Пост опубликован в канале"
        else:
            return f"❌ Ошибка: {resp.get('description')}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

def create_post_content(title, text=None):
    if text and len(text) > 50:
        post_text = None
        if AGNES_API_KEY:
            try:
                headers = {"Authorization": f"Bearer {AGNES_API_KEY}", "Content-Type": "application/json"}
                prompt = f"Перепиши следующий текст, чтобы он стал более живым, добавь эмодзи, абзацы, сделай его как пост популярного блогера о нейросетях. Текст:\n\n{text}"
                data = {
                    "model": "agnes-v1",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 600,
                    "temperature": 0.8
                }
                resp = requests.post("https://apihub.agnes-ai.cn/v1/chat/completions", json=data, headers=headers, timeout=30)
                if resp.status_code == 200:
                    rewritten = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    if rewritten and len(rewritten) > 100:
                        post_text = rewritten.strip()
                        logger.info("✅ Рерайт через Agnes выполнен")
            except Exception as e:
                logger.warning(f"Рерайт не удался: {e}")
        if not post_text:
            post_text = text
    else:
        post_text = generate_post_by_schema(title)

    image_bytes, source = generate_image(title)
    return post_text, image_bytes, source

def publish_post_item(title, text=None):
    post_text, image_bytes, source = create_post_content(title, text)
    result = publish_to_channel(post_text, image_bytes)
    return {"channel": result, "source": source}

# ---------- ПОЛУЧЕНИЕ СЛЕДУЮЩЕГО ПОСТА ----------
POSTS_POOL = None

def build_posts_pool():
    global POSTS_POOL
    posts = load_posts_from_file()
    if posts:
        POSTS_POOL = posts
        logger.info("📚 Используем посты из файла posts.txt")
        return

    if RSS_ENABLED and RSS_SOURCES_JSON and RSS_SOURCES_JSON != '[]':
        entries = get_rss_entries(RSS_SOURCES_JSON)
        if entries:
            POSTS_POOL = [{'title': t, 'text': None} for t in entries]
            logger.info(f"📚 Используем RSS-заголовки: {len(POSTS_POOL)} тем")
            return

    topics = load_topics()
    POSTS_POOL = [{'title': t, 'text': None} for t in topics]
    logger.info(f"📚 Используем запасной список тем: {len(POSTS_POOL)}")

def get_posts_pool():
    global POSTS_POOL
    if POSTS_POOL is None:
        build_posts_pool()
    return POSTS_POOL

def get_next_post():
    pool = get_posts_pool()
    if not pool:
        return None, None
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    used_indices = state.get(today, [])
    available = [i for i in range(len(pool)) if i not in used_indices]
    if not available:
        available = list(range(len(pool)))
        used_indices = []
    idx = random.choice(available)
    used_indices.append(idx)
    state[today] = used_indices
    save_state(state)
    post = pool[idx]
    return post['title'], post['text']

# ---------- СОСТОЯНИЕ ----------
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# ---------- ПЛАНИРОВЩИК ----------
def scheduled_post():
    logger.info("⏰ Автопостинг (каждые 6 часов)")
    try:
        title, text = get_next_post()
        if not title:
            logger.warning("Нет доступных постов для публикации")
            return
        result = publish_post_item(title, text)
        logger.info(f"Результат: {result}")
    except Exception as e:
        logger.error(f"Ошибка автопостинга: {e}")

def scheduler_worker():
    logger.info("📡 Планировщик запущен (4 поста в сутки)")
    scheduled_post()
    schedule.every(6).hours.do(scheduled_post)
    while True:
        schedule.run_pending()
        time.sleep(60)

# ---------- КОМАНДЫ ----------
def handle_command(chat_id, text):
    if text in ("/start", "/help"):
        send_message(chat_id,
            "🤖 Бот для канала @neiro_dusha – посты по схеме!\n"
            "📌 Команды:\n"
            "/post <заголовок> — сгенерировать пост\n"
            "/post <текст (длиннее 50 символов)> — опубликовать с рерайтом\n"
            "/ping — проверка\n"
            "/status — статистика"
        )
        return
    if text == "/ping":
        send_message(chat_id, "🏓 Pong!")
        return
    if text == "/status":
        state = load_state()
        today = datetime.now().strftime("%Y-%m-%d")
        used = state.get(today, [])
        total = len(get_posts_pool())
        send_message(chat_id, f"📊 Сегодня опубликовано {len(used)} постов из {total}.")
        return
    if text.startswith("/post"):
        content = text.replace("/post", "").strip()
        if not content:
            send_message(chat_id, "❌ Укажите тему или готовый текст.")
            return
        if len(content) > 50:
            title = content[:50] + "..."
            result = publish_post_item(title, content)
        else:
            result = publish_post_item(content)
        send_message(chat_id, f"📌 Канал: {result['channel']}")
        return

# ---------- ЗАПУСК ----------
def main():
    logger.info("🚀 Бот запущен")
    threading.Thread(target=scheduler_worker, daemon=True).start()
    last_update_id = 0
    while True:
        try:
            updates = get_updates(offset=last_update_id + 1)
            if updates:
                for update in updates:
                    last_update_id = update["update_id"]
                    if "message" in update:
                        msg = update["message"]
                        chat_id = msg["chat"]["id"]
                        if "text" in msg:
                            handle_command(chat_id, msg["text"].strip())
            time.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()