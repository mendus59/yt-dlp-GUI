"""YT Downloader: a small Windows desktop GUI on top of the yt-dlp library.

This is a separate add-on. It imports yt_dlp as a normal library and does not
modify any yt-dlp source files.

Run from source:   python ytdlp_gui.py
Build the exe:     see build.ps1 / README.md
"""

from __future__ import annotations

import os
import queue
import shutil
import ssl
import subprocess
import sys
import threading
import traceback
import urllib.request
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# A windowed PyInstaller exe has no console, so stdout/stderr are None.
# Give them a harmless target so nothing crashes when something prints.
for _name in ('stdout', 'stderr'):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, 'w', encoding='utf-8'))

import yt_dlp  # noqa: E402

APP_NAME = 'YT Downloader'
APP_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'YTDownloaderGUI'
TOOLS_DIR = APP_DIR / 'tools'
FFMPEG_ZIP_URL = ('https://github.com/yt-dlp/FFmpeg-Builds/releases/download/'
                  'latest/ffmpeg-master-latest-win64-gpl.zip')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

MIN_QUALITIES = {
    'No minimum': None,
    '1080p': 1080,
    '720p': 720,
    '480p': 480,
    '360p': 360,
}

QUALITIES = {
    'Best available': None,
    '2160p (4K)': 2160,
    '1440p': 1440,
    '1080p': 1080,
    '720p': 720,
    '480p': 480,
    '360p': 360,
}


class Cancelled(yt_dlp.utils.DownloadCancelled):
    """Stops the whole queue; yt-dlp re-raises this even with ignoreerrors on."""
    msg = 'Cancelled by user'


SKIP_MSG = 'Skipped by user'


class SkipCurrent(Exception):
    """Abandons only the current video; yt-dlp reports it and moves on."""

    def __init__(self):
        super().__init__(SKIP_MSG)


# ---------------------------------------------------------------- helpers

def bundled_path(*parts: str) -> Path | None:
    """Path to a file bundled inside the PyInstaller exe, if any."""
    base = getattr(sys, '_MEIPASS', None)
    if not base:
        return None
    p = Path(base, *parts)
    return p if p.exists() else None


def find_ffmpeg() -> Path | None:
    """Folder containing ffmpeg.exe and ffprobe.exe, or None."""
    candidates = [TOOLS_DIR]
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).parent)
    for d in candidates:
        if (d / 'ffmpeg.exe').exists() and (d / 'ffprobe.exe').exists():
            return d
    on_path = shutil.which('ffmpeg')
    if on_path and shutil.which('ffprobe'):
        return Path(on_path).parent
    return None


def find_deno() -> str | None:
    """deno is the JavaScript runtime yt-dlp needs for YouTube."""
    bundled = bundled_path('deno', 'deno.exe')
    if bundled:
        return str(bundled)
    import sysconfig
    for local in (TOOLS_DIR / 'deno.exe', Path(sysconfig.get_path('scripts'), 'deno.exe')):
        if local.exists():
            return str(local)
    return shutil.which('deno')


def ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def human_size(n: float | None) -> str:
    if not n:
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'


def default_download_dir() -> str:
    d = Path.home() / 'Downloads'
    return str(d if d.exists() else Path.home())


# ---------------------------------------------------------------- the app

