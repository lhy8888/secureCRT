# SecureCRT 9.7.4 累积功能基线与实现矩阵

目标平台：Windows 10/11。当前实现版本：0.7.0。

结合完整官方历史、功能表、FAQ 和脚本资料。“已验证子集”只表示列出的平台/场景证据，不能扩大为全部Windows设备或与SecureCRT等价。验收条件保持为目标规格，旁列实际实现与限制。

[调研总览](README.md) · [历史覆盖](release-coverage.md) · [可靠性场景](reliability-regressions.md) · [0.7 交付记录](../releases/0.7.md)

183 项能力中，未实现 73 项；没有整体产品等价性验收。

## 1. 连接与协议

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/products/securecrt/faq/index.html)、[来源 3](https://www.vandyke.com/products/securecrt/windows.html)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F01.01 | SSH2 交互会话 | 已验证子集 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 连接真实 SSH 服务，交互输入、stdout/stderr、退出码和远端 EOF 行为一致 |
| F01.02 | IPv4/IPv6 与国际化主机名 | 依赖能力未验证 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | IPv6 字面地址、DNS、IDN、非默认端口均建立连接 |
| F01.03 | 快速连接与 user@host:port 解析 | 已验证子集 | 快捷主机框与CLI解析 user@host:port、带括号IPv6、SSH URI与IDNA；拒绝URL口令/控制符/无效端口。IPv6实际网络与系统URI注册未验收。<br>证据：[tests/test_startup_batch.py](../../tests/test_startup_batch.py) | 正确处理 IPv6 方括号、空输入和转义，不能把提示文案当主机名 |
| F01.04 | 连接参数命令行入口 | 部分实现 | GUI命令行填入目标/会话/密钥路径/认证顺序；显式JSON流程可无界面执行SSH或Serial并写新报告。无命令行密码，未实现完整SecureCRT参数兼容。<br>证据：[tests/test_startup_batch.py](../../tests/test_startup_batch.py) | 命令行可选择会话、协议、主机、用户和新标签，秘密不放命令行 |
| F01.05 | 本地 CMD/PowerShell 会话 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | Windows ConPTY、窗口改变、Ctrl+C 和进程树退出正常 |
| F01.06 | Raw TCP 协议 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 明确标记明文，正确配置 CR/LF 和无仿真收发 |
| F01.07 | Telnet/Telnet-TLS | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 协商、NAWS、字符编码和 TLS 身份校验；明文协议需显式选择 |
| F01.08 | RLogin/TAPI 兼容 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 记录历史兼容范围，启用前明确需求；不作为安全默认值 |
| F01.09 | 无 shell 的 SSH 连接 | 已验证子集 | SSH仅通道模式不请求PTY或Shell，保留SFTP/隧道；拒绝终端发送、BREAK与命令流程。真实服务SFTP成功且远端进程计数为零。<br>证据：[tests/test_startup_batch.py::test_shellless_ssh_retains_sftp_and_never_opens_a_process](../../tests/test_startup_batch.py) | 仅转发或 SFTP 时不请求交互 shell |
| F01.10 | 登录后远端命令 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 按会话配置执行，远端失败可见，不混为本地命令 |
| F01.11 | 重连与退出原因识别 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 用户正常 exit 不重连；网络断线可取消、退避、有上限且不重放输入 |
| F01.12 | 协议 NO-OP 与字符串防空闲 | 部分实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 区分 SSH 保活和向 shell 输入字符；后者显式配置并显示 |
| F01.13 | 分阶段连接状态 | 部分实现 | 跳板/目标连接及交互认证阶段分别显示，认证取消/超时收敛；没有DNS/TCP/KEX全部独立阶段。<br>证据：[tests/test_authentication.py](../../tests/test_authentication.py); [tests/test_jump.py](../../tests/test_jump.py); [tests/test_ssh_ui_integration.py](../../tests/test_ssh_ui_integration.py) | DNS、TCP、KEX、认证、PTY、已连接、关闭、错误状态准确 |
| F01.14 | 顺序与并发批量连接 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 可选串行/并行，上限、取消、单点失败和进度互不污染 |

## 2. 认证、主机信任与凭据

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/products/securecrt/faq/index.html)、[来源 3](https://www.vandyke.com/products/securecrt/new-in.html)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F02.01 | 密码认证 | 已验证子集 | 密码认证及错误拒绝已通过本地SSH服务验证；跳板与目标使用独立密码，诊断不输出服务端异常正文。Windows及MFA另行验收。<br>证据：[tests/test_transport.py::test_bad_password_rejected](../../tests/test_transport.py); [tests/test_jump.py::test_jump_and_target_passwords_are_independent](../../tests/test_jump.py) | 正确密码成功，错误密码拒绝，异常与日志不回显密码 |
| F02.02 | 私钥文件与加密私钥 | 已验证子集 | 新增私钥文件选择与本次口令输入；加密 OpenSSH Ed25519 私钥对真实本地 SSH 服务认证通过。其他格式与硬件验证仍待做。<br>证据：[tests/test_transport.py::test_encrypted_openssh_private_key_authentication](../../tests/test_transport.py) | 图形选择私钥、输入口令、取消和错误口令重试均可用 |
| F02.03 | 默认密钥与 SSH Agent | 部分实现 | 修复显式client_keys=None意外禁用公钥认证；未指定密钥时允许默认密钥/Agent。实际默认密钥签名认证已测，Windows OpenSSH Agent互通未测。<br>证据：[tests/test_startup_batch.py::test_no_explicit_key_selection_does_not_disable_default_public_keys](../../tests/test_startup_batch.py) | 在 Windows OpenSSH Agent 上验证登录、agent 缺失和拒绝 |
| F02.04 | 键盘交互/MFA | 已验证子集 | 真实SSH多轮多提示认证与Qt应答；保留LF、按echo位隐藏输入，跳板/目标分别请求；90秒提示期限、单次UUID回复和轮次/大小上限。取消不回退密码。外部硬件MFA未测。<br>证据：[tests/test_authentication.py](../../tests/test_authentication.py) | 多轮 challenge、多条提示、echo 标记、内嵌 LF 与超时正确 |
| F02.05 | 认证顺序与跳过方法 | 部分实现 | 可保存auto（公钥优先）、密码优先、交互优先、仅公钥、仅交互的固定顺序预设；没有任意方法排序/GSSAPI。<br>证据：[tests/test_authentication.py](../../tests/test_authentication.py); [tests/test_profiles.py](../../tests/test_profiles.py) | 可选择公钥、交互、密码等顺序；取消不继续猜测认证 |
| F02.06 | GSSAPI/Kerberos 与 SPN | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 域环境单点登录、服务主体、MIC 和 secured KEX 单独验证 |
| F02.07 | RSA/Ed25519/ECDSA 密钥 | 已验证子集 | 图形后台生成Ed25519/RSA3072或4096/ECDSA-P256或384，bcrypt128加密OpenSSH及公钥，无覆盖发布；三类真实SSH认证及RSA-SHA2签名已测。私钥检查限制大小/KDF参数；Windows ACL继承目录，非DPAPI，PPK转换及硬件密钥未做。<br>证据：[tests/test_key_tools.py](../../tests/test_key_tools.py); [tests/test_ssh_security_ui.py](../../tests/test_ssh_security_ui.py) | 生成、导入、签名、算法协商与强度策略测试 |
| F02.08 | PPK/PPK3 导入 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 口令、证书键与格式版本识别；畸形文件不导致崩溃 |
| F02.09 | OpenSSH 用户证书 | 部分实现 | 可分别指定一个私钥与一个OpenSSH用户证书，本机检查匹配/类型/有效期，服务器验证CA与principal；错误证书不退回裸公钥。有效/过期/错钥/错principal真实连接已测。Agent组合、完整RSA证书签名矩阵及旧服务兼容未验。<br>证据：[tests/test_ssh_security.py](../../tests/test_ssh_security.py); [harbor_terminal/transport.py](../../harbor_terminal/transport.py) | 证书与私钥可分路径，验证签名算法列表与旧服务兼容 |
| F02.10 | Teleport 证书工作流 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 证书轮换、短期有效期、分离路径及失效提示 |
| F02.11 | X.509/PKCS#12 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 证书链、有效期、私钥匹配和错误口令处理 |
| F02.12 | PKCS#11/CAPI/PIV/CAC | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 多智能卡、PIN 取消、卡移除、raw key 与证书公钥指纹区别 |
| F02.13 | 主机密钥严格校验 | 已验证子集 | 未知/变更密钥拒绝；跳板与目标分别核验已存在的known_hosts文件。没有自动信任或跳过校验选项；证书/CA及密钥管理UI尚未实现。<br>证据：[tests/test_transport.py::test_changed_key_rejected](../../tests/test_transport.py); [tests/test_jump.py::test_untrusted_key_on_either_hop_is_rejected](../../tests/test_jump.py) | 未知与变更密钥拒绝；必须先独立核验 |
| F02.14 | 主机密钥管理界面 | 已验证子集 | 主机公钥库查看/导入/导出/添加/删除、别名/端口/散列模式本地匹配，SHA256指纹与信任范围需勾选核对；修订冲突拒绝覆盖，拒绝私钥输入，无网络扫描或自动信任。复杂企业公钥库仍需互通验收。<br>证据：[tests/test_key_tools.py](../../tests/test_key_tools.py); [tests/test_ssh_security_ui.py](../../tests/test_ssh_security_ui.py) | 可查看 SHA-256 指纹、导入导出、删除、主机别名和端口匹配 |
| F02.15 | OpenSSH Host CA 信任 | 已验证子集 | OpenSSH @cert-authority/@revoked真实验证CA、主机principal、有效期与吊销；有效、错principal、过期、未知CA、吊销CA/主机均有连接回归。未实现X.509/CRL/OCSP或所有证书格式矩阵。<br>证据：[tests/test_ssh_security.py](../../tests/test_ssh_security.py) | CA、主机 principal、有效期、吊销和异常证书均校验 |
| F02.16 | X.509 主机证书校验 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 链可信不等同任意主机可信；主机身份与有效期核实 |
| F02.17 | Agent 生命周期管理 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 显式加/删/预载密钥；退出与锁定策略独立于连接 |
| F02.18 | Agent 转发 | 仅关闭策略 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 默认关闭，逐会话显式授权，服务端滥用边界可见 |
| F02.19 | 凭据管理器 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 共享凭据引用、更新密码、无用户名凭据与每次询问选择 |
| F02.20 | Windows 凭据存储 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 使用 Windows Credential Manager/DPAPI，安全处理锁定与损坏 |
| F02.21 | 个人数据与会话配置分离 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 共享配置不能包含口令、私钥口令和敏感登录脚本 |
| F02.22 | 配置口令与加密迁移 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 强 KDF、唯一盐、认证加密、迁移回滚及坏口令不覆盖数据 |
| F02.23 | 凭据发送到按钮/命令/登录动作 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 只按明确目标发送，操作可取消，不记录秘密 |
| F02.24 | 秘密不落配置或诊断日志 | 已验证子集 | 会话schema5白名单新增策略与证书路径，读取1–4旧版；密码/私钥内容/认证回答不入配置，身份工具输出只有公共信息或路径。命令/流程捕获为用户明文保存，不能存秘密，不宣称Python内存擦除。<br>证据：[tests/test_profiles.py](../../tests/test_profiles.py); [tests/test_key_tools.py](../../tests/test_key_tools.py); [tests/test_ssh_security_ui.py](../../tests/test_ssh_security_ui.py) | 持久化字段白名单拒绝密码；不宣称 Python 内存可可靠擦除 |

## 3. 密码算法与协商策略

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/products/securecrt/faq/index.html)、[来源 3](https://www.vandyke.com/download/securecrt/9.5/history.txt)、[来源 4](https://www.vandyke.com/download/securecrt/9.6/history.txt)、[来源 5](https://www.vandyke.com/products/securecrt/history.txt)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F03.01 | 现代 AEAD/CTR 与 MAC | 部分实现 | 新增会话级cipher/MAC精确顺序，现代默认仅从实际运行库支持的AEAD/CTR及SHA2算法筛选；真实AES128-CTR/SHA2-ETM与默认ChaCha20连接已测，完整算法/服务器矩阵未验。<br>证据：[tests/test_ssh_security.py](../../tests/test_ssh_security.py); [artifacts/harbor-0.7.0-ssh-diagnostics.png](../../artifacts/harbor-0.7.0-ssh-diagnostics.png) | 明确允许集合、协商结果可观察；各算法需实际互通 |
| F03.02 | KEX 选择与排序 | 已验证子集 | 逐会话选择与排序KEX，默认现代曲线/SHA2-DH且按实际依赖能力显示，MLKEM混合可用时加入；真实Curve25519协商与默认MLKEM连接有证据，不静默加入未选算法。其余DH/服务器矩阵未验。<br>证据：[tests/test_ssh_security.py](../../tests/test_ssh_security.py); [artifacts/harbor-0.7.0-ssh-diagnostics.png](../../artifacts/harbor-0.7.0-ssh-diagnostics.png) | 覆盖现代曲线与需要的 DH 组，不静默降级 |
| F03.03 | SHA-2 RSA 与证书算法 | 部分实现 | RSA主机密钥强制rsa-sha2-256真实协商，RSA3072认证在仅允许SHA2-256服务端观测实际签名；公钥格式与签名名称分开展示。Ed25519证书连接已测，完整RSA cert-v01和旧服务矩阵未验。<br>证据：[tests/test_ssh_security.py](../../tests/test_ssh_security.py); [tests/test_key_tools.py](../../tests/test_key_tools.py) | 验证 rsa-sha2 与 cert-v01 协商，尊重 server-sig-algs |
| F03.04 | Strict KEX/Terrapin 防护 | 已验证子集 | 默认认证前要求Strict KEX；真实双方协商、非Strict服务器拒绝且零密码发送、显式兼容、KEXINIT前注入合法IGNORE包失败已测。AsyncSSH2.24.1元数据适配器版本固定，未知版本强制模式拒绝；非完整Terrapin攻击语料验收。<br>证据：[tests/test_ssh_security.py](../../tests/test_ssh_security.py) | 验证双方协商 Strict KEX；不能由库版本或安装成功推断安全 |
| F03.05 | 弱算法兼容策略 | 已验证子集 | 旧算法需单会话许可且逐个显式选入，空列表仍现代默认；GUI含跳板范围提示且默认取消，批处理额外显式开关。受控仅旧算法服务器先拒绝再显式连接已测。不支持group1/RC4/MD5。<br>证据：[tests/test_ssh_security.py](../../tests/test_ssh_security.py); [tests/test_ssh_security_ui.py](../../tests/test_ssh_security_ui.py); [tests/test_startup_batch.py](../../tests/test_startup_batch.py) | 按单会话启用并显示；不得全局自动恢复过时算法 |
| F03.06 | 重协商/Rekey | 已验证子集 | 字节/秒数阈值可配置；分别以4096字节与1秒触发实际NEWKEYS，512KiB二进制往返完整。长期真实设备负载、断网及重协商交叉场景未全面验收。<br>证据：[tests/test_ssh_security.py](../../tests/test_ssh_security.py) | 长连接按时间/字节重协商，过程中不丢输入或死锁 |
| F03.07 | 认证后压缩 | 已验证子集 | 默认none，只允许认证后zlib@openssh.com；观测认证前未启用、真实压缩协商和二进制往返。认证前zlib策略拒绝，完整负载/服务器矩阵未验。<br>证据：[tests/test_ssh_security.py](../../tests/test_ssh_security.py); [harbor_terminal/ssh_policy.py](../../harbor_terminal/ssh_policy.py) | 支持需要的 delayed compression，认证前不缓存未加密秘密 |
| F03.08 | FIPS 工作模式 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 需明确经验证模块及适用平台；算法选择不等同 FIPS 认证 |
| F03.09 | 畸形 SSH/KEX 包 | 部分实现 | 增加超大/截断SSH包与Strict KEX前额外包注入，验证受控失败且进程继续执行后续测试。没有完整协议fuzz语料或SecureCRT私有问题样本，不能宣称全部恶意KEX已修复。<br>证据：[tests/test_ssh_security.py](../../tests/test_ssh_security.py) | 协议库 fuzz/故障注入验证；终端转义过滤不能替代 SSH 包校验 |
| F03.10 | SSH1 兼容记录 | 安全差异 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 列入差异清单，但新安全客户端默认不提供 SSH1 |

## 4. 代理、跳板与转发

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/products/securecrt/faq/index.html)、[来源 3](https://www.vandyke.com/download/securecrt/7.1/history.txt)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F04.01 | 多级 SSH 跳板与依赖会话 | 部分实现 | 实现单级跳板，引用已保存SSH会话；跳板与目标各自认证和核验known_hosts，失败/取消关闭两端；拒绝缺失、递归及多级引用。多跳拓扑、依赖会话复用尚未实现。<br>证据：[tests/test_jump.py](../../tests/test_jump.py); [scripts/capture_services.py](../../scripts/capture_services.py) | 拓扑顺序连接、循环检测、逐跳身份校验、断开级联 |
| F04.02 | 命名防火墙与代理配置 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 共享命名配置修改后引用仍正确；可逐会话选择 |
| F04.03 | SOCKS4/5 连接代理 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 认证、DNS 位置、IPv6、错误和取消正确 |
| F04.04 | HTTP CONNECT 代理 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 认证响应、非 200、连接头和二进制数据边界正确 |
| F04.05 | ProxyCommand 本地代理 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 不用 shell 拼接输入；限制进程树、输出与超时 |
| F04.06 | 本地端口转发 | 已验证子集 | 自有回环监听在Windows绑定前启用SO_EXCLUSIVEADDRUSE，修复已复现的重复绑定；Linux/Windows真实二进制转发、半关闭、SSH断开清理。停止监听保留已有流；每会话转发流总额64。<br>证据：[tests/test_forwarding.py](../../tests/test_forwarding.py); [tests/test_service_panels.py](../../tests/test_service_panels.py) | 默认回环监听，绑定失败提示，关闭后释放端口 |
| F04.07 | 远程端口转发 | 已验证子集 | 远程转发明确目标与端口，服务端监听请求固定127.0.0.1；真实字节往返和停止释放已测。服务端可覆盖监听策略，客户端无法证明实际网卡绑定；Windows/不同SSH服务待测。<br>证据：[tests/test_forwarding.py::test_real_forward_roundtrip_and_stop_releases_listening_port](../../tests/test_forwarding.py) | 目标、监听地址、服务器拒绝与断线释放可验证 |
| F04.08 | 动态 SOCKS 转发 | 部分实现 | 自有SOCKS5 CONNECT支持IPv4/域名/IPv6解析，固定127.0.0.1；实际域名和IPv4、拒绝认证/非法请求、握手超时/取消、半关闭已测。不支持代理认证；IPv6网络互通和长期并发待验收。<br>证据：[tests/test_forwarding.py](../../tests/test_forwarding.py) | 认证/地址类型/并发连接/取消无泄漏 |
| F04.09 | 转发条目增删复制禁用 | 部分实现 | 窗口支持建立、列出和停止当前会话的监听；每会话最多16个，请求队列最多8项。关闭管理窗口保留监听，断开SSH关闭转发；停止监听可能保留已有流。复制/禁用模板、持久化与导入未实现。<br>证据：[tests/test_forwarding.py::test_listener_capacity_is_bounded_and_all_owned_ports_are_released](../../tests/test_forwarding.py); [tests/test_service_panels.py::test_forward_dialog_operates_real_tcp_and_disconnect_releases_listener](../../tests/test_service_panels.py) | 禁用动态条目不能破坏依赖连接，导入不丢转发 |
| F04.10 | X11 转发 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | DISPLAY/cookie 校验、X server 缺失与连接关闭处理 |
| F04.11 | 端口转发启动本地应用 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 仅用户授权的固定程序和参数，连接失败不误启动 |

## 5. 终端仿真、渲染与国际化

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/download/securecrt/9.6/history.txt)、[来源 3](https://www.vandyke.com/products/securecrt/history.txt)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F05.01 | VT100/102/220/320 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 设备属性、滚动区、边距、制表和状态行按回放比较 |
| F05.02 | Xterm/ANSI/Linux/SCO | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 逐仿真选择能力，不能将所有模式映射成同一字符串 |
| F05.03 | Wyse50/60、TVI910/925 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 专用键、分页、行属性和控制序列回放 |
| F05.04 | TN3270 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 字段保护、插入/覆盖、Transmit 和长粘贴不得越界 |
| F05.05 | 16/256/24位真彩色 | 已验证子集 | Qt 网格实际绘制 16/256/24位色；SGR 属性检查与离屏像素测试通过。仍未完成目标 TUI 兼容回放。<br>证据：[tests/test_terminal_model.py](../../tests/test_terminal_model.py); [tests/test_terminal_widget.py::test_grid_paints_truecolor_background_and_resizes](../../tests/test_terminal_widget.py) | GUI 显示颜色而非仅解析；SGR 组合和调色板对照 |
| F05.06 | 粗体/下划线/反色/闪烁 | 部分实现 | 已绘制粗体、斜体、下划线、删除线和反色；字符闪烁未实现。<br>证据：[tests/test_terminal_model.py::test_truecolor_256_color_and_character_attributes](../../tests/test_terminal_model.py) | 属性组合、重置、历史与选择复制保留正确 |
| F05.07 | VT 线绘制与 NRCS | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 特殊字符集切换、复制和字体回退一致 |
| F05.08 | 双宽/双高行 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | Windows 字形尺寸、光标和选区对照 |
| F05.09 | UTF-8 分片与 Unicode | 已验证子集 | UTF-8 增量解码、CJK 双格、组合字符与复制有测试；每格最多32码点。RTL/emoji 字素与跨平台字体未完成。<br>证据：[tests/test_terminal_model.py](../../tests/test_terminal_model.py); [tests/test_terminal_widget.py](../../tests/test_terminal_widget.py) | 增量解码不截断；宽字符、组合字符、双向文字另需验证 |
| F05.10 | GBK/GB2312/Big5/Shift-JIS 等编码 | 部分实现 | 界面可选 UTF-8/GB18030/Big5/Shift-JIS/Latin-1；GB18030 发送样例验证。尚未完成实际各编码终端互通。<br>证据：[tests/test_keyboard.py::test_altgr_printable_text_and_non_utf8](../../tests/test_keyboard.py) | 输入输出编码可选择，错误替换和分片一致 |
| F05.11 | 中文输入法 IME | 部分实现 | Qt preedit 显示、提交发送与候选位置接口已实现；模拟 IME 事件测试通过，Windows 真实输入法尚未验证。<br>证据：[tests/test_terminal_widget.py::test_ctrl_c_arrows_function_keys_and_ime_commit](../../tests/test_terminal_widget.py) | Windows composition/commit 正常，远端只收到一次提交 |
| F05.12 | 80/132 列与动态行列 | 部分实现 | 按可见像素计算网格并通知远端 PTY，范围8–512列、2–200行；80/132 列模式完整切换尚未验收。<br>证据：[tests/test_ssh_ui_integration.py](../../tests/test_ssh_ui_integration.py); [tests/test_transport.py::test_real_ssh_terminal_size_changes_reach_server](../../tests/test_transport.py) | 终端格数、实际视图、PTY size 同步 |
| F05.13 | 窗口改变与重排 | 部分实现 | 修复缩短高度时首行/提示行被无条件裁掉的问题，移出的行进入历史；横向缩短仍会裁切单元格，未实现软换行重排。<br>证据：[tests/test_terminal_model.py::test_shrinking_height_preserves_visible_prompt_and_retains_scrolled_rows](../../tests/test_terminal_model.py) | 滚动历史、宽字符和软换行 resize 不丢失/重复 |
| F05.14 | 备用屏幕与主屏幕 | 已验证子集 | 47/1047/1049 备用网格与主网格分离，1049 保存/恢复光标，重复进入不累积状态；未运行全量 vim/tmux/top 回放。<br>证据：[tests/test_terminal_model.py::test_alternate_screen_does_not_pollute_main_or_grow_cursor_stack](../../tests/test_terminal_model.py) | vim/tmux/top 进退恢复，滚动历史策略明确 |
| F05.15 | 百万行滚动缓冲 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 9.6 历史上限变更单列；容量、内存预算和查找需实测 |
| F05.16 | 屏幕/历史查找 | 部分实现 | 提供字面文本高亮、向前/向后循环查找，最多1000个命中；无正则/大小写选项与百万行索引。<br>证据：[tests/test_terminal_widget.py::test_wide_character_copy_and_literal_search_do_not_rewrite_output](../../tests/test_terminal_widget.py) | 方向、大小写、正则、Unicode、长行和取消 |
| F05.17 | OSC 标题/颜色与安全策略 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 按序列白名单；标题、颜色与 OSC52 不混成同一权限 |
| F05.18 | 远端剪贴板 OSC52 | 已验证子集 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 默认禁用；可选授权需限长与用户可见 |
| F05.19 | 有界控制序列解析 | 已验证子集 | 除CSI/控制串限长外，保存光标栈限制16项、组合字符限制32码点、每次feed估算操作预算20万；异常停止会话。不是通用CPU/内存隔离。<br>证据：[tests/test_terminal_stream.py](../../tests/test_terminal_stream.py); [tests/test_terminal_model.py](../../tests/test_terminal_model.py); [tests/test_ui.py](../../tests/test_ui.py) | 未结束控制串不累计，CSI 限长，异常关闭连接 |
| F05.20 | DCS/图形/终端扩展差异 | 安全差异 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 记录当前全部丢弃的兼容性损失，不算全 Xterm 支持 |
| F05.21 | 光标形状、闪烁与可访问性 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 本地选择与远端控制状态一致，屏幕阅读器能跟踪 |
| F05.22 | 滚动清除策略 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 区分清屏/清历史，允许保留历史策略 |
| F05.23 | 字体/缩放/DPI/行间距 | 部分实现 | 默认优先Consolas11pt，界面Segoe UI9pt；按已安装等宽字体回退。字体/字号选择独立保存并应用所有标签，按真实advance绘制，调整字格/PTY；Ctrl+滚轮临时缩放当前标签。Windows高DPI/多显示器和可配置行距尚未验收。<br>证据：[tests/test_desktop.py::test_font_and_color_changes_preserve_screen_and_resize_real_ssh](../../tests/test_desktop.py); [scripts/capture_services.py](../../scripts/capture_services.py) | 多显示器切换、125%–300%、缩放后光标与行列一致 |
| F05.24 | 界面深浅色与会话主题 | 部分实现 | 实现全局经典浅色/深色界面及黑底/浅色/深蓝终端，独立显示偏好存储；已采集两种UI主题并验证配色变化保持屏幕内容。逐会话主题、完整系统跟随和Windows原生验证待做。<br>证据：[tests/test_desktop.py](../../tests/test_desktop.py); [scripts/capture_services.py](../../scripts/capture_services.py) | 系统主题和自定义会话主题互不错误覆盖 |

## 6. 键盘、鼠标与剪贴板

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/download/securecrt/8.3/history.txt)、[来源 3](https://www.vandyke.com/download/securecrt/8.5/history.txt)、[来源 4](https://www.vandyke.com/download/securecrt/9.4/history.txt)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F06.01 | 逐会话键盘映射 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 任意组合键映射字符串/菜单/命令，编辑器可导出 |
| F06.02 | Xterm216+/R6/VT 键盘模式 | 部分实现 | 支持普通/应用光标、数字小键盘模式与常用 xterm 修饰键；未实现完整 Xterm216+/R6/VT 键盘配置。<br>证据：[tests/test_keyboard.py](../../tests/test_keyboard.py); [tests/test_terminal_model.py::test_application_keypad_mode_switches_from_escape_sequences](../../tests/test_terminal_model.py) | 应用光标/数字小键盘、修饰键和模式切换 |
| F06.03 | F1–F24/Home/End/Insert/Delete | 部分实现 | F1–F12、Home/End/Insert/Delete/PageUp/PageDown、方向键和修饰键已有编码；F13–F24 和图形键映射待实现。<br>证据：[tests/test_keyboard.py](../../tests/test_keyboard.py); [tests/test_terminal_widget.py](../../tests/test_terminal_widget.py) | 修饰键、功能键在目标终端编码一致 |
| F06.04 | Emacs Alt Meta | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | Alt/AltGr 与国际键盘区别，不能吞掉输入法 |
| F06.05 | 鼠标跟踪与滚轮 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 远端 mouse reporting 与 Shift 本地操作切换 |
| F06.06 | 字符/词/行/矩形选择 | 部分实现 | 网格行内/跨行拖选、CJK stub 选择与普通复制；词/矩形选择和自动复制尚未实现。<br>证据：[tests/test_terminal_widget.py::test_wide_character_copy_and_literal_search_do_not_rewrite_output](../../tests/test_terminal_widget.py) | 宽字符、末尾换行、自动复制和鼠标拖选一致 |
| F06.07 | ANSI 格式复制 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 普通文本与带色复制分开，字体和颜色可信 |
| F06.08 | 多行粘贴保护 | 已验证子集 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 多行输入必须确认，控制字符拒绝 |
| F06.09 | 粘贴预览与编辑 | 已验证子集 | 多行确认框可编辑并调整大小，编辑后重新校验控制字符/大小；取消不发送。换行策略仍为固定规则。<br>证据：[tests/test_terminal_widget.py::test_edited_paste_is_revalidated_and_remote_bracket_mode_is_honored](../../tests/test_terminal_widget.py) | 确认框可以编辑内容、调整大小并选择换行策略 |
| F06.10 | Bracketed Paste | 已验证子集 | 仅在远端启用2004模式时包裹粘贴，拒绝ESC/C1控制字符与过大数据；有编码/终止符回归。<br>证据：[tests/test_keyboard.py](../../tests/test_keyboard.py); [tests/test_terminal_widget.py](../../tests/test_terminal_widget.py) | 只在远端已启用模式时包裹；内部粘贴终止符不能逃逸 |
| F06.11 | 右键/中键/Shift-Insert 粘贴 | 部分实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 所有入口都经过相同检查，无默认菜单旁路 |
| F06.12 | 逐字/逐行发送延迟 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 慢串口不丢字，可等待特定提示再发送下一行 |
| F06.13 | 发送 BREAK/控制键 | 部分实现 | 新增250ms BREAK操作，通过专用控制队列调用SSH/串口接口；真实串口电平和SSH服务端 BREAK 尚未验收。<br>证据：[harbor_terminal/session.py](../../harbor_terminal/session.py); [harbor_terminal/transport.py](../../harbor_terminal/transport.py) | SSH break 与串口 break 有协议区别；持续时间有上限 |
| F06.14 | 引号粘贴、路径粘贴和换行规则 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 明确数据变换，不在用户无感情况下执行本地命令 |

## 7. 串口与设备操作

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/download/securecrt/9.6/history.txt)、[来源 3](https://www.vandyke.com/products/securecrt/history.txt)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F07.01 | COM 设备枚举 | 部分实现 | 后台调用系统设备枚举，可手填设备；测试确认不按COM数字过滤Moxa/虚拟COM样例。真实Windows驱动未验证。<br>证据：[tests/test_serial_settings.py::test_vendor_virtual_port_inventory_is_not_filtered_by_name](../../tests/test_serial_settings.py) | 显示真实设备、友好名称、USB标识；支持 Moxa/虚拟 COM |
| F07.02 | 波特率/数据位/校验/停止位 | 部分实现 | 可配置50–4,000,000 baud、5–8数据位、N/E/O/M/S、1/1.5/2 stopbits；参数验证/传入驱动测试通过，物理参数互通待测。<br>证据：[tests/test_serial_settings.py](../../tests/test_serial_settings.py); [tests/test_transport.py](../../tests/test_transport.py) | 常见 5–8 位及 N/E/O/M/S、1/1.5/2 stopbits 与驱动验证 |
| F07.03 | 硬件与软件流控 | 部分实现 | none/RTSCTS/DSRDTR/XONXOFF四种互斥选择已接入配置及驱动参数；没有进行实际握手电平验证。<br>证据：[tests/test_serial_settings.py](../../tests/test_serial_settings.py) | RTS/CTS、DSR/DTR、XON/XOFF 可选且互斥规则明确 |
| F07.04 | DTR/RTS 控制与调制解调状态 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 可操作线路并观察 CTS/DSR/RI/CD；注明复位副作用 |
| F07.05 | 串口读写与字节流分片 | 已验证子集 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 部分读取累计，部分写入报错，读写超时 |
| F07.06 | 串口连接取消与独占占用 | 部分实现 | 连接取消与资源关闭路径已整理，实际PTY和模拟阻塞连接测试通过；无法宣称可强制终止挂死的Windows驱动调用。<br>证据：[tests/test_session.py](../../tests/test_session.py); [tests/test_transport.py](../../tests/test_transport.py) | 无设备、被占用、驱动无响应时可取消且资源收敛 |
| F07.07 | 热拔插与重枚举 | 部分实现 | 独立只读诊断观察移除/返回，优先按唯一设备序列号跟随端口改名，重复序列号拒绝判断；无序列号仅按端口名。枚举模拟已测；实体Windows拔插未执行，未实现自动重连。<br>证据：[tests/test_diagnostics.py](../../tests/test_diagnostics.py); [docs/windows-hardware-testing.md](../../docs/windows-hardware-testing.md) | 识别设备身份变更，不自动把命令发给另一设备 |
| F07.08 | 按协议保存串口默认值 | 已验证子集 | defaults.json中SSH/Serial默认值独立保存，切协议或新建连接时应用；已有v1–v4会话按原参数载入，不随模板变更。实际Qt模板/串口切换回归通过。<br>证据：[tests/test_session_management_ui.py::test_protocol_templates_do_not_rewrite_existing_sessions_and_detect_conflicts](../../tests/test_session_management_ui.py) | 串口默认与 SSH 默认分离；升级不改已有配置 |
| F07.09 | Hex/ASCII 双视图 | 部分实现 | 串口Hex/ASCII同窗显示方向、UTC时间和偏移；32KiB/256条上限并显示丢弃量；无双向联动选区。<br>证据：[tests/test_trace.py](../../tests/test_trace.py); [tests/test_service_panels.py](../../tests/test_service_panels.py) | 逐会话双向数据带方向和偏移，选择联动，二进制不转码 |
| F07.10 | 十六进制/二进制发送 | 已验证子集 | Hex最多4096原始字节发送，不追加换行，不重试；真实PTY收发、标签切换固定目标和部分写入观察有测试。<br>证据：[tests/test_service_panels.py](../../tests/test_service_panels.py); [tests/test_session.py](../../tests/test_session.py) | 精确发送字节，包括 NUL/0xFF，不走 UTF-8 编码 |
| F07.11 | Windows 命名管道 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 虚拟机串口管道读写、断开和取消 |
| F07.12 | 串口故障与持续流量 | 部分实现 | 显式回环检测逐帧验证全部字节、超时/短写失败无重放，报告资源/延迟；Unix PTY实际通过。Windows包包含72小时实体测试入口，但未取得实体报告，未验证挂死驱动恢复。<br>证据：[tests/test_diagnostics.py](../../tests/test_diagnostics.py); [docs/windows-hardware-testing.md](../../docs/windows-hardware-testing.md) | 实体适配器矩阵、长期压力、拔插、睡眠唤醒 |

## 8. 会话数据库与布局

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/products/securecrt/faq/index.html)、[来源 3](https://www.vandyke.com/download/securecrt/6.2/history.txt)、[来源 4](https://www.vandyke.com/download/securecrt/7.3/history.txt)、[来源 5](https://www.vandyke.com/download/securecrt/9.2/history.txt)、[来源 6](https://www.vandyke.com/download/securecrt/9.6/history.txt)、[来源 7](https://www.vandyke.com/products/securecrt/history.txt)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F08.01 | 保存基本会话 | 已验证子集 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 主机、端口、用户和 known_hosts 可保存，不写密码 |
| F08.02 | 层级会话树/描述/自然排序 | 部分实现 | 层级树和管理对话框支持会话/文件夹路径重命名，大小写冲突拒绝，单JSON事务更新所有跳板引用；可选依赖范围删除。不支持拖放、描述和自然排序。<br>证据：[tests/test_profile_operations.py](../../tests/test_profile_operations.py); [harbor_terminal/session_manager.py](../../harbor_terminal/session_manager.py) | 目录、复制移动、重命名、大小写冲突和持久化 |
| F08.03 | 按会话/主机/目录/描述过滤 | 部分实现 | 支持按会话路径、主机、用户名的不区分大小写子串过滤；描述、通配符和大型数据库索引待实现。<br>证据：[tests/test_terminal_widget.py::test_saved_session_tree_filters_nested_profiles](../../tests/test_terminal_widget.py) | 通配符、输入节流、大量会话与无结果状态 |
| F08.04 | 批量编辑会话 | 已验证子集 | 固定选择范围，只修改明确勾选字段，空值须勾选；协议切换保留未勾选字段，跨协议参数不合法则整体拒绝。预览原/新值后CAS提交，取消无写入。<br>证据：[tests/test_profile_operations.py::test_batch_changes_are_atomic_and_unselected_fields_and_profiles_are_preserved](../../tests/test_profile_operations.py); [tests/test_session_management_ui.py](../../tests/test_session_management_ui.py) | 只修改显式变化的字段，协议切换保留无关配置 |
| F08.05 | 默认会话模板 | 已验证子集 | 独立SSH/Serial默认模板编辑与并发保护；新建连接采用模板，已有会话不自动改写。批量编辑可填入模板，再明确勾选字段/范围与预览。不包含全套SecureCRT默认选项。<br>证据：[harbor_terminal/session_templates.py](../../harbor_terminal/session_templates.py); [tests/test_session_management_ui.py](../../tests/test_session_management_ui.py) | 应用到已有会话需要范围确认；支持按协议默认 |
| F08.06 | 连接/重连/克隆/复用传输 | 部分实现 | 当前连接保存非秘密参数快照，克隆/手动重连只载入快速连接并要求本次凭据；各标签独立SSH连接，关闭克隆不误断原连接。无传输复用或自动重连；跳板引用按当前保存配置解析。<br>证据：[tests/test_session_management_ui.py::test_clone_is_independent_and_requires_fresh_credentials_and_lock_guards_input](../../tests/test_session_management_ui.py) | 标签身份与底层连接生命周期分离，关闭一个不误断其他 |
| F08.07 | 活动会话管理器 | 已验证子集 | 活动列表支持名称/主机/状态筛选、状态计数、多选及固定目标预览后的批量断开/输入锁；状态刷新保留UUID选择。输入锁只防误触，不是口令安全锁。<br>证据：[harbor_terminal/desktop.py::active_sessions_action](../../harbor_terminal/desktop.py); [tests/test_session_management_ui.py](../../tests/test_session_management_ui.py) | 筛选、活动标志、状态计数与批量断开/锁定 |
| F08.08 | 标签组、平铺和层叠 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 侧对侧监控、拖动分组、缩放/焦点不丢失 |
| F08.09 | 分离窗口/跨窗口拖放 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 保持连接、标签顺序和资源归属 |
| F08.10 | 工作区快照 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 保存会话集合、组/平铺/顺序，恢复布局精确 |
| F08.11 | 自动会话与上次会话恢复 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 启动时可取消；恢复配置不自动重放命令 |
| F08.12 | 最近会话/临时标签名 | 部分实现 | 可临时重命名当前标签，活动列表、窗口标题和命令目标标签同步；不改保存会话或连接参数。最近会话列表尚未实现。<br>证据：[harbor_terminal/app.py::rename_tab](../../harbor_terminal/app.py); [tests/test_session_management_ui.py](../../tests/test_session_management_ui.py) | 去重、大小写和真实会话重命名不丢数据 |
| F08.13 | 会话锁定 | 部分实现 | 单会话/批量输入锁阻止新手动键入、粘贴、Hex、BREAK和新流程，保留输出与复制；已启动流程继续。自动DA/DSR应答使用独立有界队列，不因锁或流程断开。无口令验证/隐藏输出的安全锁。<br>证据：[tests/test_session_management_ui.py](../../tests/test_session_management_ui.py); [tests/test_automation.py::test_cancelled_flow_is_not_written_after_an_awaited_protocol_reply](../../tests/test_automation.py) | 防误输入与安全锁定明确区分；锁定/隐藏输出需要验证 |
| F08.14 | 连接/活动/静默/脚本状态 | 部分实现 | 窄标签以图标区分连接/断开/处理中，提示和状态栏显示详细状态；真实连接、关闭和口令取消已测。活动会话列表同步连接状态，无静默/脚本/新活动提示。<br>证据：[tests/test_desktop.py](../../tests/test_desktop.py); [tests/test_ssh_ui_integration.py](../../tests/test_ssh_ui_integration.py); [harbor_terminal/app.py](../../harbor_terminal/app.py) | 底层失败不能显示 Connected；每标签状态不串线 |
| F08.15 | CSV/TSV 导入 | 已验证子集 | CSV/TSV显式列映射、UTF-8/GB18030/UTF-16、引号/中文、选择行、端口验证及500项限制；凭据/未知列默认忽略，不带值记录。重复名称/不支持协议拒绝。<br>证据：[tests/test_profile_operations.py](../../tests/test_profile_operations.py); [tests/test_session_management_ui.py](../../tests/test_session_management_ui.py) | 列映射、转义、多语言、端口范围和重复处理 |
| F08.16 | XML 配置导入导出 | 部分实现 | 所选会话可导入/导出Harbor原生XML/JSON，字段白名单、DTD/entity/深度/节点/重复字段与畸形Unicode拒绝，原子保存。不是SecureCRT专有XML导入；不导入全局项、转发模板或凭据库。<br>证据：[tests/test_profile_operations.py](../../tests/test_profile_operations.py); [harbor_terminal/session_manager.py::export_selected](../../harbor_terminal/session_manager.py) | 范围可选、全局/会话/转发不丢失，敏感项显式选择 |
| F08.17 | 导入冲突策略 | 已验证子集 | 仅新增、替换、合并已提供字段、复制四种策略；复制时重写批内跳板引用，大小写歧义拒绝。冻结预览、取消不写、版本冲突要求重新载入，已有连接不改变。<br>证据：[tests/test_profile_operations.py](../../tests/test_profile_operations.py); [tests/test_session_management_ui.py](../../tests/test_session_management_ui.py) | 覆盖/合并/复制/仅新增，预览后原子应用 |
| F08.18 | 配置备份/迁移/只读模式 | 部分实现 | 每次会话/模板成功替换前保留上次有效备份，损坏/不支持原文件不覆盖；会话恢复预览同时核对目标与备份版本并保留damaged副本。原生v1–v4读取；无SecureCRT迁移或完整只读模式。<br>证据：[tests/test_profile_transactions.py](../../tests/test_profile_transactions.py); [tests/test_session_management_ui.py::test_recovery_previews_exact_backup_and_preserves_damaged_original](../../tests/test_session_management_ui.py) | 坏文件、旧版本、只读介质迁移失败不丢原数据 |
| F08.19 | 跨平台路径与环境变量 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 路径展开、个人数据位置、不可用驱动器与旧设置迁移 |
| F08.20 | 配置并发与事务 | 部分实现 | OS跨进程锁、内容SHA修订、同一文件乐观并发控制、临时文件fsync/替换及最后有效备份。两个本版本窗口冲突拒绝；锁持有进程退出后可继续；目录fsync失败明确待确认。无跨文件或分布式事务保证。<br>证据：[tests/test_profile_transactions.py](../../tests/test_profile_transactions.py); [tests/test_session_management_ui.py](../../tests/test_session_management_ui.py) | 多窗口同时编辑、崩溃中断与备份恢复一致 |

## 9. 命令工作流与自动化

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/support/securecrt/scripting_faq.html)、[来源 3](https://www.vandyke.com/support/securecrt/python_examples.html)、[来源 4](https://www.vandyke.com/download/securecrt/6.0/history.txt)、[来源 5](https://www.vandyke.com/download/securecrt/6.1/history.txt)、[来源 6](https://www.vandyke.com/products/securecrt/history.txt)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F09.01 | 命令窗口与历史 | 部分实现 | Alt+M打开多行命令面板、本窗口最近50条历史、显式选目标及可编辑预览；历史无检索/持久化。<br>证据：[tests/test_workflow_panel.py](../../tests/test_workflow_panel.py) | 编辑多行、历史检索、活动/可见/选组/全部目标 |
| F09.02 | 多会话命令广播 | 已验证子集 | 逐会话勾选，预览固定目标及编码；切换标签/新增连接不自动改发送目标，分别列入队结果，无重试。真实两个SSH/Qt验证。没有即时字符广播。<br>证据：[tests/test_workflow_panel.py](../../tests/test_workflow_panel.py) | 明确展示目标列表，锁定或断开会话排除，高危命令确认 |
| F09.03 | 即时字符广播 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | Ctrl+C、Tab 补全和编辑器按键逐会话一致 |
| F09.04 | 按钮栏与按钮管理 | 部分实现 | 保存命令可固定到按钮栏；按钮仅发当前交互会话并再次预览，不沿用上次广播目标。没有多组按钮栏/完整自定义动作。<br>证据：[tests/test_workflow_panel.py](../../tests/test_workflow_panel.py); [harbor_terminal/desktop.py](../../harbor_terminal/desktop.py) | 多栏、复制/排序/颜色/说明、按会话分配 |
| F09.05 | 命令管理器 | 部分实现 | 独立明文commands.json原子保存、筛选、增删、置顶；最多200条，损坏文件保护。没有文件夹/秘密引用/命令库同步。<br>证据：[tests/test_automation.py](../../tests/test_automation.py); [tests/test_workflow_panel.py](../../tests/test_workflow_panel.py) | 分层保存、过滤、按钮栏互换及命令描述 |
| F09.06 | Expect/Send 登录动作 | 部分实现 | 手动或CLI启动声明式send/wait/delay流程，跨分片增量解码匹配，超时/取消不继续发送。未自动绑定登录动作，也无凭据引用或SecureCRT脚本兼容。<br>证据：[tests/test_automation.py](../../tests/test_automation.py); [tests/test_authentication.py](../../tests/test_authentication.py); [tests/test_workflow_panel.py](../../tests/test_workflow_panel.py) | 跨 read 边界匹配、超时、顺序、编码和取消 |
| F09.07 | 等待提示发送 | 已验证子集 | 独立有界接收流等待字面提示，按最早位置/候选顺序匹配；流与GUI渲染互不消费。游标被覆盖立即错误，不静默继续；断开/取消释放等待者。<br>证据：[tests/test_automation.py](../../tests/test_automation.py) | 无提示不能无限等待；等待状态可见，不重复发送 |
| F09.08 | Python 脚本与对象模型 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | Screen/Session/Tab/Config/Clipboard/Dialog 等逐方法规格 |
| F09.09 | Screen.Send/WaitFor/ReadString | 部分实现 | Harbor JSON流程提供发送、等待、捕获匹配前文本与候选编号；保留匹配后尾部。无crt.Screen对象、IgnoreCase或完整ReadString兼容。<br>证据：[tests/test_automation.py](../../tests/test_automation.py); [tests/test_startup_batch.py](../../tests/test_startup_batch.py) | 同步模式、忽略大小写、超时、取消与消费语义明确 |
| F09.10 | 脚本和标签生命周期 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 脚本目标固定，切换标签不误发；连接成功后才启动 |
| F09.11 | Python 版本/架构与模块 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | Windows 嵌入或外置运行时、签名、位数和更新测试 |
| F09.12 | VBScript/JScript/PerlScript | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | Windows ActiveX 兼容需求单列，不由 Python 支持推断 |
| F09.13 | 脚本参数、状态与错误 | 部分实现 | JSON流程有步骤/状态/错误、600秒总期限、每Worker一个流程，取消清理尚未发送队列；不执行本地Python/eval。不是通用脚本参数/API系统。<br>证据：[tests/test_automation.py](../../tests/test_automation.py); [tests/test_workflow_panel.py](../../tests/test_workflow_panel.py) | 参数不经 shell 拼接；异常有位置，取消收敛 |
| F09.14 | 脚本录制 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 特殊键、反斜杠、Unicode 正确转义，秘密不被录制 |
| F09.15 | 脚本编辑器 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 语法高亮、查找、保存和运行目标选择 |
| F09.16 | 启动前本地程序/端口敲门 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 明确授权，不允许远端控制序列触发本地执行 |
| F09.17 | 自动化 CLI 与批处理 | 部分实现 | 显式--run-flow/--output无GUI执行SSH密钥/Agent或Serial，主机严格校验、独立接收、JSON结果和退出码。已测真实SSH及Unix PTY；无CLI交互MFA/密钥口令。<br>证据：[tests/test_startup_batch.py](../../tests/test_startup_batch.py); [harbor_terminal/batch.py](../../harbor_terminal/batch.py) | 可预测退出码、非交互、超时和机器可读结果 |

## 10. 文件传输

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/download/securecrt/5.0/history.txt)、[来源 3](https://www.vandyke.com/download/securecrt/7.1/history.txt)、[来源 4](https://www.vandyke.com/products/securecrt/history.txt)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F10.01 | 复用连接的 SFTP | 已验证子集 | 新增SFTP独立窗口，复用现有SSH连接，不重新认证；文件任务与终端任务独立。<br>证据：[tests/test_sftp.py](../../tests/test_sftp.py); [tests/test_service_panels.py](../../tests/test_service_panels.py) | 终端和 SFTP 通道独立，取消不误断终端 |
| F10.02 | 独立 SFTP 会话 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 直接登录无需 shell，继承主机信任和认证策略 |
| F10.03 | 远程目录与文件管理 | 部分实现 | 目录浏览、上级导航、类型/大小/时间；最多2000项/2MiB名称。尚无远程修改、删除与递归操作。<br>证据：[tests/test_sftp.py::test_directory_inventory_is_bounded_and_contains_types](../../tests/test_sftp.py) | 列目录/过滤/改名/删除/递归操作和权限正确 |
| F10.04 | 上传下载、递归与属性 | 部分实现 | 单文件二进制/中文路径上传下载及SHA-256回读验证；无递归、元数据保留和符号链接工作流。上传0600，覆盖替换元数据。<br>证据：[tests/test_sftp.py](../../tests/test_sftp.py) | 二进制完整性、mtime/权限、Unicode 路径与符号链接策略 |
| F10.05 | 传输进度、取消与恢复 | 部分实现 | 进度、单项取消、断线取消与清理已测；无断点续传。提交不确定与晚取消单独表达。<br>证据：[tests/test_service_panels.py](../../tests/test_service_panels.py); [tests/test_sftp.py](../../tests/test_sftp.py) | 断线保留部分文件，恢复前核验源是否变化 |
| F10.06 | 拖放传输与协议选择 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 文件/目录支持范围可见，误拖不执行本地文件 |
| F10.07 | 覆盖/冲突/原子落盘 | 已验证子集 | 临时文件+校验+安全提交；默认不覆盖，显式覆盖、校验失败保留原文件、提交结果未知不重试均有测试。需服务器扩展。<br>证据：[tests/test_sftp.py](../../tests/test_sftp.py) | 目标存在需明确策略，中途失败不破坏原文件 |
| F10.08 | SFTP 协议扩展兼容 | 部分实现 | 遇到不支持安全提交扩展时明确失败，不做删除目标后重命名降级；尚无广泛服务器/版本互通矩阵。<br>证据：[tests/test_sftp.py::test_unsupported_atomic_operation_fails_without_unsafe_fallback](../../tests/test_sftp.py) | 不同服务端 SFTP 版本和扩展可降级，不混入登录脚本输出 |
| F10.09 | ASCII 收发 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 编码/行尾/发送节流可设置，不能当成二进制传输 |
| F10.10 | Xmodem/Ymodem/Zmodem/Kermit | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | CRC/重试/取消/批量/文件名/路径穿越单独测试 |
| F10.11 | Send Binary | 部分实现 | 串口可发送4096字节以内Hex原始数据；不是完整二进制文件传输。<br>证据：[tests/test_service_panels.py](../../tests/test_service_panels.py) | 按原字节发送，不做字符编码或换行替换 |
| F10.12 | 内置 TFTP 服务 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 只在显式授权地址提供目录，路径限制、IP限制、生命周期控制 |
| F10.13 | SFTP 本地视图与外部编辑 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 本地/远端初始目录和下载编辑不执行不可信内容 |
| F10.14 | SecureFX 集成边界 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 是独立产品集成；不把其全部 FTP/HTTPS 能力误算成终端内建 |

## 11. 日志、观察与排障

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/products/securecrt/faq/index.html)、[来源 3](https://www.vandyke.com/download/securecrt/6.2/history.txt)、[来源 4](https://www.vandyke.com/download/securecrt/8.7/history.txt)、[来源 5](https://www.vandyke.com/download/securecrt/9.1/history.txt)、[来源 6](https://www.vandyke.com/products/securecrt/history.txt)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F11.01 | 连接日志开关与自动日志 | 部分实现 | 新增会话日志控制窗口，显式开始/暂停/停止；无自动连接日志。<br>证据：[tests/test_journal.py](../../tests/test_journal.py); [tests/test_service_panels.py](../../tests/test_service_panels.py) | 逐会话开关，日志写入失败可见且不阻塞终端 |
| F11.02 | 原始字节/显示文本/屏幕日志 | 部分实现 | 原始字节base64 JSONL及接收文本分块JSONL；非屏幕日志或纯文本逐行转录。<br>证据：[tests/test_journal.py](../../tests/test_journal.py) | 三种语义分开，二进制和屏幕重绘不能混淆 |
| F11.03 | 每行时间戳与连接/断开标记 | 部分实现 | 每接收分块UTC时间、日志开始/结束与断开标记，断开去重有测试；非每行时间戳。<br>证据：[tests/test_journal.py](../../tests/test_journal.py); [tests/test_service_panels.py](../../tests/test_service_panels.py) | LF/CR/无换行分片、时区和重复断开不重复记账 |
| F11.04 | 日志路径模板 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 会话/主机/用户/端口/目录/时间变量定义与未知变量行为 |
| F11.05 | 跨日轮转和大小限制 | 部分实现 | 大小/段数限制、exclusive创建不覆盖旧段、队列满与I/O错误停止日志；无跨日轮转。<br>证据：[tests/test_journal.py](../../tests/test_journal.py) | 午夜、休眠跨日、磁盘满、并发重名处理 |
| F11.06 | 暂停/继续同一日志 | 已验证子集 | 暂停/继续同一文件，间隙有标记，解码器不跨间隙误拼字符；真实PTY流程有测试。<br>证据：[tests/test_journal.py](../../tests/test_journal.py); [tests/test_service_panels.py](../../tests/test_service_panels.py) | 9.7 行为单列，恢复不会静默换文件或重复内容 |
| F11.07 | 日志脱敏与凭据排除 | 部分实现 | 默认RX，TX显式选择，认证选项不进入日志且控制字符转义；远端输出仍可能含秘密，无通用脱敏。<br>证据：[tests/test_journal.py](../../tests/test_journal.py) | 不默认记录用户输入、认证挑战响应和脚本秘密 |
| F11.08 | SSH 诊断与算法展示 | 部分实现 | 真实协商cipher/MAC/压缩/KEX/Strict与主机签名/公钥指纹按秒刷新并可导出JSON，控制字符界面转义；仅公共元数据，认证答案不导出。完整失败阶段追踪与包级trace未做。<br>证据：[tests/test_ssh_security_ui.py](../../tests/test_ssh_security_ui.py); [harbor_terminal/ssh_dialogs.py](../../harbor_terminal/ssh_dialogs.py) | 协商/失败阶段可诊断，禁止泄漏敏感包内容 |
| F11.09 | Hex 排障窗口 | 已验证子集 | 新增固定绑定串口会话的Hex工具，限定保留量、原始ASCII安全显示、TX/RX区分与偏移。<br>证据：[tests/test_trace.py](../../tests/test_trace.py); [tests/test_service_panels.py](../../tests/test_service_panels.py) | 区分接收/发送、会话与时间，限制保留量 |
| F11.10 | 正则/关键词/临时高亮 | 部分实现 | 查找词持续字面高亮；无正则、多关键词样式及保存的关键词列表。<br>证据：[tests/test_terminal_widget.py](../../tests/test_terminal_widget.py) | 匹配范围、大小写、优先级、颜色属性及计算预算 |
| F11.11 | 活动/静默通知与音效 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 阈值、蜂鸣/音频、后台通知可设置 |

## 12. Windows 集成与企业交付

官方来源：[来源 1](https://www.vandyke.com/products/securecrt/features.html)、[来源 2](https://www.vandyke.com/products/securecrt/windows.html)、[来源 3](https://www.vandyke.com/download/securecrt/9.0/history.txt)、[来源 4](https://www.vandyke.com/download/securecrt/9.3/history.txt)、[来源 5](https://www.vandyke.com/download/securecrt/9.6/history.txt)、[来源 6](https://www.vandyke.com/products/securecrt/history.txt)

| ID | 能力/范围 | Harbor 状态 | 实现与限制 | 目标验收条件 |
|---|---|---|---|---|
| F12.01 | RDP 标签与重定向 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | Windows 原生 RDP 控件集成、缩放、重连及安全策略 |
| F12.02 | Scratchpad 记事标签 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 字体、行号、自动保存和跨平台迁移不崩溃 |
| F12.03 | 打印屏幕/选择/透传 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 远端打印权限、编码、打印机缺失和禁用策略 |
| F12.04 | SSH/Telnet URI 处理 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 系统注册，URI 不允许注入配置路径、脚本或本地程序 |
| F12.05 | 本地文件/菜单/工具栏定制 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 用户控制的动作与远端不可信输入分离 |
| F12.06 | 多显示器、DPI 与无障碍 | 部分实现 | Windows原生Qt确认Segoe UI/Consolas及100/125/150/200/300%启动/选项/字体对话框；CI屏幕小会裁切窗口。未验收真实Win10/11多显示器、中文IME与无障碍。<br>证据：[scripts/build-windows.ps1](../../scripts/build-windows.ps1); [artifacts/validation-0.5.md](../../artifacts/validation-0.5.md) | Win10/11 缩放、焦点、对话框最小尺寸、JAWS/屏幕阅读器 |
| F12.07 | 便携包/MSI/静默安装 | 部分实现 | Windows原生PyInstaller x64便携EXE/运行库ZIP及SHA-256已构建并启动，附硬件工具；必须完整解压。无签名、MSI、升级/静默安装。<br>证据：[scripts/build-windows.ps1](../../scripts/build-windows.ps1); [artifacts/validation-0.5.md](../../artifacts/validation-0.5.md) | 版本升级不混用旧 DLL，不丢配置；卸载策略明确 |
| F12.08 | 签名与可信更新 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | Windows Authenticode、下载校验、更新签名及回滚 |
| F12.09 | 企业策略禁用开关 | 未实现 | 尚无新增实现/验证记录；不得据依赖能力推断完成。 | 可控制脚本、明文传输、转发、打印、TFTP、自动登录和凭据保存 |
| F12.10 | 依赖 SBOM 与供应链维护 | 部分实现 | 21个Python发行包锁版本；Windows包带发行包/许可证文件与哈希、Python许可和构建提交号，非完整原生DLL SBOM。签名与公告治理未实现。<br>证据：[scripts/collect_licenses.py](../../scripts/collect_licenses.py); [scripts/build-windows.ps1](../../scripts/build-windows.ps1) | 版本、许可证、安全公告与签名验证纳入发布 |
| F12.11 | 长期稳定性与故障注入 | 部分实现 | 保留0.5传输/PTY持续运行，独立0.6 Qt/Worker/SSH/流程/输入锁/应答/配置持续测试已启动；两者各自保存源码哈希与实际时长，均未完成72小时。无实体COM或SecureCRT长期对照结论。<br>证据：[scripts/soak.py](../../scripts/soak.py); [scripts/soak_desktop.py](../../scripts/soak_desktop.py); [artifacts/validation-0.6.md](../../artifacts/validation-0.6.md) | 24/72小时、资源趋势、多窗口同时关闭、网断与睡眠恢复 |
| F12.12 | 兼容性与回归基线 | 部分实现 | 0.7云端304测试通过，原生Windows回归及冻结EXE在CI执行；Win10/11用户实机、实体COM和SecureCRT9.7.4同机对照仍未验收，不能由Server2025替代。<br>证据：[tests](../../tests); [.github/workflows/validate.yml](../../.github/workflows/validate.yml); [artifacts/validation-0.7.md](../../artifacts/validation-0.7.md) | Win10/11、SSH 服务矩阵、串口适配器与终端回放留原始结果 |

## 状态统计

- 已验证子集：41 项。
- 依赖能力未验证：1 项。
- 部分实现：65 项。
- 未实现：73 项。
- 仅关闭策略：1 项。
- 安全差异：2 项。

原始0.1调研时为163项未实现。0.2补终端/串口，0.3补SFTP/日志/Hex，0.4补单级跳板/转发，0.4.1重做界面/字体，0.5补MFA/命令与JSON流程及原生Windows包，0.6补会话导入/批量/模板/并发与输入锁，0.7补SSH策略/证书/主机CA与身份工具；仍不能据子集测试宣称完整模块已经完成。

后续仍包括完整证书/硬件密钥与凭据库、完整脚本对象、传输/日志高级功能、多级跳板/代理、布局快照/配置迁移、Windows 10/11实机、实体硬件及长期对照。
百万行历史、横向重排、完整仿真/鼠标协议、原生Windows IME/DPI仍未验收。历史中的弱协议/命令行秘密/自动信任不会作为安全默认值。
