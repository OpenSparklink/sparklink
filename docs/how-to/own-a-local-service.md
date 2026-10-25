# 在实验 VM 中持有一个应用 SSAP 服务

本指南面向已准备好 WS73 VM 的应用开发者。目标是取得本应用的本地服务回执，
让已建链的对端读写，并明确撤回该登记。当前资格见[能力入口](../../project/current-capabilities.md)：
本页说明基础 C/Python Owned API，不授当前页面或分支实机资格；资格仅适用于能力入口
中的准确源码和 artifact。实际执行与门禁结果由资格记录维护；本批交互示例仅做
静态校验，手动终端全流程尚未单独封存。
驱动、固件及真实设备操作保持 VM-only。

## 准备身份和权限

VM 内需要运行当前 `slkd`、安装匹配的 Python 绑定与应用库，并授予本进程服务登记
权限。`sparklink-services` 授予明确列出的 Owned 方法，普通通道组不自动拥有服务登记权限。
实机服务组资格来自 UID/GID1005、无额外组/cap 的受控部署；通用安装仍单独验收。

管理者先确认目标 controller Ready，提供当前 `index`、`generation`。完整路径形如
`/org/sparklink/slkN_gGEN`；拔插或退休后重新查询，不能只沿用旧索引或地址。
两只设备需要已建立当前连接；本地登记本身不会广播、连接、配对或启动另一个 Host。

## 登记并观察本应用的值

将下面代码保存为 `owned_service.py`。使用演示值；`SsapAccess(0)` 不要求加密或认证。
默认 `authorization="none"` 模式拒绝本地审批权限位。需要逐请求审批时使用
{ref}`显式请求接口 <ssap-language-authorization-requests>`，不能把基础示例
改为默认批准；该新接口的实机资格仍须按准确 artifact 单列核对。

```python
import sys
import time
import uuid
from sparklink import Client, ControllerId, LocalProperty, SsapAccess, SsapOperations

controller = ControllerId(int(sys.argv[1]), int(sys.argv[2]))
service_uuid, property_uuid = uuid.uuid4().bytes, uuid.uuid4().bytes
original = time.monotonic_ns() + 5_000_000_000
with Client(deadline_ns=original) as client:
    service = client.register_local_service(
        controller, service_uuid,
        [LocalProperty(property_uuid, SsapOperations.READ | SsapOperations.WRITE_WITH_RSP,
                       SsapAccess(0), b"hello")],
        deadline_ns=original,
    )

# The service retains this original caller after Client.close().
with service:
    try:
        handle = service.receipt.handles[0]
        print("service UUID:", service_uuid.hex())
        print("property UUID:", property_uuid.hex(), "handle:", handle)
        input("对端完成读写后按回车：")
        value = service.read_local(handle, deadline_ns=time.monotonic_ns() + 5_000_000_000)
        print("当前本地值：", value.hex())
    finally:
        service.unregister(deadline_ns=time.monotonic_ns() + 1_000_000_000)
```

用明确的当前身份运行，不自动选取目录中的第一只设备：

```sh
python3 owned_service.py "$INDEX" "$GENERATION"
```

初次五秒期限约束登记准入，不是服务 TTL。后续读和撤回各有自己的原期限。

## 从对端检查结果

