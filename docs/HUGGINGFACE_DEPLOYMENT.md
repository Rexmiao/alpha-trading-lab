# Hugging Face Docker 发布准备

这是云端 Python 模拟教学界面的发布说明。GitHub Pages 继续提供纯静态主教学站，两者相互独立。下列文件只是发布准备，不表示已创建 Space、通过云端构建或上线。本项目没有可代用户发布的 Hugging Face 服务账号，也没有预置 HF 认证。

## 本次个人部署目标

2026-11-26已通过公开API核实个人账号`Rexymiao`为PRO；当时公开Space列表为空。计划目标为`Rexymiao/alpha-trading-lab`，这是已配置的发布目标，不是已上线地址。用户需先在该账号创建专用Public / Docker / Blank / CPU Basic Space。此账号信息不提供服务操作权限；实际构建与公网交互仍待验证。

自动同步已默认采用此目标，用户只需在GitHub仓库Secret安全配置`HF_TOKEN`；`HF_SPACE_ID`变量保留为可选覆盖。默认目标不会创建Space、购买服务或选择其他硬件。

## 账号和费用前提

当前官方要求：个人账号在 CPU Basic 上新建 Docker Space 需要 PRO 订阅；组织需要相应 Team 或 Enterprise 计划。CPU Basic 的硬件无小时费用，不等于所有免费账号都能新建 Docker Space。请在自己的 Hugging Face 页面确认账号资格和套餐；本项目不会代购套餐、添加支付方式或选择付费硬件。

Streamlit 的内置 Spaces SDK 已弃用；本包使用 Docker SDK。Space 根目录 README 的 YAML 已配置 `sdk: docker` 和 `app_port: 7860`，不要改为旧的 `sdk: streamlit`。运行服务监听 `0.0.0.0:7860`，使用非 root UID 1000，并将数值库线程限制为1。

