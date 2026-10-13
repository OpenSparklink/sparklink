# WS73 active-radio SIGKILL 与原 generation 接任

<!-- documentation-scope: 20261014 -->
> **阅读范围：历史审计／验收资料。** SIGKILL、最后 File 和原代次接任的限定证据。
> [主题归纳与去向](project/uppercase-document-guide.md)；[推荐入口](CURRENT_CAPABILITIES.md)。
> 原文中的源码、失败、PASS 与命令仅适用于其记录版本；当前资格以 [CURRENT_CAPABILITIES](CURRENT_CAPABILITIES.md) 为准。

2026-10-12，限定实机门禁通过。生产内核和 daemon 未为此修改；新增的是
独立 VM 监督、记录与离线核验。完整 Managed、在途回复强杀、自然故障根因、
每设备非人工自动恢复和 S0–S6 尚未完成。

## 实际语义与验证

普通应用 UID1000、四组 capabilities 为0，通过实际 slctl 使第一只广播、
第二只扫描。guest init 对它自己的 slkd 子进程发送 SIGKILL 并 wait，实际
返回137。daemon不能执行正常 shutdown；内核最后 owning File 关闭撤销管理权。
独立非 owning fd 只观察，不 RELEASE、不提交 STOP、不重置 USB。

- 原两只分别只有一条所需 STOP：广告 `0x0c05` 参数五个0，扫描 `0x1002`
  参数两个0。完整 usbmon 中各有原成功 OUT 与真实成功 DLI Complete。
- 非 owning fd 的 canonical ioctl 原字节及解码结果一致，lease/flags均0，
  两只原 index/generation 保持 Ready，管理权 Free，两个 domain 都 Off。
- 新 slkd PID573、bus owner `:1.9` 取代 PID541、`:1.0`，原 generation1/2
  接任 Held。没有USB退役、重启内核、重新枚举或重新初始化。
- 每只 `advertise initialized-off`、`scan initialized-off` 实际返回
  `UnknownObject: initializer provenance absent or invalidated`。原 kernel Off
  由真实 STOP 确认，但新 daemon 没有旧实例私有的初始化凭据，不能复制。
  `adapters::initialize` 对 ControllerReady 明确直接返回。接任至四项查询结束，
  两只均零新设备命令；没有补造初始化结果或发送冗余 OFF。
- 接任者随后完成随机标识真实交换角色20轮、guest-only退役/重注册后2轮，
  匹配数据、地址、RSSI并满足10秒时限。同一接任者在这22轮中不重启。

原 capture 1293包、零 kernel/interface drops，QEMU退出0、VM taint0。固件仍
为用户指定 combined-1.10.111 的已限定 SHA；controller metadata不是版本断言。
物理拔插、四设备默认并行、自然恢复及在途强杀不从这个门禁外推。

## 源版本、原失败和证据

实际 kernel `060011963b5e3f45e9312399d2f68b8077a33353`，当前 kernel源码
`4ee4af55f38c0f2a470962978357ce3460f12d21`；实际编译服务
`f572f7890d42f2a9abbb8f0bb5b6834a09ebe5a6`，工具与冻结准备源
`a2c3b4951aa9078091d6ac9ffec35a5a8074cd13`。这次仅工具变更，服务 bundle
和实际编译版本沿用已验证生产闭包，prepare独立核对源码/二进制哈希。

首工具 `0478a8dc81d2e48f386b5f8be4f0861ea01c03aa` 的正常VM72整轮 FAIL，
没有完成RF。它错误要求接任者重新初始化并返回 op5/6 成功；实机已完成
两条真实 STOP、Free/Off/Ready与新实例接任，却在正确的 UnknownObject 上失败。
该原失败输出、捕获和哈希保留，没有倒填 PASS。源码核对 Ready fast-path 后，
工具改为要求实际凭据拒绝和零接任命令；全新VM73再完成整轮。另一次最初
unit fixture按未减2000ns的时间寻找合成 OUT 而失败，保留日志后纠正 fixture；
没有放宽 OUT/Complete 或 radio/management 验证。

[公开原字节/协议/身份/RF证据](evidence/ws73-daemon-sigkill-successor-real-20261012.json)
SHA256 `f17e4c4a1eb63b65b6b2a821bed771ddb2db3403238d5ae5ccae8a534feb4747`。父端与guest序列化proof均在生产者退出后独立
重算一致，准备输入再次核对；365项工具测试通过。两个工具提交CI均9/9。

## 复现与剩余主功能

先以当前 committed 工具创建新的、限定 Native kernel/module/service bundle
prepare，再以新的证据目录运行：

```sh
python3 tools/ws73_target.py run --prepared <fresh-native-prepared> \
  --output <new-evidence-directory> --ports 1-2.1.1 1-2.1.4 \
  --qmp-hotplug --daemon-crash --timeout 450
```

混入 observer、initializer lifecycle、其他 fault/held/parallel、custom policy或
非 Native 环境均拒绝。监督器只允许显式私有VM boot mode；不在主机强杀
daemon。只有整轮生产者结束、捕获停止、父/guest独立核验后才认定限定通过。

下一主功能推进真实 WS73连接/SSAP，而非继续用发现门禁代替S4功能。
充分对照本地 libws73-usb 与 communication_nearlink_service 的实际协议边界：
CreateConnection需核对WS73的27字节方言与异步连接 outcome，不能沿用旧
只发送6字节地址的实现或把命令接受当连接成功。Native typed admission、
per-controller状态、超时/取消/迟到事件与Managed撤销一起接通，再做双设备
连接/断开与SSAP数据互通。事件/result并发、在途SIGKILL和权限补全并行推进；
四设备/111固件根因及有限非人工恢复继续开放。完整原issues不因本成果关闭。
