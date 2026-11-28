"""Public training guide shown inside the research lab.

The static teaching page in ``web/`` stays the single source. The Space package
copies its three text files to ``hf_space/guide/``; locally they are read from
``web/``. Images are binary, which the text-only Space package does not carry, so
they load from the same repository's GitHub Pages copy. The page is illustrative
teaching only: no market observations, accounts or orders.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ASSET_BASE = "https://rexmiao.github.io/alpha-trading-lab/assets/"
_HERE = Path(__file__).resolve().parent
_CANDIDATES = (_HERE / "guide", _HERE.parent / "web")

# Embedded mode: the lab header already carries the brand and language choice, so
# the guide's own brand and language button are hidden; in-page navigation scrolls
# the lab page; the link back to this same app is hidden.
_EMBED_CSS = """
.topbar .brand,#language,a[data-i18n="openHf"]{display:none!important}
.topbar{min-height:0;padding-top:6px;padding-bottom:14px;justify-content:flex-start}
.topnav{justify-content:flex-start}
html,body{background:#fff}
"""

_EMBED_PRELUDE = """
<script>try{localStorage.setItem('alpha-guide-language','__LANG__');}catch(e){}</script>
"""

_EMBED_TAIL = """
<script>
(() => {
  const frame = window.frameElement;
  const fit = () => {
    if (!frame) return;
    const h = Math.ceil(document.documentElement.scrollHeight) + 4;
    if (Math.abs(frame.offsetHeight - h) > 2) frame.style.height = h + 'px';
  };
  new ResizeObserver(fit).observe(document.body);
  window.addEventListener('load', fit);
  setTimeout(fit, 300);
  document.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('a[href^="#"]');
    if (!a) return;
    const id = a.getAttribute('href').slice(1);
    const target = id === 'top' ? document.body : document.getElementById(id);
    if (target) { e.preventDefault(); target.scrollIntoView({behavior: 'smooth', block: 'start'}); }
  });
})();
</script>
"""


def _source_dir() -> Path:
    for folder in _CANDIDATES:
        if (folder / "index.html").is_file():
            return folder
    raise FileNotFoundError("Training guide source files are missing.")


def build_guide_html(lang: str) -> str:
    """Inline the guide's CSS and JS, point images at GitHub Pages, set the language."""
    if lang not in ("en", "zh"):
        raise ValueError("lang must be 'en' or 'zh'")
    folder = _source_dir()
    page = (folder / "index.html").read_text(encoding="utf-8")
    css = (folder / "style.css").read_text(encoding="utf-8")
    script = (folder / "main.js").read_text(encoding="utf-8")
    page = page.replace('<link rel="stylesheet" href="style.css">',
                        f"<style>{css}\n{_EMBED_CSS}</style>")
    page = page.replace('<script src="main.js?v=4"></script>',
                        _EMBED_PRELUDE.replace("__LANG__", lang)
                        + f"<script>{script}</script>" + _EMBED_TAIL)
    page = page.replace('"assets/', f'"{ASSET_BASE}')
    script_marker = "`assets/"
    page = page.replace(script_marker, f"`{ASSET_BASE}")
    if "style.css" in page.split("<style>")[0] or 'src="main.js' in page:
        raise RuntimeError("Training guide template changed; update the embedding.")
    return page


def render_guide_page(tr, on_back) -> None:
    st.button(tr("← 返回研究专题", "← Back to studies"), key="alpha_guide_back", on_click=on_back)
    st.title(tr("训练指南", "Training Guide"))
    st.caption(tr("中英双语教学：训练流程动图、动量与趋势规则、EWMA 与仓位交互、数学说明。所有数值均为假设教学示例，不是回测结果；不连接行情、账户或券商。",
                  "Bilingual teaching: the training-flow animation, momentum and trend rules, interactive EWMA and allocation examples, and mathematical notes. All values are illustrative, not backtest results; no market data, accounts or brokerage."))
    try:
        html = build_guide_html(tr("zh", "en"))
    except (OSError, RuntimeError) as error:
        st.error(tr("训练指南文件缺失，暂时无法显示。", "The training guide files are missing and cannot be shown.")
                 + f" ({type(error).__name__})")
        return
    with st.container(key="alpha_guide_frame"):
        components.html(html, height=4200, scrolling=False)
