# 端点、能力默认值与在途文件关闭门禁

这批整改保持完整 [S0–S6](IMPLEMENTATION_PLAN.md)、
[Linux／BlueZ 分层](BLUEZ_RECONCILIATION_20261011.md)及真实 WS73 北极星。
只在 VM 内运行内核、模块和设备测试；不修改宿主部署。

## 已实现的生产清理

| 类别 | 实际调用关系 | 实施 |
|---|---|---|
| 立即删除 | Rust probe → C `sle_usb_dev_register` | 删除 descriptor 失败时的 “test mode” 硬编码端点、大小、interval；返回原错误，零 packet size／interval 拒绝 |
| 立即删除 | USB／serdev `info`、controller 默认值、`sle_attach_device` metadata projection | 删除未查询的 feature、连接数、MTU/MPS、transport／measurement／crypto 声明；协议 codec 最大值不再填充硬件限制 |
| 立即删除 | USB constructor | 删除未使用的 opened 字段和 fallback 常量，修正 MAC opcode 注释；保留实际地址与已查询固件投影 |
| 移入测试／已隔离 | register／info／firmware 依赖注入、真实 QEMU IN81 暂留 | 仅 selftests 或明确 opt-in 的 VM 工具，不编入生产成功路径 |
| 等待替代 | 有调用者的旧 loader/backend、core 总线耦合、global parser/fallback/shared ring、旧信息 UAPI | 新路径接通调用者并回归后删除；UAPI 未发布，无需永久兼容 |

注册先查 descriptor、分配两个私有 context，全部成功后才更新 active table。
缓冲区来自实际 interrupt IN／bulk IN 的 packet size；失败不修改已有 table，
第一处分配的 context 在第二处失败时释放，不影响 peer。成功注册仍不提交 URB。
已有下载后的强制 rebootstrap 和 probe 失败 quiesce/join/detach 保持。

默认 0 表示尚无可宣告的能力／限制，**不代表无限制，也不证明明确不支持**。
这批没有添加完整的 known-supported／known-unsupported／unknown 来源矩阵；
旧信息接口不能完整表达它，仍需迁移版本化 snapshot 和调用者后删除。
其他编译内存预算、旧 DLI_INFO 的 max_adv_sets、profile/quirk、运行时与板级版本
资格不能当硬件能力；K11/K13 的完整门禁继续开放。Native WS73 已查询 metadata
与 driver 保持原实现，未借用标准 USB／serdev 默认值。

## 实际源码开发测试

`run_usb_discovery.py` 提取实际 C register/unregister、实际 Rust info struct/default、
USB/serdev info 以及 attach 的 metadata projection。descriptor lookup、分配、URB、
固件 getter 和周围类型是专用依赖 fixture。18 个 C sanitizer 案例覆盖错误原样返回、
非法 size/interval、两处分配失败、table 原子性、复用、peer 和 unregister；5 个
严格 Rust 测试覆盖未知不补默认、真实 getter、显式 metadata 不扩展能力。

初次提取器未支持 void unregister，在运行 C 前失败；修正提取，不改生产逻辑。
关闭门禁最初的参数拒绝测试错用了外层 lab-lock entrypoint，缺少 prepared 参数，
修正为实际 flag-validation entrypoint 加环境依赖 fixture。原失败日志保留。
全部 234 工具测试通过；fixture 不是通用 USB／serdev 方言或自然恢复资格。

## 新增真实在途关闭测试

`ws73_target.py run --active-close-verify --fault-recovery` 使用独立新 scratch VM，
可叠加 `--setup-release-verify --event-copy-verify`，排斥 synthetic、普通 deadline
和 explicit-release diagnostic 组合。复用原 hold、metadata、capture 验证器，旧证据
和 deadline 模式仍可核对。

测试使用现有 slkd 初始化两只设备到真实 Off/Ready 后退出；root Diagnostic 提交
实际 MAC 查询，QEMU 暂留已经由设备成功返回的 IN81 bytes。随后 dup owner fd，
通过 adapter.free 关闭原引用，F_GETFD 应返回 EBADF；100ms 后独立 observer 仍
看到精确 Held／Diagnostic、无 token。关闭最后 dup，F_GETFD 再返回 EBADF，
observer 必须看到 Revoking，不提前 Free、不合成 Complete。

此后只用文件/QMP 被动等待。Host 保留原 500ms deadline，Runtime 退役必须取消
真实暂留传输，QMP 显示一次 abort、零 release/reset/detach；不能向目标发送新的
命令、收到旧暂留回复。旧 generation 的 observer 拒绝调用，peer 同 generation
及两次实际 MAC 查询保持。关闭证据、原期限和 capture/kernel 日志一起核对。

