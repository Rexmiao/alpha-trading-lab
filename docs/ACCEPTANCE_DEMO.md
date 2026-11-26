# 342项Python与26项Node：离线代码验收演示

2026年11月26日重新执行：**Python 342／342、Node 26／26通过，失败与跳过均为0。** 这是对数据边界、状态机、持久化和界面的代码验收，不是收益、有效alpha、真实券商成交或完整系统上线的证明。

本轮使用固定时钟、虚构行情、注入的HTTP／SDK／子进程响应和临时SQLite。真实VeighNa MainEngine／Gateway／OMS参与指定用例，但券商响应是替身。没有读取实际认证配置、活动交易数据库或真实账户，也没有发出真实paper订单。

## 本轮实际跑了什么

运行时段为 **2026-11-26 19:38:08.857248—19:38:49.850074 UTC**。执行栈与研究页面分别使用独立环境，未将VeighNa环境的NumPy版本带入公开研究应用。

| 组别 | 测试文件与通过数 | 合计 |
| --- | --- | ---: |
| 本机执行栈 | `test_execution_marketdata.py` 37；`test_execution_runtime.py` 43；`test_veighna_bridge.py` 45；`test_rest_paper.py` 56；`test_paper_gateway.py` 18；`test_snapshot_sync_runner.py` 19 | 218 |
| 分钟研究、快照、界面、发布器 | `test_intraday.py` 48；`test_intraday_ui.py` 7；`test_snapshot_source.py` 56；`test_snapshot_publisher.py` 13 | 124 |
| Node采集器 | `test_intraday_collector.mjs` | 26 |

| 环境 | 实际记录 |
| --- | --- |
| 执行栈 | Python 3.12.7、pytest 8.3.2、vnpy 4.5.0、futu-api 10.12.7208、cryptography 50.0.2、NumPy 2.2.6、pandas 2.2.3 |
| 分钟研究／UI | Python 3.12.7、pytest 8.3.2、NumPy 1.26.4、pandas 2.2.2、Streamlit 1.67.0、PyArrow 25.0.1 |
| Node采集器 | Node v20.12.2 |

分钟组另有1条pandas FutureWarning：非法输入用例故意把空字符串放入数值列，以测试缺字段拒绝。该警告保留在完整日志，没有隐藏；测试本身通过。

运行前后对67个代码／依赖配置文件逐个计算SHA256，并对有序清单计算整体指纹；两份清单一致。整体指纹为：

```text
972cc7573e6b75ca5151e9b62d406fff9c94bf1eafca90ca5e7a30306030af2b
```

起始Git HEAD为`af14fa905ee94802b30233bf801092f5c8c4c47a`。上述指纹只对应这次基线；后续代码修复应另附增量测试与文件哈希，不能把旧报告当成新代码的全套重跑。

### 基线后的DPAPI增量修复

其后实机排查发现：Windows PowerShell 5子进程继承PowerShell 7模块路径，可能导致DPAPI读取所需模块无法自动加载。正式修复限定绝对Windows PowerShell路径和子进程系统Modules路径，清理继承的PS7缓存变量，父进程环境保持不变；另新增3项模块污染／信息不泄漏回归。

修复后**publisher 16／16通过**，包括原13项及新增3项；其他基线代码未改。基线仍记342项，16项增量复跑不重复累加到342。修复后的文件哈希、命令和结果另记本机`state/acceptance-20261126/dpapi-regression.json`与`publisher-regression.log`。该增量记录不意味着342项已经在修复后全部重跑。

## 五个可以逐步观看的场景

下面9个测试均已实际通过，**包含在342项之内，不再重复计数**。点源文件可以查看完整断言；测试名可直接用于pytest筛选。

### 1. 先写进数据库，再跨过下单边界：2／2

在假的下单调用刚要发生时，另开一个SQLite连接读取数据库。它必须已经看到运行器意图与适配器状态均为`SUBMITTING`，证明事务已提交。下单ACK只能更新委托状态，不能生成成交。

- [运行器测试](../tests/test_execution_runtime.py)：`test_paper_network_boundary_has_committed_intent_and_durable_adapter_state`
- [适配器测试](../tests/test_veighna_bridge.py)：`test_persist_submitting_precedes_rpc_and_ack_and_execution_are_saved`

### 2. 超时进入UNKNOWN，不自动再发一张：2／2

让假的提交接口超时，保留`SUBMISSION_UNKNOWN`。后续信号、重启和重复提交都不能产生第二次提交；只有查询到唯一、remark及原订单经济内容一致的委托，才可恢复已知订单身份。

- [运行器测试](../tests/test_execution_runtime.py)：`test_unknown_submit_blocks_new_signal_and_restart`
- [REST测试](../tests/test_rest_paper.py)：`test_post_timeout_never_retries_and_unique_economic_match_recovers`

