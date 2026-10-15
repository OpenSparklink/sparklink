# 当前能力与资格

本页是唯一当前资格入口；目标架构见 [ARCHITECTURE](architecture.md)，依赖与完整
退出条件见 [IMPLEMENTATION_PLAN](implementation-plan.md)。历史逐轮资格、失败及
反例保留于[历史快照](../history/architecture/progress-snapshots-20261014.md)和
[证据索引](../docs/evidence/index.md)，不能继承为新镜像 PASS。

## 当前实验失败与设备状态（2026-10-15）

保留全部旧表项的连续RAM镜像实验**未通过boot下载**：前5段USB OUT完成后，
地址`0x420000`的32KiB数据未收到boot ACK，后续枚举失败。它没有完成整镜像上传，
没有新Ready或relay资格。公开工具已在`91a5bfb792e6ccdb347137c7e06bf7eb4e336e17`
撤回固件输出入口，仅生成退役审计报告，`safe_to_upload=false`。
[准确失败、退役与恢复缺口](../docs/evidence/relay-extension-boot-failure-20261015.json)。

受影响端口`1-2.1.2`的原版111恢复尚未验证；host缓存USB节点不代表枚举/Ready。
用户现已明确要求忽略该端口：当前不操作、不恢复、不请求人工处理第2只，
保留原失败及恢复未验证记录。继续第1/4只VM测试；四设备完整门禁仍未通过，未被豁免。其他设备不自动推定Ready，没有安装宿主实验内核。
运行态BSS/栈/池边界算术不能证明boot下载器工作区安全，连续填充方案不再重试。
原始combined111文件与生产Runtime未改；以下历史准确镜像的资格保留，不升级为本次失败镜像资格。

## 当前未认证候选密钥 proof 与业务回归（2026-10-15）

准确实测生产内核 K `41572aaf736df897914a9227c81ba92fa0df9002`，编译用户态与
封存guest工具 U `37666749f57947855ab17382d685d65f165b7d70`。K `8117cb56e2ef`
只改注释；外层只读证据检查器 `89a6659441ef`新增禁止实际安装/加密的核对，并重放
原捕获，不能将后续HEAD重新标成实测镜像。

**已实现**：同一物理Session、relay转换、命令credit及最终提交票据上，显式模式2
复用原Managed File/CAP_NET_ADMIN/身份/epoch校验。真实CSPRNG生成鲜活P256与nonce，
执行真实点检查、ECDH、CMAC及peer proof；密码工作在IRQ/Host/gate锁外，回填重新
核对job/身份/原期限。取消、断链或到期不能通过迟到密码结果创建提交，也不消除
已提交物理义务。材料不导出，无测试密钥降级；默认Pair/D-Bus仍NotSupported。

**实机限定通过**：第1/4只交换G/T角色，两轮各9条134..142消息，逐条核对真实1812、
匹配Complete及对端0014 RX。G发134/136/139/141，T发135/137/138/13a/142；T137真实
Complete后才发送138。两端state8仅在peer proof验证和本地实际Complete清账后发布；
原5秒总期限内29.008/29.465ms完成。观察到两轮四公钥、四nonce各不相同。
每轮前后4次UID1000/caps0随机应用校验与回复，共8次，保持Session/租约/Ready，
显式双端Down及同行真实扫描成功。非法身份/字段、其他File、降权继承原File及同
lifetime重启均拒绝。这是独立Managed实验，未运行slkd，不声称daemon崩溃存活。

**资格边界**：已知固定offer、无MITM/无Bond/无入口方法；state8是**未认证候选**，
不是Agent批准、Paired、可信身份、实际安装、Encrypted或Bond。两只相同Native实现
互测不能证明标准/第三方互通。没有1c03/1c05、LTK请求或加密成功事件，前后业务为
明文；原版147/1ff缺项仍未修复。当前不修改原版111，不进行派生固件或hub操作。

