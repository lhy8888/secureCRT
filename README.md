# Harbor Terminal 0.4.1

面向 Windows 10/11 的独立 SSH / 串口桌面客户端，Python 3.12 + Qt。0.4.1参照SecureCRT 9.7官方Windows截图重做桌面布局、字体和配色，包含0.4的SSH跳板/转发、0.3的SFTP/日志/Hex，以及0.2终端/串口核心。尚未达到 SecureCRT 9.7.4 全功能等价，也没有“更安全/更稳定”的对照结论。

完整规格见 [历代累积功能审计](docs/research/README.md)：32 个系列、314 个发布分节、4294 条历史 bullet、183 项能力/验收。每项实现与缺口记录在 [功能矩阵](docs/research/feature-matrix.md)，本次界面变更见 [0.4.1 记录](docs/releases/0.4.1.md)，连接能力见 [0.4](docs/releases/0.4.md) 及 [0.3](docs/releases/0.3.md)。参考公开界面布局，未包含 SecureCRT 代码或品牌素材，工具栏图标独立绘制。

![0.4.1经典桌面布局，本地SSH/PTY测试数据](artifacts/harbor-0.4.1-terminal.png)

## 界面与字体

- 顶部菜单与16px图标工具栏，左侧会话管理器/活动会话，窄标签、底部状态栏；快速连接参数在独立弹窗中。
- `Alt+Q`快速连接，`Alt+R`聚焦顶部主机输入，`Alt+K`筛选会话。双击保存会话会载入参数并打开连接弹窗。
- Windows界面优先Segoe UI 9pt，终端优先Consolas 11pt；没有该字体时选Cascadia Mono或其他已安装等宽字体。云端截图使用Noto Sans CJK SC / Liberation Mono，不分发Windows字体。
- “选项 → 终端字体”选择全局等宽字体与字号，更新所有标签并同步SSH行列；Ctrl+滚轮只临时缩放当前标签。字格保留字体的实际宽度，减少额外行距。
- “查看 → 界面主题”切换经典浅色/深色；“选项 → 终端配色”选择黑底、浅色或深蓝。显示偏好独立保存在会话文件旁的`appearance.ini`，不保存连接凭据。
- `Ctrl+F`打开可关闭的查找栏；`Ctrl+C/D/S`仍发送终端控制字符，保存会话使用`Alt+S`。

[深色界面](artifacts/harbor-0.4.1-terminal-dark.png) · [快速连接](artifacts/harbor-0.4.1-quick-connect.png) · [会话选项](artifacts/harbor-0.4.1-options.png)

## 本次可用的工作流

- 单级SSH跳板：引用已保存的SSH会话，跳板与目标独立认证及主机密钥校验，取消/失败关闭两端；不做自动信任。
- SSH隧道窗口：本地转发、远程转发、本地SOCKS代理，列出与停止监听；每会话最多16个，监听请求固定127.0.0.1。
- SFTP目录浏览与单文件上传下载、SHA-256回读、临时文件提交、显式覆盖、进度与取消；复用SSH认证。
- 会话日志：RX默认、TX可选，原始字节或文本分块JSONL，暂停/继续、大小分段与配额。
- 串口Hex/ASCII观察与原始字节发送；不追加换行、不自动重发。
- 多标签 SSH/串口，逐会话状态和错误；连接与关闭可取消，关闭窗口后自动完成清理。
- Qt 字格绘制 16/256/24位颜色、粗体/斜体/下划线/删除线/反色；中文宽字符、组合字符、增量解码。
- 窗口变化计算行列并更新 SSH PTY；备用屏幕、保存/恢复光标、常用 xterm 按键与应用光标/数字小键盘模式。
- Ctrl+C 发送中断字符；Ctrl+Shift+C/V 复制粘贴；多行粘贴可编辑确认，支持远端启用的 Bracketed Paste。
- Qt 输入法预编辑/提交接口，UTF-8、GB18030、Big5、Shift-JIS、Latin-1 可选；Windows 实际 IME 仍待验证。
- 当前终端字面文本查找/持续高亮、向前/向后跳转；Ctrl+F 聚焦查找，Ctrl+滚轮缩放。
- 层级会话树（名称可用 `文件夹/会话`）及按名称、主机、用户名过滤。
- 后台枚举串口/可手填设备；数据位、校验位、停止位、四种流控与波特率可保存；提供250ms BREAK入口。
- SSH 严格 known_hosts 校验，未知/变更密钥拒绝；密码与加密 OpenSSH 私钥认证已用真实本地 SSH 服务验证。默认密钥/Agent 由 AsyncSSH 提供，Windows Agent 尚未验证。

## Windows 运行

