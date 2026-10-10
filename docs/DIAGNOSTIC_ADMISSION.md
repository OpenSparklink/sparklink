# Native metadata 诊断请求身份、截止时间与取消

2026-10-11，Linux `c89e961b80a2b99922ddd0715590c01edfe39c88`；未发布UAPI同步迁移，不保留Native双提交入口。
两类限定提交copyout幂等性已实际验证；取消/迟到回复等完整门禁仍开放，见文末。
此前K49/Ud8的实机证据继续保留，只证明那个冻结版本。

## 接口和身份

`SL_IOCTL_DIAGNOSTIC_SUBMIT`（0xd1）采用固定40字节/8字节对齐结构，
C/Rust/Python同一字段：version、flags、generation、request_id、timeout_ms、
opcode、reserved、seq、action。version=1，flags/reserved/input seq=0；
generation为显式选择的精确注册实例，request_id非零；timeout_ms=1..5000；
action=1提交、2取消。仅Native WS73 profile1的0402/0403/0404/0406无参数
metadata白名单开放；其他能力不通过模拟成功或legacy fallback支持。
每个syscall仍需CAP_NET_ADMIN、原作者fd和Diagnostic所有权。

request_id由调用者预先持有。新请求在同一open file上严格增加，fd的watermark
不随结果槽淘汰、管理租约释放或controller选择清零。不同open fd是不同作者和
ID命名空间；旧generation不会跟随新的注册。继承/共享同一open description
不授予CAP，也不创建另一份作者身份。不能把本地ID当固件线上事务号。

同一保留ID且opcode/timeout一致返回原sequence，不增加命令/统计、不更新截止
时间；修改原参数EINVAL。32个结果槽有界保留，已淘汰或从未提交的较旧ID返回
ESTALE，新ID的未知取消ENOENT。这样不会因结果淘汰把重试变成第二次硬件提交。
队列/Host拒绝时rollback记录和提交统计，watermark不推进；sequence不循环复用。

提交先完成原子admission，再copyout。copyout EFAULT后保留已接受ID，即使命令
已经发出，调用者也能以同一ID/fields重试取回原seq。input seq必须重新清零；
禁止因不知道是否已接受而换新ID重发。结果继续通过原fd/generation/seq查询
104字节非消费快照。Rust/C失败不改调用者结构；Python接通同一实际共享库。
Native旧DLI_SEND_CMD直接EOPNOTSUPP，且在power sync前拒绝；profile0消费者
仍待迁移，不能以新接口存在宣称完整旧实现删除。

## 截止时间与取消

截止时间从admission计起，包含排队、USB OUT、等待回复及Host最终处理。
重试不延长，Host在开始发送时保留原absolute deadline。尚未发送的原始诊断
超时是本地结果，不虚构硬件故障；排队的typed recipe deadline仍受Host约束。
结果查询及处理Host reply先expire，迟到Complete不能复活已超时的作者结果。

取消排队命令保持其他命令FIFO；取消在途请求只将作者结果置本地ECANCELED，
保留active/reply/credits/deadline，等待真实回复或正常不确定传输超时/恢复。
不能释放回复槽让下一条同opcode请求借用迟到回复，也不产生伪造控制器Status。
已最终完成/失败的结果保持，重复取消可重试。Host自身失败返回真实本地errno，
管理撤销的排队取消使用ECANCELED，不再伪造控制器0x03 status。

## 回归与剩余验收

23项原handler/pending/queue/Host enqueue-cancel实际代码开发门禁，依赖的
lock/clock/lease/validation/usercopy是fixture；18项实际命令队列测试包含所有
ring位置删除与raw不能遮蔽recipe deadline。用户态170项Rust回归、严格clippy、
34项Python共享库/ABI回归和155项工具回归通过；40字节结构纳入canonical C/
public C/Rust/ctypes与i386 C布局比较。专用C实机probe已迁移四种metadata提交，
保持原16个结果syscall门禁；新镜像必须重新执行后才能证明当前真实WS73路径。

该开发批次尚无实际提交copyout证明，后续两类限定验收见文末。真实排队与在途取消/
迟到回复、原期限、并发/CAP/移除、完整生命周期、32位runtime及剩余legacy
DLI消费者迁移。开发fixture不替代这些实际门禁。R12/K3/U2保持OPEN；自然
启动/重枚举/消失根因与完整无人工拔插恢复、北极星7/8、socket/SSAP/安全/
Bond/Profile/Proxy及全S0–S6范围不变。继续VM-only，不安装或重启宿主内核。

