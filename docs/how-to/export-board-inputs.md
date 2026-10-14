# 导出 WS73 板级输入候选

目标是得到可审计的运行配置字节及 provenance，不是取得硬件资格。前置条件：匹配 SDK 的 INI、当前 `tools/ws73-board-config.py`、Python，以及一个尚不存在的输出目录。SDK、校准与固件由使用者合法取得，不随本站分发。

从用户态仓库根目录执行，先将 `SDK_INI` 指向输入文件：

```sh
python3 tools/ws73-board-config.py --ini "$SDK_INI" \
  --output-dir "$OUTPUT_DIR" --board ws73-sdk-default-unverified \
  --usb-link-check 0
```

`OUTPUT_DIR` 必须是新的目录；例中的 link-check=0 只是候选，必须核对部署配置的编译开关后选择 0 或 1。板名记录出处，不认证兼容。

检查结果：`bsle_custom.bin` 为 140 字节，`pm_config.bin` 为 4 字节；JSON manifest 应记录输入、工具和输出 hash。它们不是包含 ASCII SHA-256 头的启动镜像。字节布局通过不表示 USB、BSLE、DLI 或空口通过。

失败处理：不要覆盖旧候选。缺字段、重复字段、超范围或 flash 模式须修正输入后在新目录重试；flash 校准及地址不能由 efuse 导出器还原。不要将候选直接刷到主机硬件。后续打包与驱动加载仅在隔离 VM 中进行。

[原始输入依据及历史步骤](../../project/reference/environment/ws73-board-configuration.md) 保留；以 [当前资格](../../project/current-capabilities.md) 判定实机范围。