class YtdlpLogger:
    """Routes yt-dlp's messages into the GUI log.

    yt-dlp logs constantly while it works (fetching pages, solving YouTube's
    JavaScript, retrying, merging), not only while bytes are downloading. So
    the logger is also where Cancel / Skip get noticed between downloads.
    """

    def __init__(self, app: App):
        self.app = app
        self.post = app.post
        self.errors: list[str] = []
        self.user_skipped = 0

    def debug(self, msg):
        # yt-dlp sends normal info lines through debug() with a '[...]' prefix
        if not msg.startswith('[debug] '):
            self.post('log', msg)
        self.app.check_stop()

    def info(self, msg):
        self.post('log', msg)
        self.app.check_stop()

    def warning(self, msg):
        self.post('log', f'WARNING: {msg}')
        self.app.check_stop()

    def error(self, msg):
        # Never raise from here: yt-dlp is in the middle of reporting a failure.
        if SKIP_MSG in msg:
            self.user_skipped += 1
            self.post('log', '>>> Skipped current video')
            return
        self.errors.append(msg.replace('ERROR: ', '', 1))
        self.post('log', msg)
        if not self.app.skip_errors_var.get():
            self.app.error_stop.set()  # stop at the next checkpoint


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_flag = threading.Event()   # stop the whole run
        self.skip_flag = threading.Event()     # abandon only the current video
        self.error_stop = threading.Event()    # a video failed and skipping is off
        self._downloading = False

        root.title(APP_NAME)
        root.minsize(640, 480)
        icon = bundled_path('app.ico')
        if icon:
            try:
                root.iconbitmap(str(icon))
            except tk.TclError:
                pass

        self.url_var = tk.StringVar()
        self.dir_var = tk.StringVar(value=default_download_dir())
        self.mode_var = tk.StringVar(value='video')
        self.quality_var = tk.StringVar(value='1080p')
        self.min_quality_var = tk.StringVar(value='No minimum')
        self.skip_errors_var = tk.BooleanVar(value=True)
        self.audio_fmt_var = tk.StringVar(value='mp3')
        self.playlist_var = tk.BooleanVar(value=False)
        self.subs_var = tk.BooleanVar(value=False)
        self.id_names_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value='Ready.')
        self.ffmpeg_var = tk.StringVar()

        self._build_ui()
        self.refresh_ffmpeg_status()
        self.root.after(100, self._drain_events)

    # ---- layout
    def _build_ui(self):
        pad = {'padx': 8, 'pady': 4}
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill='both', expand=True)
        main.columnconfigure(1, weight=1)

        ttk.Label(main, text='Video URL(s):').grid(row=0, column=0, sticky='w', **pad)
        url_entry = ttk.Entry(main, textvariable=self.url_var)
        url_entry.grid(row=0, column=1, sticky='ew', **pad)
        url_entry.focus_set()
        url_entry.bind('<Return>', lambda e: self.start_download())
        ttk.Button(main, text='Paste', command=self.paste_url).grid(row=0, column=2, **pad)

        ttk.Label(main, text='Save to:').grid(row=1, column=0, sticky='w', **pad)
        ttk.Entry(main, textvariable=self.dir_var).grid(row=1, column=1, sticky='ew', **pad)
        ttk.Button(main, text='Browse…', command=self.pick_dir).grid(row=1, column=2, **pad)

        opts = ttk.LabelFrame(main, text='Options', padding=8)
        opts.grid(row=2, column=0, columnspan=3, sticky='ew', **pad)

        ttk.Radiobutton(opts, text='Video', value='video', variable=self.mode_var,
                        command=self._sync_mode).grid(row=0, column=0, sticky='w')
        ttk.Label(opts, text='Max quality:').grid(row=0, column=1, sticky='e', padx=(16, 4))
        self.quality_box = ttk.Combobox(opts, textvariable=self.quality_var, state='readonly',
                                        values=list(QUALITIES), width=16)
        self.quality_box.grid(row=0, column=2, sticky='w')
        ttk.Label(opts, text='Min quality:').grid(row=0, column=4, sticky='e', padx=(16, 4))
        self.min_box = ttk.Combobox(opts, textvariable=self.min_quality_var, state='readonly',
                                    values=list(MIN_QUALITIES), width=12)
        self.min_box.grid(row=0, column=5, sticky='w')

        ttk.Radiobutton(opts, text='Audio only', value='audio', variable=self.mode_var,
                        command=self._sync_mode).grid(row=1, column=0, sticky='w', pady=(4, 0))
        ttk.Label(opts, text='Format:').grid(row=1, column=1, sticky='e', padx=(16, 4), pady=(4, 0))
        self.audio_box = ttk.Combobox(opts, textvariable=self.audio_fmt_var, state='readonly',
                                      values=['mp3', 'm4a', 'opus', 'wav', 'flac'], width=16)
        self.audio_box.grid(row=1, column=2, sticky='w', pady=(4, 0))

        ttk.Checkbutton(opts, text='Download whole playlist', variable=self.playlist_var
                        ).grid(row=0, column=3, sticky='w', padx=(24, 0))
        ttk.Checkbutton(opts, text='English subtitles', variable=self.subs_var
                        ).grid(row=1, column=3, sticky='w', padx=(24, 0), pady=(4, 0))
        ttk.Checkbutton(opts, text='Skip videos that fail and keep going',
                        variable=self.skip_errors_var
                        ).grid(row=2, column=0, columnspan=3, sticky='w', pady=(6, 0))
        ttk.Checkbutton(opts, text='Add video ID to file names (no clashes when titles repeat)',
                        variable=self.id_names_var
                        ).grid(row=2, column=3, columnspan=3, sticky='w', padx=(24, 0), pady=(6, 0))
        ttk.Label(opts, text='Tip: paste several URLs separated by spaces to queue them.',
                  foreground='gray').grid(row=3, column=0, columnspan=6, sticky='w', pady=(2, 0))

        ff = ttk.Frame(main)
        ff.grid(row=3, column=0, columnspan=3, sticky='ew', **pad)
        ff.columnconfigure(0, weight=1)
        ttk.Label(ff, textvariable=self.ffmpeg_var).grid(row=0, column=0, sticky='w')
        self.ffmpeg_btn = ttk.Button(ff, text='Get ffmpeg', command=self.get_ffmpeg)
        self.ffmpeg_btn.grid(row=0, column=1)

        btns = ttk.Frame(main)
        btns.grid(row=4, column=0, columnspan=3, sticky='ew', **pad)
        self.dl_btn = ttk.Button(btns, text='Download', command=self.start_download)
        self.dl_btn.pack(side='left')
        self.skip_btn = ttk.Button(btns, text='Skip current video', command=self.skip_current,
                                   state='disabled')
        self.skip_btn.pack(side='left', padx=(8, 0))
        self.cancel_btn = ttk.Button(btns, text='Cancel all', command=self.cancel, state='disabled')
        self.cancel_btn.pack(side='left', padx=8)
        ttk.Button(btns, text='Open folder', command=self.open_folder).pack(side='right')

        self.progress = ttk.Progressbar(main, mode='determinate', maximum=100)
        self.progress.grid(row=5, column=0, columnspan=3, sticky='ew', **pad)
        ttk.Label(main, textvariable=self.status_var).grid(row=6, column=0, columnspan=3,
                                                           sticky='w', **pad)

        logf = ttk.Frame(main)
        logf.grid(row=7, column=0, columnspan=3, sticky='nsew', **pad)
        main.rowconfigure(7, weight=1)
        self.log = tk.Text(logf, height=12, wrap='word', state='disabled',
                           font=('Consolas', 9))
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        self._sync_mode()

    def _sync_mode(self):
        video = self.mode_var.get() == 'video'
        self.quality_box.configure(state='readonly' if video else 'disabled')
        self.min_box.configure(state='readonly' if video else 'disabled')
        self.audio_box.configure(state='disabled' if video else 'readonly')

    # ---- small actions
    def paste_url(self):
        try:
            self.url_var.set(self.root.clipboard_get().strip())
        except tk.TclError:
            pass

    def pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or None)
        if d:
            self.dir_var.set(d)

    def open_folder(self):
        d = self.dir_var.get()
        if os.path.isdir(d):
            os.startfile(d)

    def refresh_ffmpeg_status(self):
        loc = find_ffmpeg()
        if loc:
            self.ffmpeg_var.set(f'ffmpeg: found ({loc})')
            self.ffmpeg_btn.configure(text='Update ffmpeg')
        else:
            self.ffmpeg_var.set('ffmpeg: not found. Without it, video is limited to formats that '
                                'already include audio (360p on YouTube) and audio stays in its original format.')
            self.ffmpeg_btn.configure(text='Get ffmpeg')

    def write_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text.rstrip() + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def set_busy(self, busy: bool):
        self.dl_btn.configure(state='disabled' if busy else 'normal')
        self.ffmpeg_btn.configure(state='disabled' if busy else 'normal')
        self.cancel_btn.configure(state='normal' if busy else 'disabled')
        self.skip_btn.configure(state='normal' if busy and self._downloading else 'disabled')

    def post(self, kind, *payload):
        """Thread-safe: queue an update for the GUI thread."""
        self.events.put((kind, payload))

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'log':
                    self.write_log(payload[0])
                elif kind == 'status':
                    self.status_var.set(payload[0])
                elif kind == 'progress':
                    pct = payload[0]
                    if pct is None:
                        self.progress.configure(mode='indeterminate')
                        self.progress.start(15)
                    else:
                        self.progress.stop()
                        self.progress.configure(mode='determinate', value=pct)
                elif kind == 'done':
                    ok, msg = payload
                    self.progress.stop()
                    self.progress.configure(mode='determinate', value=100 if ok else 0)
                    self.status_var.set(msg)
                    self.set_busy(False)
                    self.refresh_ffmpeg_status()
                    if not ok and msg.startswith('Error'):
                        messagebox.showerror(APP_NAME, msg)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def cancel(self):
        self.cancel_flag.set()
        self.status_var.set('Cancelling the whole run…')
        self.write_log('>>> Cancel all requested')

    def skip_current(self):
        self.skip_flag.set()
        self.status_var.set('Skipping the current video…')
        self.write_log('>>> Skip current video requested')

    def check_stop(self):
        """Called from yt-dlp's worker thread at every log line and hook."""
        if self.cancel_flag.is_set() or self.error_stop.is_set():
            raise Cancelled()
        if self.skip_flag.is_set():
            self.skip_flag.clear()
            raise SkipCurrent()

    # ---- downloading
    def build_options(self, ffmpeg_dir: Path | None) -> dict:
        outdir = self.dir_var.get().strip() or default_download_dir()
        playlist = self.playlist_var.get()
        name = '%(title)s [%(id)s]' if self.id_names_var.get() else '%(title)s'
        template = (f'%(playlist_title)s/%(playlist_index)03d - {name}.%(ext)s' if playlist
                    else f'{name}.%(ext)s')

        opts = {
            'paths': {'home': outdir},
            'outtmpl': template,
            'noplaylist': not playlist,
            'logger': YtdlpLogger(self),
            'progress_hooks': [self._progress_hook],
            'postprocessor_hooks': [self._pp_hook],
            'noprogress': True,
            'no_color': True,
            'windowsfilenames': True,
            # Always let yt-dlp report a failed video and move on; when the
            # "skip failures" box is off, the logger stops the run instead.
            # (This is also what lets "Skip current video" work.)
            'ignoreerrors': True,
            'retries': 5,
            'fragment_retries': 5,
        }
        if ffmpeg_dir:
            opts['ffmpeg_location'] = str(ffmpeg_dir)
        deno = find_deno()
        if deno:
            opts['js_runtimes'] = {'deno': {'path': deno}}

        if self.subs_var.get():
            opts.update({
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': ['en.*', 'en'],
            })
            if ffmpeg_dir:
                opts.setdefault('postprocessors', []).append(
                    {'key': 'FFmpegSubtitlesConvertor', 'format': 'srt'})

        if self.mode_var.get() == 'audio':
            codec = self.audio_fmt_var.get()
            if ffmpeg_dir:
                opts['format'] = 'bestaudio/best'
                opts.setdefault('postprocessors', []).insert(0, {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': codec,
                    'preferredquality': '0' if codec == 'mp3' else '5',
                })
            else:
                # No conversion possible; grab the best audio as-is, preferring m4a.
                opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
        else:
            height = QUALITIES.get(self.quality_var.get())
            min_h = MIN_QUALITIES.get(self.min_quality_var.get())
            sort = ['vcodec:h264', 'ext:mp4:m4a']
            if height:
                sort.insert(0, f'res:{height}')
            opts['format_sort'] = sort
            # A video with nothing at or above the minimum fails with
            # "Requested format is not available" (and is skipped if enabled).
            f = f'[height>={min_h}]' if min_h else ''
            if ffmpeg_dir:
                opts['format'] = f'bestvideo*{f}+bestaudio/best{f}'
                opts['merge_output_format'] = 'mp4'
            else:
                opts['format'] = f'best{f}'  # single file with both video and audio
        return opts

    def _progress_hook(self, d):
        self.check_stop()
        status = d.get('status')
        if status == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            done = d.get('downloaded_bytes') or 0
            speed = d.get('speed')
            eta = d.get('eta')
            name = os.path.basename(d.get('filename') or '')
            if total:
                self.post('progress', done * 100 / total)
            else:
                self.post('progress', None)
            parts = [f'{human_size(done)} / {human_size(total)}']
            if speed:
                parts.append(f'{human_size(speed)}/s')
            if eta is not None:
                parts.append(f'ETA {int(eta)}s')
            self.post('status', f'Downloading {name}  ' + '  '.join(parts))
        elif status == 'finished':
            self.post('progress', 100)
            self.post('status', 'Download finished, processing…')

    def _pp_hook(self, d):
        self.check_stop()
        if d.get('status') == 'started':
            self.post('progress', None)
            self.post('status', f'Processing ({d.get("postprocessor")})…')

    def start_download(self):
        if self.worker and self.worker.is_alive():
            return
        urls = self.url_var.get().split()
        if not urls:
            messagebox.showinfo(APP_NAME, 'Paste a video or playlist URL first.')
            return
        max_h = QUALITIES.get(self.quality_var.get())
        min_h = MIN_QUALITIES.get(self.min_quality_var.get())
        if self.mode_var.get() == 'video' and max_h and min_h and min_h > max_h:
            messagebox.showinfo(APP_NAME, 'Min quality is higher than max quality.')
            return
        outdir = self.dir_var.get().strip()
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as e:
            messagebox.showerror(APP_NAME, f'Cannot use that folder:\n{e}')
            return

        ffmpeg_dir = find_ffmpeg()
        if not ffmpeg_dir and self.mode_var.get() == 'video' and min_h and min_h > 360:
            # YouTube's only file with both video and audio is usually 360p;
            # anything better is separate streams that ffmpeg has to merge.
            if messagebox.askyesno(
                    APP_NAME, f'ffmpeg is not installed, so YouTube videos are limited to 360p '
                    f'and your {min_h}p minimum would make every video fail with '
                    '"Requested format is not available".\n\nGet ffmpeg now?'):
                self.get_ffmpeg()
            return
        if not ffmpeg_dir and self.mode_var.get() == 'audio' and self.audio_fmt_var.get() != 'm4a':
            if not messagebox.askyesno(
                    APP_NAME, 'Converting audio needs ffmpeg, which is not installed.\n\n'
                    'Continue and save the audio in its original format?\n'
                    '(Or click "Get ffmpeg" first.)'):
                return

        opts = self.build_options(ffmpeg_dir)
        for flag in (self.cancel_flag, self.skip_flag, self.error_stop):
            flag.clear()
        self._downloading = True
        self.set_busy(True)
        self.progress.configure(value=0)
        self.write_log('--- ' + '  '.join(urls))
        self.status_var.set('Starting…')
        self.worker = threading.Thread(target=self._run_download, args=(urls, opts), daemon=True)
        self.worker.start()

    def _run_download(self, urls, opts):
        logger = opts['logger']
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download(urls)
        except Cancelled:
            pass
        except Exception as e:  # keep the GUI alive no matter what
            self.post('log', traceback.format_exc())
            logger.errors.append(str(e))
        self._finish_run(logger, opts['paths']['home'])

    def _finish_run(self, logger, outdir):
        if logger.errors:
            self.post('log', f'--- {len(logger.errors)} video(s) failed:')
            for e in logger.errors:
                e = e.replace('Requested format is not available. Use --list-formats for a '
                              'list of available formats',
                              'no format matches your settings (below the min quality, '
                              'or ffmpeg is needed: click "Get ffmpeg")')
                self.post('log', '  * ' + e)
        notes = []
        if logger.errors:
            notes.append(f'{len(logger.errors)} failed')
        if logger.user_skipped:
            notes.append(f'{logger.user_skipped} skipped by you')
        extra = f' ({", ".join(notes)}; see the log)' if notes else ''

        if self.error_stop.is_set():
            self.post('done', False, 'Error: stopped after a video failed' + extra + '.')
        elif self.cancel_flag.is_set():
            self.post('done', False, 'Cancelled' + extra + '.')
        elif logger.errors:
            self.post('done', False, 'Finished' + extra + '.')
        else:
            self.post('done', True, f'Done{extra}! Saved to {outdir}')

    # ---- ffmpeg setup
    def get_ffmpeg(self):
        if self.worker and self.worker.is_alive():
            return
        if not messagebox.askyesno(
                APP_NAME, 'Download ffmpeg (about 140 MB) from the yt-dlp FFmpeg-Builds '
                f'project on GitHub?\n\nIt will be saved to:\n{TOOLS_DIR}'):
            return
        self.cancel_flag.clear()
        self._downloading = False
        self.set_busy(True)
        self.write_log(f'--- Downloading ffmpeg from {FFMPEG_ZIP_URL}')
        self.worker = threading.Thread(target=self._run_get_ffmpeg, daemon=True)
        self.worker.start()

    def _run_get_ffmpeg(self):
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = TOOLS_DIR / 'ffmpeg-download.zip'
        try:
            req = urllib.request.Request(FFMPEG_ZIP_URL, headers={'User-Agent': 'ytdlp-gui'})
            with urllib.request.urlopen(req, context=ssl_context(), timeout=60) as resp, \
                    open(zip_path, 'wb') as out:
                total = int(resp.headers.get('Content-Length') or 0)
                done = 0
                while chunk := resp.read(1 << 16):
                    if self.cancel_flag.is_set():
                        raise Cancelled()
                    out.write(chunk)
                    done += len(chunk)
                    self.post('progress', done * 100 / total if total else None)
                    self.post('status', f'Downloading ffmpeg  {human_size(done)} / {human_size(total)}')
            self.post('status', 'Extracting ffmpeg…')
            self.post('progress', None)
            with zipfile.ZipFile(zip_path) as zf:
                for member in zf.namelist():
                    base = member.rsplit('/', 1)[-1]
                    if base in ('ffmpeg.exe', 'ffprobe.exe'):
                        with zf.open(member) as src, open(TOOLS_DIR / base, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
            if not (TOOLS_DIR / 'ffmpeg.exe').exists():
                raise RuntimeError('ffmpeg.exe was not found in the downloaded archive')
            ver = subprocess.run([str(TOOLS_DIR / 'ffmpeg.exe'), '-version'], capture_output=True,
                                 text=True, creationflags=NO_WINDOW).stdout.splitlines()
            self.post('log', ver[0] if ver else 'ffmpeg installed')
            self.post('done', True, 'ffmpeg is ready.')
        except Cancelled:
            self.post('done', False, 'Cancelled.')
        except Exception as e:
            self.post('log', traceback.format_exc())
            self.post('done', False, f'Error getting ffmpeg: {e}')
        finally:
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------- website links
#
# The web app can't run yt-dlp itself (a static site has no server, and
# browsers block cross-site video downloads). Instead its "Open in app" button
# uses a custom link like
#     ytdlp-gui://open?url=https%3A%2F%2Fyoutu.be%2F...&max=1080&min=720&mode=video
# which Windows hands to this exe. The app only pre-fills the form; the user
# still clicks Download, so a web page can never start a download on its own.

PROTOCOL = 'ytdlp-gui'


def register_protocol():
    """Per-user registration (HKCU, no admin) pointing ytdlp-gui:// at this exe."""
    if not getattr(sys, 'frozen', False) or os.name != 'nt':
        return
    try:
        import winreg
        cmd = f'"{sys.executable}" "%1"'
        base = rf'Software\Classes\{PROTOCOL}'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, f'URL:{APP_NAME}')
            winreg.SetValueEx(k, 'URL Protocol', 0, winreg.REG_SZ, '')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r'\DefaultIcon') as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, f'"{sys.executable}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r'\shell\open\command') as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, cmd)
    except OSError:
        pass


