# LEAN、Qlib 与 NautilusTrader 选型研究

研究日期：2026-11-26（America/New_York）；报告版本：1.0。适用项目：Windows／Python、美股日频、moomoo、DL／GenAI alpha 研究，后续统一支持提醒、人工确认、自动执行。

本轮核对官方文档、固定版本源码、发布记录、包元信息和维护者说明。没有安装框架、执行性能基准、迁移真实数据、连接交易账户或验证第三方插件。以下“适合度”“成本”和采用顺序是结合本项目的工程判断，不是实测性能排名或收益结论。

## 1. 针对本项目的结论

- **模型研究：优先评估 Qlib。** 模型接口、研究流程和实验记录最贴合当前 alpha 研究，但必须适配我们的数据可见时间、h5 标签和预测单位。
- **美股完整回测／执行框架：优先把 LEAN 作为对照候选。** 股票公司行动和组合执行机制有直接价值；moomoo 适配和 C#／Docker 工作量尚未验证。
- **细粒度事件驱动执行：NautilusTrader 值得参考，但当前采用优先级较低。** 稳定版与 2.x 文档存在差异，现有依赖有冲突，股票公司行动和 moomoo 接入还需要额外工作。
- **当前 M1：继续完成小型 Python 每日系统。** 复用现有只读采集，保存可信快照、因子和状态。进入 M2／M3 前再用小样例比较成熟引擎，避免提前自建全部订单管理，也避免因换框架丢失已明确的时间和恢复契约。

## 2. 对比概览

| 维度 | LEAN | Qlib | NautilusTrader |
| --- | --- | --- | --- |
| 主要定位 | 多资产研究、组合、回测与交易引擎 | AI／ML alpha 研究、实验管理与组合评价 | 事件驱动回测与交易执行引擎 |
| 对我们最有用的优势 | 美股公司行动、组合与执行分层、已有券商生态 | 自定义预测模型、模型基准、实验追踪 | 策略复用、订单事件、适配器和状态管理 |
| 主要额外工作 | 数据转换、默认行为核对、moomoo 券商插件 | 数据转换、自定义标签／处理器、外部执行系统 | 固定稳定 API、隔离依赖、公司行动、moomoo 联调 |
| 当前 moomoo 可直接使用？ | 未核实；官方券商列表未列 moomoo／Futu | 未核到专用券商执行适配 | 官方稳定目录未列；存在未验收的第三方 OpenD 插件 |
| 原生 Windows／Python | Python 策略；核心 C#，便利本地路线通常含 Docker | 0.9.7 有 CPython 3.12 Windows wheel；完整依赖待验证 | 1.231.0 有 CPython 3.12 Windows wheel；与现有锁版本存在冲突 |
| 框架会自动完成我们的 GenAI 策略？ | 仍须实现模型、数据和验证 | 可包装自定义模型，具体 DDPM 仍须实现 | 可接预测结果，研究训练流程仍须实现 |
| 核心仓库许可 | Apache-2.0 | MIT | LGPL-3.0-or-later |

