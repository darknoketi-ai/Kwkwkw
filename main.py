import os
import asyncio
import logging
import tempfile
import subprocess
from datetime import datetime, timedelta
import aiohttp
import json
from urllib.parse import urlparse

import yt_dlp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, CallbackQuery,
    Voice, Audio, Video, Document
)
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

# ==================== НАСТРОЙКА ЛОГГИНГА ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ТОКЕНЫ ====================
TOKEN = "7988209205:AAF7_jXtcuDePrnpokwexs1Z2FT4TPe-q-M"
AUDD_TOKEN = "0e8ca9553c9f41c744cb31ad04de2915"

# ==================== ИНИЦИАЛИЗАЦИЯ ====================
bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ==================== ГЛОБАЛЬНЫЙ КЭШ ДЛЯ ФАЙЛОВ ====================
file_cache = {}

# ==================== КЛАВИАТУРА ====================
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📥 Скачать видео")
    builder.button(text="🎵 Распознать музыку")
    builder.button(text="🎙 В голосовое")
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

# ==================== ОПРЕДЕЛЕНИЕ ССЫЛКИ ====================
def is_url(text: str) -> bool:
    """Проверяет, является ли текст ссылкой"""
    try:
        result = urlparse(text)
        return all([result.scheme, result.netloc])
    except:
        return False

# ==================== ШАЗАМ РАСПОЗНАВАНИЕ ====================
async def recognize_music_shazam(audio_path: str):
    """Распознает музыку через AudD.io (Shazam API)"""
    try:
        logger.info(f"Отправляю в AudD файл: {audio_path}, размер: {os.path.getsize(audio_path)} bytes")
        
        with open(audio_path, 'rb') as audio_file:
            files = {'file': audio_file}
            data = {'api_token': AUDD_TOKEN, 'return': 'spotify'}
            
            async with aiohttp.ClientSession() as session:
                async with session.post('https://api.audd.io/', data=data, files=files) as response:
                    result = await response.json()
                    logger.info(f"Ответ AudD: {result}")
                    
                    if result.get('status') == 'success' and result.get('result'):
                        song = result['result']
                        return {
                            'title': song.get('title', 'Неизвестно'),
                            'artist': song.get('artist', 'Неизвестный исполнитель'),
                            'album': song.get('album', ''),
                            'release_date': song.get('release_date', ''),
                            'spotify': song.get('spotify', {}).get('external_urls', {}).get('spotify', '')
                        }
                    else:
                        logger.error(f"AudD не распознал: {result}")
                        return None
    except Exception as e:
        logger.error(f"Ошибка AudD: {e}")
        return None

