# 2026-10-11 复核与当前整改计划

这份复核基于用户提供的14项报告，逐项检查实现与调用者。原审查基线：
Linux `fc0b4d1a44b6cd417eb99ebee1378bda52a63300`、用户态
`157ec71c3b9a088e39318425299c17c9a70fcd4a`。复核时新增Linux
`2ba3978d22f2`及用户态`8042eb7`只改变QEMU诊断、VM控制/证据工具和文档；
该时点14项生产路径尚未修复。随后376bb1e8a544/c2c4aa4ad0bd已约束
R01/R02/R05，最新分项证据见文末；表中“确认”是原基线发现，不表示新代码
仍具有被删除的测试行为。每批生产提交重新核对，不能复用旧基线验收结论。

用户确认UAPI尚未发布：没有旧公开ABI兼容期要求。修改时同步内核头、Rust/C/
Python绑定、CLI、D-Bus调用者、测试和CI内核pin；迁移调用者后直接移除旧接口。
此前的WS73广播扫描及物理拔插证据继续保留，其范围不能推广到连接/安全/SSAP。

K代表OpenSparklink/linux，U代表OpenSparklink/sparklink。以下任务均为OPEN，
不是已经完成的修复。P1阻止相应能力开放；P2阻止该项功能验收。

| ID | 优先级/结论 | 核对位置与限定 | 既有issue | 修复及必须回归 |
|---|---|---|---|---|
| R01 | P1，确认 | `sle_security.rs`固定nonce、忽略远端DHKey check、ECDH失败测试密钥降级；`sle_workers.rs`普通配对事件调用。不是已证明的WS73实机攻击。 | K7/K18、U5 | 立即删除固定nonce和测试降级；在标准认证/每连接上下文完成前拒绝不可信配对，不能仅随机化nonce后宣称安全。验证错误proof、缺少proof、非法/截短公钥、ECDH失败、错连接/旧generation均不能Paired/生成Bond；实际随机源、标准向量和真实互通是开放条件。 |
| R02 | P1，确认 | `sle_crypto.rs`SM3/HMAC/SM4吞FFI错误，`sle_security.rs`仍推进计数。 | K7/K19、U5 | 所有密码学包装返回Result；检查长度转换，失败不提交密钥/状态/计数/可用密文。以实际包装及可控FFI错误覆盖分配、算法/密钥失败，校验缓冲和计数未被错误提交；测试crypto ioctl迁入专用测试接口或移除。 |
| R03 | P1，确认 | `sle_conn.rs::send`入64深度tx_queue无消费者，core同时直接send_data；先提交统计再发送。Native discovery不能因此被称为坏掉。 | K17/K4 | 明确一个每连接发送所有者；删除重复队列/直发路径，按credit、完整发送完成提交序号/统计。>64连续包、零credit后恢复、短写/发送失败、断链及旧generation清理，多连接隔离。 |
| R04 | P1，确认 | `sle_ssap.rs`ReadRsp追加后转u16，WriteReq追加后累加u16；WriteCmd也忽略扩展/写入错误；该路径没有事务总预算/期限。 | K6、U3 | 每片追加前检查属性上限、PDU大小、checked offset、每连接和全局内存预算；事务截止/断链取消。覆盖65535/65536边界、持续完整片、非法偏移、超MTU、OOM、超时、乱序/错连接；以迁往用户态Engine为最终所有者，旧内核Engine不长期并存。 |
| R05 | P1，确认 | `sle_uart.rs`/`sle_spi.rs`普通backend本地生成CommandComplete(Success)，数据发送只编码日志。 | K9/K12/K19 | 立即移除伪造成功和假数据发送；未接通硬件明确EOPNOTSUPP。模拟行为只进入专用测试backend。实际实现需真实回复/完成关联；无回复、拒绝/超时、短写证明不会成功，保留纯codec测试。 |
| R06 | P1，确认 | `slkd/config.rs`安全/auto_enable配置没有消费，main对所有读/解析错误用默认。 | U5/U6/U8 | 区分允许的默认路径不存在与显式缺失、权限错误、无效配置；明确拒绝未实现非默认安全/启用策略，不能静默弱化。覆盖显式文件缺失、无权限、语法/未知字段、auto_pair/min_encryption、auto_enable以及默认WS73启动回归。 |
| R07 | P2；开放SSAP前必须修复，确认 | profile/service/HID掩码0x04被当notify；内核READ=01、WRITE_NO_RSP=02、WRITE_WITH_RSP=04、NOTIFY=08、INDICATE=10。 | U3、K6/K19 | 建立规范命名常量及明确转换，禁止散落魔数；read+notify不能获得写权限。跨内核C头、Rust、Python的语义测试，涵盖Battery/HID、两种write和indicate，未知位拒绝。 |
| R08 | P2，确认 | `sle_workers.rs`先取notification再credit，失败丢弃且忽略send错误；通知缺少明确连接归属。 | K6/K17、U3 | 连接归属、credit预留、编码/发送提交后出队；失败归还预算并保留消息，indication等确认/期限。零credit恢复、失败/取消、两连接并行、重复/迟到ACK、断链清理。 |
| R09 | P2，确认 | core PHY set与SEC_ENCRYPT_ON在发送/设备确认前修改本地状态。 | U4、K7/K16 | 请求值/pending/已确认值分离；唯一提交由匹配成功Complete驱动。拒绝、超时、错误opcode/generation、发送失败查询不得显示已生效；同样审查其他设置。 |
| R10 | P2，确认 | core conn_send解析handle0后仍传原cd.handle。 | K17 | 解析后的handle用于同一发送事务、credit、队列和统计；默认/显式、无连接、两连接和断链复用回归，与R03一起修复。 |
| R11 | P2，确认 | serdev忽略ctx，共用parser，probe覆盖最新dev_id。 | K4/K10/K12 | parser、分片、waiter归属具体backend/runtime/generation，ctx有稳定生命周期；双设备交错字节/分片、移除/迟到回调、并发probe/remove及释放检查。不能将单设备成功推广为隔离完成。 |
| R12 | P2，确认 | core旧read_iter先dequeue，copy_to_iter零/部分结果消耗事件；Native专用事件已有复制提交语义。 | K3、U2 | 以统一按订阅者、完整记录、复制后提交为目标；迁移读取调用者并删除旧事件队列/UAPI。无效地址、部分copy、短buffer及重试不能丢失或交付半记录，多订阅隔离与退役唤醒。 |
| R13 | P2，确认但限定 | Kconfig核心依赖USB=y、核心持总线注册和backend枚举；drivers/sparklink Virtual模块只打印日志。核心内置Virtual另有实现，开发测试不是全无。 | K1/K9/K12、U7 | 先收敛注册/模块所有权接口，再迁移总线注册及删除枚举；Virtual驱动实际注册相同Runtime/生命周期，迁移模型测试后删除核心内置重复实现；核心USB=n、USB=m、driver=y/m、Virtual热插拔/卸载与WS73原路径回归，然后扩展Proxy。 |
| R14 | P2，确认并补远端证据 | release记录39个slkd warning；CI -D warnings。基线157ec71的run38072489528中cargo check失败，test/clippy/release被跳过，fmt和Python ABI成功。 | K19、U8 | 不降低-D warnings；整理未接通模块/死代码，再以固定依赖建立check/test/clippy/fmt/release基线。把工具、跨语言语义/ABI、生命周期及配置矩阵纳入CI；硬件VM测试使用专用有设备runner/手动门禁，普通CI不得把fixture当RF。 |

