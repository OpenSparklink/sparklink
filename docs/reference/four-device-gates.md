# 四设备业务门禁契约

此参考适用于 `ws73_target.py run` 的独立四设备 VM 模式。它们复用每设备 Runtime、
唯一 Session、授权 socket 与现有 `slktest`，没有另一条业务发送路径。
源码支持、离线检查及准确 artifact 的实机资格分别见[当前资格入口](../../project/current-capabilities.md)。

| 选项 | 固定工作负载 | 必需证据 |
| --- | --- | --- |
| `--four-device-business` | 两组各两种连接角色，每角色20次61字节往返 | 共80次随机载荷校验回复；两组真实 USB 业务窗口重叠 |
| `--four-device-disconnect` | 每角色交替选择受害组4次、存活组20次61字节往返 | 共48次回复；存活组实际Disconnect前至少2次、双方Down后至少4次完整往返 |
| `--four-device-burst` | 两组各两种角色，每角色16次2042字节往返 | 共64次回复、实际PB分片、有限队列背压与逐controller观测pool饱和后恢复 |
| `--four-device-owned` | 原80次短消息，另运行两组／两角色／两方向的Owned审批和拒绝 | 16个真实拥有者、80次请求／回复交换，包含退出后远端拒绝；两组SSAP线上窗口重叠 |
| `--four-device-update-delivery` | 原80次短消息，另执行protected2下的完整update-v2矩阵 | 两组／两角色／两方向，32／2036／2037／2042字节，notification及indication共64次更新、64次对端应用校验回复和128次CPCD决定；两组更新线上窗口重叠 |

| `--four-device-shared-subscription` | 原80次短消息，另独立运行原共享订阅release／expiry／owner-exit矩阵 | protected2；两组／两角色／双向notify和indicate共112次更新、192次应用校验回复、32次共享加入、按case核对部分成员退出、16次最终disable；实际UID1004 reader／UID1005 publisher与两组线上窗口重叠 |

六个模式分别运行；不能混入QMP热插拔、故障注入或双设备参数。每条数据由对端应用
实际校验并回复；USB成功、NOCP、协议ACK和日志不能替代它。普通应用仍经slkd取得
授权fd。实验协调者与只具应用组权限的部署资格分别验收，非root并不自动证明权限分离。

## 开始无线业务前的身份检查

四设备 RF 与业务协调器在首个 Ready 屏障释放前，复用收尾时的唯一身份检查：
两条实际 worker pipe 必须分别报告其明确分配的两个 guest 端口；四个 controller 的
端口、对象路径、地址、index、USB bus/device 及 index/generation 组合必须相互区分，
设备描述材料也必须完整。重复地址、缺失记录或错配 slot 时，两组都不会收到开始确认。
这只核对观察及准入，不证明地址的正式分配、芯片身份认证或跨设备全局 generation。
历史材料不因新检查加入而升级；新资格仍须绑定实际执行工具与 artifact。

## 动态通道的接线边界

当前四设备业务门禁使用固定 basic 通道。内部 benchmark supervisor 已复用订阅测试的
pair0／1 隔离方式，分别绑定请求目录、临时存储、关闭后的产物和报告校验，并要求明确的
版本、pair 与专用 VM token。没有增加收发循环、协议 codec 或 Host。
这些目录仅隔离测试产物命名，不是同UID进程之间的权限沙箱或daemon故障隔离。
这组原语仍未接通四设备动态通道 runner；离线路径隔离检查不授予动态多通道、公平性、
性能或实机资格。普通两设备 benchmark 的无 pair 路径和原工作负载保留。

## 受控断链的因果编排

新 prepared／run 的 `four_disconnect_progress_contract_version=1` 要求匹配的暂存
工具；旧载体不能在新物理入口冒充该契约。历史记录仍按其原版本解码，不能补字段升级。
协调记录的 `disconnect_progress_contract_version=1` 绑定如下顺序：

1. 两组均实际建链；保留原 ControllerEvent copy、退休UAPI、元数据与registry检查，
   此时确认各controller有一条物理连接。
2. 原应用启动，受害组4次、存活组20次；两组都保持原始非限速业务和原期限。
3. 存活组协调进程从原initiator stdout观察至少两条有序往返记录，发出有界进展通知。
   它只是调度提示，不授Ready、credit、权限或通过；应用进程继续运行，不被暂停。
4. 受害组应用完成后，复用唯一类型化Disconnect实现。每个phase最多提交一次，
   仍需原始期限内的真实双方Down、旧对象拒绝和实际radio停止检查。
5. 两组完成后保留原被动检查，并新增Down后的零物理连接检查；fd关闭与controller
   退休不是同一动作。进展前缀、PID、现场pipe事件、回执和时间范围均须能与原记录核对。

最终判据仍独立使用两端捕获核对至少2次断开前、至少4次双方Down后回复，以及两组
业务窗口重叠、同一应用进程和daemon身份。通知、父进程释放屏障或48次分项回复
本身均不足以通过。检查移出Disconnect关键路径不删除检查，也不延长协议期限。

