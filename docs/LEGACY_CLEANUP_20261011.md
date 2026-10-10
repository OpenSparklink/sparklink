# 旧内核实验实现：调用审计与清理清单

审计日期：2026-10-11。基线 Linux fc0b4d1a44b6、用户态 157ec71c3b9a；
后续 Linux 376bb1e8a544 / c2c4aa4ad0bd 和用户态 9f57d1e / 34b54fd 已整改部分
生产调用链，以下分别记录原调用链、当前实现、
迁移条件及限定回归。UAPI 未发布，无兼容期。

## 立即删除：生产测试行为及错误完成

| 对象/调用链 | 本批措施 | 验收状态 |
|---|---|---|
| core ioctl_dispatch_security → SecurityInner::start_pairing；workers PairInfo/Option/Random/Confirm/DHKeyVerify → SecurityInner | 删除固定 nonce、ECDH 失败测试密钥降级和未验证 proof 的 Paired 转移；旧步骤 reset 后 EOPNOTSUPP，调用者不得发送认证成功回复 | 376bb1e8a544：实际编译和错误 proof/截短公钥/乱序步骤拒绝回归通过；完整每连接安全仍开放 |
| sle_crypto Rust wrappers → sle_crypto_ffi.c；security KDF/CTR/RPA 和 core 查询调用者 | Result 传播原 errno、检查长度/计数；CTR C 临时缓冲完整成功后才提交数据/IV；失败不提交 keys/counter/address | 376bb1e8a544：实际函数分配/算法/密钥/部分写入失败注入及 sanitizers 通过；不是标准密码算法验收 |
| core SEC_SM3/SM4/HMAC_TEST ioctl → SecurityInner 测试辅助/CTR counter=0 | 移除生产执行，返回 EOPNOTSUPP；删除 SecurityInner 测试辅助，迁算法/错误覆盖到 selftests；编号/绑定随调用者迁移删除 | 376bb1e8a544：生产执行已删；旧调用者/UAPI 与正向向量迁移仍待完成，不能用旧 ioctl 成功测试证明生产能力 |
| backend SleController::open/send_command/send_data/reset → UART/SPI 自制 CommandComplete(Success) | 删除伪成功及仅编码却报告发送成功；无真实硬件实现的操作 EOPNOTSUPP | c2c4aa4ad0bd：实际 trait 方法拒绝回归通过，虚假 firmware/capability 已删；纯 framing 留作测试，不宣称硬件支持 |
| slkd config → main defaults，未消费策略 | 显式配置错误拒绝；不支持的非默认策略拒绝。不得静默降级安全 | 9f57d1e 已签名推送：启动前拒绝无效/未知配置和未实现策略，10项配置/实际进程测试；完整策略仍待实现 |

## 移入测试：保留有效开发支撑

| 内容 | 专用位置/边界 | 状态 |
|---|---|---|
| crypto FFI 故障注入、私有状态计数检查 | tools/testing/selftests/sparklink；编译实际 Rust 包装/security 及实际 CTR C 函数，依赖用可控 stub，明确非 RF/非算法向量 | 已通过，stub 不编入生产内核 |
| UART/SPI 纯 codec、分片/边界 | selftests framing；硬件未接通不能用 codec 或本地 Complete 替代支持 | 待保留/迁移有效用例；伪 Complete 直接删除，无业务价值 |
| 核心 Virtual、连接/SSAP 模型及注入 ioctl | 专用 Virtual backend / selftests；相同 Runtime、生命周期和契约 | K1/K19 待迁；不先删除有价值失败用例 |
| QEMU 一次 bulk IN81 错误、autoscan/re-enum/open 故障工具 | 已在专用 qemu-sle-dli 和 VM 工具；默认关闭、单对象 guard、有故障边界回归 | 保留；人工故障支持与自然根因/自动恢复验收分开 |
| Profile callback 阻塞/cancel/drain/panic 测试、transport codec | 34b54fd移到slk-experimental；默认daemon无运行时依赖，无旧服务注册/actor。显式实验feature保留profile0注册和连接callback，Native不注册；请求回调仍未接通 | 实际actor/codec回归保留，严格all-target/all-feature测试，不加全局allow(dead_code)；服务互通仍待验 |

## 等待替代：先迁调用者及回归，再删除

