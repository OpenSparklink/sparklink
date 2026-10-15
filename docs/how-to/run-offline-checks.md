# 运行不访问硬件的开发检查

本页的操作可以在主机运行，不安装内核、不加载模块、不访问 WS73。
在 SparkLink 仓库根目录执行。

## 用户态检查

使用当前保留资格构建的 Rust 1.96.1 工具链（其他版本作为独立前向兼容检查）；完整用户态测试还需要 `dbus-daemon`。
以下命令创建私有测试总线，不部署系统服务：

```sh
cargo +1.96.1 fmt --all -- --check
cargo +1.96.1 check --locked --workspace --all-targets --all-features
cargo +1.96.1 test --locked --workspace --all-features
cargo +1.96.1 clippy --locked --workspace --all-targets --all-features -- -D warnings
```

内核 ABI 和部分工具测试需要匹配的 Linux 源码或 CI 中的固定 UAPI 提交；
不要用另一版本的头文件解释结果。

## 形式化与证据工具

具体模型、实际生产函数的映射、依赖及未证明范围，请查看
[验证入口](https://github.com/OpenSparklink/sparklink/blob/670674736ac90ec0f89ca0330849e22b1bc8f81b/formal/README.md)。
运行前核对所选模型的当前实现和预算，不将工具安装自检当成协议性质证明。

离线模型、合成后端和人工故障注入各有资格边界。需要真实 USB/HCC/对端业务
证据的事项，继续使用 VM-only 的独立实机门禁。