**离线与形式化分开**：实际relay15、Host68、Cargo222、跨语言38、工具516及严格
clippy/内核构建通过。实际内核密码VM另验证P256/CMAC及独立OpenSSL toy派生/proof
向量（a7c源码/1cf启动内核、无USB、专用测试模块taint4096）；它不是实机配对或标准
向量。新Kani直接验证准确415生产转换的T侧job撤销/到期与旧物理义务；1110项生成
检查无失败，但工具unsupported使结果仍为**NOT_PROVEN_UNSUPPORTED**。仅queue2、
unwind80、一个70字节公钥输入，排除密码数学、真实锁/引用/USB排空及完整九消息协议。
不把历史Kani/CBMC标量证明升级为当前完整协议证明。

**原路径新镜像回归通过**：11组共136次真实随机业务往返、32次超限拒绝、两角色严格
最后fd退出；实际发现/连接/SSAP ExchangeInfo、单值读写、UUID及发现保持。应用长度
61、248、249、250、253、254、255、1024、2042重新通过；含32条2042字节burst。
两角色真实pool5耗尽、新拒绝增量26/25、NOCP后继续提交，最终债务归零，每角色每端
206次提交/NOCP。旧模式1也在同一新镜像交换角色重新通过134/135与另8次前后业务。
136、模式2的8次及模式1的8次分别记账，未完成PDU不算交付。所有物理捕获丢失0、
VM taint0。[准确源码、USB坐标、范围及未决](../docs/evidence/security-key-agreement-20261015.json)。

下一安全子门禁为同一机制的Agent/method策略、角色绑定实际1c03/1c05安装与0011，
再以加密后对端应用校验回复验收；不能由候选proof自动获得可信Grant。新relay受控
撤权/Down/原期限与实际提交交错仍缺，不继承旧K494资格。动态通道、四设备及唯一
用户态SSAP通知/指示继续并行，不等待控制面竞争全集。
历史K1cf/U02ac受限能力交换保留[原准确报告](../docs/evidence/security-capabilities-20261015.json)。

## 保留的先前子资格（准确旧镜像）

以下先前生产内核为 K `49467d4df595f8988a7ad6310b53932f37d68283`；编译服务
U `e2a0139ff3ccbccb51f5a8606deda5a0d43688c3`，公开冷加载核对工具为
`86e8cd81f4d18b4a26fcfca8d06832c38927f6e8`。该历史子资格不自动升级为当前415镜像。

- **实机限定通过**：Managed release／最后控制File关闭／dup最终引用释放，各两侧
  共六组。在2042字节业务PDU实际已提交6片、1524字节后撤权，返回后无新USB提交；
  每组观察2条迟到NOCP、阻塞者EACCES/ERR/HUP、新lease不复活旧fd，同行租约、Ready
  与实际扫描保留。撤权前共16次真实随机业务往返；六个未完成PDU各为**零次**业务往返。
  [六组准确证据与限制](../docs/evidence/managed-prefix-withdrawal-20261015.json)。
- **固件缺项因果证据已取得，原版交付仍失败**：官方vendor objdump与5632字节实际
  boot代码读取核对，定位原版111的44项包描述表及另一张RX分派表均缺147/1ff。
  在独立RAM固件实验中，双方包描述及接收端分派共三行替换后，现有生产K494/Ue2a
  Session/credit/ticket发出的真实`1ff/02`到达对端，参考Host返回真实PAIR_REJECT；
  缺接收端包描述的区分组合仍失败。两次正向组合后均恢复原版，逐字节核对两端实际
  上传；原版再次缺包。[因果对照、源码映射及恢复](../docs/evidence/relay-firmware-table-cause-20261015.json)。
  **这不是原版111修复或批准配对资格**：实验刻意替换现有146，不能发布或自动改blob；
  仅Native responder/reference initiator角色。原版支持边界、保留全部旧能力的修正、
  Agent/批准/可信安装/加密/Bond及反向角色仍缺。此前隔离133对照保留为历史证据。
