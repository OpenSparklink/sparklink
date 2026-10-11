# Native连接生产接入与未完成验收

2026-10-12，Linux `82318ed9fe3f0c733d887e76a3f32fe319606a2a`。
codec、operation storage和Host调用者已接入生产源码，重复staging Session/
codec/header已删除。完整bzImage/modules构建通过，源码和配置稳定、无编译
警告。库/Rust/C/Python可提交与查询；slkd/D-Bus/slctl连接消费者尚待接入。
没有新VM引导、连接空口或SSAP验收。已有实机资格仍为原Linux d227/实际
编译服务195的VM74无连接RF20+2，不扩大到本版本。

## 已接通调用关系

typed submit → per-file affinity/generation/profile及CAP_NET_ADMIN/Managed
lease → 单调request watermark → WS73 driver prepare/validate完整plan →
Runtime Host → 共用credit queue内部connection tag → retained TX再次driver
validate → 真实OUT。仅该typed请求的匹配CommandStatus释放wire slot；查询
和广播扫描成功Status仍等Complete，raw DLI仍只允许原metadata查询。

真实WS73事件 → driver-normalized link evidence → 同一Runtime Host内物理
LinkObservation和operation → 原始完整event log。OUT、Status接受和匹配
peer type/address或disconnect handle的异步outcome缺一不会成功。作者取消
保留Cancelled/-ECANCELED，迟到真实handle仍保留物理义务。传输/期限不确定
保留首fault并禁止复用，结果淘汰或日志loss不能清除物理义务。未知/不匹配
事件不完成作者请求，仍保留独立物理观察与原始诊断。

每Runtime串行一个procedure是Host admission policy，不是固件连接数量。
同一open file可查询当前operation及32项有界历史，dup共享作者和watermark；
淘汰返回无记录，单调ID防止旧请求重新排队。Create必须Host已初始化，
Disconnect必须匹配独立观察的现有handle。

## 方言、ABI及真实源码测试

参考本地libws73-usb、communication_nearlink_service及T/XS10003-2025
8.4.1/8.4.2/8.4.3/9.1.14，独立实现协议事实，未复制LGPL代码。WS73 111
Create为27字节（peer、GT/frame1、scan/connection interval、latency、
supervision与event length）；Disconnect为LE handle两字节+reason一字节。
每个参数显式提供，不套用旧6字节helper或标准V2额外PHY/frame quartet。
codec拒绝错误及跨操作多余字段，失败保持output。

0x1402标准取消存在，但111固件实际支持未证明，driver不宣布支持。
operation3只取消作者，不发送伪造物理取消或成功Complete。

UAPI未发布：submit112字节 `_IOW(0x9c)`，result64字节 `_IOWR(0x9d)`；
Rust/C/Python按字段、大小、8字节对齐及i386 C编译核对。state为Queued1/
OnWire2/AwaitingOutcome3/Succeeded4/Failed5/Cancelled6/Faulted7；flags1/2/4
表示command status/outcome status/handle存在，handle0有效。whole-operation
budget由调用者给出1..10000ms，不在OUT/Status后延长。submit成功仅admission；
同ID重试被拒绝，须在同fd查询。

10项生产operation/history测试；实际完整Host方法与queue/storage/link依赖
共23项（8项直接Host、10项operation、5项physical observation），覆盖三证据
顺序、Setup/tag拒绝、未选中撤销、在途取消/迟到handle、期限/首fault/peer
隔离、错误opcode/peer/reply class和原查询/广播扫描完成规则。实际driver
codec/prepare/validate完整ASan/UBSan/Leak通过。另有management源码45项、
diagnostic源码42项、atomic ingress10项支持门禁；包含依赖fixture，不证明
VFS、运行内核或RF。

首次构建的u16 helper与kernel typedef冲突及14项Rust pub警告已在签名小
修正中解决，原失败/源码配置记录保留。sandbox ptrace阻止LeakSanitizer的
原失败保留，同一测试在沙箱外通过；fixture常量提取、错误共享库路径、host
ccache/dbus依赖问题也保留，未跳过测试或放宽检查。

```sh
python3 tools/testing/selftests/sparklink/run_native_connection_contract.py \
  --output /absolute/path/new-connection-source-receipt.json
python3 tools/testing/selftests/sparklink/run_native_connection_host.py \
  --output /absolute/path/new-host-source-receipt.json
```

## 下一步必须完成

1. release/最后fd/daemon的真实连接清理。当前queued可本地撤销；on-wire、
   accepted或已建立link不能仅凭作者Cancelled/radio Off成为Free，明确
   EOPNOTSUPP/Faulted。需要真实Disconnect/outcome屏障、迟到建立清理与
   有限timeout；当前守卫不算完整Managed teardown。
2. slkd/库/slctl的连接消费者和动态Connected状态，替换旧连接投影，迁移后
   删除重复旧逻辑；SSAP/security/Profile未接通仍返回不支持，不制造成功。
3. 新签名镜像VM空USB及真实双设备：先保留默认RF20/角色交换/拔插，再真实
   连接/断开和release/last-fd/dup/迟到回复/peer隔离。实验kernel/daemon/
   device I/O VM-only，源码门禁不顶替空口证据。
4. 完整原S0–S6/28项：SSAP、安全/Bond、PHY/PM/Proxy等继续推进。默认四设备
   资格仍0，自然RCA及不依赖人工拔插的自动恢复未通过，issues保持开放。

历史staging证据在Linux c8及用户态d0提交保留；当前只有已迁入的实现。
