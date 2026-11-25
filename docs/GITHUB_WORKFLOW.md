# GitHub 上传与后续维护

目标仓库：[Rexmiao/alpha-trading-lab](https://github.com/Rexmiao/alpha-trading-lab)。本项目沿用现有 GitHub App，不另起包含组织访问的登录流程。

## 授权方式

1. 通过现有连接器检查目标仓库和 App 可访问仓库列表。
2. 新建仓库若返回 `403 Resource not accessible by integration`，先检查 App 是否只授权了旧仓库。能够读取公开仓库，并不代表 App 已获得写入权限。
3. 在 [GitHub App 安装设置](https://github.com/settings/installations) 中进入已有 App 的配置，在 **Selected repositories** 加入本次目标个人仓库并保存。保留已有授权；不改成全部仓库，不申请组织范围。
4. 再检查目标仓库是否进入 App 列表，并以待上传的实际源文件验证写入。无需索取或保存个人访问令牌。

当前连接器可上传文件，但没有创建仓库的工具。需要新仓库时，由用户建立并初始化 README，再通过以上方式补充该目标仓库访问即可。本项目仓库已由用户建立，后续复用现有仓库。

## 上传范围与步骤

上传包括代码、SPEC、依赖、测试、论文索引、API 手册、教学 GIF/封面和 `web/` 静态网页源码。论文原文通过官方链接访问，全文是否可再分发需单独确认。

`data/`、`runs/`、`state/`、聊天截图、账户、凭据及本地模型权重不上传。上传使用明确源文件清单，不能把整个上级资料文件夹当作仓库。

1. 先更新 [SPEC](../SPEC.md)、[README](../README.md) 和对应手册，检查相对链接与依赖。
2. 读取远端分支当前提交和目录对象，保留用户初始化的 MIT License 与已有文件。
3. 对待上传文件计算内容哈希。使用 Git 数据接口创建 blob；GIF/PNG 等二进制以 base64 传输，核对返回 Git blob SHA 与本地文件一致。
4. 基于现有目录对象建立新 tree，再创建以当前提交为父提交的 commit。
5. 以预期旧提交号更新目标分支，拒绝强制覆盖。若分支在此期间变化，先读取新提交并核对差异。
6. 回读远端提交和文件，核对哈希、README 资料入口及中英文动画路径。确认成功后再报告上传完成。

## 与公开教学网站的关系

GitHub 保存研究代码、复现资料和 README 动图；当前[公开教学页](https://alpha-training-lab-guide.totalbluebell3.chatgpt.site)使用独立网站托管。上传 GitHub 并不会自动部署 GitHub Pages。

网页导出文件位于 `web/`。在仓库根目录运行：

```powershell
python -m http.server 8512 --bind 127.0.0.1 --directory web
```

再打开 http://127.0.0.1:8512/ 。网页不依赖 moomoo 在线或本机研究结果。更新动画与网页后，需同步导出文件并按 [SPEC](../SPEC.md) 验证语言切换与交互。
