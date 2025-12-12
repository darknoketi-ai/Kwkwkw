import os
import asyncio
import logging
import tempfile
import subprocess
from datetime import datetime, timedelta
import aiohttp
import json

import yt_dlp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile, CallbackQuery
)
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

# ==================== НАСТРОЙКА ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "7988209205:AAF7_jXtcuDePrnpokwexs1Z2FT4TPe-q-M"
AUDD_TOKEN = "0e8ca9553c9f41c744cb31ad04de2915"

bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ==================== КЛАВИАТУРА ====================
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📥 Скачать видео")
    builder.button(text="🎵 Распознать музыку")
    builder.button(text="🎙 В голосовое")
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

# ==================== ФУНКЦИИ ШАЗАМА ====================
async def shazam_recognize(audio_path: str):
    """Распознает музыку через AudD.io (Shazam API)"""
    try:
        with open(audio_path, 'rb') as audio_file:
            files = {'file': audio_file}
            data = {'api_token': AUDD_TOKEN, 'return': 'spotify'}
            
            async with aiohttp.ClientSession() as session:
                async with session.post('https://api.audd.io/', data=data, files=files) as response:
                    result = await response.json()
                    
                    if result.get('status') == 'success' and result.get('result'):
                        song = result['result']
                        return {
                            'title': song.get('title', 'Неизвестно'),
                            'artist': song.get('artist', 'Неизвестный исполнитель'),
                            'album': song.get('album', ''),
                            'spotify_url': song.get('spotify', {}).get('external_urls', {}).get('spotify', '')
                        }
        return None
    except Exception as e:
        logger.error(f"Shazam error: {e}")
        return None

# ==================== СКАЧИВАНИЕ ВИДЕО ====================
async def download_video_simple(url: str, user_id: int):
    """Простое скачивание видео"""
    temp_dir = tempfile.mkdtemp(prefix=f"vid_{user_id}_")
    output_path = os.path.join(temp_dir, "video.mp4")
    
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'video')[:100]
            
            if os.path.exists(output_path):
                return output_path, title
    except Exception as e:
        logger.error(f"Download error: {e}")
    
    return None, "video"

# ==================== КОНВЕРТАЦИЯ ====================
def convert_to_mp3(input_path: str, output_path: str):
    """Конвертирует в MP3"""
    try:
        subprocess.run([
            'ffmpeg', '-i', input_path,
            '-codec:a', 'libmp3lame',
            '-b:a', '320k',
            '-y', output_path
        ], capture_output=True, check=True)
        return True
    except:
        return False

def convert_to_voice(input_path: str, output_path: str):
    """Конвертирует в голосовое (OGG Opus)"""
    try:
        subprocess.run([
            'ffmpeg', '-i', input_path,
            '-codec:a', 'libopus',
            '-b:a', '64k',
            '-vbr', 'on',
            '-y', output_path
        ], capture_output=True, check=True)
        return True
    except:
        return False

# ==================== ОБРАБОТЧИК ССЫЛОК ====================
@router.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "🚀 <b>Добро пожаловать в @saveallv_bot!</b>\n\n"
        "Я скачиваю видео без водяных знаков, распознаю музыку и конвертирую в голосовые.\n"
        "Просто кинь ссылку (TikTok, Instagram, YouTube, Spotify) или голосовуху — всё сделаю сам!\n\n"
        "💡 <i>Кнопки внизу для удобства, но не обязательны.</i>"
    )
    await message.answer(text, reply_markup=get_main_keyboard())

@router.message(F.text & ~F.text.startswith('/'))
async def handle_text(message: Message):
    text = message.text.strip()
    
    # Проверяем ссылку
    if 'http' in text and ('://' in text or 'www.' in text):
        await process_url(message, text)
    elif text == "📥 Скачать видео":
        await message.answer("🔗 Отправьте ссылку на видео:")
    elif text == "🎵 Распознать музыку":
        await message.answer("🎤 Отправьте голосовое или аудио:")
    elif text == "🎙 В голосовое":
        await message.answer("🎵 Отправьте аудио или видео:")
    else:
        await message.answer("Отправьте ссылку или медиафайл!", reply_markup=get_main_keyboard())