安装 Python 3.12，在 PowerShell 的项目根目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps .
.\.venv\Scripts\harbor-terminal.exe
```

按Alt+Q或点击工具栏快速连接图标，在弹窗填写SSH主机、端口、用户名和本次密码；私钥文件和本次口令在“会话选项 → SSH / 身份”中选择。连接前通过受信任渠道核实主机公钥指纹，再使用 OpenSSH 格式的 `known_hosts` 文件。非默认端口条目为 `[host]:port`。`ssh-keyscan` 只能收集公钥，不能证明可信。没有忽略校验开关。

密码、私钥口令与私钥内容不写入会话配置或诊断日志；只允许保存私钥路径。Python 内存中的秘密副本不能保证擦除。配置v3可读取旧v1/v2文件，读取旧文件时不自动改写；新版本只增加跳板会话名称引用，不保存跳板密码。

使用跳板时，先保存一个独立SSH跳板会话，再加载目标会话，在“会话选项 → SSH / 跳板”中选择跳板并输入本次跳板密码/口令。目标密码在快速连接弹窗输入；两端各用自己的known_hosts。当前拒绝缺失引用和嵌套跳板。连接后的“传输 → SFTP文件”和“工具 → 会话日志 / SSH隧道”固定绑定打开它们的会话，切换标签不会转向其他连接。

隧道中，L的目标从SSH服务端访问，R的目标从本机访问，SOCKS的目标按代理请求从SSH服务端访问。监听端口0表示自动分配。关闭隧道窗口会保留监听；停止选中监听会拒绝新连接，已有数据流可能继续，断开SSH才会关闭全部流。远程服务器可能覆盖回环监听请求，应按其实际策略配置。SOCKS无代理认证，本机其他用户可能访问该监听；不提供公网监听入口。

快速连接中协议选Serial，设备栏填写`COM3`等或从枚举中选择，端口栏为波特率。“会话选项 → 串口”可改5–8位、N/E/O/M/S、1/1.5/2停止位、none/RTSCTS/DSRDTR/XONXOFF。波特率允许50–4,000,000，实际可用范围由设备和驱动决定；串口不提供SSH加密。云端不能访问你电脑上的实体COM。

## Windows 打包

```powershell
./scripts/build-windows.ps1
```

生成 `dist/HarborTerminal/HarborTerminal.exe` 及同目录运行库；分发需保留整个目录。这是未签名开发包的构建流程，**本轮 Linux 环境没有生成或测试 Windows EXE**。Windows CI 配置在 `.github/workflows/validate.yml`，尚未远端执行。正式发布前还需许可证清单、签名、升级与原生平台验证。

## 验证与界面采集

```bash
cd /workspace/secureCRT
/workspace/securecrt-venv/bin/python -m pytest -q
QT_QPA_PLATFORM=offscreen /workspace/securecrt-venv/bin/python scripts/capture_terminal.py
QT_QPA_PLATFORM=offscreen /workspace/securecrt-venv/bin/python scripts/capture_services.py
```

运行截图脚本前，修改源码后需重新执行 `python -m pip install --no-deps .`，脚本使用安装后的包。本地真实SSH服务验证加密收发、密钥拒绝、私钥认证、窗口变化、跳板、SFTP、三类转发及Qt输入链路；Linux PTY验证串口字节流。截图均来自生成测试数据，不是真实网络设备或Windows界面。

工具截图：[SFTP](artifacts/harbor-0.4.1-sftp.png) · [SSH隧道](artifacts/harbor-0.4.1-tunnels.png) · [会话日志](artifacts/harbor-0.4.1-log.png) · [串口Hex](artifacts/harbor-0.4.1-hex.png)。复查结果见 [本轮验证](artifacts/validation-0.4.1.md)。

## 实现边界

- SFTP当前限单文件，上传安全提交需hardlink/POSIX rename；不保留元数据，无递归/续传/独立SFTP登录。日志为JSONL分块，无逐行纯文本/跨日/自动脱敏。完整约束见0.3记录。
- 跳板仅单级，转发不保存模板、不自动重建；SOCKS只验证无认证IPv4子集，未验收域名/IPv6和长期并发。仍无X/Y/Zmodem/Kermit、脚本/Expect、命令广播、凭据库、快照/平铺、导入向导和自动重连。
- 不是完整 VT320/TN3270/Wyse/Xterm 实现。未做 vim/tmux/top 全量回放、远端鼠标、闪烁、双高/双宽行、RTL/emoji完整字素兼容。OSC/DCS/APC/PM/SOS仍被过滤。
- 2000行历史；最多16个标签；网格最多512列×200行。缩小高度保留适用行与移出的历史，**横向缩小会裁切列，尚无软换行重排**。
- 接收256KiB、发送64KiB缓冲，收发独立并施加背压；CSI限制128字符，保存光标栈16项，每格32码点；每次解析有估算操作预算。这些边界不是操作系统级CPU/内存沙箱。
- 串口实体线路、热拔插、挂死的驱动调用、Windows IME/DPI/Agent、72小时稳定性与 SecureCRT 同机对照仍未验证。
