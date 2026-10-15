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

端口`1-2.1.2`的历史描述符失败及RAM下载失败保持原记录。用户再次报告重插后，
只读比对确认该口设备号85→88，端口3及1/4不变；本次受控VM原版111配置已到达
两只Ready，端口2/3交换连接角色完成4次61字节普通用户随机对端校验回复。
这是人工操作后实验条件恢复，不是自然故障根因或非人工恢复通过；不声称固件完整
读回/执行证明。随后准确45/37、227固定工具的17组保持回归全部通过，包含两角色
能力/候选/安装和原11数据门禁；新期限代码不继承这些旧ABI资格，报告正在封存。
没有安装宿主实验内核，不要求继续人工拔插。历史失败保留：
[前轮失败及端口3限定成功](../docs/evidence/port-requalification-20261015.json)。
运行态BSS/栈/池边界算术不能证明boot下载器工作区安全，连续填充方案不再重试。
连续RAM实验未改原始combined111文件或生产Runtime；以下历史准确镜像的资格保留，不升级为本次失败镜像资格。

## 保留的完整回归镜像（eff620/2cd，2026-10-15）

上一轮完整回归 K `eff62088fe572f417fbd87e4a32b8305b658b4b5`，编译用户态和封存工具
U `2cd55722d483b3a651d5351d2adf58ffc8b09618`。两仓库签名提交已推送，
严格内核构建、WS73/标准USB无设备启动及Virtual VM通过；U的CI与Documentation通过。
[准确源码hash、两端捕获hash、回归与边界](../docs/evidence/session-owner-retention-20261015.json)。

**生产行为**：唯一物理Session不再随作者撤权从表中删除；停止数据/作者工作，保留
原epoch对象直到真实Down或注册退休，拒绝同lifetime的后继lease替换。000e/0011
元数据在撤权后只可找到原已有对象、结算旧物理义务，不分配新Session或授予业务
权限。命令Status接受不清除异步安装义务，未知事件和不确定失败不伪造终态。

**实机限定通过**：第1/4只交换G/T角色，同一Session/命令credit/最终票据，分别核对
实际九条relay/Complete/对端0014、G1c03、T真实000e后1c05和各自0011，原5秒内
36.396/37.207ms完成。8次UID1000/caps0随机应用校验回复中**4次安装前、4次控制器
报告初始加密后**。另15组保持回归全部通过：其中11数据门禁136次对端业务回复、
32超限拒绝、两角色严格最后fd，61/248/249/250/253/254/255/1024/2042及既有SSAP
路径保持。6组begun2042 PDU的Managed release/最后管理fd/dup两角色回归通过，
真实断链且同行租约/Ready保持；这六组不是安全安装Status/0011受控交错门禁。

**实际credit补充观察**：两角色源端池满拒绝增量30/29，两端均出现容量/实际峰值5，
NOCP后恢复提交，各端每角色206次提交/NOCP、最终debt0；32次burst均有对端应用
回复。原manifest不改写；这不证明晚到/重复NOCP、handle复用或完整组合性质。

**离线与未证明**：44项实际Native/data函数检查、68项Host及snoop脱敏通过；C分配、
锁/引用和USB依赖仍是fixture。旧f5实际Session源码的撤权丢表引用行为在同一检查器
重现，新实现通过对应回归；不是实机提前Free/串包/UAF证据。337的23项纯转换及
Kani1681检查覆盖的生产纯源码hash未变，但原结果仍为NOT_PROVEN_UNSUPPORTED，
不是新证明，不覆盖eff620集成、真实锁/引用/USB和硬件屏障。

