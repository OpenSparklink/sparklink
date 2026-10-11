# 未触及 radio policy 的 Setup 租约释放

源码实现：Linux `f822db7756d7c99eb6a7d0e1e9e32c513e91ad71`。本批新镜像K`f822db7756d7`／编译U`ccb3d34ae1bc`的
[两个独立新VM证据](evidence/ws73-vm-setup-release-20261011.json)已封存；
资格仅限未触及policy的Setup release/last-file/dup，不引用历史镜像代替新源码。

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

未触及policy的Setup限定实机门禁通过；完整事件迁移/旧UAPI删除、C通用固件ACK/短传输、安全/
连接socket/SSAP/Bond/Profile、四设备/Native/Proxy/PM/sandbox及全部S0–S6保持。
VM-only，不改变host内核/服务/权限，不使用人工拔插作为恢复，不关闭整项issue。


首轮[失败证据](evidence/ws73-vm-setup-release-record-writer-failed-20261011.json)
发生于测试progress写入第二份metadata：误用one-shot握手writer，C probe尚未启动，
没有实机release/fd-close/RF资格。原RUNNING progress与terminal FAIL均保留；
修为原子replace并补实际重复文件写入/FAIL持久化与one-shot拒绝回归，再跑新VM。


## Setup 租约释放新镜像限定通过，完整生命周期仍 OPEN

K`f822db7756d7`／编译U`ccb3d34ae1bc`的[证据](evidence/ws73-vm-setup-release-20261011.json)
证明两个独立新VM各6项实际release/last-file/dup门禁：两只分别显式release前
错误token EPERM，最后fd close，dup第一次close仍Held/末引用close Free；独立
observer完整snapshot/radio/peer/generation保持Setup/Unknown。整个probe窗口
含间隙及两设备零DLI command/Complete/failure，不假Off/Ready，不归一化非零回复。
本批复用唯一Host已有policy状态，没有额外dirty authority；有操作/取消/部分初始化/
在途/错误历史仍走真实cleanup。完整锁/并发、held transport fd-close和unknown
cleanup不因此通过完成；初始0x1e失败和首轮测试记录writer失败均保留原证据。

新image/私有签名modules/空USBsmoke通过；编译器warning0，GNU make仍记录
一次jobserver警告。每新VM随后普通UID1000/caps0真实20+2，最长
622/769ms，各自同RF slkd/peer隔离；两capture各
1345/1431 USB、22RX/零drop、guest warning0/taint0/traceoverrun0，host四只释放在位。
原500ms在途超时/实际Runtime取消暂留回复/driver现有稳定预算归零，另一VM原
格式7完整诊断63记录/50proof/46wire、read7/result16/copyout2/poll3/淘汰33/
CLI4/旧注册27拒绝及queued期限保持；hold发生在主RF daemon前，同daemon期间
hold未验收。USB/HCC/DLI不是独立PHY嗅探，原生宿主对照未执行，VM-only保持。
[精确源码CI38108517103](https://github.com/OpenSparklink/sparklink/actions/runs/38108517103)
九作业成功，实际170 Rust/34 Python/228工具/32期限及10管理源码门禁。

开放issue集合重新核对为28项（Linux19、用户态9），此前近期批量更新列表漏了
K11方言/能力与K13差异/来源审查，本批补齐，原checklist不替换。K11的descriptor/
来源/caps/limits/quirks/不同firmware fallback及不支持设备行为仍逐项待验，不能
使用默认255/8或参考单链路限制作全设备能力。K13的字段级来源矩阵、去敏样本/
golden许可、最小基准抓包/连接ACB与pairing relay仍独立验收；FW111 combined
固定hash不证明board/运行时版本资格，原016c00a100查询不能唯一识别110/111。

下一步C通用固件拒绝短传输、截短/错opcode/非零最终ACK，并独立backend资格；
部分初始化真实cleanup/held fd-close、自然启动/重枚举/消失RCA、无人工拔插恢复
与历史物理xHCI warning继续OPEN。随后独立事件调用者迁移、shared ring/fallback/
旧UAPI删除、socket/SSAP/每连接安全/Agent/Bond/Profile、四设备两组/Native/Proxy/
PM/sandbox/发布及完整S0–S6保持，北极星7/8，整项不关闭，draft不合并。