## 依赖顺序与验收边界

1. **立即约束生产能力**（R01/R02/R05/R06）：删除生产测试nonce/密钥降级/伪造
   完成；完整实现未知时拒绝操作。失败证据与协议标准尚未确认时，不采用猜测的
   认证算法。WS73 Native discovery保留可用，安全等能力按独立状态暴露。
2. **基础正确性**：R03+R10共用一条发送事务，R04+R07约束SSAP，随后R08、R09、
   R12。只有实际错误传播和完成提交成立后，才能扩大连接/服务/加密验收。
3. **设备生命周期同时保持当前优先任务**：K10/K14/K15/K19、U10处理自然启动
   超时、重枚举、设备消失、幸存者及xHCI警告。R11归入每设备隔离。恢复预算、
   自动Ready、daemon不停机仍需单/双/四设备负向矩阵；只允许VM，原生主机对照
   未授权且未执行，不能用VM替代。真实四设备两组并行仍待验收。
4. **收敛架构和删除旧实现**：R13后逐一迁移SSAP到用户态、每连接安全/Bond、
   Profile/HID及transport。不能把旧内核Engine与用户态Engine作为永久双实现。
   迁移时保留真实WS73 gates、故障历史和有价值codec/协议回归。
5. **CI/文档作为每批提交的门禁**（R14），不等到最后统一清理。每个修复提交
   记录对应R编号、生产调用链、删除路径、失败/成功回归、能力开放条件和证据。

