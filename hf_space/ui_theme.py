"""Shared presentation layer for the hosted research lab.

Pure presentation: no data access, computation, credentials or network calls.
Styles target only stable hooks: Streamlit ``st-key-<key>`` classes created by
explicit widget/container keys, ``data-testid`` names and this module's own
``alpha-*`` classes. Colors use translucent tints so light and dark themes from
``.streamlit/config.toml`` both keep readable contrast.
"""
from __future__ import annotations

from html import escape

import streamlit as st


APP_URL = "https://rexymiao-alpha-trading-lab.hf.space/"
PROJECT_URL = "https://huggingface.co/spaces/Rexymiao/alpha-trading-lab"
AI_ANCHOR = "ai-study"
STUDY_ORDER = ("ai", "strategies", "intraday", "beta", "sr", "options", "premarket")

# Badge kinds: real (observed history), frozen (frozen derived reference),
# visitor (visitor-supplied file), teaching (synthetic / TOY), info (neutral).
STUDIES = {
    "ai": {
        "label": ("AI 模型对照", "AI model comparison"),
        "group": ("机器学习 · 日频", "Machine learning · daily"),
        "summary": ("比较 Ridge、MLP、重采样 MLP 与 DDPM 增强 MLP，观察成本、仓位上限与风险预算如何改变模拟结果。",
                    "Compare Ridge, MLP, resampled MLP and DDPM-augmented MLP, and see how costs, position caps and risk budgets change simulated results."),
        "badges": (("visitor", "访客 / moomoo CSV", "Visitor / moomoo CSV"),
                   ("real", "Yahoo 真实日 K", "Yahoo daily history"),
                   ("teaching", "合成教学", "Synthetic teaching")),
        "sidebar": True,
    },
    "strategies": {
        "label": ("日频动量与趋势", "Daily momentum & trend"),
        "group": ("规则策略 · 日频", "Rule strategies · daily"),
        "summary": ("用同一份日 K 比较四类规则策略的信号、仓位、含成本权益与回撤。",
                    "Compare four rule strategies on the same daily bars: signals, weights, equity after costs and drawdowns."),
        "badges": (("visitor", "访客 / moomoo CSV", "Visitor / moomoo CSV"),
                   ("real", "Yahoo 真实日 K", "Yahoo daily history"),
                   ("teaching", "合成教学", "Synthetic teaching")),
        "sidebar": True,
    },
    "intraday": {
        "label": ("5 分钟动量与趋势", "5-minute momentum & trend"),
        "group": ("规则策略 · 日内", "Rule strategies · intraday"),
        "summary": ("比较三种 5 分钟日内规则，以及含成本的纸面代理成交与持仓。",
                    "Compare three 5-minute intraday rules with cost-inclusive proxy fills and holdings."),
        "badges": (("real", "已发布 moomoo 快照", "Published moomoo snapshot"),
                   ("visitor", "访客 5 分钟 CSV", "Visitor 5-minute CSV"),
                   ("teaching", "合成教学", "Synthetic teaching")),
        "sidebar": True,
    },
    "beta": {
        "label": ("Beta 测量与策略对照", "Beta measurement & comparison"),
        "group": ("风险与因子 · 日频", "Risk & factors · daily"),
        "summary": ("126／252 日 Beta 测量；比较高／低 Beta、全池等权与 80%、100% SPY 无杠杆对照。",
                    "126/252-day Beta measurement; compare high and low Beta, equal weight, and unlevered 80% / 100% SPY controls."),
        "badges": (("real", "已发布 moomoo 日 K", "Published moomoo daily bars"),
                   ("visitor", "访客日 K CSV", "Visitor daily CSV")),
        "sidebar": True,
    },
    "sr": {
        "label": ("支撑与阻力策略", "Support & resistance"),
        "group": ("价格区域 · 日内", "Price levels · intraday"),
        "summary": ("以前一完整交易日高低点形成冻结区域，比较支撑反弹、阻力突破与突破回踩。",
                    "Freeze zones from the prior complete session's high and low; compare support bounce, resistance breakout and breakout-retest."),
        "badges": (("real", "已发布 moomoo 快照", "Published moomoo snapshot"),
                   ("visitor", "访客 5 分钟 CSV", "Visitor 5-minute CSV"),
                   ("teaching", "合成教学", "Synthetic teaching")),
        "sidebar": True,
    },
    "options": {
        "label": ("期权结构研究", "Options structure research"),
        "group": ("衍生品结构", "Derivatives structure"),
        "summary": ("先审计 SPY／QQQ 期权数据实际能观察到什么，再运行明确标记的 TOY GEX 与最大痛苦教学计算。",
                    "Audit what SPY / QQQ option data can actually observe, then run clearly labeled TOY GEX and Max Pain teaching calculators."),
        "badges": (("frozen", "安全聚合审计", "Aggregated data audit"),
                   ("teaching", "TOY 教学情景", "TOY teaching scenarios")),
        "sidebar": False,
    },
    "premarket": {
        "label": ("盘前涨幅与开盘下探", "Premarket & opening downside"),
        "group": ("事件研究", "Event study"),
        "summary": ("QQQ、SPY、DIA 盘前涨幅超过阈值后，开盘半小时内最大下探有多深、样本有多少。",
                    "For QQQ, SPY and DIA: after a premarket gain above your threshold, how many events occurred and how far did prices fall in the first 30 minutes?"),
        "badges": (("frozen", "冻结 moomoo 1 分钟派生统计", "Frozen moomoo 1-minute derived stats"),
                   ("info", "250 个交易日 · 非实时", "250 sessions · not live")),
        "sidebar": False,
    },
}


