# 标准USB wire与默认实验代码整改审计

<!-- documentation-scope: 20261014 -->
> **阅读范围：历史审计／验收资料。** 标准 USB provider/驱动归属及默认实验依赖迁移。
> [主题归纳与去向](../../docs/project/uppercase-document-guide.md)；[推荐入口](../../project/architecture.md)。
> 原文中的源码、失败、PASS 与命令仅适用于其记录版本；当前资格以 [CURRENT_CAPABILITIES](../../project/current-capabilities.md) 为准。

Canonical所有权/计划/资格仍为ARCHITECTURE、ADR0002、IMPLEMENTATION_PLAN、CURRENT_CAPABILITIES。
本清单是对应调用审计，不是另一个执行计划。审计基线K1d6b3195484f；整改K6db8a530f9c6，VM工具U2484932。

| 类别 | 生产调用者与原功能 | 本批处理/替代 | issues与回归条件 |
|---|---|---|---|
| 立即删除 | sle_usb::prepare_usb_controller → sle_fw::load_usb_firmware → C download，自动对sle_usb_v1.bin发F810/F811/A5 | net/sle_fw模块/C下载/FFI删除；standard只查询已经运行的DLI；WS73 FW由drivers/sparklink/ws73按SDK111实现 | K#1/#9/#10/#12/#19；实际prepare不请求通用FW、完整build、真实WS73保持 |
| 立即纠正 | UsbController.send_command_transport和bootstrap C sync，A1+bulk指令、bulk读reply | 共同C EP0 writer四字节头、interrupt query、device/interface provenance、wLength边界 | K#9/#11/#12/#19；actual25C+8Rust、context19、双端实机保持；standard物理仍缺 |
| 立即拒绝 | Std UsbController.submit单bool typed mutation；ControllerBackend.validate_command此前默许 | 未接通recipe/connection返回Unsupported，raw只准核对的queries，在准入及submit检查 | K#5/#9/#11；port5不会发未经资格mutation，未来common标准typed policy后接通 |
| 立即拒绝 | old sle_usb_dev_send_data(handle-only)和A3-magic RX生成DataReceived | TX Unsupported，bulk/unknown lane拒绝；不再交旧连接队列 | K#6/#17/#19；无fake data/Complete，WS73票据业务40/249不受影响；未来standard Session/ticket/credit/PB接通 |
| 移入测试 | 旧固件bounds/timeout/alloc/return，以及旧C数据短传输边界 | selftests/retired-usb-firmware、retired-usb-registration/handle_only_data.c；历史74C/12Rust和数据边界保留，明确非生产wire | K#17/#19/U#3；CI历史回归保留，不增加能力资格 |
| 等待替代 | static ControllerBackend::Usb、core USB注册/open与旧事件/连接消费者 | 接common标准descriptor/Host/provider retained ops/RX-open-close后迁调用者并删重复，移transport到drivers；新typed/data资格逐项取得 | K#1/#3/#6/#9/#12/#17/#19/U#1/#2/#3/#8；genuineVirtual、USB=n/m/module/IRQ/PM、准确回归，不只改enum名称 |

本地标准参考：T/XS10003-2025 §6.2.1/6.2.2.1/6.2.2.2/6.2.3/6.2.6/7.2/7.3；未上传标准全文。
EP最大packet不是整个DLI event/URB预算，event上限65535参数+4头；control wLength包含4头。
Metadata/buffer支持不代表SSAP MTU/可靠mode/security policy或Ready；profile0默认daemon仍不宣称支持。

[实施/模型假设/历史与新实机](../../docs/evidence/standard-binding-offline-20261013.json)。仅VM中真实设备I/O，
普通应用对端随机校验回复及USB/HCC/A3，而非USB写成功/日志/广播替代业务。
标准binding错误不作为WS73自然启动/重枚举/消失RCA，受控缺文件/QMP/manual/hub切电不算自然恢复。
完整S0–S6及原scope保持，部分成果不关闭整项。

## 后续调用者迁移已实施（Ka368cf5f1784）

standard经C provider ops/共同descriptor及精确reserved身份接入；Core安装/open-close、snapshot、query、
cleanup和Native data port消费者统一。static UsbController、ControllerBackend::Usb/new_usb和Core USB
独立安装/open删除；有价值旧info/open regression仅selftests/retired-usb-registration。
当前C provider14/descriptor40/common projection5/Core18等实际源码回归，准确WS73新40/249/fault8保持。
等待替代清单收敛为transport/driver注册移drivers及USB=n/m、genuineVirtual、标准typed/ticketed data/canonical
事件、旧ring/连接消费者、moduleIRQPM与完整lifetime/自然恢复；不能以本批迁移关闭整项。

## 驱动归属迁移已实施（Kae5b24535a89）

立即删除：net/sle_usb.rs生产注册、net/sle_usb_ffi.c transport位置、USB=y依赖、死Core USB包装与常量。
移入测试：旧Core注册/wrappers位于selftests/retired-usb-registration，仅历史回归。
替代：drivers/standard_usb.c实际USB驱动，net/sle_standard_dli.rs协议入口；共同provider/Runtime精确身份不变。
等待替代：standard typed/Session-ticketed data与canonical事件、真正Virtual、完整module/IRQ/PM/自然恢复。
旧USB_DEV_COUNT明确Unsupported；未发布旧UAPI完整删除仍待调用者迁移，不设兼容期。
[准确新证据](../../docs/evidence/standard-driver-move-offline-20261013.json)与CURRENT_CAPABILITIES集中维护资格。
