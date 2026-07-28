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
# توکن‌ها و تنظیمات
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

def download_instagram_via_api(url, target_dir):
    session = requests.Session()
    clean_url = url.split('?')[0]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://cobalt.tools/'
    }
    
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
                    is_video = 'mp4' in dl_url.lower() or 'video' in dl_url.lower() or data.get('type') == 'video'
                    ext = '.mp4' if is_video else '.jpg'
                    out_path = os.path.join(target_dir, f"ig_{int(time.time())}{ext}")
                    v_res = session.get(dl_url, headers=headers, stream=True, timeout=20)
                    if v_res.status_code == 200:
                        with open(out_path, 'wb') as f:
                            for chunk in v_res.iter_content(chunk_size=8192):
                                if chunk: f.write(chunk)
                        return [out_path], "Instagram Media"
                        
            elif status == 'picker':
                picker = data.get('picker', [])
                downloaded_files = []
                for idx, item in enumerate(picker):
                    dl_url = item.get('url')
                    if dl_url:
                        is_video = 'mp4' in dl_url.lower() or item.get('type') == 'video'
                        ext = '.mp4' if is_video else '.jpg'
                        out_path = os.path.join(target_dir, f"ig_{int(time.time())}_{idx}{ext}")
                        v_res = session.get(dl_url, headers=headers, stream=True, timeout=20)
                        if v_res.status_code == 200:
                            with open(out_path, 'wb') as f:
                                for chunk in v_res.iter_content(chunk_size=8192):
                                    if chunk: f.write(chunk)
                            downloaded_files.append(out_path)
                if downloaded_files:
                    return downloaded_files, "Instagram Media"
    except Exception as e:
        print(f"Cobalt API Error: {e}")

    raise Exception("اینستاگرام لینک را مسدود کرد یا پست در دسترس نیست.")

def download_tiktok_pure(url, target_dir):
    session = requests.Session()
    api_url = f"https://api.tiklydown.eu.org/api/download?url={url}"
    headers = BROWSER_HEADERS.copy()
    
    res = session.get(api_url, headers=headers, timeout=15)
    if res.status_code == 200:
        data = res.json()
        title = data.get('title', 'TikTok Media')
        title = re.sub(r'[\\/*?:"<>|]', "", title)
        
        video_data = data.get('video', {})
        v_url = video_data.get('noWatermark') or video_data.get('watermark')
        if v_url:
            out_path = os.path.join(target_dir, f"tt_{int(time.time())}.mp4")
            v_res = session.get(v_url, headers=headers, stream=True)
            if v_res.status_code == 200:
                with open(out_path, 'wb') as f:
                    for chunk in v_res.iter_content(chunk_size=8192):
                        if chunk: f.write(chunk)
                return out_path, title, False

    raise Exception("دریافت ویدیو از تیک‌تاک ناموفق بود.")

