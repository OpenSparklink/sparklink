# Native diagnostic result ownership（部分迁移）

2026-10-11。遵循 ADR 0001 的结果只交付原请求者、观察与管理分离要求。
最新限定实测 Linux `78e729c06a5e` / 编译用户态 `2dfd6bd09e7b`；
下文保留各历史批次基线，未发布 UAPI 无兼容期限。

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

专用 selftest 编译完整 `sle_mgmt.rs`、原 result handler 和原结构声明；当前11项
测试覆盖 pending/final、重复查询、copy fault 重试、失败/超长、作者与租约分别
校验、generation/version/profile/显式选择/缺失、32槽替换、重复回复、到期、
rollback 和 sequence 用尽。锁、时钟、租约、分配和 usercopy 依赖为 fixture，
不是实际 VFS/CAP/并发/退役证明；模拟只在 selftests，生产无成功注入。

实际 Rust 回归 169 项、严格 all-targets/all-features clippy 通过；Python 的
canonical C/public C/Rust/ctypes layout 与 i386 C 对齐门禁包含新结构。
共享库 `/dev/null` 负向测试覆盖 errno、零身份、空指针和输出保持。
固定新内核提交的远端 CI 及新 VM 实机回归应独立记录，不能引用旧镜像证明新接口。

新 ioctl 限定的 VM owner/CAP/坏地址/旧 generation 退役门禁已通过，见文末；
完整并发、断链/移除、Pending/控制器失败/超长/槽替换的实际 syscall 验收仍缺。
尚未完成提交 ioctl 自身 copyout 失败的幂等/可找回 admission、完整 cancel/deadline 契约；旧
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

## 实际诊断门禁实施与保留失败

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

首轮新门禁VM因测试启动顺序失败：probe在capture-ready标记之前等待USB，
runner等该标记才QMP接入，形成等待环。原私有失败目录
`.dev/diagnostic-live-real-recovery`保留；QMP只有握手、无device_add，
不能把这个环境错误称为WS73启动/自然恢复失败或将其计作通过。
修正诊断模式capture-ready标记顺序；测试metadata可用时允许Setup，
不改变生产Ready定义，snapshot重试清零输出flags，transport-open只对
EAGAIN/零lease有界6秒重试，不重置或跟随新注册。新镜像重新执行后再记录结果。

第二轮新门禁中diagnostic/run.json为DIAGNOSTIC_RESULT_LIVE_PASS，
C19条记录（16个case、子进程身份、2个phase）及4次实际CLI查询完成，
真实20+2也完成，但整轮仍为FAIL：旧注册metadata证明窗口从0到Ready，
包含新增C/CLI同opcode查询，严格唯一性校验拒绝。失败目录
`.dev/diagnostic-live-v2-real-recovery`保留，不回写成功。
现以首个诊断提交的实测开始时间界定初始化metadata上界，并逐一验证
4次C与4次CLI的明确时间窗、参数、完成OUT和成功reply/data；仍拒绝窗口内
重复命令/回复，不按同opcode任意挑选。旧无诊断模式门禁不变。新增3项
捕获verifier用例，总工具门禁155项通过；修改后的工具须重新冻结/执行VM。

## 当前限定实机门禁通过（完整 issue 仍 OPEN）

[第三轮新冻结镜像证据](evidence/ws73-vm-diagnostic-live-20261011.json)基于
Linux `49cabad043f6` / 编译用户态 `d8c091a4b243`。整轮 runner 退出0，
状态 FAULT_RECOVERY_SUPPORT_PASS；前两轮原 FAIL 不改写，原因与 manifest
hash 同时保留。修正测试启动顺序和 metadata 证明窗口没有放宽唯一回复校验。

16个实际 syscall case 通过：四种 profile1 metadata；继承原 fd 的子进程
单独实测 UID/eUID1000、有效及许可能力均0，被拒 EPERM；另一个 root fd 即使
持有自己的 Diagnostic 租约仍不能读取原作者结果；只读输出页与跨页复制
确实返回 EFAULT，后者已写56字节，完整104字节重试保持；非法版本/flags/
reserved/零身份、错误 generation、缺失 sequence 与退役旧 fd 均拒绝。
租约在 slkd 启动前释放，旧 fd 不持租约地保留到人工恢复后返回 ENODEV。
随后实际 slkconfig 四次 query 均通过。独立核对8组 C/CLI USB命令、成功
Complete 和 metadata 数据；每个明确窗口严格要求唯一完成命令/回复。

普通用户的7类 legacy read 与真实双设备20＋2轮继续通过，最长606ms，22份
RX / 1279 USB包零drop；同 slkd PID646/start1521 与 bus owner、幸存g2不变，
目标g1→g3，两只最终STOP_CONFIRMED。VM warning0/taint0/trace overrun0，
退出后host4只仍在且释放。人工IN81错误至新Ready约10412.540ms；发现10秒
从成功 scan Complete计时，RX USB/HCC/DLI佐证不等于PHY嗅探。

