# 通用 USB 固件路径整改

<!-- documentation-scope: 20261014 -->
> **阅读范围：历史审计／验收资料。** 通用 USB 固件路径和复制/边界整改。
> [主题归纳与去向](project/uppercase-document-guide.md)；[推荐入口](CURRENT_CAPABILITIES.md)。
> 原文中的源码、失败、PASS 与命令仅适用于其记录版本；当前资格以 [CURRENT_CAPABILITIES](CURRENT_CAPABILITIES.md) 为准。

这是旧 `net/sparklink/sle_usb*` 后端的确定性错误校验整改，不是 Native WS73
固件方言资格，也不是自然启动超时、重枚举或设备消失根因的结论。
Native WS73 的启动、HCC/BSLE 和固件仍由 `drivers/sparklink/ws73` 拥有。
完整分层和迁移顺序保持 [架构决策](BLUEZ_RECONCILIATION_20261011.md) 与
[S0–S6 方案](IMPLEMENTATION_PLAN.md)；未发布 UAPI 在调用者迁移后直接删除。

## 调用链与修复

`probe_usb_device → prepare_usb_controller → load_usb_firmware →
sle_usb_dev_download_fw` 是实际生产调用链。此前 C 下载器在 bulk OUT 返回
0 后直接推进 offset，没有校验实际长度；FW_DOWNLOAD_DONE 的回复也没有
调用现有 CommandComplete 校验。实际源码依赖 fixture 已重现短写、空回复、
错误 opcode、非零 status 被记作成功。Rust probe 又吞掉所有固件加载错误，
并在上传前读取身份，成功上传后没有重新 bootstrap。

当前实现：

- C 入口限制固件到 4 MiB，与已有 Rust 限额一致；只允许 chunk=0 自动选择，
  明确大小限制在 16 位长度内；非法值在分配和传输前拒绝。
- 每个 chunk 必须完整发送，短写返回 EIO；错误不推进下一片，不发送 DONE，
  不打印成功。传输 errno 保留。
- 同步回复复制前检查 actual length；DONE 必须是完整、正确长度、对应 opcode
  且 status=0 的 CommandComplete，错误返回 EPROTO 或 EREMOTEIO。
- Rust 下载层只接受返回值 0；负 errno 原样返回，异常正数返回 EIO。
- probe 只有 ENOENT 允许使用已成功 bootstrap 的现有固件；其他请求或下载错误
  必须终止。成功上传后重新 Reset/version/MAC，再读取身份。
- 无法读取身份、零或全 ff 地址均拒绝发布；register/bootstrap 的异常正返回也
  拒绝。失败保留 quiesce → USB unregister/join → detach 顺序，不计入成功设备。

## 测试和证据边界

内核 selftest `run_usb_firmware.py` 提取实际 C 下载器、同步命令、回复校验器
以及实际 Rust loader、prepare、probe 函数体；C static 仅提升链接可见性。
USB、分配、固件请求和 registry 是专用依赖 fixture，未复制下载或 probe 逻辑。

69 个 C 案例以 ASan/UBSan/LSan 覆盖 payload/offset、短写、完整及错误回复、
传输 errno、逐处分配失败、输入和尺寸边界；12 个严格 Rust 测试覆盖文件错误、
FFI 错误、重新查询、真实身份、无失败发布和清理顺序。Fixture 不发送 USB，
不加载宿主模块，不把模拟成功编入生产驱动。

本地 sandbox 的 ptrace 导致第一次 LSan 运行失败，保留失败日志；随后在普通
用户、纯 CPU/内存进程中运行全部 sanitizer 成功，没有关闭泄漏检测。
CI 固定检查相应内核提交并运行此门禁。

通用固件 START 的确认语义、异步 URB 与同步查询所有权、真正对应硬件和方言、
总线迁入 drivers、其他 backend 的互通仍开放。必须独立实机验收，不能借用
WS73 固定 1.10.111 combined 的验证。WS73 双设备回归只证明这批旧路径改动
保留已验证的 Native discovery；不会证明上述通用方言可用。

