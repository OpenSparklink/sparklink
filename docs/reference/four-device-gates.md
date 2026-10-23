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

五个模式分别运行；不能混入QMP热插拔、故障注入或双设备参数。每条数据由对端应用
实际校验并回复；USB成功、NOCP、协议ACK和日志不能替代它。普通应用仍经slkd取得
授权fd。实验协调者与只具应用组权限的部署资格分别验收，非root并不自动证明权限分离。

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