## 清理旧实现与死代码：当前工作项

- 生产固定nonce、测试密钥和模拟成功立即删除；需要的模拟移至明确测试backend。
- Profile注册/连接回调确实已接入旧profile0，不能误删有效生命周期回归；读写
  请求未接入，Native profile1不注册服务。下一步明确实验边界或接通，不能继续
  文档宣称完整Profile服务。transport目前无生产消费者，隔离到实验feature或测试
  crate，保留codec用例；不要用allow(dead_code)掩盖未接通能力。
- 按调用者和运行路径清单迁移旧crypto/SSAP/事件/tx队列/总线实现，删除重复逻辑；
  未发布UAPI不设置兼容期限，不保留永久适配层。文档和错误能力声明同批更正。
- AGENTS.md旧“七阶段完成”仅是历史文件进度，不是验收；删除该状态依据。
  原始故障证据保持可追溯，fixture、人工注入、真实RF、物理拔插分别标明范围。

## 已验证路径与新恢复支持的重审

物理证据仍为[2026-10-10物理闭环](evidence/ws73-vm-physical-20261010.json)，
20+2轮、两只真实WS73、普通UID/caps0、daemon/bus不变。新增
[人工传输错误支持](evidence/ws73-vm-artificial-recovery-20261010.json)已检查
单对象默认关闭/arm guard、close取消、其他对象隔离、guest普通应用与独立capture
校验；141项工具测试及新QEMU mock/QMP边界通过。实际一次IOERROR经guest
xHCI endpoint恢复后丢回复，触发-110命令超时，有限恢复至新generation并再做2轮
真实RF：这是额外开发证据，**U10仍7/8**，不关闭自动恢复或根因未明issues。

远端CI基线：[run38072489528](https://github.com/OpenSparklink/sparklink/actions/runs/38072489528)。
这里没有宣称完整生态、标准一致性认证、PHY嗅探证据、板级校准资格或安全实机验收。

## 架构与清理增补（2026-10-11）

采用 [ADR 0001](decisions/0001-management-channel-service-boundaries.md)，最终连接
数据面是每逻辑通道独立 socket fd；SSAP/服务/Profile 用户态所有者，管理/事件/
诊断/Proxy 独立。 [三类调用审计](LEGACY_CLEANUP_20261011.md)细分立即删除、
移入 selftests、等待新路径替代；不增加未发布 UAPI 的兼容负担。
[BlueZ 对比](BLUEZ_COMPARISON.md)删除错误完整/优势宣称，参考官方 MGMT、
GATT、Agent、L2CAP 和 VM 测试语义。R01/R02/R05 首批已签名推送并完成限定开发/新镜像实机回归，仍未完成
每连接安全/真实其他 backend 验收；R06–R14、自然恢复及整项 issues 仍 OPEN。

### 首批实现、开发测试与实机状态

- 实现：Linux `376bb1e8a544`删除不安全配对/生产crypto测试执行并传播FFI错误；
  `c2c4aa4ad0bd`删除UART/SPI伪Complete/发送成功和虚假能力。未支持操作EOPNOTSUPP。
- 开发：实际Rust6项安全失败回归、实际C CTR5阶段失败和ASan/UBSan/LSan、UART/SPI
  实际方法2项、跨语言/32位ABI29项通过。kernel完整镜像/modules及对象无warning。
- 实机：[整改后新VM证据](evidence/ws73-vm-cleanup-regression-20261011.json)记录
  20+2真实RF（最长624ms）、单对象人工故障有限恢复、同daemon/幸存者、22份独立RX
  佐证及1163记录零drop，taint0。历史物理证据保留，本批未重做人工物理拔插。
- 未决：R01/R02完整认证/向量/凭据安装、旧正向测试与UAPI迁移；R05真实其他backend；
  R06–R14、自然根因/无人工恢复/四设备/全sandbox。严格CI39 warning不隐藏，
  新CI门禁不能代表全部质量基线已恢复，所有整项issue继续开放。

### 最新远端质量门禁核对

用户态 `082e6743e20b` 的 [CI run38075881263](https://github.com/OpenSparklink/sparklink/actions/runs/38075881263)：
新增 actual kernel security/backend failure 门禁、Python/内核ABI和rustfmt成功；
cargo check仍因slkd原有39个dead-code错误失败，test/clippy/header/release跳过。
没有降低-D warnings，R14仍开放；新增门禁成功不表示全部质量或标准验收通过。
