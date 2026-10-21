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
