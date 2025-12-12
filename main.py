import os
import asyncio
import logging
import tempfile
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pathlib import Path
import json

import yt_dlp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile, CallbackQuery, Voice, Audio, Video, Document
)
from aiogram.filters import Command, StateFilter
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
import aiohttp
import subprocess
import re
from urllib.parse import urlparse
import shutil

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ПРОВЕРКА FFMPEG ====================
def check_ffmpeg():
    """Проверяем наличие FFmpeg"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=5)
        logger.info(f"✅ FFmpeg найден: {result.stdout.split()[2]}")
        return True
    except Exception as e:
        logger.error(f"❌ FFmpeg не найден: {e}")
        return False

# Проверяем при старте
if not check_ffmpeg():
    logger.warning("⚠️ FFmpeg не установлен, конвертация аудио не будет работать!")

# ==================== ТОКЕНЫ ====================
TOKEN = "7988209205:AAF7_jXtcuDePrnpokwexs1Z2FT4TPe-q-M"
AUDD_TOKEN = "0e8ca9553c9f41c744cb31ad04de2915"

# ==================== ИНИЦИАЛИЗАЦИЯ БОТА ====================
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_main_keyboard():
    """Создает главную клавиатуру"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="📥 Скачать видео")
    builder.button(text="🎵 Распознать музыку")
    builder.button(text="🎙 В голосовое")
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def is_url(text: str) -> bool:
    """Проверяет, является ли текст ссылкой"""
    try:
        result = urlparse(text)
        return all([result.scheme, result.netloc])
    except:
        return False

def clean_filename(filename: str) -> str:
    """Очищает имя файла"""
    return re.sub(r'[<>:"/\\|?*]', '', filename)[:100]

class RateLimiter:
    """Ограничитель запросов (5 в минуту)"""
    def __init__(self):
        self.requests: Dict[int, list] = {}
    
    def check(self, user_id: int) -> bool:
        now = datetime.now()
        if user_id not in self.requests:
            self.requests[user_id] = []
        
        # Удаляем старые запросы
        self.requests[user_id] = [
            t for t in self.requests[user_id] 
            if now - t < timedelta(minutes=1)
        ]
        
        if len(self.requests[user_id]) >= 5:
            return False
        
        self.requests[user_id].append(now)
        return True

rate_limiter = RateLimiter()

# ==================== РАСПОЗНАВАНИЕ МУЗЫКИ ====================

async def recognize_audio(file_path: str) -> Optional[Dict[str, Any]]:
    """Распознает музыку через AudD.io"""
    try:
        with open(file_path, 'rb') as f:
            files = {'file': f}
            data = {'api_token': AUDD_TOKEN, 'return': 'spotify'}
            
            async with aiohttp.ClientSession() as session:
                async with session.post('https://api.audd.io/', 
                                      data=data, files=files) as resp:
                    result = await resp.json()
                    
                    if result.get('status') == 'success' and result.get('result'):
                        return result['result']
        return None
    except Exception as e:
        logger.error(f"AudD ошибка: {e}")
        return None

# ==================== КОНВЕРТАЦИЯ АУДИО ====================

def convert_audio_file(input_path: str, output_path: str, format_type: str) -> bool:
    """Конвертирует аудио в разные форматы"""
    try:
        if format_type == 'mp3':
            cmd = ['ffmpeg', '-i', input_path, '-codec:a', 'libmp3lame', 
                  '-b:a', '320k', '-y', output_path]
        elif format_type == 'flac':
            cmd = ['ffmpeg', '-i', input_path, '-codec:a', 'flac', 
                  '-compression_level', '12', '-y', output_path]
        elif format_type == 'm4a':
            cmd = ['ffmpeg', '-i', input_path, '-codec:a', 'aac', 
                  '-b:a', '256k', '-y', output_path]
        elif format_type == 'ogg':
            cmd = ['ffmpeg', '-i', input_path, '-codec:a', 'libopus', 
                  '-b:a', '64k', '-vbr', 'on', '-y', output_path]
        else:
            return False
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except Exception as e:
        logger.error(f"Конвертация ошибка: {e}")
        return False

