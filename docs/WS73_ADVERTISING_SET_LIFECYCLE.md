# WS73 广播集合生命周期：连接失败对照与接入要求

2026-10-12，实际内核46db、服务/工具cd64065的Native VM95再次失败：随机
可连接广播已被真实扫描匹配，Create OUT与Status成功，10秒无outcome；411包、
零丢包、QEMU退出0。不能沿用参考Host成功来宣称Native连接通过。

[九例参考因子矩阵及当前Native失败](evidence/ws73-reference-advertising-set-lifecycle-20261012.json)
独立复算6183包、零丢包，每个非Create命令都具有自己匹配的成功Complete。
原参考f4d85d0仓库保持clean；试验只在私有修改版server/client中运行，所有
变更和二进制哈希保留。它们不是原参考版本资格，也不合入生产代码。

| 参考VM | 相对已通过基线的因素 | 真实连接 |
|---|---|---|
| 28 | 不发送SetPublicAddress | 成功 |
| 29 | 主动扫描改被动，160/40不变 | 成功 |
| 30 | 被动时序改1600/800 | 成功 |
| 31 | 广播换43字节随机Native marker | 成功 |
| 32 | 前置Native mode0参数配置、OFF，再配置mode3 | 发现成功、Status成功、无outcome |
| 33 | 同上，只移除前置OFF | 同样失败 |
| 34 | 同VM32，仅首次GT2姿态byte33从0改1 | 同样失败 |
| 35 | 同VM32，首次mode0使用GT0协商策略 | 同样失败 |
| 36 | 同VM32，在再次配置前增加RemoveAdvertisingSet | 成功 |

VM32与VM36的实际command序列、参数逐项一致，唯一新增是0x0c08/body00。
0x0c08有真实成功Complete，之后才重新配置mode3并产生双端30字节成功连接
事件。参考client都用20秒应用预算；失败记录保留，没有延长等待转成通过。

这证明**在本次111固件/拓扑下，既有mode0广播集合仅靠参数更新不能完成这次
mode3连接转换，删除后重建可以恢复**。不证明固件内部究竟缓存了哪一字段，
也不保证所有模式/GT角色/固件都有同样行为。芯片冷断电状态未在本轮测量，
No-SetPublicAddress成功不能扩展为所有冷启动都无需设置地址。

参考完整Host的DLI_RemoveAdvSet定义0x0c08、一字节handle、CommandComplete；
其设备发现模块要求先停止已启用集合再删除。WS73的实际支持以本次捕获确认，
不根据源码存在或Opcode常量推定。参考SSAP client日志PASS仍未完整逐帧核对；
本项目SSAP/安全/Profile和Native连接未验收。

## 当前Host接入设计

实现属于WS73方言和每设备Host；默认广播继续非连接mode0，不以更换默认模式
绕过失败。单一状态来源必须是实际匹配的控制器回复，禁止daemon保存另一份
推测的集合存在性或已应用参数。

1. 在Host内记录同generation/handle的集合存在性和已确认参数配置。只在真实
   成功SetAdvParams Complete提交新配置；只在真实成功Remove Complete标记
   缺失。失败/在途回复/退役后的旧回复不得更新新注册或新请求。
2. 提交typed广播操作时，在现有Host→gate顺序内原子核对租约、结果容量、
   liveness、Faulted状态及集合状态，再建立不可变recipe。若需要模式转换，
   先确认旧集合OFF，再Remove，确认成功后Params/Data/可选ScanResponse/
   Enable。未知radio/资源状态必须有明确拒绝或受控清理，不能猜测OFF。
3. 删除/重建与广播操作共用一个cookie、全程deadline和作者结果；Host仍按真实
   credits选中下一步。不得给每步重启超时预算，不允许另一个请求插入重建中间。
   现有recipe容量4需按实际最长链核对，更新C/Rust/独立源码测试的一致边界。
4. 取消后的作者结果仍Cancelled。撤销清理依据删除是否真实完成、后续Params/
   Enable是否选中及真实回复决定义务：已删除且未重建不能发送会失败的旧
   STOP；已选中重建或Enable需等待原回复并清理实际集合。超时/失败保持
   不确定或Faulted，不合成Complete、不把部分重建宣布Ready。
5. 最后File关闭和dup沿用真实VFS租约寿命；部分删除/重建也必须有限清理。
   资源存在性、radio truth、初始化资格和物理连接义务分别核对，只有实际证据
   足够才Free/Ready。slkd保持同进程，动态状态变化来自canonical事件/快照。
6. 新状态接通现有调用者后删除重复缓存/旧分支；诊断query仍只读白名单，不为
   0x0c08开放任意raw写入口。UAPI未发布，可同步调整，但应保留已验证的typed
   广播/扫描行为和作者结果隐私。未接通能力明确不支持。

## 修复与回归顺序

先实现并测试实际配置/删除回复的状态边界、recipe长度和全程预算、失败及旧
回复归属，再完整构建当前实验内核；随后VM真实两设备验证Native双向Create/
Disconnect的OUT/Status/outcome。成功后才能做connected release/最后fd/dup/
在途回复及另一只隔离，不能用无连接队列取消替代。

覆盖实际Remove成功/失败、原回复held、取消发生在删除前后及重建选中前后；
要求作者结果不翻转、旧resource不被误STOP、新resource不遗留、对端Ready和
扫描不受影响。同源码重新跑北极星20轮角色交换及QMP/物理生命周期范围内
适用门禁、原队列/部分初始化真实FD回归，保留全部历史失败。物理拔插要独立
验收，QMP不能替代；默认四设备两组并行也保持独立验收。

自然启动超时/bulk/消失RCA和非人工自动恢复仍OPEN；本轮没有hub切电。
完整S0–S6/原28项继续，部分成果不关闭整项。所有实验保持VM-only。

参考矩阵之后Native VM96独立完成RF20+2和QMP guest移除/重加：
1267包/零丢包/taint0、同slkd/bus、普通应用UID1000/caps0；
无物理拔插或自动恢复资格转移。正常VM累计96、维护36，失败不归零。

## 当前Native接入与实机范围

Linux1305136c已把实际配置/缺失状态、原子有界重建、传输前标记校验及取消
后的资源清理接到Host，仍保留同配置的三步路径。VM97在真实设备完成可协商
双向Connect/Disconnect、模式返回默认beacon后的RF22和QMP guest生命周期，
1377包/零丢包/taint0，实际服务与工具fdfd、同slkd/bus、普通UID1000/caps0。
[当前证据](evidence/ws73-native-advertising-recreation-connection-20261012.json)。
Source42Host+2helper/23plan/48management/diagnostic及codec sanitizers通过。
新删除/重建真实FD与connected撤销、fixed-T、物理范围仍待，不能把模型/源码
或单次新连接通过作为整项结束；后续改动仍需按具体新输入重新回归。
