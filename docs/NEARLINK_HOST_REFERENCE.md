# OpenHarmony NearLink Host 参考与设计调整

用户提供的本地参考：`../communication_nearlink_service`。核验基线为
`f0872dfaac33ffa99b80b352f6c05fba2df6414e`，origin 为
`https://gitcode.com/openharmony/communication_nearlink_service.git`；检查时工作树无修改。
README.OpenSource 声明 Apache-2.0，源码有相应许可头。本次只读取与记录事实，
没有复制参考代码到 Linux 或 Rust crates。逐文件复用须单独记录许可、来源和依赖。

这是覆盖 DLI、连接管理、数据传输、安全、SSAP 与 Profiles 的 Host 源码参考。
本次未构建或运行 OpenHarmony 服务，也未验证其 WS73 互通；“有实现”不代表
本项目已有协议、硬件或标准认证证据。

以下路径均相对于参考仓库。完整 hash 清单见本地开发证据
`.dev/nearlink-host-reference.json`（工作区根），不把本地文件 hash 当作实测结果。

| 已读取来源 | 观察 | 本项目决定 / 对应 issue |
|---|---|---|
| `services/stack/src/dli/interface/dli_opcode.h` | SetEventMask=0x0401，ReadLocalBuffer=0x0402，ReadLocalVersion=0x0404；状态与完成事件不同 | 增加 OpenHarmony reference profile 对照；与本地 T/XS 10003 V1.1 的冲突必须显式映射。不据参考自动判断 WS73 方言。K#11/#13/#16 |
| `services/stack/src/dli/interface/dli_event_struct.h` | Buffer 返回 ACB/ICB 长度与数量，version/company/subversion，独立 capabilities | Ready 查询按 dialect 解码，并保留 unknown，不能把 USB 枚举或回调成功当 Ready。K#10/#15/#16 |
| `services/stack/src/dli/layer/src/dli_layer.c`、`dli_layer_config.c` | pending command、command count、10s 命令 timer、按 lcid 重组；核心为静态 g_info | 借鉴流程，不照搬全局模型和超时常量。每 controller/generation 独立 pending/credit/reassembly；迟到事件必须隔离。K#3/#4/#17 |
| `services/stack/src/dp/dtap/interface/dtap_tcid.h` | SLE CMTC=0x02、SMTC=0x0A、默认数据=0x1F，动态单播范围 0x80–0xDF，TCID 为 uint8_t | 与本地 TCID 标准交叉核验；区分 TCID 与厂商 envelope/LCID，测试 local/remote TCID 映射。K#6/#17 |
| `services/stack/src/cp/bsl/sle/servm/ssap/include/inner/ssap_pkt.h`、`src/ssapc_client.c`、`src/ssap_link.c` | ExchangeInfo、min MTU/version、1.3 fragment/multiProcessing 扩展、独立重组 timer | 本地标准基线为 V1.2.0；先实现经标准确认的协商与降级，1.3 只作为待核验扩展，不提前宣告支持。SSAP 分片与 ACB 分片各自测试。U#3、K#6 |
| `services/stack/src/cp/bsl/sle/sm/src/sm_slink.c`、`sm_numcmp.c` | 安全上下文关联 lcid；不同方法状态机、用户确认与密钥安装 | 连接级机制/Agent policy 边界保持既定设计；参考完整失败与确认路径，不继续使用全局安全状态或 fingerprint 代替 credential。K#7/#18、U#5 |
| `services/stack/src/cp/bal/profile/bas/include/nlstk_bas_def.h` | Battery service=0x060A，percentage attribute=0x1034 | 与已查本地 30011 一致，修复旧 Bluetooth UUID，补真实 PDU/Profile 测试。U#3 |
| `services/hardware/src/SleDliLayerAdapter.cpp`、`services/hardware/BUILD.gn` | HAL 调用外部 HDI ISleHciInterface；全局实例；service death/reset 使用 SIGKILL；依赖 HDF/IPC/FFRT | 不能直接当 Linux USB 驱动。Linux Native driver 与 vendord Proxy 独立实现；故障只影响对应 controller。K#9/#10/#12，U#7 |
| `services/stack/src/dli/sapi/src/dli_sapi.c`、`dli_data_stub.c` | 真实 HAL 初始化等待与 NEARLINK_SERVICE_STACK_LOCAL_TEST 条件桩分开；桩模拟回复和分片 | 新测试 manifest 必须记录真实 HAL/桩路径。桩测试只能证明软件，不计入 WS73 RF 验收。K#19 |
| `services/stack/BUILD.gn`、`services/stack/src/dli/BUILD.gn` | GN/OpenHarmony 依赖 SDF、securec、hilog、OpenSSL、硬件服务等 | 不假定普通 Linux 可直接构建。后续先隔离纯 codec 或构建独立参考 harness，实际运行后才称为差分测试。K#13/#19 |

## 方案变更

