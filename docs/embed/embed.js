/*
 * <ytdlp-gui-card> : drop-in project card for a personal website.
 *
 *   <script src="https://mendus59.github.io/yt-dlp-GUI/embed/embed.js" defer></script>
 *   <ytdlp-gui-card></ytdlp-gui-card>
 *
 * Attributes (all optional):
 *   theme="light|dark|auto"   default auto (follows the visitor's OS setting)
 *   compact                   hide the highlights list
 *   accent="#c4302b"          button / icon colour
 *
 * Content comes from project.json next to this file, so updating that file
 * updates every site that embeds the card. Styles live in a shadow root and
 * won't clash with the host page.
 */
(() => {
  const BASE = new URL('.', document.currentScript ? document.currentScript.src
                                                   : 'https://mendus59.github.io/yt-dlp-GUI/embed/');
  let dataPromise;
  const load = () => dataPromise ||= fetch(new URL('project.json', BASE)).then(r => {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  });
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  class YtdlpGuiCard extends HTMLElement {
    static get observedAttributes() { return ['theme', 'compact', 'accent']; }
    connectedCallback() { this.render(); }
    attributeChangedCallback() { if (this.isConnected) this.render(); }

    async render() {
      const root = this.shadowRoot || this.attachShadow({ mode: 'open' });
      let d;
      try { d = await load(); }
      catch {
        root.innerHTML = '<a href="https://mendus59.github.io/yt-dlp-GUI/">YT Downloader</a>';
        return;
      }
      const theme = this.getAttribute('theme') || 'auto';
      const accent = this.getAttribute('accent') || '#c4302b';
      const light = '--bg:#fff;--text:#1d1d1f;--muted:#5f6368;--border:#e2e2de;--chip:#f0f0ec;';
      const dark = '--bg:#1e1e1e;--text:#ececec;--muted:#a0a0a0;--border:#333;--chip:#2a2a2a;';
      const vars = theme === 'dark' ? dark : light;
      const auto = theme === 'auto' ? `@media (prefers-color-scheme: dark){:host{${dark}}}` : '';
      const highlights = this.hasAttribute('compact') ? '' :
        `<ul>${d.highlights.map(h => `<li>${esc(h)}</li>`).join('')}</ul>`;

      root.innerHTML = `
<style>
:host{display:block;${vars}--accent:${esc(accent)};font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--text)}
${auto}
.card{background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:18px;max-width:640px}
.head{display:flex;gap:12px;align-items:center}
img{width:44px;height:44px;border-radius:10px;flex:none}
h3{margin:0;font-size:1.15rem}
.tag{margin:2px 0 0;color:var(--muted);font-size:.9rem}
p{margin:12px 0}
ul{margin:0 0 12px;padding-left:18px} li{margin:2px 0}
.tech{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 14px;padding:0;list-style:none}
.tech li{background:var(--chip);border-radius:999px;padding:2px 10px;font-size:.8rem;margin:0}
.links{display:flex;flex-wrap:wrap;gap:8px}
a{color:var(--accent)}
.btn{display:inline-block;padding:7px 14px;border-radius:8px;border:1px solid var(--border);text-decoration:none;color:var(--text);font-weight:600;font-size:.9rem}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
</style>
<div class="card">
  <div class="head"><img src="${esc(d.image)}" alt="">
    <div><h3>${esc(d.name)}</h3><div class="tag">${esc(d.tagline)}</div></div></div>
  <p>${esc(d.summary)}</p>
  ${highlights}
  <ul class="tech">${d.tech.map(t => `<li>${esc(t)}</li>`).join('')}</ul>
  <div class="links">
    <a class="btn primary" href="${esc(d.links.site)}">Try it</a>
    <a class="btn" href="${esc(d.links.download)}">Download (Windows)</a>
    <a class="btn" href="${esc(d.links.source)}">Source</a>
  </div>
</div>`;
    }
  }
  if (!customElements.get('ytdlp-gui-card')) customElements.define('ytdlp-gui-card', YtdlpGuiCard);
})();
