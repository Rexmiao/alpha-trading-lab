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


APP_URL = "https://alphalab.levyquant.ai/"
PROJECT_URL = "https://huggingface.co/spaces/Rexymiao/alpha-trading-lab"
AI_ANCHOR = "ai-study"
STUDY_ORDER = ("ai", "strategies", "intraday", "beta", "sr", "options", "premarket")

# Badge kinds: real (observed history), frozen (frozen derived reference),
# visitor (visitor-supplied file), teaching (synthetic / TOY), info (neutral).
STUDIES = {
    "ai": {
        "label": ("AI 模型对照", "AI Model Comparison"),
        "group": ("机器学习 · 日频", "Machine learning · daily"),
        "summary": ("比较 Ridge、MLP、重采样 MLP 与 DDPM 增强 MLP，观察成本、仓位上限与风险预算如何改变模拟结果。",
                    "Compare Ridge, MLP, resampled MLP and DDPM-augmented MLP, and see how costs, position caps and risk budgets change simulated results."),
        "badges": (("visitor", "访客 / moomoo CSV", "Visitor / moomoo CSV"),
                   ("real", "Yahoo 真实日 K", "Yahoo daily history"),
                   ("teaching", "合成教学", "Synthetic teaching")),
        "sidebar": True,
    },
    "strategies": {
        "label": ("日频动量与趋势", "Daily Momentum & Trend"),
        "group": ("规则策略 · 日频", "Rule strategies · daily"),
        "summary": ("用同一份日 K 比较四类规则策略的信号、仓位、含成本权益与回撤。",
                    "Compare four rule strategies on the same daily bars: signals, weights, equity after costs and drawdowns."),
        "badges": (("visitor", "访客 / moomoo CSV", "Visitor / moomoo CSV"),
                   ("real", "Yahoo 真实日 K", "Yahoo daily history"),
                   ("teaching", "合成教学", "Synthetic teaching")),
        "sidebar": True,
    },
    "intraday": {
        "label": ("5 分钟动量与趋势", "5-Minute Momentum & Trend"),
        "group": ("规则策略 · 日内", "Rule strategies · intraday"),
        "summary": ("比较三种 5 分钟日内规则，以及含成本的纸面代理成交与持仓。",
                    "Compare three 5-minute intraday rules with cost-inclusive proxy fills and holdings."),
        "badges": (("real", "已发布 moomoo 快照", "Published moomoo snapshot"),
                   ("visitor", "访客 5 分钟 CSV", "Visitor 5-minute CSV"),
                   ("teaching", "合成教学", "Synthetic teaching")),
        "sidebar": True,
    },
    "beta": {
        "label": ("Beta 测量与策略对照", "Beta Measurement & Comparison"),
        "group": ("风险与因子 · 日频", "Risk & factors · daily"),
        "summary": ("126／252 日 Beta 测量；比较高／低 Beta、全池等权与 80%、100% SPY 无杠杆对照。",
                    "126/252-day Beta measurement; compare high and low Beta, equal weight, and unlevered 80% / 100% SPY controls."),
        "badges": (("real", "已发布 moomoo 日 K", "Published moomoo daily bars"),
                   ("visitor", "访客日 K CSV", "Visitor daily CSV")),
        "sidebar": True,
    },
    "sr": {
        "label": ("支撑与阻力策略", "Support & Resistance"),
        "group": ("价格区域 · 日内", "Price levels · intraday"),
        "summary": ("以前一完整交易日高低点形成冻结区域，比较支撑反弹、阻力突破与突破回踩。",
                    "Freeze zones from the prior complete session's high and low; compare support bounce, resistance breakout and breakout-retest."),
        "badges": (("real", "已发布 moomoo 快照", "Published moomoo snapshot"),
                   ("visitor", "访客 5 分钟 CSV", "Visitor 5-minute CSV"),
                   ("teaching", "合成教学", "Synthetic teaching")),
        "sidebar": True,
    },
    "options": {
        "label": ("期权结构研究", "Options Structure Research"),
        "group": ("衍生品结构", "Derivatives structure"),
        "summary": ("先审计 SPY／QQQ 期权数据实际能观察到什么，再运行明确标记的 TOY GEX 与最大痛苦教学计算。",
                    "Audit what SPY / QQQ option data can actually observe, then run clearly labeled TOY GEX and Max Pain teaching calculators."),
        "badges": (("frozen", "安全聚合审计", "Aggregated data audit"),
                   ("teaching", "TOY 教学情景", "TOY teaching scenarios")),
        "sidebar": False,
    },
    "premarket": {
        "label": ("盘前涨幅与开盘下探", "Premarket & Opening Downside"),
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
[data-testid="stMainBlockContainer"]{max-width:1280px;padding-top:3.25rem;padding-bottom:4rem}
@media (max-width:640px){[data-testid="stMainBlockContainer"]{padding-left:1rem;padding-right:1rem;padding-top:3.5rem}}
h1{letter-spacing:-.02em}
@media (max-width:640px){h1{font-size:1.6rem !important;line-height:1.25 !important}
  .st-key-alpha_header_controls{justify-content:flex-start}}
h2,h3{letter-spacing:-.01em}

/* Header: brand, language and access links */
.st-key-alpha_header{padding:.6rem .9rem .6rem .75rem;border-radius:.9rem;
  border:1px solid rgba(120,135,155,.25);border-color:light-dark(#DDE4EC,rgba(120,135,155,.25));
  background-color:light-dark(#FFFFFF,rgba(255,255,255,.03));
  box-shadow:0 1px 2px light-dark(rgba(16,40,70,.06),transparent),0 8px 24px -16px light-dark(rgba(16,40,70,.22),transparent)}
.alpha-brand{display:flex;align-items:center;gap:.75rem;min-width:0}
.alpha-logo{width:2.5rem;height:2.5rem;flex:none;display:block;border-radius:.7rem;
  box-shadow:0 6px 16px -8px rgba(11,60,80,.7)}
.alpha-logo-line{stroke-dasharray:40;stroke-dashoffset:40;animation:alpha-draw 1.2s cubic-bezier(.4,.1,.2,1) forwards .2s}
.alpha-logo-dot{transform-origin:31.5px 9.5px;animation:alpha-pop .4s ease-out both 1.2s}
.alpha-wordmark{font-weight:750;font-size:1.1rem;line-height:1.2;letter-spacing:-.015em}
.alpha-wordmark span{background:linear-gradient(92deg,#0E9F95,#2F6FB3);-webkit-background-clip:text;background-clip:text;color:transparent}
.alpha-tagline{font-size:.78rem;line-height:1.35;opacity:.68}
.st-key-alpha_header .stLinkButton a{font-size:.82rem;min-height:2.1rem;padding:.25rem .7rem}
.alpha-theme-toggle{display:inline-flex;align-items:center;justify-content:center;width:2.1rem;height:2.1rem;
  padding:0;border-radius:.5rem;cursor:pointer;color:inherit;background:transparent;
  border:1px solid light-dark(#D3DCE6,#2B3A4B);transition:background-color .15s,border-color .15s,transform .15s}
.alpha-theme-toggle:hover{border-color:#0B6E75;background-color:light-dark(rgba(11,110,117,.06),rgba(60,193,184,.1))}
.alpha-theme-toggle:active{transform:scale(.94)}
.alpha-theme-toggle:focus-visible{outline:2px solid #0B6E75;outline-offset:2px}
.alpha-theme-toggle svg{width:1.05rem;height:1.05rem;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.alpha-theme-toggle .alpha-ico-sun,.alpha-theme-toggle[data-mode="dark"] .alpha-ico-moon{display:none}
.alpha-theme-toggle[data-mode="dark"] .alpha-ico-sun{display:block}
.alpha-theme-switching [data-baseweb="popover"]{opacity:0 !important}

/* Sidebar: white rail, quiet panels, notes as indented captions */
[data-testid="stSidebar"]{border-right:1px solid light-dark(#E3E8EF,rgba(120,135,155,.18))}
[data-testid="stSidebarUserContent"]{padding-top:.25rem}
[data-testid="stSidebar"] h3{font-size:1rem !important;display:flex;align-items:center;gap:.55rem;
  padding-bottom:.55rem;margin-bottom:.35rem;border-bottom:1px solid light-dark(#E8EDF3,rgba(120,135,155,.2))}
[data-testid="stSidebar"] h3::before{content:"";width:.6rem;height:.6rem;border-radius:.2rem;flex:none;
  background:linear-gradient(135deg,#2DD4BF,#3B82F6)}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p{font-weight:600;font-size:.84rem}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{font-size:.78rem;line-height:1.5;
  padding-left:.65rem;border-left:2px solid light-dark(#CFE3E4,rgba(60,193,184,.35))}
[data-testid="stSidebar"] [data-testid="stForm"],[data-testid="stSidebar"] [data-testid="stExpander"] details,
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]{
  background-color:light-dark(#F7F9FC,transparent) !important;box-shadow:none}

/* Study navigation as pills */
.st-key-alpha_nav{padding:.15rem 0 .2rem}
.st-key-hf_study [data-testid="stWidgetLabel"] p{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;font-weight:600;opacity:.7}
.st-key-hf_study [data-testid="stRadioGroup"]{gap:.4rem .45rem;flex-wrap:wrap}
.st-key-hf_study [data-testid="stRadioOption"]{border:1px solid rgba(120,135,155,.38);border-radius:999px;margin:0;
  padding:.28rem .8rem .28rem .6rem;transition:background-color .15s,border-color .15s}
.st-key-hf_study [data-testid="stRadioOption"]:hover{border-color:rgba(11,110,117,.65)}
.st-key-hf_study [data-testid="stRadioOption"][data-selected="true"]{border-color:rgba(14,140,140,.8);
  background:linear-gradient(120deg,rgba(45,212,191,.18),rgba(59,130,246,.14));box-shadow:0 0 0 3px rgba(45,212,191,.12)}
.st-key-hf_study [data-testid="stRadioOption"]{transition:background-color .2s,border-color .2s,box-shadow .2s,transform .2s}
.st-key-hf_study [data-testid="stRadioOption"]:hover{transform:translateY(-1px)}
.st-key-hf_study [data-testid="stRadioOption"][data-selected="true"] p{font-weight:600}
/* Surfaces: light theme = white panels on a cool blue-gray canvas. light-dark() follows the
   color-scheme Streamlit sets on .stApp; older browsers keep the transparent default. */
.st-key-hf_study [data-testid="stRadioOption"]:not([data-selected="true"]){background-color:light-dark(#FFFFFF,transparent)}
[class*="st-key-alpha_card_"],[class*="st-key-premarket_card_"],[data-testid="stForm"],
[data-testid="stExpander"] details,[data-testid="stTabs"] [data-baseweb="tab-panel"]{
  background-color:light-dark(#FFFFFF,transparent);
  box-shadow:0 1px 2px light-dark(rgba(16,40,70,.06),transparent),0 6px 18px -12px light-dark(rgba(16,40,70,.18),transparent)}
[data-testid="stTabs"] [data-baseweb="tab-panel"]{border:1px solid light-dark(#DDE4EC,rgba(120,135,155,.22));
  border-radius:.6rem;padding:.9rem 1rem !important}@media (max-width:640px){.st-key-hf_study [data-testid="stRadioOption"]{padding:.22rem .65rem .22rem .5rem}
  .st-key-hf_study [data-testid="stRadioOption"] p{font-size:.85rem}}

/* Landing hero and study catalog */
/* Hero: self-colored dark band, readable in both app themes */
.st-key-alpha_hero{position:relative;isolation:isolate;overflow:hidden;padding:2.4rem 2.2rem 1.9rem;border-radius:1.1rem;
  background:linear-gradient(135deg,#06101D 0%,#0A2240 48%,#0A3A45 100%);color:#E8F1F8;
  border:1px solid rgba(127,224,210,.18);box-shadow:0 18px 50px -24px rgba(6,16,29,.65)}
.st-key-alpha_hero::before{content:"";position:absolute;inset:-40%;z-index:-1;pointer-events:none;
  background:radial-gradient(38% 42% at 22% 30%,rgba(45,212,191,.32),transparent 70%),
             radial-gradient(34% 40% at 78% 70%,rgba(59,130,246,.30),transparent 70%),
             radial-gradient(26% 30% at 60% 18%,rgba(139,92,246,.20),transparent 70%);
  filter:blur(18px);animation:alpha-aurora 18s ease-in-out infinite alternate}
.st-key-alpha_hero::after{content:"";position:absolute;inset:0;z-index:-1;pointer-events:none;
  background-image:radial-gradient(rgba(255,255,255,.14) 1px,transparent 1px);background-size:22px 22px;
  -webkit-mask-image:linear-gradient(180deg,rgba(0,0,0,.9),transparent 85%);mask-image:linear-gradient(180deg,rgba(0,0,0,.9),transparent 85%)}
.st-key-alpha_hero [data-testid="stMarkdownContainer"],.st-key-alpha_hero [data-testid="stMarkdownContainer"] p{color:#D5E3EE}
.st-key-alpha_hero h1{font-size:2.7rem;line-height:1.12;padding-bottom:.55rem;
  background:linear-gradient(92deg,#FFFFFF 0%,#D9FBF5 45%,#6EE7D8 100%);-webkit-background-clip:text;background-clip:text;color:transparent;
  animation:alpha-rise .7s cubic-bezier(.2,.7,.2,1) both .05s}
.st-key-alpha_hero .alpha-eyebrow{opacity:1;color:#7FE0D2;display:inline-flex;align-items:center;gap:.5rem;animation:alpha-rise .6s ease both}
.alpha-live{width:.5rem;height:.5rem;border-radius:50%;background:#2DD4BF;box-shadow:0 0 0 0 rgba(45,212,191,.6);animation:alpha-ping 2.2s ease-out infinite}
.st-key-alpha_hero .alpha-lede{color:#C9D8E4;font-size:1.06rem;animation:alpha-rise .7s ease both .15s}
.st-key-alpha_hero .alpha-badges{animation:alpha-rise .7s ease both .25s}
.st-key-alpha_hero .alpha-badge{color:#E8F1F8;border-color:rgba(255,255,255,.2);background:rgba(255,255,255,.05);backdrop-filter:blur(4px)}
.alpha-hero-stats{display:flex;flex-wrap:wrap;gap:1.6rem;margin:1rem 0 .3rem;animation:alpha-rise .7s ease both .35s}
.alpha-hero-stats div{min-width:6.5rem}
.alpha-hero-stats b{display:block;font-size:2rem;font-weight:700;line-height:1.1;color:#fff;font-variant-numeric:tabular-nums}
.alpha-hero-stats span{font-size:.8rem;color:#9FB4C6}
@property --alpha-n{syntax:"\\3C integer\\3E";inherits:false;initial-value:0}
.alpha-count{--alpha-to:0;counter-reset:alpha var(--alpha-n);animation:alpha-count 1.6s cubic-bezier(.2,.7,.2,1) both .4s}
.alpha-count::after{content:counter(alpha)}
.alpha-count.n7{--alpha-to:7}.alpha-count.n250{--alpha-to:250}.alpha-count.n0{--alpha-to:0}
.alpha-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.st-key-alpha_hero_art{position:relative;animation:alpha-rise .9s ease both .2s}
.alpha-art-wrap{position:relative;padding:1.4rem 0 1.2rem}
.alpha-art{width:100%;height:auto;display:block;filter:drop-shadow(0 10px 30px rgba(45,212,191,.18))}
.alpha-art .grid line{stroke:rgba(255,255,255,.08)}
.alpha-art .bar{fill:rgba(127,224,210,.22);transform-box:fill-box;transform-origin:bottom;animation:alpha-grow .9s cubic-bezier(.2,.7,.2,1) both}
.alpha-art .bench{fill:none;stroke:rgba(147,197,253,.55);stroke-width:2;stroke-dasharray:6 6}
.alpha-art .line{fill:none;stroke:url(#alphaLine);stroke-width:3;stroke-linecap:round;stroke-linejoin:round;
  stroke-dasharray:1400;stroke-dashoffset:1400;animation:alpha-draw 2.6s cubic-bezier(.4,.1,.2,1) forwards .3s}
.alpha-art .area{fill:url(#alphaArea);opacity:0;animation:alpha-fade 1.2s ease forwards 1.8s}
.alpha-art .scan{stroke:rgba(127,224,210,.45);stroke-width:1.5;animation:alpha-scan 6s linear infinite 2.9s;opacity:0}
.alpha-art .dot{fill:#6EE7D8;opacity:0;animation:alpha-fade .4s ease forwards 2.8s}
.alpha-art .ring{fill:none;stroke:#6EE7D8;stroke-width:2;transform-box:fill-box;transform-origin:center;opacity:0;animation:alpha-ring 2.4s ease-out infinite 3s}
.alpha-art-note{position:absolute;right:.4rem;bottom:.1rem;font-size:.68rem;color:#8EA3B5;letter-spacing:.02em}
.alpha-float{position:absolute;font-size:.72rem;color:#E8F1F8;padding:.28rem .6rem;border-radius:999px;
  border:1px solid rgba(255,255,255,.18);background:rgba(10,34,64,.72);backdrop-filter:blur(6px);animation:alpha-float 6s ease-in-out infinite}
.alpha-float.a{top:6%;left:4%}.alpha-float.b{top:40%;right:0;animation-delay:-3s}
@media (max-width:900px){.st-key-alpha_hero h1{font-size:2.1rem}}
@media (max-width:640px){.st-key-alpha_hero{padding:1.4rem 1.1rem 1.1rem}
  .st-key-alpha_hero [data-testid="stColumn"]:has(.st-key-alpha_hero_art){display:none}
  .st-key-alpha_hero h1{font-size:1.75rem !important}.alpha-hero-stats{gap:.8rem;flex-wrap:nowrap}
  .alpha-hero-stats div{min-width:0;flex:1}.alpha-hero-stats b{font-size:1.5rem}.alpha-hero-stats span{font-size:.74rem}}
.alpha-eyebrow{font-size:.72rem;text-transform:uppercase;letter-spacing:.09em;font-weight:600;opacity:.7;margin-bottom:.15rem}
.alpha-lede{font-size:1.02rem;line-height:1.55;max-width:58rem}
[class*="st-key-alpha_card_"]{min-height:14.5rem}
[class*="st-key-alpha_card_"] .stButton{margin-top:auto}
.alpha-card-title{font-weight:650;font-size:1rem;line-height:1.3;margin:.1rem 0 .1rem}
.alpha-card-text{font-size:.86rem;line-height:1.5;opacity:.82}
.alpha-card-action{margin-top:auto}
.alpha-card-action a{display:inline-block;padding:.25rem 0;font-size:.95rem;color:inherit;text-decoration:none}
.alpha-card-action a:hover{text-decoration:underline}
[class*="st-key-alpha_card_"]{position:relative;overflow:hidden;
  transition:transform .25s cubic-bezier(.2,.7,.2,1),box-shadow .25s ease,border-color .25s ease;
  animation:alpha-rise .6s cubic-bezier(.2,.7,.2,1) both}
[class*="st-key-alpha_card_"]::before{content:"";position:absolute;left:0;right:0;top:0;height:3px;
  background:linear-gradient(90deg,#2DD4BF,#3B82F6,#8B5CF6);transform:scaleX(0);transform-origin:left;transition:transform .35s ease}
[class*="st-key-alpha_card_"]:hover{transform:translateY(-4px);border-color:rgba(14,140,140,.55) !important;
  box-shadow:0 14px 34px -18px rgba(11,60,80,.55)}
[class*="st-key-alpha_card_"]:hover::before{transform:scaleX(1)}
.st-key-alpha_card_strategies{animation-delay:.06s}.st-key-alpha_card_intraday{animation-delay:.12s}
.st-key-alpha_card_beta{animation-delay:.18s}.st-key-alpha_card_sr{animation-delay:.24s}
.st-key-alpha_card_options{animation-delay:.3s}.st-key-alpha_card_premarket{animation-delay:.36s}
[class*="st-key-alpha_card_"] .stButton button{transition:transform .2s ease}
[class*="st-key-alpha_card_"]:hover .stButton button{transform:translateX(3px)}
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

/* Motion: entrances, feedback and hero ambience */
[data-testid="stMainBlockContainer"] h1{animation:alpha-rise .55s cubic-bezier(.2,.7,.2,1) both}
.alpha-badges,.alpha-runbar,[class*="st-key-premarket_card_"]{animation:alpha-rise .5s ease both}
[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"]{transition:transform .2s ease,box-shadow .2s ease}
[data-testid="stBaseButton-primary"]:hover,[data-testid="stBaseButton-primaryFormSubmit"]:hover{transform:translateY(-1px);
  box-shadow:0 8px 22px -10px rgba(11,110,117,.75)}
.alpha-logo{transition:transform .4s cubic-bezier(.2,.7,.2,1)}
.alpha-brand:hover .alpha-logo{transform:rotate(-6deg) scale(1.06)}
@keyframes alpha-rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
@keyframes alpha-fade{to{opacity:1}}
@keyframes alpha-aurora{0%{transform:translate3d(0,0,0) rotate(0)}50%{transform:translate3d(4%,-3%,0) rotate(8deg)}100%{transform:translate3d(-4%,3%,0) rotate(-6deg)}}
@keyframes alpha-ping{0%{box-shadow:0 0 0 0 rgba(45,212,191,.6)}80%,100%{box-shadow:0 0 0 .55rem rgba(45,212,191,0)}}
@keyframes alpha-draw{to{stroke-dashoffset:0}}
@keyframes alpha-pop{from{transform:scale(0)}to{transform:scale(1)}}
@keyframes alpha-grow{from{transform:scaleY(0);opacity:0}to{transform:scaleY(1);opacity:1}}
@keyframes alpha-scan{0%{transform:translateX(0);opacity:0}8%{opacity:1}92%{opacity:1}100%{transform:translateX(470px);opacity:0}}
@keyframes alpha-ring{0%{transform:scale(.6);opacity:.9}100%{transform:scale(2.4);opacity:0}}
@keyframes alpha-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
@keyframes alpha-count{from{--alpha-n:0}to{--alpha-n:var(--alpha-to)}}
@media (prefers-reduced-motion:reduce){
  .st-key-alpha_hero::before,.alpha-live,.alpha-float,.alpha-art .scan,.alpha-art .ring{animation:none !important}
  [class*="st-key-alpha_"],[class*="st-key-alpha_"] *,[data-testid="stMainBlockContainer"] h1,.alpha-badges,.alpha-runbar,
  [class*="st-key-premarket_card_"],.alpha-count,.alpha-art *,.alpha-logo *{animation-duration:.001s !important;animation-delay:0s !important;
  animation-iteration-count:1 !important;transition:none !important}
  .alpha-art .line{stroke-dashoffset:0}}
</style>
"""


def inject_styles() -> None:
    st.html(_CSS)


def badges_html(items) -> str:
    return "<div class='alpha-badges'>" + "".join(
        f"<span class='alpha-badge {escape(kind)}'>{escape(text)}</span>" for kind, text in items) + "</div>"


def badges(items) -> None:
    st.markdown(badges_html(items), unsafe_allow_html=True)


# Decorative, deterministic shapes only: not market data and not a backtest.
_ART_LINE = (230, 224, 228, 214, 206, 212, 198, 190, 196, 182, 170, 176, 188, 180, 164,
             152, 158, 142, 134, 140, 124, 112, 118, 100, 88)
_ART_BENCH = (232, 229, 227, 224, 222, 219, 218, 214, 213, 210, 206, 205, 203, 200, 197,
              195, 192, 190, 186, 184, 181, 178, 176, 172, 170)
_ART_BARS = (18, 26, 14, 30, 22, 16, 34, 20, 12, 28, 38, 24, 30, 18, 26, 40, 22, 16, 32, 20, 28, 36, 18, 24, 30)


def _hero_art(tr) -> str:
    xs = [30 + i * 19.5 for i in range(len(_ART_LINE))]
    line = " ".join(f"{x:.1f},{y}" for x, y in zip(xs, _ART_LINE))
    bench = " ".join(f"{x:.1f},{y}" for x, y in zip(xs, _ART_BENCH))
    area = f"{xs[0]:.1f},270 " + line + f" {xs[-1]:.1f},270"
    bars = "".join(f"<rect class='bar' x='{x - 5:.1f}' y='{290 - h}' width='10' height='{h}' rx='2' "
                   f"style='animation-delay:{0.15 + i * 0.04:.2f}s'/>" for i, (x, h) in enumerate(zip(xs, _ART_BARS)))
    grid = "".join(f"<line x1='20' x2='510' y1='{y}' y2='{y}'/>" for y in (60, 110, 160, 210, 260))
    end_x, end_y = xs[-1], _ART_LINE[-1]
    svg = (
        "<svg class='alpha-art' viewBox='0 0 530 300' role='img' aria-hidden='true' focusable='false'>"
        "<defs><linearGradient id='alphaLine' x1='0' x2='1'><stop offset='0' stop-color='#2DD4BF'/>"
        "<stop offset='.6' stop-color='#60A5FA'/><stop offset='1' stop-color='#A78BFA'/></linearGradient>"
        "<linearGradient id='alphaArea' x1='0' x2='0' y1='0' y2='1'><stop offset='0' stop-color='rgba(45,212,191,.35)'/>"
        "<stop offset='1' stop-color='rgba(45,212,191,0)'/></linearGradient></defs>"
        f"<g class='grid'>{grid}</g>{bars}"
        f"<polyline class='bench' points='{bench}'/>"
        f"<polygon class='area' points='{area}'/>"
        f"<polyline class='line' points='{line}'/>"
        f"<line class='scan' x1='30' x2='30' y1='40' y2='290'/>"
        f"<circle class='ring' cx='{end_x:.1f}' cy='{end_y}' r='7'/>"
        f"<circle class='dot' cx='{end_x:.1f}' cy='{end_y}' r='5'/>"
        "</svg>")
    return ("<div class='alpha-art-wrap'>" + svg
            + f"<span class='alpha-float a'>▶ {escape(tr('只在点击运行后计算', 'Computes only on Run'))}</span>"
            + f"<span class='alpha-float b'>● {escape(tr('来源逐项标注', 'Every source labeled'))}</span>"
            + f"<div class='alpha-art-note'>{escape(tr('示意图 · 非市场数据或回测结果', 'Illustration · not market data or a backtest'))}</div>"
            + "</div>")


def hero(tr, title: str) -> None:
    """Landing hero; ``st.title`` stays a native heading for navigation and tests."""
    with st.container(key="alpha_hero"):
        text, art = st.columns([7, 5], vertical_alignment="center", gap="large")
        with text:
            st.markdown("<div class='alpha-eyebrow'><span class='alpha-live'></span>"
                        + escape(tr("量化研究工作台 · 冻结与标注数据", "Quantitative research workbench · frozen & labeled data"))
                        + "</div>", unsafe_allow_html=True)
            st.title(title)
            st.markdown("<div class='alpha-lede'>" + escape(tr(
                "七个独立研究专题：日频 AI Alpha、日频与 5 分钟动量／趋势、Beta、支撑／阻力、期权结构，以及盘前涨幅后的开盘下探。每个专题都标明数据来源、样本与限制；只有点击运行才会计算。",
                "Seven independent studies: daily AI alpha, daily and 5-minute momentum and trend, Beta, support and resistance, options structure, and opening downside after premarket gains. Every study labels its data source, sample and limits, and computes only when you click Run."))
                + "</div>", unsafe_allow_html=True)
            stats = ((7, tr("个研究专题", "research studies")),
                     (250, tr("个冻结盘前交易日", "frozen premarket sessions")),
                     (0, tr("个券商连接", "brokerage connections")))
            st.markdown("<div class='alpha-hero-stats'>" + "".join(
                f"<div><b class='alpha-count n{value}' aria-hidden='true'></b><span class='alpha-sr'>{value}</span>"
                f"<span>{escape(label)}</span></div>" for value, label in stats) + "</div>", unsafe_allow_html=True)
            badges([("real", tr("真实历史与冻结派生数据", "Real history & frozen derived data")),
                    ("visitor", tr("访客 CSV 云端临时处理", "Visitor CSV, processed temporarily in the cloud")),
                    ("teaching", tr("合成／TOY 教学明确标记", "Synthetic / TOY teaching clearly labeled")),
                    ("info", tr("不连接券商 · 不下单 · 非实盘业绩", "No brokerage · no orders · not live performance"))])
        with art, st.container(key="alpha_hero_art"):
            st.markdown(_hero_art(tr), unsafe_allow_html=True)


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


# Brand mark: rising volume bars under an equity line ending in a live point. Decorative only.
_LOGO = (
    "<svg class='alpha-logo' viewBox='0 0 40 40' aria-hidden='true' focusable='false'>"
    "<defs><linearGradient id='alphaLogoBg' x1='0' y1='0' x2='1' y2='1'>"
    "<stop offset='0' stop-color='#0B2545'/><stop offset='1' stop-color='#0B6E75'/></linearGradient>"
    "<linearGradient id='alphaLogoLine' x1='0' x2='1'>"
    "<stop offset='0' stop-color='#2DD4BF'/><stop offset='1' stop-color='#CCFBF1'/></linearGradient></defs>"
    "<rect width='40' height='40' rx='11' fill='url(#alphaLogoBg)'/>"
    "<rect x='8.5' y='25' width='4' height='7' rx='1.2' fill='#fff' opacity='.26'/>"
    "<rect x='15.5' y='21' width='4' height='11' rx='1.2' fill='#fff' opacity='.34'/>"
    "<rect x='22.5' y='23' width='4' height='9' rx='1.2' fill='#fff' opacity='.3'/>"
    "<rect x='29.5' y='17' width='4' height='15' rx='1.2' fill='#fff' opacity='.42'/>"
    "<polyline class='alpha-logo-line' points='8,22 16,15.5 23,18.5 31.5,9.5' fill='none' "
    "stroke='url(#alphaLogoLine)' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>"
    "<circle class='alpha-logo-dot' cx='31.5' cy='9.5' r='2.8' fill='#F0FDFA'/>"
    "</svg>")


# Day / night switch. Streamlit has no Python API to change the viewer's theme, so the
# button drives the built-in main-menu theme items (stMainMenuItem-theme-Light/Dark):
# the change is applied in place without a rerun, so reports and session_state stay,
# and Streamlit itself remembers the choice in the browser. If the menu is missing the
# click does nothing; it never reloads the page. st.html strips inline SVG, so the
# script inserts the icons.
_THEME_ICONS = (
    "<svg class='alpha-ico-moon' viewBox='0 0 24 24' aria-hidden='true'><path d='M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7Z'/></svg>"
    "<svg class='alpha-ico-sun' viewBox='0 0 24 24' aria-hidden='true'><circle cx='12' cy='12' r='4.2'/>"
    "<path d='M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6'/></svg>")
_THEME_JS = """
<script>
(() => {
  const doc = document;
  const mode = () => {
    const app = doc.querySelector('.stApp');
    return app && getComputedStyle(app).colorScheme.includes('dark') ? 'dark' : 'light';
  };
  const sync = () => doc.querySelectorAll('.alpha-theme-toggle').forEach(b => {
    if (!b.querySelector('svg')) b.innerHTML = `__ICONS__`;
    const m = mode();
    b.dataset.mode = m;
    const label = m === 'dark' ? b.dataset.toLight : b.dataset.toDark;
    b.setAttribute('aria-label', label); b.title = label;
  });
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const find = async (sel, tries = 20) => {
    for (let i = 0; i < tries; i++) { const el = doc.querySelector(sel); if (el) return el; await wait(25); }
    return null;
  };
  const toggle = async () => {
    const target = mode() === 'dark' ? 'Light' : 'Dark';
    const menu = doc.querySelector('[data-testid="stMainMenu"] button');
    if (!menu) { console.warn('alpha theme: main menu unavailable'); return; }
    doc.documentElement.classList.add('alpha-theme-switching');
    try {
      menu.click();
      const item = await find(`[data-testid="stMainMenuItem-theme-${target}"]`);
      if (item) item.click(); else console.warn('alpha theme: theme item unavailable');
      await wait(60);
      if (doc.querySelector('[data-testid="stMainMenuList"]')) menu.click();
    } finally {
      await wait(60);
      doc.documentElement.classList.remove('alpha-theme-switching');
      sync();
    }
  };
  if (!window.__alphaThemeInit) {
    window.__alphaThemeInit = true;
    doc.addEventListener('click', e => {
      const b = e.target.closest && e.target.closest('.alpha-theme-toggle');
      if (b) { e.preventDefault(); toggle(); }
    });
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => setTimeout(sync, 100));
    doc.addEventListener('click', e => {
      if (e.target.closest && e.target.closest('[data-testid^="stMainMenuItem-theme-"]')) setTimeout(sync, 100);
    }, true);
  }
  sync(); setTimeout(sync, 300);
})();
</script>
"""


def theme_toggle(tr) -> None:
    to_dark = escape(tr("切换到夜间模式", "Switch to night mode"), quote=True)
    to_light = escape(tr("切换到日间模式", "Switch to day mode"), quote=True)
    st.html(f"<button type='button' class='alpha-theme-toggle' data-to-dark='{to_dark}' "
            f"data-to-light='{to_light}' aria-label='{to_dark}' title='{to_dark}'></button>"
            + _THEME_JS.replace("__ICONS__", _THEME_ICONS.replace("<", "\\x3C")),
            unsafe_allow_javascript=True, width="content")


def header(tr, on_language_change) -> None:
    with st.container(key="alpha_header"):
        brand, controls = st.columns([5, 6], vertical_alignment="center")
        with brand:
            st.markdown(
                "<div class='alpha-brand'>" + _LOGO + "<div>"
                "<div class='alpha-wordmark'>Alpha Trading <span>Lab</span></div>"
                f"<div class='alpha-tagline'>{escape(tr('量化研究工作台 · 七个研究专题 · 仅研究与模拟，不连接券商', 'Quant research workbench · seven studies · research and simulation only, no brokerage'))}</div>"
                "</div></div>", unsafe_allow_html=True)
        with controls, st.container(horizontal=True, horizontal_alignment="right",
                                    vertical_alignment="center", gap="small", key="alpha_header_controls"):
            st.radio("Language / 语言", ("English", "中文"), key="hf_language", horizontal=True,
                     on_change=on_language_change, label_visibility="collapsed", width="content")
            theme_toggle(tr)
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