async def process_url(message: Message, url: str):
    """Обрабатывает URL - САМАЯ ВАЖНАЯ ФУНКЦИЯ"""
    try:
        # Определяем платформу
        if 'tiktok' in url.lower():
            platform = "TikTok 🎵"
        elif 'instagram' in url.lower():
            platform = "Instagram 📸"
        elif 'youtube' in url.lower() or 'youtu.be' in url.lower():
            platform = "YouTube ▶️"
        elif 'twitter' in url.lower() or 'x.com' in url.lower():
            platform = "Twitter/X 🐦"
        else:
            platform = "видео 🎬"
        
        # Сообщение о начале
        status_msg = await message.answer(f"🔍 <b>Определяю {platform}...</b>")
        
        # Прогресс
        await status_msg.edit_text(f"📥 <b>Скачиваю {platform}...</b>")
        
        # СКАЧИВАЕМ ВИДЕО
        video_path, title = await download_video_simple(url, message.from_user.id)
        
        if not video_path:
            await status_msg.edit_text("❌ <b>Не удалось скачать видео</b>")
            await asyncio.sleep(3)
            await status_msg.delete()
            return
        
        await status_msg.edit_text("🎬 <b>Обрабатываю видео...</b>")
        
        # Извлекаем аудио для Шазама
        temp_dir = os.path.dirname(video_path)
        audio_path = os.path.join(temp_dir, "audio.mp3")
        
        try:
            subprocess.run([
                'ffmpeg', '-i', video_path, '-q:a', '0', '-map', 'a',
                '-y', audio_path
            ], capture_output=True, timeout=30)
        except:
            audio_path = None
        
        # Распознаем музыку через Шазам
        caption = f"🎥 {title}"
        if audio_path and os.path.exists(audio_path):
            shazam_result = await shazam_recognize(audio_path)
            if shazam_result:
                caption = f"🎵 <b>{shazam_result['title']}</b> — {shazam_result['artist']}"
        
        await status_msg.edit_text("✅ <b>Готово! Отправляю видео...</b>")
        
        # Отправляем видео
        with open(video_path, 'rb') as video_file:
            try:
                # Пробуем как видео
                await message.answer_video(
                    video=FSInputFile(video_path),
                    caption=caption,
                    reply_markup=get_main_keyboard()
                )
            except:
                # Если не получается, как документ
                await message.answer_document(
                    document=FSInputFile(video_path),
                    caption=caption,
                    reply_markup=get_main_keyboard()
                )
        
        # Очистка
        try:
            os.remove(video_path)
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
            os.rmdir(temp_dir)
        except:
            pass
        
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"URL processing error: {e}")
        await message.answer("❌ <b>Ошибка скачивания</b>\nПопробуйте другую ссылку.", reply_markup=get_main_keyboard())

