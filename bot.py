import os
import asyncio
import re
import time
import json
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import instaloader

TOKEN = '8897975172:AAFXrND5_zFFeSsGDxD9lYdF32zwhTFtpds'

# نمونه‌ی instaloader استفاده‌شده برای گرفتن پست‌های عمومی اینستاگرام با
# کیفیت اصلی و کامل (شامل آلبوم/کروسل)، بدون نیاز به لاگین. بارها ساختنش
# گرون نیست ولی برای جلوگیری از overhead تکراری، یک‌بار در سطح ماژول
# ساخته می‌شه.
_IG_LOADER = instaloader.Instaloader(
    quiet=True,
    download_pictures=False,
    download_videos=False,
    download_video_thumbnails=False,
    download_geotags=False,
    download_comments=False,
    save_metadata=False,
    compress_json=False,
    post_metadata_txt_pattern='',
)

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
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

def get_spotify_details_pure(url):
    clean_url = url.split('?')[0]
    try:
        oembed_res = requests.get(f"https://open.spotify.com/oembed?url={clean_url}", headers=BROWSER_HEADERS, timeout=8).json()
        title_full = oembed_res.get('title', '')
        thumbnail = oembed_res.get('thumbnail_url')

        if title_full:
            if " by " in title_full:
                parts = title_full.rsplit(" by ", 1)
                song_title = parts[0].replace("- Single", "").replace("- Album", "").strip()
                artist_name = parts[1].strip()
                return {'title': song_title, 'artist': artist_name, 'thumbnail': thumbnail}
            elif " - " in title_full:
                parts = title_full.split(" - ", 1)
                return {'title': parts[1].strip(), 'artist': parts[0].strip(), 'thumbnail': thumbnail}
            else:
                return {'title': title_full, 'artist': 'نامشخص', 'thumbnail': thumbnail}
    except Exception:
        pass

    try:
        res = requests.get(clean_url, headers=BROWSER_HEADERS, timeout=10)
        if res.status_code == 200:
            og_title = re.search(r'<meta property="og:title" content="(.*?)"', res.text)
            og_desc = re.search(r'<meta property="og:description" content="(.*?)"', res.text)
            og_image = re.search(r'<meta property="og:image" content="(.*?)"', res.text)

            title = og_title.group(1) if og_title else "نامشخص"
            desc = og_desc.group(1) if og_desc else ""
            thumbnail = og_image.group(1) if og_image else None

            artist = "نامشخص"
            if "·" in desc:
                artist = desc.split("·")[0].strip()
            elif "by " in desc:
                artist = desc.split("by ")[1].split(" on ")[0].split("·")[0].strip()
            elif "Song ·" in desc:
                artist = desc.replace("Song ·", "").strip()

            if title != "نامشخص" and artist == "نامشخص":
                if " - " in title:
                    pts = title.split(" - ", 1)
                    artist, title = pts[0].strip(), pts[1].strip()

            return {'title': title, 'artist': artist, 'thumbnail': thumbnail}
    except Exception:
        pass

    return {'title': 'Spotify Track', 'artist': 'نامشخص', 'thumbnail': None}