使用[连接级远端 SSAP API](../reference/interfaces.md#cpython连接级远端ssap读写与无响应写命令)，
选择对端当前连接对象。先按实际 UUID/handle 读取并比对 `hello`，再写入一份随机值；
发布进程回车后读取并核对同一份字节。本地登记回执只能证明本地配置，远端 API 返回、
协议回复及发布应用实际读取是不同阶段。需要可靠业务确认时，由应用发送明确回复。

撤回成功表示原 broker 已确认移除本地登记。对端后续访问应按协议拒绝；它不表示
物理连接断开。自动门禁保存双端 USB、对端校验和发布者值观察，不能仅凭本例的打印
宣称另一只设备已经收到或处理。

## 显式公开属性说明

需要对外说明属性含义时，在上例同一个 `with service` 内显式设置：

```python
service.set_description(
    handle, "实验温度读数",
    deadline_ns=time.monotonic_ns() + 5_000_000_000,
)
```

这是公开只读元数据，不能存放秘密；属性值的加密或审批权限不自动保护说明。
对端先执行实际属性发现并确认 `descriptors` 包含 `01`，再用
`connection.ssap().read_description(handle, deadline_ns=...)` 逐字节核对预期 UTF-8。
CLI 可用 `ssap-read-description CONNECTION HANDLE [MINIMUM]`；`ssap-serve` 的原进程
支持 `description TEXT`，会显示本地提交回执。另起进程不能修改原 caller 的登记。
边界与错误见[只读说明契约](../reference/ssap-permissions.md#显式公开的只读属性说明)。
本段是接口用法，不宣称该示例或最新分支已通过实机验收。

## 需要按请求生成只读值时

上面的示例使用数据库存储值。动态只读 Provider 则由原应用针对每次实际请求
提供字节或应用错误。C/Python 收件箱和 `ssap-serve` 共用 Rust SDK 的具体 Provider
frontend，仍由 daemon 中唯一的 SSAP Engine 处理协议。审批请求的布尔答复不提供值。

属性操作位必须恰为 READ。绑定消耗原初值且在该登记内不可更换或解除，之后本地
读取与替换返回 NotSupported，没有缓存回退；公开 type1 说明仍独立处理。
绑定期限只约束这次绑定，不是后续请求的期限。准确边界见
[动态只读值契约](../reference/ssap-permissions.md#owned-read-only-provider)。

下面示例登记一个不要求本地审批的 READ 属性，接到实际请求后由应用显式选择
返回值。保存为 `read_provider.py`，传入当前 `INDEX`、`GENERATION`。十六进制输入
必须在提示中原 `deadline_ns` 到达前完成；等待终端输入不会延长期限。

```python
import sys
import time
import uuid
from sparklink import Client, ControllerId, LocalProperty, SsapAccess, SsapOperations

controller = ControllerId(int(sys.argv[1]), int(sys.argv[2]))
service_uuid, property_uuid = uuid.uuid4().bytes, uuid.uuid4().bytes
original = time.monotonic_ns() + 5_000_000_000
with Client(deadline_ns=original) as client:
    service = client.register_local_service(
        controller, service_uuid,
        [LocalProperty(property_uuid, SsapOperations.READ, SsapAccess(0), b"")],
        deadline_ns=original,
    )

# Keep the original service alive: the inbox/request do not retain its owner.
with service:
    try:
        handle = service.receipt.handles[0]
        with service.bind_read_provider(
            handle, deadline_ns=time.monotonic_ns() + 5_000_000_000,
        ) as provider:
            print("service UUID:", service_uuid.hex())
            print("property UUID:", property_uuid.hex(), "handle:", handle, flush=True)
            # This bounds local waiting only; the delivered callback keeps its own deadline.
            with provider.next_request(
                deadline_ns=time.monotonic_ns() + 30_000_000_000,
            ) as request:
                print("original request:", request.info, flush=True)
                answer = input("HEX, '-' for empty success, or 'error-FF': ")
                if answer == "error-FF":
                    request.reply(b"", status=0xFF)
                else:
                    request.reply(b"" if answer == "-" else bytes.fromhex(answer))
    finally:
        service.unregister(deadline_ns=time.monotonic_ns() + 1_000_000_000)
```

实际值不得超过该请求的 `maximum_bytes`。成功空值是 `reply(b"")`，不是应用错误；
错误使用空值加 `status=0xAF..0xFF`。非法状态、非空错误值或超长值不会消耗原答复
机会，但原期限继续经过。不要自动重试已接受、过期或结果不确定的答复。

C 使用同一条路径：先以 `slk_local_service_bind_read_provider` 取得 inbox，
用 `slk_read_provider_next` 非阻塞取出请求，再读取 `SlkReadProviderRequestInfo`
并调用 `slk_read_provider_request_reply`。例如，以下片段处理一个已经取得的请求：

```c
SlkReadProviderRequestInfo info;
int result = slk_read_provider_request_info(request, &info);
if (result == 0) {
    /* Explicit empty success; use status 0xFF with NULL, 0 for application error. */
    result = slk_read_provider_request_reply(request, 0, NULL, 0);
}
slk_read_provider_request_free(request);
/* result == 0 means local acceptance, not peer receipt. */
```

C 的 `next` 返回 `-EAGAIN` 时，可等待 `slk_read_provider_fd` 返回的可读通知 fd，
再尝试取请求。Python 对应 `notification_fd()` 和不带期限的 `next_request()`。
fd 由调用者关闭，只用于 poll；不得读写它的计数器。fd、inbox 和 request 都不持有
原服务的 Owner。释放 request 与回调实际结束是两件事，均完成后才释放待决容量。
完整签名、错误及关闭顺序见[接口参考](../reference/interfaces.md#sdk-只读-provider-收件箱)。

需要本地审批时，以 `authorization="requests"` 登记并设置所需 READ 授权位；应用
同时处理授权和 Provider 两个独立通知入口，先按实际策略回答授权请求，再提供值。
批准不生成值，两阶段仍共享服务端原请求期限。不要在等待审批时只阻塞等待 Provider。

这些收件箱已在源码中接通；Python 封装、ABI 和生命周期离线检查与实际设备资格
分别记录。示例和离线结果不向最新分支转授历史实机资格，准确结果由资格记录维护。

使用现有前台 `ssap-serve` 时，将 OPS 设为1，ACCESS 按应用需要设置；原初值只用于
登记，绑定后即释放。进入前台后输入 `provider`，等待 `SsapReadProviderBound` 本地
绑定回执，再让对端发起真实属性读取。实际请求显示 `SsapReadProviderPrompt`，
按提示的 `pTOKEN` 回复 `provide pTOKEN HEX`，空值用 `provide pTOKEN -`；应用失败
用 `provider-error pTOKEN AF`，状态允许两位十六进制 `AF..FF`。

若属性还要求本地审批，先回答原 `yes TOKEN`/`no TOKEN` 提示，再提供值；批准本身
不生成成功值。两次等待共用原期限。错误或过期 token、重复答复、超出提示预算的值
均拒绝；不要预先发送答复。输入 `quit` 会先停止本地答复，再撤回登记和移除回调。
对端仍须检查实际字节或应用错误，前台打印不表示远端已经收到。

完整2042字节值的 hex 加命令/token 可能触及终端的行截断边界。终端单行须少于
4096字节（含换行）；超出时使用管道，在读到实际提示后发送答复，单行不超过4160
字节。工具拒绝触及截断边界的终端行，不会以截短值冒充成功。

## 处理失败和退出

EACCES 时核对服务组及实际 system-bus 策略；EOPNOTSUPP 时核对操作位、审批模式和
权限位组合。超限初值会被拒绝，不能截断为短值。owner/generation 失效后重新取得当前
身份，不能把旧回执绑定到替换 daemon。错误与布局见[权限参考](../reference/ssap-permissions.md)。

超时或回复丢失可能发生在远端效果之后，不能当作回滚或盲目重试。显式 unregister
失败需保留错误；服务 close、context 退出和析构释放本地引用，并停止该登记的本地
Provider 准入。其他持有 Client 的派生引用可能继续持有 caller；Provider inbox、
request 与通知 fd 不在其中。最后 caller 退出才触发 daemon 的 owner 清理，不承诺
它已同步完成。仅关闭 inbox 不撤回登记，也不恢复原存储值。

若提供值的进程异常退出，先确认该 Owner 的本地登记已被清理，再按新的请求检查
远端结果。待决读取可能收到应用错误或属性不存在，也可能因原期限耗尽而失败；
已经编码的响应仍可能交付。不要把进程退出、一个 `EIO` 或登记消失当作原请求已
撤回的证明，也不要重新使用旧 token。其他 Owner 的服务应使用各自的登记和请求检查。

如果 Provider 一直没有答复，分别检查调用者的 SDK 期限和提示里的服务端期限；
SDK 返回 `ETIMEDOUT` 不表示服务端期限已经到达。超过原提示期限后提交
`provide pTOKEN HEX`，前台应输出 `SsapReadProviderInput: rejected stale token,
expired request or invalid value/status`，不会重新开放该请求。保留原提示和错误，
不要用新 token 或新的超时预算重试旧请求。

服务端原义务到期后，当前 SSAP actor 会进入失败终态；调用者的在途义务也可能使
其 actor 终止。此时应显式清理登记，并按连接管理流程取得新的连接 lifetime 后再
使用 SSAP；不承诺同一 actor 会自行恢复。独立的普通通道是否继续可用，应由对端
实际校验和回复确认，不能根据 SSAP 的超时日志推断。