**仍缺**：Agent/method/调用者策略、认证身份/可信Grant、Bond/重连、独立空口密码及
第三方互通。当前只取得控制器报告的未认证安装与业务子资格，默认Pair/D-Bus仍
NotSupported，独立Managed实测未运行daemon。接下来为Agent复用已接通的单请求作者取消及
原期限，禁止用撤销整个controller租约来取消一个应用。相关安全Status/0011、撤权/
Down/实际提交组合仍需受控VM验证。动态通道、四设备和真实SSAP通知/指示并行，
自然根因/非人工恢复、原147/1ff缺项及第2只原版恢复未验证继续开放；用户重插端口未确认，VM对1-2.1.2的描述符检查仍失败。

## 新期限代码与准确子资格（8cbf53/2d81/575工具）

K `8cbf53e6a088899229d398b0673a82e8e5aed9ff`将未发布SUBMIT改为版本2/64字节，
强制携带批准等待前的CLOCK_MONOTONIC原期限。Session的prepare/crypto/input/最终
票据/查询使用纳秒，Host的jiffies只安排清理，不授予新预算。RESULT/CANCEL仍版本1。
准确干净内核构建、31项实际生产转换、39跨语言、522工具、Cargo与严格clippy通过。
Kani100项检查对**生产期限算术**限定通过（所有u64时间/所有u32上界，x86四种HZ）；
首次任意HZ全范围检查超时保留。它不证明时钟对应、Session/Host/USB/锁/硬件，
旧安装组合1766检查unsupported也不因该算术结果升级。Agent尚未接线。
两角色真实VM已核对：受控等待2秒计入原5秒，5031.487/5029.999ms从初始输入
观测到state7/ETIMEDOUT（准入后仅2976/2973ms），取消两次不改写超时终态。
新请求号/有效新期限仍EBUSY，同租约/lifetime/Ready不变，共8次普通用户随机对端
校验回复、两端USB/HCC/A3及后续实际Down/扫描通过；taint0/drop0。
[准确源码、限定形式化及失败保留](../docs/evidence/security-absolute-deadline-20261015.json)。
这是受控等待门禁，Agent仍未接线；首次探针复用过期输入导致门禁失败已保留，
575仅修探针。新镜像两角色提交前取消、实际未认证安装、能力和候选协商亦通过，
原5秒内取得真实relay/角色安装命令/0011及对应前后普通用户业务；各门禁分列。
它们不表示Agent或认证/Bond；本批21组相关实机门禁全部通过：10安全机制分项40次业务、11数据门禁136次
对端校验回复、32超限拒绝及两角色严格最后fd；长度61/248/249/250/253/254/255/
1024/2042保持。burst的软件背压不自动升级为硬件credit证明。
[准确21组矩阵及限制](../docs/evidence/security-absolute-deadline-regression-20261015.json)。
补充[实际池满与NOCP后恢复观察](../docs/evidence/security-deadline-credit-observation-20261015.json)：
两角色源端新增池满拒绝29/30，两端容量/实际峰值5、各角色各端206提交/NOCP，最终
debt0，32次burst对端业务回复。原manifest的credit_exhaustion=false不改写；这不证明
重复/迟到NOCP准确性、handle复用屏障或完整守恒/提交组合。
整项Agent/安全/Bond、受控在途安装组合、四设备和非人工恢复仍OPEN。

## 最新取消机制与准确实机子资格（45c049/37f7bc2）

K `45c049f329643de7a9941fe664642b3f847561e0`接通32字节类型化取消；
编译用户态U `37f7bc220cd769e44d968d3a6c0a20efb4d4f231`，封存/执行门禁工具
U `227f2f576ddf1741b2787138fbd27108acc650d9`。复用原Session/credit/票据，不释放controller租约，
不消除在途物理义务或改写终态。Rust/C/Python绑定、28生产转换、39跨语言、
44Native/68Host、Cargo222/13 suites、严格clippy、准确内核及无USB VM通过。