# ---------------------------------------------------------
# دانلودر تضمینی اینستاگرام (هوشمند برای عکس، آلبوم و ویدیو)
# ---------------------------------------------------------
def download_instagram_pure(url, target_dir):
    clean_url = url.split('?')[0].rstrip('/')
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    downloaded_paths = []
    caption = ""

    # سرویس 0: instaloader — از API واقعی اینستاگرام استفاده می‌کنه (نه صفحه‌ی
    # ساده‌شده‌ی embed یا og-tag)، برای همین هم کیفیت اصلی عکس/ویدیو رو می‌ده
    # (بدون کراپ شدن) و هم برای پست‌های آلبومی همه‌ی آیتم‌ها رو برمی‌گردونه.
    # این باید اولین و مطمئن‌ترین راهه؛ فقط اگه fail بشه (مثلاً به‌خاطر ریت‌لیمیت
    # یا بلاک شدن IP) میریم سراغ سرویس‌های بعدی.
    try:
        shortcode_match = re.search(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)', clean_url)
        if shortcode_match:
            shortcode = shortcode_match.group(1)
            post = instaloader.Post.from_shortcode(_IG_LOADER.context, shortcode)
            caption = post.caption or ""

            nodes = []
            if post.typename == "GraphSidecar":
                nodes = list(post.get_sidecar_nodes())
            else:
                # یک آبجکت شبیه‌ساز ساده برای پست تکی، تا حلقه‌ی پایین یکسان بمونه
                class _SingleNode:
                    def __init__(self, is_video, display_url, video_url):
                        self.is_video = is_video
                        self.display_url = display_url
                        self.video_url = video_url
                nodes = [_SingleNode(post.is_video, post.url, post.video_url if post.is_video else None)]

            for idx, node in enumerate(nodes):
                media_url = node.video_url if node.is_video else node.display_url
                if not media_url:
                    continue
                ext = ".mp4" if node.is_video else ".jpg"
                out_p = os.path.join(target_dir, f"ig_{int(time.time())}_{idx:02d}{ext}")
                try:
                    r = session.get(media_url, stream=True, timeout=20)
                    if r.status_code == 200:
                        with open(out_p, 'wb') as f:
                            for chunk in r.iter_content(8192):
                                f.write(chunk)
                        downloaded_paths.append(out_p)
                except Exception:
                    pass

            if downloaded_paths:
                return downloaded_paths, caption
    except Exception:
        pass  # instaloader fail شد -> برو سراغ سرویس 1 (fallbackهای قدیمی)

    # سرویس 1: FastDL / SnapInsta Direct API Scraper
    try:
        api_res = session.post("https://v3.fastdl.app/api/convert", json={"url": clean_url}, timeout=12).json()
        if "url" in api_res and isinstance(api_res["url"], list):
            for idx, item in enumerate(api_res["url"]):
                media_url = item.get("url")
                if not media_url: continue
                ext = ".mp4" if item.get("type") == "video" or ".mp4" in media_url else ".jpg"
                out_path = os.path.join(target_dir, f"ig_{int(time.time())}_{idx:02d}{ext}")
                r = session.get(media_url, stream=True, timeout=15)
                if r.status_code == 200:
                    with open(out_path, 'wb') as f:
                        for chunk in r.iter_content(8192): f.write(chunk)
                    downloaded_paths.append(out_path)
            if downloaded_paths:
                return downloaded_paths, caption
    except Exception:
        pass

    # سرویس 2: Cobalt Engine
    try:
        c_res = session.post("https://api.cobalt.tools/api/json", json={
            "url": clean_url
        }, headers={
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': BROWSER_HEADERS['User-Agent']
        }, timeout=12)

        if c_res.status_code == 200:
            c_data = c_res.json()
            if c_data.get("status") == "picker":
                picker = c_data.get("picker", [])
                for idx, item in enumerate(picker):
                    m_url = item.get("url")
                    m_type = item.get("type", "photo")
                    ext = ".mp4" if m_type == "video" else ".jpg"
                    out_p = os.path.join(target_dir, f"ig_{int(time.time())}_{idx:02d}{ext}")
                    r = session.get(m_url, stream=True, timeout=15)
                    if r.status_code == 200:
                        with open(out_p, 'wb') as f:
                            for chunk in r.iter_content(8192): f.write(chunk)
                        downloaded_paths.append(out_p)
                if downloaded_paths:
                    return downloaded_paths, caption

            elif c_data.get("status") in ["redirect", "stream"]:
                m_url = c_data.get("url")
                ext = ".mp4" if ".mp4" in m_url or "video" in c_data.get("type", "") else ".jpg"
                out_p = os.path.join(target_dir, f"ig_{int(time.time())}{ext}")
                r = session.get(m_url, stream=True, timeout=15)
                if r.status_code == 200:
                    with open(out_p, 'wb') as f:
                        for chunk in r.iter_content(8192): f.write(chunk)
                    return [out_p], caption
    except Exception:
        pass

    # سرویس 3: yt-dlp — فقط برای پست‌هایی که واقعاً ویدیو دارند
    # نکته مهم: اکسترکتور اینستاگرام yt-dlp اکسپشن "There is no video in this
    # post" رو همون داخل extract_info پرتاب می‌کنه (چه download=True باشه چه
    # download=False) — یعنی این محدودیت مال مرحله‌ی دانلود نیست، بلکه yt-dlp
    # اصلاً از پست‌های فقط-عکسیِ اینستاگرام پشتیبانی نمی‌کنه. برای همین اینجا
    # کل try/except رو دور extract_info می‌ذاریم: اگه fail شد (پست عکسیه)،
    # ساکت رد میشیم و می‌ریم سراغ سرویس 4 که با اسکرپ مستقیم HTML کار می‌کنه.
    class _SilentLogger:
        def debug(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): pass

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'http_headers': BROWSER_HEADERS,
            'logger': _SilentLogger(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            meta = ydl.extract_info(clean_url, download=False)

        # پست تکی entries نداره؛ پست کروسل/آلبوم entries داره
        entries = meta.get('entries') if meta.get('entries') else [meta]

        for idx, entry in enumerate(entries):
            if not entry:
                continue

            if not caption:
                caption = entry.get('description') or entry.get('title', '') or meta.get('description', '') or ''

            is_video = bool(entry.get('vcodec') not in (None, 'none') and entry.get('url'))

            if is_video:
                v_url = entry.get('url')
                out_p = os.path.join(target_dir, f"ig_v_{int(time.time())}_{idx:02d}.mp4")
                try:
                    r = session.get(v_url, stream=True, timeout=20)
                    if r.status_code == 200:
                        with open(out_p, 'wb') as f:
                            for chunk in r.iter_content(8192):
                                f.write(chunk)
                        downloaded_paths.append(out_p)
                        continue
                except Exception:
                    pass

            # اگر ویدیو نبود یا دانلود ویدیو fail شد، تصویر پست رو بگیر
            img_url = None
            if not is_video:
                img_url = entry.get('url')
            if not img_url:
                thumbs = entry.get('thumbnails') or []
                if thumbs:
                    img_url = thumbs[-1].get('url')
            if not img_url:
                img_url = entry.get('thumbnail')

            if img_url:
                out_p = os.path.join(target_dir, f"ig_img_{int(time.time())}_{idx:02d}.jpg")
                try:
                    r = session.get(img_url, stream=True, timeout=15)
                    if r.status_code == 200:
                        with open(out_p, 'wb') as f:
                            for chunk in r.iter_content(8192):
                                f.write(chunk)
                        downloaded_paths.append(out_p)
                except Exception:
                    pass

        if downloaded_paths:
            return downloaded_paths, caption
    except Exception:
        pass  # yt-dlp نتونست (معمولاً یعنی پست فقط عکسه) -> برو سراغ سرویس 4

    # سرویس 4: صفحه‌ی عمومی embed اینستاگرام (بدون نیاز به لاگین)
    # اینستاگرام برای امکان نمایش پست در سایت‌های دیگه (embed)، یک صفحه‌ی
    # ساده و کاملاً عمومی در آدرس /p/{shortcode}/embed/captioned/ ارائه
    # می‌ده که برخلاف صفحه‌ی اصلی پست، پشت دیوار لاگین نیست و برخلاف og:image
    # (که همیشه یک نسخه‌ی کراپ‌شده‌ی مربعی برای پیش‌نمایش لینکه) عکس اصلی
    # پست رو با کیفیت کامل می‌ده. اگه پست آلبوم/کروسل باشه، JSON این صفحه
    # یک بخش "edge_sidecar_to_children" داره که همه‌ی آیتم‌های آلبوم توش
    # هست؛ همه رو استخراج می‌کنیم نه فقط اسلاید اول.
    try:
        shortcode_match = re.search(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)', clean_url)
        if shortcode_match:
            shortcode = shortcode_match.group(1)
            embed_url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
            res4 = session.get(embed_url, headers=BROWSER_HEADERS, timeout=15)
            print(f"[IG-DEBUG] service4 embed_url={embed_url} status={res4.status_code} len={len(res4.text)}")
            if res4.status_code == 200:
                html4 = res4.text

                if not caption:
                    cap_match = re.search(r'"caption"\s*:\s*"(.*?)(?<!\\)"', html4)
                    if cap_match:
                        caption = cap_match.group(1).encode().decode('unicode_escape', errors='ignore')

                def _clean_media_url(u):
                    return u.replace('\\u0026', '&').replace('\\/', '/')

                # آلبوم/کروسل: چند آیتم داخل edge_sidecar_to_children
                sidecar_idx = html4.find('"edge_sidecar_to_children"')
                print(f"[IG-DEBUG] sidecar_idx={sidecar_idx} has_display_url={'\"display_url\"' in html4} has_video_url={'\"video_url\"' in html4}")
                if sidecar_idx != -1:
                    sidecar_text = html4[sidecar_idx:]
                    node_chunks = re.split(r'\{"node":', sidecar_text)[1:]
                    print(f"[IG-DEBUG] node_chunks_count={len(node_chunks)}")
                    for idx, chunk in enumerate(node_chunks):
                        is_video_m = re.search(r'"is_video"\s*:\s*(true|false)', chunk)
                        is_video = bool(is_video_m and is_video_m.group(1) == 'true')

                        media_url = None
                        if is_video:
                            v_m = re.search(r'"video_url"\s*:\s*"(.*?)(?<!\\)"', chunk)
                            if v_m:
                                media_url = _clean_media_url(v_m.group(1))
                        if not media_url:
                            d_m = re.search(r'"display_url"\s*:\s*"(.*?)(?<!\\)"', chunk)
                            if d_m:
                                media_url = _clean_media_url(d_m.group(1))
                                is_video = False

                        if not media_url:
                            continue

                        ext = ".mp4" if is_video else ".jpg"
                        out_p = os.path.join(target_dir, f"ig_{'v' if is_video else 'img'}_{int(time.time())}_{idx:02d}{ext}")
                        try:
                            r = session.get(media_url, stream=True, timeout=20)
                            if r.status_code == 200:
                                with open(out_p, 'wb') as f:
                                    for c in r.iter_content(8192):
                                        f.write(c)
                                downloaded_paths.append(out_p)
                        except Exception:
                            pass

                # پست تکی: فقط یک ویدیو یا یک عکس
                if not downloaded_paths:
                    video_match = re.search(r'"video_url"\s*:\s*"(.*?)(?<!\\)"', html4)
                    if not video_match:
                        video_match = re.search(r'<video[^>]+src="(.*?)"', html4)

                    if video_match:
                        v_url = _clean_media_url(video_match.group(1))
                        out_p = os.path.join(target_dir, f"ig_v_{int(time.time())}.mp4")
                        r = session.get(v_url, stream=True, timeout=20)
                        if r.status_code == 200:
                            with open(out_p, 'wb') as f:
                                for chunk in r.iter_content(8192):
                                    f.write(chunk)
                            downloaded_paths.append(out_p)
                    else:
                        img_match = re.search(r'"display_url"\s*:\s*"(.*?)(?<!\\)"', html4)
                        if not img_match:
                            img_match = re.search(r'<img[^>]+class="[^"]*EmbeddedMediaImage[^"]*"[^>]+src="(.*?)"', html4)
                        if img_match:
                            img_url = _clean_media_url(img_match.group(1))
                            out_p = os.path.join(target_dir, f"ig_img_{int(time.time())}.jpg")
                            r = session.get(img_url, stream=True, timeout=15)
                            if r.status_code == 200:
                                with open(out_p, 'wb') as f:
                                    for chunk in r.iter_content(8192):
                                        f.write(chunk)
                                downloaded_paths.append(out_p)

                print(f"[IG-DEBUG] service4 downloaded_paths_count={len(downloaded_paths)}")
                if downloaded_paths:
                    return downloaded_paths, caption
    except Exception as e4:
        import traceback
        print(f"[IG-DEBUG] service4 exception: {e4}")
        traceback.print_exc()
        pass  # صفحه embed هم fail شد -> برو سراغ سرویس 5 (og-tag، آخرین fallback)

    # سرویس 5: اسکرپ og:image / og:video (آخرین fallback؛ فقط یک عکس و
    # معمولاً کراپ‌شده‌ی مربعی، چون og:image برای پیش‌نمایش لینک ساخته شده،
    # نه نمایش کامل رسانه. فقط وقتی به اینجا می‌رسیم که سرویس‌های بالا
    # هیچ‌کدوم جواب ندادن.)
    try:
        crawler_headers = {
            'User-Agent': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        res = session.get(clean_url, headers=crawler_headers, timeout=15)
        if res.status_code == 200:
            html_text = res.text

            def _extract_meta(prop):
                m = re.search(r'<meta[^>]*?property="' + prop + r'"[^>]*?content="(.*?)"', html_text)
                if not m:
                    m = re.search(r'<meta[^>]*?content="(.*?)"[^>]*?property="' + prop + r'"', html_text)
                return m.group(1) if m else None

            og_desc = _extract_meta('og:description')
            if og_desc and not caption:
                caption = og_desc.replace('&quot;', '"').replace('&amp;', '&').replace('&#039;', "'")

            og_video = _extract_meta('og:video:secure_url') or _extract_meta('og:video')
            og_image = _extract_meta('og:image')

            if og_video:
                v_url = og_video.replace('&amp;', '&')
                out_p = os.path.join(target_dir, f"ig_v_{int(time.time())}.mp4")
                r = session.get(v_url, stream=True, timeout=20)
                if r.status_code == 200:
                    with open(out_p, 'wb') as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    downloaded_paths.append(out_p)

            elif og_image:
                img_url = og_image.replace('&amp;', '&')
                out_p = os.path.join(target_dir, f"ig_img_{int(time.time())}.jpg")
                r = session.get(img_url, stream=True, timeout=15)
                if r.status_code == 200:
                    with open(out_p, 'wb') as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    downloaded_paths.append(out_p)

            if downloaded_paths:
                return downloaded_paths, caption
    except Exception:
        pass

    raise Exception("پست یافت نشد یا سرور پاسخ نداد. مطمئن شوید لینک مستقیم پست است و پابلیک/عمومی است.")


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

    raise Exception("این پست رسانه مستقیمی برای دانلود ندارد.")

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
# هندلرهای ربات
# ---------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "💎 <b>سلام؛ به ربات دانلودر پیشرفته خوش آمدید!</b>\n\n"
        "⚡️ <b>پلتفرم‌های پشتیبانی‌شده:</b>\n"
        "▫️ <b>Spotify & SoundCloud</b>\n"
        "▫️ <b>YouTube & YouTube Music</b>\n"
        "▫️ <b>Instagram</b> (پست عکسی، آلبوم، ویدیو، ریلز)\n"
        "▫️ <b>TikTok</b> (بدون واترمارک)\n"
        "▫️ <b>Pinterest & Reddit</b>\n\n"
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

    if "reddit.com" in url or "r.reddit.com" in url:
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Reddit Post', 'is_audio_only': False}
        keyboard = [[InlineKeyboardButton("⚡️ استخراج مستقیم رسانه", callback_data="fmt_best")]]
        await update.message.reply_text("📌 <b>ردیت شناسایی شد.</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
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
        keyboard = [[InlineKeyboardButton("📥 دانلود پست / ریلز / عکس", callback_data="fmt_ig")]]
        context.user_data['url'] = url
        context.user_data['info'] = {'title': 'Instagram Media', 'is_audio_only': False}
        await update.message.reply_text("🎬 <b>اینستاگرام شناسایی شد.</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    progress_msg = await update.message.reply_text("🧠 <b>در حال استخراج کیفیت‌ها...</b>", parse_mode="HTML")
    try:
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'skip_download': True, 'noplaylist': True,
            'http_headers': BROWSER_HEADERS,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            meta = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))

        formats = meta.get('formats', [])
        title = meta.get('title', 'Media')
        thumbnail = meta.get('thumbnail')
        context.user_data['url'] = url
        context.user_data['info'] = {'title': title, 'is_audio_only': False}

        # بهترین فرمت صوتی رو جدا پیدا می‌کنیم چون فایل نهایی ویدیو = ویدیو + این صدا (merge)
        # پس حجم نمایش داده‌شده باید مجموع این دو باشه، نه فقط حجم استریم ویدیو.
        audio_only_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
        best_audio_size = 0
        if audio_only_formats:
            best_audio = max(audio_only_formats, key=lambda x: x.get('abr') or 0)
            best_audio_size = best_audio.get('filesize') or best_audio.get('filesize_approx') or 0

        keyboard = []
        seen_resolutions = set()
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('height'):
                res = f"{f.get('height')}p"
                if res in seen_resolutions: continue
                video_size = f.get('filesize') or f.get('filesize_approx') or 0
                total_size = video_size + best_audio_size if video_size else 0
                size_mb = f"({total_size / (1024 * 1024):.1f} MB)" if total_size else ""
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

    is_reddit = "reddit.com" in url or "r.reddit.com" in url
    is_pinterest = "pinterest" in url or "pin.it" in url
    is_instagram = "instagram.com" in url or data == "fmt_ig"
    is_tiktok = "tiktok.com" in url or "vm.tiktok.com" in url

    if is_instagram:
        await edit_message_safe(query, "⚡️ <b>در حال استخراج عکس / ویدیو / کپشن اینستاگرام...</b>")
        try:
            ig_files, ig_caption = await main_loop.run_in_executor(
                None, lambda: download_instagram_pure(url, 'downloads')
            )
            if ig_files:
                ig_files.sort()
                clean_ig_caption = str(ig_caption).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') if ig_caption else ""

                if len(ig_files) > 1:
                    for i in range(0, len(ig_files), 10):
                        chunk_files = ig_files[i:i + 10]
                        media_group = []
                        for idx, f in enumerate(chunk_files):
                            _, f_ext = os.path.splitext(f.lower())
                            cap = clean_ig_caption if idx == 0 else ""
                            if f_ext in ['.jpg', '.jpeg', '.png', '.webp']:
                                media_group.append(InputMediaPhoto(open(f, 'rb'), caption=cap, parse_mode="HTML"))
                            elif f_ext in ['.mp4']:
                                media_group.append(InputMediaVideo(open(f, 'rb'), caption=cap, parse_mode="HTML"))

                        if media_group:
                            await context.bot.send_media_group(chat_id=query.message.chat_id, media=media_group)
                else:
                    single_file = ig_files[0]
                    _, f_ext = os.path.splitext(single_file.lower())
                    with open(single_file, 'rb') as f_obj:
                        if f_ext in ['.jpg', '.jpeg', '.png', '.webp']:
                            await context.bot.send_photo(chat_id=query.message.chat_id, photo=f_obj, caption=clean_ig_caption, parse_mode="HTML")
                        else:
                            await context.bot.send_video(chat_id=query.message.chat_id, video=f_obj, caption=clean_ig_caption, parse_mode="HTML")

                for f in ig_files:
                    if os.path.exists(f): os.remove(f)
                await query.message.delete()
                return
        except Exception as e:
            clean_err = str(e).replace("ERROR:", "").strip()
            await query.message.reply_text(f"❌ <b>خطا در پردازش اینستاگرام:</b>\n<code>{clean_err}</code>", parse_mode="HTML")
            return

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

    ydl_opts = {
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'progress_hooks': [progress_hook],
        'http_headers': BROWSER_HEADERS,
        'ignoreerrors': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
    }

    is_audio = data == "fmt_audio" or data.startswith("spo_")

    if is_audio:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }]
    elif data.startswith("vid_"):
        fmt_id = data.split("_")[1]
        ydl_opts['format'] = f"{fmt_id}+bestaudio/best"
        ydl_opts['merge_output_format'] = 'mp4'
    elif data.startswith("direct_"):
        fmt_id = data.split("_")[1]
        ydl_opts['format'] = fmt_id
    else:
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
        ydl_opts['merge_output_format'] = 'mp4'

    if data.startswith("spo_"):
        track_title = info.get('title', '')
        track_artist = info.get('artist', '')
        search_query = f"{track_artist} {track_title}".strip() if track_artist != 'نامشخص' else track_title

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
        await edit_message_safe(query, "⚡️ <b>در حال دریافت فایل...</b>")

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

        elif is_reddit and not filename:
            try:
                filename, res_title, is_image_doc = await main_loop.run_in_executor(
                    None, lambda: download_reddit_via_json(download_url, 'downloads')
                )
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
