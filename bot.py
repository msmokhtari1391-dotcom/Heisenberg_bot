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

class ProgressFileWriter:
    def __init__(self, filename, callback):
        self.file = open(filename, 'rb')
        self.total_size = os.path.getsize(filename)
        self.callback = callback

    def read(self, size=-1):
        chunk = self.file.read(size)
        if chunk:
            self.callback(len(chunk), self.total_size)
        return chunk

    def close(self):
        self.file.close()

    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

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

        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'http_headers': BROWSER_HEADERS}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            title = info.get('track') or info.get('title', 'Track')
            artist = info.get('artist') or info.get('uploader') or "نامشخص"
            thumbnail = info.get('thumbnail')

        return {'title': title, 'artist': artist, 'thumbnail': thumbnail}
    except Exception as e:
        print(f"Error extracting Spotify details: {e}")
        return {'title': 'Track', 'artist': 'نامشخص', 'thumbnail': None}

def clean_reddit_url(url):
    url = url.split('?')[0]
    url = re.sub(r'https://(www\.)?reddit\.com', 'https://old.reddit.com', url)
    url = re.sub(r'https://r\.reddit\.com', 'https://old.reddit.com', url)
    return url

def download_reddit_via_json(url, target_dir):
    try:
        session = requests.Session()
        res = session.head(url, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'})
        final_url = res.url
    except:
        final_url = url

    base_url = clean_reddit_url(final_url)
    clean_url = base_url.rstrip('/') + '.json'
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
        'Cookie': 'over18=1'
    }
    
    res = requests.get(clean_url, headers=headers, timeout=15, allow_redirects=True)
    if res.status_code != 200:
        raise Exception(f"ردیت دسترسی را مسدود کرد (Status: {res.status_code})")
        
    data = res.json()
    if not isinstance(data, list) or not data:
        raise Exception("ساختار دیتای ردیت نامعتبر است.")
        
    post_data = data[0]['data']['children'][0]['data']
    title = re.sub(r'[\\/*?:"<>|]', "", post_data.get('title', 'Reddit_Media'))
    
    media_data = post_data.get('secure_media') or post_data.get('media')
    if media_data and media_data.get('reddit_video'):
        video_url = media_data['reddit_video'].get('fallback_url')
        if video_url:
            video_url = video_url.split('?')[0]
            audio_url = re.sub(r'DASH_\d+\.mp4', 'DASH_AUDIO_128.mp4', video_url)
            v_path = os.path.join(target_dir, f"v_{int(time.time())}.mp4")
            a_path = os.path.join(target_dir, f"a_{int(time.time())}.mp4")
            out_path = os.path.join(target_dir, f"{title}.mp4")
            
            v_res = requests.get(video_url, headers=headers)
            with open(v_path, 'wb') as f: f.write(v_res.content)
            a_res = requests.get(audio_url, headers=headers)
            
            if a_res.status_code == 200:
                with open(a_path, 'wb') as f: f.write(a_res.content)
                os.system(f'ffmpeg -y -i "{v_path}" -i "{a_path}" -c:v copy -c:a aac "{out_path}" > /dev/null 2>&1')
                if os.path.exists(v_path): os.remove(v_path)
                if os.path.exists(a_path): os.remove(a_path)
            else:
                if os.path.exists(v_path): os.rename(v_path, out_path)
            return out_path, title, False

    if post_data.get('url'):
        url_lower = post_data['url'].lower()
        if any(url_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            img_url = post_data['url']
            _, ext = os.path.splitext(img_url.split('?')[0])
            out_path = os.path.join(target_dir, f"{title}{ext}")
            img_res = requests.get(img_url, headers=headers)
            with open(out_path, 'wb') as f: f.write(img_res.content)
            return out_path, title, True
        
    raise Exception("این پست رسانه مستقیم (ویدیو یا عکس) قابل استخراجی ندارد.")

def download_pinterest_pure(url, target_dir):
    headers = BROWSER_HEADERS.copy()
    session = requests.Session()
    
    response = session.get(url, headers=headers, allow_redirects=True, timeout=15)
    html_text = response.text
    
    video_url = None
    script_data = re.search(r'<script[^>]*id="__PWS_DATA__"[^>]*>(.*?)</script>', html_text, re.DOTALL)
    if script_data:
        try:
            json_raw = script_data.group(1)
            data = json.loads(json_raw)
            props = data.get('props', {}).get('initialState', {}).get('pins', {})
            for pin_id in props:
                pin_info = props[pin_id]
                videos = pin_info.get('videos', {}).get('video_list', {})
                if videos:
                    best_v = None
                    max_width = 0
                    for v_key, v_val in videos.items():
                        if isinstance(v_val, dict) and v_val.get('url'):
                            w = v_val.get('width', 0)
                            if w >= max_width:
                                max_width = w
                                best_v = v_val.get('url')
                    if best_v:
                        video_url = best_v
                        break
                
                if not video_url:
                    images = pin_info.get('images', {})
                    main_img = images.get('originals', {}).get('url') or images.get('v736x', {}).get('url')
                    if main_img:
                        target_path = os.path.join(target_dir, f"pin_{int(time.time())}.jpg")
                        img_resp = session.get(main_img, headers=headers, timeout=15)
                        if img_resp.status_code == 200:
                            with open(target_path, 'wb') as f: f.write(img_resp.content)
                            return target_path, True
        except:
            pass

    if not video_url:
        v_match = re.search(r'https://v1\.pinimg\.com/videos/[a-zA-Z0-9/_.-]+\.mp4', html_text) or \
                  re.search(r'https://v\.pinimg\.com/videos/[a-zA-Z0-9/_.-]+\.mp4', html_text)
        if v_match:
            video_url = v_match.group(0)

    if video_url:
        target_path = os.path.join(target_dir, f"pin_{int(time.time())}.mp4")
        v_resp = session.get(video_url, headers=headers, stream=True, timeout=20)
        if v_resp.status_code == 200:
            with open(target_path, 'wb') as f:
                for chunk in v_resp.iter_content(chunk_size=8192):
                    if chunk: f.write(chunk)
            return target_path, False

    img_urls = re.findall(r'https://i\.pinimg\.com/[a-zA-Z0-9/_.-]+\.(?:jpg|png|webp|jpeg)', html_text)
    filtered_urls = [img for img in img_urls if "/user/" not in img and "avatar" not in img.lower() and "/75x75" not in img]
    
    main_img = None
    for img in filtered_urls:
        if "/originals/" in img or "/736x/" in img:
            main_img = img
            break
            
    if not main_img and filtered_urls:
        main_img = filtered_urls[0]

    if main_img:
        main_img = re.sub(r'/(?:136x136|236x|474x|736x|736X)/', '/originals/', main_img)
        target_path = os.path.join(target_dir, f"pin_{int(time.time())}.jpg")
        img_resp = session.get(main_img, headers=headers, timeout=15)
        if img_resp.status_code == 200:
            with open(target_path, 'wb') as f: f.write(img_resp.content)
            return target_path, True

    raise Exception("رسانه پینترست (ویدیو یا عکس) یافت نشد.")

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

        images = data.get('images', [])
        if images:
            img_url = images[0].get('url') if isinstance(images[0], dict) else images[0]
            if img_url:
                out_path = os.path.join(target_dir, f"tt_{int(time.time())}.jpg")
                img_res = session.get(img_url, headers=headers)
                if img_res.status_code == 200:
                    with open(out_path, 'wb') as f: f.write(img_res.content)
                    return out_path, title, True

    raise Exception("دریافت ویدیو از تیک‌تاک ناموفق بود.")

# ---------------------------------------------------------
# هندلرهای تلگرام
# ---------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "💎 <b>سلام به ربات دانلودر پیشرفته خوش آمدید!</b>\n\n"
        "⚡️ <b>پلتفرم‌های پشتیبانی‌شده:</b>\n"
        "▫️ <b>Spotify</b> (دانلود موزیک همراه با کاور و متادیتای دقیق)\n"
        "▫️ <b>YouTube & YouTube Music</b> (کیفیت‌های HD/4K + MP3)\n"
        "▫️ <b>Instagram</b> (پست، ریلز و استوری)\n"
        "▫️ <b>TikTok</b> (دانلود بدون واترمارک)\n"
        "▫️ <b>Pinterest & Reddit & SoundCloud</b>\n\n"
        "🔗 <b>کافیست لینک رسانه مورد نظر خود را ارسال کنید:</b>"
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
        await message.reply_text("❌ <b>لطفاً یک لینک معتبر اینترنتی ارسال کنید.</b>", parse_mode="HTML")
        return

    url = text

    if "tiktok.com" in url or "vm.tiktok.com" in url:
        keyboard = [[InlineKeyboardButton("📥 دانلود بدون واترمارک (HD)", callback_data="fmt_best")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'TikTok Media', 'is_audio_only': False}
        await update.message.reply_text("🎵 <b>پست تیک‌تاک شناسایی شد.</b>\nجهت دریافت فایل روی دکمه زیر کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if "reddit.com" in url or "r.reddit.com" in url:
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Reddit Post', 'is_audio_only': False}
        keyboard = [[InlineKeyboardButton("⚡️ استخراج مستقیم رسانه", callback_data="fmt_best")]]
        await update.message.reply_text("📌 <b>پست ردیت شناسایی شد.</b>\nجهت دریافت بدون محدودیت کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if "spotify.com" in url:
        progress_msg = await update.message.reply_text("🔍 <b>در حال استخراج دقیق متادیتا و کاور از اسپاتیفای...</b>", parse_mode="HTML")
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
            f"🎵 <b>عنوان اثر:</b> {title}\n"
            f"👤 <b>خواننده:</b> {artist}\n\n"
            f"✨ <b>پلتفرم دانلود مورد نظر را انتخاب کنید:</b>"
        )
        if thumbnail:
            await update.message.reply_photo(photo=thumbnail, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if "soundcloud.com" in url:
        progress_msg = await update.message.reply_text("🔍 <b>در حال بررسی لینک ساندکلاد...</b>", parse_mode="HTML")
        sc_title, sc_thumbnail = "SoundCloud Track", None
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'http_headers': BROWSER_HEADERS}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                sc_info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                sc_title = sc_info.get('title', 'SoundCloud Track')
                sc_thumbnail = sc_info.get('thumbnail')
        except: pass
        await progress_msg.delete()
        context.user_data['url'] = url
        context.user_data['info'] = {'is_audio_only': True, 'title': sc_title}
        keyboard = [[InlineKeyboardButton("🎧 دانلود کیفیت عالی (MP3)", callback_data="fmt_audio")]]
        caption = f"🎧 <b>موزیک ساندکلاد:</b>\n📌 <b>نام:</b> {sc_title}"
        if sc_thumbnail: await update.message.reply_photo(photo=sc_thumbnail, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else: await update.message.reply_text(caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if "pinterest" in url or "pin.it" in url:
        keyboard = [[InlineKeyboardButton("📸 دانلود تصویر / ویدیو کیفیت اصلی", callback_data="fmt_best")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Pinterest Media', 'is_audio_only': False}
        await update.message.reply_text("📸 <b>پینترست شناسایی شد.</b>\nجهت دریافت فایل اصلی کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if "instagram.com" in url:
        keyboard = [[InlineKeyboardButton("📥 دانلود فوری پست / ریلز", callback_data="fmt_best")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Instagram Media', 'is_audio_only': False}
        await update.message.reply_text("🎬 <b>اینستاگرام شناسایی شد.</b>\nبرای دانلود با بهترین کیفیت کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    progress_msg = await update.message.reply_text("🧠 <b>در حال آنالیز لینک و بررسی کیفیت‌های موجود...</b>", parse_mode="HTML")
    try:
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'noplaylist': True, 'http_headers': BROWSER_HEADERS}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            meta = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))

        formats = meta.get('formats', [])
        title = meta.get('title', 'Media')
        thumbnail = meta.get('thumbnail')
        context.user_data['url'] = url
        context.user_data['info'] = {'title': title, 'is_audio_only': False}

        keyboard = []
        seen_resolutions = set()
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('height'):
                res = f"{f.get('height')}p"
                if res in seen_resolutions: continue
                size = f.get('filesize') or f.get('filesize_approx')
                size_mb = f"({size / (1024 * 1024):.1f} MB)" if size else ""
                fmt_id = f.get('format_id')
                callback_id = f"vid_{fmt_id}" if "youtube.com" in url or "youtu.be" in url else f"direct_{fmt_id}"
                keyboard.append([InlineKeyboardButton(f"🎬 کیفیت {res} {size_mb}", callback_data=callback_id)])
                seen_resolutions.add(res)
        
        if not keyboard:
            keyboard.append([InlineKeyboardButton("📥 دانلود بهترین کیفیت موجود", callback_data="fmt_best")])

        keyboard.append([InlineKeyboardButton("🎵 استخراج فقط صدا (MP3 Audio)", callback_data="fmt_audio")])
        await progress_msg.delete()
        caption = f"🎬 <b>رسانه شناسایی شد:</b>\n📌 <b>عنوان:</b> {title}\n\n👇 <b>کیفیت مورد نظرتان را انتخاب کنید:</b>"
        if thumbnail: await update.message.reply_photo(photo=thumbnail, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else: await update.message.reply_text(caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        keyboard = [[InlineKeyboardButton("⚡️ دانلود مستقیم (پشتیبان)", callback_data="fmt_best")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Media', 'is_audio_only': False}
        await progress_msg.delete()
        await update.message.reply_text("⚠️ <b>آنالیز کیفیت‌ها موفق نبود. تلاش جهت دانلود مستقیم؟</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

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
        await query.message.reply_text("❌ <b>اطلاعات نشست منقضی شده است. لطفاً لینک را دوباره ارسال کنید.</b>", parse_mode="HTML")
        return
        
    main_loop = asyncio.get_running_loop()
    last_update_time = time.time()
    
    def progress_hook(d):
        nonlocal last_update_time
        current_time = time.time()
        if d['status'] == 'finished':
            asyncio.run_coroutine_threadsafe(edit_message_safe(query, "⚡️ <b>دانلود کامل شد! در حال پردازش و تبدیل...</b>"), main_loop)
            return
        if d['status'] == 'downloading' and current_time - last_update_time > 0.5:
            last_update_time = current_time
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            if total > 0:
                percent = (downloaded / total) * 100
                speed = d.get('speed', 0) or 0
                speed_mb = speed / (1024 * 1024) if speed > 0 else 0
                filled_blocks = int(percent // 10)
                bar = "🟦" * filled_blocks + "⬜" * (10 - filled_blocks)
                status_text = f"📥 <b>در حال دریافت فایل از سرور...</b>\n\n{bar} <code>{percent:.1f}%</code> \n🚀 <b>سرعت:</b> <code>{speed_mb:.2f} MB/s</code>"
            else:
                status_text = "📥 <b>در حال استخراج و دانلود فایل...</b>"
            asyncio.run_coroutine_threadsafe(edit_message_safe(query, status_text), main_loop)

    is_reddit = "reddit.com" in url or "r.reddit.com" in url
    is_pinterest = "pinterest" in url or "pin.it" in url
    is_instagram = "instagram.com" in url
    is_tiktok = "tiktok.com" in url or "vm.tiktok.com" in url
    
    reddit_bypass_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': '*/*',
        'Cookie': 'over18=1',
        'Referer': 'https://old.reddit.com/'
    } if is_reddit else BROWSER_HEADERS

    ydl_opts = {
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'progress_hooks': [progress_hook],
        'http_headers': reddit_bypass_headers,
        'ignoreerrors': True
    }
    
    if is_instagram:
        ydl_opts['format'] = 'best'
        ydl_opts['outtmpl'] = 'downloads/ig_%(id)s_%(autonumber)s.%(ext)s'
        ydl_opts['extractor_args'] = {'instagram': {'max_comments': [0]}}
    
    is_audio = data == "fmt_audio" or data.startswith("spo_")
    
    if is_audio:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }]
    elif not is_instagram and data.startswith("vid_"):
        fmt_id = data.split("_")[1]
        ydl_opts['format'] = f"{fmt_id}+bestaudio/best"
        ydl_opts['merge_output_format'] = 'mp4'
    elif not is_instagram and data.startswith("direct_"):
        fmt_id = data.split("_")[1]
        ydl_opts['format'] = fmt_id
    elif not is_instagram and not is_instagram:
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
        ydl_opts['merge_output_format'] = 'mp4'

    if data.startswith("spo_"):
        track_title = info.get('title', '')
        track_artist = info.get('artist', '')
        search_query = f"{track_artist} {track_title}".strip()
        
        if data == "spo_ytm":
            download_url = f"ytsearch1:{search_query} audio"
        else:
            download_url = f"scsearch1:{search_query}"
        ydl_opts['default_search'] = 'auto'
    else:
        download_url = url

    filename = None
    downloaded_files = []
    res_title = info.get('title', 'Media')
    is_image_doc = False
    
    try:
        await edit_message_safe(query, "⚡️ <b>در حال اتصال به سرور و دانلود فایل اصلی...</b>")
        
        if is_tiktok:
            try:
                filename, res_title, is_image_doc = await main_loop.run_in_executor(
                    None, lambda: download_tiktok_pure(download_url, 'downloads')
                )
            except:
                is_tiktok = False

        if is_pinterest and not filename:
            res_title = "Pinterest Media"
            try:
                filename, is_image_doc = await main_loop.run_in_executor(
                    None, lambda: download_pinterest_pure(download_url, 'downloads')
                )
            except:
                is_pinterest = False
                
        elif is_reddit and not filename:
            try:
                filename, res_title, is_image_doc = await main_loop.run_in_executor(
                    None, lambda: download_reddit_via_json(download_url, 'downloads')
                )
            except:
                is_reddit = False
        
        if not is_pinterest and not is_tiktok and not filename:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                download_info = await main_loop.run_in_executor(None, lambda: ydl.extract_info(download_url, download=True))
                
                if download_info and 'entries' in download_info and download_info['entries']:
                    for entry in download_info['entries']:
                        if entry:
                            f_path = ydl.prepare_filename(entry)
                            if data.startswith("spo_"):
                                f_path = os.path.splitext(f_path)[0] + ".mp3"
                            if os.path.exists(f_path): downloaded_files.append(f_path)
                            else:
                                base, _ = os.path.splitext(f_path)
                                for ext in ['.mp3', '.mp4', '.jpg', '.jpeg', '.png', '.webp', '.mkv']:
                                    if os.path.exists(base + ext):
                                        downloaded_files.append(base + ext)
                                        break
                else:
                    active_info = download_info
                    if active_info:
                        filename = ydl.prepare_filename(active_info)
                        if data.startswith("spo_"):
                            filename = os.path.splitext(filename)[0] + ".mp3"
                        if not data.startswith("spo_"):
                            res_title = active_info.get('title', 'Media')
                        
                        if not os.path.exists(filename):
                            base, _ = os.path.splitext(filename)
                            for ext in ['.mp3', '.mp4', '.jpg', '.jpeg', '.png', '.webp', '.mkv']:
                                if os.path.exists(base + ext):
                                    filename = base + ext
                                    break

        if not filename and downloaded_files:
            filename = downloaded_files[0]

        if not filename or not os.path.exists(filename):
            raise Exception("فایل موردنظر در سرور منبع پیدا نشد یا دانلود نشد.")

        chat_id = query.message.chat_id

        if len(downloaded_files) > 1 and not is_audio:
            media_group = []
            for f in downloaded_files:
                _, f_ext = os.path.splitext(f.lower())
                if f_ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    media_group.append(InputMediaPhoto(open(f, 'rb')))
                elif f_ext in ['.mp4', '.mkv']:
                    media_group.append(InputMediaVideo(open(f, 'rb')))
            
            if media_group:
                await context.bot.send_media_group(chat_id=chat_id, media=media_group)
                for f in downloaded_files:
                    if os.path.exists(f): os.remove(f)
                await query.message.delete()
                return

        last_upload_update = time.time()
        uploaded_bytes = 0

        def sync_upload_progress(chunk_len, total_bytes):
            nonlocal last_upload_update, uploaded_bytes
            uploaded_bytes += chunk_len
            now = time.time()
            if now - last_upload_update > 0.5 or uploaded_bytes == total_bytes:
                last_upload_update = now
                percent = (uploaded_bytes / total_bytes) * 100
                filled_blocks = int(percent // 10)
                bar = "🟩" * filled_blocks + "⬜" * (10 - filled_blocks)
                status_text = f"📤 <b>در حال آپلود روی تلگرام...</b>\n\n{bar} <code>{percent:.1f}%</code>"
                context.application.create_task(edit_message_safe(query, status_text))

        _, ext = os.path.splitext(filename.lower())
        
        with ProgressFileWriter(filename, sync_upload_progress) as tracked_file:
            safe_title = str(res_title).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            if is_audio:
                artist_name = str(info.get('artist', 'نامشخص')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                song_title = str(info.get('title', res_title)).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                caption_text = f"🎵 <b>{song_title}</b>\n👤 <b>خواننده:</b> {artist_name}\n\n🤖 @Heisenberg_bot"
                await context.bot.send_audio(
                    chat_id=chat_id, audio=tracked_file, 
                    filename=f"{artist_name} - {song_title}.mp3",
                    caption=caption_text, 
                    performer=artist_name, 
                    title=song_title,
                    read_timeout=180, write_timeout=180, parse_mode="HTML"
                )
            elif (ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif'] or is_image_doc) and ext != '.mp4':
                await context.bot.send_photo(
                    chat_id=chat_id, photo=tracked_file,
                    caption=f"🖼️ <b>{safe_title}</b>\n\n🤖 @Heisenberg_bot", parse_mode="HTML"
                )
            else:
                await context.bot.send_video(
                    chat_id=chat_id, video=tracked_file, filename=os.path.basename(filename),
                    caption=f"🎬 <b>{safe_title}</b>\n\n🤖 @Heisenberg_bot", 
                    read_timeout=180, write_timeout=180, parse_mode="HTML"
                )
        
        if filename and os.path.exists(filename): os.remove(filename)
        for f in downloaded_files:
            if os.path.exists(f): os.remove(f)
        await query.message.delete()
        
    except Exception as e:
        if filename and os.path.exists(filename): os.remove(filename)
        for f in downloaded_files:
            if os.path.exists(f): os.remove(f)
        clean_err = str(e).replace("ERROR:", "").strip()
        await query.message.reply_text(f"❌ <b>خطا در دانلود یا ارسال نهایی:</b>\n<code>{clean_err}</code>", parse_mode="HTML")

def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    
    app = Application.builder().token(TOKEN).connect_timeout(180).read_timeout(180).write_timeout(180).pool_timeout(180).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_click))
    print("Bot is running successfully with fixed Instagram & downloaders...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