自动恢复、自然故障根因、部分初始化/在途 fd-close cleanup、四设备两组、连接
socket、用户态 SSAP、安全/Agent/Bond/Profile、Proxy/PM/sandbox/发布仍按原 issue
开放。保留历史失败和物理 xHCI warning，不据单批测试关闭完整事项。

首次完整内核编译发现当前 Rust prelude 未导出 EPROTO，实际源码 fixture 的依赖
定义未揭示这个集成错误。[失败记录](evidence/generic-firmware-kernel-build-failed-20261011.json)
保留；修正为 canonical kernel bindings 后必须重新编译和 VM 验证，旧 image
不能记为本提交通过。

## 下一批调用关系清理

| 类别 | 代码及调用者 | 处理与门禁 |
|---|---|---|
| 立即删除 | C `sle_usb_dev_register` 由实际 Rust probe 调用；descriptor 失败分支以 “test mode” 回退硬编码端点、大小和 interval | 返回真实 descriptor 错误；在分配/发布前拒绝，实际 register 依赖 fixture 验证错误和清理，再做新镜像 WS73 回归 |
| 移入测试／已隔离 | 本批 USB、固件请求、分配、registry 注入 | 仅 selftests dependency fixture；生产不得链接模拟返回成功 |
| 等待替代 | 有实际 probe 消费者的 loader、旧 USB backend、route/parser、global fallback 和 shared event ring | 先接通 drivers-owned backend／独立消费者和真实 Runtime 生命周期，再迁调用者和有价值测试，删除重复逻辑及未发布旧 UAPI |

实际 register 只分配 event/data contexts，未提交 URB；probe 的同步 bootstrap／
上传／再查询在 `sle_switch_controller_usb` 调用 `controller.open()` 之前。
不能仅凭 register 分配 URB 宣称 bootstrap 已有并发收包竞态。启动后、重启和
PM 的 IN 所有权仍需另外核对。下一批清理不能扩展本批证据范围。

## 本批新镜像限定回归通过

K`7f2ba1f81ce0`／编译U`ae542f568e03`修复实际C短写/最终ACK校验及Rust
loader/probe错误传播，只有ENOENT允许使用已bootstrap固件；上传后重新查询，
禁止发布旧身份或失败设备。[调用链、三类清单和限制](GENERIC_USB_FIRMWARE_REMEDIATION.md)
明确Native WS73 driver未改、专用fixture不等于通用固件真实方言资格。
69个ASan/UBSan/LSan C案例、12个严格Rust实际函数测试通过；首次缺少EPROTO
完整编译[失败记录](evidence/generic-firmware-kernel-build-failed-20261011.json)保留，
修正canonical binding后全内核/private modules/签名smoke通过。编译器warning0，
GNU make一次jobserver警告；一次过早smoke在缺少私有module时退出、未创建VM，
原日志保留，实际stage终结后才运行通过。

[新镜像两个独立VM证据](evidence/ws73-vm-generic-firmware-boundaries-20261011.json)
保留各6 Setup release/last-file/dup门禁和整个窗口零DLI，实际在途500ms超时/
Runtime退役/稳定预算归零，以及另一VM原诊断63记录/50proof/46wire、read7/
result16/copyout2/poll3/淘汰33/CLI4/旧注册27拒绝及queued原期限。每VM
UID1000/caps0真实20+2，最长773/622ms，各自同RF slkd及peer不变，USB1345/
1431、各22RX/零drop，guest warning0/taint0/traceoverrun0，结束四只释放在位。
[精确源码CI38109661941](https://github.com/OpenSparklink/sparklink/actions/runs/38109661941)
九作业终结成功，实际170 Rust/34 Python/228工具/32期限/10管理及新增69 C/
12 Rust固件源码门禁。USB/HCC/DLI不等于独立PHY嗅探；hold期间同daemon未资格。