这不是“close 立即 abort”的要求或证明：安全 drain 可以等待原在途 deadline，
不能因作者关闭就丢失旧回复关联，也不能靠新超时无限延期。精准期限上界、Managed
部分初始化 cleanup、所有 owner/CAP/并发/removal/32-bit、自然 RCA 和完整自动恢复
仍单独开放。本批新 VM 实测的限定资格见下；源代码和 mock 记录本身不能算通过。


### 当前端点／能力默认值清理与真实在途最后文件关闭

K`c5ec97f50c06`／编译U`ad5e28727229`已删除生产descriptor失败的“test mode”
端点回退，context私有准备成功后才发布；删除USB/serdev/default/attach未经查询
的feature、255/8/MTU/MPS/transport/measurement/crypto声明，保留实际身份/固件。
[调用清单、未知值和门禁范围](USB_DESCRIPTOR_CAPABILITY_CLEANUP.md)明确0不代表
无限制或已知不支持；完整caps/limit/quirk来源、旧DLI_INFO软件预算与UAPI迁移仍OPEN。
18个实际C register/unregister sanitizer案例、5个实际Rust info/default/attach测试
通过；原固件69 C/12 Rust及管理10门禁保持。6个在途close负例测试使工具总数234。
提取器void支持和测试入口错误、一次错误expected HEAD被快照校验器拒绝的原日志
均保留；修正后完整内核/private modules/签名smoke通过，编译器原0计数有误、实际1条warning（见下方勘误）；GNU make
一次jobserver警告。Native WS73 driver/已查询metadata未改。

[新镜像两个独立VM封存](evidence/ws73-vm-descriptor-cleanup-held-close-20261011.json)
首轮实际Diagnostic MAC回复由QEMU暂留：原fd关闭得到EBADF，dup保有Held100ms；
最后dup关闭EBADF、observer精确Revoking，原500ms Host deadline触发Runtime退役
并取消实际IN81，一次abort／零release-reset-detach、无新目标命令或旧回复交付，
旧generation拒绝、peer不变且两次真实MAC成功。此为already-Off Diagnostic有界
原期限drain，**不证明close立即abort、Managed部分初始化或完整生命周期**。
两新VM均各6 Setup release/last-file/dup及完整窗口零DLI；分别保留稳定预算归零
和完整原诊断63记录/50proof/46wire/read7/result16/copyout2/poll3/淘汰33/CLI4/
旧注册27拒绝、queued原期限。各UID1000/caps0真实20+2，最长470/774ms，各自
同RF slkd/peer，USB1345/1431、各22RX/零drop，guest warning0/taint0/traceoverrun0，
四只结束释放在位。USB/HCC/DLI不是独立PHY；hold期间同daemon未资格。
[精确源码CI38111118827](https://github.com/OpenSparklink/sparklink/actions/runs/38111118827)
九作业终结success，170 Rust/34 Python/234工具、32期限/10管理/固件69+12/
新增descriptor18+info5门禁。

下一步推进Managed部分初始化真实cleanup、不同radio/history/在途阶段的close与
有限恢复／自然RCA；迁移独立事件消费者后删shared ring/fallback/未发布旧UAPI，
并接通完整能力来源与显式不支持、drivers-owned backend/parser、最小socket、
SSAP/每连接安全/Agent/Bond/Profile、四设备两组及Native/Proxy/PM/sandbox/发布。
完整S0–S6与28项原scope保持，VM-only／北极星7/8，不关闭自然启动/重枚举/消失
根因、无人工拔插恢复或历史物理xHCI warning，部分成果不关闭整项或合并draft。


## 构建警告计数勘误（原封存保留）

上一批 K`c5ec97f50c06` 的“编译器 warning0”计数错误：原构建日志实际有
1 条 `MAX_PAYLOAD_LEN` 未使用导入警告，另有 1 条 GNU make jobserver 警告。
[勘误及原日志/封存哈希](evidence/descriptor-cleanup-build-warning-erratum-20261011.json)
保留原 JSON 字节，不把错误记录改成成功；文档和 issue 中的原编译器零计数应以
此勘误为准。原 guest warning/taint、RF/USB/VFS/deadline 证据来自独立实测，
不与编译器 warning 混同，也不因勘误宣称新源码或新 Managed 分支验收。

K`292f9fec84b6` 已删除导入，新完整构建 compiler warning0、make jobserver warning1。
离线 build checker 增加终结日志 SHA-256 验证与 diagnostics 分类：编译器 warning、
make warning、未分类 warning 分别记录，Rust/Clang 汇总行不当作第二条警告。
未知 producer 不能被宣称为 warning-free，活跃/失败/无哈希/日志篡改拒绝。
六项新增负例/计数测试及全部 240 工具测试通过。日志计数仍不等于全部 compiler
输入来源、实机或完整发布资格；自然 RCA、完整恢复和 S0–S6 原验收继续 OPEN。
