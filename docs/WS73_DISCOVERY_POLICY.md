# 每设备 WS73 发现策略

最新生产 U7b1bd0464ec9 的默认真实RF22保持通过；四设备功率0首轮仍超时，
初始化出处与失败清理的限定实机范围通过。策略与硬件状态仍分别查询，出处
不改写为新STOP，详见[初始化OFF边界与receipt](WS73_INITIALIZATION_OFF.md)。

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
Ud17f3f6f531c 的新 VM 验证；该默认receipt不验收自定义参数。后续两个限定案例
见下文，源码回归不能替代空口证据。
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

首批自定义参数验收只允许独立双设备 `run --qmp-hotplug`。随后四设备格式v2
接通下述策略证明，允许独立 `--parallel-pairs` 对照；Managed 注入仍不得带
自定义配置。父进程的双设备记录仍将
自定义 RF 验收标为 false；只有终止后独立核对每个实际注册的策略查询、
全部初始化/START 原始参数、Complete、随机 marker 空口与同 daemon 重注册
的 receipt 才能验收。周期和功率分开实验，保留默认路径及所有失败证据。

## 两个单变量实际案例（2026-10-12）

新服务源码Ua9dfe3fcbb80、内核K060011963b5e，两次独立VM均选主机
1-2.1.1/CD与1-2.1.4/F9。每例两只独立Ready、RF20交换角色，QMP guest-only
退役CD、保持F9原注册，再加CD为新generation并RF2；同slkd/认证bus，
UID1000/caps0。两例分别1265包、零capture drop、taint0、QEMU0。
每例三项注册/六次show、全部25个广播和28个扫描参数、22轮marker/data/
地址/RSSI/Complete及10秒期限已在进程终止后独立核对，重算与父进程证明相同。

| 案例 | CD请求 | F9请求 | 实际参数/回复 | 限定证据 |
|---|---|---|---|---|
| 周期 | 广播min/max1237，power127，scan1600/800 | 默认1200/127/1600/800 | CD全部广告参数1237，F9全部1200，扫描不变 | [周期RF22 receipt](evidence/ws73-frozen-custom-period-real-20261012.json) |
| 功率 | 默认1200，power0，scan1600/800 | 默认1200/127/1600/800 | CD实际Complete选中-2，F9选中20，周期/扫描不变 | [功率RF22 receipt](evidence/ws73-frozen-custom-power-real-20261012.json) |

周期receipt SHA256 `8c0857f87616bc843837e2f34e0b2d019ec67940f43ab598374d9d9cf16d827d`；
功率receipt SHA256 `c03edf817ba5dd8e00225fd29853ce2fb1871a498d40d5bd023919b40dcfc0d1`。
功率请求是偏好，不把0请求写成0实际生效；独立核对器原先假定实际0而拒绝，
随后保留失败并按原始`fe`/有符号-2及slctl关联重算，没有改写实际run。
CD被接收的RSSI约-40，仍非校准辐射功率测量或四设备根因证明。

复现使用同一验签kernel/module/boot smoke和此精确源码的service bundle。
周期私有配置：

```toml
[[ws73.adapters]]
address = "00:01:09:32:54:CD"
[ws73.adapters.policy]
advertising_interval_min_slots = 1237
advertising_interval_max_slots = 1237
```

另一次功率配置只保留同一地址/policy表及`tx_power_dbm = 0`，省略周期字段
使其回到内建1200；不要在同一次实验同时改变周期和功率。以新的output运行
prepare，并分别追加`--native-discovery-config <case.conf>`。配置必须在
prepare后保持不变；不得手改冻结root、manifest或服务payload。运行：

```sh
python3 tools/ws73_target.py run --prepared <case-prepared> --output <fresh-case-output> \
    --ports 1-2.1.1 1-2.1.4 --qmp-hotplug --timeout 1800
```

`PASSTHROUGH_SUPPORT_PASS`仅是父进程的RF/guest生命周期判断；还须核对
导出的`slkd-config.conf`/校验输出与冻结SHA、每项show请求策略及初始化/START
原始参数。功率以关联Complete的有符号字节为准，不能从配置或RSSI反推。
精确源码[CI38169431821](https://github.com/OpenSparklink/sparklink/actions/runs/38169431821)
九项成功；本地配置CLI4例、340工具例及严格all-target/all-features clippy通过。

正常VM累计63、维护20、四设备尝试仍5。后续先迁移四设备证明对自定义策略
的范围标记，再分别开展周期/功率对照；保持默认0启动偏移，无测试sleep补偿。
这两个案例不验收默认四设备、物理拔插、自然故障RCA、单只非人工恢复或整项
Managed；全部原S0–S6/28项scope保持，相关issues继续开放。

## 四设备参数证明格式v2

`slkd --check-config --dump-ws73-policies --config <file>` 输出实际解析器的
规范化默认值和地址覆盖，仍在总线/设备管理权前退出。prepare以精确staged
daemon生成冻结的expectation，保存配置及expectation哈希；不在Python重写TOML
解析或默认值继承规则。guest将expectation归root、设为0444，并显式加载经
哈希核对的配置。两个普通用户worker必须引用同一expectation且前后不变。

每项注册RF前后各一次Ready/show查询，核对generation/address/profile及
全部请求策略；独立USB重算检查每个初始化/START的完整49字节广告与8字节扫描
参数、真实成功Complete、每次选中功率原始字节。原RF40/20重叠、实际OFF、
阴性对照、同daemon、随机marker与10秒期限均保持。

只有格式v2、无自定义配置、规范化值严格为默认v3且启动偏移0，才可获得
`default_parallel_gate_acceptance`。自定义配置通过时仅为
`custom_policy_parallel_contrast_acceptance`，不可关闭默认并行issue。旧格式v1
继续核对历史RF/时序，标记`historical_parameter_scope`，不补发缺失的完整参数
资格。新合成回归拒绝配置/worker/argv不一致、缺失/失效/时序错误查询、广告
周期/信道/功率或扫描窗口漂移、缺失domain和失败Complete；不作为实机证据。

格式v2已执行[三个四设备单变量案例](WS73_PARALLEL_POLICY_MATRIX.md)，均FAIL；
配置/实际参数一致不等于RF40。新鲜OFF所属domain解析修复有离线原始Complete
重算，重复OFF的0x0b仍失败；初始化OFF出处查询和实际失败清理验收继续开放。
