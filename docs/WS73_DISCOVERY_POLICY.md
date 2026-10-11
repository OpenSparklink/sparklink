# 每设备 WS73 发现策略

策略格式 v3 将请求参数保存在每个查询得到的 WS73 注册对象上。Setup 的
configure-OFF/scan-initialize-OFF 和后续 START 使用同一份不可变策略。
角色交换、取消/reacquire 不改变它；新注册重新按查询得到的地址选择配置。
其他设备的策略不随某只设备退役而改变。不是全局设备序号映射或测试端延迟。

默认请求与已验证的 v1 相同：广播周期 min=max=1200，功率偏好127，扫描
interval/window=1600/800。v2 连续窗口实验失败后已删除。驱动继续负责编码和
实际 Complete；策略范围校验、配置选择与业务决定属于用户态，不发送 raw DLI。

## 配置

`main.conf` 可设置 `[ws73.defaults]`，以及按地址匹配的 `[[ws73.adapters]]`。
每个 override 必须提供 `policy` 表，未填写的字段使用内建默认值，独立于
`ws73.defaults`。地址严格为六个两位十六进制字节；大小写等价，零地址、
重复地址、未知字段、错误类型或非法参数拒绝启动，不静默回退。策略在取得
管理凭据之前选择。非 WS73 对象不宣称支持本策略。

以下只展示配置格式，不声明这些参数已在真实固件上通过：

```toml
[ws73.defaults]
advertising_interval_min_slots = 1200
advertising_interval_max_slots = 1200
tx_power_dbm = 127
scan_interval_slots = 1600
scan_window_slots = 800

[[ws73.adapters]]
address = "00:01:09:32:54:CD"
[ws73.adapters.policy]
advertising_interval_min_slots = 1237
advertising_interval_max_slots = 1237
tx_power_dbm = 127
scan_interval_slots = 1600
scan_window_slots = 800
```

SDK `sle_device_discovery.h` 的周期/窗口单位为125us。广播 min/max 范围
32..16777215 且 min<=max；扫描 interval/window 范围4..65535且window<=interval。
功率偏好为 -127..20 dBm，127表示不指定。合法请求仍可能被控制器拒绝，
不将合法范围或成功参数 Complete 当作空口、功耗或故障恢复验收。

## 观测和验收

普通用户 `slctl --adapter <path> show` 通过该对象的 `GetDiscoveryPolicy` 显示
版本、广播周期、功率偏好和扫描参数。它表示不可变请求策略，不是测量结果；
实际选中功率须看关联的 `NativeOperationResult` 与原始 Complete。
退役对象拒绝查询，无策略返回不支持，不能返回默认值伪装已接通。

迁移删除了四个 `ws73_basic_*` 固定参数构造函数，旧未发布版本常量已替换，
仅保留一套请求构造实现。格式v3不改变 Native ioctl 结构/编号、frame-1、
广播数据、管理凭据或真实结果的来源。C头由cbindgen同步生成。

回归覆盖 SDK 数值边界、地址规范化/重复拒绝、两只策略隔离、Setup/START
参数一致、管理凭据失效先拒绝及退役查询。实际默认双设备已由精确源码
Ud17f3f6f531c 的新 VM 验证；自定义参数空口验证仍开放，源码回归不能替代它。
先验证默认路径，再将周期和功率分别作为独立变量做四设备对照；默认并行、
自然根因、单只非人工恢复及完整 S0–S6/原28项 issues 保持原验收范围。

[默认实机 receipt](evidence/ws73-per-device-policy-default-real-20261012.json)
SHA256 `cbec285f3fe4d0704fdaa558650e722124eec5f5ff07e9c5c135c3d615129ad5`：
真实双设备交换角色 RF20，QMP guest-only 退役/重注册后 RF2，同 slkd/bus，
UID1000/caps0，1265包/零capture drop、QEMU0。父进程封存的22轮原始证明已
独立重算一致；初始化/START 的49字节广播参数、8字节扫描参数与v1默认一致。
三个实际注册对象的Ready查询及一次Setup查询显示同一请求策略v3；自定义
覆盖、物理拔插、默认四设备、完整Managed和自动恢复均不由此receipt验收。
源码[CI38167553391](https://github.com/OpenSparklink/sparklink/actions/runs/38167553391)
九项成功；本轮原始捕获和服务二进制保持私有，SDK/固件blob未提交。

## 冻结的 VM 配置输入

`slkd --check-config --config <file>` 使用实际 daemon 的同一解析和策略校验，
在连接 D-Bus、发布对象或取得控制器管理权前退出。必须显式指定文件；合法
TOML 和 SDK 数值范围不表示固件支持、实际发射功率或 RF 验收。

`ws73_target.py prepare --native-discovery-config <private.conf>` 必须同时
指定三个完整 native VM profile 参数。它将文件冻结到 guest 的
`/etc/sparklink/main.conf`，使用 bundle 中的精确 slkd 二进制执行上述检查，
记录输入和二进制哈希，拒绝校验失败、超时及复制/校验期间的变化。
guest 在启动 daemon 前核对 SHA256、再校验，并导出实际配置与校验输出；
daemon 显式加载该文件，缺失时不能回退到默认值。它不安装主机文件。

首个自定义参数验收只允许独立双设备 `run --qmp-hotplug`。现有默认四设备
和 Managed 注入验收不得带此配置，待其策略证明迁移后再开放。父进程仍将
自定义 RF 验收标为 false；只有终止后独立核对每个实际注册的策略查询、
全部初始化/START 原始参数、Complete、随机 marker 空口与同 daemon 重注册
的 receipt 才能验收。周期和功率分开实验，保留默认路径及所有失败证据。
