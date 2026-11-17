# YT Downloader: project summary

## In one paragraph

YT Downloader is an independent study project that wraps the open-source
yt-dlp command-line downloader in a Windows desktop app anyone can use. You
paste a video, playlist or channel link, pick a quality range or audio format,
and click Download. The app ships as a single self-contained exe, is built
automatically by GitHub Actions, and has a companion web app on GitHub Pages
that opens the desktop app with settings already filled in. Everything is free
to use and free to run.

## What I built

- **Desktop app** (`app/ytdlp_gui.py`, Python + Tkinter). Uses yt-dlp as a
  library on a background thread. yt-dlp's progress hooks, post-processor hooks
  and a custom logger feed a queue that the window reads every 100 ms, so the
  UI never freezes.
- **Quality control.** A max quality is a sort preference (`-S res:1080`), and a
  min quality is a hard format filter (`[height>=720]`). A video that can't meet
  the minimum fails cleanly and is skipped.
- **Robust batch runs.** Failed videos are logged and skipped. *Skip current
  video* and *Cancel all* are checked at every yt-dlp log line and hook, so
  they take effect while fetching pages and solving YouTube's JavaScript
  challenge, not only while bytes are flowing. Cancel-all subclasses yt-dlp's
  `DownloadCancelled`, which yt-dlp re-raises even when errors are ignored.
- **Packaging.** PyInstaller one-file build with the deno runtime bundled.
  ffmpeg is fetched on demand from the yt-dlp FFmpeg-Builds project to keep
  the exe at ~60 MB.
- **Web companion** (`docs/index.html`). A static page that builds a
  `ytdlp-gui://open?url=…&max=1080&min=720` link. The app registers that scheme
  per user (no admin rights needed) and pre-fills the form from it. The page
  also shows the equivalent yt-dlp command and can share its settings as a URL.
- **CI/CD.** Tagging `v*` builds the exe on a GitHub-hosted Windows runner and
  publishes a Release. Pushing to `main` redeploys the site.

## Design decision: why downloads run on the user's PC

A static site can't run yt-dlp, and browsers block cross-origin video fetches.
A hosted download server was rejected for four reasons. It costs money beyond
free tiers. YouTube rate-limits and blocks datacenter IPs. An open endpoint
invites abuse. Proxying downloads for the public raises Terms of Service
issues. Handing settings to a local app keeps the project free, reliable and
within each user's own responsibility.

## Results

- Tested on a 471-video channel at 720p to 1080p: 468 downloaded on the first
  pass. The 3 that failed during a network outage were skipped automatically
  and completed on a resumed run, about 31 GB in total.
- Found and fixed real-world issues during testing: YouTube's only combined
  stream is 360p (which is why ffmpeg is needed for HD), cancel didn't stop
  between downloads, and two videos with identical titles overwrote each
  other (fixed with the optional video ID in file names).

## Tech

Python 3.13, Tkinter, yt-dlp, deno, ffmpeg, PyInstaller, GitHub Actions,
GitHub Pages, vanilla JavaScript (Web Components).

---

## Putting it on your personal website

Everything below is served from GitHub Pages, so it's free and updates itself
when `docs/embed/project.json` changes.

**Option 1: drop-in card (recommended).** Paste anywhere in your HTML:

```html
<script src="https://mendus59.github.io/yt-dlp-GUI/embed/embed.js" defer></script>
<ytdlp-gui-card></ytdlp-gui-card>
```

Optional attributes: `theme="light|dark|auto"`, `compact`, `accent="#hex"`.
The card's styles are isolated in a shadow root, so they won't clash with your site.

**Option 2: iframe** (for site builders that block scripts, such as some Wix/Squarespace plans):

```html
<iframe src="https://mendus59.github.io/yt-dlp-GUI/embed/card.html?theme=auto"
        title="YT Downloader" style="width:100%;max-width:660px;height:420px;border:0"></iframe>
```

**Option 3: just the data.** Fetch
`https://mendus59.github.io/yt-dlp-GUI/embed/project.json` (name, tagline,
summary, highlights, tech, links) and render it with your own site's components.
GitHub Pages sends `Access-Control-Allow-Origin: *`, so it works from any domain.