- **真实断链子门禁通过**：K494/编译Ue2a，工具`2d6c250`，第1/4只交换断链发起方。
  各自2042字节PDU已实际提交7片1778字节／6片1524字节时，保持双方Managed租约，
  执行绑定lifetime的Disconnect；两端真实Down、阻塞RX和旧fd的ESTALE/ERR/HUP、
  对端原generation/租约及真实扫描均核对通过。此前共4次随机应用往返，未完成PDU
  各为零次应用往返。[准确源码、封存重放与边界](../docs/evidence/begun-link-down-20261015.json)。
  这是直接断链，与六组撤权分开；不证明精确提交屏障、原期限、NOCP复用或独立同行业务链路。
- **原5秒期限子门禁通过**：K494/编译Ue2a，工具`eb4dffa`，独立8秒有界QEMU夹具。
  第1/4只交换源端：2042字节业务PDU实际提交5片1270字节，普通用户只读快照确认
  outstanding=connection_debt=capacity=5；阻塞RX分别在原准入后5.006/5.009秒返回
  ETIMEDOUT。显式释放的真实IN81回复与原URB hash/长度一致，随后五条NOCP到达；
  旧fd始终ENOTCONN/ERR/HUP，双方管理租约保持，实际清理Down和peer扫描通过。
  [期限、真实回复、首轮失败与范围](../docs/evidence/original-pdu-deadline-20261015.json)。
  前置共4次随机应用往返；两个未完成PDU各零次应用往返。首轮跨宿主/guest墙钟
  比较被判失败，修复后用新guest确认收据重新实测，不升级旧记录。
  Session失败后原只读Binding查询按契约拒绝，故不宣称本门禁直接读回了失败后的
  全部credit债务；完整守恒、重复/迟到NOCP复用和精确提交屏障仍缺。QMP延迟不是自然恢复。
- **离线与形式化分开**：本批`eb4dffa`的511检查通过；此前工具`2d6c250`的505检查通过，`bd84733`另加入Down类型/数量负向核对并重放两份原捕获；此前502工具检查通过（包含失败方案退役CLI负向回归）；只读READM核对工具3e3e973的历史结果保留；诊断265的实际codec在Clang sanitizer下
  533352项synthetic IO检查通过。无新增完整安全证明；原consent311仍只限标量，
  Kani unsupported/timeout及旧NOCP复用反例保持未证明。

撤权时间仅由syscall前后区间限定，不宣称精确观察内核线性化瞬间；未覆盖所有在途提交、
完整期限组合、完整断链提交竞态、重复NOCP或handle复用。同行扫描不等于另一独立业务链路仍通信。
完整Grant、S5、安全恢复及整项issues继续开放。下面136轮资格仍绑定原U d744，不能
因工具提交或本批16轮自动升级为U e2a的全部长度/压力资格。

## 准确源码与范围

原长度/压力资格镜像 K `49467d4df595f8988a7ad6310b53932f37d68283`／编译服务 U `d74421c210eeb1b706dbd90f3500442e28a214dc`。
原104轮全部已取得长度点及32超限拒绝重新回归，另32轮2042字节burst，共136轮
真实对端随机序号/载荷校验与回复；严格fd退出两角色及真实SSAP/发现/连接保持。
[准确源码、只读预算、两端时间线与限定门禁](../docs/evidence/tx-budget-observation-20261015.json)。

新增授权64字节TX_STATUS：同一锁序观察软件队列、Session在途PDU及Runtime ACB
债务，不申请/归还credit。burst两角色都出现outstanding=connection_debt=capacity=5
和新池满拒绝；源端计数增量29/30，随后观察NOCP与新的USB提交，最终债务归零。
每角色两端分别206包真实提交/NOCP（包括协商、SSAP及业务）；全部32条业务取得对端校验与回复。
这是当前SDK111/固定通道的池满后恢复子门禁，未覆盖晚到/重复NOCP、handle复用、
Managed撤权/断链/原期限期间在途物理义务或完整组合证明。

旧manifest的credit_exhaustion_acceptance=false保持原样；新独立只读核对器从原run
和pcap重算，资格来自补充报告，不能把旧软件EAGAIN记录自动升级。查询峰值包含
明确未提交回滚reservation；这里只因实际两端时间线和新池满拒绝共同成立而授予子门禁。

