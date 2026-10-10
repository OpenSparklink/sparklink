# 旧 Profile/HID/transport 的实验边界

2026-10-11 清理 R14，保留 S0–S6。默认 slkd 不再自动注册旧 Battery、DeviceInfo、
HID 服务，不编入未消费的 transport codec 或 Profile actor。新增未发布
`slk-experimental` crate 保存旧模型、codec、注册实现及原测试，没有默认 daemon
运行时依赖；workspace 构建实验库不意味着该库被链接进默认 daemon。

`experimental-legacy-profiles` 是显式构建 feature：

```
cargo build -p slkd --features experimental-legacy-profiles
```

它仅恢复旧 profile0 的注册/连接生命周期，Native profile1 仍不注册。此 feature
供受控开发，不是合格服务支持。旧 UUID/权限位（R07）、SSAP 请求路由/预算/credit、
真实服务互通、安全要求仍未闭合。默认不宣称 Profile/HID/transport 可用。

Profile actor 的串行回调、阻塞/cancel/drain/panic 及 D-Bus 响应回归保留，测试和
实验 feature 编译同一 actor。没有复制第二套实现；迁往用户态 SSAP Engine 前
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

工具 CI 需加载匹配内核的 lab helper，固定 c2c4aa4ad0bd；通过
`SPARKLINK_KERNEL_SOURCE` 指定 checkout 根目录，本地默认仍为相邻 linux。
首轮新增 CI 暴露了相邻仓库假设导致的两项失败，保留失败记录；修复不跳过测试。
