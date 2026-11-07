# 0.5验证证据

本文件记录实际执行范围。目标为Windows 10/11，但云端本机是Linux；远端Windows CI使用Server 2025，不等同用户实机。

## 源码与原生Windows

- 本地Linux/Python3.12：216通过、0失败、0跳过，JUnit为test-results-0.5.0.xml。真实SSH/MFA/加密私钥/SFTP/转发/Qt输入/流程及Unix PTY在用例中执行。
- [运行42371238666](https://github.com/lhy8888/secureCRT/actions/runs/42371238666)，源码1acc09b：Linux Python3.12/3.14均216通过；Windows Python3.12/3.14均210通过、6个Unix PTY用例跳过，0失败。JUnit在ci-0.5-protocols目录。
- 同次Windows PyInstaller包以Python3.14.10生成。实际EXE在100/125/150/200/300%缩放下完成主窗、快速连接、嵌套选项和字体对话框检查；确认Segoe UI/Consolas。冻结进程还实际完成加密私钥SSH、二进制SFTP往返、本地转发、未知主机拒绝、键盘交互MFA和无界面JSON流程。
- CI屏幕只有1024×768附近；300%时窗口被系统裁切至347×250逻辑尺寸。因此这些是启动/字体/对话框检查，不是完整多显示器、布局、Win10/11或IME验收。
- 1acc09b原生包371文件，59,809,800字节，SHA-256为02c55b89ff85b2410c42988349f3c693123b87678701294a1a645aba25d3f2b0。后续含同机采样脚本的交付包有独立提交和哈希，不能混用。

## 初始失败及处理

初次Windows测试暴露本地隧道重复绑定，改用绑定前SO_EXCLUSIVEADDRUSE的自有socket；Windows真实冲突测试通过。SOCKS域名、半关闭、未完成握手取消及停止监听保留已有流有实际测试。

初次Windows离屏插件无法枚举系统字体；使用原生windows平台后才确认Segoe UI/Consolas，未将回退字体误报为Windows字体成功。Linux runner缺少libEGL/libOpenGL，工作流已安装。

一次Python3.14 CI重跑中，MFA回归的70毫秒握手预算受调度负载影响而失败。测试改为2秒握手预算与两轮共2.2秒应答，仍验证应答可超过握手期限；产品超时策略未改变。失败JUnit留存，修正后完整矩阵重跑通过（见下文最终交付），没有跳过该测试。

## 持续运行

旧基线：4162.57秒，20428循环，0错误；2044次SFTP文件操作、818次隧道往返、102次计划重连。主动停止以切换新版，状态interrupted，报告soak-0.5-baseline-interrupted.json。**这不是72小时通过**，也不是新版的累计运行时间。

最新包重新开始259200秒运行，实时报告为soak-0.5-final-live.json，状态running表示未完成。记录全部Python源文件哈希；循环验证SSH二进制、SFTP、L/R/SOCKS、Unix PTY、终端模型及发送/等待流程，并监测内存/句柄预算。报告只代表本地传输/模型，不含GUI长期渲染、实体COM或SecureCRT对照。环境快照不保留运行进程。

## 分发与硬件

包附构建信息、Python/发行包许可及哈希，不是完整原生二进制SBOM。21个锁定Python发行包在本次pip-audit中未报告已知漏洞（dependency-audit-0.5.json）；这不是全应用安全审计。包未签名，无MSI/可信更新。

用户已确认有Windows电脑和USB转串口。清单/回环/拔插/72小时工具准备完成；串口清单为空也不等于实体收发通过。实体报告尚未取得，Windows10/11的驱动、IME、多显示器、Agent和SecureCRT9.7.4同机/长期对照仍待执行。

95项能力仍未实现；有部分/子集证据的条目也保留明确缺口，不宣称全功能或更安全稳定。

## 最终交付包

[运行42371959285](https://github.com/lhy8888/secureCRT/actions/runs/42371959285)，提交27c4c251fe1e5ee5ca386630d6ce769580d7dabb，全部5个job通过。Linux3.12/3.14各216通过；Windows3.12/3.14各210通过、6跳过，均0失败。最终JUnit在ci-0.5-final，Windows实际报告与截图在windows-0.5-final。

最终x64 ZIP为59,813,744字节/373条目，SHA-256为1b46756acc6d50c5cf781df4dc105d057f08d278d5998e76f8dd64f55470788e。PE头确认为AMD64，构建信息source_dirty=false、Python3.14.10，源码/已安装包/wheel的29个Python模块逐字节一致。包未签名。

5种缩放下各12项实际EXE检查全部通过。冻结EXE调用真实Windows串口枚举接口，发现1个CI端口，仅枚举未打开；这不能作为实体COM收发通过。资源采样脚本对正常启动的Harbor EXE采集2个样本，运行1.03秒后completed，不含SecureCRT测试。两份PowerShell脚本均经过原生解析检查。

从/tmp工作目录使用安装包启动完整诊断通过，防止误用源码目录导入。pip check通过，wheel构建成功，离线研究浏览器筛选/状态统计/历史分页检查通过。

新版持续测试快照：893.93秒，4390循环，0错误，44次流程；状态running。见soak-0.5-progress-snapshot.json。这是快照，不是72小时结论，实时报告仍在继续更新。