def study_label(tr, study: str) -> str:
    return tr(*STUDIES[study]["label"])


_CSS = """
<style>
[data-testid="stMainBlockContainer"]{max-width:1280px;padding-top:3.75rem;padding-bottom:4rem}
@media (max-width:640px){[data-testid="stMainBlockContainer"]{padding-left:1rem;padding-right:1rem;padding-top:3.5rem}}
h1{letter-spacing:-.02em}
@media (max-width:640px){h1{font-size:1.6rem !important;line-height:1.25 !important}
  .st-key-alpha_header_controls{justify-content:flex-start}}
h2,h3{letter-spacing:-.01em}

/* Header: brand, language and access links */
.st-key-alpha_header{border-bottom:1px solid rgba(120,135,155,.28);padding-bottom:.9rem}
.alpha-brand{display:flex;align-items:center;gap:.7rem;min-width:0}
.alpha-mark{width:2.25rem;height:2.25rem;border-radius:.6rem;flex:none;display:flex;align-items:center;justify-content:center;
  background:linear-gradient(135deg,#0B2545 0%,#0B6E75 100%);color:#fff;font-weight:700;font-size:.95rem;letter-spacing:.02em}
.alpha-wordmark{font-weight:700;font-size:1.08rem;line-height:1.2;letter-spacing:-.01em}
.alpha-tagline{font-size:.8rem;line-height:1.35;opacity:.72}
.st-key-alpha_header .stLinkButton a{font-size:.82rem;min-height:2.1rem;padding:.25rem .7rem}

/* Study navigation as pills */
.st-key-alpha_nav{padding:.15rem 0 .2rem}
.st-key-hf_study [data-testid="stWidgetLabel"] p{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;font-weight:600;opacity:.7}
.st-key-hf_study [data-testid="stRadioGroup"]{gap:.4rem .45rem;flex-wrap:wrap}
.st-key-hf_study [data-testid="stRadioOption"]{border:1px solid rgba(120,135,155,.38);border-radius:999px;margin:0;
  padding:.28rem .8rem .28rem .6rem;transition:background-color .15s,border-color .15s}
.st-key-hf_study [data-testid="stRadioOption"]:hover{border-color:rgba(11,110,117,.65)}
.st-key-hf_study [data-testid="stRadioOption"][data-selected="true"]{background:rgba(14,140,140,.13);border-color:rgba(14,140,140,.8)}
.st-key-hf_study [data-testid="stRadioOption"][data-selected="true"] p{font-weight:600}
@media (max-width:640px){.st-key-hf_study [data-testid="stRadioOption"]{padding:.22rem .65rem .22rem .5rem}
  .st-key-hf_study [data-testid="stRadioOption"] p{font-size:.85rem}}

/* Landing hero and study catalog */
.st-key-alpha_hero{padding:1.35rem 1.5rem 1.1rem;border:1px solid rgba(120,135,155,.26);border-radius:.9rem;
  background:linear-gradient(120deg,rgba(11,37,69,.07),rgba(11,110,117,.08))}
@media (max-width:640px){.st-key-alpha_hero{padding:1rem 1rem .8rem}}
.alpha-eyebrow{font-size:.72rem;text-transform:uppercase;letter-spacing:.09em;font-weight:600;opacity:.7;margin-bottom:.15rem}
.alpha-lede{font-size:1.02rem;line-height:1.55;max-width:58rem}
[class*="st-key-alpha_card_"]{min-height:14.5rem}
[class*="st-key-alpha_card_"] .stButton{margin-top:auto}
.alpha-card-title{font-weight:650;font-size:1rem;line-height:1.3;margin:.1rem 0 .1rem}
.alpha-card-text{font-size:.86rem;line-height:1.5;opacity:.82}
.alpha-card-action{margin-top:auto}
.alpha-card-action a{display:inline-block;padding:.25rem 0;font-size:.95rem;color:inherit;text-decoration:none}
.alpha-card-action a:hover{text-decoration:underline}
@media (min-width:641px) and (max-width:1100px){
  .st-key-alpha_catalog [data-testid="stHorizontalBlock"]{flex-wrap:wrap}
  .st-key-alpha_catalog [data-testid="stColumn"]{min-width:calc(50% - 1rem)}}
@media (max-width:640px){[class*="st-key-alpha_card_"]{min-height:0}}

/* Badges and notes */
.alpha-badges{display:flex;flex-wrap:wrap;gap:.35rem;margin:.2rem 0 .3rem}
.alpha-badge{display:inline-flex;align-items:center;gap:.4rem;font-size:.75rem;line-height:1.25;padding:.18rem .55rem;
  border-radius:999px;border:1px solid rgba(120,135,155,.38);white-space:normal}
.alpha-badge::before{content:"";width:.45rem;height:.45rem;border-radius:50%;background:var(--alpha-dot,#8392A5);flex:none}
.alpha-badge.real{--alpha-dot:#0E9F95;border-color:rgba(14,159,149,.5)}
.alpha-badge.frozen{--alpha-dot:#2F6FB3;border-color:rgba(47,111,179,.5)}
.alpha-badge.visitor{--alpha-dot:#C98A1E;border-color:rgba(201,138,30,.55)}
.alpha-badge.teaching{--alpha-dot:#7A5CC2;border-color:rgba(122,92,194,.5)}
.alpha-badge.warn{--alpha-dot:#C98A1E;border-color:rgba(201,138,30,.6);background:rgba(201,138,30,.08)}
.alpha-badge.ok{--alpha-dot:#0E9F95}
.alpha-note{font-size:.82rem;line-height:1.45;opacity:.8;margin:.1rem 0 .4rem}
.alpha-runbar{display:flex;flex-wrap:wrap;gap:.35rem .5rem;align-items:center;font-size:.82rem;line-height:1.4;
  padding:.5rem .75rem;border-radius:.6rem;border:1px solid rgba(120,135,155,.3);background:rgba(120,135,155,.06);margin:.25rem 0 .6rem}
.alpha-runbar.changed{border-color:rgba(201,138,30,.65);background:rgba(201,138,30,.09)}
.alpha-runbar b{font-weight:650}
.alpha-chip{padding:.05rem .45rem;border-radius:.35rem;background:rgba(120,135,155,.13);font-variant-numeric:tabular-nums}
.alpha-stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.3rem .9rem;font-size:.84rem;margin:.2rem 0 .3rem}
.alpha-stats span{opacity:.72}
.alpha-stats b{font-variant-numeric:tabular-nums;font-weight:600;display:block}

/* Wide content scrolls inside its own box instead of the page */
.katex-display{overflow-x:auto;overflow-y:hidden;padding:.2rem 0}
[data-testid="stMarkdownContainer"] pre{overflow-x:auto}
[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums}
.alpha-kpis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.4rem .9rem;margin:.1rem 0 .2rem}
.alpha-kpis span{display:block;font-size:.8rem;opacity:.72}
.alpha-kpis b{display:block;font-size:1.6rem;font-weight:620;line-height:1.25;font-variant-numeric:tabular-nums}
[data-testid="stExpander"] summary p{font-weight:550}
</style>
"""


