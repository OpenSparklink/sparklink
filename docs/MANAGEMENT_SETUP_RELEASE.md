# 未触及 radio policy 的 Setup 租约释放

源码实现：Linux `f822db7756d7c99eb6a7d0e1e9e32c513e91ad71`。当前限定真实资格仍为Kf5f83d7eb970；
本批新镜像和实际release/fd-close门禁尚待执行，不引用历史镜像作证明。

## 缺陷与修复边界

历史[失败记录](evidence/ws73-vm-uninitialized-managed-release-failed-20261011.json)
捕获未配置广播handle0的Setup租约release发出bare stop，真实Complete状态
0x1e后EIO退役。参考Host将0x1e定义为unknown advertising identifier，与捕获相符；
此解释不等于固件全根因闭合，自然启动/重枚举/消失RCA及完整恢复仍OPEN。

修复复用每设备Host已有状态：quiet，无fault/recipe/revocation，两个radio状态
Unknown且未初始化，policy cookies为0、没有任何保留的discovery操作。只有
全部成立才允许Managed租约直接Free；不添加第二套dirty状态，不设置Off或Ready。
Diagnostic元数据查询可能增加next_cookie，不能以cookie计数为1来判断policy历史。
已有确认Off使用原屏障；任何提交、取消、部分初始化、在途/待回复、错误或unknown
历史都仍需真实cleanup/退役。非零Complete和原errno不能改成成功。

同一revoke_management在显式release和PinnedDrop最后一个file reference关闭时
执行，仍持管理mutex，并检查Runtime存活及Host fault。dup持有同一File ownership，
关闭一个引用不能释放租约，最后引用关闭才撤销；独立观察fd不持有该租约。

## 开发门禁与专用实机门禁

10项selftest编译实际Host predicates、core快速释放block和真实operation/queue/
management模块；锁/周围driver依赖为fixture，不宣称VFS或硬件验收。覆盖
Unknown/Off/On矩阵、所有operation槽和terminal/cancel历史、cookie/recipe/
revocation/active/reply/queue、错误保留、token身份及observer权限。

专用C selftest只由明确VM工具启动，两只真实Setup各3项：显式release（错误token
先拒EPERM）、最后fd close、dup后第一次close仍Held及最后close Free。
独立观察完整snapshot/radio/lease与peer；每项保留完整UAPI字节与有界quiet时间。
严格verifier核对6项顺序、身份/字节、token隐藏、Unknown与Setup不变，USB捕获
包括每项间隙和两设备，整个probe窗口不得出现任何DLI command/Complete/failure。
测试不编入生产success路径。

可复现：先准备新签名scratch VM，run添加`--setup-release-verify --fault-recovery`。
本门禁可与独立active-deadline模式或原完整诊断模式分别结合；每轮都须普通用户
真实20+2、同RF slkd/peer隔离及独立capture。partial-init cleanup、held transport
fd-close/drain、并发/权限/32-bit和自然恢复不因本门禁通过而完成。

## 未决条件

新内核实机资格待执行；完整事件迁移/旧UAPI删除、C通用固件ACK/短传输、安全/
连接socket/SSAP/Bond/Profile、四设备/Native/Proxy/PM/sandbox及全部S0–S6保持。
VM-only，不改变host内核/服务/权限，不使用人工拔插作为恢复，不关闭整项issue。


首轮[失败证据](evidence/ws73-vm-setup-release-record-writer-failed-20261011.json)
发生于测试progress写入第二份metadata：误用one-shot握手writer，C probe尚未启动，
没有实机release/fd-close/RF资格。原RUNNING progress与terminal FAIL均保留；
修为原子replace并补实际重复文件写入/FAIL持久化与one-shot拒绝回归，再跑新VM。
