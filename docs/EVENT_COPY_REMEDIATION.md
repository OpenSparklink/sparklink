# 旧事件 read 的消费提交与迁移门禁

当前限定取消/迟到实机门禁见[实际记录与未决条件](DIAGNOSTIC_CANCEL_GATES.md)：
K`cc4018c4e3a6`/编译U`4a9de6a91617`使用专用QEMU暂留178字节真实回复，
在途/排队本地ECANCELED、旧槽隔离、新查询自己的回复及46组wire限定通过；
原20+2/read7/诊断/legacy poll3保持。完整deadline/held close/并发和自然恢复
仍OPEN，生产路径不变。全部issues和完整S0–S6保持开放。

2026-10-11；Linux 20f431f54af01334faa37a6af84bbce1260ef9c9。R12限定整改；
K3/U2及完整独立事件/移除/旧路径清理验收仍OPEN。UAPI未发布，无兼容期。

## 调用审计

| 路径 | 当前调用者/所有者 | 本批状态 |
|---|---|---|
| MiscDevice::read_iter → per-fd EventQueue | 旧kernel C selftest/ctl；固定44字节SleWireEvent | 使用唯一copy_records，完整记录复制成功才消费/增加delivered |
| EventQueue::drain_to_buf | rg审计无调用者 | 立即删除；dequeue仅私有提交helper，无第二套生产drain |
| DLI_POLL_EVENT → runtime.pop_dli_event/backend.poll_event | legacy lib EventReceiver、profile0 slkd、旧DLI工具/selftests | 共享消费旧路径；K54621800ee4c已增加复制后提交和fallback暂存；Native ring三类实际复制故障已通过；fallback资格、完整事件及独立订阅迁移/删除仍待完成 |
| slkconfig Native query → owner-private diagnostic result | 原生产调用者，已按 fd/generation/local sequence 迁移 | 删除 stale drain 与共享 poll；结果不消费，完整旧调用者迁移仍 OPEN |
| ControllerEventReceiver → typed controller subscription | 当前Native WS73 slkd/slctl；新monitor独立snoop | 本批不改；重新用新镜像验证discovery及幸存者 |

保持三类清理安排：无人调用的helper立即删除，copy故障模拟仅selftests；旧DLI
消费/默认选择/事件UAPI等待替代与调用者迁移。不能将read修复称为DLI ioctl修复。

## 记录及错误语义

持有per-fd queue mutex直到复制/提交完毕，阻止同fd另一reader或producer替换head。
零长度返回0；非零但小于一条记录返回EINVAL；足够空间且无记录返回EAGAIN。
第一条完全/部分复制失败返回EFAULT，队列/交付统计不变。已有成功记录时只返回
其完整字节数，下一条失败记录保留；用户空间忽略返回长度以外的任何部分写入。
这不是向用户内存的原子写保证。capacity尾部不足整条不消费下一条。
显式64槽overflow仍按原策略计数，与copy失败保留分开。

## 开发测试与实机边界

专用run_event_copy.py编译整个实际sle_event.rs和实际read_iter，依赖copy/mutex/
未执行in-place init由fixture提供，不是复制出来的第二套队列算法。9项覆盖44字节
全部first/later partial位置、零/短缓冲、容量尾部、wrap/overflow、实际BroadcastRing
fan-out、实际read接线与同fd锁内提交。严格-D warnings通过；完整kernel核心对象
编译通过，已知make jobserver警告仍记录，未新增global lint压制或生产测试hook。
新增固定kernel pin CI门禁；本批完整image/新VM真实双设备回归需另行记录。

fixture不能证明真实read(2)坏地址/跨页用户copy、kernel mutex/lockdep、runtime路由或
设备移除唤醒。实际VFS故障的后续验证见下文；R12旧DLI消费者迁移仍待实现，
保留有价值旧失败用例。
原 R09 本地提前提交路径已[移除](LINK_STATE_REMEDIATION.md)，实际硬件事务仍待接通；WS73自然超时/重枚举/消失根因、完整无人工恢复、
四设备两组及宿主原生对照（VM-only未授权）不因本批关闭。北极星仍7/8。

## 新镜像实机及CI复核