# ---------------------------------------------------------
# هندلرهای تلگرام
# ---------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "💎 <b>سلام! ربات با رفع کامل خطای پست‌های عکسی اینستاگرام آماده است.</b>\n\n"
        "🔗 لینک اسپاتیفای، اینستاگرام، یوتیوب یا تیک‌تاک خود را ارسال کنید:"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    
    try:
        await message.set_reaction("🫡")
    except Exception:
        pass

    if not text.startswith(("http://", "https://")):
        await message.reply_text("❌ <b>لطفاً یک لینک معتبر بفرستید.</b>", parse_mode="HTML")
        return

    url = text

    if "spotify.com" in url:
        progress_msg = await update.message.reply_text("🔍 <b>در حال استخراج مشخصات از اسپاتیفای...</b>", parse_mode="HTML")
        details = await asyncio.get_event_loop().run_in_executor(None, lambda: get_spotify_details_pure(url))
        await progress_msg.delete()
        
        title = details['title']
        artist = details['artist']
        thumbnail = details['thumbnail']
        
        context.user_data['url'] = url
        context.user_data['info'] = {'title': title, 'artist': artist, 'is_audio_only': True}
        
        keyboard = [
            [InlineKeyboardButton("❤️ دانلود از YouTube Music", callback_data="spo_ytm")],
            [InlineKeyboardButton("🧡 دانلود از SoundCloud", callback_data="spo_sc")]
        ]
        
        caption = (
            f"🎵 <b>موزیک:</b> {title}\n"
            f"👤 <b>هنرمند:</b> {artist}\n\n"
            f"✨ <b>منبع دانلود را انتخاب کنید:</b>"
        )
        if thumbnail:
            await update.message.reply_photo(photo=thumbnail, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if "instagram.com" in url:
        keyboard = [[InlineKeyboardButton("📥 دانلود پست / ریلز اینستاگرام", callback_data="fmt_instagram")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Instagram Media', 'is_audio_only': False}
        await update.message.reply_text("🎬 <b>لینک اینستاگرام شناسایی شد.</b>\nبرای دریافت فایل کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if "tiktok.com" in url or "vm.tiktok.com" in url:
        keyboard = [[InlineKeyboardButton("📥 دانلود بدون واترمارک", callback_data="fmt_best")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'TikTok Media', 'is_audio_only': False}
        await update.message.reply_text("🎵 <b>تیک‌تاک شناسایی شد.</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    progress_msg = await update.message.reply_text("🧠 <b>در حال آنالیز لینک...</b>", parse_mode="HTML")
    try:
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'noplaylist': True, 'http_headers': BROWSER_HEADERS}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            meta = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))

        title = meta.get('title', 'Media')
        thumbnail = meta.get('thumbnail')
        context.user_data['url'] = url
        context.user_data['info'] = {'title': title, 'is_audio_only': False}

        keyboard = [
            [InlineKeyboardButton("📥 دانلود بهترین کیفیت", callback_data="fmt_best")],
            [InlineKeyboardButton("🎵 استخراج صوت (MP3)", callback_data="fmt_audio")]
        ]
        await progress_msg.delete()
        caption = f"🎬 <b>رسانه:</b> {title}\n\n👇 <b>انتخاب کیفیت:</b>"
        if thumbnail: await update.message.reply_photo(photo=thumbnail, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else: await update.message.reply_text(caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        keyboard = [[InlineKeyboardButton("⚡️ دانلود مستقیم", callback_data="fmt_best")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Media', 'is_audio_only': False}
        await progress_msg.delete()
        await update.message.reply_text("⚠️ خطا در آنالیز. تلاش برای دانلود مستقیم؟", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def edit_message_safe(query, text):
    try:
        if query.message.photo or query.message.caption: 
            await query.message.edit_caption(caption=text, parse_mode="HTML")
        else: 
            await query.edit_message_text(text=text, parse_mode="HTML")
    except: pass

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get('url')
    data = query.data
    info = context.user_data.get('info')
    
    if not url or not info:
        await query.message.reply_text("❌ اطلاعات منقضی شد. لطفاً دوباره لینک بفرستید.", parse_mode="HTML")
        return
        
    main_loop = asyncio.get_running_loop()
    chat_id = query.message.chat_id
    
    filename = None
    downloaded_files = []
    res_title = info.get('title', 'Media')
    
    try:
        await edit_message_safe(query, "⚡️ در حال دانلود فایل...")
        
        if data == "fmt_instagram":
            downloaded_files, res_title = await main_loop.run_in_executor(
                None, lambda: download_instagram_via_api(url, 'downloads')
            )
        elif data.startswith("spo_"):
            track_title = info.get('title', '')
            track_artist = info.get('artist', '')
            search_query = f"{track_artist} {track_title}".strip()
            download_url = f"ytsearch1:{search_query} audio" if data == "spo_ytm" else f"scsearch1:{search_query}"
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': 'downloads/%(id)s.%(ext)s',
                'default_search': 'auto',
                'quiet': True,
                'no_warnings': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192'
                }]
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                download_info = await main_loop.run_in_executor(None, lambda: ydl.extract_info(download_url, download=True))
                if download_info and 'entries' in download_info and download_info['entries']:
                    entry = download_info['entries'][0]
                    filename = ydl.prepare_filename(entry)
                    filename = os.path.splitext(filename)[0] + ".mp3"
                else:
                    raise Exception("موزیک مورد نظر در یوتیوب/ساندکلاد یافت نشد.")
        else:
            ydl_opts = {
                'format': 'best',
                'outtmpl': 'downloads/%(id)s.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'http_headers': BROWSER_HEADERS,
                'ignoreerrors': True
            }
            if data == "fmt_audio":
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192'
                }]
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                download_info = await main_loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
                if download_info:
                    if 'entries' in download_info:
                        for entry in download_info['entries']:
                            if entry:
                                f_path = ydl.prepare_filename(entry)
                                if data == "fmt_audio": f_path = os.path.splitext(f_path)[0] + ".mp3"
                                if os.path.exists(f_path): downloaded_files.append(f_path)
                    else:
                        filename = ydl.prepare_filename(download_info)
                        if data == "fmt_audio": filename = os.path.splitext(filename)[0] + ".mp3"
                        res_title = download_info.get('title', 'Media')

        if not filename and len(downloaded_files) == 1:
            filename = downloaded_files[0]

        if not filename and not downloaded_files:
            raise Exception("فایل یافت نشد.")

        if len(downloaded_files) > 1:
            media_group = []
            for f in downloaded_files:
                if f.lower().endswith(('.mp4', '.mkv', '.mov', '.webm')):
                    media_group.append(InputMediaVideo(open(f, 'rb')))
                else:
                    media_group.append(InputMediaPhoto(open(f, 'rb')))
            
            await context.bot.send_media_group(chat_id=chat_id, media=media_group)
            for f in downloaded_files:
                if os.path.exists(f): os.remove(f)
            await query.message.delete()
            return

        if not filename and downloaded_files:
            filename = downloaded_files[0]

        if not os.path.exists(filename):
            raise Exception("فایل خروجی ایجاد نشد.")

        _, ext = os.path.splitext(filename.lower())
        
        with open(filename, 'rb') as f_obj:
            if data == "fmt_audio" or data.startswith("spo_"):
                await context.bot.send_audio(chat_id=chat_id, audio=f_obj, caption=f"🎵 {res_title}", parse_mode="HTML")
            elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
                await context.bot.send_photo(chat_id=chat_id, photo=f_obj, caption=f"🖼️ {res_title}", parse_mode="HTML")
            else:
                await context.bot.send_video(chat_id=chat_id, video=f_obj, caption=f"🎬 {res_title}", parse_mode="HTML")
        
        if filename and os.path.exists(filename): os.remove(filename)
        for f in downloaded_files:
            if os.path.exists(f): os.remove(f)
        await query.message.delete()
        
    except Exception as e:
        if filename and os.path.exists(filename): os.remove(filename)
        for f in downloaded_files:
            if os.path.exists(f): os.remove(f)
        await query.message.reply_text(f"❌ خطا: {str(e)}", parse_mode="HTML")

def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_click))
    print("Bot is running with fixes...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