1. S0 增加来源版本与 dialect/feature 差异表。证据同时标注标准、参考源码、
   libws73 作者 capture、本项目 synthetic 和本项目实机，保持原 issue 验收要求。
2. S1/S2 Host 的 descriptor 显式记录 standard DLI、WS73 profile 与所选版本；
   不把三套 opcode 混成统一 enum。未知版本 fail closed 或仅提供受权 diagnostic。
3. S4 SSAP 首先交付本地标准基线，再测试旧版本协商/降级；reference 1.3
   扩展需新标准或互通证据，并受协商 feature gate 控制。
4. S5 安全用参考状态机检查方法覆盖与错误路径；密码学和凭据设计仍依据
   标准及本项目 kernel/userspace 边界，不搬用 OpenHarmony 的系统密钥依赖。
5. S6 增加差分测试矩阵：标准兼容样本、显式 dialect 样本、异常长度/乱序/
   超时/credit、两个 controller、真实 HAL 与桩路径。reference build 不可用时
   明确 SKIP，不能将源码比较称为互通 PASS。

WS73 优先级与 S0–S6 总顺序不变；不扩大到参考库的音频、测距等无关联 issue
的产品功能。参考复核不替代四设备实机与双端空口通信验收。

## WS73 实机方言与 libws73-usb / SDK 交叉核验

本地 libws73-usb 基线 `f4d85d0`（LGPL-3.0-or-later）继续作为线格式、
状态/完成分离、RF双端验收的参考，独立实现Linux/Rust代码，不搬用其
进程全局状态。`src/sle73/sle73_priv.h` 的0401是SetEventMask；
`src/sle73/sle73_discovery.c` 的 get_local_addr 返回SetPublicAddress后的
缓存，不能当作本项目真实0406查询成功。SetAdvParams与StopAdvertiser分别
发送0c02与0c05；本项目实机fresh实例stop返回1e，与OpenHarmony
`services/stack/src/dli/interface/dli_errno.h` 的UnknownAdvertisingIdentifier
相符，须核验创建实例的前置步骤，不能吞掉失败发布Ready。

用户授权检查的SDK `application/lib/v660/libsle_host.so` SHA256为
`020349f35db6598bbae3cb7be3acfe8dbc2757c3a1785a2f22f67ef43eb97803`，
`application/lib/stm32mp157/sle/libsle_host.a` SHA256为
`aa89e30ab798cf0cae2cea2684de66047c6858d571b02f5ed34d4cfb535dba8c`。
两者 get-public-address 构造0406时参数指针/长度均0。标准和OpenHarmony的
地址类型字节不适用于这一WS73调用：本项目实机旧参数00触发Hardware Error，
独立修正为零参数后四项元数据全通过、读到真实地址，但仍仅Setup。私有
库、反汇编和固件均留本地，不提交；来源事实、模型与本项目实测分开记录。

SDK `driver/bsle/sle_driver/sle_host_register.c::sle_recovery` 的重新customize/
SLE_OPEN/BOOT_FINISH为后续恢复流程参考；其全局HCC/device状态不符合本项目
多设备隔离要求，最小每设备暖启动切片已独立实现，完整自动恢复验收仍开放。完整设计与未通过项见
[WS73_RECOVERY.md](WS73_RECOVERY.md)。

## 固件版本对照与111基线

用户指定libws73-usb使用SDK后缀111。其`blobs/README`记录合并格式为
`cat ws73.bin wifi_cali.bin btc_cali.bin > combined-<版本>.bin`，三段各保留
64字节小写SHA256头，顺序固定，没有长度字段。当前本地SDK/us三文件
拼接后与110逐字节相同：`09865cf9c42addb064079ac0953ee39770d31e63eb27268813bdfc804016266f`。
上述实机启动与1e失败因此属于110，不倒填成111测试。

111参考blob SHA256：`7a9bb91d00a94fb8fc146fe17f73a78976bee9a5525303da2d6d4a3f8becaef3`。
独立工具先验证显式整包hash，再按三段各自hash定位边界，全部验证成功才
写入全新私有目录，保留原文件头与payload、不覆盖SDK、不提交二进制：

```sh
python3 tools/ws73_firmware.py \
  --combined ../libws73-usb/blobs/fw/combined-1.10.111.bin \
  --sha256 7a9bb91d00a94fb8fc146fe17f73a78976bee9a5525303da2d6d4a3f8becaef3 \
  --output ../.dev/firmware-1.10.111
```

验证拆出完整文件大小144604/21044/7740 bytes。`firmware-source.json`保留
整包、每文件和payload hash；`ws73_target.py prepare --firmware-dir`选择该
目录，原内核三文件加载路径无需改变。六项单元测试覆盖截断、改写、假内嵌
header、额外段/尾字节、空payload、hash拒绝及不覆盖。导入时111客体仅已准备。随后实机冷启动通过下载/BSLE，但在buffer
Complete的SLE subtype1处失败；当时尚未证明修复后完整启动；后续实际结果见下节。BSLE/PM板配置与
固件版本分开记录，板级校准/功率仍NOT_ASSERTED。

