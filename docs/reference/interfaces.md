# 接口与能力的查找入口

| 接口 | 权威来源 | 使用边界 |
|---|---|---|
| 内核 UAPI／socket | 匹配的 Linux `include/uapi/linux/sparklink*.h`，及 Rust `slk-protocol` | 尚未发布，按当前调用路径核对 |
| D-Bus | `crates/slkd/src/dbus_iface.rs` 及相关对象模块 | 观察、管理与授权分开；对象绑定当前设备生命周期 |
| C API | `crates/libsparklink/include/sparklink.h` 与生成配置 | 保持头文件、实际 cdylib 与匹配内核版本一致 |
| Python | `bindings/python/sparklink/` 与 ABI 检查 | 与文档构建的 Python 项目分开 |
| CLI | 当前构建的 `slctl --help`、`slkconfig --help` | 原生管理、离线诊断和迁移中的旧命令有不同限制 |
| 当前资格 | [CURRENT_CAPABILITIES](../CURRENT_CAPABILITIES.md) | 区分源码、离线、模型、实机与未决条件 |
| 目标设计 | [ARCHITECTURE](../ARCHITECTURE.md) 与 ADR | 不代表接口已接通 |

可选 UserHost 目前属于低优先级延期规划。旧 SSAP 业务入口的移除，也不意味着
新的用户态 SSAP Engine 已实现。错误和 NotSupported 行为以当前源码及资格为准。


## 本批源码核对的状态（未发布 ABI）

核对用户态 `670674736ac90` 和 Linux 已提交 `88372a9b7cbc`。内核另有未提交诊断整改，未视为该基线的已实现或实机资格。

| 范围 | 当前状态与限制 | 源码定位 |
|---|---|---|
| Native 管理／诊断 | 版本化请求，controller generation／所有权检查；新标准 Diagnostic 修复尚未提交验收 | `slk-protocol/src/ioctl.rs`、内核 `sparklink_core.rs` |
| Native WS73 发现／连接／通道 | 已接通路径；实机资格仅限能力页所列准确提交及场景 | `slkd/src/dbus_iface.rs`、`libsparklink` Native API、内核 socket |
| D-Bus ServiceManager／RemoteService | 正常业务明确 NotSupported；非法参数可先 InvalidArgs；不表示服务已远端发布 | `slkd/src/service.rs` |
| 旧 SSAP ioctl | 业务命令已删除，旧编号 ENOTTY，不提供兼容 fallback；权限类型继续复用 | `slk-protocol/src/ioctl.rs`、内核 UAPI |
| 旧 property／write facade | property 超 248、write 超 252 字节拒绝；这是遗留输入校验，不是新 Engine MTU 承诺 | `slkd/src/service.rs` |
| Profile／transport 实验 | 独立 `slk-experimental`；不构成默认生产能力 | 实验 crate README、构建 feature |
| UserHost／厂商 Host 适配 | P4 规划，接口／实现／证明／实机均未完成 | ADR 0003 |
| 新用户态 SSAP Engine | 待接通；不存在的长写／通知能力不得模拟成功 | 唯一实施计划 WP08 |

C 头、Rust FFI 和 Python 绑定应匹配准确源码，不能根据函数声明推导硬件支持。本表是状态查找参考，完整资格仍仅维护于能力入口；逐字段自动生成 API 及全错误矩阵尚待下一批。
