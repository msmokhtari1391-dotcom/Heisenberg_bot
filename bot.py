import os
import asyncio
import re
import time
import json
import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp

# ---------------------------------------------------------
# تنظیمات اولیه
# ---------------------------------------------------------
TOKEN = '8897975172:AAFXrND5_zFFeSsGDxD9lYdF32zwhTFtpds'

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
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
            try:
                self.callback(len(chunk), self.total_size)
            except Exception:
                pass
        return chunk

    def close(self):
        try:
            self.file.close()
        except:
            pass

    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

def find_latest_downloaded_file(target_dir='downloads', max_age_seconds=120):
    if not os.path.exists(target_dir):
        return None
    files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if not f.endswith('.tmp') and not f.endswith('.part')]
    if not files:
        return None
    latest_file = max(files, key=os.path.getctime)
    if time.time() - os.path.getctime(latest_file) <= max_age_seconds:
        return latest_file
    return None

# ---------------------------------------------------------
# بخش اینستاگرام (بدون کوکی و با ۵ API چرخشی)
# ---------------------------------------------------------
def download_instagram_pure(url, target_dir):
    clean_url = url.split('?')[0].rstrip('/')
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    
    downloaded_paths = []

    # ۱. تست سرورهای Cobalt
    cobalt_instances = [
        "https://api.cobalt.tools/",
        "https://cobalt-api.kwiatekm.tokyo/",
        "https://co.wuk.sh/",
        "https://cobalt.q1.i.ng/"
    ]
    
    for endpoint in cobalt_instances:
        try:
            payload = {"url": clean_url, "videoQuality": "max", "filenamePattern": "basic"}
            res = session.post(endpoint, json=payload, headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=8)
            if res.status_code == 200:
                data = res.json()
                status = data.get("status")
                
                if status in ["redirect", "tunnel"]:
                    media_url = data.get("url")
                    ext = ".mp4" if (".mp4" in media_url or "video" in media_url.lower()) else ".jpg"
                    out_path = os.path.join(target_dir, f"ig_{int(time.time())}_00{ext}")
                    
                    r = session.get(media_url, stream=True, timeout=20)
                    if r.status_code == 200:
                        with open(out_path, 'wb') as f:
                            for chunk in r.iter_content(8192): f.write(chunk)
                        return [out_path]

                elif status == "picker":
                    for idx, item in enumerate(data.get("picker", [])):
                        media_url = item.get("url")
                        ext = ".mp4" if item.get("type") == "video" else ".jpg"
                        out_path = os.path.join(target_dir, f"ig_{int(time.time())}_{idx:02d}{ext}")
                        r = session.get(media_url, stream=True, timeout=20)
                        if r.status_code == 200:
                            with open(out_path, 'wb') as f:
                                for chunk in r.iter_content(8192): f.write(chunk)
                            downloaded_paths.append(out_path)
                    if downloaded_paths:
                        return sorted(downloaded_paths)
        except Exception:
            continue

    # ۲. تست API کمکی TikWM
    try:
        backup_api = f"https://api.v2.tikwm.com/api/?url={clean_url}"
        res = session.get(backup_api, timeout=10).json()
        if res.get("data"):
            data = res["data"]
            if "images" in data and data["images"]:
                for idx, img_u in enumerate(data["images"]):
                    out_path = os.path.join(target_dir, f"ig_{int(time.time())}_{idx:02d}.jpg")
                    r = session.get(img_u, timeout=15)
                    if r.status_code == 200:
                        with open(out_path, 'wb') as f: f.write(r.content)
                        downloaded_paths.append(out_path)
                if downloaded_paths:
                    return downloaded_paths

            v_url = data.get("play") or data.get("wmplay")
            if v_url:
                out_path = os.path.join(target_dir, f"ig_{int(time.time())}_backup.mp4")
                r = session.get(v_url, stream=True, timeout=15)
                if r.status_code == 200:
                    with open(out_path, 'wb') as f:
                        for chunk in r.iter_content(8192): f.write(chunk)
                    return [out_path]
    except Exception:
        pass

    # ۳. تست DDInstagram
    try:
        dd_url = clean_url.replace("instagram.com", "ddinstagram.com")
        r = session.get(dd_url, timeout=10)
        if r.status_code == 200:
            videos = re.findall(r'property="og:video" content="([^"]+)"', r.text)
            images = re.findall(r'property="og:image" content="([^"]+)"', r.text)
            
            target_media = videos[0] if videos else (images[0] if images else None)
            if target_media:
                target_media = target_media.replace("&amp;", "&")
                ext = ".mp4" if videos else ".jpg"
                out_path = os.path.join(target_dir, f"ig_{int(time.time())}_dd{ext}")
                media_res = session.get(target_media, stream=True, timeout=20)
                if media_res.status_code == 200:
                    with open(out_path, 'wb') as f:
                        for chunk in media_res.iter_content(8192): f.write(chunk)
                    return [out_path]
    except Exception:
        pass

    raise Exception("دریافت رسانه اینستاگرام ناموفق بود. ممکن است پیج خصوصی باشد.")

