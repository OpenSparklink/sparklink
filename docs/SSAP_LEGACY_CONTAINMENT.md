# 旧 SSAP 生产路径限制与 Engine 迁移

日期：2026-10-11。Linux 4d8a0d61673d77c5fd104d219346e0a2d3e23ef2；属于 R04/R08 的能力限制与旧代码清理，
不是标准 SSAP、完整连接或服务互通验收。R07 跨语言权限及 Profile 修复仍开放。

## 标准核对改变了修复方式

用户提供的 T/XS 20001-2025 V1.2.0 表32规定 READ=01、WRITE_NO_RSP=02、
WRITE_WITH_RSP=04、NOTIFY=08、INDICATE=10。旧内核权限位符合这张表，但部分
旧用户态 Profile 把04用于通知；应同步以命名常量和实际权限测试整改。

该标准表72、75、76使用消息控制码表达读写分包、立即写入、缓存后续与取消。
旧 codec 把 handle/offset 直接编码，并以短 payload 判断结束，缺少这些控制码。
因此不能通过加上512/u16界限就宣称实现标准长读写，也不能继续开放不可靠操作。
本次删除生产 wire codec/请求构造器/事务累积器；只在 selftests 保留历史 codec。
旧源码仍可从 Git 75b77fc19613 查阅，故障证据不删除。

## 当前运行行为

- 旧远端 SSAP ioctl 明确 EOPNOTSUPP，不碰用户数据、锁、credit 或 backend。
- worker 与旧注入入口拒绝 SERVICE_MGMT；不解析、不回应成功、不发送 ACK 或
  credit grant，不驱动未确认可靠协商。原有重复通知发送循环已删除。
- 无连接归属的全局通知队列已删除；notify/indicate/旧 dequeue ioctl 不支持。
  无 Profile callback 的 method 不再默认 echo 成功。
- 旧本地 service staging 保留到调用者迁移，不能代表远端服务发布。属性写入先
  分配新值后替换；OOM 保留旧值。过大 ioctl length/value_len 拒绝，不截断。
- Native WS73 typed discovery/HCC/BSLE 未修改；新内核仍须完成独立实机回归。
  源文件原有全局 dead_code/unreachable_pub 约束仍待局部类型/调用者清理；本批
  没有新增 suppression，也不声称整个旧模块已经清理完成。

## 替代路径与回归门禁

遵循 [ADR 0001](decisions/0001-management-channel-service-boundaries.md)：内核提供
受权限、安全和 generation 约束的完整 PDU socket；slkd 是 SSAP codec、协商、
事务、服务数据库和 Profile 的唯一所有者。未发布旧 UAPI 在调用者迁移后直接删除。

实现次序：冻结 PDU/socket 契约及消息边界/背压/断链门禁；开发标准 codec/控制码
正反向向量；每连接事务、deadline/取消、全局与局部预算；服务数据库、权限、
Profile 路由与 indication ACK；最终真实双设备服务互通，再四设备并行。
不得长期保留两套 Engine，也不能把成功 socket send 当作服务最终完成。

门禁至少覆盖：持续完整片和65535/65536、超MTU、无进展/乱序/错误 offset或控制码、
取消/超时/OOM、错连接/旧 generation/迟到响应、未知权限位、两种写权限隔离、
read+notify 不授予写、零credit后恢复、提交失败保留消息、预算与两连接隔离。
indication 需匹配 ACK/期限；不得先出队再取credit或给未存入队列的消息成功ACK。

## 已有与未决证据

新增8项编译实际生产完整模块和实际远端 ioctl dispatcher 的回归：所有 opcode/
长度0至65536在拒绝前无分配/修改/响应，重复满片无累积器、无method echo、
无归属notify拒绝、分配失败保留旧值及local长度/权限。一个历史codec用例保留
已知offset格式和短buffer检查。依赖分配器为显式 fixture；不属于标准或实机证据。
完整Rust核心对象编译通过，无代码warning；make仍有已知jobserver警告。

[新内核实机回归](evidence/ws73-vm-ssap-containment-regression-20261011.json)已完成：
完整镜像、空USB VM签名模块load/unload、真实双设备20+2（最长622ms）、
单对象人工IN81故障后generation1→3，幸存generation2和slkd PID518/start343
及bus不变；应用UID1000/caps0。1163 USB/零drop，host独立核对22份RX。
最后两只停止确认，VM warning0/taint0；宿主四口均保持身份并已释放。
人工故障命令开始至新Ready约10204.609ms；10秒门限用于成功scan Complete后的
发现，不用于冒称恢复时延。没有本轮物理拔插、自然根因或完整自主恢复验收。
[CI38079779731](https://github.com/OpenSparklink/sparklink/actions/runs/38079779731)
对应用户态558f556/内核4d8a0d61673d，9 jobs全success；已核对实际新增8项SSAP、
11项sender和C USB边界日志。工具141、Rust160、ABI29和strict gates通过。
R04/R07/R08、socket/SSAP/Profile和生命周期issues保持OPEN；自然故障根因、
完整自主恢复、历史物理xHCI警告及native对照不因本批清理关闭。
