# Native metadata 诊断请求身份、截止时间与取消

2026-10-11，Linux `c89e961b80a2b99922ddd0715590c01edfe39c88`；未发布UAPI同步迁移，不保留Native双提交入口。
这是一项实现/开发门禁记录，新的实际syscall故障和迟到回复门禁尚未验收。
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

尚需实际提交只读/部分copyout失败及重复ID的单次wire证明，真实排队与在途取消/
迟到回复、原期限、并发/CAP/移除、完整生命周期、32位runtime及剩余legacy
DLI消费者迁移。开发fixture不替代这些实际门禁。R12/K3/U2保持OPEN；自然
启动/重枚举/消失根因与完整无人工拔插恢复、北极星7/8、socket/SSAP/安全/
Bond/Profile/Proxy及全S0–S6范围不变。继续VM-only，不安装或重启宿主内核。

首次完整内核构建（922a009）因Pin guard的as_mut分派失败，原失败log/manifest
保留；c89e961改为显式Option::as_mut借用，再重新完整构建。依赖fixture通过
不代表内核lock/Pin/并发可用，新的镜像构建和实机结果必须独立核对。