def parse_launch_link(argv: list[str]) -> dict:
    """Read settings from a ytdlp-gui:// link or a plain URL argument."""
    from urllib.parse import parse_qs, urlsplit
    if len(argv) < 2:
        return {}
    arg = argv[1].strip()
    if not arg.lower().startswith(PROTOCOL + ':'):
        return {'url': arg} if arg.startswith(('http://', 'https://')) else {}
    q = {k: v[0] for k, v in parse_qs(urlsplit(arg).query).items()}
    out = {}
    url = q.get('url', '')
    if all(u.startswith(('http://', 'https://')) for u in url.split()) and url:
        out['url'] = url
    if q.get('mode') in ('video', 'audio'):
        out['mode'] = q['mode']
    by_height = {v: k for k, v in QUALITIES.items() if v}
    min_by_height = {v: k for k, v in MIN_QUALITIES.items() if v}
    if q.get('max', '').isdigit() and int(q['max']) in by_height:
        out['max'] = by_height[int(q['max'])]
    if q.get('min', '').isdigit() and int(q['min']) in min_by_height:
        out['min'] = min_by_height[int(q['min'])]
    if q.get('audio') in ('mp3', 'm4a', 'opus', 'wav', 'flac'):
        out['audio'] = q['audio']
    for key in ('playlist', 'subs'):
        if q.get(key) in ('1', 'true'):
            out[key] = True
    return out


def apply_launch_link(app: App, link: dict):
    if not link:
        return
    if 'url' in link:
        app.url_var.set(link['url'])
    if 'mode' in link:
        app.mode_var.set(link['mode'])
    if 'max' in link:
        app.quality_var.set(link['max'])
    if 'min' in link:
        app.min_quality_var.set(link['min'])
    if 'audio' in link:
        app.audio_fmt_var.set(link['audio'])
    app.playlist_var.set(link.get('playlist', False))
    app.subs_var.set(link.get('subs', False))
    app._sync_mode()
    app.write_log('Settings filled in from a website link. Check them, then click Download.')


def main():
    register_protocol()
    link = parse_launch_link(sys.argv)
    try:
        # Crisp text on high-DPI screens (must happen before the window exists)
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    style = ttk.Style(root)
    if 'vista' in style.theme_names():
        style.theme_use('vista')
    app = App(root)
    apply_launch_link(app, link)
    root.mainloop()


if __name__ == '__main__':
    main()