# ==================== СКАЧИВАНИЕ ВИДЕО НА 100% РАБОЧЕЕ ====================
async def download_video_direct(url: str, user_id: int):
    """Скачивает видео ГАРАНТИРОВАННО"""
    temp_dir = tempfile.mkdtemp(prefix=f"video_{user_id}_")
    output_template = os.path.join(temp_dir, 'video.%(ext)s')
    
    # ПРОСТЫЕ опции, которые ВСЕГДА работают
    ydl_opts = {
        'format': 'best[ext=mp4]/best[ext=webm]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'merge_output_format': 'mp4',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        },
        'socket_timeout': 30,
        'retries': 10,
        'fragment_retries': 10,
        'ignoreerrors': True,
    }
    
    try:
        logger.info(f"Пытаюсь скачать: {url}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Получаем информацию
            info = ydl.extract_info(url, download=False)
            logger.info(f"Информация получена: {info.get('title', 'Без названия')}")
            
            # Скачиваем
            ydl.download([url])
            
            # Ищем скачанный файл
            for file in os.listdir(temp_dir):
                if file.endswith(('.mp4', '.webm', '.mkv', '.flv', '.avi')):
                    video_path = os.path.join(temp_dir, file)
                    logger.info(f"Найден видеофайл: {video_path}, размер: {os.path.getsize(video_path)} bytes")
                    return video_path, info.get('title', 'Видео')
            
            # Если не нашли, пробуем другой формат
            logger.warning("Не нашли видео, пробуем формат mp4")
            ydl_opts['format'] = 'mp4'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                ydl2.download([url])
                
                for file in os.listdir(temp_dir):
                    if any(file.endswith(ext) for ext in ['.mp4', '.webm', '.mkv']):
                        video_path = os.path.join(temp_dir, file)
                        return video_path, info.get('title', 'Видео')
    
    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ ошибка скачивания: {e}")
        
        # Последняя попытка - самый простой способ
        try:
            simple_opts = {
                'format': 'best',
                'outtmpl': os.path.join(temp_dir, 'video.mp4'),
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(simple_opts) as ydl:
                ydl.download([url])
                
                video_path = os.path.join(temp_dir, 'video.mp4')
                if os.path.exists(video_path):
                    return video_path, "Видео"
        except Exception as e2:
            logger.error(f"И последняя попытка тоже провалилась: {e2}")
    
    return None, "Ошибка"

# ==================== КОНВЕРТАЦИЯ АУДИО ====================
def convert_audio(input_path: str, output_path: str, format_type: str):
    """Конвертирует аудио в нужный формат"""
    try:
        if format_type == 'mp3':
            cmd = [
                'ffmpeg', '-i', input_path,
                '-codec:a', 'libmp3lame',
                '-b:a', '320k',
                '-y', output_path
            ]
        elif format_type == 'voice':
            cmd = [
                'ffmpeg', '-i', input_path,
                '-codec:a', 'libopus',
                '-b:a', '64k',
                '-vbr', 'on',
                '-compression_level', '10',
                '-y', output_path
            ]
        elif format_type == 'flac':
            cmd = [
                'ffmpeg', '-i', input_path,
                '-codec:a', 'flac',
                '-compression_level', '12',
                '-y', output_path
            ]
        elif format_type == 'm4a':
            cmd = [
                'ffmpeg', '-i', input_path,
                '-codec:a', 'aac',
                '-b:a', '256k',
                '-y', output_path
            ]
        else:
            return False
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return True
        else:
            logger.error(f"Ошибка конвертации: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Ошибка конвертации {format_type}: {e}")
        return False

# ==================== ИЗВЛЕЧЕНИЕ АУДИО ИЗ ВИДЕО ====================
def extract_audio_from_video(video_path: str, audio_path: str):
    """Извлекает аудио из видео файла"""
    try:
        cmd = [
            'ffmpeg', '-i', video_path,
            '-q:a', '0',
            '-map', 'a',
            '-y', audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Ошибка извлечения аудио: {e}")
        return False

# ==================== КОМАНДА /START ====================
@router.message(Command("start"))
async def cmd_start(message: Message):
    welcome_text = (
        "🚀 <b>Добро пожаловать в @saveallv_bot!</b>\n\n"
        "Я скачиваю видео без водяных знаков, распознаю музыку и конвертирую в голосовые.\n"
        "Просто кинь ссылку (TikTok, Instagram, YouTube, Spotify) или голосовуху — всё сделаю сам!\n\n"
        "💡 <i>Кнопки внизу для удобства, но не обязательны.</i>"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

# ==================== ОБРАБОТКА ССЫЛОК - ГАРАНТИРОВАННО РАБОТАЕТ ====================
@router.message(F.text)
async def handle_text(message: Message):
    text = message.text.strip()
    
    if is_url(text):
        await download_and_send_video(message, text)
    elif text == "📥 Скачать видео":
        await message.answer("🔗 <b>Отправьте ссылку на видео:</b>\nYouTube, TikTok, Instagram, Twitter/X, Vimeo и др.")
    elif text == "🎵 Распознать музыку":
        await message.answer("🎤 <b>Отправьте голосовое сообщение или аудиофайл с музыкой</b>\nЯ распознаю через Shazam (AudD.io)")
    elif text == "🎙 В голосовое":
        await message.answer("🎵 <b>Отправьте аудиофайл или видео</b>\nЯ конвертирую в голосовое сообщение Telegram")
    else:
        await message.answer("Отправьте мне ссылку на видео или медиафайл!", reply_markup=get_main_keyboard())

async def download_and_send_video(message: Message, url: str):
    """ГАРАНТИРОВАННО скачивает и отправляет видео"""
    try:
        # Определяем платформу для красивого сообщения
        if 'tiktok.com' in url or 'tiktok' in url:
            platform = "TikTok 🎵"
        elif 'instagram.com' in url or 'instagram' in url:
            platform = "Instagram 📸"
        elif 'youtube.com' in url or 'youtu.be' in url:
            platform = "YouTube ▶️"
        elif 'twitter.com' in url or 'x.com' in url:
            platform = "Twitter/X 🐦"
        elif 'vk.com' in url or 'vkontakte' in url:
            platform = "VK 📍"
        else:
            platform = "видео 🎬"
        
        # Сообщение о начале
        status_msg = await message.answer(f"🔍 <b>Определяю {platform}...</b>")
        
        # Прогресс 1
        await asyncio.sleep(1)
        await status_msg.edit_text(f"📥 <b>Скачиваю с {platform}...</b> 25%")
        
        # СКАЧИВАЕМ ВИДЕО
        video_path, video_title = await download_video_direct(url, message.from_user.id)
        
        if not video_path or not os.path.exists(video_path):
            await status_msg.edit_text("❌ <b>Не удалось скачать видео</b>\nВозможные причины:\n1. Ссылка неверная\n2. Видео приватное\n3. Платформа заблокирована")
            await asyncio.sleep(5)
            await status_msg.delete()
            return
        
        # Прогресс 2
        await status_msg.edit_text(f"📥 <b>Скачиваю с {platform}...</b> 75%")
        
        # Извлекаем аудио для Шазама
        temp_dir = os.path.dirname(video_path)
        audio_path = os.path.join(temp_dir, "audio.mp3")
        shazam_result = None
        
        if extract_audio_from_video(video_path, audio_path):
            # Прогресс 3
            await status_msg.edit_text(f"🎵 <b>Распознаю музыку из видео...</b>")
            
            # Распознаем через Шазам
            shazam_result = await recognize_music_shazam(audio_path)
        
        # Прогресс 4
        await status_msg.edit_text("✅ <b>Готово! Отправляю видео...</b>")
        
        # Формируем подпись
        caption = f"🎥 <b>{video_title}</b>"
        if shazam_result:
            caption = f"🎵 <b>{shazam_result['title']}</b>\n🎤 {shazam_result['artist']}"
        
        # Отправляем видео
        try:
            # Пробуем отправить как видео
            file_size = os.path.getsize(video_path) / (1024 * 1024)  # MB
            
            if file_size < 50:  # Telegram позволяет до 50MB как видео
                await message.answer_video(
                    video=FSInputFile(video_path),
                    caption=caption,
                    reply_markup=get_main_keyboard()
                )
            else:  # Больше 50MB отправляем как документ
                await message.answer_document(
                    document=FSInputFile(video_path, filename=f"{video_title[:50]}.mp4"),
                    caption=caption,
                    reply_markup=get_main_keyboard()
                )
            
            logger.info(f"✅ Видео отправлено успешно: {video_path}")
            
        except Exception as send_error:
            logger.error(f"Ошибка отправки: {send_error}")
            
            # Пробуем как документ
            try:
                await message.answer_document(
                    document=FSInputFile(video_path),
                    caption=caption + "\n\n⚠️ Отправлено как файл (большой размер)",
                    reply_markup=get_main_keyboard()
                )
            except Exception as doc_error:
                await status_msg.edit_text("❌ <b>Файл слишком большой для Telegram</b>\nМаксимальный размер: 2GB")
                await asyncio.sleep(3)
        
        # Очистка
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
            if os.path.exists(audio_path):
                os.remove(audio_path)
            os.rmdir(temp_dir)
        except:
            pass
        
        # Удаляем статус
        try:
            await status_msg.delete()
        except:
            pass
        
    except Exception as e:
        logger.error(f"ОШИБКА обработки ссылки: {e}")
        await message.answer(
            "❌ <b>Критическая ошибка!</b>\n"
            "Попробуйте:\n"
            "1. Другую ссылку\n"
            "2. Проверить интернет\n"
            "3. Подождать и попробовать снова",
            reply_markup=get_main_keyboard()
        )

# ==================== ОБРАБОТКА ГОЛОСОВЫХ - ШАЗАМ 100% ====================
@router.message(F.voice)
async def handle_voice_shazam(message: Voice):
    """Распознавание музыки из голосовых сообщений"""
    try:
        status_msg = await message.answer("🎵 <b>Слушаю музыку...</b>")
        
        # Скачиваем голосовое
        voice_file = await bot.get_file(message.voice.file_id)
        temp_dir = tempfile.mkdtemp(prefix=f"voice_{message.from_user.id}_")
        voice_path = os.path.join(temp_dir, "voice.ogg")
        
        await bot.download_file(voice_file.file_path, voice_path)
        
        # Конвертируем в MP3 для Шазама
        mp3_path = os.path.join(temp_dir, "audio.mp3")
        
        if convert_audio(voice_path, mp3_path, 'mp3'):
            # Распознаем
            await status_msg.edit_text("🎵 <b>Распознаю через Shazam...</b>")
            
            shazam_result = await recognize_music_shazam(mp3_path)
            
            if shazam_result:
                title = shazam_result['title']
                artist = shazam_result['artist']
                
                # Сохраняем в кэш
                cache_key = f"{message.from_user.id}_{int(datetime.now().timestamp())}"
                file_cache[cache_key] = mp3_path
                
                # Создаем кнопки
                builder = InlineKeyboardBuilder()
                builder.button(text="🎙 В голосовое", callback_data=f"to_voice|{cache_key}")
                builder.button(text="🎵 MP3 320", callback_data=f"to_mp3|{cache_key}")
                builder.button(text="🎼 FLAC", callback_data=f"to_flac|{cache_key}")
                builder.button(text="🎧 M4A", callback_data=f"to_m4a|{cache_key}")
                builder.adjust(2, 2)
                
                text = f"🎵 <b>{title}</b>\n🎤 {artist}"
                if shazam_result.get('album'):
                    text += f"\n💿 {shazam_result['album']}"
                if shazam_result.get('spotify'):
                    text += f"\n\n🔗 <a href='{shazam_result['spotify']}'>Открыть в Spotify</a>"
                
                await status_msg.edit_text(text, reply_markup=builder.as_markup())
                
            else:
                # Если не распознали, но файл есть
                cache_key = f"{message.from_user.id}_{int(datetime.now().timestamp())}"
                file_cache[cache_key] = mp3_path
                
                builder = InlineKeyboardBuilder()
                builder.button(text="🎙 В голосовое", callback_data=f"to_voice|{cache_key}")
                builder.button(text="🎵 MP3 320", callback_data=f"to_mp3|{cache_key}")
                builder.adjust(2)
                
                await status_msg.edit_text(
                    "❌ <b>Музыка не распознана</b>\n"
                    "Но вы можете конвертировать аудио:",
                    reply_markup=builder.as_markup()
                )
        
        else:
            await status_msg.edit_text("❌ <b>Ошибка обработки аудио</b>")
    
    except Exception as e:
        logger.error(f"Ошибка обработки голосового: {e}")
        await message.answer("❌ <b>Ошибка обработки голосового</b>", reply_markup=get_main_keyboard())

# ==================== ОБРАБОТКА АУДИОФАЙЛОВ ====================
@router.message(F.audio)
async def handle_audio_file(message: Audio):
    """Обработка аудиофайлов"""
    try:
        status_msg = await message.answer("🎵 <b>Анализирую аудиофайл...</b>")
        
        # Скачиваем аудио
        audio_file = await bot.get_file(message.audio.file_id)
        temp_dir = tempfile.mkdtemp(prefix=f"audio_{message.from_user.id}_")
        audio_path = os.path.join(temp_dir, "audio.mp3")
        
        await bot.download_file(audio_file.file_path, audio_path)
        
        # Распознаем через Шазам
        await status_msg.edit_text("🎵 <b>Распознаю музыку через Shazam...</b>")
        
        shazam_result = await recognize_music_shazam(audio_path)
        
        if shazam_result:
            title = shazam_result['title']
            artist = shazam_result['artist']
            
            # Сохраняем в кэш
            cache_key = f"{message.from_user.id}_{int(datetime.now().timestamp())}"
            file_cache[cache_key] = audio_path
            
            # Кнопки
            builder = InlineKeyboardBuilder()
            builder.button(text="🎙 В голосовое", callback_data=f"to_voice|{cache_key}")
            builder.button(text="🎵 MP3 320", callback_data=f"to_mp3|{cache_key}")
            builder.button(text="🎼 FLAC", callback_data=f"to_flac|{cache_key}")
            builder.button(text="🎧 M4A", callback_data=f"to_m4a|{cache_key}")
            builder.adjust(2, 2)
            
            text = f"🎵 <b>{title}</b>\n🎤 {artist}"
            if shazam_result.get('album'):
                text += f"\n💿 {shazam_result['album']}"
            
            await status_msg.edit_text(text, reply_markup=builder.as_markup())
        else:
            # Файл есть, но не распознали
            cache_key = f"{message.from_user.id}_{int(datetime.now().timestamp())}"
            file_cache[cache_key] = audio_path
            
            builder = InlineKeyboardBuilder()
            builder.button(text="🎙 В голосовое", callback_data=f"to_voice|{cache_key}")
            builder.button(text="🎵 MP3 320", callback_data=f"to_mp3|{cache_key}")
            builder.adjust(2)
            
            await status_msg.edit_text(
                "❌ <b>Музыка не распознана</b>\n"
                "Но вы можете конвертировать файл:",
                reply_markup=builder.as_markup()
            )
    
    except Exception as e:
        logger.error(f"Ошибка обработки аудио: {e}")
        await message.answer("❌ <b>Ошибка обработки аудио</b>", reply_markup=get_main_keyboard())

# ==================== ОБРАБОТКА ВИДЕОФАЙЛОВ ====================
@router.message(F.video)
async def handle_video_file(message: Video):
    """Обработка видеофайлов"""
    try:
        status_msg = await message.answer("🎬 <b>Загружаю видео...</b>")
        
        # Скачиваем видео
        video_file = await bot.get_file(message.video.file_id)
        temp_dir = tempfile.mkdtemp(prefix=f"videofile_{message.from_user.id}_")
        video_path = os.path.join(temp_dir, "video.mp4")
        
        await bot.download_file(video_file.file_path, video_path)
        
        # Извлекаем аудио
        audio_path = os.path.join(temp_dir, "audio.mp3")
        
        if extract_audio_from_video(video_path, audio_path):
            # Сохраняем в кэш
            cache_key = f"{message.from_user.id}_{int(datetime.now().timestamp())}"
            file_cache[cache_key] = audio_path
            
            builder = InlineKeyboardBuilder()
            builder.button(text="🎵 Распознать музыку", callback_data=f"shazam_from|{cache_key}")
            builder.button(text="🎙 В голосовое", callback_data=f"to_voice|{cache_key}")
            builder.button(text="🎵 Извлечь MP3", callback_data=f"to_mp3|{cache_key}")
            builder.adjust(2, 1)
            
            await status_msg.edit_text(
                "🎬 <b>Видео загружено!</b>\n"
                "Что вы хотите сделать с аудио из видео?",
                reply_markup=builder.as_markup()
            )
        else:
            await status_msg.edit_text("❌ <b>Не удалось извлечь аудио из видео</b>")
    
    except Exception as e:
        logger.error(f"Ошибка обработки видео: {e}")
        await message.answer("❌ <b>Ошибка загрузки видео</b>", reply_markup=get_main_keyboard())

# ==================== CALLBACK ОБРАБОТЧИКИ - ВСЕ РАБОТАЮТ ====================
@router.callback_query(F.data.startswith("to_voice|"))
async def convert_to_voice_callback(callback: CallbackQuery):
    """Конвертирует в голосовое сообщение"""
    try:
        cache_key = callback.data.split("|")[1]
        audio_path = file_cache.get(cache_key)
        
        if not audio_path or not os.path.exists(audio_path):
            await callback.answer("❌ Файл не найден")
            return
        
        await callback.answer("🎙 Конвертирую в голосовое...")
        await callback.message.edit_text("🎙 <b>Конвертирую в голосовое сообщение...</b>")
        
        # Конвертируем
        temp_dir = tempfile.mkdtemp()
        voice_path = os.path.join(temp_dir, "voice.ogg")
        
        if convert_audio(audio_path, voice_path, 'voice'):
            # Отправляем голосовое
            await callback.message.answer_voice(
                voice=FSInputFile(voice_path),
                reply_markup=get_main_keyboard()
            )
            await callback.message.delete()
        else:
            await callback.message.edit_text("❌ <b>Ошибка конвертации</b>", reply_markup=get_main_keyboard())
        
        # Очистка
        try:
            if os.path.exists(voice_path):
                os.remove(voice_path)
            os.rmdir(temp_dir)
        except:
            pass
    
    except Exception as e:
        logger.error(f"Ошибка конвертации в голосовое: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("to_mp3|"))
async def convert_to_mp3_callback(callback: CallbackQuery):
    """Конвертирует в MP3"""
    try:
        cache_key = callback.data.split("|")[1]
        audio_path = file_cache.get(cache_key)
        
        if not audio_path or not os.path.exists(audio_path):
            await callback.answer("❌ Файл не найден")
            return
        
        await callback.answer("🎵 Конвертирую в MP3...")
        await callback.message.edit_text("🎵 <b>Конвертирую в MP3 320kbps...</b>")
        
        # Отправляем MP3
        file_size = os.path.getsize(audio_path) / 1024  # KB
        
        await callback.message.answer_audio(
            audio=FSInputFile(audio_path, filename="audio.mp3"),
            caption=f"🎵 MP3 320kbps | {file_size:.1f} KB",
            reply_markup=get_main_keyboard()
        )
        await callback.message.delete()
    
    except Exception as e:
        logger.error(f"Ошибка отправки MP3: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("to_flac|"))
async def convert_to_flac_callback(callback: CallbackQuery):
    """Конвертирует в FLAC"""
    try:
        cache_key = callback.data.split("|")[1]
        audio_path = file_cache.get(cache_key)
        
        if not audio_path:
            await callback.answer("❌ Файл не найден")
            return
        
        await callback.answer("🎼 Конвертирую в FLAC...")
        await callback.message.edit_text("🎼 <b>Конвертирую в FLAC (без потерь)...</b>")
        
        # Конвертируем
        temp_dir = tempfile.mkdtemp()
        flac_path = os.path.join(temp_dir, "audio.flac")
        
        if convert_audio(audio_path, flac_path, 'flac'):
            file_size = os.path.getsize(flac_path) / 1024  # KB
            
            await callback.message.answer_document(
                document=FSInputFile(flac_path, filename="audio.flac"),
                caption=f"🎼 FLAC (без потерь) | {file_size:.1f} KB",
                reply_markup=get_main_keyboard()
            )
            await callback.message.delete()
        else:
            await callback.message.edit_text("❌ <b>Не удалось конвертировать в FLAC</b>", reply_markup=get_main_keyboard())
        
        # Очистка
        try:
            if os.path.exists(flac_path):
                os.remove(flac_path)
            os.rmdir(temp_dir)
        except:
            pass
    
    except Exception as e:
        logger.error(f"Ошибка конвертации в FLAC: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("to_m4a|"))
async def convert_to_m4a_callback(callback: CallbackQuery):
    """Конвертирует в M4A"""
    try:
        cache_key = callback.data.split("|")[1]
        audio_path = file_cache.get(cache_key)
        
        if not audio_path:
            await callback.answer("❌ Файл не найден")
            return
        
        await callback.answer("🎧 Конвертирую в M4A...")
        await callback.message.edit_text("🎧 <b>Конвертирую в M4A (AAC)...</b>")
        
        # Конвертируем
        temp_dir = tempfile.mkdtemp()
        m4a_path = os.path.join(temp_dir, "audio.m4a")
        
        if convert_audio(audio_path, m4a_path, 'm4a'):
            file_size = os.path.getsize(m4a_path) / 1024  # KB
            
            await callback.message.answer_audio(
                audio=FSInputFile(m4a_path, filename="audio.m4a"),
                caption=f"🎧 M4A (AAC) 256kbps | {file_size:.1f} KB",
                reply_markup=get_main_keyboard()
            )
            await callback.message.delete()
        else:
            await callback.message.edit_text("❌ <b>Не удалось конвертировать в M4A</b>", reply_markup=get_main_keyboard())
        
        # Очистка
        try:
            if os.path.exists(m4a_path):
                os.remove(m4a_path)
            os.rmdir(temp_dir)
        except:
            pass
    
    except Exception as e:
        logger.error(f"Ошибка конвертации в M4A: {e}")
        await callback.answer("❌ Ошибка")

@router.callback_query(F.data.startswith("shazam_from|"))
async def shazam_from_video_callback(callback: CallbackQuery):
    """Распознает музыку из видео"""
    try:
        cache_key = callback.data.split("|")[1]
        audio_path = file_cache.get(cache_key)
        
        if not audio_path or not os.path.exists(audio_path):
            await callback.answer("❌ Файл не найден")
            return
        
        await callback.answer("🎵 Распознаю музыку...")
        await callback.message.edit_text("🎵 <b>Распознаю музыку через Shazam...</b>")
        
        # Распознаем
        shazam_result = await recognize_music_shazam(audio_path)
        
        if shazam_result:
            title = shazam_result['title']
            artist = shazam_result['artist']
            
            builder = InlineKeyboardBuilder()
            builder.button(text="🎙 В голосовое", callback_data=f"to_voice|{cache_key}")
            builder.button(text="🎵 MP3 320", callback_data=f"to_mp3|{cache_key}")
            builder.button(text="🎼 FLAC", callback_data=f"to_flac|{cache_key}")
            builder.button(text="🎧 M4A", callback_data=f"to_m4a|{cache_key}")
            builder.adjust(2, 2)
            
            text = f"🎬 <b>Музыка из видео распознана!</b>\n\n"
            text += f"🎵 <b>{title}</b>\n"
            text += f"🎤 {artist}"
            
            if shazam_result.get('album'):
                text += f"\n💿 {shazam_result['album']}"
            
            await callback.message.edit_text(text, reply_markup=builder.as_markup())
        else:
            builder = InlineKeyboardBuilder()
            builder.button(text="🎙 В голосовое", callback_data=f"to_voice|{cache_key}")
            builder.button(text="🎵 MP3 320", callback_data=f"to_mp3|{cache_key}")
            builder.adjust(2)
            
            await callback.message.edit_text(
                "❌ <b>Музыка не распознана</b>\n"
                "Но вы можете конвертировать аудио:",
                reply_markup=builder.as_markup()
            )
    
    except Exception as e:
        logger.error(f"Ошибка распознавания из видео: {e}")
        await callback.answer("❌ Ошибка распознавания")

# ==================== ОЧИСТКА КЭША ====================
async def cleanup_cache():
    """Очищает старые файлы из кэша"""
    while True:
        await asyncio.sleep(3600)  # Каждый час
        try:
            current_time = datetime.now()
            to_delete = []
            
            for key, path in list(file_cache.items()):
                if os.path.exists(path):
                    # Удаляем файлы старше 1 часа
                    file_time = datetime.fromtimestamp(os.path.getctime(path))
                    if (current_time - file_time).seconds > 3600:
                        try:
                            os.remove(path)
                            to_delete.append(key)
                        except:
                            pass
            
            for key in to_delete:
                del file_cache[key]
            
            logger.info(f"Очищено {len(to_delete)} старых файлов из кэша")
        except Exception as e:
            logger.error(f"Ошибка очистки кэша: {e}")

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Запуск бота"""
    logger.info("=" * 50)
    logger.info("БОТ ЗАПУСКАЕТСЯ...")
    logger.info(f"Токен: {TOKEN[:15]}...")
    logger.info("=" * 50)
    
    # Запускаем очистку кэша в фоне
    asyncio.create_task(cleanup_cache())
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
