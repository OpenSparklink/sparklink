# 为 WS73 回归准备隔离 VM

目标是冻结一组可追溯的 VM 输入，而不是安装实验主机内核。前置条件：匹配源码与配置的 kernel build、签名模块依赖树、成功的 scratch-root boot 报告、准确提交编译的 service bundle、两只可区别的真实 USB 设备，以及合法取得的固件／校准／板级输入。

1. 从 [当前资格](../CURRENT_CAPABILITIES.md) 取得准确源码对；历史通过只作对照。若测试最新源码，建立新的资格记录。
2. 核对内核配置、模块 vermagic／签名、bundle 及固件 hash。保持独立输出目录，记录 QEMU 版本和 USB 拓扑。
3. 在 runner 的 VM profile 中同时提供 `native_module_tree`、`native_boot_smoke`、`native_service_bundle`。`tools/ws73_vm_native_root.py` 是内部 staging 模块，不是可直接运行的部署 CLI。
4. 在 VM 启动和模块门禁通过后再接入真实设备。逐个核对 controller index、generation、USB 身份与 Ready，不能把 Installed 或 transport 可用当作 Ready。
5. 在 VM 内使用普通用户应用进行业务门禁；管理／捕获权限独立配置。保存 console、控制请求和两端 USB/HCC/应用证据。

结果检查：所有输入固定身份；VM 内两个独立 Runtime；主机没有安装服务、加载实验模块或执行直接 USB 协议 I/O。空 USB 启动成功不算真实双设备通过。

失败处理：保存首次启动 panic、超时、枚举丢失及失败输出；停止本次资格传播。重新启动、人工拔插、hub 切电或 QMP 操作只记录为干预，不宣称自然恢复。不要重用旧成功输出目录。

本页给出准备契约；完整 runner 参数随源码变化，运行前核对选定提交的 `--help`。历史环境和原生主机安装步骤见 [旧记录](../WS73_TARGET_ENVIRONMENT.md)／[原生 lab 历史](../WS73_NATIVE_LAB.md)，其中主机安装不属于当前允许操作。