[CI38088063720](https://github.com/OpenSparklink/sparklink/actions/runs/38088063720)
三个内核checkout固定当前K49，9作业成功，实际日志核对169 Rust、33 Python、
155工具、11项诊断原handler fixture及既有security7/backend2/TX11/SSAP9/
event9、C sanitizers、历史PHY3/拒绝arm1。CI只编译live C probe，不执行硬件用例。

这补齐16个限定syscall case与一个生产CLI调用者的真实证明，不代表完整
Diagnostic/API/事件验收。旧DLI消费者与共享队列迁移/删除、admission copyout
找回及幂等、cancel/deadline、并发/完整移除仍待实现与实际回归；自然启动/
重枚举/消失根因和无人工拔插完整恢复继续OPEN，VM-only和完整S0–S6不变。

### Native diagnostic admission 身份与取消（开发门禁，实机待复核）

[新提交契约](DIAGNOSTIC_ADMISSION.md)用调用者预先持有的request ID找回copyout
失败后的admission；保留重试不重发/不续期，淘汰旧ID拒绝ESTALE。取消排队命令
保持FIFO，在途取消保留真实Host回复槽，超时/取消/Host错误保留本地errno。
Native旧输出seq-only提交入口不支持，C/Rust/Python、CLI和专用probe同步迁移。
开发测试通过不引用K49/Ud8旧镜像证明新语义；完整实际取消/迟到回复及剩余DLI
迁移继续OPEN，当前真实路径须用新镜像独立回归。自然恢复根因和完整S0–S6不缩减。

[当前新入口回归](DIAGNOSTIC_ADMISSION.md#当前新镜像路径回归限定通过)已用Kc89/
编译Udf9新冻结镜像复核metadata8、结果syscall16、read7和真实20+2，最长620ms，
同daemon/幸存g2保持；固定源码9作业CI通过。新提交copyout幂等、实际取消/
迟到回复尚未验收，不能把已有结果copyout门禁当作提交门禁。迁移及完整issue
继续OPEN，自然恢复根因与S0–S6范围不变。原失败构建/环境记录保留。


## 最新限定提交故障验收与 BlueZ 分析复核（2026-10-11）

再次收到的BlueZ分析与已采用文本SHA256相同，ADR 0001和最终每通道socket、
用户态SSAP/服务/Profile、安全机制/策略边界保持；未发布UAPI可同步替换，
不保留永久双实现。基线更新为Linux `372d3cbcd557` / 编译用户态 `ee2793301e9a`。
[限定提交故障证据](evidence/ws73-vm-diagnostic-copyout-20261011.json)证明只读/
部分输出EFAULT后同ID取回原seq、三次重复完整返回，提交/完成各一次；完整
窗口实际USB只有一个OUT/成功Complete。结果16/CLI4/wire8/read7和真实20+2
保持，同slkd/幸存g2不变，最长620ms、1279 USB零drop；9作业CI成功（170
Rust/34 Python/159工具）。生产Kc89/Udf9未变，本批仅selftest/验证与证据。

实际淘汰旧ID、取消/迟到回复/期限/并发及剩余legacy DLI迁移仍待接通和回归，
随后删除共享结果/事件和重复UAPI。自然启动/重枚举/消失根因、无人工自主恢复
及历史xHCI警告继续OPEN；VM-only和北极星7/8不变。按严重程度继续拒绝未支持
安全/服务能力，生命周期与旧代码清理并行；socket/用户态SSAP/每连接安全/
Bond/Profile/四设备/其他Native/Proxy及全S0–S6保留全部原验收。


## 当前调用审计及删除依赖（K78/U2df）

| 调用者/路径 | 当前事实 | 替代与删除门禁 |
|---|---|---|
| slkconfig Native query、NativeAdapter Rust/C/Python | 已用caller ID提交与作者私有结果，正常、输出故障、顺序槽淘汰有实机证据 | 继续补实际取消/迟到/期限和完整权限/生命周期；不能用它替代事件订阅 |
| libsparklink EventReceiver、Adapter.poll_event/旧next_event | 仍调用DLI_POLL_EVENT，共享破坏性消费；50ms fallback。旧receiver转移fd所有权不等于独立订阅 | profile0接入统一Runtime及完整订阅后迁移；保留cancel/drop/actor回归，再删除旧receiver与poll/helper |
| slkd profile0 EventTask、legacy C slk_poll_event/Python Adapter.poll_event | 委托旧receiver/poll；Native EventTask使用独立ControllerEventReceiver，不能误改真实WS73路径 | 先接通所有事件类型/权限/退役，再同步删旧FFI/header/ctypes/daemon调用。未发布UAPI不留兼容期限 |
| slkmon/slkdump --legacy | 明确只准profile0；默认Native snoop独立，不能当作已迁移所有legacy调用者 | 在通用独立capture接通profile0、保留hex/filter/文件/退出回归后删--legacy |
| Adapter.dli_send_cmd、runtime/daemon_management/sparklink_test.c旧raw命令测试 | Native旧提交已EOPNOTSUPP；profile0路径仍存在，不应继续用于新Native测试 | 按诊断白名单或Typed Managed归属迁移；旧假完成/错误wire正向测试重写为拒绝或专用backend后删旧入口 |
| 核心DLI_POLL_EVENT、共享dli_ring与controller.poll_event fallback | 仍先pop后copy；fallback也先消费。新作者私有结果不自动修复这个旧入口 | 剩余调用者接通独立订阅后删ring/fallback/UAPI；过渡期间复制失败不能消耗，需单独整改/实际故障回归，整项R12仍OPEN |

[当前限定槽淘汰证据](evidence/ws73-vm-diagnostic-eviction-20261011.json)与
[提交契约](DIAGNOSTIC_ADMISSION.md)只补齐
作者私有诊断的顺序保留/拒绝。共享POLL入口仍有copy前消费，不能把read7或新
result16/eviction验证当作该路径已修复。生命周期/自然根因并行，迁移后删除
重复实现，完整R12/K3/U2及S0–S6保持OPEN。