**实机限定通过**：端口3/1交换G/T，各取消被动端等待中的一个安全作者请求，原5秒内
20.610/19.370ms得到state6/ECANCELED；错误版本/保留位/身份/请求/非作者及普通用户
继承管理fd被拒绝，重复取消保持终态，同租约/物理lifetime/Ready和通道不变。共8次
随机业务往返（4次取消前、4次取消后）均由UID1000/caps0对端实际校验回复，双端
USB/HCC/A3核对；该窗口无安全relay/安装/启用命令及伪安全事件，随后真实Down/扫描
清理通过，taint0、抓包丢包0。[准确证据与可复现命令](../docs/evidence/security-passive-cancel-20261015.json)。

这不是安装已在途的取消/Status/0011/撤权/断链受控交错，也不授予Agent、D-Bus/CLI、
认证身份或Bond资格；这些仍缺。521工具检查通过；1766项Kani检查仍
NOT_PROVEN_UNSUPPORTED，实际File授权/锁/引用/USB组合未证明。
上方eff620的完整安装/15+6保持矩阵保留准确旧身份，不继承为45的完整资格。

## 历史准确镜像入口

K `41572aaf736d` / U `37666749f579` 的候选proof与旧模式/136次数据资格保留
[原报告](../docs/evidence/security-key-agreement-20261015.json)，state8不是实际安装。
K `f5c79a50467b` / U `3eb3c459c686` 的首次两角色安装与15组保持回归保留
[原报告](../docs/evidence/security-installation-20261015.json)。历史结果不改名为最新镜像，
失败、反例、原资格与限定证明范围均保留；含密钥USB捕获仅私有保存。

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

当前eff620/2cd的新回归见上；旧Down/期限资格继续绑定各自K494/Ue2a证据，不继承完整受控交错。

| 能力 | 已实现 | 离线/形式化范围 | 实机资格及仍缺 |
|---|---|---|---|
| WS73 广播扫描、建链断链 | 默认 Native 路径 | 实际入口/Host 回归 | 本批原路径回归保持；完整隔离/自然恢复仍未闭合 |
| 普通用户业务 socket | 基础DGRAM、固定两通道、Session唯一分流、有限队列 | 当前CI与实际源函数检查通过；完整组合仍缺 | eff620/2cd取得136次回复/32超限、软件及真实池满恢复、严格fd；动态通道/完整生命周期仍缺 |
| 用户态 SSAP | 唯一actor，ExchangeInfo、单值读写、发现、UUID | 实际codec/预算/生命周期限定检查 | 新镜像原路径保持；底层DLI PB不等于SSAP长写/分片；正向CCC/通知/指示、安全及Profile仍缺 |
| 安全 relay | 唯一Session/typed1812/命令credit/票据；私有候选材料、真实1c03/1c05/0011、异步义务与撤权保留 | 23纯转换、44实际Native、68Host等限定通过；Kani unsupported仍未证明 | eff620/2cd两角色未认证安装、4次安装前/4次报告加密后回复；Agent/可信身份/Grant/Bond及原147/1ff缺项仍开放 |
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

## 新增源码参考的资格边界（2026-10-15）

`drivers_peripheral@879984db5c71` 的 NearLink DLI/HAL 已完成
[只读版本/许可证/调用边界审计](../docs/evidence/openharmony-peripheral-reference-20261015.json)。
它补充既有 NearLink Host/SDK111/libws73 参考，不改变运行代码或 WS73 资格；
HDI 初始化返回、onboard 状态和 transport 写入均不能替代 Ready、真实 Complete、
安装结果或对端应用校验回复。厂商 Host/UserHost 适配仍为低优先级规划，未实现。

## 最新CI

U `37f7bc2` Documentation通过，综合CI因授权guest矩阵漏列CANCEL失败，保留失败记录。
K `239e0171b6ef`仅改测试：补齐CANCEL、删除过时102/35固定计数，保留独立全部成员
契约和旧计数拒绝测试。4契约/79verdict/严格C编译通过；U `b0e88bc`的综合CI
38728290114及两Documentation已通过。这不表示完整授权VM或形式化已通过；
工具提交227f2f5的综合CI 38729575220、Documentation 38729575509亦通过；
生产镜像仍准确标识45/37。