# ==================== СКАЧИВАНИЕ ВИДЕО ====================

async def download_video_url(url: str, user_id: int) -> Optional[str]:
    """Скачивает видео через yt-dlp"""
    temp_dir = tempfile.mkdtemp(prefix=f"video_{user_id}_")
    output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4][height<=2160]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Ищем скачанный файл
            for ext in ['.mp4', '.mkv', '.webm']:
                for file in Path(temp_dir).glob(f'*{ext}'):
                    return str(file)
            
            return None
    except Exception as e:
        logger.error(f"Ошибка скачивания: {e}")
        try:
            # Пробуем простой формат
            ydl_opts['format'] = 'best[ext=mp4]/best'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                for file in Path(temp_dir).iterdir():
                    if file.is_file():
                        return str(file)
        except Exception as e2:
            logger.error(f"Вторая попытка тоже неудачна: {e2}")
        
        return None

# ==================== КЭШ ДЛЯ ФАЙЛОВ ====================

class TempFileCache:
    """Временное хранилище файлов для callback"""
    def __init__(self):
        self.files: Dict[str, str] = {}  # hash -> file_path
    
    def add(self, file_path: str) -> str:
        """Добавляет файл в кэш и возвращает хэш"""
        file_hash = hashlib.md5(file_path.encode()).hexdigest()[:16]
        self.files[file_hash] = file_path
        return file_hash
    
    def get(self, file_hash: str) -> Optional[str]:
        """Получает путь к файлу по хэшу"""
        return self.files.get(file_hash)
    
    def remove(self, file_hash: str):
        """Удаляет файл из кэша"""
        if file_hash in self.files:
            try:
                os.remove(self.files[file_hash])
            except:
                pass
            del self.files[file_hash]

temp_cache = TempFileCache()

# ==================== ОБРАБОТЧИК КОМАНД ====================

