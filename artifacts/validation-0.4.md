# Harbor Terminal 0.4 — 本轮验证

日期：2026-11-07。Linux x86_64 / Python 3.12 / Qt离屏。所有服务、密钥、密码及文件均为本地生成的测试夹具。

- `python -m pytest -q --junitxml=artifacts/test-results-0.4.xml`：**146通过，0失败、0跳过**，10.73秒；包括之前版本的回归。
- 本地真实SSH/SFTP验证：交互、独立主机身份与密码、加密私钥、PTY尺寸、单级跳板、SFTP复用认证、1–3字节响应、提前EOF、哈希错误、覆盖保护、取消与提交回复丢失。
- 真实TCP验证：L/R转发、SOCKS5握手及二进制往返、绑定冲突、监听数量上限、停止/断开释放；Qt隧道窗口实际创建及停止监听。
- Unix PTY验证：串口原始双向字节、短写提示、不自动重发、Hex固定会话、日志暂停/继续、磁盘错误隔离及关闭清理。
- 安装后的`harbor-terminal==0.4.0`从`/tmp`导入site-packages，Qt主窗口启动/关闭和SSH隧道入口通过；`pip check`无依赖冲突。wheel已构建。
- `pip-audit`检查锁定的21个Python发行包，未报告已知漏洞；见[机器结果](dependency-audit-0.4.json)。这不等于应用安全审计结论。
- 离线审计浏览器的领域/状态/文本筛选、历史/系列筛选、导航与分页通过Node DOM验证；文档从规范JSON生成。183项中118未实现、37部分实现、22子集已测，另有依赖/策略/安全差异6项。
- `scripts/capture_services.py`使用安装后的包，真实经跳板连接本地SSH目标并执行SFTP上传/哈希校验、建立三类监听、开启日志和PTY Hex收发；正常退出清理全部工作线程及服务。

截图：[终端](harbor-0.4-terminal.png) · [SFTP](harbor-0.4-sftp.png) · [隧道](harbor-0.4-tunnels.png) · [日志](harbor-0.4-log.png) · [Hex](harbor-0.4-hex.png)。这些是实际Qt运行采集，属于本地生成测试数据，不是Windows或实体设备证据。

Craft Anything 0.4.0 CLI已在`/workspace/tools/bin`安装；之前的doctor、MCP自检及自有ELF分析有保留记录。未运行模型端到端重建，也未构建其桌面GUI。

Windows CI/未签名目录打包脚本已配置，未远端执行；未生成或测试Windows EXE。Windows COM/驱动/IME/DPI/Agent、全量协议模糊测试、长期资源趋势、72小时稳定性及SecureCRT 9.7.4同机对照仍未验收。不能据本轮结果声称全功能等价、更安全或更稳定。

源码保留在工作区，未提交或推送Git。源码ZIP和Python wheel均不是Windows安装包。云环境草稿的保存不代表发布快照或在新任务中验证恢复。