## 并行 Owned SSAP

显式模式复用现有 `ws73_ssap_owned` 调用者与唯一用户态Engine，应用业务仍用原通道。
每个角色／每组均执行两个方向的allow／deny；拥有者实际核对值，退出后删除注册，
对端再读必须取得真实协议错误。默认四设备模式不会自动启用该能力。

新准备记录的 `four_owned_contract_version=1` 要求当前Python工具及可执行`/init`。
复用旧载体时保留冻结ELF和父产物，另行封存当前启动脚本及其输入hash；不能仅更新
Python或启动参数。实际启动的parallel／business／Owned选择器必须唯一且一致，不能以Owned覆盖长包或断链标志。
协调记录的 `parallel_owned_contract_version=1` 绑定原始工作进程、
旗标、阶段和现有Owned材料；聚合器重新核对原记录，不仅接受一个PASS字符串。

完整判据仍由既有Owned校验器逐条匹配原审批／拒绝／owner退出和两端USB中的真实
请求、回复、载荷及lifetime，再检查两组线上SSAP区间重叠。原80次随机socket回复、
真实业务重叠、原期限和清理同时成立。记录缺失、source／init不匹配或任一失败均拒绝。
这只覆盖UID1000／caps0的control-role实验；不授service-only部署、密码身份、Bond、
每个owner退出时同行持续业务、完整取消矩阵或设备故障隔离。

## Protected2 更新交付

此显式模式复用现有按controller隔离的numeric-approve Agent、relay／安装状态、
唯一SSAP Engine和C／Python应用调用者。真实安全见证、Grant拒绝和线上关联先成立，
再执行完整update-v2；本地批准、服务值替换、协议ACK或加密日志均不能替代对端应用回复。
通知和指示各32次，发送方向及连接角色均交换。它不证明射频密文、密码身份认证、
Bond、service-only部署或完整协议安全。

准备时显式提供`--native-discovery-config`，要求冻结配置`ssap.channel_security=2`。
复用旧载体时，配置只能由其确切冻结slkd执行`--check-config --dump-ws73-policies`
校验；guest的版本化绝对别名在私有root内解析。此操作不启动宿主daemon或安装服务。
其他旧四设备模式不会自动接受自定义配置，也不会因配置不匹配降级为明文。
此外显式提供`--native-verification-openssl /path/to/openssl`：准备阶段执行独立CMAC
向量，封存guest校验器及动态库hash；与冻结运行库冲突则拒绝，不替换旧ELF依赖。
运行前核对完整闭包；缺少该依赖时不得先运行业务后跳过安全证据校验。

`four_delivery_contract_version=1`要求匹配的当前工具、可执行init、冻结见证ELF和应用
产物；实际启动的parallel／business／delivery选择器必须唯一且一致。
协调记录`parallel_delivery_contract_version=1`绑定两个原工作进程、实际numeric机制、
安全等级、完整长度和原始材料。聚合器复用现有安全及update校验器，另核对真实物理
连接期限内的两组更新窗口重叠。任一缺项或失败均拒绝，不退回明文Owned或缩减矩阵。

更新监督器复用既有有界子进程pipe收集器，实时回执来自原进程的stdout／stderr，
证据文件只作持久化sink，不通过实时重读文件驱动事务。每流最多2MiB，仍保留原
消息／观测次数和期限；这不是协议队列或业务载荷预算的扩大。写入、UTF-8、EOF、
最终文件身份或预算错误仍失败，清理错误不得覆盖原首因；没有文件读取重试或隐式
fallback。新记录的`ssap_update_delivery_output_contract_version=1`要求每个publisher
与peer的完整pipe／字节记账；历史记录保留原观察方式和原判定，不补字段升级。

当前订阅读取也复用同一有界子进程pipe收集器；文件只作持久化证据sink，不在
活跃reader上反复重读。`ssap_subscription_output_contract_version=1`绑定原请求、
root结果及父记录；当前执行必须具备该契约和准确collector依赖，不能回退旧观察方式。
普通reader原24行、shared pressure原64行、现有每流2MiB和phase快照预算分别保持。
原始期限、租约、队列、载荷及角色矩阵不变；部分stdio行只在活跃观察时等待补全，
完整关闭转录、UTF-8、终止换行、字节记账、EOF／错误与最终文件身份均须检查。
缺失／重复／超限／清理失败仍拒绝，作者原错误不得被后续清理错误覆盖。

旧未带该观察契约的捕获只按原身份进行离线重放，不升级为当前pipe资格；保留的
ENODATA原堆栈和失败不变。注入活跃文件读取失败验证的是观察依赖，不是底层9p／
文件系统根因证明，也不授自然恢复资格。

## 并行共享订阅

`--four-device-shared-subscription`复用现有shared-release调用者、唯一SSAP Engine、
真实system bus角色probe和关闭后快照。准备要求`four_subscription_contract_version=1`，
保留上述protected2配置、numeric Agent、独立CMAC校验器及准确冻结产物闭包。
`parallel_subscription_contract_version=1`绑定实际请求和两个工作进程；使用原`--ssap-subscription-shared-case`显式选择`expiry`、`owner-exit`或`pressure`，默认仍为`release`。
不接受单reader降级、减少原80次socket回复或放宽期限。

