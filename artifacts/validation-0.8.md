# Harbor Terminal 0.8 验证记录

## 功能与故障场景

本轮推进六项此前未实现能力：历史清除、Alt Meta、逐字节/逐行节流、粘贴引用/路径/换行、串口线路控制、ASCII文本收发。仍有67项未实现；45已测子集及67部分实现也不表示模块全部完成。

云端Python3.12/Linux全套336通过、0失败、0跳过，见test-results-0.8.0.xml。两个旧协议兼容测试的FFDH弃用警告保留，不静音当作安全通过。主要新增证据：

- 真实SSH中逐字节发送Unicode/CRLF，接收为GB18030并规范换行；真实PTY发送字节完整，线路查询不支持时明确未知。
- 受控传输记录真实写入时间，验证字节/行间隔；一秒行等待期间DSR应答优先，取消不补发后续行。
- 取消等待在途写入结束后再报告字节下限；已知部分写入及连接重置的不确定写入分别标记，不重试。新任务不插入仍在写出的数据。
- 每行等待只使用该行前新建的RX游标，旧历史提示不能误放行下一行；超时停止后续数据。
- 接收线程分片Unicode、CRLF、控制序列过滤与转码；已有文件拒绝覆盖，严格解码/队列/配额错误保留部分输出并明确报错。
- 原生Qt合成Alt/AltGr/GroupSwitch/IME，保持原始CRLF及POSIX/PowerShell引用预览，路径粘贴取消后无发送，源文件改变不改变冻结发送内容。
- DTR/RTS受控驱动操作，自动流控占用线拒绝手动设置，输出确认回车取消，未知信号不伪装低电平。
- ED2/ED3/RIS与本地清屏/历史分离；schema5读取/6写入及XML往返，策略/证书字段在批量编辑中可明确选择。

Windows国际键盘/物理线路不是上述合成事件和替身的验证范围。没有全部历史问题样本、全协议fuzz或整体可靠性优于SecureCRT的证据。

开发初轮旧304项中303通过/1失败，原因是关闭测试的Worker替身未接受新增input_policy关键字；更新替身参数转发后保留原取消/关闭断言，再加入32项新测试，最终336通过。初轮原始报告test-results-0.8-initial.xml保留，未将替身修改计为产品缺陷修复。

## 安装包与界面

独立/workspace/securecrt-0.8-venv复用固定依赖并安装0.8应用；0.7开发目录不变，长测继续。setup-cloud-0.8.sh已实际运行，Rust/Craft固定构建、pip安装及336测试通过；Craft CLI0.4.0，无模型端到端重建声明。依赖锁仍为原21包，未新增依赖或本轮全应用漏洞审计。

独立/tmp目录运行已安装CLI完成39项检查，见desktop-0.8-installed.json；实际SSH文本收发/取消、加密密钥/证书、MFA/SFTP/转发/流程、GUI输入/历史/信任/配置等均执行。源代码、已安装包与wheel的41模块逐字节一致，见package-consistency-0.8.json。

实际Qt生成23张0.8截图，新输入/文本/串口页已查看；使用生成的本地测试数据。云端字体Noto Sans CJK SC/Liberation Mono，不是Windows字体证据。离线审计统计/筛选/分页另由脚本检查。

## 持续运行

首次0.8短基线12.10秒、126循环、0错误、6次协议查询/回复、2次文本发送、1次配置提交，见desktop-soak-0.8-baseline.json，只是短时通过。后续补充测试工具的接收线程关闭检查和runner源码哈希；不把工具验证改动记作产品稳定性修复。

退出检查另跑5.06秒/53循环，退出后接收线程closed且无存活线程；报告在desktop-soak-0.8-close-check.json。先前候选运行68.84秒/247循环/0错误后主动中止并另存desktop-soak-0.8-candidate-interrupted.json，最终另启新文件从零计时。所有运行时长不累计。

0.7的PID8349在本轮核对时仍有新心跳，38个已安装模块哈希与起始报告一致；0.8安装没有改动它。快照见desktop-soak-0.7-at-0.8-progress.json。0.5/0.6旧PID已不存在，旧状态说明见soak-restoration-0.7.json。没有72小时完成结果、实体COM或供应商同机对照。

## 尚待实测

用户Windows10/11、USB转串口实际DTR/RTS电平/复位/流控、设备断开和驱动恢复、国际键盘/IME、多显示器DPI、长时负载及SecureCRT9.7.4逐项对照均待用户设备报告。Windows包附INPUT-SERIAL.md、SSH-SECURITY.md、硬件规程和本机工具；枚举成功不是实体收发通过。

## 最终Windows交付

[运行42393786587](https://github.com/lhy8888/secureCRT/actions/runs/42393786587)五个job全部成功，应用提交33aeb0bc034dfce64d0a9c53237b63d325426ca9。Linux3.12/3.14各336通过；Windows3.12/3.14各328通过、8跳过、0失败/错误。跳过为7个Unix PTY及1个POSIX目录同步分支，完整JUnit在ci-0.8-final。初版应用8e97842的42393596369也通过，最终包使用33aeb0b的界面预览修正。

实际冻结EXE使用Python3.14.10/Qt6.12.0，100/125/150/200/300%各39项检查通过，字体Segoe UI/Consolas；新增文本发送/接收/取消、引用保留CRLF、AltGr、历史及串口流控界面均执行。原生串口枚举和自有EXE采样完成，未打开实体线路或运行SecureCRT。报告/截图在windows-0.8-final；小屏高缩放仍可能系统裁切，不算完整DPI布局验收。

ZIP60,323,135字节/379条目，SHA-256：556ff54b61d3e762aa77d2db74b7bbc2e8d5467a7a146974a15642f57a9397f1。已核对CI侧哈希、BUILD-INFO提交、source_dirty=false及PE头AMD64；含INPUT-SERIAL.md及此前说明/PowerShell工具。构建信息windows-0.8-build.json，完整未签名包/workspace/HarborTerminal-0.8.0-Windows-x64.zip。

本轮install_script和start_skill已保存环境草稿，仓库/网络/凭据设置未改动；未代替用户发布环境或验证新任务恢复。后续源交付提交增加文档、原始证据和测试工具退出检查，应用41模块与上述Windows构建保持一致。

快照desktop-soak-0.7-at-0.8-progress.json：3388.00秒、11699循环、0错误，状态running、PID8349及源码哈希在本次核对时有效；不是259200秒完成。

快照desktop-soak-0.8-progress.json：254.37秒、894循环、0错误，状态running、PID15271及源码哈希在本次核对时有效；不是259200秒完成。