能力证据分别见下文；许可标识来自各自[LEAN](https://github.com/QuantConnect/Lean/blob/master/LICENSE)、[Qlib](https://github.com/microsoft/qlib/blob/main/LICENSE)、[NautilusTrader](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/LICENSE)许可证。代码许可不等于行情、商业托管或数据订阅免费。

## 3. 版本与运行环境：先消除安装歧义

| 项目 | 本次核到的版本边界 | 采用时应固定什么 |
| --- | --- | --- |
| LEAN | 当前 master 提交为 65e09859fae6287e9e70ae7fcce3ff478ea2fdb0，提交时间 2026-11-25；GitHub releases/latest 返回的是 2017 的 v2.4.0.1，不能代表当前部署版本或据此判断停止维护 | 实际引擎提交、镜像 digest、Python 及研究依赖 |
| Qlib | PyPI 默认版本 0.9.7；GitHub release 为 v0.9.8；stable 文档标 0.9.7，latest 文档为 0.9.8.dev11 | 选择明确 tag／包版本，记录完整依赖；不能混用说明和实现 |
| NautilusTrader | 默认稳定包 1.231.0；latest 安装文档明确介绍 2.x，预览安装需 --pre，Python API 与 1.x 不同 | 固定 1.x 或另作 2.x 预览研究，分别使用对应 API／样例 |

来源：[LEAN 核对提交](https://github.com/QuantConnect/Lean/commit/65e09859fae6287e9e70ae7fcce3ff478ea2fdb0)、[LEAN release 入口](https://api.github.com/repos/QuantConnect/Lean/releases/latest)、[Qlib PyPI](https://pypi.org/project/pyqlib/)、[Qlib v0.9.8](https://github.com/microsoft/qlib/releases/tag/v0.9.8)、[Nautilus 1.231.0](https://pypi.org/project/nautilus_trader/1.231.0/)、[Nautilus 2.x 安装说明](https://nautilustrader.io/docs/latest/getting_started/installation/)。2.x 文档明确不建议 release candidate 用于真实资金生产。

当前项目 Python 为 3.12.7，锁定 NumPy 1.26.4、pandas 2.2.2、scikit-learn 1.5.1、joblib 1.4.2。HF 清单为 PyArrow 25.0.1、tzdata 2025.2；Community Cloud 已核到的实际 PyArrow 为 24.0.0，详见[主 SPEC](../SPEC.md)。

Nautilus 1.231.0 元信息要求 pandas>=2.3.3,<4、PyArrow>=25、tzdata>=2026.3。因此 pandas 与现有锁版本冲突，tzdata 与云端清单冲突，Community Cloud 实际 Arrow 也不满足；NumPy>=1.26.4 这一项则满足。应独立环境验证并交换标准化预测／文件，不直接升级现有公开演示的整套依赖。[固定版本依赖](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/pyproject.toml)、[PyPI 元信息](https://pypi.org/pypi/nautilus_trader/1.231.0/json)。这属于声明依赖检查，尚未进行安装或完整解算。

Qlib 0.9.7 的 wheel 覆盖 CPython 3.12 Windows，其直接依赖未对现有 NumPy／joblib 设冲突版本，pandas>=0.24 也未直接否决 2.2.2；MLflow、LightGBM、cvxpy、gym 等新增直接依赖、其传递依赖及 DL 依赖仍待实际验证，不能外推为整个环境兼容。旧安装页的 Python 3.8 描述与现有 wheel 不一致，以具体版本元信息核对。[0.9.7 文件](https://pypi.org/project/pyqlib/0.9.7/#files)、[0.9.7 依赖](https://github.com/microsoft/qlib/blob/v0.9.7/pyproject.toml)、[安装页](https://qlib.readthedocs.io/en/stable/start/installation.html)。

## 4. LEAN：美股全流程能力有价值，接入栈和券商适配较重

### 优势

1. **契合排名、多因子和定期组合调整。** Universe、Alpha、Portfolio、Risk、Execution 各有边界，容易表达“模型分数→目标仓位→风险约束→执行”。但内置默认组合规则仍需按我们现金下限、单股上限和五日调仓锚点定制。[Algorithm Framework](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview)
2. **美股公司行动处理有现成基础。** 支持拆股、分红、不同复权模式，以及相应持仓／部分未成交订单处理。这能节省自行实现股票账本的工作，前提是行情和公司行动输入完整、适配正确。[Corporate Actions](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/corporate-actions)
3. **DL 可以通过 Python 接入。** 官方提供 PyTorch 模型训练、保存、加载和预训练模型示例；研究训练后固定 artifact 做日常推理，与我们的设计相容。[PyTorch](https://www.quantconnect.com/docs/v2/writing-algorithms/machine-learning/popular-libraries/pytorch)

### 劣势与需要补做的部分

1. **Python 算法运行在较厚的引擎栈中。** 核心是 C#，深改券商插件通常涉及 .NET；官方 CLI 本地路线含 Docker，Windows 还涉及 WSL 2 等环境。不是把现有 pandas 脚本 import 进去就完成迁移。[引擎说明](https://www.quantconnect.com/docs/v2/lean-engine/getting-started)、[CLI 安装](https://www.quantconnect.com/docs/v2/lean-cli/installation/installing-lean-cli)
2. **moomoo 接入尚无现成官方证据。** 当前官方券商目录未列 moomoo／Futu。自定义接入并非被禁止，但须处理初始化现金／持仓／未完成订单、提交／修改／取消、成交与连接事件等，工作量需单独验证。[券商目录](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages)、[实现职责](https://www.quantconnect.com/docs/v2/lean-engine/contributions/brokerages/creating-the-brokerage)
3. **数据格式和默认行为会改变实验。** 原生美股格式和我们的七列 CSV 不同；默认 fill-forward、复权口径都要审查。导入前复权 OHLC 不会自动补出拆股、分红和历史证券身份数据。[美股格式](https://www.quantconnect.com/docs/v2/lean-engine/data-format/us-equity)、[订阅默认行为](https://www.quantconnect.com/docs/v2/writing-algorithms/securities/asset-classes/us-equity/requesting-data)
4. **开源引擎与商业服务费用分开。** 当前 CLI 文档要求付费组织，数据和云计算另有费用边界；可自行构建开源引擎，但便利程度和维护成本不同。本报告不报价、不订阅服务。[CLI 要求](https://www.quantconnect.com/docs/v2/lean-cli/installation/installing-lean-cli)、[价格入口](https://www.quantconnect.com/pricing)
5. **回测与实际成交仍需分别验收。** 框架有异步订单事件和可替换成交／费用模型，不能据此推定断线、未知提交和重启恢复自动符合我们的 SPEC。[交易与订单](https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading/trading-and-orders)

对本项目的判断：若优先解决长期美股持仓、公司行动和成熟券商执行，LEAN 是值得认真试验的候选；如果坚持当前 moomoo 桌面链路，先完成只读 M1 的改动更小。容器内 localhost 与本机 Host 的可达性、凭据机制及账户地区仍须独立验证。

## 5. Qlib：最贴合 alpha 研究，默认标签与执行边界必须重审

### 优势

1. **模型研究素材丰富。** 官方模型基准包含多种树模型和深度模型，适合做相同数据下的基线对照。基准表来自其特定市场和实验配置，不能当作我们的美股收益证据。[模型基准](https://github.com/microsoft/qlib/tree/main/examples/benchmarks)
2. **自定义模型接口适合包装我们的 DL／生成增强方法。** 可将训练／预测接入既有研究工作流，仍需自己实现具体条件 DDPM 和对照实验。[模型集成](https://qlib.readthedocs.io/en/stable/start/integration.html)
3. **实验记录和配置化流程比较完整。** Recorder／MLflow 可登记参数、指标和产物，适合多 seed、多模型、滚动时间窗口比较。信息可见时间、冻结快照和信号版本仍由本项目补齐。[Workflow](https://qlib.readthedocs.io/en/stable/component/workflow.html)、[Recorder](https://qlib.readthedocs.io/en/stable/component/recorder.html)
4. **有自有数据转换和美股区域设置。** 可以把冻结的 moomoo 数据转换到其数据层，而不必改变主数据源。[数据层](https://qlib.readthedocs.io/en/stable/component/data.html)

### 劣势与需要补做的部分

1. **预制数据当前不可直接依赖。** 官方 README 明确官方数据集暂时停用；已有 US 下载说明不等于完整、最新、含历史成分和退市股票的数据已经可用。[数据状态](https://github.com/microsoft/qlib#data-preparation)
2. **默认任务与我们的标签不同。** v0.9.7 Alpha158／360 默认以未来 close 构造标签，学习处理器对 label 使用 CSZScoreNorm。我们的标签是 T+1 开盘到 T+6 开盘减 SPY；需自定义标签、保留 label-end purge，并明确输出是排序分数还是收益率。标准化分数不能直接与 bps 成本比较。[固定版本 handler](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/contrib/data/handler.py)
3. **US 配置也不是我们的 next-open 执行政策。** 美股区域设置并不会自动改成我们的开盘成交、五日锚点和 EWMA 资金分配；默认 close 和示例费用需要显式修改。[固定版本配置](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/config.py)、[组合策略](https://qlib.readthedocs.io/en/stable/component/strategy.html)
4. **Online Serving 主要管理预测与模型更新。** stable 文档明确列出支持每日次日预测、受公开数据限制不支持生成次日订单的边界。它不能替代 moomoo 委托／成交、未知提交查询和对账。默认模型滚动和预测更新也须适配我们的任务版本固定与不可修改记录规则。[Online Serving](https://qlib.readthedocs.io/en/stable/component/online.html)
5. **GenAI 辅助研发不等于生成式 alpha 模型。** 官方 RD-Agent 方向包含 LLM 辅助因子／模型研发；这与生成收益样本、条件扩散增强或直接预测 alpha 是不同实验，不能因项目集成了 LLM 就声称复现了我们的论文方法。[项目说明](https://github.com/microsoft/qlib)
6. **包版本与文档存在漂移。** v0.9.8 包含 artifact／配置加载等加固与依赖变更，而 PyPI 默认仍是 0.9.7。采用时要明确选择并验证版本，不能混用其运行和复现说明。[v0.9.8 release](https://github.com/microsoft/qlib/releases/tag/v0.9.8)

对本项目的判断：优先做隔离环境中的研究适配小实验。先让同一份数据和 h5 标签在现有研究程序、Qlib 中对齐，再决定采用模型库／Recorder 的范围。引入 Qlib 不替代每日采集和后续交易执行。

## 6. NautilusTrader：事件与执行模型值得借鉴，美股长持有存在额外缺口

稳定版 1.231.0 仍包含 Cython v1 引擎与 Rust 组件；完整 Rust／PyO3 的新运行时属于 2.x 路线。该稳定包元信息仍标记 Beta，新功能重心转向 v2，不能把预览能力或开发分支样例直接混入稳定部署。[v1 引擎源码](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/engine.pyx)、[发布与迁移说明](https://github.com/nautechsystems/nautilus_trader/releases/tag/v1.231.0)。

### 优势

1. **有回测和交易共用策略的结构。** 稳定版以 Python 策略连接事件驱动组件，适配器将行情和执行回报转换为统一事件，适合复杂订单生命周期。应以固定 v1.231.0 的代码和样例验证，而不是照抄 2.x 的 LiveNode 示例。[稳定版说明](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/README.md)
2. **执行和状态职责较明确。** 订单、持仓、账户、缓存及持久化基础能够减少全套自建工作；实际券商差异和恢复仍需用自己的案例验收。[稳定版代码](https://github.com/nautechsystems/nautilus_trader/tree/v1.231.0/nautilus_trader)
3. **存在真实的第三方 Futu 路线供评估。** loadstarCN/nautilus-futu 声明提供 OpenD 行情、交易和回报适配，说明有可研究的现成代码；这是第三方项目声明，尚未被本项目安装、审计或联调验证。[第三方插件](https://github.com/loadstarCN/nautilus-futu)

### 劣势与需要补做的部分

1. **公司行动是当前重要限制。** 官方维护者于 2026-11-10 将广义拆股／更名／合并支持提案关闭为当前范围 not planned，并明确历史归一化和自定义事件不能提供实盘持仓、订单的自动公司行动处理。对股票长期持仓，这会带来额外账本和恢复工作；不能把“支持 equities”理解为这些流程已齐备。[维护者说明](https://github.com/nautechsystems/nautilus_trader/issues/3307#issuecomment-6757711011)
2. **稳定／预览 API 不同。** latest 文档覆盖 2.x，普通 pip 安装默认 1.x；2.x 使用不同 Python API。选型要把版本、样例、插件和测试一起固定。[安装说明](https://nautilustrader.io/docs/latest/getting_started/installation/)
3. **现有依赖无法原样共存。** 1.231.0 对 pandas、tzdata 的要求与本项目锁版本不同，Community Cloud 当前 Arrow 也不匹配。先隔离验证，不改公开研究应用依赖。[稳定版依赖](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/pyproject.toml)
4. **第三方 Futu 插件不是当前桌面 API 的直接替换。** 官方稳定适配器目录未列 Futu／moomoo。该第三方 README 使用传统 OpenD 默认端口 11111 和 v1 TradingNode API；我们当前是桌面 Host 22222，只读方法和认证不同。它声明的版本下限不构成所有未来版本兼容保证。[官方稳定目录](https://github.com/nautechsystems/nautilus_trader/tree/v1.231.0/nautilus_trader/adapters)、[第三方接入说明](https://github.com/loadstarCN/nautilus-futu)
第三方插件还声明成交推送中费用先按零处理、完整费用需另外查询。因此即使它能产生 FILLED 回报，也不能直接把这条推送当成完整含成本现金账本；需单独验收费用回补与去重。[第三方已知限制](https://github.com/loadstarCN/nautilus-futu#readme)

5. **事件引擎不包办 alpha 研究。** 因子数据、模型训练、GenAI 增强和严格时间验证仍需我们组织。对当前日频策略，尚无证据表明换用此引擎的吞吐优势能改善预测质量或降低接入总成本；本次没有做速度实测。

对本项目的判断：保留为未来执行引擎候选，尤其有多市场、复杂订单或更高频需求时重新评估。若用于美股持仓，先解决公司行动与恢复，再讨论速度和更多订单特性。

## 7. 自建部分的真实代价

继续小型 Python M1 的优势是能直接延续现有数据、h5 标签、版本与界面契约；缺点是任务租约、崩溃恢复、行情修订、持续资金账本和订单状态都需要工程实现及长期维护。代码量少不能推导出可靠性高，也不能假定自建永远比接入成熟引擎便宜。

当前只自建与我们直接相关的采集／研究运行层，后续在“目标仓位→订单管理”边界评估成熟引擎。无论采用哪一种，提醒／确认／自动是统一应用策略；模拟／实盘是独立环境，均须通过实施 SPEC 的 C01–C25、U01–U07 中对应验收。框架自带交易功能不代表已完成本项目模式切换、去重或账户恢复。

不要在同一账户上让两个独立账本同时作执行真相。若组合层和执行引擎分离，目标仓位、实际持仓、在途数量和成交事件的责任必须唯一且可追溯；否则复用多个框架反而增加对账成本。

## 8. 用小实验决定采用范围

下列验证尚未执行，也不改变 M1 当前状态：

| 验证 | 固定条件 | 通过标准 | 决策作用 |
| --- | --- | --- | --- |
| Qlib 研究适配 | 独立环境、固定版本、同一冻结 moomoo 快照、自定义 h5-SPY 标签 | 证券／日期／有效样本和标签与现有程序逐行对齐；生成样本只见训练集；保存版本与依赖 | 决定是否采用模型接口、模型库和 Recorder |
| LEAN 回测对照 | 固定提交／镜像、同一策略规则、原始与研究价分开、明确费用和 next-open | 成交时点、持仓净差、现金和费用可解释对齐；自建小样本拆股／分红账本正确 | 决定美股回测／组合／执行层是否迁移 |
| moomoo 模拟接入 | 单独确认传统 OpenD 或其他正式接口、固定账户地区和模拟环境 | 回报、部分成交、未知提交、断线和重启对账符合 SPEC；无实盘调用 | 决定采用官方 SDK、自写适配还是验证第三方插件 |

前两个离线验证不需要交易账户。第三个在进入 M3、明确接口和模拟账户后才进行。现有仅前复权日 K 不足以单独验收真实货币公司行动账本；离线自建样本验证的是工程语义，真实数据覆盖另行核对。

本次不提供跨框架速度、开发天数、预期收益或自动交易可靠性的数值排名，因为尚无相同任务的可比实测。完整实现顺序与当前状态以[每日系统实施 SPEC](../specs/DAILY_SIGNAL_SYSTEM.md)为准。