def inject_styles() -> None:
    st.html(_CSS)


def badges_html(items) -> str:
    return "<div class='alpha-badges'>" + "".join(
        f"<span class='alpha-badge {escape(kind)}'>{escape(text)}</span>" for kind, text in items) + "</div>"


def badges(items) -> None:
    st.markdown(badges_html(items), unsafe_allow_html=True)


def study_badges(tr, study: str) -> None:
    badges([(kind, tr(zh, en)) for kind, zh, en in STUDIES[study]["badges"]])


def study_meta(tr, study: str) -> None:
    """Source badges plus, for sidebar studies, where the settings live."""
    study_badges(tr, study)
    if STUDIES[study]["sidebar"]:
        st.markdown("<div class='alpha-note'>⚙ " + escape(tr(
            "本专题的数据与参数在左侧边栏；手机上点左上角箭头展开。修改参数不会自动运行。",
            "Data and settings for this study are in the left sidebar; on phones, open it with the arrow at the top left. Editing settings never starts a run.")
        ) + "</div>", unsafe_allow_html=True)


def run_bar(tr, items, *, changed: bool) -> None:
    """Show the executed settings, and flag unsubmitted edits without applying them."""
    label = tr("当前结果来自上次运行：", "Results shown use the last run:")
    chips = "".join(f"<span class='alpha-chip'>{escape(str(item))}</span>" for item in items)
    tail = ("<span>⚠ " + escape(tr("输入已修改，尚未应用；点击运行／统计后才会更新结果。",
                                   "Inputs edited but not applied; click Run / Compare to update results.")) + "</span>"
            if changed else "")
    st.markdown(f"<div class='alpha-runbar{' changed' if changed else ''}'><b>{escape(label)}</b>{chips}{tail}</div>",
                unsafe_allow_html=True)


