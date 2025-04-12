#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Vericu Tuning YouTube Downloader V1.9TDI
----------------------------------------
A complete PyQt5 application with:
  - A compact advanced-mode GUI with a dark color scheme, drag-and-drop, and persistent settings.
  - Cookies support: specify a cookies file via a text field with a Browse button.
  - FFmpeg integration: if not found in PATH, an ffmpeg.exe (from your project) is copied
    into a temporary folder and later cleaned up.
  - Download functionality (via yt_dlp) for both audio and video, with dynamic Format and Quality options.
  - Album art lookup: first via iTunes then falling back to YouTube (preferring square images).
  - Post-download processing:
       • For audio: if “Remove Silence” is checked, leading silence is removed precisely.
         (It detects silence using FFmpeg with a 0.1-second duration at -25dB and trims so that 0.3 seconds
          of ambient sound are preserved.)
       • For audio: if “Process Metadata” is checked, metadata is processed after download.
       • For video: the YouTube thumbnail is automatically embedded.
  - Support for multiple URLs via a pop-up dialog.
  - A combined control row (Remove Silence, Process Metadata, Multi-URLs, Download, and Documentation).
  - Persistent settings and download history.
  - An About button that shows licensing and contact information.
  
Requirements:
  - PyQt5, yt_dlp, requests, Pillow
  - An “ffmpeg.exe” must be located in the project directory.

