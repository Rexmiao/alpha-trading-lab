"""Render a bilingual or English-only illustrative AI-alpha teaching animation.

This renderer uses only hard-coded educational drawings. It never reads project
data, runs, config, credentials, account information, or brokerage interfaces.

Rebuild: python scripts/export_training_gif.py
Optional: python scripts/export_training_gif.py --output-dir path/to/media
English: python scripts/export_training_gif.py --language en
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle, Wedge
import numpy as np
from PIL import Image


WIDTH, HEIGHT = 1200, 600
COLORS = {"background": "#F3F6FA", "paper": "#FFFFFF", "ink": "#172D47",
          "muted": "#61738B", "line": "#D9E2EC", "teal": "#087F8C",
          "aqua": "#29B4B8", "mint": "#E4F4F3", "gold": "#C88A22",
          "pale_gold": "#FFF4D9", "slate": "#95A8BE", "red": "#C46868"}
STAGES = [
    ("日 K 数据", "Daily bars", "完成的交易日", "Completed sessions",
     "每根 K 线只代表已完成的交易日", "Use completed sessions only.",
     "保留来源、复权口径和时间戳", "Keep source, adjustments and timestamps.",
     "完整日 K / Completed daily bars"),
    ("历史特征", "Past-only features", "信号日可见信息", "Known at the signal time",
     "输入仅用信号时点已知的信息", "Build inputs from information available by T.",
     "标准化参数只在训练期拟合", "Fit preprocessing on the training period only.",
     "历史可见 / Past-only inputs"),
    ("历史监督训练", "Historical supervision", "输入与历史答案", "Past inputs and historical answers",
     "未来答案只用于历史样本训练", "Future labels teach historical examples only.",
     "按时间切分，剔除跨界标签", "Split by time; purge labels crossing boundaries.",
     "禁止未来泄漏 / No look-ahead"),
    ("DL 与生成式 AI", "DL + conditional GenAI", "条件生成与预测", "Conditional generation and prediction",
     "同一条件 X 配套生成标签 y", "Pair each generated label with its condition X.",
     "与真实数据训练做同预算对照", "Compare predictors under matched budgets.",
     "合成不等于新事实 / Synthetic is not new evidence"),
    ("未见期检验", "Held-out evaluation", "真实数据留出检验", "Evaluate on real unseen observations",
     "先看真实未见期的预测排序", "Measure ranking ability on the held-out period.",
     "再看成本、回撤及跨时窗稳定性", "Then inspect costs, drawdown and other windows.",
     "训练损失不等于 alpha / Train loss is not alpha"),
    ("因子到仓位草稿", "Factor to draft weights", "受约束的模拟仓位", "Constrained, simulated target weights",
     "成本和风险约束后形成草稿", "Apply cost gates and risk limits before a draft.",
     "先有可检验的预测，再做决策", "Connect testable forecasts to decisions.",
     "仅草稿 / Draft only · No submission"),
]


# Every visible text item passes through this table in English mode. An unmapped
# Chinese label is an error, rather than leaking mixed languages into an image.
ENGLISH_LABELS = {
    "AI Alpha 研究：从日 K 到未见期检验": "AI Alpha: From Daily Bars to Unseen Tests",
    "教学示意 / Illustrative only": "Illustrative only",
    "日 K 数据": "Daily data",
    "历史特征": "Features",
    "历史监督训练": "Train on history",
    "DL 与生成式 AI": "DL + GenAI",
    "未见期检验": "Unseen tests",
    "因子到仓位草稿": "Draft weights",
    "完成的交易日": "Completed sessions",
    "信号日可见信息": "Known at signal time",
    "输入与历史答案": "Inputs and past answers",
    "条件生成与预测": "Generation and prediction",
    "真实数据留出检验": "Real held-out checks",
    "受约束的模拟仓位": "Constrained target weights",
    "每根 K 线只代表已完成的交易日": "Use completed trading sessions",
    "保留来源、复权口径和时间戳": "Keep data lineage and timestamps",
    "输入仅用信号时点已知的信息": "Use information known at signal time",
    "标准化参数只在训练期拟合": "Fit preprocessing on training data",
    "未来答案只用于历史样本训练": "Use labels for historical training only",
    "按时间切分，剔除跨界标签": "Split by time and purge crossing labels",
    "同一条件 X 配套生成标签 y": "Pair generated labels with condition X",
    "与真实数据训练做同预算对照": "Match the predictor training budgets",
    "先看真实未见期的预测排序": "Check rankings on unseen observations",
    "再看成本、回撤及跨时窗稳定性": "Inspect costs, risk and other windows",
    "成本和风险约束后形成草稿": "Apply cost gates and risk limits",
    "先有可检验的预测，再做决策": "Test forecasts before making decisions",
    "完整日 K / Completed daily bars": "Completed daily bars",
    "历史可见 / Past-only inputs": "Past-only inputs",
    "禁止未来泄漏 / No look-ahead": "No look-ahead",
    "合成不等于新事实 / Synthetic is not new evidence": "Synthetic data is not new evidence",
    "训练损失不等于 alpha / Train loss is not alpha": "Train loss is not alpha",
    "仅草稿 / Draft only · No submission": "Draft only · No submission",
    "教学图形与配置示例 · 未使用真实行情、账户、订单或回测表现":
        "Conceptual workflow and toy allocation only.",
    "日 K 序列 / Daily bars (toy)": "Toy daily candlesticks",
    "时间 / Time →     仅示例形状，不代表任何证券":
        "Time →   Toy shapes only; no security represented.",
    "信号日 T 的历史特征 / Features known by T": "Past-only features at signal time T",
    "过去收益": "Past return",
    "动量": "Momentum",
    "波动": "Volatility",
    "量比": "Volume ratio",
    "示例矩阵 / Toy feature matrix": "Toy feature matrix",
    "输入与答案分开 / Inputs and labels are separate": "Separate inputs from labels",
    "历史输入 X / Past inputs": "Past inputs X",
    "未来答案 y / Future label": "Future label y",
    "信号时点 / Signal time": "Signal time",
    "答案在历史训练时已发生，预测时尚不可见。":
        "Historical labels are known during training, not prediction.",
    "GenAI 增强训练 / GenAI augments training": "GenAI augments training",
    "条件 X": "Condition X",
    "条件 DDPM": "Conditional DDPM",
    "配套样本 (X, y)": "Paired (X, y)",
    "真实训练样本": "Real samples",
    "DL 预测器": "DL predictor",
    "预测分数": "Forecast score",
    "生成器只拟合训练期 / Fit the generator on training data only":
        "Fit the generator on training data only.",
    "真实留出期 / Real held-out observations": "Evaluate on real unseen observations",
    "训练": "Train",
    "验证校准": "Calibrate",
    "未见期": "Hold out",
    "排序能力": "Ranking ability",
    "成本后收益": "Net returns",
    "跨时窗稳定": "Stability",
    "Rank IC · 待测": "Rank IC · To measure",
    "Net of costs · 待测": "Net of costs · To measure",
    "Across windows · 待测": "Across windows · To measure",
    "没有预设好结果 / No performance outcome is assumed": "No favorable outcome is assumed.",
    "受约束的仓位示例 / Toy constrained allocation": "Toy constrained allocation",
    "示例": "Example",
    "示例 A / Asset A     20%": "Asset A             20%",
    "示例 B / Asset B     20%": "Asset B             20%",
    "现金 / Cash              60%": "Cash                 60%",
    "草稿 / DRAFT": "DRAFT",
    "成本 / Costs": "Costs",
    "约束 / Limits": "Limits",
    "仅教学配比，不是模型输出 / Toy weights, not model output": "Toy weights only; not model output.",
}


def contains_chinese(text):
    return any("\u3400" <= character <= "\u9fff" or "\uf900" <= character <= "\ufaff"
               for character in text)


def localized_label(content, language):
    if language == "en":
        if contains_chinese(content):
            if content not in ENGLISH_LABELS:
                raise ValueError(f"Untranslated visible label: {content!r}")
            content = ENGLISH_LABELS[content]
        if contains_chinese(content):
            raise ValueError(f"Chinese text is not allowed in an English frame: {content!r}")
    elif language != "bilingual":
        raise ValueError("language must be bilingual or en")
    return content


def get_font(language="bilingual"):
    if language == "en":
        return font_manager.FontProperties(family="DejaVu Sans")
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if font_path.is_file():
        return font_manager.FontProperties(fname=str(font_path))
    for family in ("Microsoft YaHei", "Noto Sans CJK SC", "Noto Sans CJK JP"):
        try:
            path = font_manager.findfont(family, fallback_to_default=False)
            return font_manager.FontProperties(fname=path)
        except ValueError:
            continue
    raise RuntimeError("A Chinese font is required: install Microsoft YaHei or Noto Sans CJK.")


def mix(first, second, proportion):
    a = np.array(matplotlib.colors.to_rgb(first))
    b = np.array(matplotlib.colors.to_rgb(second))
    return tuple(a*(1-proportion)+b*proportion)


def render(stage, phase, font, *, overview=False, language="bilingual"):
    fig = plt.figure(figsize=(12, 6), dpi=100, facecolor=COLORS["background"])
    ax = fig.add_axes([0, 0, 1, 1], xlim=(0, WIDTH), ylim=(0, HEIGHT))
    ax.set_axis_off()
    texts = []

    def text(x, y, content, size=12, color=None, ha="left", va="center", **kwargs):
        content = localized_label(content, language)
        item = ax.text(x, y, content, fontsize=size, fontproperties=font,
                       color=color or COLORS["ink"], ha=ha, va=va, **kwargs)
        texts.append(item)
        return item

    def box(x, y, w, h, fill=None, edge=None, lw=1, radius=12):
        patch = FancyBboxPatch((x,y), w,h, boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=fill or COLORS["paper"], edgecolor=edge or COLORS["line"], linewidth=lw)
        ax.add_patch(patch)
        return patch

    def arrow(start, end, color=None, lw=1.7, mutation_scale=12):
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=mutation_scale,
                                    linewidth=lw, color=color or COLORS["slate"]))

    text(32, 563, "AI Alpha 研究：从日 K 到未见期检验", 23)
    text(33, 529, "Daily bars → historical learning → real held-out checks → draft weights", 11.5,
         COLORS["muted"])
    box(878, 543, 290, 42, COLORS["paper"], COLORS["teal"])
    text(1023, 564, "教学示意 / Illustrative only", 13, COLORS["teal"], ha="center")

    for i, (cn, en, *_rest) in enumerate(STAGES):
        x, y, w, h = 32+192*i, 399, 176, 98
        active = i == stage
        completed = overview or i < stage
        edge = COLORS["teal"] if active or completed else COLORS["line"]
        fill = COLORS["mint"] if active else COLORS["paper"]
        if active:
            edge = mix(COLORS["teal"], COLORS["aqua"], .35*(1+np.sin(phase*2*np.pi)))
        box(x,y,w,h,fill,edge,2 if active else 1)
        ax.add_patch(Circle((x+20,y+75), 11,
                            color=COLORS["teal"] if active or completed else COLORS["slate"]))
        text(x+20,y+75,str(i+1),10,"white",ha="center")
        text(x+17,y+46,cn,12.3)
        text(x+17,y+22,en,9.1,COLORS["muted"])
        if i < 5:
            arrow((x+w+1,y+49),(x+191,y+49),
                  COLORS["teal"] if i < stage or overview else COLORS["line"], mutation_scale=9)

    ax.plot([32,1168],[383,383],color=COLORS["line"],lw=2)
    progress = 1168 if overview else 32+1136*(stage+phase)/6
    ax.plot([32,progress],[383,383],color=COLORS["aqua"],lw=3)
    ax.add_patch(Circle((progress,383),4,color=COLORS["teal"]))
    box(32,86,1136,282)
    ax.plot([731,731],[111,345],color=COLORS["line"],lw=1)
    _,_,heading,subheading,first_cn,first_en,second_cn,second_en,rule = STAGES[stage]
    text(758,335,heading,17)
    text(758,307,subheading,10.2,COLORS["muted"])
    for y, cn, en in ((258,first_cn,first_en),(195,second_cn,second_en)):
        ax.add_patch(Circle((763,y),3,color=COLORS["teal"]))
        text(777,y,cn,12.2)
        text(777,y-24,en,8.9,COLORS["muted"])
    box(754,106,397,39,COLORS["mint"],COLORS["mint"],radius=8)
    # Long bilingual rule labels are intentionally smaller than body text.
    text(952,126,rule,10.3,COLORS["teal"],ha="center")
    text(32,55,"教学图形与配置示例 · 未使用真实行情、账户、订单或回测表现",10.5,COLORS["muted"])
    text(32,31,"Illustrative only. No real market data, accounts, orders, or performance results.",9.3,
         COLORS["muted"])
    text(1168,31,f"{stage+1} / 6",10.5,COLORS["teal"],ha="right")

    if stage == 0:
        text(86,329,"日 K 序列 / Daily bars (toy)",14)
        ax.plot([90,675],[132,132],color=COLORS["line"])
        for y in (170,210,250,290):
            ax.plot([90,675],[y,y],color=COLORS["background"],lw=1)
        # Hard-coded mathematical shapes: no market observations are loaded.
        for i in range(15):
            opening = 212+29*np.sin(i*.64)
            closing = opening+14*np.sin(i*1.31+.4)
            high, low = max(opening,closing)+11, min(opening,closing)-10
            x = 108+i*37
            color = COLORS["teal"] if closing>=opening else COLORS["red"]
            ax.plot([x,x],[low,high],color=color,lw=1.6)
            ax.add_patch(Rectangle((x-7,min(opening,closing)),14,max(abs(closing-opening),2),
                                   facecolor=color,edgecolor=color))
        text(90,111,"时间 / Time →     仅示例形状，不代表任何证券",9.8,COLORS["muted"])
    elif stage == 1:
        text(86,329,"信号日 T 的历史特征 / Features known by T",14)
        row_labels = [("过去收益","Past return"),("动量","Momentum"),("波动","Volatility"),("量比","Volume ratio")]
        for r,(cn,en) in enumerate(row_labels):
            y = 270-r*38
            text(95,y,cn,11.5)
            text(95,y-15,en,8.5,COLORS["muted"])
            for c in range(6):
                intensity = .2+.7*(.5+.5*np.sin(r*1.6+c*.9))
                color = mix(COLORS["mint"],COLORS["teal"],intensity)
                box(242+c*71,y-18,61,29,color,color,radius=4)
        for c in range(6):
            text(272+c*71,126,"T" if c==5 else f"T−{5-c}",9,COLORS["muted"],ha="center")
        text(95,108,"示例矩阵 / Toy feature matrix",9.5,COLORS["muted"])
    elif stage == 2:
        text(86,329,"输入与答案分开 / Inputs and labels are separate",14)
        arrow((102,225),(681,225),COLORS["slate"],lw=2)
        ax.plot([398,398],[174,294],color=COLORS["gold"],linestyle="--",lw=1.8)
        box(108,248,216,49,COLORS["mint"],COLORS["mint"])
        text(216,273,"历史输入 X / Past inputs",12,COLORS["teal"],ha="center")
        box(469,248,216,49,COLORS["pale_gold"],COLORS["pale_gold"])
        text(577,273,"未来答案 y / Future label",12,COLORS["gold"],ha="center")
        for x in (119,172,225,278,331,398):
            ax.add_patch(Circle((x,225),4,color=COLORS["teal"]))
        for x in (469,522,575,628,675):
            ax.add_patch(Circle((x,225),4,color=COLORS["gold"]))
        text(225,196,"T−L … T",12,COLORS["teal"],ha="center")
        text(577,196,"T+1 … T+h",12,COLORS["gold"],ha="center")
        text(398,159,"信号时点 / Signal time",10,COLORS["muted"],ha="center")
        text(93,119,"答案在历史训练时已发生，预测时尚不可见。",11.4)
    elif stage == 3:
        text(86,329,"GenAI 增强训练 / GenAI augments training",14)
        for x,y,w,h,cn,en in (
            (92,239,130,53,"条件 X","Condition X"),
            (280,239,177,53,"条件 DDPM","Noise → label y"),
            (514,239,168,53,"配套样本 (X, y)","Paired training sample"),
            (92,142,168,53,"真实训练样本","Real training samples"),
            (327,142,150,53,"DL 预测器","DL predictor"),
            (539,142,143,53,"预测分数","Forecast score")):
            color = COLORS["mint"] if "DDPM" in cn or "DL" in cn else COLORS["background"]
            box(x,y,w,h,color,color,radius=8)
            text(x+w/2,y+33,cn,11.3,ha="center")
            text(x+w/2,y+13,en,8.3,COLORS["muted"],ha="center")
        arrow((224,265),(276,265),COLORS["teal"])
        arrow((459,265),(510,265),COLORS["teal"])
        arrow((262,168),(323,168),COLORS["teal"])
        arrow((479,168),(535,168),COLORS["teal"])
        arrow((597,235),(447,199),COLORS["aqua"])
        text(94,116,"生成器只拟合训练期 / Fit the generator on training data only",10.2,COLORS["muted"])
    elif stage == 4:
        text(86,329,"真实留出期 / Real held-out observations",14)
        for x,cn,en,fill in ((94,"训练","Train",COLORS["mint"]),
                             (293,"验证校准","Calibrate",COLORS["background"]),
                             (492,"未见期","Hold out",COLORS["pale_gold"])):
            box(x,242,183,57,fill,fill,radius=8)
            text(x+91,278,cn,12.5,ha="center")
            text(x+91,257,en,9.3,COLORS["muted"],ha="center")
        arrow((94,225),(675,225),COLORS["slate"])
        for x,cn,en in ((94,"排序能力","Rank IC"),(293,"成本后收益","Net of costs"),(492,"跨时窗稳定","Across windows")):
            box(x,139,183,63,COLORS["paper"],COLORS["line"],radius=8)
            text(x+91,181,cn,11.5,ha="center")
            text(x+91,160,en+" · 待测",9,COLORS["muted"],ha="center")
        text(95,113,"没有预设好结果 / No performance outcome is assumed",10.2,COLORS["muted"])
    else:
        text(86,329,"受约束的仓位示例 / Toy constrained allocation",14)
        center, angle = (183,223), 90
        for fraction,color in ((.2,COLORS["aqua"]),(.2,COLORS["teal"]),(.6,COLORS["slate"])):
            ax.add_patch(Wedge(center,77,angle,angle+360*fraction,width=29,
                               facecolor=color,edgecolor="white",linewidth=2))
            angle += 360*fraction
        text(183,228,"示例",13,ha="center")
        text(183,207,"Toy",10,COLORS["muted"],ha="center")
        for y,label,color in ((275,"示例 A / Asset A     20%",COLORS["aqua"]),
                              (233,"示例 B / Asset B     20%",COLORS["teal"]),
                              (191,"现金 / Cash              60%",COLORS["slate"])):
            ax.add_patch(Circle((294,y),5,color=color))
            text(309,y,label,10.4)
        box(506,149,176,148,COLORS["background"],COLORS["line"],radius=9)
        text(594,274,"草稿 / DRAFT",12,COLORS["teal"],ha="center")
        for y,label in ((242,"成本 / Costs"),(211,"EWMA / Risk"),(180,"约束 / Limits")):
            text(526,y,label,10.2,COLORS["muted"])
        text(96,112,"仅教学配比，不是模型输出 / Toy weights, not model output",10.2,COLORS["muted"])

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for item in texts:
        bounds = item.get_window_extent(renderer)
        if bounds.x0 < -1 or bounds.y0 < -1 or bounds.x1 > WIDTH+1 or bounds.y1 > HEIGHT+1:
            plt.close(fig)
            raise RuntimeError(f"Text outside canvas: {item.get_text()!r}, {bounds.bounds}")
    frame = Image.fromarray(np.asarray(fig.canvas.buffer_rgba())).convert("RGB")
    plt.close(fig)
    return frame


def export(output_dir, *, language="bilingual"):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    font = get_font(language)
    frames = [render(stage, index/8, font, language=language) for stage in range(6) for index in range(8)]
    poster = render(5,.99,font,overview=True,language=language)
    poster_path = output_dir / "poster.png"
    poster.save(poster_path, optimize=True)
    # One palette drawn from all six stages avoids per-frame color flicker.
    palette_sheet = Image.new("RGB", (900,300), COLORS["background"])
    for i in range(6):
        thumbnail = frames[i*8].resize((300,150),Image.Resampling.LANCZOS)
        palette_sheet.paste(thumbnail,((i%3)*300,(i//3)*150))
    palette = palette_sheet.quantize(colors=128,method=Image.Quantize.MEDIANCUT)
    encoded = [frame.quantize(palette=palette,dither=Image.Dither.NONE) for frame in frames]
    durations = [160 if i%8<6 else 450 for i in range(len(encoded))]
    gif_path = output_dir / "alpha-training-flow.gif"
    encoded[0].save(gif_path,save_all=True,append_images=encoded[1:],loop=0,
                    duration=durations,optimize=True,disposal=1)
    with Image.open(gif_path) as check:
        dimensions, count, loop = check.size, check.n_frames, check.info.get("loop")
        total_duration = 0
        has_transparency = False
        for i in range(count):
            check.seek(i)
            total_duration += check.info.get("duration",0)
            has_transparency |= "transparency" in check.info
        if dimensions != (WIDTH,HEIGHT) or not 1 < count <= 60 or loop != 0 or has_transparency:
            raise RuntimeError("GIF verification failed")
    with Image.open(poster_path) as check:
        if check.size != (WIDTH,HEIGHT) or check.mode != "RGB":
            raise RuntimeError("Poster verification failed")
    result = {"gif":str(gif_path.resolve()),"poster":str(poster_path.resolve()),
              "language":language,
              "width":WIDTH,"height":HEIGHT,"frames":count,"loop":loop,
              "duration_seconds":total_duration/1000,"transparent":has_transparency,
              "gif_bytes":gif_path.stat().st_size,"poster_bytes":poster_path.stat().st_size,
              "content":"Teaching illustration only; no project data, results or user information read."}
    if result["gif_bytes"]>=4*1024*1024:
        raise RuntimeError(f"GIF exceeds the 4 MiB target: {result['gif_bytes']} bytes")
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path)
    parser.add_argument("--language",choices=("bilingual","en"),default="bilingual")
    args=parser.parse_args(argv)
    output_dir=args.output_dir or Path(__file__).resolve().parents[1]/"docs"/"media"
    if args.output_dir is None and args.language=="en":
        output_dir=output_dir/"en"
    print(json.dumps(export(output_dir,language=args.language),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
