# Native diagnostic 取消、迟到回复与期限门禁

日期：2026-10-11。整项 K2/K3/K19、U1/U2/U8/U10 保持 OPEN。
本工作落实 ADR0001 的事务关联要求；WS73 discovery、S0–S6 与 VM-only 保持。
用户再次提供的 BlueZ 分析 SHA256 为
`f8de2edb3e4c6a2cca1442ce06ba59c03407469b7f8631539e974743c993853a`，
与已采用分析相同，不新增重复架构或 issues。

## 实现和调用关系

生产内核仍为 `54621800ee4c` 的路径，用户态生产 crates/data 仍为
`df9cff7d750d`；本次 Linux `091a57bb52f4` 只修改专用 QEMU selftests 工具。
旧诊断/共享事件的最终删除仍依赖调用者迁移及回归，未发布 UAPI 无兼容期。

`ioctl_diagnostic_submit` 校验作者、generation、request id、opcode 和原 timeout；
保留的同一 admission 不重发、不续期。`CmdPendingQueue::cancel_seq` 为作者保留
ECANCELED 最终结果，不能由之后的成功回复改写。`CommandHost::cancel_diagnostic`
移除排队命令，但在途命令保留真实 wire 回复槽；只有实际匹配回复被消费或
真实超时引发故障退役，才释放这个槽。没有线上事务号，不能把本地 id 当作
固件回传 id，也不能提前发送同 opcode 并把旧回复完成给新作者。

实际成功回复经 Host transport 完成关联和原 sequence 返回；已取消/超时的
本地结果不能复活。这里是源码审计和已有开发测试结论，仍需以下实机门禁。

## 已完成的专用测试基础

新 QEMU patch 暂留一次实际成功、非空的 bulk IN81，不修改 transfer 的数据、
长度或成功状态，不构造 Complete。只允许实际 attached 的 ffff:3733 WS73，
全部 host/guest reset 和 kernel detach 关闭；默认不开启，与人工 IN81 error 互斥。

暂留保留原 request/transfer/buffer，日志记录字节数及实际 SHA256。显式 release
通过原 callback 交付；REALTIME timer 截止为两秒，由事件循环执行，不是硬实时
保证。取消/abort 先清理 timer 和暂留身份，再释放已完成 transfer 一次，不再
调用 libusb cancel。close 清除未消费脉冲，并通过原 abort/drain 路径清理对象。
disarm 不丢弃已暂留的数据；无实际暂留的 release 和对其他对象的 release 拒绝。

[开发证据](evidence/qemu-runtime-hold-development-20261011.json)记录：

- 完整 QEMU 9.2.0 编译及冻结 binary/object/source/configuration。
- 固定上游归档重建实际源码，与完整构建的 host 源码 SHA256 一致。
- 实际 hold/callback/abort/cancel/getter/setter 的计数依赖 fixture 和 ASan/UBSan。
- 原 runtime-error callback/setter 回归，hold 依赖在该 fixture 中必须不被调用。
- 七个完整补丁前缀升级/幂等、八类上下文漂移拒绝，失败不修改输入。
- 暂停、未 attached 的 TCG/QMP 默认、只读、拒绝 arm/release 检查，无真实 USB 匹配。