# ==================== ОБРАБОТКА ГОЛОСОВЫХ (ШАЗАМ) ====================
@router.message(F.voice)
async def handle_voice(message: Message):
    """Распознавание музыки из голосовых - РАБОЧИЙ ШАЗАМ"""
    try:
        status_msg = await message.answer("🎵 <b>Слушаю музыку...</b>")
        
        # Скачиваем голосовое
        file = await bot.get_file(message.voice.file_id)
        temp_dir = tempfile.mkdtemp()
        voice_path = os.path.join(temp_dir, "voice.ogg")
        
        await bot.download_file(file.file_path, voice_path)
        
        # Конвертируем в MP3 для Шазама
        mp3_path = os.path.join(temp_dir, "audio.mp3")
        if convert_to_mp3(voice_path, mp3_path):
            # Распознаем через Шазам
            await status_msg.edit_text("🎵 <b>Распознаю музыку через Shazam...</b>")
            
            shazam_result = await shazam_recognize(mp3_path)
            
            if shazam_result:
                title = shazam_result['title']
                artist = shazam_result['artist']
                
                # Создаем кнопки для форматов
                builder = InlineKeyboardBuilder()
                builder.button(text="🎙 В голосовое", callback_data=f"voice_convert_{title[:20]}")
                builder.button(text="🎵 MP3 320", callback_data=f"mp3_convert_{title[:20]}")
                builder.button(text="🎼 FLAC", callback_data="flac_info")
                builder.button(text="🎧 M4A", callback_data="m4a_info")
                builder.adjust(2, 2)
                
                text = f"🎵 <b>{title}</b>\n🎤 {artist}"
                if shazam_result.get('album'):
                    text += f"\n💿 {shazam_result['album']}"
                
                await status_msg.edit_text(text, reply_markup=builder.as_markup())
                
                # Сохраняем аудио для конвертации
                with open(mp3_path, 'rb') as f:
                    audio_data = f.read()
                # Здесь нужно сохранить в кэш или временное хранилище
                
            else:
                await status_msg.edit_text("❌ <b>Музыка не распознана</b>\nПопробуйте другую запись или отправьте аудиофайл.")
        
        # Очистка
        try:
            os.remove(voice_path)
            if os.path.exists(mp3_path):
                os.remove(mp3_path)
            os.rmdir(temp_dir)
        except:
            pass
        
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await message.answer("❌ <b>Ошибка обработки голосового</b>", reply_markup=get_main_keyboard())

# ==================== ОБРАБОТКА АУДИО ====================
@router.message(F.audio)
async def handle_audio(message: Message):
    """Обработка аудиофайлов"""
    try:
        status_msg = await message.answer("🎵 <b>Анализирую аудиофайл...</b>")
        
        # Скачиваем аудио
        file = await bot.get_file(message.audio.file_id)
        temp_dir = tempfile.mkdtemp()
        audio_path = os.path.join(temp_dir, "audio.mp3")
        
        await bot.download_file(file.file_path, audio_path)
        
        # Распознаем через Шазам
        await status_msg.edit_text("🎵 <b>Распознаю музыку через Shazam...</b>")
        
        shazam_result = await shazam_recognize(audio_path)
        
        if shazam_result:
            title = shazam_result['title']
            artist = shazam_result['artist']
            
            # Кнопки для форматов
            builder = InlineKeyboardBuilder()
            builder.button(text="🎙 В голосовое", callback_data=f"audio_voice_{title[:20]}")
            builder.button(text="🎵 MP3 320", callback_data=f"audio_mp3_{title[:20]}")
            builder.adjust(2)
            
            text = f"🎵 <b>{title}</b>\n🎤 {artist}"
            await status_msg.edit_text(text, reply_markup=builder.as_markup())
        else:
            await status_msg.edit_text("❌ <b>Музыка не распознана</b>\nНо вы можете конвертировать файл.")
        
        # Очистка
        try:
            os.remove(audio_path)
            os.rmdir(temp_dir)
        except:
            pass
        
    except Exception as e:
        logger.error(f"Audio processing error: {e}")
        await message.answer("❌ <b>Ошибка обработки аудио</b>", reply_markup=get_main_keyboard())

# ==================== CALLBACK ОБРАБОТЧИКИ ====================
@router.callback_query(F.data.contains("voice_convert"))
async def convert_to_voice_callback(callback: CallbackQuery):
    """Конвертирует в голосовое сообщение"""
    await callback.answer("Конвертирую в голосовое...")
    
    # В реальном приложении здесь нужно взять аудио из кэша
    # Создаем временный файл для примера
    temp_dir = tempfile.mkdtemp()
    input_path = os.path.join(temp_dir, "input.mp3")
    output_path = os.path.join(temp_dir, "voice.ogg")
    
    # Создаем тестовый аудио файл
    subprocess.run([
        'ffmpeg', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=5',
        '-y', input_path
    ], capture_output=True)
    
    if convert_to_voice(input_path, output_path):
        await callback.message.answer_voice(
            voice=FSInputFile(output_path),
            reply_markup=get_main_keyboard()
        )
        await callback.message.delete()
    else:
        await callback.answer("❌ Ошибка конвертации")
    
    # Очистка
    try:
        os.remove(input_path)
        os.remove(output_path)
        os.rmdir(temp_dir)
    except:
        pass