# ---------------------------------------------------------
# بخش اسپاتیفای
# ---------------------------------------------------------
def get_spotify_details_pure(url):
    clean_url = url.split('?')[0]
    headers = {
        'User-Agent': BROWSER_HEADERS['User-Agent'],
        'Accept-Language': 'en-US,en;q=0.9'
    }
    
    title = "Track"
    artist = "نامشخص"
    thumbnail = None

    try:
        res = requests.get(clean_url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            
            og_title = soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                title = og_title['content']
                
            og_img = soup.find('meta', property='og:image')
            if og_img and og_img.get('content'):
                thumbnail = og_img['content']

            meta_artist = soup.find('meta', property='music:musician') or soup.find('meta', name='twitter:audio:artist_name')
            if meta_artist and meta_artist.get('content'):
                artist = meta_artist['content']
            else:
                og_desc = soup.find('meta', property='og:description')
                if og_desc and og_desc.get('content'):
                    desc = og_desc['content']
                    if "·" in desc:
                        parts = desc.split("·")
                        artist = parts[0].replace("Listen to", "").strip()
                    elif "Song ·" in desc:
                        artist = desc.split("Song ·")[1].split("·")[0].strip()
                        
            if artist != "نامشخص" and title != "Track":
                return {'title': title, 'artist': artist, 'thumbnail': thumbnail}
    except Exception:
        pass

    try:
        oembed_url = f"https://open.spotify.com/oembed?url={clean_url}"
        res = requests.get(oembed_url, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            title_full = data.get('title', '')
            thumbnail = thumbnail or data.get('thumbnail_url')
            
            if " by " in title_full:
                parts = title_full.rsplit(" by ", 1)
                title = parts[0].strip()
                artist = parts[1].strip()
            elif " - " in title_full:
                parts = title_full.split(" - ", 1)
                artist = parts[0].strip()
                title = parts[1].strip()
            else:
                title = title_full

            return {'title': title, 'artist': artist, 'thumbnail': thumbnail}
    except Exception:
        pass

    return {'title': title, 'artist': artist, 'thumbnail': thumbnail}

# ---------------------------------------------------------
# پینترست و تیک‌تاک
# ---------------------------------------------------------
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
    
    main_img = filtered_urls[0] if filtered_urls else None

    if main_img:
        main_img = re.sub(r'/(?:136x136|236x|474x|736x|736X)/', '/originals/', main_img)
        target_path = os.path.join(target_dir, f"pin_{int(time.time())}.jpg")
        img_resp = session.get(main_img, headers=headers, timeout=15)
        if img_resp.status_code == 200:
            with open(target_path, 'wb') as f: f.write(img_resp.content)
            return target_path, True

    raise Exception("رسانه پینترست یافت نشد.")

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
        "💎 <b>سلام؛ به ربات دانلودر پیشرفته خوش آمدید!</b>\n\n"
        "⚡️ <b>پلتفرم‌های پشتیبانی‌شده:</b>\n"
        "▫️ <b>Spotify & SoundCloud</b>\n"
        "▫️ <b>YouTube & YouTube Music</b>\n"
        "▫️ <b>Instagram</b> (پست، ریلز و تمام اسلایدهای کاروسل)\n"
        "▫️ <b>TikTok</b> (بدون واترمارک)\n"
        "▫️ <b>Pinterest</b>\n\n"
        "🔗 <b>لینک رسانه خود را ارسال کنید:</b>"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    
    try:
        await message.set_reaction("🔥")
    except Exception:
        pass

    if not text.startswith(("http://", "https://")):
        await message.reply_text("❌ <b>لطفاً یک لینک معتبر ارسال کنید.</b>", parse_mode="HTML")
        return

    url = text

    if "tiktok.com" in url or "vm.tiktok.com" in url:
        keyboard = [[InlineKeyboardButton("📥 دانلود بدون واترمارک", callback_data="fmt_best")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'TikTok Media', 'is_audio_only': False}
        await update.message.reply_text("🎵 <b>تیک‌تاک شناسایی شد.</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if "spotify.com" in url:
        progress_msg = await update.message.reply_text("🔍 <b>در حال استخراج اطلاعات از اسپاتیفای...</b>", parse_mode="HTML")
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
        
        caption = f"🎵 <b>{title}</b>\n👤 <b>خواننده: {artist}</b>\n\n✨ <b>منبع دانلود را انتخاب کنید:</b>"
        if thumbnail:
            await update.message.reply_photo(photo=thumbnail, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if "soundcloud.com" in url:
        progress_msg = await update.message.reply_text("🔍 <b>بررسی ساندکلاد...</b>", parse_mode="HTML")
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
        keyboard = [[InlineKeyboardButton("🎧 دانلود فایل صوتی (MP3)", callback_data="fmt_audio")]]
        caption = f"🎧 <b>موزیک ساندکلاد:</b>\n📌 {sc_title}"
        if sc_thumbnail: await update.message.reply_photo(photo=sc_thumbnail, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else: await update.message.reply_text(caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if "pinterest" in url or "pin.it" in url:
        keyboard = [[InlineKeyboardButton("📸 دانلود فایل اصلی", callback_data="fmt_best")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Pinterest Media', 'is_audio_only': False}
        await update.message.reply_text("📸 <b>پینترست شناسایی شد.</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if "instagram.com" in url:
        keyboard = [[InlineKeyboardButton("📥 دانلود پست / ریلز", callback_data="fmt_best")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Instagram Media', 'is_audio_only': False}
        await update.message.reply_text("🎬 <b>اینستاگرام شناسایی شد.</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    progress_msg = await update.message.reply_text("🧠 <b>در حال استخراج کیفیت‌ها...</b>", parse_mode="HTML")
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
                callback_id = f"vid_{fmt_id}" if ("youtube.com" in url or "youtu.be" in url) else f"direct_{fmt_id}"
                keyboard.append([InlineKeyboardButton(f"🎬 کیفیت {res} {size_mb}", callback_data=callback_id)])
                seen_resolutions.add(res)
        
        if not keyboard:
            keyboard.append([InlineKeyboardButton("📥 دانلود بهترین کیفیت", callback_data="fmt_best")])

        keyboard.append([InlineKeyboardButton("🎵 تبدیل به صوت (MP3)", callback_data="fmt_audio")])
        await progress_msg.delete()
        caption = f"🎬 <b>{title}</b>\n\n👇 <b>انتخاب کیفیت:</b>"
        if thumbnail: await update.message.reply_photo(photo=thumbnail, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else: await update.message.reply_text(caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception:
        keyboard = [[InlineKeyboardButton("⚡️ دانلود مستقیم", callback_data="fmt_best")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Media', 'is_audio_only': False}
        await progress_msg.delete()
        await update.message.reply_text("⚠️ <b>امکان آنالیز دقیق نبود. برای دانلود مستقیم کلیک کنید:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

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
        await query.message.reply_text("❌ <b>اطلاعات منقضی شد. لطفاً دوباره لینک بفرستید.</b>", parse_mode="HTML")
        return
        
    main_loop = asyncio.get_running_loop()
    last_update_time = time.time()
    
    def progress_hook(d):
        nonlocal last_update_time
        current_time = time.time()
        if d['status'] == 'finished':
            asyncio.run_coroutine_threadsafe(edit_message_safe(query, "⚡️ <b>دانلود کامل شد! در حال ارسال...</b>"), main_loop)
            return
        if d['status'] == 'downloading' and current_time - last_update_time > 0.8:
            last_update_time = current_time
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            if total > 0:
                percent = (downloaded / total) * 100
                speed = d.get('speed', 0) or 0
                speed_mb = speed / (1024 * 1024) if speed > 0 else 0
                filled_blocks = int(percent // 10)
                bar = "🟦" * filled_blocks + "⬜" * (10 - filled_blocks)
                status_text = f"📥 <b>در حال دانلود...</b>\n\n{bar} <code>{percent:.1f}%</code> \n🚀 <b>سرعت:</b> <code>{speed_mb:.2f} MB/s</code>"
                asyncio.run_coroutine_threadsafe(edit_message_safe(query, status_text), main_loop)

    is_pinterest = "pinterest" in url or "pin.it" in url
    is_instagram = "instagram.com" in url
    is_tiktok = "tiktok.com" in url or "vm.tiktok.com" in url
    
    ydl_opts = {
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'progress_hooks': [progress_hook],
        'http_headers': BROWSER_HEADERS,
        'ignoreerrors': True
    }
    
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
    elif not is_instagram:
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
    res_title = info.get('title', 'Media')
    is_image_doc = False
    
    try:
        await edit_message_safe(query, "⚡️ <b>در حال دانلود رسانه...</b>")
        
        if is_instagram:
            try:
                ig_files = await main_loop.run_in_executor(
                    None, lambda: download_instagram_pure(download_url, 'downloads')
                )
                if ig_files:
                    ig_files.sort()
                    if len(ig_files) == 1:
                        filename = ig_files[0]
                    else:
                        for i in range(0, len(ig_files), 10):
                            chunk_files = ig_files[i:i + 10]
                            media_group = []
                            for f in chunk_files:
                                _, f_ext = os.path.splitext(f.lower())
                                if f_ext in ['.jpg', '.jpeg', '.png', '.webp']:
                                    media_group.append(InputMediaPhoto(open(f, 'rb')))
                                elif f_ext in ['.mp4']:
                                    media_group.append(InputMediaVideo(open(f, 'rb')))
                            
                            if media_group:
                                await context.bot.send_media_group(chat_id=query.message.chat_id, media=media_group)
                        
                        for f in ig_files:
                            if os.path.exists(f): os.remove(f)
                        await query.message.delete()
                        return
            except Exception as e:
                raise Exception(str(e))

        if is_tiktok and not filename:
            try:
                filename, res_title, is_image_doc = await main_loop.run_in_executor(
                    None, lambda: download_tiktok_pure(download_url, 'downloads')
                )
            except: pass

        if is_pinterest and not filename:
            try:
                filename, is_image_doc = await main_loop.run_in_executor(
                    None, lambda: download_pinterest_pure(download_url, 'downloads')
                )
                res_title = "Pinterest Media"
            except: pass
        
        if not filename:
            files_before = set(os.listdir('downloads')) if os.path.exists('downloads') else set()
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                await main_loop.run_in_executor(None, lambda: ydl.extract_info(download_url, download=True))

            files_after = set(os.listdir('downloads')) if os.path.exists('downloads') else set()
            new_files = list(files_after - files_before)

            if new_files:
                filename = os.path.join('downloads', new_files[0])
            else:
                filename = find_latest_downloaded_file('downloads', max_age_seconds=120)

        if not filename or not os.path.exists(filename):
            raise Exception("فایل موردنظر دانلود نشد.")

        chat_id = query.message.chat_id

        last_upload_update = time.time()
        uploaded_bytes = 0

        def sync_upload_progress(chunk_len, total_bytes):
            nonlocal last_upload_update, uploaded_bytes
            uploaded_bytes += chunk_len
            now = time.time()
            if now - last_upload_update > 0.8 or uploaded_bytes == total_bytes:
                last_upload_update = now
                percent = (uploaded_bytes / total_bytes) * 100
                filled_blocks = int(percent // 10)
                bar = "🟩" * filled_blocks + "⬜" * (10 - filled_blocks)
                status_text = f"📤 <b>در حال آپلود به تلگرام...</b>\n\n{bar} <code>{percent:.1f}%</code>"
                context.application.create_task(edit_message_safe(query, status_text))

        _, ext = os.path.splitext(filename.lower())
        
        with ProgressFileWriter(filename, sync_upload_progress) as tracked_file:
            safe_title = str(res_title).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            if is_audio or ext in ['.mp3', '.m4a', '.ogg', '.wav', '.flac']:
                artist_name = str(info.get('artist', 'نامشخص')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                song_title = str(info.get('title', res_title)).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                caption_text = f"🎵 <b>{song_title}</b>\n👤 <b>خواننده:</b> {artist_name}"
                await context.bot.send_audio(
                    chat_id=chat_id, audio=tracked_file, 
                    filename=os.path.basename(filename),
                    caption=caption_text, 
                    performer=artist_name, 
                    title=song_title,
                    read_timeout=180, write_timeout=180, parse_mode="HTML"
                )
            elif (ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif'] or is_image_doc) and ext != '.mp4':
                await context.bot.send_photo(
                    chat_id=chat_id, photo=tracked_file,
                    caption=f"🖼️ <b>{safe_title}</b>", parse_mode="HTML"
                )
            else:
                await context.bot.send_video(
                    chat_id=chat_id, video=tracked_file, filename=os.path.basename(filename),
                    caption=f"🎬 <b>{safe_title}</b>", 
                    read_timeout=180, write_timeout=180, parse_mode="HTML"
                )
        
        if filename and os.path.exists(filename): 
            os.remove(filename)
        await query.message.delete()
        
    except Exception as e:
        if filename and os.path.exists(filename): 
            os.remove(filename)
        clean_err = str(e).replace("ERROR:", "").strip()
        await query.message.reply_text(f"❌ <b>خطا در پردازش یا ارسال:</b>\n<code>{clean_err}</code>", parse_mode="HTML")

def main():
    if not os.path.exists('downloads'): 
        os.makedirs('downloads')
    
    app = Application.builder().token(TOKEN).connect_timeout(180).read_timeout(180).write_timeout(180).pool_timeout(180).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_click))
    
    print("Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
