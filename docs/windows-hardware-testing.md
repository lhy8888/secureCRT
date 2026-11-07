# Windows 本机串口验收

将Windows ZIP完整解压后运行HarborTerminal.exe；无需另装Python。测试脚本位于同一目录。所有报告只保存在本机Diagnostics目录，不自动上传。

## 设备清单

```powershell
powershell -ExecutionPolicy Bypass -File .\Test-HarborHardware.ps1 -Mode Inventory
```

清单包含实际COM名称、硬件ID与设备序列号。没有设备也可完成枚举，但不代表实体收发通过。

## 实体回环

先将USB转串口从其他设备完全断开，按适配器说明只将TX和RX接成回环，不接供电引脚。TTL与RS-232电气制式不能混接。本测试仅适用于已准备好的回环，不向工作中的设备发送测试数据。

```powershell
powershell -ExecutionPolicy Bypass -File .\Test-HarborHardware.ps1 -Mode Loopback -Port COM3 -Seconds 600
```

脚本要求输入LOOPBACK后启动；也可以在明确准备好的回环上使用-ConfirmLoopback。测试8N1、无流控，持续发送包含全部256种字节的编号帧并逐字节验证，记录帧数、字节数、错误、p50/p95延迟、内存和句柄快照。Windows上同时检查第二个进程内打开请求被独占拒绝。短写、超时、拔出或不匹配均失败，不自动重发或重连。

## 拔插与重枚举

```powershell
powershell -ExecutionPolicy Bypass -File .\Test-HarborHardware.ps1 -Mode Hotplug -Port COM3 -Seconds 120
```

在观察期间拔下并重新插入适配器。只观察枚举，不打开COM、不发字节。优先按设备序列号识别同一适配器；没有序列号时只能验证原端口名，报告会标明这个限制。必须同时观察到移除和返回才通过。

## 72小时实体持续收发

```powershell
powershell -ExecutionPolicy Bypass -File .\Test-HarborHardware.ps1 -Mode Loopback -Port COM3 -Seconds 259200 -ConfirmLoopback
```

只有实际运行到时限且全部帧匹配，报告才显示passed。running、interrupted、incomplete和failed都不是通过。进度每5秒更新；资源样本最多4096条，延迟统计为最近2048帧。底层驱动调用异常挂住时外部脚本会结束超时进程；不能因此宣称驱动或设备恢复正常。

当前云端没有你的实体适配器。本说明和测试包准备完成，不等于实体COM或72小时测试已经完成；以你的本机报告为准。
