# 2026-10-14 进度整理前的历史快照

这是历史入口，不是当前计划或镜像资格。此前逐批进度、失败和限定结果完整保留于：

- [当时的资格记录](https://github.com/OpenSparklink/sparklink/blob/0610519c66a9a3684689d508da772c4a1689c26f/project/current-capabilities.md)，SHA256 `9907c3d3ad836f96e23f8524dbe691eff62058c9b3a39d7909cd2669bb399e68`。
- [当时的实施进度与完整计划](https://github.com/OpenSparklink/sparklink/blob/0610519c66a9a3684689d508da772c4a1689c26f/project/implementation-plan.md)，SHA256 `1f4c883daa1b4dddc43c599778ec281435b617988b898cda02a94f682cea5b8e`。
- [逐批证据入口](../../docs/evidence/index.md)：每份记录的源码身份、失败、反例和限定范围继续有效。

重排不会把旧 PASS 升级为当前镜像资格。当前事实只看
[唯一资格入口](../../project/current-capabilities.md)，下一步只看
[唯一实施计划](../../project/implementation-plan.md)。
首次启动 panic、最后回复关闭丢弃、warm reset/重枚举失败及自然恢复未决均保留；
人工、hub、QMP 或注入不构成自然恢复通过。

## 2026-10-15 实施计划开头的历史进展归档

本节从575ba337c05b09b6c3e96f4182ffcf7ffb6b466c的唯一实施计划移出，
保留当时提交身份、失败与限定资格；不是当前实施顺序或当前镜像资格。
当前计划仍以project/implementation-plan.md为唯一权威，资格以CURRENT_CAPABILITIES为准。

本批有限退出已取得：准确 K `eff62088fe57` / 编译与封存工具 U `2cd55722d483`，
唯一物理Session撤权保留、后继epoch拒绝、000e/0011只结算旧义务；准确严格构建、
无设备/Virtual VM及CI通过。实机两角色安装各9条relay/Complete/peer RX、真实角色
命令接受与0011；8次应用回复中4次安装前、4次控制器报告加密后。另15组保持回归、
136次业务/32拒绝/严格fd及真实pool5恢复，6组Managed release/最后fd/dup同行隔离
均通过。[准确提交及完整限定](../../docs/evidence/session-owner-retention-20261015.json)。

这不是Agent批准、认证身份/可信Grant、Bond或独立空口密码证明。44项实际Native、
68项Host和23项生产纯转换的限定通过与实机分列；旧f5丢表引用反例仅离线复现。
原337的Kani1681检查仍unsupported，生产纯源码hash未变不等于eff620集成已证明。
6组Managed数据前缀撤权不是安全安装Status/0011的受控交错，后者仍并行补齐。

下一有限退出沿用唯一机制接Agent/method/调用者策略：单请求取消已限定实机通过，
先完成绝对原期限ABI的准确新VM门禁，随后接线Agent；禁止用整个Managed租约撤销来取消一个应用；保留物理Session和已提交义务，
原期限覆盖Agent等待及内核工作。接线取得真实批准/拒绝、原期限、调用者退出与
双设备应用回复证据，再推进认证级别/Bond/重连。只设置本批相关门禁，不等待全部
控制面竞争；长包/credit、动态通道、四设备两组和SSAP通知/指示继续并行。
完整原S0–S6与默认未支持入口NotSupported保持。

旧K494/Ud744和Ue2a的准确证据保留如下，不因新实现自动继承：

1. 保留K494/Ud744的136轮/32拒绝/两角色严格fd与真实pool5恢复资格；新增
   K494/Ue2a六组begun-PDU Managed release/最后控制File/dup撤权子门禁、16次
   撤权前业务往返。[六组证据](../../docs/evidence/managed-prefix-withdrawal-20261015.json)
   不补发未完成PDU，不将撤权后同行扫描说成独立业务交付，不升级完整Grant。
2. 安全主线本批取得[实际固件表缺项因果证据](../../docs/evidence/relay-firmware-table-cause-20261015.json)：
   原版111缺147/1ff包描述与RX分派；补双方包描述和接收端分派的三行RAM对照，
   同一生产Session/credit/ticket完成真实拒绝交付，少接收端包描述则失败。
   两端已恢复原版并核对实际上传，原版仍失败。这个牺牲146的诊断不是生产修复。
   随后保留44/60所有旧表项的连续扩展方案在boot下载失败，尚未执行新Runtime；
   [失败与公开输出入口退役](../../docs/evidence/relay-extension-boot-failure-20261015.json)保留，
   端口1-2.1.2原版恢复未验证。用户此前要求忽略该口；后续再次人工重插后2/3有限业务及45/37保持回归通过，
   历史未恢复状态不是当前Ready结论，非人工恢复与自然RCA仍未闭合。当前不再请求人工处理，
   保留历史失败，不豁免四设备或自然恢复门禁；不得把该条件变成整个goal阻塞。
   不再重试连续填充镜像。分段加载或启动初始化修正须先明确下载器工作区/加载边界、
   段身份和可复现恢复，再作独立固件版本的实际回归，默认不改原blob。
   安全正向链路继续沿原版支持的13X消息、唯一Session/credit/ticket、实际Agent批准、
   角色绑定安装和加密业务推进；原版拒绝、反向角色、修正版与所有原S5门禁仍开放。
   不让固件拒绝缺项或控制竞争全集阻挡数据/SSAP纵向开发，也不另造Engine。

3. 数据面已取得两角色begun期间直接disconnect子门禁，保持双方租约，真实双端Down、
   旧fd ESTALE/ERR/HUP和对端实际扫描；4次前置应用往返，未完成PDU零交付。
   [证据](../../docs/evidence/begun-link-down-20261015.json)绑定K494/Ue2a/工具2d6c250，
   不继承原Ud744全部长度资格。本批再取得两角色原5秒PDU期限子门禁：独立8秒
   QEMU夹具实际hold成功IN81，真实pool5/1270字节前缀，原准入后5.006/5.009秒
   ETIMEDOUT、原回复释放/五条NOCP后旧fd仍失败，实际Down清理/peer扫描保持。
   [准确证据及首轮时钟验证失败](../../docs/evidence/original-pdu-deadline-20261015.json)
   保留；跨时钟用guest确认收据，原2秒夹具未改。失败后Binding查询拒绝，不能把
   USB/NOCP计数代替失败后ledger读回或完整守恒/复用证明。
   上述撤权/直接Down/期限的限定门禁已经取得，不再追加全部控制竞争作为前置。
   唯一安全机制的首个真实协商子门禁现由K1cf/U02ac接通：SDK111支持13X、同一
   物理Session/relay转换/命令credit/提交票据、显式管理批准和完整身份/epoch。
   候选proof现已在K415/U376实测；后续继续Agent/实际密钥安装/加密与peer业务。默认未批准
   继续拒绝，不能以capability协商冒充配对或认证，不新增另一Engine。
   原期限/撤权/Down到最终提交、late/duplicate NOCP与handle复用继续按本次性质组合
   建模/实测，不阻塞动态通道、四设备两组、唯一用户态SSAP通知/指示/ACK纵向开发。
4. 本批工具511检查、跨时钟反例与两份新期限捕获封存重放，及准确VM正反证据通过限定门禁；诊断265实际codec Clang sanitizer
   533352项IO检查不等于形式化证明或固件ABI。原C consent311仍排除锁/引用/Runtime/
   HCD/NOCP；Kani unsupported/timeout/展开不全继续NOT_PROVEN，不抑制警告换PASS。
5. 严格区分staged文件、实际USB上传、执行、控制器Complete、peer协议和应用处理。
   固件身份以实际上传核对；仍不构成执行认证。SDK archive表、OHOS及lib版本分别记录，
   不由任一推定固件支持。本批已用固定官方vendor工具解码关键路径；通用Ghidra坏指令输出仍保留为未反编译，不能当证明。
6. 完整S0–S6、19WP、10FV、12DG、预算及原scope不变；goal当前API为active。
   自然RCA/非人工恢复、部分初始化/事件迁移/旧代码整改持续并行；UserHost P4规划，
   不把诊断reset/QMP/注入/hub切电算自然恢复。局部通过不关闭整项。

