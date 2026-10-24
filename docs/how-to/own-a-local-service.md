# 在实验 VM 中持有一个应用 SSAP 服务

本指南面向已准备好 WS73 VM 的应用开发者。目标是取得本应用的本地服务回执，
让已建链的对端读写，并明确撤回该登记。当前资格见[能力入口](../../project/current-capabilities.md)：
本页说明基础 C/Python Owned API，不授当前页面或分支实机资格；资格仅适用于能力入口
中的准确源码和 artifact。本页交互示例只做静态校验，手动终端全流程尚未单独封存。
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

## 处理失败和退出

EACCES 时核对服务组及实际 system-bus 策略；EOPNOTSUPP 时核对操作位、审批模式和
权限位组合。超限初值会被拒绝，不能截断为短值。owner/generation 失效后重新取得当前
身份，不能把旧回执绑定到替换 daemon。错误与布局见[权限参考](../reference/ssap-permissions.md)。

超时或回复丢失可能发生在远端效果之后，不能当作回滚或盲目重试。显式 unregister
失败需保留错误；close、context 退出和析构只释放本地引用。其他派生引用可能继续
持有 caller；最后 caller 退出才触发 daemon 的 owner 清理，不承诺它已同步完成。
