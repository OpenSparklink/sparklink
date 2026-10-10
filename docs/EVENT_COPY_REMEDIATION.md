# 旧事件 read 的消费提交与迁移门禁

2026-10-11；Linux 20f431f54af01334faa37a6af84bbce1260ef9c9。R12限定整改；
K3/U2及完整独立事件/移除/旧路径清理验收仍OPEN。UAPI未发布，无兼容期。

## 调用审计

| 路径 | 当前调用者/所有者 | 本批状态 |
|---|---|---|
| MiscDevice::read_iter → per-fd EventQueue | 旧kernel C selftest/ctl；固定44字节SleWireEvent | 使用唯一copy_records，完整记录复制成功才消费/增加delivered |
| EventQueue::drain_to_buf | rg审计无调用者 | 立即删除；dequeue仅私有提交helper，无第二套生产drain |
| DLI_POLL_EVENT → runtime.pop_dli_event/backend.poll_event | legacy lib EventReceiver、profile0 slkd、旧DLI工具/selftests | 是另一条旧路径，仍存在先消费再copy风险及backend直读fallback；等待独立订阅调用者迁移后删旧入口 |
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