def header(tr, on_language_change) -> None:
    with st.container(key="alpha_header"):
        brand, controls = st.columns([5, 6], vertical_alignment="center")
        with brand:
            st.markdown(
                "<div class='alpha-brand'><div class='alpha-mark'>α</div><div>"
                "<div class='alpha-wordmark'>Alpha Trading Lab</div>"
                f"<div class='alpha-tagline'>{escape(tr('量化研究工作台 · 七个研究专题 · 仅研究与模拟，不连接券商', 'Quant research workbench · seven studies · research and simulation only, no brokerage'))}</div>"
                "</div></div>", unsafe_allow_html=True)
        with controls, st.container(horizontal=True, horizontal_alignment="right",
                                    vertical_alignment="center", gap="small", key="alpha_header_controls"):
            st.radio("Language / 语言", ("English", "中文"), key="hf_language", horizontal=True,
                     on_change=on_language_change, label_visibility="collapsed", width="content")
            st.link_button(tr("进入研究平台", "Launch Research Lab"), APP_URL, icon=":material/open_in_new:",
                           width="content")
            st.link_button(tr("Hugging Face项目页", "Hugging Face project"), PROJECT_URL,
                           icon=":material/deployed_code:", width="content")


def _open_study(study: str) -> None:
    st.session_state["_hf_study_choice"] = study


def catalog(tr) -> None:
    """Seven study cards; buttons only navigate, they never compute or fetch."""
    with st.container(key="alpha_catalog"):
        for row in (STUDY_ORDER[:4], STUDY_ORDER[4:]):
            columns = st.columns(4)
            for column, study in zip(columns, row):
                info = STUDIES[study]
                number = STUDY_ORDER.index(study) + 1
                with column, st.container(border=True, key=f"alpha_card_{study}"):
                    st.markdown(f"<div class='alpha-eyebrow'>{number:02d} · {escape(tr(*info['group']))}</div>"
                                f"<div class='alpha-card-title'>{escape(tr(*info['label']))}</div>"
                                f"<div class='alpha-card-text'>{escape(tr(*info['summary']))}</div>",
                                unsafe_allow_html=True)
                    study_badges(tr, study)
                    if study == "ai":
                        # Same-page anchor: scrolls to the AI study header; no computation.
                        st.markdown(f"<div class='alpha-card-action'><a href='#{AI_ANCHOR}' target='_self'>"
                                    + escape(tr("前往本页下方的 AI 专题", "Go to the AI study below")) + " ↓</a></div>",
                                    unsafe_allow_html=True)
                    else:
                        st.button(tr("打开专题", "Open study") + " →", key=f"hf_open_{study}", type="tertiary",
                                  on_click=_open_study, args=(study,))
