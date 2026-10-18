# 首次真实双设备消息：适用镜像

> **受限教程草案。** 当前测试入口已迁入 `slktest`，新 artifact 的实机资格待取得。
> 不把下述历史通过升级到最新构建，也不以尚未验收的新命令填充入门教程。

本学习任务的结果仍是普通用户通过两只真实 WS73 完成随机消息校验和回复。
设备、固件、实验驱动和应用都应位于受控 VM，准备者负责已有的发现/建链/授权。

此前教程的终端步骤与成功标志保存在
[冻结的已验证实验步骤](https://github.com/OpenSparklink/sparklink/blob/ca7a8a0938c49d912b6444cc92a53ef6c48ee1de/docs/tutorials/first-ws73-message.md)。
该版本使用旧 slctl 测试入口，只适用于其准确镜像；不能与新的 slktest 混用。
历史原文和失败/限定范围保留，当前资格只在
[能力入口](../../project/current-capabilities.md)。

新工具的角色、参数、错误和限制见[reference](../reference/socket-benchmark.md)，
维护者运行条件与尚缺门禁见[测试 how-to](../how-to/measure-socket-ping-pong.md)。
新工具镜像取得真实双端和已保持边界回归后，本教程再提供可重新执行的学习步骤。
目前不能宣称当前教程或最新镜像的真实 WS73 路径已重新验收。
