# 旧 Profile/HID/transport 的实验边界

<!-- documentation-scope: 20261014 -->
> **阅读范围：混合资料：有效语义与历史记录。** 实验 Profile/HID/transport 的编译隔离和回调测试边界。
> [主题归纳与去向](../../../docs/project/uppercase-document-guide.md)；[推荐入口](../../../docs/reference/interfaces.md)。
> 原文中的源码、失败、PASS 与命令仅适用于其记录版本；当前资格以 [CURRENT_CAPABILITIES](../../current-capabilities.md) 为准。

2026-10-11 清理 R14，保留 S0–S6。默认 slkd 不再自动注册旧 Battery、DeviceInfo、
HID 服务，不编入未消费的 transport codec 或 Profile actor。新增未发布
`slk-experimental` crate 保存旧模型、codec、注册实现及原测试，没有默认 daemon
运行时依赖；workspace 构建实验库不意味着该库被链接进默认 daemon。

旧 `experimental-legacy-profiles` daemon 构建入口已在R4c退休，没有兼容别名。
独立 `slk-experimental` 开发crate保留；slkd仅dev-dependency使用其模型和原actor测试。
default及all-features的生产依赖都不能重新引入实验crate。原feature只初始化没有
Native调用者的profile0 registry，不能为保留空actor而恢复旧事件业务分支。

86bfbc8起默认daemon在取得lease/发布对象前拒绝profile0，不再构造旧破坏性
EventReceiver；Native只使用ControllerEventReceiver独立游标。旧事件actor的start入口
现在仅cfg(test)编译；当前Native运行时没有历史Event类型或handle-only业务分支。
Native纯旧codec/shape与daemon callback fixture均在专用测试边界内；有效取消/shutdown
回归保留，不能升级成完整Runtime证明。内核历史ABI/selftests仍需后续迁移，不宣称WP12结束。

独立模型供受控开发，不是合格服务支持。旧UUID/权限语义回归保留，真实服务始终
通过唯一用户态SSAP Engine和现有Channel；完整Profile功能及资格仍按原门禁推进。

Profile actor 的串行回调、阻塞/cancel/drain/panic 及 D-Bus 响应回归保留，测试和
测试构建使用原 actor。没有复制第二套实现；迁往用户态 SSAP Engine 前
不得将这些实验接口作为生产能力。测试专用 Bond get/is_bonded 只在 cfg(test)。
默认与全部 targets/features 均进入严格检查，不添加全局 dead_code allow/expect。
ExtAdv Configure 的 named D-Bus 参数只有一处带理由的 too_many_arguments lint
expectation；没有屏蔽死代码或放宽 -D warnings。

配置先验证后注册 bus/获取 lease：无效或显式缺失/无权限文件拒绝，未知字段拒绝，
auto_pair=true、min_encryption非零、auto_enable=false明确不支持。仅隐式默认
文件不存在可用默认值。Native WS73不接受它无法执行的legacy discovery filter。
这里是未实现策略的拒绝修复，不宣称启用/加密/自动配对策略已经完成。

验收覆盖默认依赖图没有实验 crate、严格 default/all-target/all-feature check、
workspace test、clippy、fmt、默认 release、跨语言 ABI、VM 真双设备默认路径。
新代码与实验边界各项证据在当前 issues 维护，完整 SSAP/security/Profile、自然
故障恢复/根因及完整发布验收仍开放。历史物理/人工注入证据保留，不用新 fixture
替代真实 RF 或旧故障。

工具 CI 需加载匹配内核的 lab helper，固定bf8663bb78eb（历史c2c4 pin及失败收据保留）；通过
`SPARKLINK_KERNEL_SOURCE` 指定 checkout 根目录，本地默认仍为相邻 linux。
首轮新增 CI 暴露了相邻仓库假设导致的两项失败，保留失败记录；修复不跳过测试。


K6d49b12起旧内核serdev Rust/C骨架和其UART decoder只保存在kernel selftests，
无真实bus调用者、ignored ctx/global parser、失败后defaults不得进入默认core。
原H4/SPI无provider descriptor不再登记；并未提供新serdev支持。新的标准/Virtual/
厂商provider仍遵循同Backend Runtime/generation/module/callback契约，S0–S6保留。
