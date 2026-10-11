当前修复版实机回归更新：实际kernel d227b8a37d96、编译服务/工具195a936a0643
在正常VM74完成原无连接路径SIGKILL137／两条真实STOP／Free-Off-Ready／
原generation接任／四项旧初始化凭据拒绝且接任阶段零设备命令，再完成同一
接任者随机标识真实RF20+guest-only退役重注册RF2。1293包/零drop/taint0/
QEMU0，父/guest原proof在生产者终止后独立重算，冻结输入再次核对。完整
新kernel+modules、八GPL exports/产物检查及签名空USB VM引导均通过；
维护VM21/正常74。先前首构建/路径错误/CI8绿1红均保留，匹配195a936a0643
的CI38181871353为9/9。此为新生产代码保留北极星路径的回归，**没有发生
真实连接outcome**，不覆盖live copyout race、连接teardown或S4互通。

[当前原证据](evidence/ws73-native-link-foundation-rf-regression-20261012.json)
SHA256 `599b7273c22cfc54641bbd849bd9f3d20a58b4936e250c12e897a0113147fbd0`。
下一主功能仍为typed27字节Create/3字节Disconnect、命令接受与异步outcome
分别关联同一Runtime operation、有限超时/取消/迟到事件和连接清理，再真实
双设备连接/SSAP数据。完整原S0–S6/28项与自动恢复/根因仍开放。

当前修复更新：Linux `d227b8a37d96334ac465eac83cc3d52959863845` 已补
copyout后的Host/fault/quiet/link重新核对，按Host→gate持锁提交；实际提取
commit block覆盖link/active reply/fault/retirement/成功五种情况，候选被拒绝
不授权、不消耗counter，累计35项源码回归通过。首444450231937完整内核/
module构建已终态通过，原产物保留；修复版尚待新构建/VM。以下“窗口待修复”
是发现时历史，当前源码已修，不能外推运行内核已验收。用户态检查初CI因三个
kernel checkout仍固定4ee、缺新增selftest而失败，原8绿/1红记录保留；三个
checkout全部固定到d227b8a37d96，不跳过新门禁。Native连接/SSAP仍未互通。

# S4 原生物理连接生命周期基础：当前范围

2026-10-12，本轮主功能为真实 Native WS73连接/SSAP。当前先接通 driver RX 到
每 registration Host 的物理链路义务，避免尚未实现的连接清理被广播/扫描 Off
冒充。主动连接、断开、SSAP和安全尚未接通，不能将本基础或单元测试算互通。

## 实际生产路径变化

Linux `44445023193775fd340a9669c36d5368619099df` 已签名推送。

- WS73 driver将标准编号 `0x0015/0x0005` 及其 `0x1401/0x1405` 方言映射为
  connected/disconnected outcome事实；Status/Complete不参与映射。原完整
  event body（包含连接扩展字节）仍进入原事件日志，vendor编号留在driver。
- 新内部 `sparklink_native_link_event` 在同一次 ingress 中更新该 Runtime
  Host 的链路义务并保留完整日志。退休/generation/profile检查先于状态更新；
  Host → scheduling gate → log锁顺序，guard逆序释放。没有分配、I/O、指针保留
  或连接命令权限。日志满/overflow不会撤销已经观察到的物理义务。
- 链路按实际handle/role/opaque地址类型/地址跟踪。失败 outcome不建立或移除
  链路；错误handle断开不影响另一只；重复相同建立事件幂等。冲突/异常成功
  字段或容量溢出保持uncertain，后续任意断开不能洗掉它，直到该Runtime退休。
  容量16是安全存储上限，不是固件连接能力。地址类型不套Bluetooth枚举，
  0..255保留；T/XS 10003-2025的标识类别与WS73方言也不自动映射。
- management预检查拒绝活动/uncertain链接；revoke入口及实际revocation
  settlement均检查义务，防止准备radio cleanup期间新事件到达后仍宣布Free。
  当前没有Native连接teardown，release遇到这类义务返回不支持并Faulted，
  不确认Off、不补造disconnect、不强行重授管理权。既有无连接WS73发现路径
  的命令/权限/参数和超时不改变。

## 尚未通过的两阶段 acquisition 与实机范围

本轮进一步源码复核发现：acquire当前先检查Host，再进行可睡眠用户copyout，
commit只复核retirement。连接可以在copyout期间到达；commit还必须按
Host → scheduling gate顺序再次核对quiet和链路义务，失败时返回Busy、
不提交候选lease或消耗counter。这个窗口尚待补上，不能声称完整管理权原子
接任。当前独立新目录构建的源码被冻结在444450231937；构建终止/完成前不改
Kernel输入，之后补该修复、重新构建并验收。此前已验证Kernel060/源码4ee及
RF/FD/强杀证据继续保存，新源码不自动继承整个实机验收。

当前直接源码边界验证：

- 实际Host/revoke决策与链路模型34项Rust测试，包括cleanup期间新连接；
- 实际atomic ingress及同一链路模型10项，覆盖旧generation/错误profile/
  退休/oversize/管理事件、同行隔离、原始body、日志失败和逆序unlock；
- 实际WS73 DLI/方言归一化 ASan/UBSan 120165 checks，零失败。初次sandbox
  的LeakSanitizer被ptrace阻止，普通测试进程重跑通过，没有关闭sanitizer；
- 原诊断pending/旧TX边界回归通过。早期测试fixture因调用私有提取函数编译
  失败，保留日志后在fixture模块内加wrapper，未修改实际publisher body。

上述locks/owner lookup/log及transport依赖有专用fixture，是源码支持证据；
不是实际ioctl、运行内核、物理连接或RF证明。构建检查已要求新增GPL export，
CI纳入实际ingress提取测试；旧七export产物不能被新工具误认作新连接基础。

## 下一步依赖

修复copyout后commit窗口并完成新内核/模块构建与VM验证；保留真实RF20+2。
随后接通Native typed连接请求、driver-owned 27字节CreateConnection及3字节
Disconnect编码、独立operation ID/result、Status acceptance和异步outcome。
Queued/OnWire/AwaitingOutcome/Connected/Disconnecting/超时和迟到事件均须
属于同一每设备Runtime；取消/最后fd/release不能丢弃在途预留或把未知当Idle。
对照本地libws73-usb、communication_nearlink_service及T/XS10003-2025
8.4.1/9.1.14/9.1.5，独立实现字段事实，不复用旧6字节地址helper。

连接/断开实机闭环后推进SSAP数据与Profile、安全/Bond。完整S0–S6、原28项
issues、事件/权限/Managed全矩阵、四设备默认并行、自然故障根因和非人工
有限恢复继续开放；不得提前关闭整项或用本基础代替原互通验收。VM-only。
