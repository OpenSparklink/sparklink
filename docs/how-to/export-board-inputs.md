# 导出 WS73 板级输入候选

目标是得到可审计的运行配置字节及 provenance，不是取得硬件资格。前置条件：匹配 SDK 的 INI、当前 `tools/ws73-board-config.py`、Python，以及一个尚不存在的输出目录。SDK、校准与固件由使用者合法取得，不随本站分发。

从用户态仓库根目录执行，先将 `SDK_INI` 指向输入文件：

```sh
python3 tools/ws73-board-config.py --ini "$SDK_INI" \
  --output-dir "$OUTPUT_DIR" --board ws73-sdk-default-unverified \
  --usb-link-check 0
```

`OUTPUT_DIR` 必须是新的目录；例中的 link-check=0 只是候选，必须核对部署配置的编译开关后选择 0 或 1。板名记录出处，不认证兼容。

更换模块后，先记录每个物理端口的板名、芯片型号、型号信息来源、USB 身份及实际
DLI 地址，再选择适用的固件、校准和运行配置。相同 VID/PID 或启动成功不能认证
Hi3873E 与 Hi3873U 的固件、校准及板级配置通用。端口号可复用，旧模块在该端口
取得的资格不能转移给新模块；混合型号的测试应分别记录两端身份和限定结果。

检查结果：`bsle_custom.bin` 为 140 字节，`pm_config.bin` 为 4 字节；JSON manifest 应记录输入、工具和输出 hash。它们不是包含 ASCII SHA-256 头的启动镜像。字节布局通过不表示 USB、BSLE、DLI 或空口通过。

新 native bundle 和显式板型的 VM 准备过程会重读原始 INI，使用当前导出器重新编码，
核对参数、manifest 和两个实际文件。保留 INI 及整个候选目录，不能只复制两个 bin。
导出器、INI 或参数改变时，在新目录重新导出；不要修改旧 manifest 冒充原候选。
真实启动及每次单设备重新直通前，还会复核候选与 guest 中两处实际固件目录。
输入一致性通过不授予板型兼容、已装载镜像或冷启动资格。

失败处理：不要覆盖旧候选。缺字段、重复字段、超范围或 flash 模式须修正输入后在新目录重试；flash 校准及地址不能由 efuse 导出器还原。不要将候选直接刷到主机硬件。后续打包与驱动加载仅在隔离 VM 中进行。

若两只设备的 USB 身份不同，却查询到相同的 DLI 本地地址，停止双设备门禁并保留
各自的原始查询、HCC、镜像 hash 和抓包。HCC 型号正确、Native Ready 或板级文件
布局正确均不能替代业务验收；不要放宽不同地址断言或尝试烧写 eFuse。
明确授权的运行期实验可使用[临时地址配置](configure-experimental-ws73-addresses.md)，
经真实设置及读回后单独验收；这不解决厂商地址来源或正式配置契约。

后续诊断内核的只读 `sle_address_source` 观察针对固定 SLE eFuse 字段，不是地址
配置接口。使用它时仍须把准确 kernel/module、实际 HCC 请求/回复、DLI 地址及
当前 generation 分别封存。错误状态的输出不应作为地址公开；全零也不能表示
读取有效、合法分配或已查明重复地址原因。离线 codec 检查不能代替新 VM 的
固件回复与初始化证据；此诊断不会解决或绕过不同地址门禁。

[原始输入依据及历史步骤](../../project/reference/environment/ws73-board-configuration.md) 保留；以 [当前资格](../../project/current-capabilities.md) 判定实机范围。