### 3. 部分成交与撤单交错，重复回报不重复记账：2／2

状态机压力用例依次给出累计成交4股、累计10股，必须只记4股和6股两个增量。随后重复同一部分成交已撤销终态，成交记录仍为两条；持久化层也拒绝累计量回退。这里的较大数量是虚构状态机输入，当前受控paper提交仍限制每张1股。

派生成交标明`derived_from_order_cumulative`、`broker_deal_id=None`，不能伪称收到官方Deal推送。

- [累计成交测试](../tests/test_veighna_bridge.py)：`test_cumulative_notional_partial_cancel_and_duplicate_is_not_a_deal_push`
- [数据库去重测试](../tests/test_execution_runtime.py)：`test_order_reported_executions_persist_dedup_and_regression_is_blocked`

### 4. 提醒切到自动，旧提醒不会补下单：1／1

先在`ALERT_ONLY`产生提案，再切到`AUTO_EXECUTE＋BROKER_PAPER`。同一bar应返回`ALREADY_CAPTURED`；旧提醒不能通过确认入口升级为订单，假的适配器调用列表保持为空。模式改变只作用于之后符合条件的新提案。

- [模式切换测试](../tests/test_execution_runtime.py)：`test_mode_switch_never_executes_old_alert_and_status_retains_policy`

### 5. REPLAY隔离活动运行器，不把回放接成paper：2／2

CLI隔离用例禁止回放路径构造`TradingRuntime`或启动REST认证工厂，并核对原政策及审计数量不变。另一个用例使用真实VeighNa做独立影子回放，检查因果next-open撮合、预定研究退出与框架对象。前者替换回放函数以检查入口隔离，后者检查实际回放引擎；两种证据分别说明范围。

- [入口／活动数据库隔离测试](../tests/test_execution_runtime.py)：`test_shadow_replay_never_opens_active_runtime_or_configures_paper`
- [真实VeighNa回放测试](../tests/test_veighna_bridge.py)：`test_replay_causal_next_open_end_flat_and_true_framework`

## 怎样复跑

在项目根目录使用已经按相应requirements建立的独立环境。以下保留相同测试集合与pytest选项；本机实际运行另外指定了JUnit输出和独立临时目录，绝对路径、完整argv、时间、依赖及每个参数化用例状态均保存在本机JSON。

```powershell
& '.\state\veighna-venv\Scripts\python.exe' -m pytest -vv -ra `
  tests/test_execution_marketdata.py tests/test_execution_runtime.py `
  tests/test_veighna_bridge.py tests/test_rest_paper.py `
  tests/test_paper_gateway.py tests/test_snapshot_sync_runner.py

& '.\state\intraday-venv\Scripts\python.exe' -m pytest -vv -ra `
  tests/test_intraday.py tests/test_intraday_ui.py `
  tests/test_snapshot_source.py tests/test_snapshot_publisher.py

node --test --test-reporter=tap tests/test_intraday_collector.mjs
```

只演示一个场景时，可用完整node ID，例如：

```powershell
& '.\state\veighna-venv\Scripts\python.exe' -m pytest -vv `
  tests/test_execution_runtime.py::test_paper_network_boundary_has_committed_intent_and_durable_adapter_state
```

本机证据目录为`state/acceptance-20261126/`，包含三个完整stdout／stderr、两份JUnit、分套JSON、`scenarios.json`、源码前后清单和`summary.json`。该目录按项目约定留在本机，不进入公开源码包；此文档不包含原始行情、认证材料或真实账户。

本轮额外使用离线socket保护：禁止外连与普通本机网络调用，只允许Windows asyncio内部socketpair。最终两套Python报告均为0次被拦网络尝试、0次外连；UI产生的58对内部回环socketpair属于事件循环，不是券商连接。最初过严的保护误拦了这些内部socketpair，导致7项UI测试无法初始化；首轮失败日志原样保留在`attempt-01-strict-guard/`，修正测试保护工具后完整三套重新执行，未改应用代码绕过失败。

## 这些结果没有替代哪些验收

本页证明上述版本在给定离线输入下遵守断言。真实实时权限、私有数据上传／读取、模拟账户授权、REST订单期限默认及真实订单／撤单／成交需要各自的服务实测记录；本页测试不为这些事项代签通过。paper尚无预定尾盘强平，持续SHADOW执行尚未实现，当前SHADOW入口是独立历史回放。完整每日M1也未由这342项测试验收完成。

测试数量不能证明策略有效、未来收益、真实成交质量、数据覆盖完整或无人值守交易已经可用。当前执行范围与待验收项见[执行规格](../specs/VEIGHNA_MOOMOO_SYSTEM.md)，研究撮合与成本近似见[动量／趋势说明](MOMENTUM_TREND.md)。
