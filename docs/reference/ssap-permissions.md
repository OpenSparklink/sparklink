# SSAP 操作权限语义

权限位审查的历史基线：Linux `31769ea4b8c0`、用户态 `ac64b3566f33`。
本页维护仍复用的权限类型及当前入口契约；实际服务、安全与长写范围须分别核对
[当前资格](../../project/current-capabilities.md)，不能由权限位声明推导。
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

`org.sparklink.ServiceManager.RegisterLocalService` 是现有唯一用户态数据库的
入口，当前只接通 READ 和 WRITE_WITH_RSP（mask `0x05`）；其他有效操作位返回
NotSupported，保留位返回 InvalidArgs。注册成功只表示本地 staging；远端真实
发现/读取/写入须经唯一 Engine 和对端业务核对，不能使用已退休的 facade 代替。

## 测试和证明边界

保留实际 C/Rust/Python 同源权限回归、保留位、缩窄和超长拒绝；离线一致性
不等于 SSAP 双端操作或安全证明。旧数据库调用和当时测试范围见
[权限整改原始记录](../../project/reference/ssap/ssap-operations.md)，已删路径见
[生产剥离审计](../../history/ssap/ssap-production-separation-20261013.md)。
当前实机资格仅由[能力入口](../../project/current-capabilities.md)维护。

## 唯一 SMTC 的通道安全要求

`main.conf` 的 `[ssap] channel_security` 在 daemon 启动时校验，允许整数
`0`、`1`、`2`，默认 `0`。未知字段、负数、错误类型及更高等级拒绝启动，
不回退默认值。该值复制到每个 Connection 对象，在首次 SMTC 绑定前固定；
只读 D-Bus 属性 `org.sparklink.Connection.SsapSecurityRequirement` 返回该要求，
不表示当前已满足。没有运行期热更新或同 lifetime 升级、重绑承诺。

| 要求 | SMTC 首次绑定行为 |
|---|---|
| `0` | 保留连接发布时自动启动的基本通道 |
| `1` | 要求内核当前 Session 的 SDK111 已安装加密机制；未满足不绑定 |
| `2` | 要求当前 Session 的 SDK111 数字比较机制；仅等级 1 不足 |

非零要求下，发布 Connection 不启动普通 SMTC。真实原生安全请求完成后，
daemon 提示同一 Engine 启动；显式 SSAP 请求也可尝试首次绑定。最终准入仍由
内核核对当前 generation、lifetime、lease、安全等级及 epoch。Agent 批准或缓存
结果不授予通道权限。绑定失败时 SSAP 调用失败，不降级、不新建另一套 Engine。
Engine 启动后的过期、撤权、断链和旧安全 epoch 由原 Grant/socket 路径拒绝；
失败 Engine 不在同一 lifetime 自动重开。两端须各自满足本地策略。

这是整个 SMTC 的最低传输要求，不是属性级认证/本地授权或 Bond 策略；
`policy.min_encryption` 的非零值仍明确不支持。READ/WRITE 等操作位不携带安全
等级。数字比较机制不等于已绑定命名身份，也不构成独立 RF 加密证明。
新增实现的离线、形式化和实机资格分别记录，不能继承旧普通 SSAP 通过结论。


## 原请求观察与响应限制

唯一Engine的生产Native Wire读取真实内核消息上下文；unknown、非current、身份/
lifetime/channel不匹配或control截断均失败，不从最新连接快照给旧请求升级资格。
响应、错误和指示ACK携带该原RX epoch与观察机制下限，并固定原响应义务的绝对
单调期限，由原Session/Grant/Ticket在实际USB提交时再次强制；软件准入不等于
物理或对端完成。显式AF_UNIX测试Wire不生成安全上下文，不进入生产构建。

此机制仍不是逐属性安全策略或本地授权。主动ExchangeInfo/客户端请求继续受原
fd Grant管理，细粒度主动意图另行接通。操作位、命名身份/Bond、实际机制和本地
授权保持独立；失败响应不会回滚已发生的数据库写入，请求超时也不能证明对端未
执行。精确ABI/错误/原期限见[接口参考](interfaces.md)，资格只在唯一能力入口维护。
