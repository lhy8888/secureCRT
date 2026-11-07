# SecureCRT 全历史功能审计（以 9.7.4 为验收基线）

检索日期：2026-11-07。目标平台：Windows 10/11。

这次从官方旧版本入口逐系列读取历史，覆盖 **32 个系列、314 个正式/Beta/补丁发布分节、4294 条变更记录**；归档文件名从 3.2 系列开始，其中也包含 3.1 的记录。原文 bullet 包含 21 个缩进子项，顶层项为 4273 条；不是独立功能数量。没有把只读 9.7.4 当成全产品调研。

- [183 项功能/验收矩阵](feature-matrix.md)：12 个领域，逐项列 Harbor 当前状态和验收条件。
- [脚本行为契约](scripting-contract.md)：结合官方 122 页基础指南，细分流式等待、同步、目标标签及取消语义。
- [36 项可追溯故障回归](reliability-regressions.md)：每项链接到官方来源、发布版本、行号和记录 ID。
- [314 个发布分节覆盖表](release-coverage.md)：每个系列的新增、变更、修复、安全说明，以及所有发布分节。
- [4294 条变更位置索引](change-index.csv)：每条记录的位置与检索标签，无删除 Beta 或老补丁。
- [来源清单与 SHA-256](source-manifest.json)：来源、字节数与哈希，方便后续发现文档更新。
- [可筛选的审计浏览器](coverage.html)：本地直接打开，按领域、状态、主题检索；不是在线应用或开发服务器。

## 这次发现的范围错误

原来的客户端只是 SSH/串口演示。完整运维工具还包括认证/证书/硬件密钥、跳板/代理/转发、终端仿真与键鼠模式、会话库/组/平铺/快照、SFTP 与传统传输、命令管理/广播/Expect/脚本、日志/轮转/Hex，以及 Windows ConPTY/RDP/驱动/部署等成套工作流。

### 功能网页不能替代版本历史

官方功能网页仍描述 128,000 行历史，但 **9.6 Beta 1，L368** 记录新配置的 `Max Scrollback Buffer Size` 提高至 **1,024,000**，允许会话配置更大的历史。它是可设置上限的变化，不表示每会话默认预分配百万行。

