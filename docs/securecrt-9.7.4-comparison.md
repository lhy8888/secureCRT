# SecureCRT 9.7.4 对照基线

基线已扩展为全历史审计，请从 [调研总览](research/README.md) 开始。

- [183 项功能/验收矩阵](research/feature-matrix.md)
- [32 个系列、314 个发布分节覆盖](research/release-coverage.md)
- [4294 条历史变更位置](research/change-index.csv)
- [36 项历史故障回归场景](research/reliability-regressions.md)
- [本地交互审计浏览器](research/coverage.html)

官方页面现已可访问，之前的网络阻断结论只适用于早先那次验证，不再作为当前资料缺失的原因。

Harbor 0.5.0 已有Windows原生CI、实际x64 EXE、MFA/命令/声明式流程及硬件工具。183项中仍有95项未实现，其他行也只覆盖注明的子集。历史记录不表示原问题已在Harbor复现或修复，也不表示与SecureCRT 9.7.4等价。

用户已具备Windows电脑与USB转串口，可按[实体COM验证](windows-hardware-testing.md)运行随包工具，按[同机对照规程](windows-comparison.md)记录双方行为与资源。当前Windows CI运行于Server 2025，不能代替Win10/11实机、驱动、IME与完整DPI验收；72小时与SecureCRT同机对照尚无完成报告。
