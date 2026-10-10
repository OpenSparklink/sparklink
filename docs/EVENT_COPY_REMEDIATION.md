# 旧事件 read 的消费提交与迁移门禁

2026-10-11；Linux 20f431f54af01334faa37a6af84bbce1260ef9c9。R12限定整改；
K3/U2及完整独立事件/移除/旧路径清理验收仍OPEN。UAPI未发布，无兼容期。

## 调用审计

| 路径 | 当前调用者/所有者 | 本批状态 |
|---|---|---|
| MiscDevice::read_iter → per-fd EventQueue | 旧kernel C selftest/ctl；固定44字节SleWireEvent | 使用唯一copy_records，完整记录复制成功才消费/增加delivered |
| EventQueue::drain_to_buf | rg审计无调用者 | 立即删除；dequeue仅私有提交helper，无第二套生产drain |
| DLI_POLL_EVENT → runtime.pop_dli_event/backend.poll_event | legacy lib EventReceiver、profile0 slkd、旧DLI工具/selftests | 是另一条旧路径，仍存在先消费再copy风险及backend直读fallback；等待独立订阅调用者迁移后删旧入口 |
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
设备移除唤醒。后续须补实际VFS故障及R12旧DLI消费者迁移，保留有价值旧失败用例。
R09 PHY/加密状态提前提交仍待修；WS73自然超时/重枚举/消失根因、完整无人工恢复、
四设备两组及宿主原生对照（VM-only未授权）不因本批关闭。北极星仍7/8。