来源：[9.6 历史](https://www.vandyke.com/download/securecrt/9.6/history.txt)、[功能表](https://www.vandyke.com/products/securecrt/features.html)。

### 升级配置和新配置默认值不同

**7.2 Beta 1，L352** 把新安装串口默认流控改为 none；**8.7 Beta 1，L436** 又把新安装默认改为 XON/XOFF。现有配置是否迁移不能从这些措辞推断。软件流控还会消耗特定控制字节，二进制场景必须明确配置。

**6.0.2，L44** 把新安装 Agent forwarding 默认关闭；**9.7 Beta 1，L456** 把新安装默认 cipher 改为 `aes256-gcm@openssh.com`。配置迁移测试必须单列。

来源：[7.2](https://www.vandyke.com/download/securecrt/7.2/history.txt)、[8.7](https://www.vandyke.com/download/securecrt/8.7/history.txt)、[6.0](https://www.vandyke.com/download/securecrt/6.0/history.txt)、[9.7](https://www.vandyke.com/products/securecrt/history.txt)。

### 不能把历史能力简单求并集

**9.0 Beta 1** 移除过一组弱密码能力，**9.0.1** 又记录恢复部分兼容 MAC；**9.6** 移除 Python 3.8 脚本引擎支持。**8.3** 改变 ANSI 调色板配置方式并移除原会话级颜色选项。每项需求要标清版本、平台、升级路径和默认值。

SSH1、弱算法兼容、自动接受主机密钥、命令行传秘密、远端触发本地脚本等历史能力不能直接成为新软件的安全默认值。需要记录兼容差异和必要的替代流程。

### 安全经验必须落到具体协议/组件

- **9.5 Beta 3**：CVE-2023-48795 / Strict KEX，需要客户端和服务端双方扩展配合。不能用终端 ANSI 过滤宣称修复 SSH 交换问题。
- **8.7.2**：负数仿真参数触发的内存破坏风险，属于终端解析边界。
- **9.3**：持久化敏感数据与弱配置口令的离线破解风险，属于配置/凭据保护。
- **4.1.9**：URL 中配置路径与登录脚本组合的问题，属于本地执行边界。
- **9.7.3/9.7.4**：串口连接卡住、畸形 KEX 包、认证提示换行、TUI 颜色等不同子系统的问题。

这些是相应发布的历史修复记录，**不表示 9.7.4 仍包含这些缺陷**。Harbor 也不能因使用不同语言或不同依赖就声称同场景已通过。

### 大量功能隐藏在小版本和 INI/脚本选项中

例如脚本录制的转义修复、SFTP 默认协议/扩展、转发条目导入、断开日志去重、只读配置迁移、大小写改名、默认串口配置、独立 SFTP 登录、日志暂停继续、主机 CA 与用户证书、批量活动会话操作，都需要分别验收。它们不是“有同名按钮”即可等价。

## 当前产品差距

首次0.1审计时183项中有163项未实现。**0.5当前为95项未实现、56项部分实现、27项子集已验证**；其余为2项依赖未验证、1项仅关闭策略、2项安全差异。[0.5记录](../releases/0.5.md)补MFA/命令流程与原生Windows包；[0.4.1](../releases/0.4.1.md)为界面字体基线，[0.4](../releases/0.4.md)与[0.3](../releases/0.3.md)为早期连接能力。没有整体模块通过SecureCRT等价性验收，测试数量不能代表完整可靠性。

0.2补终端网格/颜色、尺寸同步、Qt输入、串口设置和基本会话树；0.3补SFTP单文件、日志和Hex；0.4补单级跳板及三类转发；0.4.1参照9.7重做桌面；0.5补MFA、固定目标命令、声明式流程、CLI、仅通道SSH及实际Windows包。后续包括证书/凭据库、通用脚本对象、传输高级功能、配置迁移、用户Win10/11/实体COM和长期对照。完整目标、限制与证据见功能矩阵；requirements.json和reliability-regressions.json分别为当前能力与历史场景证据，由render_research.py同步生成文档和浏览器。

## 完整性边界与后续证据

1. 已完整索引官方 Previous Releases 页面当前列出的所有 SecureCRT 分支，加当前 9.7 分支。对站点未列出的更早版本不作覆盖声明。
2. “新增 583、变更 830、修复 2873、安全说明 8”是**原文章节的记录数**，不是独立功能或漏洞数量；安全相关条目也可能放在普通修复/变更中。主题标签由关键词生成，仅作导航。
3. 已阅读和整理公共功能说明、Windows 介绍、FAQ、脚本 FAQ/示例与提示；**安装版内置帮助、每个脚本 API 方法、所有隐藏 INI 选项及协议序列参数尚未取得完整规格**，保持待核实。网站资料不等同全部内置手册。
4. 没有运行 SecureCRT 9.7.4，没有取得其内部实现或真实缺陷复现样本，不能推断全部根因或宣称已吸收内部稳定性设计。
5. 没有 Windows 原生、实体 COM、72 小时压力或双方同环境性能对照结果。当前研究不能支持“更安全/更稳定”的结论。

## 复查与更新

```bash
cd /workspace/secureCRT
/workspace/securecrt-venv/bin/python scripts/research_securecrt.py
# 明确重新拉取官方资料时：
/workspace/securecrt-venv/bin/python scripts/research_securecrt.py --refresh
/workspace/securecrt-venv/bin/python scripts/render_research.py
```

原始公共文档和完整逐条标准化文本与官方脚本指南保留在 `/workspace/securecrt-research-cache`，项目内保存来源索引、哈希和自行整理的规格/验收总结。抓取器会验证内容；不存在的路径可能返回 HTTP 200 的 HTML 错误页，不能计为成功取得历史。