官方来源：[Streamlit 部署建议](https://huggingface.co/docs/hub/spaces-sdks-streamlit)、[Docker Spaces](https://huggingface.co/docs/hub/spaces-sdks-docker)、[账号与硬件条件](https://huggingface.co/docs/hub/spaces-overview)、[CPU Basic 规格](https://huggingface.co/docs/hub/spaces-gpus)。实际创建时以账号界面的资格及费用说明为准。

## 先生成可检查的本地发布包

在项目根目录运行：

```sh
python scripts/package_hf_space.py
```

默认输出在项目父目录的 `outputs/hf-space-bundle/` 和 `outputs/hf-space-bundle.zip`。需要另一个名字时可加 `--name hf-space-review`；参数只接受简单目录名，不接受绝对路径或路径分隔符。发布包不是数据备份。

打包器只复制以下明确清单，不递归复制仓库：

- `deploy/huggingface/` 下四个模板：在包根目录成为 `Dockerfile`、`README.md`、`requirements.txt`、`.dockerignore`。
- `hf_space/__init__.py`、`hf_space/engine.py`、`hf_space/streamlit_app.py`。
- `research/__init__.py`、`research/data.py`、`research/models.py`、`research/portfolio.py`。
- 根目录的 MIT `LICENSE`，以及自动生成的 `MANIFEST.json`。

不会复制 `data/`、`runs/`、`state/`、`.git/`、本机配置、根目录研究界面、pipeline、coverage、moomoo CLI、凭据或本地模型权重。运行不需要 moomoo 密钥或 HF token。

脚本在写出前检查文件存在、UTF-8与Python语法，拒绝符号链接及目录连接；读入后和写出后再次核对源文件，变化中的源程序会报错。`MANIFEST.json` 只含包内相对路径、字节数和SHA256，不含本机绝对路径。报错时不要上传产物，等源代码编辑完成后重试。

目标目录已经存在时，只允许覆盖清单内的已知文件；发现额外文件或目录会停止，不会递归删除它们。请先人工核对额外内容，或使用新的 `--name`。成功退出只代表本地打包与哈希检查完成，不代表Docker实际构建或云端发布通过。

## 可选的本地容器验证

如果本机已经安装Docker，在生成的包目录中运行：

```sh
docker build -t alpha-lab-simulator .
docker run --rm -p 7860:7860 alpha-lab-simulator
```

浏览器访问 `http://localhost:7860`。不要直接以整个研究仓库作为Docker构建上下文。没有Docker时可以先审阅发布包；不能把语法及哈希检查描述成容器已验证。

## 用户登录后创建并上传

1. 用户在自己的浏览器登录 Hugging Face，并先确认有权按当前套餐创建 Docker Space；不把令牌发到聊天或仓库。
2. 在个人用户名下创建专用 Space，选择 **Docker → Blank、Public、CPU Basic**，不复用其他项目。不要将套餐购买或付费硬件当作自动获得的授权。
3. 在 Space 的 Files 页面上传生成目录中的允许文件，保持 `hf_space/` 与 `research/` 结构，模板四个文件放在Space根目录。ZIP需要先解压；仅上传一个ZIP不会自动成为应用。
4. 等待构建与启动完成，检查真实日志和 App 页面，再测试中英文、主动点击模拟运行、输入校验及下载。只有服务实际启动后才能报告发布成功，并使用平台返回的真实地址。

## 通过 GitHub Actions 同步到现有个人 Space

用户已决定同时准备 Hugging Face 和 Streamlit Community Cloud 两个Python应用入口，GitHub Pages主教学站保持独立。两边的账号与实际发布状态分别核对；本节准备好同步代码，不表示已拥有HF账号、完成套餐购买或创建服务。

此同步流程只上传到用户已经亲自创建的 **公开、个人所有、Docker、CPU Basic** Space。不创建Space、不切换硬件、不设置计费、不修改公开范围，也不支持组织名下的Space。请创建专用的新Blank Docker Space，不复用含其他项目文件的仓库。

先由用户在自己的HF账号完成以下操作：

1. 确认当前PRO及创建资格，创建 **Docker → Blank** Space，公开范围选择 **Public**，硬件确认 **CPU Basic**。套餐或硬件付费须由用户单独决定。
2. 到 HF **Settings → Access Tokens** 创建细粒度发布令牌，只给这个目标Space的仓库内容写入权限。不要给其他Space、模型、数据集、组织或硬件管理扩大授权。
3. 到 GitHub 仓库 **Settings → Secrets and variables → Actions → Secrets → New repository secret**，名称填 **`HF_TOKEN`**，值只在GitHub的Secret页面输入。不发到聊天、不写源码、不放进应用本身的Space Secrets。
4. 默认目标已是 **`Rexymiao/alpha-trading-lab`**，不必再建变量。只有实际选择了另一个专用Space时，才在 **Variables → New repository variable** 设置 **`HF_SPACE_ID`** 为已有的 `owner/name`。owner必须与该HF令牌的个人用户名一致，不填写URL或组织空间。

`.github/workflows/huggingface.yml` 在main分支相关模拟源文件更新时触发，也可在 **Actions → Sync simulator source to existing Hugging Face Space → Run workflow** 手动运行。手动的 `space_id` 输入可覆盖仓库变量；目标仍须通过同样的个人所有权、公开范围和CPU Basic检查。输入不是额外授权，不能用来向其他人的Space发布。

工作流只有GitHub `contents: read`，使用Python3.12与`huggingface_hub==2.4.0`。缺少 `HF_TOKEN` 或最终Space ID时会给出notice并跳过打包和上传；绿色的“跳过”不表示已经部署。此配置不需要新的GitHub OAuth或组织登录。

上传前会检查：

- 本地包必须恰好是13个允许文件，`MANIFEST.json`的路径、字节数与所有SHA256一致；符号链接、额外内容、缺失或变动中的包均拒绝。
- `whoami`确认个人身份与目标owner一致；目标必须已存在、为Docker且公开。
- 从Space资料和最新runtime核对硬件：所有明确值只能是`cpu-basic`，至少一项明确为`cpu-basic`。首次构建允许current未知但requested为basic；未设置requested时允许current为basic。两项仍全未知或任何一项是其他硬件均停止，不自动改设置。
- 远端文件只能是同一发布包的白名单文件或平台生成的`.gitattributes`；发现其他项目文件时停止，不删除或覆盖它们。
- 使用明确的13个`CommitOperationAdd`和已读取的`parent_commit`提交，不使用全目录上传、不删除远端文件。若远端有并发提交，停止并重新核对，不强制覆盖。

完成后的输出包含 `code_uploaded`、Space仓库网址及commit。只有收到有效commit标识时，`code_uploaded`才为`true`；这仅证明代码上传，即使观察到runtime为RUNNING，也未证明新commit对应的应用已构建完成。实际上线仍须核对该commit的构建日志、App页面和交互功能。上传后读取runtime失败时会分别保留“代码已上传”和状态查询错误，不能误报为没有发生上传。提交请求报错、响应丢失或回应缺少有效commit标识时，`code_uploaded`为`null`，表示结果未确认；应先核对远端commit，不能认定没有写入或盲目重试。

脚本只从进程环境变量读取 `HF_TOKEN`，不调用登录、不读取本地HF凭据缓存，也不持久化令牌。错误日志只报告异常类名与HTTP状态码，不输出原始服务响应、异常消息或认证头。部署令牌不属于应用运行依赖；模拟应用不需要任何HF或券商密钥。

本地有明确授权且已经通过进程环境安全提供凭据时，可以运行：

```sh
python scripts/package_hf_space.py
python scripts/upload_hf_space.py --bundle ../outputs/hf-space-bundle --space-id owner/name
```

这里的`owner/name`仅是参数格式示例，不是已创建的服务地址。本说明没有执行上述上传。官方依据：[Space 管理接口](https://huggingface.co/docs/huggingface_hub/guides/manage-spaces)、[runtime硬件字段](https://huggingface.co/docs/huggingface_hub/package_reference/space_runtime)、[仓库提交API](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api#huggingface_hub.HfApi.create_commit)。

## 会话、休眠和数据边界

界面只在用户明确操作后运行受限的模拟。教学生成数据有明确标记；主动上传的CSV会传到Space服务端Python进程处理，不是纯浏览器计算。请仅提供有意让该服务处理的标准OHLCV数据，不带账号、凭据或其他敏感字段。发布包本身不包含本机真实行情或研究结果。

CPU Basic 按官方当前规则闲置约48小时会休眠，访问时重新唤醒；重启或停止会丢失临时磁盘内容和会话状态。本模拟不依赖持久化结果，需保留的结果由当前用户主动下载。不要为了避免休眠自动调用保活请求或承诺全天在线。

未来若确有持久化需求，当前官方方案为 Storage Buckets，旧的persistent-storage配置不应被当作仍可直接启用的服务。本版本未开通存储桶或任何付费存储。参考[休眠规则](https://huggingface.co/docs/hub/spaces-gpus#set-a-custom-sleep-time)、[临时磁盘与存储](https://huggingface.co/docs/hub/spaces-storage)。

## 并行的 Streamlit Community Cloud 入口

Streamlit Community Cloud同样使用用户自己的账号，在GitHub仓库部署表单中选择入口 `hf_space/streamlit_app.py`，而不是本机结果查看入口 `app.py`；入口目录的`hf_space/requirements.txt`用于其依赖发现。它不使用HF令牌，也不受本HF同步工作流控制。仍须单独完成平台连接、实际构建与页面验证；两边都准备不能表述为两边都已上线。