两个有限root监督器只各自读取固定`parallel-business/pair-0`或`pair-1`请求，
校验选中的两个guest端口、完整controller／generation／Connection身份和实际产物。
每组独立使用`/run/ws73-subscription-role-pair-N`及对应`/evidence`关闭快照路径，
保留原32MiB tmpfs、每phase16MiB／64文件和每请求90秒／监督器180秒上限。
不接受任意目录或跨组请求；退出只清理本VM已知子进程。

release／expiry／owner-exit每组保持原56次更新、96次应用校验回复；pressure
每组为原176次更新、328次应用校验回复。各case仍有24个reader和4个publisher。reader实际
UID/GID1004、publisher1005，无附加组或capability；管理协调者仍为UID1000。
部分释放后另一个reader继续实际校验回复，最后引用才产生真实disable。独立检查器
核对完整原始输出、两phase快照hash、权限拒绝、enable／最终disable线上写入，
再核对两组更新在原物理connection lifetime内重叠；缺少一组原材料即拒绝。

expiry额外要求`four_subscription_lifetime_contract_version=1`及匹配的当前工具／init。
协调者、两个worker、各原phase、root快照与实际boot case必须一致，不能将旧release
证据改名为expiry。仍执行原112次更新、192次应用校验回复、80次socket往返；另须
核对16次原始到期和16条已接受未读数据被丢弃，过期token不能重新取得资格。

a0为原2秒本地租约，b及后继a1保持原30秒租约。先在原期限前发布未读数据，再
等待原到期并实际读取expired／discarded状态；不发送release来制造到期，也不延长
租约。同行b继续验证并回复，新a1使用不同token且保留该连接原安全epoch，只有
最后有效引用退出才发送物理disable。它是本地调用者租约门禁，不是远端协议定时器、
Native TX五秒授权、kernel Grant撤销或连接断链的替代资格。

owner-exit复用相同lifetime准备契约，另外要求16次已知guest reader真实退出、
16条退出前未消费发布及同行继续实际校验回复。仅可终止本VM原Popen子进程：校验
VM标记、原PID及UID1004后SIGKILL，实际wait必须为-9且早于原租约到期；不以断开controller、
手动release、租约expiry或日志替代。原死亡观察窗口／后续同行业务仍受5秒约束，
30秒租约和完整112／192／80矩阵不变。后继使用独立token及原安全epoch，最终
引用才产生disable。该case有16次保留同行的显式release及16次最后disable，
不同于release／expiry的32次保留同行退出；不能因名称相似套用同一计数。

未消费发布不等于已经读取后的丢弃，进程退出也不证明清理瞬时完成或没有UAF。
完整原输出、实际凭据／退出／时间线、同行应用回复、后继隔离和线上配置都须核对。
这不授kernel Grant撤销、daemon死亡、物理断链或自然设备故障恢复资格。

pressure要求独立`four_subscription_pressure_contract_version=1`、当前工具及可执行init，
不接受旧lifetime准备字段代替。沿用既有22次更新／组、16包容量和30秒租约：慢a0
先不消费，健康b持续实际校验回复；核对通知丢弃与指示拒绝分别记账、原16包有序
排空并逐条应用回复、恢复接收、部分释放及后继独立token。两组总计352次更新、
656次应用校验回复、8次通知丢弃、8次指示拒绝、16次排空及恢复；健康b共352次回复，
零缺失。原80次socket往返、角色交换、关闭快照与物理配置检查同时成立。

这只覆盖本地应用订阅有限队列，不能升级为controller data credit、USB池饱和、
吞吐／时延、公平性、断链或owner退出资格。准确新artifact仍须单独实机验收。

此门禁不授整个部署仅应用权限、完整多通道、
故障隔离、公平性、Bond或射频密文资格。快照存储隔离是测试设施职责，不构成生产
daemon进程故障域隔离；新模式存在也不代表准确新artifact的实机门禁已通过。

## 范围与拒绝

只允许资源配置中的四个固定物理叶子，逐设备附加并每次复查占用、型号与输入来源；
不透传、复位或切电整个hub／主机controller。混合设备需要显式SDK110逐叶五文件
计划与新HCC核对。E的临时地址配置／真实读回在广播前完成，结束后恢复原值并读回。

长包门禁的pool与NOCP对应关系只是原材料范围内的观测一致性；它不证明硬件完成事件
永不重复／迟到、旧debt复用屏障或整体credit正确性。受控Disconnect不授自然故障、
传输故障恢复、持续饱和时隔离、公平性、完整多通道或protected SSAP资格。

缺少一端捕获、应用回执、原字段、必要阶段，或错误／超时／SKIP时均不能生成完整PASS。
原失败及其源码身份保留，后续成功只属于新的准确运行。协调首因保留在原error字段，
退出时额外管道事件等清理错误另记；它们仍使门禁失败，不能覆盖或吞掉首因。