Note: On launch, the script auto-installs missing dependencies.
"""

import sys, os, re, shutil, subprocess, time, tempfile, concurrent.futures, json
from datetime import datetime
from io import BytesIO
from urllib.parse import quote

######################################################################
# Dependency Installer
######################################################################
def install_dependencies():
    try:
        import importlib
        required = ["PyQt5", "yt_dlp", "requests", "PIL"]
        missing = []
        for pkg in required:
            try:
                importlib.import_module(pkg)
            except ImportError:
                missing.append(pkg)
        if missing:
            print("Missing dependencies detected. Installing:", missing)
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
            print("Dependencies installed. Please restart the application.")
            sys.exit(0)
    except Exception as e:
        print("Auto dependency installation failed:", str(e))
        sys.exit(1)

install_dependencies()

######################################################################
# Now import the modules.
######################################################################
import requests
from PIL import Image
import yt_dlp
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout,
    QFileDialog, QComboBox, QTextEdit, QListWidget, QLineEdit, QStyleFactory,
    QSplitter, QProgressBar, QSlider, QMessageBox, QCheckBox, QDialog
)
from PyQt5.QtCore import Qt, QSettings, QThread, pyqtSignal
from PyQt5.QtGui import QDropEvent

import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("VericuTuningDownloader")

######################################################################
# Global Settings and Executors
######################################################################
APP_ORG = "VericuTuning"
APP_NAME = "Downloader"
settings = QSettings(APP_ORG, APP_NAME)
metadata_process_executor = concurrent.futures.ProcessPoolExecutor(max_workers=4)
general_executor = concurrent.futures.ThreadPoolExecutor(max_workers=12)

######################################################################
# FFmpeg Handling
######################################################################
FFMPEG_PATH = None
def setup_ffmpeg_embedded():
    temp_dir = tempfile.mkdtemp()
    ffmpeg_src = os.path.join(os.getcwd(), "ffmpeg.exe")
    ffmpeg_dst = os.path.join(temp_dir, "ffmpeg.exe")
    if os.path.exists(ffmpeg_src):
        shutil.copy(ffmpeg_src, ffmpeg_dst)
        logger.info("Copied FFmpeg to temp folder.")
    else:
        logger.error("ffmpeg.exe not found!")
    return ffmpeg_dst

def ensure_ffmpeg():
    global FFMPEG_PATH
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        logger.info("FFmpeg in PATH.")
        FFMPEG_PATH = "ffmpeg"
    except Exception:
        if FFMPEG_PATH is None:
            FFMPEG_PATH = setup_ffmpeg_embedded()
    return FFMPEG_PATH

######################################################################
# Album Art & Metadata Helpers
######################################################################
def remove_emojis(text):
    emoji_pattern = re.compile("[" 
        u"\U0001F600-\U0001F64F" u"\U0001F300-\U0001F5FF" u"\U0001F680-\U0001F6FF" u"\U0001F1E0-\U0001F1FF" "]+", flags=re.UNICODE)
    return emoji_pattern.sub("", text)

def clean_filename_extras(text):
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\[[^\]]*\]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def revamped_parse_filename(filename):
    name, ext = os.path.splitext(filename)
    name = name.replace("_", " ").strip()
    name = remove_emojis(name)
    name = clean_filename_extras(name)
    if " - " in name:
        artist, title = name.split(" - ", 1)
        artist, title = artist.strip().title(), title.strip().title()
    else:
        artist, title = "Unknown Artist", name.title()
    return {"artist": artist, "title": title, "ext": ext}

def generate_tidy_filename(info):
    new_name = f"{info.get('artist', 'Unknown Artist')} - {info.get('title', 'Unknown Title')}{info.get('ext', '')}"
    return re.sub(r'[\\/*?:"<>|]', "", new_name)

def lookup_cover_art_itunes(artist, title):
    try:
        term = quote(f"{artist} {title}")
        url = f"https://itunes.apple.com/search?term={term}&media=music&limit=1"
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("resultCount", 0) > 0:
                result = data["results"][0]
                art_url = result.get("artworkUrl100")
                if art_url:
                    highres = art_url.replace("100x100bb", "600x600bb")
                    art_data = requests.get(highres, timeout=8).content
                    return {"cover": art_data, "album": result.get("collectionName")}
    except Exception as e:
        logger.warning("iTunes lookup failed: %s", str(e))
    return None

def get_highres_youtube_thumbnail(thumbnail_url):
    if not thumbnail_url:
        return None
    if "hqdefault" in thumbnail_url:
        highres = thumbnail_url.replace("hqdefault", "maxresdefault")
        try:
            r = requests.get(highres, timeout=10)
            if r.status_code == 200 and r.content:
                return r.content
        except Exception as e:
            logger.warning("Highres YT thumb failed: %s", str(e))
    try:
        r = requests.get(thumbnail_url, timeout=10)
        if r.status_code == 200:
            return r.content
    except Exception as e:
        logger.warning("Fallback YT thumb failed: %s", str(e))
    return None

def lookup_cover_art_youtube(artist, title):
    query = f"ytsearch5:{artist} {title} official audio"
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(query, download=False)
        if "entries" in info and info["entries"]:
            fallback = None
            for entry in info["entries"]:
                if "audio" in entry.get("title", "").lower():
                    thumb = entry.get("thumbnail")
                    cover = get_highres_youtube_thumbnail(thumb)
                    if cover:
                        img = Image.open(BytesIO(cover))
                        if abs(img.size[0] - img.size[1]) < 10:
                            return {"cover": cover, "album": None}
                        elif fallback is None:
                            fallback = cover
            if fallback:
                return {"cover": fallback, "album": None}
            first = info["entries"][0]
            thumb = first.get("thumbnail")
            cover = get_highres_youtube_thumbnail(thumb)
            if cover:
                return {"cover": cover, "album": None}
    except Exception as e:
        logger.warning("YouTube lookup failed: %s", str(e))
    return None

def lookup_improved_cover_art(artist, title):
    return lookup_cover_art_itunes(artist, title) or lookup_cover_art_youtube(artist, title)

def update_audio_metadata_ffmpeg(input_file, metadata, output_file):
    cmd = [ensure_ffmpeg(), "-y", "-i", input_file]
    cover_temp = None
    if metadata.get("cover"):
        try:
            img = Image.open(BytesIO(metadata["cover"]))
            rgb = img.convert("RGB")
            buf = BytesIO()
            rgb.save(buf, format="JPEG")
            cover_bytes = buf.getvalue()
            fd, cover_temp = tempfile.mkstemp(suffix=".jpg")
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(cover_bytes)
        except Exception as e:
            logger.warning("Cover conversion failed: %s", str(e))
        cmd.extend(["-i", cover_temp, "-map", "0:a", "-map", "1", "-c", "copy", "-id3v2_version", "3"])
    else:
        cmd.extend(["-c", "copy", "-id3v2_version", "3"])
    if metadata.get("artist"):
        cmd.extend(["-metadata", f"artist={metadata['artist']}"])
    if metadata.get("title"):
        cmd.extend(["-metadata", f"title={metadata['title']}"])
    if metadata.get("album"):
        cmd.extend(["-metadata", f"album={metadata['album']}"])
    cmd.append(output_file)
    logger.info("FFmpeg cmd: " + " ".join(cmd))
    subprocess.run(cmd, check=True)
    if cover_temp and os.path.exists(cover_temp):
        os.remove(cover_temp)

def update_video_metadata_ffmpeg(input_file, info, output_file):
    thumbnail_url = info.get("thumbnail", None)
    cover_temp = None
    cmd = [ensure_ffmpeg(), "-y", "-i", input_file]
    if thumbnail_url:
        cover = get_highres_youtube_thumbnail(thumbnail_url)
        if cover:
            try:
                img = Image.open(BytesIO(cover)).convert("RGB")
                buf = BytesIO()
                img.save(buf, format="JPEG")
                cover_bytes = buf.getvalue()
                fd, cover_temp = tempfile.mkstemp(suffix=".jpg")
                with os.fdopen(fd, "wb") as tmp:
                    tmp.write(cover_bytes)
            except Exception as e:
                logger.warning("Video cover conversion failed: %s", str(e))
            cmd.extend(["-i", cover_temp, "-map", "0", "-map", "1", "-c", "copy", "-disposition:1", "attached_pic"])
        else:
            cmd.extend(["-c", "copy"])
    else:
        cmd.extend(["-c", "copy"])
    cmd.append(output_file)
    logger.info("FFmpeg cmd: " + " ".join(cmd))
    subprocess.run(cmd, check=True)
    if cover_temp and os.path.exists(cover_temp):
        os.remove(cover_temp)

######################################################################
# Precise Leading Silence Removal Function
######################################################################
def remove_silence(input_file):
    detect_cmd = [
        ensure_ffmpeg(), "-i", input_file,
        "-af", "silencedetect=noise=-25dB:d=0.1",
        "-f", "null", "-"
    ]
    proc = subprocess.run(detect_cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
    output = proc.stderr
    silence_end_time = None
    for line in output.splitlines():
        if "silence_end:" in line:
            try:
                parts = line.split("silence_end:")
                value = parts[1].split()[0]
                silence_end_time = float(value)
                break
            except Exception:
                continue
    if silence_end_time is None:
        logger.info("No leading silence detected in %s", input_file)
        return input_file
    new_start = max(silence_end_time - 0.3, 0)
    logger.info("Detected leading silence ends at %.3f seconds; trimming to start at %.3f seconds", silence_end_time, new_start)
    base, ext = os.path.splitext(input_file)
    temp_file = base + "_nosilence" + ext
    trim_cmd = [
        ensure_ffmpeg(), "-y", "-ss", str(new_start),
        "-i", input_file,
        "-c", "copy",
        temp_file
    ]
    subprocess.run(trim_cmd, check=True)
    os.remove(input_file)
    os.rename(temp_file, input_file)
    logger.info("Completed precise leading silence removal for: %s", input_file)
    return input_file

def process_metadata_file_ffmpeg(args):
    filename, thumb_bytes = args
    try:
        info = revamped_parse_filename(os.path.basename(filename))
        lookup = lookup_improved_cover_art(info["artist"], info["title"])
        cover = lookup.get("cover") if lookup else None
        album = lookup.get("album") if lookup else None
        final_cover = cover if cover else thumb_bytes
        new_name = generate_tidy_filename(info)
        final_output = os.path.join(os.path.dirname(filename), new_name)
        metadata = {"artist": info["artist"], "title": info["title"], "album": album, "ext": info["ext"], "cover": final_cover}
        with tempfile.NamedTemporaryFile(suffix=metadata["ext"], dir=os.path.dirname(filename), delete=False) as tmp:
            temp_output = tmp.name
        update_audio_metadata_ffmpeg(filename, metadata, temp_output)
        time.sleep(1)
        os.remove(filename)
        if os.path.exists(final_output):
            os.remove(final_output)
        os.replace(temp_output, final_output)
        return final_output
    except Exception as e:
        logger.error("Metadata update failed for %s: %s", filename, str(e))
        return None

######################################################################
# Worker Threads for Downloading and Metadata Processing
######################################################################
class DownloadWorker(QThread):
    log_update = pyqtSignal(str)
    progress_update = pyqtSignal(int)
    finished_signal = pyqtSignal(str)
    def __init__(self, urls, out_folder, mode, quality, browser, cookies, thread_count, silence_removal):
        super().__init__()
        self.urls = urls  # list of URL strings
        self.out_folder = out_folder
        self.mode = mode
        self.quality = quality
        self.browser = browser
        self.cookies = cookies
        self.thread_count = thread_count
        self.silence_removal = silence_removal
        self.cancel_flag = False
    def run(self):
        try:
            self.log_update.emit("FFmpeg OK.")
            ensure_ffmpeg()
        except Exception as e:
            self.log_update.emit("FFmpeg err: " + str(e))
            self.finished_signal.emit("Error")
            return
        if not self.urls:
            self.log_update.emit("No URLs specified.")
            self.finished_signal.emit("No files.")
            return
        results = []
        for url in self.urls:
            self.log_update.emit(f"Processing URL: {url}")
            try:
                res = self.process_single_url(url)
                if res:
                    results.extend(res)
            except Exception as ex:
                self.log_update.emit(f"Error with {url}: {str(ex)}")
        if results:
            self.finished_signal.emit("\n".join(results))
        else:
            self.finished_signal.emit("No files.")
    def process_single_url(self, url):
        ydl_opts = {
            'logger': logger,
            'quiet': True,
            'progress_hooks': [self._progress_hook]
        }
        if self.mode.lower() == "audio":
            ydl_opts['format'] = "bestaudio"
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '0',
            }]
        else:
            ydl_opts['format'] = "bestvideo+bestaudio/best"
        if self.browser.lower() != "none":
            ydl_opts["cookiesfrombrowser"] = (self.browser.lower(),)
        elif self.cookies and os.path.exists(self.cookies):
            ydl_opts["cookiefile"] = self.cookies
        outtmpl = os.path.join(self.out_folder, "%(title)s.%(ext)s")
        ydl_opts['outtmpl'] = outtmpl
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        results = []
        if "entries" in info and info["entries"]:
            entries = info["entries"]
            self.log_update.emit(f"Playlist found: {len(entries)} items.")
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.thread_count) as executor:
                futures = [executor.submit(self._download_and_process, e, dict(ydl_opts)) for e in entries]
                for f in futures:
                    path = f.result()
                    if path:
                        results.append(os.path.basename(path))
        else:
            path = self._download_and_process(info, ydl_opts)
            if path:
                results.append(os.path.basename(path))
        return results
    def _download_and_process(self, entry_info, base_opts):
        try:
            url = entry_info.get("webpage_url", "")
            title = entry_info.get("title", "Unknown")
            self.log_update.emit(f"Downloading: {title}")
            ydl_opts_local = dict(base_opts)
            ydl_opts_local['outtmpl'] = os.path.join(self.out_folder, "%(title)s.%(ext)s")
            def progress_hook(d):
                if d.get("status") == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                    downloaded = d.get("downloaded_bytes", 0)
                    self.log_update.emit(f"{title}: {int(downloaded*100/total)}%")
            ydl_opts_local['progress_hooks'] = [progress_hook]
            with yt_dlp.YoutubeDL(ydl_opts_local) as ydl:
                ydl.download([url])
            info = ydl.extract_info(url, download=False)
            fname = ydl.prepare_filename(info)
            if self.mode.lower() == "audio":
                fname = os.path.splitext(fname)[0] + ".mp3"
                if self.silence_removal:
                    self.log_update.emit(f"Starting silence removal for {fname}")
                    fname = general_executor.submit(remove_silence, os.path.abspath(fname)).result()
                    self.log_update.emit(f"Silence removal completed for {fname}")
                else:
                    self.log_update.emit(f"Silence removal skipped for {fname}")
            else:
                temp_file = os.path.abspath(fname)
                with tempfile.NamedTemporaryFile(suffix=os.path.splitext(fname)[1], dir=self.out_folder, delete=False) as tmp:
                    out_file = tmp.name
                update_video_metadata_ffmpeg(temp_file, info, out_file)
                os.remove(temp_file)
                fname = out_file
            return os.path.abspath(fname)
        except Exception as e:
            self.log_update.emit(f"Error: {str(e)}")
            return None
    def _progress_hook(self, d):
        if self.cancel_flag:
            raise yt_dlp.utils.DownloadError("Cancelled.")
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
            downloaded = d.get("downloaded_bytes", 0)
            self.progress_update.emit(int(downloaded * 100 / total))
    def cancel(self):
        self.cancel_flag = True
        self.log_update.emit("Cancelling...")

class MetadataProcessor(QThread):
    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal()
    def __init__(self, folder, file_list=None):
        super().__init__()
        self.folder = folder
        self.file_list = file_list
    def run(self):
        try:
            files = self.file_list if self.file_list else [
                os.path.join(self.folder, f)
                for f in os.listdir(self.folder)
                if os.path.splitext(f)[1].lower() in [".mp3", ".m4a", ".flac", ".opus", ".wma"]
            ]
            if not files:
                self.log_update.emit("No files for meta.")
                self.finished_signal.emit()
                return
            tasks = []
            for f in files:
                self.log_update.emit("Meta: " + os.path.basename(f))
                info_clean = revamped_parse_filename(os.path.basename(f))
                lookup = lookup_improved_cover_art(info_clean["artist"], info_clean["title"])
                cover = lookup.get("cover") if lookup else None
                tasks.append((f, cover))
            results = metadata_process_executor.map(process_metadata_file_ffmpeg, tasks)
            for res in results:
                if res:
                    self.log_update.emit("Updated: " + os.path.basename(res))
                else:
                    self.log_update.emit("Meta fail.")
        except Exception as e:
            self.log_update.emit("Meta err: " + str(e))
        self.finished_signal.emit()

######################################################################
# Documentation Dialog (Integrated Documentation)
######################################################################
class DocumentationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Documentation")
        self.resize(700, 500)
        layout = QVBoxLayout(self)
        self.doc_edit = QTextEdit()
        self.doc_edit.setReadOnly(True)
        self.doc_edit.setHtml(self.get_documentation_html())
        layout.addWidget(self.doc_edit)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
    def get_documentation_html(self):
        # Combined README and Wiki documentation in HTML format.
        html = """
        <html>
        <head>
          <style>
            body { font-family: Segoe UI, sans-serif; background-color: #202124; color: #e8eaed; padding: 10px; }
            h1, h2, h3 { color: #e91e63; }
            ul { margin-left: 20px; }
            li { margin-bottom: 4px; }
            pre { background: #303134; padding: 10px; border-radius: 4px; }
            hr { border: 1px solid #444; margin: 20px 0; }
          </style>
        </head>
        <body>
          <h1>Vericu Tuning YouTube Downloader V1.9TDI</h1>
          <h2>Read me!</h2>
          <p><strong>Vericu Tuning YouTube Downloader V1.9TDI</strong> is a comprehensive PyQt5-based tool for downloading YouTube videos and playlists in both audio and video formats, with advanced post-processing options.</p>
          <h3>Features</h3>
          <ul>
            <li>Dark-themed GUI with drag-and-drop support.</li>
            <li>Cookies and FFmpeg integration.</li>
            <li>Audio &amp; Video downloads with dynamic format and quality options.</li>
            <li>Album art lookup from iTunes or YouTube.</li>
            <li>Post-download processing:
              <ul>
                <li>Audio: Optional precise removal of leading silence (preserving 0.3 seconds) and metadata processing.</li>
                <li>Video: Automatic thumbnail embedding.</li>
              </ul>
            </li>
            <li>Multi-URL support via a dedicated pop-up dialog.</li>
            <li>Thread control and persistent settings.</li>
          </ul>
          <h3>Installation</h3>
          <p>
            On first launch, the application auto-installs missing dependencies:
            PyQt5, yt_dlp, requests, and Pillow.
            Ensure that an <code>ffmpeg.exe</code> file is present in the project directory.
          </p>
          <h3>Usage</h3>
          <ol>
            <li>Enter a URL in the URL field or click <strong>Multi-URLs</strong> to paste multiple URLs (one per line).</li>
            <li>Select an output folder using <strong>Browse Folder</strong>.</li>
            <li>Configure options:
              <ul>
                <li>Select browser and cookies (if needed).</li>
                <li>Choose the download type (Audio/Video) and adjust format, quality, and thread count.</li>
                <li>For Audio downloads, toggle <strong>Remove Silence</strong> and/or <strong>Process Metadata</strong>.</li>
              </ul>
            </li>
            <li>Click the <strong>Download</strong> button to start.</li>
            <li>Click <strong>Documentation</strong> anytime to view this help.</li>
          </ol>
          <h3>License &amp; Contact</h3>
          <p>
            This project is provided "as is" with no warranties. Follow on YouTube: @real151kmh, TikTok: @151kmh, and Instagram: @151kmh.
          </p>
          <hr>
          <h2>Wiki Documentation</h2>
          <h3>Overview</h3>
          <p>
            The downloader provides a reliable way to download and process YouTube content with advanced features for both audio and video.
          </p>
          <h3>Features &amp; Settings</h3>
          <ul>
            <li><strong>GUI &amp; Layout:</strong> Dark interface with persistent settings and drag-and-drop support.</li>
            <li><strong>Download Options:</strong> 
              <ul>
                <li>Audio/Video modes with dynamic format and quality controls.</li>
                <li>Multi-URL support for batch downloads.</li>
                <li>Thread control for simultaneous downloads.</li>
              </ul>
            </li>
            <li><strong>Audio Processing:</strong>
              <ul>
                <li><strong>Remove Silence:</strong> Uses FFmpeg silencedetect (0.1s duration, -25dB threshold) and trims the audio so that 0.3 seconds of ambient sound remain.</li>
                <li><strong>Process Metadata:</strong> Automatically updates metadata by parsing filenames and retrieving album art.</li>
              </ul>
            </li>
            <li><strong>Video Processing:</strong> Automatically embeds YouTube thumbnails.</li>
            <li><strong>Documentation:</strong> Accessible directly from the interface.</li>
          </ul>
          <h3>FAQ</h3>
          <p>
            <strong>Q:</strong> What is the purpose of the Remove Silence feature?<br>
            <strong>A:</strong> It removes unwanted leading silence while preserving a short segment of the ambient sound.
          </p>
          <p>
            <strong>Q:</strong> How does metadata processing work?<br>
            <strong>A:</strong> The application extracts artist and title info from the filename, retrieves album art, and updates the file metadata using FFmpeg.
          </p>
          <p>
            <strong>Q:</strong> Can I download multiple videos at once?<br>
            <strong>A:</strong> Yes, use the Multi-URLs dialog to paste several URLs (one per line).
          </p>
          <p>
            <strong>Q:</strong> What should I do if a download fails?<br>
            <strong>A:</strong> Check the log panel for error details and ensure that <code>ffmpeg.exe</code> is correctly set up.
          </p>
          <h3>Troubleshooting</h3>
          <ul>
            <li>Ensure all dependencies are installed and <code>ffmpeg.exe</code> is in the proper directory.</li>
            <li>For metadata issues, follow the recommended filename format: "Artist - Title".</li>
          </ul>
        </body>
        </html>
        """
        return html

######################################################################
# Main GUI Window – Settings, History, Log, and About Button
######################################################################
class DownloaderMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vericu Tuning YouTube Downloader V1.9TDI")
        self.resize(1200, 800)
        self._restore_geometry()
        self.setAcceptDrops(True)
        self._init_ui()
        self._load_settings()
        self.multi_urls = []  # List to store multiple URLs
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10,10,10,10)
        main_layout.setSpacing(10)
        # Row 1: URL, Browser, Type, Cookies
        row1 = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("YouTube URL or Playlist")
        row1.addWidget(QLabel("URL:"))
        row1.addWidget(self.url_input, 3)
        self.browser_choice = QComboBox()
        self.browser_choice.addItems(["firefox", "chrome", "edge", "opera", "brave", "none"])
        row1.addWidget(QLabel("Browser:"))
        row1.addWidget(self.browser_choice, 1)
        self.download_type = QComboBox()
        self.download_type.addItems(["Audio", "Video"])
        self.download_type.currentIndexChanged.connect(self.update_format_quality)
        row1.addWidget(QLabel("Type:"))
        row1.addWidget(self.download_type, 1)
        self.cookies_file = QLineEdit()
        self.cookies_file.setPlaceholderText("Cookies file path")
        self.cookies_browse = QPushButton("Browse Cookies")
        self.cookies_browse.clicked.connect(self.browse_cookies)
        cookie_layout = QHBoxLayout()
        cookie_layout.addWidget(self.cookies_file)
        cookie_layout.addWidget(self.cookies_browse)
        row1.addWidget(QLabel("Cookies:"))
        row1.addLayout(cookie_layout, 2)
        main_layout.addLayout(row1)
        # Row 2: Folder, Format, Quality, Threads, About
        row2 = QHBoxLayout()
        self.folder_label = QLabel("Select Folder")
        self.folder_btn = QPushButton("Browse Folder")
        self.folder_btn.clicked.connect(self.browse_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.folder_label)
        folder_layout.addWidget(self.folder_btn)
        row2.addWidget(QLabel("Folder:"))
        row2.addLayout(folder_layout, 2)
        self.format_choice = QComboBox()
        row2.addWidget(QLabel("Format:"))
        row2.addWidget(self.format_choice, 1)
        self.quality_choice = QComboBox()
        row2.addWidget(QLabel("Quality:"))
        row2.addWidget(self.quality_choice, 1)
        self.thread_slider = QSlider(Qt.Horizontal)
        self.thread_slider.setMinimum(1)
        self.thread_slider.setMaximum(12)
        self.thread_slider.setValue(4)
        self.thread_slider.setTickInterval(1)
        self.thread_slider.setTickPosition(QSlider.TicksBelow)
        self.thread_slider.valueChanged.connect(self.update_thread_count_label)
        self.thread_count_label = QLabel("4")
        thread_layout = QHBoxLayout()
        thread_layout.addWidget(self.thread_slider)
        thread_layout.addWidget(self.thread_count_label)
        row2.addWidget(QLabel("Threads:"))
        row2.addLayout(thread_layout, 1)
        self.about_btn = QPushButton("About")
        self.about_btn.clicked.connect(self.show_about)
        row2.addWidget(self.about_btn)
        main_layout.addLayout(row2)
        # Row 3: Combined controls – Remove Silence, Process Metadata, Multi-URLs, Download, Documentation
        row3 = QHBoxLayout()
        self.silence_removal_checkbox = QCheckBox("Remove Silence")
        self.silence_removal_checkbox.setChecked(True)
        self.metadata_checkbox = QCheckBox("Process Metadata")
        self.metadata_checkbox.setChecked(False)
        self.multi_urls_btn = QPushButton("Multi-URLs")
        self.multi_urls_btn.clicked.connect(self.open_multi_url_dialog)
        self.download_btn = QPushButton("Download")
        self.download_btn.setFixedWidth(200)  # Bigger download button
        self.download_btn.clicked.connect(self.start_download)
        self.doc_btn = QPushButton("Documentation")
        self.doc_btn.clicked.connect(self.open_documentation_dialog)
        row3.addWidget(self.silence_removal_checkbox)
        row3.addWidget(self.metadata_checkbox)
        row3.addWidget(self.multi_urls_btn)
        row3.addWidget(self.download_btn)
        row3.addWidget(self.doc_btn)
        main_layout.addLayout(row3)
        # Splitter for History and Log
        splitter = QSplitter(Qt.Horizontal)
        history_widget = QWidget()
        h_layout = QVBoxLayout(history_widget)
        h_layout.addWidget(QLabel("Download History"))
        self.history_list = QListWidget()
        h_layout.addWidget(self.history_list)
        splitter.addWidget(history_widget)
        log_widget = QWidget()
        l_layout = QVBoxLayout(log_widget)
        l_layout.addWidget(QLabel("Log"))
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        l_layout.addWidget(self.log_edit)
        splitter.addWidget(log_widget)
        splitter.setStretchFactor(1,2)
        main_layout.addWidget(splitter, stretch=1)
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(25)
        main_layout.addWidget(self.progress_bar)
        self.setStyleSheet("""
            QWidget { background-color: #202124; color: #e8eaed; font-family: Segoe UI, sans-serif; }
            QLabel { font-weight: 500; }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #303134; border: 1px solid #5f6368; border-radius: 4px; padding: 4px;
            }
            QPushButton {
                background-color: #3c4043; border: none; border-radius: 6px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #5f6368; }
            QListWidget {
                background-color: #2b2c2e; border: 1px solid #444; border-radius: 4px;
            }
            QProgressBar {
                background-color: #616161; border-radius: 4px; text-align: center;
            }
            QProgressBar::chunk { background-color: #e91e63; border-radius: 4px; }
            QSplitter::handle { background-color: #3c4043; }
            QSlider::groove:horizontal {
                background: #303134; height: 8px; border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #e91e63; border: none; width: 16px; margin: -4px 0; border-radius: 8px;
            }
        """)
    def open_documentation_dialog(self):
        dlg = DocumentationDialog(self)
        dlg.exec_()
    def open_multi_url_dialog(self):
        dlg = MultiUrlDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            new_urls = dlg.get_urls()
            if new_urls:
                self.multi_urls = new_urls
                self.log(f"Added {len(new_urls)} URL(s) via multi-URL dialog.")
    def update_format_quality(self):
        if self.download_type.currentText().lower() == "audio":
            self.format_choice.clear()
            self.format_choice.addItems(["mp3", "wav", "aac"])
            self.quality_choice.clear()
            self.quality_choice.addItems(["256kbps", "192kbps", "128kbps"])
            self.silence_removal_checkbox.setVisible(True)
            self.metadata_checkbox.setVisible(True)
        else:
            self.format_choice.clear()
            self.format_choice.addItems(["mp4", "webm", "mkv"])
            self.quality_choice.clear()
            self.quality_choice.addItems(["2160p", "1440p", "1080p", "720p", "480p"])
            self.silence_removal_checkbox.setVisible(False)
            self.metadata_checkbox.setVisible(False)
    def update_thread_count_label(self, value):
        self.thread_count_label.setText(str(value))
    def dragEnterEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            self.url_input.setText(url.toLocalFile())
        event.acceptProposedAction()
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.folder_label.setText(folder)
            settings.setValue("output_path", folder)
    def browse_cookies(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Cookies File")
        if path:
            self.cookies_file.setText(path)
    def start_download(self):
        folder = self.folder_label.text().strip()
        if not folder or folder == "Select Folder":
            self.log("Choose an output folder before downloading.")
            return
        if self.multi_urls:
            urls = self.multi_urls
        else:
            single_url = self.url_input.text().strip()
            if not single_url:
                self.log("Enter a URL or use Multi-URLs.")
                return
            urls = [single_url]
        browser = self.browser_choice.currentText()
        d_type = self.download_type.currentText()
        fmt = self.format_choice.currentText()
        quality = self.quality_choice.currentText()
        cookies = self.cookies_file.text().strip()
        thread_count = self.thread_slider.value()
        silence_removal = self.silence_removal_checkbox.isChecked()
        self.log(f"Starting download: {len(urls)} URL(s)  T:{thread_count}  SilenceRemoval:{silence_removal}")
        self.download_worker = DownloadWorker(
            urls, folder, d_type, quality, browser, cookies, thread_count, silence_removal
        )
        self.download_worker.log_update.connect(self.log)
        self.download_worker.progress_update.connect(self.progress_bar.setValue)
        self.download_worker.finished_signal.connect(self.download_finished)
        self.download_worker.start()
    def download_finished(self, message):
        if message not in ["Error", "No files."]:
            for f in message.splitlines():
                if not self.history_list.findItems(f, Qt.MatchExactly):
                    self.history_list.addItem(f)
        self.log("Download finished: " + message)
        self.progress_bar.setValue(0)
        if (
            self.download_type.currentText().lower() == "audio"
            and self.metadata_checkbox.isChecked()
            and message not in ["Error", "No files."]
        ):
            folder = self.folder_label.text().strip()
            self.log("Processing metadata in folder: " + folder)
            self.meta_worker = MetadataProcessor(folder)
            self.meta_worker.log_update.connect(self.log)
            self.meta_worker.finished_signal.connect(lambda: self.log("Metadata processing done."))
            self.meta_worker.start()
    def show_about(self):
        about_text = (
            "Vericu Tuning YouTube Downloader V1.0.50\n"
            "Copyright ©️2025 - Made by 151kmh only using ChatGPT 4o - No rights reserved\n\n"
            "YouTube: @real151kmh\n"
            "TikTok: @151kmh\n"
            "Instagram: @151kmh"
        )
        QMessageBox.about(self, "About", about_text)
    def log(self, message):
        self.log_edit.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
    def _load_settings(self):
        self.url_input.setText(settings.value("last_url", ""))
        self.folder_label.setText(settings.value("output_path", "Select Folder"))
        self.cookies_file.setText(settings.value("cookies_file", ""))
        self.browser_choice.setCurrentText(settings.value("browser", "firefox"))
    def _restore_geometry(self):
        geom = settings.value("main_geometry")
        if geom:
            self.restoreGeometry(geom)
    def closeEvent(self, event):
        settings.setValue("last_url", self.url_input.text())
        settings.setValue("browser", self.browser_choice.currentText())
        settings.setValue("cookies_file", self.cookies_file.text())
        settings.setValue("main_geometry", self.saveGeometry())
        ffmpeg_temp_dir = os.path.dirname(ensure_ffmpeg())
        shutil.rmtree(ffmpeg_temp_dir, ignore_errors=True)
        event.accept()

######################################################################
# Main Entry Point
######################################################################
def main():
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    window = DownloaderMainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