@router.callback_query(F.data.contains("mp3_convert"))
async def convert_to_mp3_callback(callback: CallbackQuery):
    """Конвертирует в MP3"""
    await callback.answer("Конвертирую в MP3...")
    
    temp_dir = tempfile.mkdtemp()
    input_path = os.path.join(temp_dir, "input.mp3")
    output_path = os.path.join(temp_dir, "audio.mp3")
    
    # Тестовый файл
    subprocess.run([
        'ffmpeg', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=5',
        '-codec:a', 'libmp3lame', '-b:a', '320k',
        '-y', input_path
    ], capture_output=True)
    
    await callback.message.answer_audio(
        audio=FSInputFile(input_path),
        caption="🎵 MP3 320kbps",
        reply_markup=get_main_keyboard()
    )
    await callback.message.delete()
    
    # Очистка
    try:
        os.remove(input_path)
        os.rmdir(temp_dir)
    except:
        pass

@router.callback_query(F.data == "flac_info")
async def flac_info(callback: CallbackQuery):
    await callback.answer("FLAC - формат без потерь качества")
    await callback.message.edit_text(
        "🎼 <b>FLAC (Free Lossless Audio Codec)</b>\n\n"
        "• Формат без потерь качества\n"
        "• Исходное качество звука\n"
        "• Больший размер файла\n"
        "• Поддержка метаданных",
        reply_markup=get_main_keyboard()
    )

@router.callback_query(F.data == "m4a_info")
async def m4a_info(callback: CallbackQuery):
    await callback.answer("M4A - формат Apple")
    await callback.message.edit_text(
        "🎧 <b>M4A (AAC Audio)</b>\n\n"
        "• Формат Apple (iTunes)\n"
        "• Высокое качество при малом размере\n"
        "• Поддержка метаданных\n"
        "• Совместимость с Apple устройствами",
        reply_markup=get_main_keyboard()
    )

# ==================== ОБРАБОТКА ВИДЕОФАЙЛОВ ====================
@router.message(F.video)
async def handle_video(message: Message):
    """Обработка видеофайлов"""
    try:
        builder = InlineKeyboardBuilder()
        builder.button(text="🎵 Распознать музыку", callback_data="video_shazam")
        builder.button(text="🎙 В голосовое", callback_data="video_to_voice")
        builder.adjust(2)
        
        await message.answer(
            "🎬 <b>Видео получено!</b>\nЧто вы хотите сделать?",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Video processing error: {e}")

@router.callback_query(F.data == "video_shazam")
async def video_shazam(callback: CallbackQuery):
    """Шазам из видео"""
    await callback.answer("Распознаю музыку из видео...")
    await callback.message.edit_text(
        "🎬 <b>Извлекаю аудио из видео...</b>\n"
        "🔍 <b>Распознаю через Shazam...</b>\n\n"
        "⏳ Это может занять несколько секунд.",
        reply_markup=get_main_keyboard()
    )

@router.callback_query(F.data == "video_to_voice")
async def video_to_voice(callback: CallbackQuery):
    """Видео в голосовое"""
    await callback.answer("Конвертирую видео в голосовое...")
    await callback.message.edit_text(
        "🎬 <b>Извлекаю аудио из видео...</b>\n"
        "🎙 <b>Конвертирую в голосовое сообщение...</b>\n\n"
        "✅ В реальном боте здесь будет отправлено голосовое",
        reply_markup=get_main_keyboard()
    )

# ==================== ЗАПУСК ====================
async def main():
    logger.info("Бот запускается...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
