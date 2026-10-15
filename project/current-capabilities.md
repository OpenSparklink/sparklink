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
当前hub直接访问权限不足、`sudo -n`要求密码，已请求恢复先前配置的权限或单只冷断电。
此请求只恢复诊断设备，不记自然恢复；其他设备也不自动推定Ready。没有安装宿主实验内核。
运行态BSS/栈/池边界算术不能证明boot下载器工作区安全，连续填充方案不再重试。
原始combined111文件与生产Runtime未改；以下历史准确镜像的资格保留，不升级为本次失败镜像资格。

## 新增限定资格（2026-10-15）

生产内核仍为 K `49467d4df595f8988a7ad6310b53932f37d68283`；本批编译服务
U `e2a0139ff3ccbccb51f5a8606deda5a0d43688c3`，公开冷加载核对工具为
`86e8cd81f4d18b4a26fcfca8d06832c38927f6e8`。本批无生产Runtime变更。

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
- **离线与形式化分开**：工具`2d6c250`的505检查通过，`bd84733`另加入Down类型/数量负向核对并重放两份原捕获；此前502工具检查通过（包含失败方案退役CLI负向回归）；只读READM核对工具3e3e973的历史结果保留；诊断265的实际codec在Clang sanitizer下
  533352项synthetic IO检查通过。无新增完整安全证明；原consent311仍只限标量，
  Kani unsupported/timeout及旧NOCP复用反例保持未证明。

撤权时间仅由syscall前后区间限定，不宣称精确观察内核线性化瞬间；未覆盖所有在途提交、
原期限、完整断链提交竞态、重复NOCP或handle复用。同行扫描不等于另一独立业务链路仍通信。
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

| 能力 | 已实现 | 离线/形式化范围 | 实机资格及仍缺 |
|---|---|---|---|
| WS73 广播扫描、建链断链 | 默认 Native 路径 | 实际入口/Host 回归 | 本批原路径回归保持；完整隔离/自然恢复仍未闭合 |
| 普通用户业务 socket | 基础DGRAM、固定两通道、Session在途PDU/唯一分流、有限8项TX预算 | 实际Native/worker/consent限定检查；跨语言预算与482工具测试，完整组合仍缺 | 本批136轮/32超限、真实软件队列及controller池满恢复、严格fd退出保持；当前两角色burst池满/NOCP恢复子门禁；完整生命周期仍缺 |
| 用户态 SSAP | 唯一actor，ExchangeInfo、单值读写、发现、UUID | 实际codec/预算/生命周期限定检查 | 新镜像原路径保持；底层DLI PB不等于SSAP长写/分片；正向CCC/通知/指示、安全及Profile仍缺 |
| 安全 relay | 唯一物理Session子对象、typed1812、命令credit/票据、真实Complete关联、0014观察lifetime；默认拒绝未批准配对 | 原实际Host/codec回归与限定CBMC保留，Kani unsupported仍未证明 | 原版111仍缺包；三行RAM诊断替换下真实拒绝到达peer，已恢复原版；无生产修复/批准配对资格，授权配对、可信安装/Bond和加密业务缺失 |
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
