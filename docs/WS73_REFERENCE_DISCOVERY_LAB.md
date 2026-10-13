# WS73 参考 Host 的 VM 设备发现对照

<!-- documentation-scope: 20261014 -->
> **阅读范围：混合资料：有效语义与历史记录。** 参考 Host 的 guest 发现对照与故障追踪。
> [主题归纳与去向](project/uppercase-document-guide.md)；[推荐入口](how-to/prepare-vm-gate.md)。
> 原文中的源码、失败、PASS 与命令仅适用于其记录版本；当前资格以 [CURRENT_CAPABILITIES](CURRENT_CAPABILITIES.md) 为准。

本对照只运行在隔离 VM。原 `libws73-usb` f4d85d0 源码和 server/client
二进制不改动；固件为用户指定 1.10.111 三文件合并，私有 blob 不入库。
参考代码没有合入生产内核或 slkd。

## 已观察到的失败机制

无 udev daemon 的精简 VM 中，server reset 后 guest sysfs 已出现 device4、
bcdDevice0100、两个端点。新建的独立 libusb context 同样看到它，但 server
原 context 在此后34次设备列表读取仍返回旧 device3、bcdDevice0318、五个
端点，最终 open 旧对象返回 -4/NO_DEVICE。旧 context 返回的配置描述符成功
并不意味着设备仍存在。跟踪器没有修改设备列表、回复、credits 或返回值。

补齐 udev daemon 的 maintenance VM27 使用相同原参考二进制、同 libusb、
同跟踪器和从 runtime 开始的相同拓扑，原 context 实际观察 boot device4
和重新上传后的 runtime device5；server/client 完成启动，client 退出0。
捕获719包、零丢包、taint0、QEMU退出0。已独立核对真实 Create OUT、成功
CommandStatus 和两只控制器的30字节成功连接事件（handle0，角色相反）。
[对照证据](evidence/ws73-reference-udev-discovery-connection-20261012.json)。

这支持**参考实验 VM 缺少 udev 导致长生命周期 libusb 设备列表不刷新**的
环境原因。它没有查明以前原生驱动 bulk 超时、设备消失或切电不恢复的根因，
不关闭这些事项，不计非人工自动恢复通过。

参考 client 日志还记录 SSAP 发现、读、写、订阅、通知 PASS；当前证据只把
连接 OUT/Status/双端 outcome 做了 wire 级核对。ACL/SSAP 内容未独立完整复算，
不能据此宣称本项目 SSAP、安全或 Profile 完成。server 被实验 supervisor
正常终止，不能把它的 -15 误报为自然控制器断连。

## 跟踪和复现

工具源文件 [libusb_trace.c](../tools/reference/libusb_trace.c) 与
[fresh_context.c](../tools/reference/fresh_context.c) 是本项目独立诊断代码。
可以在开发主机编译、复制入 VM，**执行只在 VM**，日志写 guest `/evidence`。
它们记录 libusb 返回的 bus/address/port、bcdDevice、配置读取 errno/端点数；
fresh helper 每100ms重建独立 context，不 claim USB interface。

```sh
cc -Wall -Wextra -Werror -fPIC -shared $(pkg-config --cflags libusb-1.0) \
  tools/reference/libusb_trace.c -ldl -o libusb-trace.so
cc -Wall -Wextra -Werror $(pkg-config --cflags libusb-1.0) \
  tools/reference/fresh_context.c $(pkg-config --libs libusb-1.0) -o fresh-context
```

在各自冷启动的 VM 使用相同参考二进制、固件、USB映射和捕获方式：一份精简
init 不启动 udev；另一份在挂入 USB 前启动 guest udev daemon，先通过 guest
`udevadm control --ping`，并记录实际进程。仅 guest root 需要设备访问权限。
不为了此对照关闭正常主机 udev 服务。

```sh
# 仅在 guest，捕获已启动，/evidence 已挂载：
./fresh-context > /evidence/fresh-observer.log &
LD_PRELOAD=/libusb-trace.so ./sle73_minimal_server \
  --path 1-2 --mac 00:01:09:32:54:F9 /reference-combined.bin
```

同时每50ms记录 guest sysfs 的 devnum、bcdDevice、速度、配置和端点数，
独立保留 kernel日志与 usbmon。对比必须按墙钟对齐，并保存旧实例的失败，
不能仅认后来一次成功或改大超时。原源码 read_capture 拒绝 ACL TX，因为它
只核对 Native command 路径；[独立参考 reader](../tools/ws73_reference_capture.py)
只在参考对照中验证 ACL envelope 并排除其 command 资格，不放宽生产 reader。

## 后续 Native 连接定位

参考 Create 的27字节和 negotiable 广播的49字节，逐字节等于之前 Native
失败案例。因此先对照真正不同的步骤：参考发送 SetPublicAddress 0x0405
并收到成功 Complete；Native目前查询 ReadMacAddr，但没有同等设置步骤。
此外扫描参数和广播数据不同。先逐项做受控对照，再决定 typed initializer
和状态来源的变更，禁止凭猜测加入命令或伪造初始化成功。

Native VM93在无udev失败对照后再次独立完成 RF22/QMP guest生命周期，
1369包/零丢包/taint0。原未执行队列和九例部分初始化资格继续保留。
Native connection、connected撤销、SSAP及完整 S0–S6/28项仍开放。

参考连接对照之后 Native VM94也独立完成RF22，1267包/零丢包/
taint0、同slkd/bus；这是当前46db内核/cd64065服务与工具的回归，不是
参考连接资格向Native转移。正常VM累计94、维护27，失败不归零。
