# Native diagnostic result ownership（部分迁移）

2026-10-11。遵循 ADR 0001 的结果只交付原请求者、观察与管理分离要求。
Linux `5c87f9075d37`；用户态同步修改，未发布 UAPI 无兼容期限。

调用审计发现 `slkconfig query` 仍先清空共享 DLI 事件、再按 opcode 找回复。
诊断租约只能限制提交者，不能为共享出队增加可靠关联或保证 copyout 失败后重试。
现在通过 `SL_IOCTL_DIAGNOSTIC_RESULT` 查询 admitted local sequence 的快照。
sequence 由 Host 已捕获的在途 wire slot 完成；不假定 WS73 回传本地事务号。

## 契约与实现

- 必须显式选择 controller；generation 必须精确匹配，查询 fd 是原提交者。
- 每次 syscall 仍需 CAP_NET_ADMIN 和该 fd 的 Diagnostic 所有权。
  不同步电源，不申请或扩展管理权限，不能绕过 Managed/Diagnostic 互斥。
- 固定 104 字节、8 字节对齐；version=1、flags=0、非零 generation/seq，
  padding/reserved 为零。state=1 Pending、2 Complete、3 Failed；errno 与
  controller status 分开。成功 Status 不作为最终 Complete。
- 精确保存最多 64 字节；超长响应返回失败 EMSGSIZE，禁止截断后成功。
  本地 pending 到期为 ETIMEDOUT；控制器失败保留非零 status。
- 查询不确认、不出队、不推进订阅 cursor；复制失败可重新查询。
  32 个槽有界，已完成记录保留至后续提交复用槽；不存在/已替换为 ENOENT。
  sequence 用尽拒绝 EOVERFLOW，不循环复用旧身份。
- 目前只支持 Native WS73 profile 1 原有只读 metadata 白名单。
  其他 profile 不通过旧事件读取 fallback 模拟支持。
- `slkconfig query` 已迁移，删除 stale drain、opcode-only legacy poll。
  Rust/C/Python 结果查询同步接通；C 的失败/缺失保持调用者输出不变。

## 开发门禁与未决条件

专用 selftest 编译完整 `sle_mgmt.rs`、原 result handler 和原结构声明；10 项
测试覆盖 pending/final、重复查询、copy fault 重试、失败/超长、作者与租约分别
校验、generation/version/profile/显式选择/缺失、32槽替换、重复回复、到期、
rollback 和 sequence 用尽。锁、时钟、租约、分配和 usercopy 依赖为 fixture，
不是实际 VFS/CAP/并发/退役证明；模拟只在 selftests，生产无成功注入。

实际 Rust 回归 169 项、严格 all-targets/all-features clippy 通过；Python 的
canonical C/public C/Rust/ctypes layout 与 i386 C 对齐门禁包含新结构。
共享库 `/dev/null` 负向测试覆盖 errno、零身份、空指针和输出保持。
固定新内核提交的远端 CI 及新 VM 实机回归应独立记录，不能引用旧镜像证明新接口。

尚未完成：新 ioctl 的 VM 实际 owner/CAP/坏地址/断链/退役验收；提交 ioctl
自身 copyout 失败的幂等/可找回 admission、完整 cancel/deadline 契约；旧
DLI_POLL_EVENT 和 EventReceiver、legacy C/Python、slkd profile 0、监视工具
`--legacy`、旧 scan/selftests 的调用者迁移。只迁移一个生产调用者不能删除
所有旧事件路径或关闭 R12/K3/U2。保留有价值的历史失败和回归测试。

WS73 真实双设备闭环必须用当前镜像持续回归；自然启动/重枚举/消失根因、
无人工拔插恢复、物理 xHCI warning、四设备两组并行及 native-host 对照仍开放。
仅使用 VM；该接口不改变 S0–S6、SSAP 用户态归属或最终 socket 数据面方向。

## 当前镜像回归与复核证据

[CI 38086204506](https://github.com/OpenSparklink/sparklink/actions/runs/38086204506)
固定 Linux `5c87f9075d37` / 编译用户态 `f2aea829dab3`，9作业终态成功，实际日志
核对169 Rust、33 Python、146工具及新增10项内核结果测试；既有security7、
backend2、TX11、SSAP9、event9、历史PHY3/拒绝arm1与sanitizers仍通过。

[新镜像VM证据](evidence/ws73-vm-diagnostic-result-20261011.json)：7类实际read
门禁及真实20＋2轮通过，最长469ms；独立22份RX/1247 USB零drop，普通UID1000/
caps0，同slkd PID521/start331及bus owner，幸存generation2保持、目标1→3。
两只最终STOP_CONFIRMED，VM warning0/taint0/trace overrun0，host4只释放后仍在。
单对象人工IN81错误至新Ready约10328.452ms，发现计时
仍从成功scan Complete起算；RX USB/HCC/DLI佐证不等于PHY嗅探。

这轮VM运行验证当前生产路径保持，不执行新diagnostic ioctl的权限/copy/退役
验收，不代表原生宿主对照、物理拔插、自然恢复或全事件验收。完整issue保持OPEN。

## 后续实际诊断门禁（实施中）

Linux `7cc1175f28f4` 在 lease 检查前拒绝已关闭 admission 的 Runtime，退役 fd
返回 ENODEV，避免被已撤销租约的 EPERM 掩盖。原 handler fixture 增至11项。
新增专用 `sparklink_diagnostic_result_test.c`，仅在 root、scratch-root VM 和
`ws73.diagnostic=1` 同时满足时运行；没有生产测试 hook。

VM runner 的 `--diagnostic-verify` 必须同时使用 `--fault-recovery`，先在 slkd
启动前测试四种实际只读 metadata、原 fd 子进程 UID1000/实测零有效及许可能力、
Diagnostic 持有者与结果作者分别校验、零/错误 generation、version/flags/reserved、
缺失 sequence；对只读输出页/跨页输出复制失败逐字节核对原结果重试。C 记录完成后
释放租约，实际 slkconfig 再执行四种 query，才允许 slkd Managed 启动。
旧 fd 无租约地保留至单设备人工恢复后，检查 ENODEV；不重启 daemon。

新增6项证据 verifier 开发用例，拒绝缺失/错误 errno、copy 重试数据、身份、时钟、
能力或退役步骤及错误测试模式。合成 verifier 输入不是真实 syscall 证据。
冻结 C/工具/CLI 并用新镜像执行后另记结果；开发门禁不提前宣称实际验收通过。
完整旧 DLI 调用者迁移、共享队列删除、提交 copyout 幂等/cancel 与自然恢复仍OPEN。