[本批VM证据](evidence/ws73-vm-event-copy-regression-20261011.json)对应内核
20f431f54af0/编译用户态5f48a80b07b6：完整image/modules、冻结source/config/hash、
空USB签名module两次load/unload通过。真实双设备20+2轮，最长621ms，host独立
核对22份RX/1163 USB零drop；UID1000/caps0，同slkd PID528/start338及bus owner，
幸存generation2不变，目标1→3，最终两只STOP_CONFIRMED，VM warning0/taint0。
单对象人工guest IN81失败命令至新Ready约10572.148ms；10秒发现门限从成功scan
Complete计时，不能用恢复耗时替换发现计时。host四只仍在并释放。本轮没有物理
拔插、自然故障根因、完整自主恢复、live VFS坏地址或完整sandbox验收。

[CI38082158063](https://github.com/OpenSparklink/sparklink/actions/runs/38082158063)
9作业成功，实际日志核对167 Rust/33 Python/141工具，以及security6/backend2/
TX11/SSAP9/event-copy9与C sanitizers。此处event-copy依赖fixture范围仍适用，
不能把本批RF证据当作read(2)故障测试。后续文档head与实际编译head分别记录。

## live VFS门禁及新镜像验收

新增canonical C selftest通过两个绑定相同controller的独立fd读取真实管理事件。
专用VM工具由普通用户slctl scan on/off产生事件，C调用实际read(2)/mmap/mprotect：
零/短buffer、完全不可写地址、首条和后续guarded-page部分复制、capacity尾部及
完整batch。失败后与另一fd参考记录逐字节比较，核对pending/enqueued/drop/delivered，
确认空队列EAGAIN。部分copy必须观察到已写的前缀，不能仅测试预检查拒绝。
没有生产注入hook，不执行raw DLI、不重置设备或重启daemon。

使用新prepared环境运行ws73_target.py run --event-copy-verify --fault-recovery。
该选项仅支持明确opt-in的隔离NVMe/Btrfs VM，不能在宿主执行；固化C source、
canonical header、编译命令/程序及Python supervisor。CLI退出/进度截止时间、
reference bytes/统计/类型/顺序均为门禁，开发verifier fixtures不算live结果。
Linux `3a6669114069` / 编译用户态 `6c06b8f9ef83` 的
[新镜像证据](evidence/ws73-vm-live-event-copy-20261011.json)已完成7类实际read测试。
内核生产代码与20f431f54af0相同，新增C selftest仅用于测试；没有生产注入hook。

| 场景 | 实际返回 | 验证 |
|---|---|---|
| 零buffer | 0 | 3条记录及delivered保持，重试取回全部 |
| 非零短buffer | -1 / EINVAL | 不返回假EOF，不消费 |
| 完全不可写地址 | -1 / EFAULT | 失败head保留，重试字节与独立fd相同 |
| 首条跨页部分复制 | -1 / EFAULT | 确实写入22字节，记录及统计仍保持 |
| 后续跨页部分复制 | 44 | 只消费前一条完整记录；另写入22字节不计返回，失败head保留 |
| 容量尾部不足整条 | 44 | 下一条保留 |
| 完整batch | 132 | 3条各44字节完整交付，之后EAGAIN |

每类都核对pending/enqueued/drop/delivered及参考fd原始记录，独立解析probe
JSONL并重新运行严格verifier。普通supervisor UID1000/caps0，C程序校验实际/有效
UID；冻结ELF无setid/file capabilities，未另采集子进程capability状态。两个fd
绑定同一controller，事件来自真实WS73经slctl完成的scan命令，不是合成事件。
两只保持原generation、同slkd PID523/start341及bus；probe退出0、停止确认。

随后真实双设备20+2轮通过，最长622ms，独立22份RX/1247 USB包零drop。
人工guest IN81失败至新Ready约10773.253ms，幸存generation2保持、目标1→3、
同daemon、最终两只STOP_CONFIRMED，VM warning0/taint0/trace overrun0。host
四只仍在且已释放。本批没有物理拔插，接收端USB/HCC/DLI佐证不是PHY嗅探。
[CI38083436958](https://github.com/OpenSparklink/sparklink/actions/runs/38083436958)
9作业成功，实际日志核对167 Rust/33 Python/146工具；security6/backend2/TX11/
SSAP9/event fixture9及C sanitizers通过。CI只编译live C probe，7类实机执行在VM。

这关闭了上述7类legacy read用户copy门禁，不能替代旧DLI ioctl消费者迁移、
kernel并发/lockdep、完整结果所有权/路由或移除唤醒。R12/K3/U2整项、自然恢复
根因、北极星7/8及完整S0–S6仍OPEN；旧DLI入口迁移后直接删除，无兼容期。

### R12 当前限定 diagnostic 实机门禁（2026-10-11）

Linux `49cabad043f6` / 编译用户态 `d8c091a4b243` 的
[诊断迁移记录](DIAGNOSTIC_RESULT_MIGRATION.md#当前限定实机门禁通过完整-issue-仍-open)
与[新镜像证据](evidence/ws73-vm-diagnostic-live-20261011.json)补齐16个实际
syscall case、4次实际slkconfig查询和8组独立USB命令/回复。退役Runtime在租约
检查前返回ENODEV；原fd继承的UID1000/caps0子进程、另一个持自己Diagnostic
租约的root fd均拒EPERM；只读/部分输出EFAULT后的104字节结果重试保持。
模拟只在selftests；新测试程序仅在显式隔离VM运行，没有生产成功注入。

7类legacy read及真实20+2轮仍通过，最长606ms、22份RX/1279 USB零drop、
同slkd与幸存g2不变；9作业CI实际169 Rust/33 Python/155工具/诊断fixture11。
前两轮测试环境/证明窗口FAIL原记录保留。限定门禁通过不删除仍有调用者的
旧DLI路径，也不关闭R12/K3/U2：下一步补齐admission copyout可找回/幂等、
cancel/deadline及剩余消费者迁移，回归后删除重复实现。自然故障根因、完整
无人工拔插恢复、socket/SSAP/每连接安全/Bond/Profile/Proxy及全S0–S6仍OPEN。


## 旧 DLI poll 过渡修复（K54621800ee4c，实机故障门禁待执行）

调用审计确认，共享 ring 与 backend fallback 都在复制到用户空间前消费事件。
本提交让该入口先 peek，完整写入256字节后才 pop。若 ring 为空，backend 已取出的
事件先放入同一现存 ring；EFAULT 后重试优先返回暂存事件，不再次取走 backend
事件。选定 controller 的状态 mutex 保持到复制和提交结束，防止同期消费者或
overflow 替换队首。没有新增第二队列、生产模拟、公开 UAPI 或全局 lint 豁免。

这只修复复制失败的消费顺序：部分写入用户缓冲仍可能发生。ring 保持原32槽/
31条可用及显式丢弃最旧记录策略；后续真实 overflow 仍可能丢弃保留事件。
状态锁跨 usercopy 的过渡实现会阻塞同设备工作；不宣称完整并发、活性或lockdep
验收。最终仍迁移 EventReceiver/profile0 C/Python/slkd、--legacy、旧 selftests，
删除共享 ring、backend fallback 和 DLI_POLL_EVENT。UAPI未发布，无兼容期限。

`python3 tools/testing/selftests/sparklink/run_event_copy.py`编译实际 canonical声明、
push/peek/pop 与 ioctl helper；新增6项依赖fixture，已有9项read_iter继续通过。
覆盖所有0..255复制前缀、backend仅取一次及重复失败后重试、FIFO/一次提交、
wrap/overflow、空队列EAGAIN及退役ENODEV。controller/codec、usercopy与std mutex
为依赖替身，不能当作真实backend、内核usercopy、权限或并发证明。

新镜像必须先回归20+2真实WS73、普通用户、同slkd、read7、诊断result16/
copyout2/淘汰33。随后新增实际legacy ioctl坏地址、只读与跨页部分输出：
用真实MAC查询完成事件作为队首，核对256字节重试内容、成功后一次消费和空队列
EAGAIN，并捕获唯一真实查询/回复。Native ring的实机结果也不能替代另一backend
fallback的独立资格验收。在K546提交时这些新故障门禁仍待执行，完整R12/K3/U2保持OPEN。


## 新生产内核的已验证路径回归

[新镜像证据](evidence/ws73-vm-legacy-poll-copy-20261011.json)：K`54621800ee4c`/
编译U`dc8745986044`，完整image/modules与默认bundle已冻结，空USB VM两次
签名module加载/卸载通过。真实WS73双设备20+2均匹配随机数据、地址、RSSI，
最长621ms；普通UID1000/caps0、同slkd PID649/start1567与bus owner。
幸存generation2保持，人工IN81错误目标1→3，新Ready约10298.322ms；这不是
自然故障验收，10秒发现门限仍从scan成功Complete开始计算。read7、result16/
copyout2、第二作者淘汰33/旧ID无重发及CLI4通过，捕获1411/零drop，独立
核对22份RX与41组诊断命令/回复；VM warning0/taint0/trace overrun0，四只host
设备均存在且释放。USB/HCC/DLI捕获不等于独立PHY嗅探。

[CI38093030937](https://github.com/OpenSparklink/sparklink/actions/runs/38093030937)
9作业全部成功，实际日志核对170 Rust/34 Python/165工具及event-copy15
（read9/poll6），全部三个kernel pin均为新生产提交。CI编译live C而不执行
设备；fixture仍不证明真实kernel mutex/并发或legacy ioctl用户copy。

这轮K546镜像证明保持已验证WS73路径；该批尚未执行新legacy poll复制故障门禁，
backend fallback资格、共享投影删除、完整事件/事务、自然故障根因及恢复仍OPEN。
历史物理xHCI警告保留，不以本批无warning推论已修复；S0–S6范围不缩减。


## 实际 legacy ioctl 复制故障工具与限定验收

K9b16e634bfd3新增专用C探针，生产内核保持K54621800ee4c。在slkd启动前，
root Diagnostic独占同controller；最多31条清理本轮已有投影，再分别用ID5..7
提交真实MAC查询。成功结果104字节与实际地址核对后，对输出256字节事件执行
坏地址、只读页、128字节可写前缀+只读后缀测试；实际EFAULT后取回完整相同事件，
再poll必须EAGAIN。存储提交输入/输出40、结果104、事件参考/重试256、可读
fault输出、实际errno/时间/统计；没有生成测试Complete或生产注入hook。

当前诊断runner使用format4，要求三条legacy记录位于missing_sequence之后、
释放原作者并验证foreign作者之前；诊断淘汰33、copyout2、原结果16和CLI4仍是
必须项。独立捕获每个seed/fault/retry窗口一个真实OUT/成功Complete，并核对整个
legacy阶段含间隙没有额外命令/回复。58条C记录、44组诊断wire及一个拒绝观察窗口已在下述新镜像验证；
只记录限定Native ring门禁，不扩展为完整事件或另一backend资格。

verifier新增5项合成拒绝回归（诊断共24，工具共170），保留历史format1/2/3
证据严格验证，当前runner不能降级。Native共享ring实机测试不能证明backend
fallback硬件资格、内核并发/lockdep/移除唤醒或完整事件所有权；它们仍OPEN。


## Native ring 三类实际 ioctl 复制故障通过

[冻结证据](evidence/ws73-vm-legacy-poll-live-20261011.json)：K`9b16e634bfd3`/
编译U`1d3a17b688ee`；生产内核保持K54621800ee4c，daemon/library/crates/data
保持Udf9。完整image/modules、空USB VM两次签名模块load/unload、默认bundle
重新构建通过。root Diagnostic在slkd之前执行真实MAC seed ID5..7/seq5..7。
先清理本轮4条旧投影，再逐项执行：

| 实际场景 | 第一次返回 | 观察输出与重试 |
|---|---|---|
| 地址1不可写 | -1 / EFAULT | 重试256字节与真实MAC结果的canonical事件完全相同 |
| 整页只读 | -1 / EFAULT | 原256字节A5保持；重试完整事件 |
| 前128字节可写，后128只读 | -1 / EFAULT | 前缀确实等于canonical事件，后缀A5保持；重试完整事件 |

每项重试成功后再次poll为-1/EAGAIN；submitted/resolved各仅增加1、pending0/
timeout不变。输入输出40、成功结果104、事件参考/重试256、可读故障输出及
实际时间/errno均保存。独立捕获核对每个完整seed/fault/retry窗口唯一真实OUT/
成功Complete，三项整体阶段包括间隙也没有额外命令/回复。不是用生成事件
或模拟success测试。另一个backend的controller.poll_event fallback未实机验收。

第二作者淘汰门禁现为seq8..40，33次真实查询/旧ID拒绝和100ms无重发保持；
原结果16/copyout2/CLI4、read7和普通UID1000/caps0真实WS7320+2通过，最长620ms。
同slkd PID654/start1559/bus owner，幸存g2不变、人工IN81目标g1→g3，新Ready
约10917.300ms。1423 USB零drop、独立22份RX/44组诊断wire，warning0/taint0/
trace overrun0，host四只存在且释放；无人工拔插/宿主部署。USB/HCC/DLI并非独立
PHY嗅探，人工错误支撑不证明自然故障根因/自主恢复。

[CI38093912963](https://github.com/OpenSparklink/sparklink/actions/runs/38093912963)
9作业成功，实际日志170 Rust/34 Python/170工具、event15；三个kernel pin均新提交。
当前runner必须format4，历史format1/2/3按各自范围严格验证，不升级历史验收。
实际gate是顺序Native Diagnostic、x86_64与上述三种输出；并发/lockdep/活性/
移除唤醒/32-bit runtime/完整所有权与subscriber迁移及ring/fallback/UAPI删除仍OPEN。