111新增实机抓包显示ReadVersion回复tag=a0，ReadBuffer回复tag=a1，后者
内部为合法A2/0002/op0402/status0/6-byte返回值。SDK
`driver/bsle/sle_driver/sle_hcc/sle_hcc_proc.c::sle_hcc_adapt_rx`不使用
sub_type，libws73-usb的`rx_slot_netbuf`/`is_data_header`按service/queue
识别SLE。独立修正只取消SLE RX的额外subtype==0约束，不修改TX或BSLE，
不扫描padding，仍验证全部slot和DLI长度。五帧实际捕获经生产C codec离线
复核通过；修复后的实机启动/广播尚未重跑。原始反例/抓包保存在本地
`.dev/ws73-real-111-standby`，零capture drops；不发布设备allocation padding。

## 111实测进展与版本边界

后续真实111已完成四项DLI查询与独立Ready。SDK CLOSE30/action3新ACK再
customize/open/BOOT_FINISH用于一次有界暖采纳，无hub reset或重新上传。
扫描初始OFF的0b在参数成功后仍复现；被动参数/ON/OFF三个Complete后
才建立OFF。真实20轮数据/RSSI/地址及零drop USB证据已按初始双设备阶段
单独复核；当前封存组合为当轮冷上传111的1-2.1.1与保留110的1-2.1.3。
两者DLI version tuple相同，不能据此推断两只都是111。完整拔插隔离曾失败，
自动恢复及设备消失根因未闭环，见[恢复与验收](WS73_RECOVERY.md)。


### 故障恢复参考：协议关闭与芯片复位是不同层级

继续核对 libws73-usb f4d85d0e95af2d0043432e1301fd2f6b660a4906：
`src/ws73_usb_control.c` 的 reset_device 使用运行态 register endpoints，
读 GLB_RST_CRG_CTL0(0x4001f118)，设置 mask0x10 后写回，等待 boot-mode
重新枚举；它不是 libusb_reset_device 的 USB 总线复位。两者不能混写。
`src/ws73_host_bridge.c` 另行按原路径重新打开并确认该路径有两个端点，
避免 wait_mode 被另一只已经 boot 的 WS73 满足。这支持恢复预算与确认必须
按物理端口记录的设计；不允许“任意一只复位成功”使当前 owner 恢复成功。

参考实现读寄存器失败时会退为只写 RST_MASK；本项目尚未实现/验证芯片复位，
不能据此执行未知寄存器写入或宣称恢复完成。下一层实现须保留原位、读失败
终止、先撤销当前 generation 并停止该 owner URB/worker、跨重枚举有限预算、
仅同端口确认 boot/runtime，然后完整重新查询并通过广播/扫描 OFF。不可复位
整个 hub，也不可把无 handle 的 Absent当作可以发命令的运行态故障。

进一步核对本地SDK的`hcc_usb_host.h::rw_reg_setup_bytes`及
`hcc_usb_host_ops.c::usb_rw_reg_send_setup`：运行态setup实际是16字节，
寄存器offset字段仅16位，长度4、读方向0/写方向1、stage1。因此参考库只
编码地址低16位与SDK字段约定一致，不能单凭高16位未发送就判定实现错误。
仍需确认固件端寄存器窗口映射；这不构成允许任意32位地址截断访问的证据。
仅独立实现已核验的固定寄存器操作，不新增任意地址读写的公共UAPI。

SDK的`plat_pm_board_ws73.c::ws73_board_power_reset_hcc`读取
`0x4001f118`失败后直接返回，成功才保留原值并设置`0x10`。本项目采用这项
失败边界。SDK工作态setup发送使用异步提交，共享寄存器buffer和重试循环；
本项目实现时须使用每设备buffer、串行完整事务、确认16字节OUT及4字节IN，
并让各阶段共享恢复截止，不能以提交成功或短读作为寄存器读取成功。

下一步资格验证依次为：固定寄存器只读及真实抓包，读失败/短写/短读均无复位
写入，撤销旧owner后一次有界读改写，观察同物理端口boot重新枚举，再执行
完整111上传/启动/查询与两项OFF。复位写OUT遇到NO_DEVICE只能记录结果不确定，
后续同端口重新枚举才是确认依据；不盲目重发复位。全过程由另外一只持续
进行随机广播/发现，验证其generation、控制权及slkd不变。原生Linux和QEMU
分别验收；枚举前缺失设备只能记录Absent，不能借用另一只设备的句柄恢复。
目前仅完成离线事实核对，尚未发送寄存器事务或启用芯片自动复位。

kernel92 的真实 QMP guest-detach 对照20+2轮已通过，但主机物理连接未掉线，
不会据此关闭物理根因或自主恢复 issues；详情见 WS73_RECOVERY.md。
