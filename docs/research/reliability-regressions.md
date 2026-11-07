# 历史故障 → Harbor 回归验收

以下均是官方历史中记载的修复/变更。**这些记录不表示问题仍存在于 SecureCRT 9.7.4，也不表示 Harbor 已修复了同一漏洞。**

每条把公开可观察的问题转成自己的验收场景；不推断供应商内部根因。`原型已测`、`同一场景已复现`和`生产修复已验证`是三种不同状态。

| ID | 历史问题 | 公开证据 | 应执行的回归 | Harbor 证据/缺口 |
|---|---|---|---|---|
| R01 | SSH 交换恶意包 | [9.7.4 (Official)](https://www.vandyke.com/products/securecrt/history.txt) L20 / `73d53c4787cd` | 畸形 KEX 包、分片、取消、超长字段；协议解析失败后进程仍可用 | 协议故障注入待做 |
| R02 | 串口连接阻塞 | [9.7.3 (Official)](https://www.vandyke.com/products/securecrt/history.txt) L45 / `4cabada2fce4` | 驱动拒绝/无响应/设备占用时能够取消；连接线程在期限内退出 | Windows/Unix读写超时和取消路径有回归；实体USB驱动挂死未测试。附本机回环/拔插工具，不等于实测通过。 |
| R03 | 交互式认证 LF 提示 | [9.7.4 (Official)](https://www.vandyke.com/products/securecrt/history.txt) L26 / `ce1ebc32a7d5` | 多行 challenge、echo=false、取消、密码变更提示均正确 | 真实SSH + Qt多轮认证已测LF提示、掩码、取消、过期与重复回答；不是供应商原始问题复现。 |
| R04 | 主机公钥与证书指纹区别 | [9.7.3 (Official)](https://www.vandyke.com/products/securecrt/history.txt) L51 / `6039f180a5fe` | 同证书 raw-key 与 certificate 模式显示对应公钥指纹 | 硬件密钥未实现 |
| R05 | 只读旧配置迁移 | [9.7.2 (Official)](https://www.vandyke.com/products/securecrt/history.txt) L85 / `fa2dc7816a13` | 在只读/不可写目标上提示，旧文件不被破坏，主界面正常启动 | 旧版迁移未实现 |
| R06 | 会话大小写改名丢失 | [9.7.1 (Official)](https://www.vandyke.com/products/securecrt/history.txt) L189 / `277f9c5a9064` | Windows 上只改大小写、Unicode 归一化与冲突不丢会话 | 已有基本层级会话树；大小写重命名/Windows文件系统场景未实现 |
| R07 | 连接失败误显示已连接 | [9.7.1 (Official)](https://www.vandyke.com/products/securecrt/history.txt) L181 / `4d12313277dd` | 认证/PTY 创建失败后活动列表、标签、按钮状态一致 | 连接/取消/密钥拒绝、跳板/目标及交互认证阶段已测；仅通道模式不打开Shell。DNS/KEX全部阶段仍未验收。 |
| R08 | 证书算法协商过滤 | [9.7.1 (Official)](https://www.vandyke.com/products/securecrt/history.txt) L142 / `4ca322797ffa` | 受控服务端返回不同算法列表，验证禁止使用未协商证书签名 | 证书互通未实现 |
| R09 | 终端重复字符与颜色 | [9.7.1 (Official)](https://www.vandyke.com/products/securecrt/history.txt) L169 / `55366fa7e33d` | REP、256色、密集 SGR 和属性复位的屏幕回放 | REP、256/24位颜色及Qt字格已测；供应商原始TUI问题未复现，完整回放待做 |
| R10 | 导入丢端口转发 | [9.6.4 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L20 / `eaa66f789cdd` | 完整配置 round-trip 比较启用标志、地址、端口和方向 | 本地/远程/SOCKS转发已有实际流测试，Windows重复绑定另有修复；配置导入/持久化仍未实现。 |
| R11 | 禁用动态转发破坏跳板 | [9.6.3 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L36 / `85b32d3e12fd` | 禁用配置不参与创建；依赖会话仍能建立 | 单级跳板和动态监听已实现并分别测试；禁用模板及该依赖组合场景尚未验收 |
| R12 | 串口输出延迟 | [9.6.3 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L45 / `a62dd07b6ce8` | 测 p50/p95/p99 交互延迟，单字节与大块输出均测 | PTY回环报告实测帧/延迟；云端持续传输在运行。实体串口延迟与SecureCRT同条件对照待执行。 |
| R13 | 串口设备枚举遗漏 | [9.6.3 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L79 / `fac0e6abad8a` | FTDI/CP210x/CH340/Moxa/虚拟COM、枚举和热插拔矩阵 | 实体硬件未测 |
| R14 | Moxa 端口遗漏 | [9.6.2 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L128 / `0b2b4a2454bc` | 真实驱动安装后可见可连接，不能仅检查 COM 数字范围 | 实体硬件未测 |
| R15 | 配置整数越界 | [9.6.2 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L106 / `249aa34b0732` | 导入对端口、尺寸、缓冲、超时做类型/范围验证并原子拒绝 | XML 导入未实现 |
| R16 | 配置敏感项空条目 | [9.6.2 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L99 / `fa31653e441f` | 共享/个人数据目录导入不得丢凭据引用或生成空记录 | 凭据库未实现 |
| R17 | 本地终端 resize 丢历史 | [9.6.2 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L121 / `072dc7cca68f` | ConPTY 与历史重排：交替缩放、宽字符、长行回放比对 | 本地终端未实现 |
| R18 | 重复断开日志 | [9.6.3 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L63 / `bcd553241e09` | 多路关闭/断线同时发生时 disconnect 事件和落盘只发生一次 | 真实SSH/SFTP断开并取消传输时日志disconnected事件一次已测；其他关闭组合待覆盖 |
| R19 | 多窗口同时关闭 | [9.6.3 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L73 / `ac613a1a896c` | 关闭窗口时取消任务、等待工作线程、释放传输只执行一次 | 单窗口关闭有实现；多窗口未实现 |
| R20 | 脚本启动/关闭登录会话 | [9.6.1 (Official)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L148 / `15c485393bdf` | 登录脚本、关闭、异步返回同时发生时不访问已销毁对象 | 有界JSON流程的成功/取消/断开、目标冻结有真实SSH/Qt测试；没有通用脚本对象或任意脚本生命周期。 |
| R21 | 畸形私钥文件 | [9.5.2 (Official)](https://www.vandyke.com/download/securecrt/9.5/history.txt) L20 / `09252d1038ae` | 各格式损坏/超长/加密口令错误，报类型化错误不崩溃 | 加密OpenSSH私钥认证和图形选择已实现；畸形/超长私钥语料及全部格式未验证 |
| R22 | 旧 DLL 污染升级 | [9.5.2 (Official)](https://www.vandyke.com/download/securecrt/9.5/history.txt) L26 / `f78f27e94fa9` | 旧/新二进制混杂时阻止启动或完整修复，不加载任意搜索路径 | Windows原生未签名便携包及冻结EXE启动已测；无旧版DLL污染、安装升级或签名验收。 |
| R23 | 脚本先于连接 | [9.5.2 (Official)](https://www.vandyke.com/download/securecrt/9.5/history.txt) L34 / `669ef37fb30a` | 明确等待认证和 PTY 完成后启动，失败时不运行 | 未连接时拒绝发送/启动流程，断开取消等待并释放队列；未实现通用Python/VB脚本。 |
| R24 | Strict KEX 与完整性 | [9.5 (Beta 3)](https://www.vandyke.com/download/securecrt/9.5/history.txt) L73 / `35c3e2bda388` | CVE-2023-48795 场景需双方扩展协商及包序列测试 | 协议级测试未做 |
| R25 | 第三方密码库漏洞更新 | [9.5.1 (Official)](https://www.vandyke.com/download/securecrt/9.5/history.txt) L48 / `11224dad437c` | SBOM、依赖公告、适用模块、补丁和回归；不能只比库版本 | 21个锁定Python包未报告已知漏洞；Windows包附分发包/许可清单与哈希，仍非完整二进制SBOM和发布治理。 |
| R26 | 存储口令抵抗离线破解 | [9.3 (Official)](https://www.vandyke.com/download/securecrt/9.3/history.txt) L55 / `f8c0e51635b6` | 凭据本地存储使用平台安全服务或合适 KDF/AEAD；弱主口令策略 | 原型不存密码；加密库未实现 |
| R27 | 终端负数参数内存破坏 | [8.7.2 (Official)](https://www.vandyke.com/download/securecrt/8.7/history.txt) L62 / `fbedf608f0a2` | 终端 CSI 超长/负数/极值/分片，解析器不崩溃、内存有界 | 通用有界控制串测试通过；非同漏洞复现 |
| R28 | 脚本录制转义丢失 | [8.3.4 (Official)](https://www.vandyke.com/download/securecrt/8.3/history.txt) L20 / `ae94c0ade947` | 录制含反斜杠、引号、特殊键和 Unicode 后正确重放 | 录制器未实现 |
| R29 | URI 触发恶意本地脚本 | [4.1.9 (Official)](https://www.vandyke.com/download/securecrt/4.1/history.txt) L65 / `127cf910f865` | URI 白名单参数，不接受配置目录或本地执行注入 | CLI解析SSH URI但未注册系统handler；拒绝URL密码/路径/query，不执行接收到的本地脚本。系统URI触发仍未实现。 |
| R30 | SSH1 长标识缓冲溢出 | [3.2.2 (Official)](https://www.vandyke.com/download/securecrt/3.2/history.txt) L18 / `503d634f217f` | 不提供 SSH1；SSH2 标识/包尺寸仍需独立验证 | SSH1 安全差异；SSH2包测试待做 |
| R31 | SSH1 转发内存增长 | [3.2.1 (Official)](https://www.vandyke.com/download/securecrt/3.2/history.txt) L30 / `63aa7c288368` | 重复创建关闭转发通道、fd/句柄/RSS 趋势收敛 | 仅SSH2；监听/流/半关闭/取消和端口释放已测。旧基线69分钟20428循环零错误后主动中止；最新72小时仍在运行，不能作长期通过结论。 |
| R32 | X11 cookie 与身份校验 | [3.2.1 (Official)](https://www.vandyke.com/download/securecrt/3.2/history.txt) L38 / `9812b5bf3b3c` | cookie 长度、校验、DISPLAY 与恶意连接限制 | 未实现 X11 |
| R33 | SFTP 小块传输提前结束 | [3.2 (Official)](https://www.vandyke.com/download/securecrt/3.2/history.txt) L61 / `b85908d18095` | 随机 1–3 字节分片、EOF、中断和文件校验 | SSH2/SFTP真实服务1–3字节响应往返及提前EOF保护/临时文件清理已测；非供应商原始缺陷复现 |
| R34 | 默认算法变更与升级区分 | [9.7 (Beta 1)](https://www.vandyke.com/products/securecrt/history.txt) L456 / `63baf7224251` | 新安装与升级配置分开测试，已有安全策略不被覆盖 | 策略UI/迁移未实现 |
| R35 | 串口流控默认改变 | [8.7 (Beta 1)](https://www.vandyke.com/download/securecrt/8.7/history.txt) L436 / `700e4c3db557` | XON/XOFF 会消耗控制字节；二进制场景与历史配置显式核验 | 流控配置和驱动参数传递已测，默认none；实体设备、XON/XOFF字节消费及旧配置对照待测 |
| R36 | 百万行历史上限变更 | [9.6 (Beta 1)](https://www.vandyke.com/download/securecrt/9.6/history.txt) L368 / `9e2ca7744c14` | 滚动容量可配置，严格资源预算；大历史查找不阻塞 UI | 当前仅2000行；未实现大历史 |

## 所有历史修复的处理方式

4294 条历史记录均已进入索引，不能只抓含 crash 的行。新增功能、默认值变化、修复、单列安全说明都有独立章节标签。
上表是跨时期、跨子系统的首批明确回归场景，不是把 2873 条 Bug Fixes 全部复现过。语义重复、平台限定、已废弃功能需要逐项归并到功能需求；没有证据的项目保持未验证。
自动故障关键词标签仅用于定位，不用于判断漏洞数量、严重性或 root cause；不少安全相关记录放在普通 Changes/Bug Fixes 中。

## 共同量化要求

- 每个连接/脚本/传输任务有可见状态、取消入口和期限；关闭之后任务数、线程数、端口/句柄数归零或回到稳态。
- SSH、SFTP、终端、日志共享传输时有公平性/背压；某个慢消费者不能饿死其他通道。
- 故障测试保留包/PTY 回放或最小复现、随机种子、平台/依赖版本、运行时长和资源曲线。
- Windows 独立验证设备驱动、DPI、IME、ConPTY、RDP、签名/升级；Linux PTY 和离屏 Qt 测试不能代替它们。
- 对照测试使用相同客户端硬件、服务端、网络扰动、串口适配器和工作负载，才比较断线率、恢复时间与长期资源趋势。
