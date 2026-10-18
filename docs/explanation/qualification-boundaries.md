# 为什么源码、证明与实机资格必须分开

同一个功能有不同层次的证据。源码中的接口声明只能证明入口存在；离线测试证明
给定输入与环境下的行为；形式化结果受模型、状态空间与假设限制。真实设备资格
还需要匹配编译产物、固件、拓扑和对端应用记录。因此文档不能用一个“已完成”覆盖这些事实。

## 发送不是一个瞬间

应用发送被软件准入、USB 提交成功、控制器 NOCP 完成、对端应用收到并校验，是
不同阶段。前一阶段成功不能推出后一阶段成功。随机载荷与对端真实回复的价值在于
排除本地 echo、模拟成功和仅凭广播数据推断连接后业务可用。

## 生命周期身份决定证据归属

controller index 可复用；generation 区分控制器注册。connection handle 也可复用；
connection lifetime 区分物理连接。逻辑通道使用 local／remote TCID 与 PI，而不是
把 handle 当作通道编号。历史抓包若没有足够身份，不能归入新连接或新镜像。
当前 Runtime-owned Session、Channel 和 fd binding 的职责见
[目标架构](../../project/architecture.md)，设计说明不授予实现资格。

## 有限证明与硬件假设

NOCP 在线上只有 handle／count，不能声称硬件携带 generation／lifetime。
形式化检查需要显式记录事件准确性、迟到和复用屏障的假设，实机再检查这些假设。
工具安装通过、模型通过、注入恢复和人工切电都不能证明自然故障自动恢复。
工具超时或 unsupported 仍是未证明。

## 历史仍然有用

首次 panic、最后回复关闭丢弃、模型反例和旧限定 PASS 是回归设计的输入。
它们应保留原始源码身份与失败条件，通过[历史入口](../history/index.md)查阅。
重新排版不会赋予当前 HEAD 资格；[当前能力入口](../../project/current-capabilities.md)
是唯一资格来源，完整工作及未决条件只在[实施计划](../../project/implementation-plan.md)维护。
