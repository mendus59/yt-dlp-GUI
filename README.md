# YT Downloader (yt-dlp GUI)

<!-- site-summary:start -->
<!-- This section is this project's card on https://mendus59.github.io and is copied there daily.
     Keep it true of what's on main: one plain-text summary line (max 160 characters), then 1-6 short bullets.
     See CLAUDE.md ("Site summary"). -->
A free Windows desktop app that puts a simple window on top of yt-dlp, with a web app that opens it with your settings filled in.

- Paste video, playlist or channel URLs and download video, with a maximum and minimum quality, or audio only as mp3, m4a, opus, wav or flac.
- Live progress, skip the current video or cancel all, and keep going when one video fails.
- Optional English subtitles and video IDs in file names; a Get ffmpeg button sets up 1080p+ merging and audio conversion.
- One Windows 10/11 exe with Python, yt-dlp and deno bundled, so there is nothing to install.
- The web app builds your settings and opens the desktop app with them through a ytdlp-gui:// link.
<!-- site-summary:end -->

A free Windows desktop app that puts a simple window on top of
[yt-dlp](https://github.com/yt-dlp/yt-dlp), plus a GitHub Pages web app that
opens the desktop app with your settings filled in.

- **Web app:** https://mendus59.github.io/yt-dlp-GUI/
- **Download:** [YT-Downloader.exe](https://github.com/mendus59/yt-dlp-GUI/releases/latest/download/YT-Downloader.exe) (Windows 10/11, ~60 MB, no install)

## Features

- Paste one or more video, playlist or channel URLs
- Video with max and min quality (min skips videos that don't reach it), or audio only (mp3, m4a, opus, wav, flac)
- Whole playlists and channels, optional English subtitles, optional video ID in file names
- Live progress, **Skip current video**, **Cancel all**, and keep going when one video fails
- Bundles Python, yt-dlp and deno (the JavaScript runtime YouTube now requires)
- **Get ffmpeg** button installs ffmpeg once, for 1080p+ merging and audio conversion
- `ytdlp-gui://` links: the web app's **Open in YT Downloader** button launches the app pre-filled

## Repo layout

| Path | What it is |
| --- | --- |
| `app/ytdlp_gui.py` | The desktop app (Tkinter + yt-dlp as a library) |
| `app/build.ps1` | Builds the single-file exe with PyInstaller |
| `docs/` | GitHub Pages site: the web app (`index.html`) and the embeddable card (`embed/`) |
| `.github/workflows/release.yml` | Builds the exe on GitHub Actions and attaches it to a Release on each `v*` tag |
| `.github/workflows/pages.yml` | Deploys `docs/` to GitHub Pages on each push to `main` |
| `SUMMARY.md` | Project write-up and instructions for embedding on a personal website |

## Run or build locally

```powershell
python -m pip install "yt-dlp[default,deno]"
python app\ytdlp_gui.py
```

```powershell
powershell -ExecutionPolicy Bypass -File .\app\build.ps1                               # yt-dlp from PyPI
powershell -ExecutionPolicy Bypass -File .\app\build.ps1 -YtDlpSource ..\yt-dlp-master # or a local checkout
```

The exe lands in `dist\`. The build environment lives in `%LOCALAPPDATA%\ytdlp-gui-build`.

## Releasing

```powershell
git tag v1.0.1
git push origin v1.0.1
```

GitHub Actions builds `YT-Downloader.exe` on a Windows runner and publishes it as a
Release. The web app's download button always points at the latest release.

## Why the web app doesn't download videos itself

GitHub Pages serves static files only, and browsers block pages from fetching
video from other sites. A public server that downloads on visitors' behalf
would cost money, get blocked by YouTube, and invite abuse. So the web app
builds settings and hands them to the desktop app, and downloads happen on
your own PC.

## Responsible use

Only download content you have the right to. YouTube's Terms of Service
restrict downloading outside its own features. This project is not affiliated
with YouTube or the yt-dlp project. yt-dlp is released under the Unlicense.
