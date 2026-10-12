# 当前能力与资格

**唯一当前资格入口。** [ARCHITECTURE](ARCHITECTURE.md)与ADR定义目标/契约，
[IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md)是唯一执行入口；
[采用记录](ARCHITECTURE_ADOPTION_20261013.json)记录用户提案、在线scope及调整。
五个维度独立；源码、离线、模型、实机均不替代其他维度，不用一个“完成”字段。

| 范围 | 已实现 | 离线通过 | 形式化限定通过 | 实机通过 | 仍缺失 |
|---|---|---|---|---|---|
| WS73发现/连接 | Native真实事务、动态adapter、typed Peer/Connection | 对应准确提交的生产源码/codec/ABI回归 | 不继承数据模型资格 | 当前K770364dcc152/U96ac968两次RF22、真实建链/断链与QMP支撑，历史物理证据保留 | 原NS1自然恢复、当前数据路径物理拔插/全部连接竞争 |
| 默认CUTC31/PI241 socket | A3/ACB、运行时254/5查询、独立命令/data credit、旧debt、有界TX与普通fd委托 | 当前20项Native生产函数体回归（USB/锁/注册依赖fixture）、CI96ac968九项成功 | Credit守恒Kani仍未证明；不证明NOCP物理归属 | 新K770364dcc152/U96ac968每角色20/共40轮61-byte实际对端往返 | credit耗尽/满队列、提交票据、Grant epoch、旧lifetime全矩阵 |
| 协商原期限/共享状态 | 38926b2完整三步骤与原期限；同锁快照、关闭/最终软件准入 | C编译、ASan/UBSan deadline/terminal selftest、完整新内核/空USB VM | FV01生产CBMC131项；FV03锁LKMM两性质，故意弱对照允许坏结果 | 上述新40轮及下述249路径保持 | 受控回复/credit阻塞期限、worker/VFS引用完整映射、唤醒及VM KCSAN/lockdep |
| application249/DTAP254 | 当前单ACB上限与精确长度拒绝，ec67348后工具/应用接通 | 196 workspace/423工具及严格clippy；准确96ac968 CI9/9 | 不能从协商模型推出codec/分片性质 | 新版本8轮249字节及16次application250/253/254/255 EMSGSIZE，拒绝载荷捕获为零 | DG02同Binding短→最大→拒绝→短、其他层253/254/255、长包/PB TX/SAR |
| Session/Channel/Binding/Grant | 当前仍单socket消费整连接ACB，单消费者限制保留 | 目标所有权/四阶段契约采用 | FV04仅2controller/2generation/queue1/refs0..2抽象契约784状态；没有refinement | 不继承单socket数据资格为多通道资格 | Session唯一RX、CMTC与fd分离、同life reopen、可撤销Grant、Ticket/复用屏障 |
| NOCP/复用 | 旧debt保留，未知/过量/不确定Fault，不自动退款 | 生产ledger已重现四步复用风险 | FV07期望反例，不是安全证明；FV02 unsupported/超时NOT_PROVEN | 短40轮实际88完成、249八轮实际24完成，范围限定 | 同/跨life重复/迟到来源、准确性与可信排空屏障；无实机串包断言 |
| 旧SSAP业务 | K167f468剥离local DB/session/cache；K770364dcc152/U7d8857b删除18旧ioctl/业务字段/绑定，CLI/Profile拒绝；旧模型仅selftests；U56ea3e8默认facade NotSupported | 历史八项和生产依赖审计、Native20、连接边界及删除后用户态196/严格clippy；Python34含全Netlink声明一致性，facade私有D-Bus回归；实验callback回归保留 | 不能宣称已有生产用户Engine | 本批默认生产剥离通过：旧18 ioctl root/ordinary全部ENOTTY，新40短/249/发现建链路径保持；没有真实SSAP资格 | 本批退出条件通过；后续Session/Ticket/Grant/socket/Backend等目标架构整改，再WP08唯一用户Engine；相关整项issues仍开放 |
| SSAP/安全/Bond/Profile | 用户态目标层；旧Profile已隔离实验crate，Native不注册旧Profile | 部分机制/actor/类型测试，仅各自范围 | FV08/09完整协议证明未取得 | 尚无新真实通道服务/安全安装矩阵资格 | 唯一用户态Engine、真实read/write/notify/indicate、可信安装/Bond/Profile |
| Backend/事件/恢复/PM/四设备 | 现有Native及限定事件/生命周期基础保留 | 原完整方案/历史部分初始化和取消测试保留 | FV10及完整工作引用/恢复模型缺 | 历史物理/注入/部分清理仅其准确范围；本轮warm恢复不授予自然恢复 | 可注册seam/构建组合、事件迁移、四设备两组数据、自然RCA/非人工恢复、Proxy/PHY/PM/发布 |

当前实现/资格：K770364dcc152、编译服务与工具U96ac968。两次VM均保留原slkd、
同行generation/业务及真实断链/QMP支撑。QMP不是物理拔插，也不是自然恢复。
本批原期限/credit源码未改；形式化资格仍按原报告逐文件hash核对，未新增整体证明。

证据索引：

* [SSAP剥离后40轮](evidence/ws73-ssap-separated-short-repeat-20261013.json)：当前准确源码；336 raw A3、176两端SDU、88真实NOCP、2225包/零drop/taint0。
* [SSAP剥离后249/超限](evidence/ws73-ssap-separated-249-boundary-20261013.json)：当前准确源码；8往返、16超限拒绝，192 raw A3、48两端SDU、24真实NOCP、1809包/零drop/taint0。
* [本批离线/源码映射](evidence/ssap-abi-separation-offline-20261013.json)：196workspace、34Python、423tooling及CI9/9；历史模型不算新用户Engine。

* [P1历史准确版本40轮短业务](evidence/ws73-ordinary-channel-state-repeat-20261013.json)：K d3abbdc0c13a、编译应用/工具afb5ee2，336 raw A3→176两端SDU、88真实NOCP，2225包/零drop/taint0。
* [P1历史准确版本249及超限](evidence/ws73-ordinary-channel-249-boundary-20261013.json)：同源码，192 raw A3→48两端SDU、24真实NOCP，1809包/零drop/taint0。
* [形式化报告及原始输出](evidence/formal-20261013/manifest.json)：K d3abbdc/U40c7fba，源码hash/工具/假设/界限见formal/README；安装13项不计实现证明。
* [旧40轮](evidence/ws73-ordinary-channel-repeat-20261013.json)、[首次注册panic](evidence/ws73-channel-registration-boot-failure-20261013.json)、[最后回复关闭丢弃](evidence/ws73-channel-last-reply-close-failure-20261013.json)均保留。
* [历史实施/故障索引](IMPLEMENTATION_HISTORY_PRE_20261013.md)保留原scope、partial/release/最后fd/dup/在途与所有失败；不会把旧源码资格倒填新版本。

K4b4c6add8189已把基础类型迁移DGRAM并拒绝未合格SEQPACKET，broker同步；当前新提交VM资格待取得。
历史实验SOCK_SEQPACKET证据只证明消息边界/业务往返，不能授予可靠递送承诺。
实验AF/PF46已实现，正式协调未完成。SDK111镜像/配置来源与本轮冷/暖/实际上传分别记录，warm tuple不证明本轮上传。
实验驱动与真实I/O保持VM-only。全部原28项issues及goal保持开放/active，自然启动/重枚举/消失根因和
非人工自动恢复未闭合。人工拔插、hub切电、QMP、注入、模型及USB写成功均不替代业务/自然恢复资格。