首次完整内核构建（922a009）因Pin guard的as_mut分派失败，原失败log/manifest
保留；c89e961改为显式Option::as_mut借用，再重新完整构建。依赖fixture通过
不代表内核lock/Pin/并发可用，新的镜像构建和实机结果必须独立核对。


## 当前新镜像路径回归（限定通过）

[新冻结镜像证据](evidence/ws73-vm-diagnostic-admission-20261011.json)基于Linux
`c89e961b80a2` / 编译用户态 `df9cff7d750d`。完整build/image/modules和空USB
root两次加载卸载通过，配置不变；原922a009失败构建与service-bundle目录参数
传错的准备FAIL保留，不回写成功，没有把环境失败称为硬件自然故障。

新入口的四种C metadata与四次实际slkconfig均通过，独立8组USB命令/成功
Complete/数据证明；原16类结果syscall及7类实际legacy read门禁保持通过。
真实20＋2轮最长620ms、22份RX/1279 USB包零drop，普通UID1000/caps0，同
slkd PID650/start1532/bus owner；幸存g2不变、目标g1→g3，最终两只停止确认。
VM warning0/taint0/trace overrun0，13条QMP无device_del，只有一次人工IN81
错误，无host open/close/reset失败标记；host4只仍在且已释放。人工错误到新
Ready约10572.303ms，发现10秒从成功scan Complete起算，RX证据不是PHY嗅探。