timer、transport、digest、USB combining 是依赖替身。上述结果不证明实际 QEMU
调度、完整 close drain、多设备并发、真实取消/迟到/期限或自然故障恢复。
[固定源码CI38095468362](https://github.com/OpenSparklink/sparklink/actions/runs/38095468362)
九作业全部成功；已读取终结日志确认新增QEMU门禁和170 Rust/34 Python/170工具
实际执行。CI运行固定归档依赖门禁，不编译完整QEMU、不执行USB或guest。
构建/fixture 的失败尝试保留，修正后重测；不能将它们抹成首次全部通过。

## 实际 VM 门禁（部分限定通过，完整门禁仍 OPEN）

| 门禁 | 需要的实际证据 | 失败处理 |
|---|---|---|
| 在途取消 | arm 后真实 MAC OUT，QEMU 暂留的真实成功 IN；作者结果变 ECANCELED，重复查询字节/计数不变 | 记录原始 errno、完整结构及日志，不生成测试成功 |
| 排队取消 | 旧 wire 槽被暂留时排入新查询再取消；队列中移除，无该查询实际 OUT | 全窗口 USB 捕获，不仅检查局部样本 |
| 迟到隔离 | 同 opcode 新查询仍 Pending，无提前 OUT；显式释放旧回复后旧结果不复活，新查询仅由自己的 OUT/回复完成 | 对照 QMP 时间、暂留 SHA256、USB/HCC/DLI 与结果 sequence |
| 原截止时间 | 相同 id 重试不续期；排队过期不发包；在途过期走原有受控退役和有限恢复 | 记录实际截止/状态/计数；不使用人工拔插恢复 |
| 清理隔离 | 有实际暂留时关闭/取消/退役；旧 timer 不重放、另一设备不受影响 | 单/多设备分别记录，适用时运行内存/锁检查 |
| 路径回归 | 当前镜像普通 UID/caps0 WS73 20+2、随机数据/地址/RSSI、同 daemon、read 与 diagnostic 原门禁 | 新失败不得引用旧版本通过替代 |

测试协调只存在专用 guest/host 工具，不加入生产内核 hook。客体在 daemon 前
执行受控 root Diagnostic；应用 RF 回归仍由普通用户执行。显式 release 应在
timer 到期前完成且 bounded-release 计数为零；自动到期不能冒充显式释放验收。
实际 timer/close 行为另行验收。故障恢复后无需重启 slkd，幸存者 generation 保持。

最新真实基线仍是 K`9b16e634bfd3`/编译 U`1d3a17b688ee` 的
[20+2/read/结果/copyout/淘汰/legacy poll 证据](evidence/ws73-vm-legacy-poll-live-20261011.json)。
该镜像未使用本次新 QEMU binary；本次没有新增 RF 或取消实机验收声明。
自然启动/重枚举/消失根因、自主恢复、历史物理 xHCI warning、四设备两组、
socket/用户态 SSAP/每连接安全/Bond/Profile/Proxy/完整 sandbox 与发布仍 OPEN。

## 实际门禁工具接通（实机执行待完成）

Linux `cc4018c4e3a6`只新增专用C探针，生产路径不改。新显式模式先完成原
metadata/copyout/legacy poll门禁，再通过三阶段host QMP握手测试在途MAC取消、
排队Features取消、同opcode MAC等待旧槽，以及50ms重复ID/重复取消观察。
释放原回复后，两个ECANCELED结果必须逐字节保持，新MAC仅由自己的回复完成；
100ms观察后再执行原33次淘汰、CLI、作者/CAP和退役门禁。

`--diagnostic-cancel-verify`必须同时指定`--diagnostic-verify --fault-recovery`；
禁止support或单独启用。证据format5同时要求旧全部门禁和新取消记录，历史
format1–4仍按原范围验证。guest/host JSON marker在写完后rename发布，拒绝重复。
C stdin握手有超时，显式释放必须保持bounded-release/drop为零。抓包验证完整
阶段恰有两个MAC OUT/回复，旧回复先于新OUT，Features无OUT；host成功IN的
SHA256和长度必须与实际USB交付一致。QMP、syscall结构、计数及抓包分别核对。

严格C编译和新增记录/抓包/QMP拒绝fixture通过，完整工具回归在原170项上增加
这些开发门禁。fixture不能证明实际成功；正在构建冻结新VM，实机结果单独记录。
当前只是取消/迟到回复门禁；完整原deadline、在途超时恢复、held状态close/drain、
其他作者/CAP取消/多设备并发仍需独立验收。自然根因、北极星最后一项及S0–S6
保持OPEN，不用新测试框架存在替代功能完成。

## 新镜像实际限定通过

[冻结证据](evidence/ws73-vm-diagnostic-cancel-live-20261011.json)：Kcc4018c4e3a6/
编译U4a9de6a91617，新QEMU binary与模块/root/bundle均冻结。Native root Diagnostic
在slkd前执行；MAC ID8/seq8实际OUT后的成功178字节IN81被暂留，QMP实际held
读回后取消，作者结果为state3/error-ECANCELED。ID9/seq9同opcode MAC保持Pending，
ID10/seq10 Features排队后取消。50ms内重复ID/取消不重发、不增加计数；显式释放
前新MAC无OUT，Features整段无OUT。释放旧MAC后旧两个结果逐字节保持取消，
新MAC由自己新OUT/回复完成，之后100ms结果和计数稳定。scope是本地请求取消，
没有宣称固件命令被线上中止；在途wire槽保持至旧回复被真实消费。

QMP三个实际readback与guest ack相同，holds1/releases1/bounded0/drops0；原host
成功transfer SHA256及178字节长度与guest USB交付完全相同。独立原始pcap重算
确认旧IN先于新OUT/IN，全阶段两组MAC且无Features发包。63条C原始记录，40/104
字节完整结构、计数和顺序均核对；原legacy poll3及33次第二作者淘汰保持，后者
seq11..43。诊断46组wire加排队取消/淘汰两个零发包窗口分别记录。

普通UID1000/caps0两只真实WS7320+2轮全部随机数据/地址/RSSI匹配，最长620ms；
同slkd、幸存g2不变/人工错误目标g1→3、read7/result16/copyout2/CLI4保持。
1431 USB零drop，warning0/taint0/trace overrun0，host四只在位且释放，无device_del/
宿主部署/人工拔插。[源码CI38096557114](https://github.com/OpenSparklink/sparklink/actions/runs/38096557114)
九作业完成成功，终结日志核对170 Rust/34 Python/185工具及实际源代码边界检查。
USB/HCC/DLI是实际radio接收证据，不是独立PHY嗅探。

这更新前面的取消/迟到门禁“待实机”，不更新完整原deadline、自动到期、实际
暂留时USB cancel/abort/close drain、CAP/其他作者取消/退役并发/32-bit或自然根因。
本次50ms重试不证明5000ms截止点不续期；它仍需独立实际到期门禁。历史物理
xHCI warning不能由新批零warning抹除。北极星仍7/8，所有完整issues继续OPEN。

## 原始 queued deadline 新门禁（format6；实现与开发）

新增显式 --diagnostic-deadline-verify，必须同时选择真实fault-recovery、
diagnostic和cancel门禁；support拒绝。专用C探针新增deadline参数和独立
scratch-root cmdline许可，默认format1–5保持原范围。format6必须验证所有
已有copy/legacy/eviction/cancel及Host hold门禁，不能降级绕过deadline记录。

实际暂留MAC8后，MAC9继续Pending，Features10取消，额外Features11仅排队
并在原100ms期限内失败。连续同ID重试记录精确40字节输出/104字节结果、
单调时钟样本；前后计数只新增一次接受、一次resolve和一次timeout，显式释放
原回复及新的MAC完成后，超时结果仍逐字节保持。完整阶段与结束到淘汰的间隙
不得有Features OUT/回复；已有旧MAC IN→新MAC OUT/IN顺序和原SHA仍须核对。

采样通过真实submit/result syscall触发expire_stale；不证明500ms后台维护
周期的自主过期、active USB timeout、held cancel/abort/close/drain或自然恢复。
开发fixture/严格C通过不等于实机通过。新镜像、全真实双设备20+2及独立raw/
pcap/QMP复核后才能记录限定资格；完整transactions、自然根因与S0–S6继续OPEN。


## 原始 queued deadline 限定实机通过（完整事务仍 OPEN）

[本批新镜像证据](evidence/ws73-vm-queued-original-deadline-20261011.json)使用实际
编译 K`7f9314309e30`／U`f8c7efb`，后续变更仅文档；全部编译源 hash 与冻结
prepared 输入再次核对。原 Features11/seq11 请求 100ms，136 个真实连续重试
样本中 90 个 Pending，首次观察 ETIMEDOUT 距 admission 前时钟 99.581092ms，
采样跨度 149.374022ms（实现时钟精度与观测间隔限制保留，不宣称精确到期时刻）。
40 字节 admission 和 104 字节结果完整核对；超时只记一次，释放后不复活。
全暂留阶段和释放到淘汰之间没有 Features OUT／回复。

原 host 成功 transfer 为178字节，SHA256
`1a94d249b21c58f47ec1c7c5bce5b0f8af10358b950f03ff148b51561a6a1b69` 与实际 guest
USB 记录一致；QMP与guest ack保持一hold／一显式release，无bounded release/drop。
独立49份诊断证明含46组wire；旧MAC IN先于新MAC OUT／IN。原63条C、read7、
result16、copyout2、legacy poll3、淘汰33／静默、CLI4、三身份旧注册27拒绝保持。
真实WS73普通用户20＋2轮随机数据／地址／RSSI均匹配，最长621ms；同slkd
PID661/start1644，幸存g2保持，人工IN81目标g1→3，重新Ready约10.175秒。
1431 USB零drop、22份真实RX、warning0／taint0／trace overrun0；host四只释放在位，
没有device_del、宿主部署或人工拔插。USB／HCC／DLI并非独立PHY嗅探。

[源码CI38099897596](https://github.com/OpenSparklink/sparklink/actions/runs/38099897596)
九作业终结成功，实际日志170 Rust／34 Python／195工具，4授权／78verifier／
18queue及严格C探针通过。一次日志下载EOF保留，仅重新下载该作业日志；没有
重跑或修改CI门禁。此前本地fixture错误、构建／prepare失败及物理xHCI warning
历史记录保留，不用本批零warning抹除自然故障根因。

这只更新 queued 原始期限／同ID不续期的 syscall 观测资格，不更新后台500ms
heartbeat自主过期、active USB timeout、held cancel／abort／close／drain、完整
owner／CAP／并发／removal／32-bit或自然故障恢复资格。下一步分别实现这些门禁
及旧调用者迁移删除。北极星7／8，全部完整issues和S0–S6继续OPEN，VM-only。