| 旧路径/调用者 | 唯一替代所有者与删除门禁 | issues |
|---|---|---|
| 原core CONN_SEND → conn.send 入 tx_queue + controller.send_data；队列无消费者/handle0错误 | 75b77fc19613已删影子TX ring/重复直发，统一单次backend提交、句柄映射及成功记账，短写/长度拒绝；实际函数回归通过。仍待每通道socket、真实可靠/credit/分片/断链/权限/旧generation及数据实机，迁调用者后删旧UAPI | K4/K17，R03/R10；完整验收OPEN |
| 原workers SERVICE_MGMT/动态reliable与core remote ioctl → 旧wire Engine；local staging留待迁移 | 4d8a0d61673d77c5fd104d219346e0a2d3e23ef2已删除未达标准的wire Engine、无界累积器/无归属通知与method echo，历史codec仅selftests，remote不支持。最终slkd标准Engine/数据库与kernel PDU socket仍待权限/预算/deadline/credit/ACK/Profile及实机门禁；本地staging及旧编号在调用者迁移后删除 | K6/K17、U3，R04/R07/R08 |
| SecurityInner controller-local 状态、SEC_ENCRYPT_ON 提前提交；Bond 仅元数据 | 每连接机制/匹配真实完成，Agent/policy/Bond 用户态；错误 proof、安装拒绝/超时、restore/revoke、真实互通后删旧状态及控制接口 | K7/K18、U5，R01/R02/R09 |
| core legacy read_iter → 旧 event dequeue/copy；Native subscription 另一实现 | 独立订阅、完整记录 copy 后提交、移除唤醒；迁 lib/工具 read 调用者，坏地址/部分 copy/短 buffer/多订阅后删旧队列/UAPI | K3、U2，R12 |
| backend enum、core USB/serdev 注册；serdev 回调忽略 ctx/全局 parser | 可引用 Backend 注册接口，bus 在 drivers；parser/waiter per-runtime+generation；USB=n/m、driver y/m、Virtual卸载和 WS73 原路径后删枚举/全局切换 | K1/K4/K9/K10/K12，R11/R13 |
| slkd transport 未消费、Profile/HID read/write/notify 未路由、过时配置和文档 | 接通、明确实验隔离或删除；保留有效 codec/生命周期测试，严格 check/test/clippy/fmt/release，不以 allow(dead_code) 消除报错 | U3/U8，R14 |

## 每批门禁和证据

本批只约束不可靠能力，不声称完成安全、其他总线或 SSAP。每批签名小提交记录
调用者、删除范围、回归、开放条件，推送后更新现有 issues 的实现/开发测试/实机/
未决状态；不关闭整项。旧源码历史由 git 保留，故障证据文件不删不覆盖。

WS73 Native HCC/BSLE/discovery 生产实现不改；新内核必须重新 VM 启动并用两只
真实 WS73 20 轮交换随机广播/扫描，再检查恢复/幸存者。编译或 fixture 不能证明
真实路径未退化。自然恢复/根因未明继续开放，四设备、服务 sandbox 未验收。
架构迁移按 [ADR 0001](decisions/0001-management-channel-service-boundaries.md)。

### 首批新镜像复核证据

[新镜像回归](evidence/ws73-vm-cleanup-regression-20261011.json)：Linux c2c4aa4ad0bd，
完整 image/modules 构建无 warning；私有签名模块在空 USB VM 两次加载/卸载、
taint0/无 warning。新 VM 真双设备20+2轮全部匹配（最长624ms），一次人工
IN81故障后 generation1→3、幸存generation2不变，slkd PID525/start339不变；
1163 USB记录/零drop，host独立核对22份 RX。应用 UID1000/caps0，最终两只
STOP_CONFIRMED。没有本次物理拔插、自然根因或全自主恢复验收，北极星仍7/8。

实际Rust安全失败测试6项 + C CTR五阶段错误/ASan/UBSan/LSan、后端2项、Python
C/Rust布局/ioctl/32位ABI29项通过。新增CI生产代码失败门禁和同步kernel pin；
远端执行结果须单独核对，用户态39个warning/严格CI仍未闭合。旧正向配对/crypto
ioctl用例尚未迁入算法测试后端，不把其移除或失败改记为成功。R06–R14继续推进。

### 未接通用户态模块的隔离

[实验边界](EXPERIMENTAL_CODE_BOUNDARY.md)：旧Profile/HID/transport移到独立
slk-experimental；默认daemon运行时依赖图无该crate，默认停止旧内建服务注册。
显式experimental-legacy-profiles保留profile0旧注册/实际actor；Native profile1
仍不注册。原模型和actor回归保留，R07/SSAP请求路由/互通等待替代，不宣称完成。
严格检查覆盖default及all-targets/all-features，不增加dead-code lint压制。

本批R04/R08详细范围见[SSAP路径限制](SSAP_LEGACY_CONTAINMENT.md)；删除不可靠旧行为不等于替代Engine已经完成。