@router.message(Command("start"))
async def cmd_start(message: Message):
    """Приветственное сообщение"""
    welcome_text = (
        "🚀 <b>Добро пожаловать в @saveallv_bot!</b>\n\n"
        "Я скачиваю видео без водяных знаков, распознаю музыку и конвертирую в голосовые.\n"
        "Просто кинь ссылку (TikTok, Instagram, YouTube, Spotify) или голосовуху — всё сделаю сам!\n\n"
        "💡 <i>Кнопки внизу для удобства, но не обязательны.</i>"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Помощь"""
    help_text = (
        "📚 <b>Как использовать бота:</b>\n\n"
        "1. <b>Скачать видео</b> - отправьте ссылку (YouTube, TikTok, Instagram, etc.)\n"
        "2. <b>Распознать музыку</b> - отправьте голосовое или аудиофайл\n"
        "3. <b>В голосовое</b> - конвертировать аудио/видео в голосовое сообщение\n\n"
        "🎯 <i>Автоматический режим:</i>\n"
        "• Отправьте ссылку → получите видео\n"
        "• Отправьте аудио → распознавание музыки\n"
        "• Отправьте видео → выбор действия"
    )
    await message.answer(help_text, reply_markup=get_main_keyboard())

# ==================== ОБРАБОТКА ТЕКСТА (ССЫЛКИ) ====================

@router.message(F.text & ~F.text.startswith('/'))
async def handle_text(message: Message):
    """Обработчик текстовых сообщений"""
    if not rate_limiter.check(message.from_user.id):
        await message.answer("⏳ Слишком много запросов. Подождите минуту.")
        return
    
    text = message.text.strip()
    
    # Если это URL
    if is_url(text):
        await process_video_link(message, text)
    
    # Если это кнопки меню
    elif text == "📥 Скачать видео":
        await message.answer(
            "🔗 <b>Отправьте ссылку на видео:</b>\n"
            "• YouTube / YouTube Shorts\n"
            "• TikTok\n" 
            "• Instagram Reels/Stories\n"
            "• Twitter/X видео\n"
            "• Vimeo\n"
            "• И 2000+ других платформ",
            reply_markup=get_main_keyboard()
        )
    
    elif text == "🎵 Распознать музыку":
        await message.answer(
            "🎤 <b>Отправьте голосовое сообщение или аудиофайл с музыкой</b>\n"
            "Я распознаю трек через Shazam (AudD.io) и предложу варианты скачивания.",
            reply_markup=get_main_keyboard()
        )
    
    elif text == "🎙 В голосовое":
        await message.answer(
            "🎵 <b>Отправьте аудиофайл или видео</b>\n"
            "Я конвертирую в голосовое сообщение Telegram (Opus, 64kbps).",
            reply_markup=get_main_keyboard()
        )
    
    else:
        await message.answer(
            "❌ Не понимаю команду.\n"
            "Отправьте мне:\n"
            "• Ссылку на видео\n"
            "• Голосовое сообщение\n"
            "• Аудиофайл\n"
            "• Или используйте кнопки ниже 👇",
            reply_markup=get_main_keyboard()
        )

async def process_video_link(message: Message, url: str):
    """Обрабатывает скачивание видео по ссылке"""
    try:
        # Определяем платформу
        platform = "видео"
        if 'tiktok.com' in url.lower():
            platform = "TikTok"
        elif 'instagram.com' in url.lower():
            platform = "Instagram"
        elif 'youtube.com' in url.lower() or 'youtu.be' in url.lower():
            platform = "YouTube"
        elif 'twitter.com' in url.lower() or 'x.com' in url.lower():
            platform = "Twitter/X"
        elif 'spotify.com' in url.lower():
            platform = "Spotify"
        
        # Отправляем сообщение о начале
        status_msg = await message.answer(f"🔍 <b>Определяю {platform}...</b>")
        
        # Обновляем статус
        progress_messages = [
            f"📥 <b>Скачиваю с {platform}...</b> 25% 🎬",
            f"📥 <b>Скачиваю с {platform}...</b> 50% 🎬",
            f"📥 <b>Скачиваю с {platform}...</b> 78% 🎬",
            f"🎬 <b>Обрабатываю видео...</b> 95%",
            f"✅ <b>Готово! Отправляю...</b>"
        ]
        
        for i, progress_text in enumerate(progress_messages):
            try:
                await status_msg.edit_text(progress_text)
            except:
                pass
            
            if i < 3:
                await asyncio.sleep(2)
            else:
                await asyncio.sleep(1)
        
        # Скачиваем видео
        video_path = await download_video_url(url, message.from_user.id)
        
        if not video_path or not os.path.exists(video_path):
            await status_msg.edit_text("❌ <b>Не удалось скачать видео</b>\nПроверьте ссылку или попробуйте позже.")
            await asyncio.sleep(3)
            await status_msg.delete()
            return
        
        # Получаем информацию о файле
        file_size = os.path.getsize(video_path) / (1024 * 1024)  # MB
        file_name = os.path.basename(video_path)
        clean_name = clean_filename(file_name)
        
        # Извлекаем аудио для распознавания
        temp_dir = os.path.dirname(video_path)
        audio_path = os.path.join(temp_dir, "audio.mp3")
        
        try:
            # Пробуем извлечь аудио
            subprocess.run([
                'ffmpeg', '-i', video_path, '-q:a', '0', '-map', 'a', audio_path
            ], capture_output=True, timeout=30)
            
            # Распознаем музыку
            music_info = await recognize_audio(audio_path)
            caption = "🎥 Видео скачано"
            
            if music_info:
                title = music_info.get('title', '')
                artist = music_info.get('artist', '')
                if title and artist:
                    caption = f"🎵 <b>{title}</b> — {artist}"
                elif title:
                    caption = f"🎵 <b>{title}</b>"
            
        except:
            caption = "🎥 Видео скачано"
        
        # Отправляем видео
        try:
            if file_size <= 50:  # До 50MB как видео
                await bot.send_video(
                    chat_id=message.chat.id,
                    video=FSInputFile(video_path),
                    caption=caption,
                    reply_markup=get_main_keyboard()
                )
            else:  # Больше 50MB как файл
                await bot.send_document(
                    chat_id=message.chat.id,
                    document=FSInputFile(video_path, filename=clean_name),
                    caption=caption,
                    reply_markup=get_main_keyboard()
                )
        except Exception as e:
            logger.error(f"Ошибка отправки видео: {e}")
            await status_msg.edit_text("❌ <b>Файл слишком большой для Telegram</b>\nМаксимальный размер: 2GB")
            await asyncio.sleep(3)
        
        # Удаляем временные файлы
        try:
            os.remove(video_path)
            if os.path.exists(audio_path):
                os.remove(audio_path)
            os.rmdir(temp_dir)
        except:
            pass
        
        # Удаляем сообщение о статусе
        try:
            await status_msg.delete()
        except:
            pass
        
    except Exception as e:
        logger.error(f"Ошибка обработки ссылки: {e}")
        await message.answer(
            "❌ <b>Ошибка при обработке ссылки</b>\n"
            "Возможные причины:\n"
            "• Ссылка недействительна\n"
            "• Видео заблокировано\n"
            "• Платформа не поддерживается\n\n"
            "Попробуйте другую ссылку.",
            reply_markup=get_main_keyboard()
        )

# ==================== ОБРАБОТКА ГОЛОСОВЫХ И АУДИО ====================

@router.message(F.voice)
async def handle_voice_message(message: Message):
    """Обработчик голосовых сообщений"""
    if not rate_limiter.check(message.from_user.id):
        await message.answer("⏳ Слишком много запросов. Подождите минуту.")
        return
    
    await process_audio_for_recognition(message, is_voice=True)

@router.message(F.audio)
async def handle_audio_file(message: Message):
    """Обработчик аудиофайлов"""
    if not rate_limiter.check(message.from_user.id):
        await message.answer("⏳ Слишком много запросов. Подождите минуту.")
        return
    
    await process_audio_for_recognition(message, is_voice=False)

async def process_audio_for_recognition(message: Message, is_voice: bool = True):
    """Обрабатывает аудио для распознавания музыки"""
    try:
        status_msg = await message.answer("🎵 <b>Анализирую аудио...</b>")
        
        # Скачиваем файл
        if is_voice:
            file_id = message.voice.file_id
            file = await bot.get_file(file_id)
            temp_ext = "ogg"
        else:
            file_id = message.audio.file_id
            file = await bot.get_file(file_id)
            temp_ext = "mp3"
        
        # Создаем временную директорию
        temp_dir = tempfile.mkdtemp(prefix=f"audio_{message.from_user.id}_")
        audio_path = os.path.join(temp_dir, f"audio.{temp_ext}")
        
        await bot.download_file(file.file_path, audio_path)
        
        # Обновляем статус
        await status_msg.edit_text("🎵 <b>Распознаю музыку...</b> 45% 🎵")
        
        # Распознаем музыку
        result = await recognize_audio(audio_path)
        
        if result:
            title = result.get('title', 'Неизвестно')
            artist = result.get('artist', 'Неизвестный исполнитель')
            album = result.get('album', '')
            release_date = result.get('release_date', '')
            
            # Формируем текст результата
            result_text = f"🎵 <b>{title}</b>\n🎤 {artist}"
            if album:
                result_text += f"\n💿 Альбом: {album}"
            if release_date:
                result_text += f"\n📅 {release_date}"
            
            # Создаем inline-клавиатуру
            file_hash = temp_cache.add(audio_path)
            
            builder = InlineKeyboardBuilder()
            builder.button(text="🎙 В голосовое", callback_data=f"conv_ogg_{file_hash}")
            builder.button(text="🎵 MP3 320", callback_data=f"conv_mp3_{file_hash}")
            builder.button(text="🎼 FLAC", callback_data=f"conv_flac_{file_hash}")
            builder.button(text="🎧 M4A", callback_data=f"conv_m4a_{file_hash}")
            builder.adjust(2, 2)
            
            await status_msg.edit_text(result_text, reply_markup=builder.as_markup())
            
        else:
            # Если не распознали, предлагаем конвертацию
            file_hash = temp_cache.add(audio_path)
            
            builder = InlineKeyboardBuilder()
            builder.button(text="🎙 В голосовое", callback_data=f"conv_ogg_{file_hash}")
            builder.button(text="🎵 MP3 320", callback_data=f"conv_mp3_{file_hash}")
            builder.adjust(2)
            
            await status_msg.edit_text(
                "❌ <b>Музыка не распознана</b>\n"
                "Но вы можете конвертировать аудио:",
                reply_markup=builder.as_markup()
            )
    
    except Exception as e:
        logger.error(f"Ошибка обработки аудио: {e}")
        await message.answer(
            "❌ <b>Ошибка обработки аудио</b>\n"
            "Попробуйте другой файл или запись.",
            reply_markup=get_main_keyboard()
        )

# ==================== ОБРАБОТКА ВИДЕОФАЙЛОВ ====================

@router.message(F.video)
async def handle_video_file(message: Message):
    """Обработчик видеофайлов"""
    if not rate_limiter.check(message.from_user.id):
        await message.answer("⏳ Слишком много запросов. Подождите минуту.")
        return
    
    try:
        # Скачиваем видео файл
        status_msg = await message.answer("📥 <b>Загружаю видео...</b>")
        
        file_id = message.video.file_id
        file = await bot.get_file(file_id)
        
        temp_dir = tempfile.mkdtemp(prefix=f"video_file_{message.from_user.id}_")
        video_path = os.path.join(temp_dir, "video.mp4")
        
        await bot.download_file(file.file_path, video_path)
        
        # Извлекаем аудио
        audio_path = os.path.join(temp_dir, "audio.mp3")
        
        try:
            subprocess.run([
                'ffmpeg', '-i', video_path, '-q:a', '0', '-map', 'a', audio_path
            ], capture_output=True, timeout=30)
            
            # Проверяем, извлеклось ли аудио
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                file_hash = temp_cache.add(audio_path)
                
                builder = InlineKeyboardBuilder()
                builder.button(text="🎵 Распознать музыку", callback_data=f"recognize_{file_hash}")
                builder.button(text="🎙 В голосовое", callback_data=f"video_voice_{file_hash}")
                builder.button(text="🎵 Извлечь аудио (MP3)", callback_data=f"extract_mp3_{file_hash}")
                builder.adjust(2, 1)
                
                await status_msg.edit_text(
                    "🎬 <b>Видео загружено!</b>\n"
                    "Выберите действие:",
                    reply_markup=builder.as_markup()
                )
            else:
                # Если не удалось извлечь аудио
                os.remove(video_path)
                os.rmdir(temp_dir)
                await status_msg.edit_text(
                    "❌ <b>Не удалось извлечь аудио из видео</b>\n"
                    "Возможно, видео не содержит звуковой дорожки."
                )
                
        except Exception as e:
            logger.error(f"Ошибка извлечения аудио: {e}")
            await status_msg.edit_text("❌ <b>Ошибка обработки видео</b>")
            
    except Exception as e:
        logger.error(f"Ошибка обработки видеофайла: {e}")
        await message.answer("❌ <b>Ошибка загрузки видео</b>", reply_markup=get_main_keyboard())

# ==================== ОБРАБОТКА CALLBACK-КНОПОК ====================

@router.callback_query(F.data.startswith("conv_"))
async def handle_audio_conversion(callback: CallbackQuery):
    """Обработчик конвертации аудио"""
    try:
        # Извлекаем данные
        parts = callback.data.split('_')
        if len(parts) != 3:
            await callback.answer("❌ Ошибка формата")
            return
        
        format_type = parts[1]  # ogg, mp3, flac, m4a
        file_hash = parts[2]
        
        # Получаем путь к файлу
        audio_path = temp_cache.get(file_hash)
        if not audio_path or not os.path.exists(audio_path):
            await callback.answer("❌ Файл не найден")
            await callback.message.edit_text(
                "❌ Файл устарел. Пожалуйста, отправьте аудио заново.",
                reply_markup=get_main_keyboard()
            )
            return
        
        await callback.answer("🔄 Конвертация...")
        
        # Обновляем сообщение
        format_names = {
            'ogg': 'голосовое сообщение (OGG Opus)',
            'mp3': 'MP3 320kbps',
            'flac': 'FLAC без потерь',
            'm4a': 'M4A (AAC)'
        }
        
        await callback.message.edit_text(
            f"🔄 <b>Конвертирую в {format_names.get(format_type, 'аудио')}...</b>\n"
            f"⏳ Пожалуйста, подождите..."
        )
        
        # Конвертируем
        temp_dir = tempfile.mkdtemp(prefix=f"convert_{callback.from_user.id}_")
        output_path = os.path.join(temp_dir, f"audio.{format_type}")
        
        if convert_audio_file(audio_path, output_path, format_type):
            # Отправляем файл
            file_size = os.path.getsize(output_path) / 1024  # KB
            
            if format_type == 'ogg':
                # Голосовое сообщение
                await bot.send_voice(
                    chat_id=callback.message.chat.id,
                    voice=FSInputFile(output_path),
                    reply_markup=get_main_keyboard()
                )
                await callback.message.delete()
                
            else:
                # Аудио файл
                format_captions = {
                    'mp3': '🎵 MP3 320kbps',
                    'flac': '🎼 FLAC без потерь',
                    'm4a': '🎧 M4A (AAC)'
                }
                
                await bot.send_audio(
                    chat_id=callback.message.chat.id,
                    audio=FSInputFile(output_path),
                    caption=f"{format_captions.get(format_type, 'Аудио файл')} | {file_size:.1f} KB",
                    reply_markup=get_main_keyboard()
                )
                await callback.message.delete()
            
            # Удаляем исходный файл из кэша
            temp_cache.remove(file_hash)
            
        else:
            await callback.message.edit_text(
                "❌ <b>Ошибка конвертации</b>\n"
                "Попробуйте другой формат или отправьте файл заново.",
                reply_markup=get_main_keyboard()
            )
        
        # Очистка временных файлов
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rmdir(temp_dir)
        except:
            pass
        
    except Exception as e:
        logger.error(f"Ошибка конвертации: {e}")
        await callback.answer("❌ Ошибка конвертации")
        await callback.message.edit_text(
            "❌ <b>Ошибка конвертации</b>\n"
            "Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )

@router.callback_query(F.data.startswith("recognize_"))
async def handle_recognize_from_video(callback: CallbackQuery):
    """Распознать музыку из извлеченного аудио"""
    try:
        file_hash = callback.data.split('_')[1]
        audio_path = temp_cache.get(file_hash)
        
        if not audio_path or not os.path.exists(audio_path):
            await callback.answer("❌ Файл не найден")
            return
        
        await callback.answer("🎵 Распознавание...")
        await callback.message.edit_text("🎵 <b>Распознаю музыку из видео...</b>")
        
        result = await recognize_audio(audio_path)
        
        if result:
            title = result.get('title', 'Неизвестно')
            artist = result.get('artist', 'Неизвестный исполнитель')
            
            # Создаем кнопки для конвертации
            builder = InlineKeyboardBuilder()
            builder.button(text="🎙 В голосовое", callback_data=f"conv_ogg_{file_hash}")
            builder.button(text="🎵 MP3 320", callback_data=f"conv_mp3_{file_hash}")
            builder.button(text="🎼 FLAC", callback_data=f"conv_flac_{file_hash}")
            builder.button(text="🎧 M4A", callback_data=f"conv_m4a_{file_hash}")
            builder.adjust(2, 2)
            
            await callback.message.edit_text(
                f"🎬 <b>Музыка из видео распознана!</b>\n\n"
                f"🎵 <b>{title}</b>\n"
                f"🎤 {artist}\n\n"
                f"Выберите формат для скачивания:",
                reply_markup=builder.as_markup()
            )
        else:
            builder = InlineKeyboardBuilder()
            builder.button(text="🎙 В голосовое", callback_data=f"conv_ogg_{file_hash}")
            builder.button(text="🎵 MP3 320", callback_data=f"conv_mp3_{file_hash}")
            builder.adjust(2)
            
            await callback.message.edit_text(
                "❌ <b>Музыка не распознана</b>\n"
                "Но вы можете конвертировать аудио:",
                reply_markup=builder.as_markup()
            )
    
    except Exception as e:
        logger.error(f"Ошибка распознавания из видео: {e}")
        await callback.answer("❌ Ошибка распознавания")

@router.callback_query(F.data.startswith("extract_mp3_"))
async def handle_extract_mp3(callback: CallbackQuery):
    """Извлечь MP3 из видео"""
    try:
        file_hash = callback.data.split('_')[2]
        audio_path = temp_cache.get(file_hash)
        
        if not audio_path:
            await callback.answer("❌ Файл не найден")
            return
        
        await callback.answer("🎵 Извлечение MP3...")
        await callback.message.edit_text("🎵 <b>Извлекаю аудио в MP3...</b>")
        
        # Конвертируем в MP3 если нужно
        if audio_path.endswith('.mp3'):
            output_path = audio_path
        else:
            temp_dir = tempfile.mkdtemp()
            output_path = os.path.join(temp_dir, "audio.mp3")
            convert_audio_file(audio_path, output_path, 'mp3')
        
        # Отправляем MP3
        file_size = os.path.getsize(output_path) / 1024  # KB
        
        await bot.send_audio(
            chat_id=callback.message.chat.id,
            audio=FSInputFile(output_path, filename="audio.mp3"),
            caption=f"🎵 Аудио из видео | {file_size:.1f} KB",
            reply_markup=get_main_keyboard()
        )
        
        await callback.message.delete()
        
        # Очистка
        if audio_path != output_path and os.path.exists(output_path):
            os.remove(output_path)
            os.rmdir(temp_dir)
    
    except Exception as e:
        logger.error(f"Ошибка извлечения MP3: {e}")
        await callback.answer("❌ Ошибка извлечения")

@router.callback_query(F.data.startswith("video_voice_"))
async def handle_video_to_voice(callback: CallbackQuery):
    """Конвертировать видео в голосовое"""
    try:
        file_hash = callback.data.split('_')[2]
        audio_path = temp_cache.get(file_hash)
        
        if not audio_path:
            await callback.answer("❌ Файл не найден")
            return
        
        await callback.answer("🎙 Конвертация...")
        await callback.message.edit_text("🎙 <b>Конвертирую в голосовое...</b>")
        
        # Конвертируем в OGG Opus
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, "voice.ogg")
        
        if convert_audio_file(audio_path, output_path, 'ogg'):
            # Отправляем голосовое
            await bot.send_voice(
                chat_id=callback.message.chat.id,
                voice=FSInputFile(output_path),
                reply_markup=get_main_keyboard()
            )
            await callback.message.delete()
        else:
            await callback.message.edit_text(
                "❌ <b>Ошибка конвертации</b>",
                reply_markup=get_main_keyboard()
            )
        
        # Очистка
        if os.path.exists(output_path):
            os.remove(output_path)
        os.rmdir(temp_dir)
    
    except Exception as e:
        logger.error(f"Ошибка конвертации видео в голосовое: {e}")
        await callback.answer("❌ Ошибка конвертации")

# ==================== ЗАПУСК БОТА ====================

async def main():
    """Главная функция запуска бота"""
    logger.info("=" * 50)
    logger.info(f"Бот @saveallv_bot запускается...")
    logger.info(f"Токен: {TOKEN[:15]}...")
    logger.info("=" * 50)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
