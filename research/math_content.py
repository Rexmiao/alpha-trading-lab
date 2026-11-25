"""Bilingual mathematical notes aligned with the implemented pipeline."""
from __future__ import annotations
from typing import Any
import streamlit as st


def _render_training_flow(config: dict[str, Any], lang: str) -> None:
    """Teach the real pipeline without treating a backtest as evidence of an edge."""
    en = lang == "en"
    lookback = int(config.get("lookback", 30))

    def t(zh: str, english: str) -> str:
        return english if en else zh

    def say(zh: str, english: str) -> None:
        st.write(t(zh, english))

    st.subheader(t("先看全程：模型是怎样学会预测的", "The complete process: how a model learns to forecast"))
    st.markdown(t("**moomoo完整日K → 历史特征X → 后来实现的答案y → 按时间分组训练 → 冻结模型 → 未见期检验 → 风险与成本约束 → 模拟订单草稿**", "**Completed moomoo daily bars → historical features X → later realized answers y → chronological training → frozen model → unseen-period evaluation → risk and cost constraints → simulated order drafts**"))
    say("训练是调整模型参数，回测是重演一套已经确定的交易规则，决策是在今天已知的信息下计算下一步。三者回答不同问题，不应把一条历史净值曲线当作模型已经学会盈利的证明。", "Training adjusts model parameters. Backtesting replays an already specified trading process. Decision-making calculates the next action from information available today. They answer different questions; a historical equity curve does not establish that a model has learned to profit.")

    st.markdown(t("**1 每只股票的每一天，先形成一份历史信息**", "**1 Start with one historical information set per stock and date**"))
    say("数据继续来自moomoo日K：开盘、最高、最低、收盘和成交量。只使用已完成交易日；先检查重复、缺失、不合法价格、复权与公司行动，再对齐SPY交易日。半导体、存储和新云股票都可以进入研究股票池；股票池决定研究范围，不等于你的实际持仓。同行业股票通常相关，增加股票数量也不等于增加同样多的独立市场经历。", "Data continue to come from moomoo daily OHLCV bars. Use completed sessions only; check duplicates, gaps, invalid prices, adjustments and corporate actions, then align dates with SPY. Semiconductor, memory/storage and emerging-cloud stocks can enter the research universe. A research universe is not your actual holdings. Sector names can be highly correlated, so more stocks do not imply as many independent market experiences.")

    st.markdown(t("**2 把历史行情变成模型能读的数字X**", "**2 Convert market history into numerical inputs X**"))
    say(f"默认30日回看得到41个历史特征；当前lookback={lookback}时为{lookback + 11}个：{lookback}个滞后日收益、5/10/20日动量共3个、对应波动共3个，再加当日开收盘收益、高低价幅度、20日相对成交量、SPY当日收益和5日相对SPY动量共5个。它们都能在信号日收盘后计算，不包含未来答案。", f"The default 30-session lookback gives 41 historical features; the current lookback of {lookback} gives {lookback + 11}: {lookback} lagged daily returns, three momentum measures over 5/10/20 sessions, three corresponding volatility measures, plus five others: intraday return, high/low range, volume relative to its 20-day average, SPY's daily return and five-session momentum relative to SPY. All are available after the signal day's close; none contains the future answer.")
    st.caption(t("一个训练样本是一只股票在一个信号日的X及其后来实现的y，不是把整张未来走势图交给模型。标准化参数也只在训练期拟合。", "One training example is a stock's X on one signal date and its later realized y, not an entire future chart. Fit scaling parameters on training data only."))

    st.markdown(t("**3 历史训练可以有答案，真实预测时没有答案**", "**3 Historical training can have answers; a new forecast cannot**"))
    st.info(t("教学假设：下面的数字只用于解释，既不是moomoo真实行情，也不是当前模型的预测或回测成绩。持有期在例子中固定为5个交易日。", "Teaching assumptions: the numbers below are illustrative, not real moomoo observations or current forecasts or backtest results. These examples use a fixed five-session holding period."))
    say("假设信号日是t：股票A在t+1开盘为100，t+6开盘为103，五日收益为3%；SPY同区间收益为1%，所以答案y=3%−1%=2%。在历史研究中，这些日子已经过去，我们可以把当时的X与后来2%的答案配对，让模型学习。", "Suppose t is the signal date: stock A opens at 100 on t+1 and 103 on t+6, giving a five-session return of 3%. SPY returns 1% over the same interval, so the answer is y=3%−1%=2%. In historical research these dates have passed, so we can pair the information known at t with the later 2% answer for learning.")
    say("但如果今天就是t，t+6的103还不存在于已知信息里。程序只能输入今天的历史特征并输出预测；必须等持有期结束，才知道真实答案并评价这次预测。后来知道答案并不等于当时允许偷看答案。", "If today is t, the price of 103 at t+6 is not yet known. The program can only use today's historical features to produce a forecast. It must wait until the holding period ends to observe the answer and evaluate that forecast. Knowing the answer later does not make it available earlier.")

    st.markdown(t("**4 训练、验证和测试，按时间隔开**", "**4 Separate training, validation and test periods chronologically**"))
    say("教学假设：第1–600日用于训练，第601–700日用于验证，第701–800日用于测试。信号日在训练期还不够：例如第600日的五日标签要到第606日才结束，已经跨入验证期，必须从训练样本中剔除。验证标签同样不能跨入测试。具体运行的日期以数据追溯记录为准。", "Teaching assumption: sessions 1–600 are training, 601–700 validation and 701–800 test. A training-period signal date alone is insufficient: session 600's five-session label ends at session 606, inside validation, so remove that example from training. Likewise, validation labels cannot cross into test. Consult the saved lineage for the actual run's dates.")
    say("训练集用来更新网络和生成器；验证集检查设定、选择训练检查点，独立论文机制实验还用它校准收益单位；测试集留到最后检查。不能看完测试结果反复改规则，再把同一段测试称为从未见过。", "Training data update the networks and generator. Validation data check settings and select checkpoints; the separate paper-mechanism study also calibrates return units there. Reserve test data for the final check. After repeatedly changing rules based on test results, that same period is no longer unseen.")

    st.markdown(t("**5 MLP先猜一次，再根据误差调整参数**", "**5 An MLP makes a forecast, measures its error and updates parameters**"))
    say("MLP把X送过两层隐藏单元，得到预测相对收益。教学假设：真实答案是2%，第一次只猜0.5%，误差为−1.5个百分点，原始收益尺度下的单样本平方误差为(0.005−0.02)²=0.000225。这是教学数值，实际训练先标准化标签，不能与训练日志的loss直接相比较。", "The MLP passes X through two hidden layers to predict excess return. Teaching assumption: the answer is 2%, but the first forecast is 0.5%, an error of −1.5 percentage points. The single-example squared error in original return units is (0.005−0.02)²=0.000225. Actual training standardizes targets, so this example is not directly comparable with logged training loss.")
    st.latex(r"\text{predict }\hat y=f_\theta(X)\quad\longrightarrow\quad\text{measure loss}\quad\longrightarrow\quad\theta\leftarrow\theta-\eta\nabla_\theta\mathcal L")
    say("θ是模型内部的权重，梯度告诉它怎样调整才能减小训练误差，η控制步幅。上式只表示最简单的更新方向；当前实现用Adam调整更新。重复多个小批量和轮次后，模型可能学到关系，也可能只记住噪声，所以训练误差降低仍需要未见期检验。", "θ denotes network weights, gradients indicate adjustments that reduce training error, and η controls step size. The formula shows a basic update direction; the implementation uses Adam. Repeating batches and epochs may learn a relationship or merely memorize noise, so lower training error still needs unseen-period evaluation.")

    st.markdown(t("**6 GenAI只在训练期补充条件样本**", "**6 GenAI adds conditional samples inside the training period only**"))
    say("条件DDPM学习训练期的p(y|X)：给定一份真实训练X，生成与这个条件配套的可能收益标签，再用于增强MLP训练。它不是让模型提前看到测试答案，也不是把生成路径当成真实行情。普通MLP、重采样MLP和DDPM增强MLP使用相同的预测器更新预算，单独记录生成器的额外计算量。", "The conditional DDPM learns training-period p(y|X): given a real training X, it generates a possible corresponding return target for MLP augmentation. It does not reveal test answers or turn generated observations into real market data. Ordinary, resampled and DDPM-augmented MLPs have matched predictor update budgets; generator computation is recorded separately.")
    say("验证和测试仍使用真实历史标签。合成数据能改变训练方式，却不会创造独立的新市场历史；有没有帮助，要用同一段真实未见期与对照模型比较。", "Validation and test labels remain real historical outcomes. Synthetic data change the training procedure but create no independent market history. Evaluate any benefit against controls on the same genuinely unseen real period.")

    st.markdown(t("**7 冻结模型后，分别检查预测和交易过程**", "**7 Freeze the model, then evaluate predictions and the trading process separately**"))
    say("先用冻结的标准化器和模型在每个测试日预测；事后用真实答案检查排序是否对应，得到Rank IC。另一个问题是：若当时按固定规则下一开盘调仓、计算成本、持续记持仓账本，资金会怎样变化？这才是回测。回测使用后来行情来结算已经作出的决定，不允许用后来行情决定当时买什么。", "Apply frozen scalers and models to each test date, then use realized answers to evaluate rankings with Rank IC. A separate question is how capital would evolve under fixed next-open rebalancing rules, costs and a holdings ledger: that is backtesting. Later prices may settle an already-made decision, but may not determine what was bought earlier.")
    say("预测排序好不自动等于净收益好，净值上涨也可能只是市场或行业整体上涨。需要同时看对照、成本、换手、回撤和样本长度；本教学不以当前任何一组回测数字证明模型有效。", "Good rankings do not automatically imply net profits, and rising equity may reflect market or sector exposure. Examine controls, costs, turnover, drawdowns and sample length together. This lesson uses no current backtest figure as proof that a model works.")

    st.markdown(t("**8 预测经过成本门槛和风险约束，才成为草稿**", "**8 Forecasts become drafts only after cost and risk constraints**"))
    say("如果输出是无单位的原始排序分数，先在独立验证期校准为预期相对收益；再与配置的成本门槛比较。通过门槛的股票按分数入选，EWMA用截至当天的历史收益估计风险，逆波动分配预算，再受单股上限、现金下限和组合相关性风险缩放约束。EWMA控制仓位大小，不预测涨跌。", "If the output is a unitless ranking score, first calibrate it to expected excess returns on independent validation data, then apply the configured cost threshold. Rank qualifying names, estimate risk from history available that day using EWMA, allocate by inverse volatility, and apply name caps, the cash floor and portfolio covariance scaling. EWMA sizes positions; it does not predict direction.")
    say("教学假设：预测0.1%未超过0.2%的研究门槛，就不因排名靠前而买入；0.8%过门槛也只是候选，不保证交易获利。阈值是研究假设，真实成本和预测误差都可能更大。", "Teaching assumption: a 0.1% forecast fails a 0.2% research threshold even if highly ranked. A 0.8% forecast is only a candidate, not a guaranteed profitable trade. The threshold is an assumption; actual costs and forecast errors may be larger.")
    say("最后把目标权重变成整数数量。教学假设：模拟权益10,000美元、目标权重10%、参考价50美元、现仓0股、单边成本0.1%。先预留成本后，连续目标金额略低于1,000美元，向下取整为19股，不是忽略费用时的20股。实际还需检查最小交易额和现金，输出BUY草稿；参考收盘价必须重新报价。", "Finally convert weights to integer quantities. Teaching assumption: simulated equity USD 10,000, target weight 10%, reference price USD 50, zero existing shares and one-way cost 0.1%. After reserving costs, continuous target notional is just below USD 1,000, rounding down to 19 shares rather than the fee-free 20. Also check minimum trade value and cash before producing a BUY draft; the reference closing price needs a fresh quote.")
    st.info(t("此时得到的是可检查的研究决策和模拟草稿：训练负责学习，回测负责检验，今天的决策只用今天已知信息。本页面不会训练模型、读取真实持仓或提交订单。", "The output is a reviewable research decision and simulated draft: training learns, backtesting evaluates, and today's decision uses only information known today. This page does not train models, read real holdings or submit orders."))


