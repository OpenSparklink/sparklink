# 四设备策略单变量矩阵（2026-10-12）

三项均为失败，不能关闭默认并行、自动恢复或未明根因 issue。实际服务与
核对工具源码U66d21f689c9c、实际内核K060011963b5e，四口顺序固定为主机
1-2.1.1/CD、1-2.1.2/D1:AC、1-2.1.3/CE:85、1-2.1.4/F9；guest两组为
CD/D1:AC与CE:85/F9。全程VM-only，实际启动偏移参数0，无回复注入或hub复位。

| 配置 | 请求参数 | 原始结果 | 完整轮数/组 | USB包 | 清理 |
|---|---|---|---|---|---|
| 默认 | adv1200、power127、scan1600/800 | 第二组第二轮超时 | 1/1 | 973 | 四只双domain真实OFF通过 |
| 周期 | adv1237、power127、scan1600/800 | 第一组第二轮超时 | 1/1 | 1091 | 四只双domain真实OFF通过 |
| 功率 | adv1200、power0、scan1600/800 | 第二组第一轮超时 | 0/0 | 921 | 原清理FAIL，不能改写 |

四只均独立Ready，实际配置由精确staged daemon解析/规范化，前置show与
全部初始化/START参数核对一致；每例分别16、16、12项真实参数/Complete证明。
默认和周期实际选中功率均20；功率例全部返回`fe`/有符号-2，不能写成实际0。
所有扫描失败均发生在真实成功Scan Complete后10秒匹配期限；失败不是
被测recipe的控制器启动拒绝。功率例第一组有一次真实匹配，但等待同行失败
后未完成共同ACK/OFF/整轮，因此完整轮数仍0，不能追加为RF40或成功轮。

[独立封存matrix receipt](evidence/ws73-four-radio-policy-matrix-20261012.json)
SHA256 `8f1da3e3ff95f73c42115e4dde713219456091d4adada56e2178d07a06dacd44`。
三项原FAIL与完整核对器拒绝保留；默认/周期已完成的各2轮仅标prefix证据。
每例QEMU0、零capture drop、同行有限abort无强杀；失败分支未输出taint数值，
receipt明确记未测，不冒充taint0。所有冻结inputs/源码在终止后独立重验。
精确源码[CI38170801462](https://github.com/OpenSparklink/sparklink/actions/runs/38170801462)
九项成功，本地CLI5例、344工具例、严格all-target/all-features clippy通过。

## 功率例的两个清理问题

初始化后未在业务阶段开启过扫描的CD/CE:85，重复scan OFF得到原生0x0b；
CLI正确返回失败。D1:AC/F9的新鲜advertise OFF则有真实成功0c05 Complete，
但当时独立scan仍On，旧测试解析器错误要求两个domain都Off而拒绝。
后者属于核对器错误，前者不能转换成成功。

签名工具修复Ucfe8161a99ea将新鲜OFF与已有retained OFF一样限定所属domain，
独立domain只能是已知Off/On，仍拒绝Unknown/Error、错generation、错误opcode/
步骤、失败state/status和0x0b。344工具回归通过；离线重算此原始功率case的
6个真实成功OFF均与原始命令/Complete匹配，2个0x0b仍拒绝。没有重跑VM，
没有修改原FAIL或授予清理资格；也不能把修复工具HEAD写成实际服务来源。
原matrix封存先于该工具修复，保留冻结U66d来源。
修复[CI38172047179](https://github.com/OpenSparklink/sparklink/actions/runs/38172047179)
已独立核对精确HEAD九项成功，不能代替实际失败清理回归。

## 后续实施与验收

2026-10-12后续签名 U51158a8107d6/U7b1bd0464ec9 已实现真实初始化出处查询。
新服务默认双设备RF22保留路径；功率0四设备仍首轮RF失败，但12项初始化
出处、4项业务后拒绝与4项真实STOP使本轮四只失败清理通过。两个独立receipt
与管理边界待验收见[初始化OFF范围](WS73_INITIALIZATION_OFF.md)。旧三例原FAIL
及旧功率清理FAIL不改写，以下设计记录保留；完整Managed/默认并行/RCA仍开放。

先接通每注册的初始化OFF证据查询：adapters初始化目前核对op5/6结果后丢弃
request ID，而radio.stop直接发新OFF。保留实际op5/6 ID与原始结果，查询时
重新核对当前generation、present、管理epoch/凭据与内核当前domain状态；
旧、缺失、evicted、撤销或Unknown/Error证据不得确认Off。返回真实初始化
出处，不改写为op2/4，不发虚构Complete，不把0x0b当作成功。新旧路径统一
使用内核结果，不能凭用户态布尔缓存推断硬件状态。

专门覆盖“首轮一组失败、另一组已匹配但等待共同ACK”及扫描/广告业务未
开启的组合，区分初始化已确认Off、业务已真实停止和失败未确认。分别回归
当前注册/旧generation、cancel/release/最后fd/dup/在途回复、同daemon和同行
保持Ready；完整清理有原始成功OFF或有效未改变的初始化OFF证明后才可通过。

随后继续相位/周期实际接收节律、参考Host与固件行为定位。当前三个单变量
结果只说明这些调整未使本矩阵通过；不能归结为确定的RF、固件或Linux根因。
37ms历史对照继续保留，不能加测试sleep当作生产修复。默认双设备/两个自定义
RF22历史路径保留，必要时按新源码重新验收，不从旧证据扩大范围。

该历史三例封存时正常VM累计66/维护20，四设备尝试8；最新累计68/20/9。
默认资格仍0，历史37ms对照资格1。
完整Managed、物理拔插、自然RCA、单只非人工恢复及原S0–S6/28项均保持开放。
