# Linux Bluetooth / BlueZ 与 SparkLink：设计依据和验证边界

2026-10-11 重审。对标是 Linux Bluetooth 内核协议栈加 BlueZ 用户态生态。
目标为可维护、可扩展的 Linux 通信子系统；当前不能宣称完整、可投入使用或
功能对等。审查基线与确定缺陷见[14 项整改](REVIEW_REMEDIATION_20261011.md)。

## 可借鉴的职责分界

| 接口/职责 | Bluetooth / BlueZ 官方依据 | SparkLink 采用的目标 |
|---|---|---|
| 管理与命令结果 | [MGMT](https://github.com/bluez/bluez/blob/master/doc/mgmt-protocol.rst) 定义控制器管理请求/事件 | Managed 与独立订阅；请求者专属结果，generation、超时/取消明确 |
| 连接数据 | [L2CAP](https://github.com/bluez/bluez/wiki/L2CAP) 消息 socket、流控、安全选项 | 每逻辑通道独立 socket fd；协商可靠能力用 SEQPACKET，不可靠能力考虑连接式 DGRAM |
| 应用服务注册 | [GattManager](https://github.com/bluez/bluez/blob/master/doc/org.bluez.GattManager.rst) 定义用户态服务对象注册 | slkd SSAP codec/协商/事务/数据库/Profile；内核提供 PDU、背压及安全上下文 |
| 用户认证交互 | [Agent](https://github.com/bluez/bluez/blob/master/doc/org.bluez.Agent.rst) 确认/密码/授权交互 | slkd Agent/trust/Bond policy；内核拥有配对机制/密码学/安装与强制 |
| 开发与系统测试 | [功能测试](https://github.com/bluez/bluez/blob/master/doc/functional-testing.rst)、[test-runner](https://github.com/bluez/bluez/wiki/test%E2%80%90runner) 包括协议测试器与内核 VM 方式 | Virtual、实际实现 selftests、VM 真设备，分别标注范围，不能把 fixture 当作实机 |

这是设计借鉴，不表示协议或 Profile 一一对应。最终职责、socket/UAPI 契约及
迁移门禁见 [ADR 0001](decisions/0001-management-channel-service-boundaries.md)。

## 当前能力按证据判断

| SparkLink 项目 | 已有证据 | 未决条件 |
|---|---|---|
| WS73 Native discovery | VM 两只真实 WS73 20+2 轮，普通用户、同 daemon、物理重接；动态 adapter/独立事件/snoop | 故障根因及完整自主恢复；四设备两组并行；完整服务 sandbox |
| 人工错误恢复 | 单对象 bulk IN81 注入，真实 RF 后恢复新 generation，幸存者不变 | 不能证明自然消失/重枚举根因闭合；宿主原生对照未授权/未执行 |
| 连接/socket | 影子TX ring/重复提交已删，解析wire handle并在backend成功后记账，实际Rust/C边界测试通过 | credit/协议/通道状态仍待接通；原生socket未实现，无真实数据通道验收 |
| 安全/Bond | 危险旧配对/测试密钥降级已删，FFI失败传播；Bond元数据及错误边界测试存在 | 每连接认证、标准向量、真实安装/可恢复凭据、Agent互通 |
| SSAP/Profile/HID | 未达标准旧wire Engine/通知队列已删；权限命名/转换/入口已对齐，实验框架隔离 | 用户态Engine/PDU socket、每peer权限/预算/credit/ACK、请求路由、服务和应用互通 |
| 其他 backend/发布 | UART/SPI不再伪造成功，Virtual模型/部署文件存在；固定提交9个严格CI作业成功 | 真实backend、Proxy、权限/PM/完整构建/兼容/全sandbox矩阵 |

[物理证据](evidence/ws73-vm-physical-20261010.json)和
[人工恢复证据](evidence/ws73-vm-artificial-recovery-20261010.json)保留其历史
源码/hash 范围；后续源码变动须重新回归。U10 仍 7/8，全 S0–S6/issues 保持开放。

## 纠正此前判断

Rust 可约束部分错误，不能自动消除竞态、协议错误或 FFI 生命周期风险。
代码行数、ioctl 数量、框架/配置文件的存在都不能证明架构或支持更完整。
BlueZ 有虚拟设备、协议测试器和内核 VM 测试；旧文档称其缺少系统测试不成立。
原始硬件控制参数更多也不代表应用体验更好。

generation、owner、恢复状态和证据链是我们的设计重点，需要隔离/失败回归证明。
竞争验收比较可重复的多设备隔离、异常恢复、安全拒绝、服务互通和应用集成。
吞吐、延迟分位数、功耗要有同条件 Bluetooth 基线才可比较，目前不宣称领先。
清理安排见[生产调用审计](LEGACY_CLEANUP_20261011.md)，不以全局 allow(dead_code)
或过时“已完成”标记替代接通与验收。

旧内核SSAP wire Engine已因标准格式不符限制并移除；用户态标准Engine尚未接通，不能将历史codec用例或本地staging视为服务互通。见[当前边界](SSAP_LEGACY_CONTAINMENT.md)。

2026-10-11再次收到的分析已对最新bde171beb2e0/aece3407e1c1核对；
[权限整改与实际调用门禁](SSAP_OPERATIONS.md)、
[新镜像20+2回归](evidence/ws73-vm-ssap-operations-regression-20261011.json)和
[CI](https://github.com/OpenSparklink/sparklink/actions/runs/38081123658)记录当前变化。
保留物理历史证据及其xHCI warning，不用本批无warning替代历史故障根因。
