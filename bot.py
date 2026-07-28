import os
import asyncio
import re
import time
import json
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp

# ---------------------------------------------------------
# تنظیمات اصلی
# ---------------------------------------------------------
TOKEN = '8897975172:AAFXrND5_zFFeSsGDxD9lYdF32zwhTFtpds'

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

def get_spotify_details_pure(url):
    try:
        clean_url = url.split('?')[0]
        oembed_url = f"https://open.spotify.com/oembed?url={clean_url}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        
        res = requests.get(oembed_url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            title_full = data.get('title', '')
            thumbnail = data.get('thumbnail_url')
            
            artist = "نامشخص"
            title = title_full
            
            if " by " in title_full:
                parts = title_full.rsplit(" by ", 1)
                title = parts[0].strip()
                artist = parts[1].strip()
            elif " - " in title_full:
                parts = title_full.split(" - ", 1)
                artist = parts[0].strip()
                title = parts[1].strip()
                
            return {'title': title, 'artist': artist, 'thumbnail': thumbnail}
    except Exception as e:
        print(f"Spotify OEmbed Error: {e}")
    
    return {'title': 'Spotify Track', 'artist': 'نامشخص', 'thumbnail': None}

def download_instagram_pure(url, target_dir):
    session = requests.Session()
    clean_url = url.split('?')[0]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://cobalt.tools/'
    }
    
    downloaded_files = []
    
    # استفاده از Cobalt API (بهینه‌ترین و بی‌خطاترین روش برای اینستاگرام)
    try:
        payload = {"url": clean_url, "vQuality": "max"}
        cobalt_headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        }
        res = session.post("https://api.cobalt.tools/api/json", json=payload, headers=cobalt_headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            status = data.get('status')
            if status in ['stream', 'redirect']:
                dl_url = data.get('url')
                if dl_url:
                    ext = '.mp4' if 'mp4' in dl_url.lower() or 'video' in dl_url.lower() else '.jpg'
                    out_path = os.path.join(target_dir, f"ig_{int(time.time())}{ext}")
                    v_res = session.get(dl_url, headers=headers, stream=True, timeout=20)
                    if v_res.status_code == 200:
                        with open(out_path, 'wb') as f:
                            for chunk in v_res.iter_content(chunk_size=8192):
                                if chunk: f.write(chunk)
                        downloaded_files.append(out_path)
            elif status == 'picker':
                picker = data.get('picker', [])
                for idx, item in enumerate(picker):
                    dl_url = item.get('url')
                    if dl_url:
                        ext = '.mp4' if 'mp4' in dl_url.lower() else '.jpg'
                        out_path = os.path.join(target_dir, f"ig_{int(time.time())}_{idx}{ext}")
                        v_res = session.get(dl_url, headers=headers, stream=True, timeout=20)
                        if v_res.status_code == 200:
                            with open(out_path, 'wb') as f:
                                for chunk in v_res.iter_content(chunk_size=8192):
                                    if chunk: f.write(chunk)
                            downloaded_files.append(out_path)
    except Exception as e:
        print(f"Cobalt Instagram Error: {e}")

    if downloaded_files:
        return downloaded_files, "Instagram Media"

    raise Exception("اینستاگرام لینک را مسدود کرد یا پست خصوصی است.")

# ---------------------------------------------------------
# هندلرهای ربات
# ---------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💎 ربات آماده است. لینک خود را بفرستید.", parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    if not text.startswith(("http://", "https://")):
        await message.reply_text("❌ لطفاً یک لینک معتبر بفرستید.", parse_mode="HTML")
        return

    url = text

    if "spotify.com" in url:
        progress_msg = await update.message.reply_text("🔍 در حال استخراج مشخصات از اسپاتیفای...", parse_mode="HTML")
        details = await asyncio.get_event_loop().run_in_executor(None, lambda: get_spotify_details_pure(url))
        await progress_msg.delete()
        
        title = details['title']
        artist = details['artist']
        thumbnail = details['thumbnail']
        
        context.user_data['url'] = url
        context.user_data['info'] = {'title': title, 'artist': artist, 'is_audio_only': True}
        
        keyboard = [[InlineKeyboardButton("❤️ دانلود از YouTube Music", callback_data="spo_ytm")]]
        caption = f"🎵 <b>{title}</b>\n👤 <b>{artist}</b>"
        
        if thumbnail:
            await update.message.reply_photo(photo=thumbnail, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if "instagram.com" in url:
        keyboard = [[InlineKeyboardButton("📥 دانلود از اینستاگرام", callback_data="fmt_instagram")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Instagram Media', 'is_audio_only': False}
        await update.message.reply_text("🎬 لینک اینستاگرام شناسایی شد:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    # برای بقیه لینک‌ها
    context.user_data['url'] = url
    context.user_data['info'] = {'title': 'Media', 'is_audio_only': False}
    keyboard = [[InlineKeyboardButton("📥 دانلود فایل", callback_data="fmt_best")]]
    await update.message.reply_text("📌 لینک دریافت شد. جهت دانلود کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get('url')
    data = query.data
    info = context.user_data.get('info')
    
    if not url or not info:
        await query.message.reply_text("❌ اطلاعات منقضی شد.", parse_mode="HTML")
        return
        
    main_loop = asyncio.get_running_loop()
    chat_id = query.message.chat_id
    
    try:
        await query.message.edit_text("⚡️ در حال دانلود...")
        
        filename = None
        downloaded_files = []
        
        if data == "fmt_instagram":
            downloaded_files, _ = await main_loop.run_in_executor(
                None, lambda: download_instagram_pure(url, 'downloads')
            )
        elif data == "spo_ytm":
            track_title = info.get('title', '')
            track_artist = info.get('artist', '')
            search_query = f"{track_artist} {track_title}".strip()
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': 'downloads/%(title)s.%(ext)s',
                'default_search': 'ytsearch1',
                'quiet': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192'
                }]
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res_info = await main_loop.run_in_executor(None, lambda: ydl.extract_info(search_query, download=True))
                if 'entries' in res_info and res_info['entries']:
                    item = res_info['entries'][0]
                    filename = ydl.prepare_filename(item)
                    filename = os.path.splitext(filename)[0] + ".mp3"
                else:
                    raise Exception("موزیک مورد نظر در یوتیوب پیدا نشد.")
        else:
            ydl_opts = {
                'format': 'best',
                'outtmpl': 'downloads/%(title)s.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res_info = await main_loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                if res_info:
                    if 'entries' in res_info:
                        for entry in res_info['entries']:
                            if entry:
                                f_path = ydl.prepare_filename(entry)
                                if os.path.exists(f_path): downloaded_files.append(f_path)
                    else:
                        filename = ydl.prepare_filename(res_info)

        if not filename and downloaded_files:
            if len(downloaded_files) == 1:
                filename = downloaded_files[0]
            else:
                # ارسال به صورت آلبوم عکس یا ویدیو
                media_group = [InputMediaPhoto(open(f, 'rb')) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) else InputMediaVideo(open(f, 'rb')) for f in downloaded_files]
                await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                for f in downloaded_files:
                    if os.path.exists(f): os.remove(f)
                await query.message.delete()
                return

        if not filename or not os.path.exists(filename):
            raise Exception("فایل خروجی ایجاد نشد.")

        _, ext = os.path.splitext(filename.lower())
        with open(filename, 'rb') as f_obj:
            if data == "spo_ytm":
                await context.bot.send_audio(chat_id=chat_id, audio=f_obj, caption=f"🎵 {info.get('title')}", parse_mode="HTML")
            elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
                await context.bot.send_photo(chat_id=chat_id, photo=f_obj, parse_mode="HTML")
            else:
                await context.bot.send_video(chat_id=chat_id, video=f_obj, parse_mode="HTML")
                
        if os.path.exists(filename): os.remove(filename)
        for f in downloaded_files:
            if os.path.exists(f): os.remove(f)
        await query.message.delete()

    except Exception as e:
        await query.message.reply_text(f"❌ خطا: {str(e)}", parse_mode="HTML")

def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_click))
    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()

