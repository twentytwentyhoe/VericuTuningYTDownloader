# VericuTuningYTDownloader
**Vericu Tuning YouTube Downloader V1.9TDI** is a comprehensive PyQt5-based tool for downloading YouTube videos and playlists in both audio and video formats, with advanced post-processing options.

## Features

- **Dark-Themed GUI:** Modern interface with drag-and-drop support.
- **Cookies & FFmpeg Integration:** Automatic dependency detection and setup.
- **Audio & Video Downloads:** Dynamic format and quality selections.
- **Album Art Lookup:** Automatically retrieves album art from iTunes or YouTube.
- **Post-Download Processing:**
  - **Audio:** Optional precise removal of leading silence (keeps 0.3 seconds of ambient sound) and metadata processing.
  - **Video:** Automatic thumbnail embedding.
- **Multi-URL Support:** Paste multiple URLs using the dedicated dialog.
- **Thread Control:** Configure concurrent downloads.
- **Persistent Settings & History**

## Installation

On first launch, the application auto-installs missing dependencies:
- PyQt5
- yt_dlp
- requests
- Pillow

Ensure that an `ffmpeg.exe` is in the project directory or available in your PATH.

## Usage

1. **Enter a URL or use the Multi-URLs:**  
   - Enter a single URL or click **Multi-URLs** to paste multiple URLs (one per line).

2. **Set the Output Folder:**  
   Use the **Browse Folder** button to select where files are saved.

3. **Configure Options:**  
   - Select **Browser**, **Type** (Audio/Video), and set cookies if required.
   - Adjust **Format**, **Quality**, and thread count.
   - For Audio: Check **Remove Silence** and/or **Process Metadata** as needed.

4. **Download:**  
   Click the enlarged **Download** button to start downloading and processing.

5. **View Documentation:**  
   Click the **Documentation** button for detailed instructions and feature explanations.

## License & Contact

Provided "as is" with no warranties.  
Follow on:  
- YouTube: @real151kmh  
- TikTok: @151kmh  
- Instagram: @151kmh