[CI38089420254](https://github.com/OpenSparklink/sparklink/actions/runs/38089420254)
9作业成功，三个kernel pin均为c89e961；实际日志核对170 Rust/34 Python/155
工具与诊断原代码23项（结果12/提交11），既有security7/backend2/TX11/SSAP9/
event9、C sanitizers和历史PHY3/拒绝arm1保持。CI仅编译live C，不执行真实设备。

上述Kc89/Udf9批次只证明正常metadata与结果门禁；
**提交copyout幂等性、实际排队/在途取消、原deadline与迟到回复没有live证明**。
这些仍为开发门禁，下一批必须专门执行，不关闭R12/K3/U2或完整事务issue。
自然故障根因/自主恢复、物理xHCI警告、旧消费者删除和完整S0–S6继续OPEN。


## 实际提交copyout门禁实施与限定验收

专用C probe在MAC提交时制造全输出页只读EFAULT，在features提交时制造跨页
输出EFAULT：前36字节可写（包含offset32的seq），其余4字节只读。输入40字节
全部可读，直接ioctl采用byte buffer/memcpy，无未对齐C结构体解引用。
保留完整输入与失败输出，核对确实写入的sequence，再以同ID/fields取回seq、
等待真实结果，并三次重复提交比较完整40字节与104字节结果不变；统计只增加
一次提交/完成、pending归零、timeout不变。四种metadata正常窗口覆盖全部重试。

诊断证据format_version=2强制包含这两条admission记录；supervisor/runner拒绝
缺失、下调版本或与metadata身份/时间窗不一致。独立capture仍要求完整失败/
重试窗口恰好一个成功OUT和一个实际成功Complete，不能凭返回同seq证明未重发。
旧format1仅用于历史结果证据复核；当前执行明确要求format2。新增4项verifier
开发测试（总159），合成fixtures只证明拒绝边界，不证明实际syscall/USB行为。

Linux本轮仅修改专用selftest，生产驱动/core未改变；用户态只改测试工具及
捕获验证。已用固定新提交的新镜像执行，结果见下；实际取消、迟到回复、
原deadline、并发/移除及自然故障根因仍OPEN，不关闭整项事务/恢复issue。

### 本批冻结新镜像与证据

Linux `372d3cbcd557` / 编译用户态 `ee2793301e9a` 的
[实际证据](evidence/ws73-vm-diagnostic-copyout-20261011.json)记录两个真实提交
EFAULT：全输出只读、36字节可写前缀。输入/失败输出40字节、取回的seq、三次
同ID重复返回完整40字节及不变的104字节结果均核对；提交/完成统计各增加一次，
pending=0、timeout不变。每个完整故障/重试窗口独立USB核对恰好一次OUT及
对应成功Complete，不能只从相同seq推断没有重发。

诊断证据format2/21条记录（结果case16、admission2、身份1、phase2），实际
CLI4、独立wire8全部通过；legacy read7及真实20+2最长620ms/22份RX保持，
1279 USB包零drop。普通UID1000/caps0，同slkd PID648/start1532/bus owner，
幸存g2保持、目标g1→g3；人工错误到新Ready10798.365ms，非自然故障验收。
VM warning0/taint0/trace overrun0、13条QMP无device_del，host4只仍在且释放。

完整image/modules、空USB root两次加载卸载、默认bundle重新构建通过；
[CI38090373115](https://github.com/OpenSparklink/sparklink/actions/runs/38090373115)
9作业成功，实际日志170 Rust/34 Python/159工具/诊断fixture23。CI只编译live
C，不执行硬件；开发fixture依赖与旧失败记录保留。生产内核与用户态分别仍为
Kc89/Udf9。本批没有物理拔插或宿主原生试验。

**通过范围仅为两类顺序metadata提交copyout与同ID重试**。实际淘汰旧ID不重发、
排队/在途取消和迟到回复、原deadline、并发/CAP/完整移除/32位runtime、旧
DLI消费者删除仍需验收，R12/K3/U2及完整事务issue保持OPEN。北极星7/8、
自然根因/完整自主恢复、socket/SSAP/安全/Bond/Profile/Proxy及全S0–S6不缩减。


## 实际结果槽淘汰门禁实施与限定验收

独立Diagnostic作者fd在原foreign-author EPERM核对后，顺序完成33次真实MAC
只读查询，超过32槽保留界限；每次保存输入/输出40字节、完整结果104字节、
序号、时间窗与提交/完成/timeout/pending统计。然后旧ID1三次重试必须ESTALE，
旧seq结果必须ENOENT且输入不变；边界ID2仍返回原seq和完整原结果。
拒绝和保留重试后的100ms观察内，统计不得变化、USB不得产生任何命令/回复。
不注入成功、不重置设备。原作者fd继续保留至退役ENODEV，16个结果case不删。

当前证据format3强制copyout与eviction门禁，55条记录（原21加33填充与1拒绝窗口）；
验证器要求33个连续填充记录位于foreign-author检查之后。独立捕获逐窗口核对
唯一OUT/成功Complete，整个填充范围连查询间隙也拒绝额外命令/回复，拒绝范围
限定该controller，不影响其他设备。历史format1/2仅复核各自旧证据。
新增6项开发验证用例（工具165、诊断19）通过，但合成fixture不代表实际淘汰。
本批仅专用selftest/工具；生产Kc89/Udf9保持。新镜像结果见下；取消/迟到回复/
原期限、并发/CAP/移除、旧调用者迁移与自然恢复根因仍需独立验收。

### 本批实际槽替换、旧ID拒绝与独立命令证据

[冻结镜像证据](evidence/ws73-vm-diagnostic-eviction-20261011.json)基于K78e729c06a5e/
编译U2dfd6bd09e7b。第二作者fd的ID1..33对应seq5..37，33次实际MAC查询均
完成、返回当前地址，提交/完成各+1。第二fd的ID1在原作者ID1仍保留时有自己
的新seq及一次真实OUT，证明本批命名空间隔离；原作者结果事先对该fd拒EPERM。

33次完成后，旧ID1三次ESTALE/旧seq ENOENT，输入40/104字节保持；边界ID2
仍返回原seq6、完整40字节admission及104字节结果。统计完全不变，pending=0；
100.261ms拒绝观察窗口内该controller没有OUT或DLI回复。每次填充窗口独立
核对一条命令/成功Complete，整个33次范围含间隙也没有额外命令或回复。
原fd此时结果也已淘汰，仍保留至generation退役并优先返回ENODEV。

format3/55条记录、33填充+1拒绝窗口、copyout2/result16/CLI4、41组实际
命令/回复通过；read7与真实20+2最长621ms/22份RX/1411 USB零drop保持。
普通UID1000/caps0、同slkd PID654/start1557/bus owner、幸存g2保持/目标g1→g3；
人工错误至新Ready10187.785ms，未作自然恢复或物理拔插验收。warning0/taint0/
trace overrun0、13条QMP无device_del、host4只仍在且释放。

[CI38091465529](https://github.com/OpenSparklink/sparklink/actions/runs/38091465529)
9作业成功，实际日志170 Rust/34 Python/165工具/诊断fixture23；完整image/
modules、空USB root两次加载卸载及默认bundle通过。生产Kc89/Udf9未变。
**验收只覆盖顺序、单controller、第二作者metadata槽替换与上述无重发窗口**。
真实排队/在途取消、迟到回复/原期限、并发/CAP/完整移除/32位runtime、旧DLI
调用者及共享队列删除仍OPEN；自然根因/自主恢复、北极星7/8和全S0–S6不缩减。