实际Native41、Session sanitizer、C/Rust/Python37项布局及482工具测试通过。
CBMC311标量检查直接映射本批C consent函数，排除锁/引用/Runtime/HCD/NOCP真值
和完整C/Rust组合；Kani unsupported继续未证明。失败CI及沙箱/缺少dbus记录保留，
测试预算和pin修正后CI通过；不改变编译服务d744的生产逻辑。
安全147/1ff对端交付历史失败继续保持；本批无新SMP/key/加密/Bond/Profile资格。
自然RCA与非人工恢复继续开放。

## 当前能力矩阵

K415/U376的新回归见上；旧撤权/Down/期限资格继续绑定各自K494/Ue2a证据。

| 能力 | 已实现 | 离线/形式化范围 | 实机资格及仍缺 |
|---|---|---|---|
| WS73 广播扫描、建链断链 | 默认 Native 路径 | 实际入口/Host 回归 | 本批原路径回归保持；完整隔离/自然恢复仍未闭合 |
| 普通用户业务 socket | 基础DGRAM、固定两通道、Session在途PDU/唯一分流、有限8项TX预算 | 实际Native/worker/consent限定检查；本批38跨语言/516工具检查，完整组合仍缺 | 新K415/U376取得136轮/32超限、真实软件队列及controller池满恢复、严格fd退出；完整生命周期仍缺 |
| 用户态 SSAP | 唯一actor，ExchangeInfo、单值读写、发现、UUID | 实际codec/预算/生命周期限定检查 | 新镜像原路径保持；底层DLI PB不等于SSAP长写/分片；正向CCC/通知/指示、安全及Profile仍缺 |
| 安全 relay | 唯一物理Session/typed1812/命令credit/票据；受保护capability/candidate-proof及真实Complete/RX观察，默认Pair不支持 | 15项实际转换/跨语言通过；新job Kani unsupported仍未证明 | K415/U376两角色134..142及8次前后明文应用往返通过；旧模式另8次；原版147/1ff仍缺项；Agent、可信安装/加密/Bond及完整竞争仍缺 |
| 应用权限与扫描 | controller scan RPC显式管理语义；可选sparklink-apps仅领取通道fd | XML白名单/实际调用迁移与严格daemon测试 | apps-only身份尚未实机验收；共享扫描租约/完整按应用策略仍缺，控制组caps0回归不能代替 |
| 设备与daemon生命周期 | per-controller Runtime、epoch撤销、有限工作/期限；单进程daemon | 当前限定模型和实际取消/清理回归 | 六组begun撤权子门禁通过；actor不是进程隔离；不承诺跨daemon崩溃存活；完整组合仍缺 |
| 长包/真实credit压力/多通道/四设备业务 | 有界PB、Session持有begun operation、8项包含busy、原期限 | 游标/consent限定证明保持；software与controller credit分别表达 | 所列长度及真实软件背压通过；两角色burst硬件池满恢复已取得；撤权/Down/期限、重复晚到NOCP/复用、动态多通道/四设备及完整DG03–12开放 |
| 安全/恢复/PM/发布/UserHost | UserHost仅低优先级规划；实验代码不是生产能力 | 安装工具通过或模型通过不等于实现证明 | 原S0–S6全部未完成条件保持；自然RCA、非人工恢复及整项issues继续开放 |

本批正常业务两轮捕获零内核丢包，VM taint0；QMP与受控初始化故障只作隔离开发
支撑。USB写入、NOCP、协议ACK、本地准入和日志均不能替代真实对端应用检查与回复。
模型受信任基础和硬件假设必须明示；完整 Linux、运行库、固件和硬件未被证明。

[BlueZ官方来源、当前调用审查与剩余门禁](../docs/evidence/bluez-contract-review-20261014.json)。
本项目取舍采用[ADR0004](../docs/decisions/0004-application-ownership-and-delivery.md)，
不把它描述为BlueZ缺陷，也不宣称已优于BlueZ。
