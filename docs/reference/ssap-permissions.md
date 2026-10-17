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

主动 ExchangeInfo 和客户端请求也通过原 fd 的 PREPARE_TX ioctl 取得限制，实际
sendmsg 必须携带限制；没有 raw-send 回退。准备不预留 credit、不续 Grant、不升级
旧 protected fd 的 epoch。客户端回复须匹配原请求 epoch 和机制下限。操作位、命名
身份/Bond、实际机制和本地授权保持独立；失败响应不会回滚已发生的数据库写入，
请求超时也不能证明对端未执行。精确ABI/错误/原期限见[接口参考](interfaces.md)，资格只在唯一能力入口维护。

## 逐属性值访问要求

本地注册 properties 项现为 `(uuid:ay, operations:u32, access:u32, value:ay)`。
`ListLocalServices` 的属性项为 `(handle:u16,uuid:ay,operations:u32,access:u32)`。
未发布接口同步迁移，无旧签名兼容期。操作位仍用表32的 0x73f；access 是独立六位
本地 API 编码，复用固定 NearLink Host 的 NapiPermission，不把它写入远端属性声明。

| access 位 | 值 | 限制 |
|---|---:|---|
| WRITE_ENCRYPTED | 1 | 写原请求观察机制至少 1 |
| WRITE_AUTHENTICATED | 2 | 写原请求观察机制至少 2 |
| WRITE_AUTHORIZED | 4 | 仅 Owned 登记及有效原请求审批可满足；旧 staging 仍 NotSupported |
| READ_ENCRYPTED | 8 | 读原请求观察机制至少 1 |
| READ_AUTHENTICATED | 16 | 读原请求观察机制至少 2 |
| READ_AUTHORIZED | 32 | 仅 Owned 登记及有效原请求审批可满足；旧 staging 仍 NotSupported |

保留位返回 InvalidArgs；授权位不能由任意应用布尔值授予。当前内核的等级 2 表示
SDK111 数字比较机制，不能推导命名身份、Bond 或独立 RF 加密证明。服务端在读取
值或修改数据库之前检查真实原 RX 上下文；普通读取、按 UUID 读取、响应写共用同一
检查。认证不足返回表51错误 8，加密不足返回 10；未获本地授权返回 9；只有当前 Owned 登记的原审批者可满足该要求。公开发现元数据不包含受保护的值或 access 要求。

`slctl ssap-register SERVICE_HEX PROPERTY_HEX OPS ACCESS VALUE_HEX` 只配置本地库。
`ssap-list` 列出本地元数据，不能当作远端发现。`ssap-read`、`ssap-write` 和
`ssap-read-uuid` 末尾可指定 `MINIMUM`（0/1/2，默认 0），经唯一 Engine 和原 fd
约束实际发送；超出当前机制或输入范围明确失败，无明文降级。局部数据库检查、
访问谓词测试和工具有界结果不能替代真实双端请求/拒绝/修改及 USB 证据。

实现已接通；本批新源码的实机资格须单独取得。Kani 检查原生产谓词的七项性质，
工具仍有编译诊断，当前保持“未证明”，不升级为全生命周期或安全协议证明。


`sdk111-*` 是现有实验Agent方法的历史方言名称，不是执行固件的版本证明。
SDK110 U设备两机制的准确短消息/SSAP资格已单列；E、完整负向部署矩阵、命名身份/
Bond及属性授权不继承。当前版本适用范围仍只由能力入口的准确artifact记录决定。


## 应用拥有的本地服务与逐请求审批

`RegisterOwnedLocalService(uuid:ay, properties:a(ayuuay), authorizer:o)` 的 properties
沿用上述四字段（实际 D-Bus 签名 `a(ayuuay)`），返回 `(start:q,end:q,handles:aq)`。
登记者来自真实消息 sender 的 unique name，不能指定其他 owner。`authorizer=/`
表示不提供审批；带授权位的登记此时返回 NotSupported。服务登记仍只表示本地配置。
`UnregisterOwnedLocalService(start:q)` 和 `ReadOwnedLocalValue(handle:q)->ay` 只允许
原 owner；管理组的显式全局移除/本地读权限仍独立。`sparklink-services` 策略只允许
这三个 Owned 方法，不授 controller 管理或普通通道权限；实际最小权限部署门禁待验。

审批调用原 unique owner 的 `org.sparklink.SsapAuthorizer.AuthorizeValue(prompt)->b`。
`prompt` 是 `(request_id:t, identity:(qttqtuyyy), property:q, write:b, deadline:t, value:ay)`；
identity 的实际签名为 `(qttqtuyyy)`，依次为 controller、generation、lifetime、connection
handle、原 RX security epoch、原 RX security level、local TCID、remote TCID、PI。
READ 不发送秘密值；WRITE 携带有界 proposed value。期限是原 RX 响应义务的绝对
CLOCK_MONOTONIC 纳秒，最长五秒；排队和审批不重置期限。超时/方法错误/退出不批准。

每 adapter 最多16个正在登记/活跃 owner watch（单服务一个），同 actor 待发响应、
排队请求和正在审批请求合计最多8条。先监听 owner 退出再核对存活。句柄在同数据库
不复用；删除重建、原 owner 退出或失效审批不能访问新属性。controller退休时先撤销登记，
再在数据库锁之外等待owner watch退出；最终析构保留abort兜底。审批等待不持数据库锁，
不预留协议 credit；唯一 actor 继续处理其他 RX/client/ACK，但按服务请求顺序答复。
期限失败仍失败该 Engine，不承诺同 lifetime 自动重绑。

读/写前通过原 fd 重查 generation/lifetime/security epoch，数据库锁下再核对登记和
owner；这是一份准入快照，不是内核与数据库的原子事务。已经提交的本地写入不会因
随后撤权/断链回滚；原响应继续受原 Grant/Ticket/epoch/期限限制。超时的写入结果
可能不确定。批准只满足本地授权，不满足缺失的加密/认证，也不产生可信身份或 Bond。

`slctl --adapter PATH ssap-serve SERVICE_HEX PROPERTY_HEX OPS ACCESS VALUE_HEX [ask|allow|deny]`
以前台连接拥有服务。默认 ask 要求 `yes REQUEST_ID` 或 `no REQUEST_ID`；原期限外及
旧编号无效。allow/deny 是服务所有者显式本地策略，不是安全 Agent 自动批准。标准
输入 `value` 通过同 owner 读取实际本地值，`quit` 主动注销；进程被杀时由 unique owner
退出清理。新入口沿用唯一 Engine，不新增远端协议引擎。实现、私有 D-Bus、VM 实机和
形式化结果分别记于能力入口，不继承旧 artifact 的资格。
