# SSAP 操作权限语义

源码核对：Linux `31769ea4b8c0`；用户态已提交 `ac64b3566f33`。
这里是仍复用的权限类型契约，不表示 SSAP 服务/安全/长写已经接通。
标准语义来源为项目审查使用的 T/XS 20001-2025 V1.2.0 表32；受限原材料不发布。

| 命名 | 值 | 含义 |
|---|---|---|
| READ | 0x01 | 读取 |
| WRITE_NO_RSP | 0x02 | 无响应写入 |
| WRITE_WITH_RSP | 0x04 | 有响应写入 |
| NOTIFY | 0x08 | 通知，无ACK |
| INDICATE | 0x10 | 指示，需ACK |
| BROADCAST | 0x20 | 广播 |
| DESC_WRITABLE | 0x100 | 数据值说明描述符可写 |
| CLIENT_CFG_WR | 0x200 | 客户端配置描述符可写 |
| SERVER_CFG_WR | 0x400 | 服务端配置描述符可写 |

有效mask=0x73f。b6、b7、b11..b31保留，必须拒绝。read+notify是0x09，不能获得
任何写权限；两种写权限不能相互替代。操作声明与认证/加密/授权是独立约束，
不能把设置权限位当作已经授予调用者访问。标准Engine须同时核对peer安全上下文。

## 当前源码与拒绝规则

C `include/uapi/linux/sparklink_ioctl.h` 的 `SL_SSAP_OP_*`、valid/allows/fits_legacy
和 Rust `slk_protocol::SsapOperations` 使用同一 mask。
Python `bindings/python/sparklink/ssap.py` 拒绝 bool、负数、超32位和保留位；
`to_legacy_bits` 显式拒绝 descriptor 权向8位缩窄。
legacy narrowing 仅用于遗留 facade 输入和回归，不恢复已删除的数据库/业务 ioctl。

slkd `Service.AddProperty` 先校验权限和值（最多248字节），合法业务仍 NotSupported；
遗留 WriteProperty 超252字节、RemoteService.Write/CallMethod 超248字节拒绝，不静默截断。该输入上限不是新 Engine 的协商 MTU
或真实长写资格。无响应写和有响应写、通知和指示分别授权；设置位不能绕过
peer 身份、连接授权和认证/加密条件。安全/Bond 尚未实机合格时不得宣称可信权限。

## 测试和证明边界

保留实际 C/Rust/Python 同源权限回归、保留位、缩窄和超长拒绝；离线一致性
不等于 SSAP 双端操作或安全证明。旧数据库调用和当时测试范围见
[权限整改原始记录](../SSAP_OPERATIONS.md)，已删路径见
[生产剥离审计](../SSAP_PRODUCTION_SEPARATION_20261013.md)。
当前实机资格仅由[能力入口](../CURRENT_CAPABILITIES.md)维护。