def render_math(config: dict[str, Any] | None = None, lang: str = "zh") -> None:
    config = config or {}
    p = config.get("portfolio") or {}
    en = lang == "en"
    h = config.get("horizon", 5)

    def t(zh: str, english: str) -> str:
        return english if en else zh

    def say(zh: str, english: str) -> None:
        st.write(t(zh, english))

    st.title(t("数学原理", "Mathematics"))
    say("从预测目标到订单草稿，每个公式对应一个研究决定。", "Each formula connects a research decision to a prediction or an order draft.")
    st.info(t("DL是预测器；GenAI生成训练期的条件收益标签；RL学习动作策略，首版没有RL。本项目不是ADNN或DARL论文的精确复现。", "DL predicts returns; GenAI generates conditional training targets. RL learns an action policy and is not implemented. This project is not an exact reproduction of ADNN or DARL."))
    tabs = st.tabs([t("训练全流程", "Training walkthrough"), t("Alpha 标签", "Alpha target"), t("DL 预测", "DL prediction"), t("GenAI 条件生成", "GenAI generation"), t("EWMA 波动率", "EWMA volatility"), t("因子到仓位", "Factor to position")])

    with tabs[0]:
        _render_training_flow(config, lang)

    with tabs[1]:
        st.subheader(t("收盘形成信号，次日开盘持有", "Form signals after the close; enter at the next open"))
        say(f"默认h={h}个交易日。t收盘观察信息，t+1开盘进入，t+h+1开盘结束，与每h日的开盘调仓匹配。", f"The horizon is h={h} sessions. Observe at close t, enter at open t+1 and exit at open t+h+1, matching the h-session rebalance schedule.")
        st.latex(r"R^{(h)}_{i,t}=\frac{O_{i,t+h+1}}{O_{i,t+1}}-1,\qquad y_{i,t}=R^{(h)}_{i,t}-R^{(h)}_{SPY,t}")
        say("O是开盘价。若股票涨3%、SPY涨1%，标签y为0.02。预测的是持有期相对收益，不是下一根K线价格。", "O is the opening price. A stock return of 3% versus SPY's 1% gives y=0.02. The target is holding-period excess return, not the next candle's price.")
        st.latex(r"X_{i,t}\in\mathcal I_t,\qquad O_{i,t+h+1}\notin\mathcal I_t")
        say("输入只能使用截至t收盘可见的数据。训练标签的结束日必须在训练边界内，所有股票按共同交易日分割，不能逐行随机拆分。", "Inputs must be known by close t. Each training label must end inside the training period. Split all stocks on common trading dates, never by random rows.")
        st.subheader(t("Rank IC 是排序检验", "Rank IC evaluates ranking"))
        st.latex(r"IC_t=\operatorname{Corr}_i\left(\operatorname{rank}_i(\hat y_{i,t}),\operatorname{rank}_i(y_{i,t})\right)")
        say("同一天，在股票之间比较预测排序与实际排序。正IC不保证扣成本后赚钱；缺失或常数序列不能当作零IC。", "Compare forecast and realized rankings across stocks on each date. Positive IC does not guarantee profits after costs. Missing or constant series do not have zero IC.")
        st.latex(r"\Delta IC_t=IC_t^{DDPM+MLP}-IC_t^{control},\quad\overline{\Delta IC}=\frac1{|\mathcal D_{paired}|}\sum_{t\in\mathcal D_{paired}}\Delta IC_t")
        st.caption(t("只在共同测试日配对。相邻h日标签重叠可能产生相关性，滚动平均不是显著性检验。", "Pair common test dates only. Overlapping h-session targets can be serially dependent; rolling means are not significance tests."))

    with tabs[2]:
        st.subheader(t("标准化只拟合训练数据", "Fit scaling on training data only"))
        st.latex(r"\mu_j=\frac1{N_{tr}}\sum_{n\in tr}X_{nj},\quad \sigma_j^2=\frac1{N_{tr}}\sum_{n\in tr}(X_{nj}-\mu_j)^2,\quad Z_{nj}=\frac{X_{nj}-\mu_j}{\max(\sigma_j,\epsilon)}")
        say("特征和标签分别用训练期StandardScaler拟合，验证与测试沿用同一组参数。禁止用全历史的均值、极值或波动率处理过去。", "Separate StandardScalers for features and targets fit training data only. Apply those same parameters to validation and test data. Never transform past data with full-history means, extremes or volatility.")
        st.subheader(t("两隐藏层 MLP", "Two-hidden-layer MLP"))
        st.latex(r"h_1=\operatorname{ReLU}(W_1Z+b_1),\quad h_2=\operatorname{ReLU}(W_2h_1+b_2),\quad\hat y=\mu_y+\sigma_y(W_3h_2+b_3)")
        st.latex(r"\mathcal L=\frac1{2N}\sum_n\left(f_\theta(Z_n)-\frac{y_n-\mu_y}{\sigma_y}\right)^2+\frac{a}{2N}\sum_\ell\|W_\ell\|_F^2")
        say("默认隐藏层48、24个单元。输出还原为小数收益，再与入选阈值比较。平方误差限制预测偏差，L2限制权重过大；训练loss与原始收益尺度MSE需区分。", "Default hidden layers have 48 and 24 units. Transform predictions back to decimal returns before comparing them with the threshold. Squared error penalizes prediction errors and L2 penalizes large weights. Training loss differs from original-scale MSE.")
        say("四组实验是Ridge、普通MLP、重采样MLP、DDPM增强MLP。三组MLP保持每轮样本量、批量和更新预算一致；生成器额外预算单列。验证期选模，测试期评价。", "Compare Ridge, ordinary MLP, resampled MLP and DDPM-augmented MLP. All three predictors use matched samples per epoch, batch sizes and update budgets. Generator computation is reported separately. Select on validation data and evaluate on test data.")
        with st.expander(t("论文机制实验的平滑 IC 训练", "Smooth-IC training in the paper mechanism study")):
            say("另一个独立实验保留相同网络，把MSE换成同日股票截面的平滑IC损失。对预测和真实标签分别按当天均值、总体标准差做变换，再计算Pearson相关；不是两两股票的sigmoid排序。", "A separate experiment keeps the same network and replaces MSE with same-date cross-sectional smooth-IC loss. Transform predictions and targets separately using that day's mean and population standard deviation, then compute Pearson correlation. This is not pairwise sigmoid ranking.")
            st.latex(r"g(x_i)=\operatorname{sigmoid}\left(\frac{1.83(x_i-\bar x)}{2s_x}\right),\quad\mathcal L_{softIC}=-\frac1{|\mathcal D|}\sum_{t\in\mathcal D}\operatorname{Corr}_i(g(s_{i,t}),g(y_{i,t}))")
            say("每个完整日期等权；目标常数或不足3只股票的日期不训练。这里s是原始排序分数，没有收益单位，不能直接与0.2%的成本门槛比较。", "Give each complete date equal weight; exclude dates with constant targets or fewer than three stocks. Here s is a raw ranking score with no return units, so it cannot be compared directly with a 0.2% cost threshold.")
            st.latex(r"\hat y^{cal}_{i,t}=a+b\,s_{i,t},\qquad b\ge0")
            say("在独立验证期拟合a、b，再把校准后的收益预测交给仓位规则。若b为0，校准预测为常数，校准后IC可以为空。它只复现论文损失的一项机制，不含完整预训练、遗传搜索或剪枝。", "Fit a and b on a separate validation period, then pass calibrated return predictions to the position rules. If b is zero, forecasts are constant and calibrated IC may be undefined. This reproduces one loss mechanism, without the complete pretraining, genetic search or pruning system.")

    with tabs[3]:
        st.subheader(t("条件要与标签配对", "Keep targets paired with their conditions"))
        say("z₀是训练期标准化的收益标签。条件c由训练期X标准化、最多8维PCA及再次标准化得到。生成时保留真实训练X，仅为它生成配套标签y；不读取测试标签。", "z₀ is the training-standardized return target. Condition c uses scaled training X, PCA with at most eight components, and another scaler. Keep a real training X and generate its corresponding y without using test targets.")
        st.latex(r"z_k=\sqrt{\bar\alpha_k}z_0+\sqrt{1-\bar\alpha_k}\epsilon,\quad\epsilon\sim\mathcal N(0,I),\quad\bar\alpha_k=\prod_{s=1}^{k}(1-\beta_s)")
        say("k是扩散步，区别于市场日期t。默认32步cosine噪声日程。前向过程混入噪声，反向过程学习恢复条件收益分布。", "k is a diffusion step, not market date t. The default uses 32 steps and a cosine noise schedule. The forward process adds noise; the reverse process learns the conditional return distribution.")
        st.subheader(t("当前实现采用 v 预测", "The implementation predicts v"))
        st.latex(r"v_k=\sqrt{\bar\alpha_k}\epsilon-\sqrt{1-\bar\alpha_k}z_0,\qquad\mathcal L_v=\mathbb E\|v_k-v_\theta(z_k,k,c)\|_2^2")
        st.latex(r"\hat\epsilon=\sqrt{1-\bar\alpha_k}z_k+\sqrt{\bar\alpha_k}\hat v_k,\quad\hat z_0=\sqrt{\bar\alpha_k}z_k-\sqrt{1-\bar\alpha_k}\hat v_k")
        say("v是稳定的去噪参数化，不是交易量或波动率。由v重建干净标签，再使用DDPM高斯后验采样。", "v is a stable denoising parameterization, not volume or volatility. Reconstruct the clean target from v, then sample the DDPM Gaussian posterior.")
        st.latex(r"\tilde\mu_k=\frac{\sqrt{\bar\alpha_{k-1}}\beta_k}{1-\bar\alpha_k}\hat z_0+\frac{\sqrt{\alpha_k}(1-\bar\alpha_{k-1})}{1-\bar\alpha_k}z_k,\quad\tilde\beta_k=\frac{1-\bar\alpha_{k-1}}{1-\bar\alpha_k}\beta_k")
        st.latex(r"z_{k-1}=\tilde\mu_k+\sqrt{\tilde\beta_k}\eta,\qquad\widetilde y=\mu_y+\sigma_y\widetilde z_0")
        say("最后一步不额外加噪声。清洁标签估计按训练期界限裁剪，记录裁剪率。合成数据只参与训练，不创造新的独立市场历史；生成质量与样本外增量都需检验。", "The final step adds no new noise. Clean-target estimates are clipped to training-derived bounds and clipping rates are recorded. Synthetic data enter training only and do not create independent market history. Evaluate both generation quality and out-of-sample gains.")

    with tabs[4]:
        st.subheader(t("零基础理解 EWMA", "EWMA from first principles"))
        say("把每日涨跌变成收益r，再平方。涨3%和跌3%都产生0.03²的冲击，因此这里衡量幅度，不判断方向。近期冲击得到更高权重，旧冲击逐渐淡出。", "Convert daily moves into returns r, then square them. Both +3% and −3% produce a shock of 0.03², measuring size rather than direction. Recent shocks receive more weight and older shocks gradually fade.")
        st.latex(r"r_t=C_t/C_{t-1}-1,\qquad v_t=0.94v_{t-1}+0.06r_t^2,\qquad\sigma_t=\sqrt{v_t}")
        say("λ=0.94演示：94%旧方差＋6%今天的平方收益。旧方差0.0001、今天收益3%，得到新方差0.000148，开平方后日波动约1.22%。它不预测明天涨跌。", "With λ=0.94: 94% old variance + 6% today's squared return. An old variance of 0.0001 and today's 3% return give 0.000148; taking the square root gives about 1.22% daily volatility. This does not predict tomorrow's direction.")
        st.subheader(t("实际代码的有限窗口估计", "The finite-window estimate used in code"))
        say(f"当前λ={p.get('ewma_decay', 0.94)}，最多{p.get('risk_lookback', 60)}个历史交易日。有限窗口归一化的初始化与上面的递推例子不同。", f"Current λ={p.get('ewma_decay', 0.94)}, using at most {p.get('risk_lookback', 60)} past sessions. Normalizing a finite window differs from the illustrative recursion's initialization.")
        st.latex(r"a_j=\frac{\lambda^{n-1-j}}{\sum_{k=0}^{n-1}\lambda^k},\quad\Sigma_{ann}=252\sum_{j=0}^{n-1}a_jr_jr_j^\top,\quad\sigma_i=\sqrt{(\Sigma_{ann})_{ii}}")
        say("实现按短期均值为零使用二阶矩，不去均值；非对角项保留股票间相关性。全部数据截至信号日。", "The implementation uses a zero short-run mean second moment without demeaning; off-diagonal terms preserve cross-stock dependence. All data end at the signal date.")
        st.latex(r"\sigma_p=\sqrt{w^\top\Sigma_{ann}w}")
        st.info(t("用于position大小：预测分数决定候选，波动尺度决定仓位。波动越高，逆波动权重越低；组合风险还会统一缩放。", "Use this for position sizing: forecasts select candidates, volatility sizes them. Higher volatility implies smaller inverse-volatility weights, followed by portfolio risk scaling."))
        with st.expander(t("Lévy 跳跃不自动等于波动聚集", "Lévy jumps do not automatically imply volatility clustering")):
            say("常参数Lévy过程能表达跳跃、偏斜和厚尾，但独立平稳增量不自动产生波动聚集。随机时间变换或随机波动率可引入动态风险。首版默认EWMA，未拟合Lévy或GARCH，未来再比较GARCH。", "Constant-parameter Lévy processes can model jumps, skew and heavy tails, but independent stationary increments do not automatically generate volatility clustering. A stochastic clock or stochastic volatility adds dynamic risk. This version uses EWMA and fits neither Lévy nor GARCH; GARCH is a future comparison.")
            st.latex(r"\sigma_t^2=\omega+\alpha\epsilon_{t-1}^2+\beta\sigma_{t-1}^2")
            st.caption(t("上式为未来方向GARCH(1,1)，尚未实现。", "This is GARCH(1,1), a future direction, not implemented."))
            st.markdown(t("参考：", "References: ") + "[arch documentation](https://arch.readthedocs.io/en/latest/univariate/univariate_volatility_modeling.html) · [Carr–Geman–Madan–Yor 2002](https://doi.org/10.1086/338705)")

    with tabs[5]:
        st.subheader(t("分数先筛选，再逆波动分配", "Filter scores, then allocate by inverse volatility"))
        say(f"先要求预测收益大于τ={p.get('min_expected_excess', 0.002):.2%}，再选前{p.get('top_k', 4)}只。无合格股票、无足够历史或零波动时留现金。示例股票池尚未确认是你的持仓。", f"Require a forecast above τ={p.get('min_expected_excess', 0.002):.2%}, then select the top {p.get('top_k', 4)} names. Stay in cash if none qualify, history is insufficient or volatility is zero. The example universe is not confirmed as your holdings.")
        st.latex(r"\mathcal S=\operatorname{TopK}\{i:\hat y_i>\tau\},\quad u_i=(1-c_{min})\frac{1/\sigma_i}{\sum_{j\in\mathcal S}1/\sigma_j},\quad w_i^{cap}=\min(u_i,w_{max})")
        say("封顶后不重新分配剩余预算，剩余留现金，不重新归一化到100%。", "Do not redistribute the budget left after caps: it stays in cash. Never renormalize capped weights back to 100%.")
        st.latex(r"g=\min\left(1,\frac{\sigma_{budget}}{\sqrt{(w^{cap})^\top\Sigma_{ann}w^{cap}}}\right),\quad w_i^*=g\,w_i^{cap},\quad w_{cash}=1-\sum_iw_i^*")
        say(f"单股上限{p.get('max_weight', 0.2):.0%}、现金下限{p.get('min_cash_weight', 0.2):.0%}、年波动预算{p.get('target_annual_vol', 0.15):.0%}。风险缩放只减仓，不借款放大；波动预算不保证损失上限。", f"Name cap {p.get('max_weight', 0.2):.0%}, cash floor {p.get('min_cash_weight', 0.2):.0%}, annual volatility budget {p.get('target_annual_vol', 0.15):.0%}. Risk scaling only reduces exposure, without borrowing. A volatility budget is not a guaranteed loss limit.")
        st.subheader(t("扣费用后转成整数数量", "Convert post-fee equity into integer quantities"))
        st.latex(r"E'=E-c\sum_i|w_i^*E'-q_i^{current}P_i|,\quad q_i^{target}=\left\lfloor\frac{w_i^*E'}{P_i}\right\rfloor,\quad\Delta q_i=q_i^{target}-q_i^{current}")
        say("先解连续费用后权益，再向下取整。低于最小交易额可跳过；先卖后买，买入受现金下限约束。数量差正为BUY，负为SELL。", "Solve continuous post-fee equity first, then round quantities down. Skip trades below the minimum value; sell before buying and respect the cash floor. Positive quantity changes are BUY; negative changes are SELL.")
        st.warning(t("只有独立模拟账户草稿。参考价是完整日K收盘，requires_requote=true；不是实时报价、已提交或已成交订单。", "Independent simulated drafts only. Reference prices are completed daily closes and requires_requote=true. These are not live quotes or submitted or filled orders."))
        st.subheader(t("持仓账本和单边成本", "Holdings ledger and one-way costs"))
        st.latex(r"F_t=c\sum_i|\Delta q_{i,t}|O_{i,t},\quad B_t^+=B_t^--\sum_i\Delta q_{i,t}O_{i,t}-F_t,\quad q_{i,t}^+=q_{i,t}^-+\Delta q_{i,t}")
        st.latex(r"E_t=B_t^++\sum_iq_{i,t}^+C_{i,t},\qquad DD_t=E_t/\max_{s\le t}E_s-1")
        say(f"每{h}个交易日开盘调仓，期间股数不变、权重漂移。成本为{p.get('cost_bps', 10)}基点÷10000，按实际成交金额单边扣除，不将换手除以2。每日按收盘记账，不重复叠加h日收益。", f"Rebalance at the open every {h} sessions. Hold quantities constant between rebalances while weights drift. Cost is {p.get('cost_bps', 10)} bps ÷ 10000 on actual traded notional, without halving turnover. Mark to each close and never repeatedly compound overlapping h-session returns.")

    st.caption(t("方法不保证预测优势。可信度来自明确时点、冻结数据、训练边界、成本和能对账的持仓记录。", "The method does not guarantee predictive edge. Credibility requires explicit timing, frozen data, training boundaries, costs and a reconciled holdings ledger."))
