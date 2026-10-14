# API 查找与旧表退役

本文只定位接口，不另维护能力矩阵。当前支持和限定资格见
[CURRENT_CAPABILITIES](CURRENT_CAPABILITIES.md)，目标职责见[ARCHITECTURE](ARCHITECTURE.md)。
完整字段、错误、权限参考仍分批补齐；存在声明或绑定不表示真实固件支持。

## 旧表的处理

[旧 544 行 ioctl/绑定总表](https://github.com/OpenSparklink/sparklink/blob/ac64b3566f330557a025f1994b0a6f49a22b3bd3/docs/API.md)
按准确提交保留；其中实验/注入、已删状态和旧编号不能用于当前程序。
UAPI 尚未发布，已删除入口无兼容期；不可通过旧接口 fallback 或模拟 Complete 支持业务。

## 按当前入口查找

| 要查什么 | 入口／实际源码 | 边界 |
|---|---|---|
| 管理、诊断、socket 与绑定 | [接口定位](reference/interfaces.md)、匹配内核 `include/uapi/linux/sparklink*.h` | 字符设备 ioctl 与通道 socket ioctl 分开，不能一概说都经 `/dev/sparklink` |
| 完整 controller 事件 | [事件参考](reference/controller-events.md) | generation/游标与作者私有诊断结果分开 |
| DLI 监控 | [snoop 参考](reference/controller-snoop.md) | 复制流量，不取得控制所有权或业务 ACK |
| SSAP 操作权限 | [权限参考](reference/ssap-permissions.md) | 类型仍复用，旧数据库/业务 ioctl 已删除 |
| C／Python | `crates/libsparklink/include/sparklink.h`、`bindings/python/sparklink/` | 头/库/内核必须匹配；不能用旧表推导函数存在 |
| D-Bus／CLI | `crates/slkd/src/` 对象、当前 CLI `--help` | 正常不支持能力明确拒绝；观察与控制授权不同 |

## 已删除与明确拒绝的范围

旧 read 44 字节事件队列、0x70/0x71统计、0x82 DLI poll、旧 SSAP 业务 ioctl
已删除，旧编号不得当作有效 API。旧连接/发现/安全/PM 等实验 facade 的拒绝语义
按[接口参考](reference/interfaces.md)查找，不能因 Rust 类型还存在就推断可用。
新 ControllerEvent、DiagnosticResult 和通道能力查询分别有自己的身份及授权契约。

旧 SSAP 本地 staging 不是远端服务发布。默认 ServiceManager/RemoteService 的
未接通业务返回 NotSupported，非法输入可先 InvalidArgs；250/253/254/255 等
业务长度资格也不能转授为 SSAP 长写支持。

## 阅读历史与当前开发

[全部大写原文归纳](project/uppercase-document-guide.md)区分权威、混合与历史。
文档审计基线时 SSAP actor 尚未提交；后续准确实现与资格仅从当前能力入口查找，
本页不独立授予实机或正式 API 资格。
