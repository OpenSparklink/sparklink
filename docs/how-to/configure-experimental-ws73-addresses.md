# 在实验 VM 中配置 WS73 运行期地址

本指南供显式 Native 管理者在无线操作前配置临时实验地址。它不是地址分配、
生产烧录或普通应用接口；不写 eFuse、Flash 或 NV。适用接口及限制见
[运行期地址参考](../reference/interfaces.md#实验性运行期地址配置)。

前置条件：使用匹配内核的 `slkconfig`，两只设备逐叶分配给专用 VM，且没有其他
使用者。明确选择各自适用的主固件和两份校准；启动后分别检查实际 HCC 型号／总线。
相同 VID/PID 不能证明型号。当前混合 E/U 启动仍须遵守现有固件选择限制。
VM 管理进程需要 Native 权限；随后普通应用通过 daemon 授权的 socket 收发。

1. 在启动 slkd、广播、扫描或连接之前，记录每只设备的 controller index、
   generation、USB 拓扑、HCC 结果及固件输入 hash。控制器须处于尚未使用的 Setup。
   将下列变量设为本次实际身份，在 VM 中执行真实读回，并分别保存原地址：

   ```sh
   slkconfig --adapter "$INDEX" --generation "$GENERATION" query mac
   ```

   成功输出必须包含 `opcode=0x0406`、`status=0x00` 和六字节 `data`。SDK／libws
   本地缓存、sysfs 或 daemon 对象不能单独替代这条控制器回复。

2. 为两只设备显式选择不同、且与已观察实验设备不冲突的六字节临时值。
   `ADDRESS` 使用冒号分隔格式；按输入字节顺序传输，不反转，也不套用
   Wi-Fi／Bluetooth 的分配位规则。零值和全 FF 会被拒绝；其余值仍由固件实际
   校验。不要把固件接受等同于正式公共地址、认证身份或全局唯一性。

   ```sh
   slkconfig --adapter "$INDEX" --generation "$GENERATION" runtime-address "$ADDRESS"
   ```

   此命令取得独占 Diagnostic lease，先查原值，再通过现有 Runtime 命令队列、
   credit 和提交票据发送 0x0405。真实 Complete 后，在同一原始 5000 ms 期限内
   发送新的 0x0406；匹配后才发布 Runtime 地址。检查输出的
   `NativeRuntimeAddressOriginal`、`NativeRuntimeAddressSetComplete` 和
   `NativeRuntimeAddressVerified`，保存原值、seq、generation 与实际抓包。

3. 每设置一只，都对另一只执行真实 `query mac`，确认未变化。两只全部核实后才
   启动 daemon，检查其公开对象与 Runtime 地址一致，再进行
   [发现验证](capture-and-check-discovery.md)及
   [连接后业务验证](check-business-roundtrip.md)。随机广播、Complete 或 NOCP
   均不能替代对端应用实际校验和回复。

每次注册最多一次地址修改。已使用的 Setup、Managed 占用、旧 generation、
无权限、固件拒绝、超时或读回不匹配都会失败；保留 stderr、退出码和捕获，停止
无线验收。不要修改校验、仅更新缓存、改用 libusb，或把失败重试当成已成功设置。
未核实的修改可能隔离 controller，不能宣称 Free／Ready。

结束时保存断链后的真实 0x0406。恢复原值也需要经过现有生命周期重新初始化，
取得新的注册身份，在未使用的 Setup 中设置保存的原地址，并再次真实读回；
原值不能从临时值推算。新注册不是冷断电，也不能证明固件已经清除全部状态。
恢复失败须明确记录，不能宣称还原。

分别记录设置后、断链后、软件复位后及固件重载后的读回。复位与重载若不可分离，
只报告合并观察；没有实际冷断电就标记未测。运行期通信成功不解决出厂重复地址、
正式配置来源、冷 ROM 自动选择或自然故障恢复。准确资格只读取
[当前能力入口](../../project/current-capabilities.md)。

核对作用范围时，按下表保留每个阶段的控制器回复，不将不同运行拼成一次通过：

| 阶段 | 所需证据与结论边界 |
| --- | --- |
| 设置后 | 同一原始期限内的 `0x0405 Complete`、更新后的 `0x0406` 和同行读回；本地缓存不足以证明设置成功。 |
| 断链后 | 关联实际 Down 的后续 `0x0406`；若另启 VM 或重新注册，单独注明身份变化，不能称为同一 generation 内观察。 |
| 复位／重载后 | 分别记录操作、ROM 归属、上传与新 Runtime；只能观察到组合操作时，不能回答单独复位是否保留地址。 |
| 恢复原值 | 使用本轮保存的原始六字节值，核对真实读回及同行不变；恢复为相同原值也不证明两块板具有唯一生产身份。 |

保留编译产物和执行工具的各自身份。暖态业务运行没有当次 ROM 上传时，明确记录
该缺口；先前维护运行的上传不能被直接继承为当前执行镜像认证。已有长度或生命周期
记录继续绑定原产物，不因地址复验、工具改名或文档更新转授给整个最新 HEAD。

既有实验 runner 可将显式运行期地址配置作为普通 socket 基线或 `slktest` benchmark
的共同前置步骤。benchmark 使用自己的 `rate`、`window` 或 `duplex` 门禁，不同时开启
基线 socket 验证开关；端口、E／USB、真实设置与读回检查仍相同。允许组合入口不代表
这些负载已取得 E 实机资格：仍须核对准确产物、随机载荷、对端应用回复及双方捕获。
地址成功不能覆盖业务失败、未执行的场景或缺少的终态证据。

若使用单独的维护镜像观察复位／RAM 重载，先在无 USB VM 中验证启动和抓包屏障。
Native 驱动完成退休前不得直接访问传输端点。进入 ROM 后，重新核对本次端口、
序列号、两端点描述符和实际 VM 所有者，再允许已选定镜像下载；主机侧 `usbfs`
占用只有在精确关联到本 VM 的实际 fd 时才属于该 VM，不能据名称判断可抢占。
重枚举中 sysfs 的 `ENOENT`／`ENODEV` 只能在原有等待期限内重新观察，不能当成
ROM、固件加载或恢复成功；权限及其他 I/O 错误仍须原样失败。保存全部失败，
重新加载后分别以真实 HCC 和 `0x0406` 取证，不将镜像文件 hash 当成下载证据。
