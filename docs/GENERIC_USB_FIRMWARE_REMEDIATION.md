# 通用 USB 固件路径整改

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
