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


## 对生产 C codec 重放语料和短 fuzz

先取得包含 `ddea575bff55` 自测的匹配 Linux checkout，以及Clang/libFuzzer、ASAN/
UBSAN、同版本llvm-profdata/llvm-cov、nm。以下只调用纯codec，可在宿主运行，
不加载驱动或访问USB；实验驱动/实机仍须VM-only。绝不能将畸形输入发给真实设备。
在Linux checkout执行：

```sh
python3 tools/testing/selftests/sparklink/fuzz/test_ws73_codec_verdict.py
python3 tools/testing/selftests/sparklink/run_ws73_codec_fuzz.py \
    --output /tmp/ws73-codec-fuzz-new-run --runs 20000 --seed 730111
```

输出目录必须全新；`CC`、`LLVM_PROFDATA`、`LLVM_COV`可选择对应工具。
检查report.json中的完整终态、实际目标函数执行计数、准确源码/工具、每阶段退出
和语料hash。`BOUNDED_FUZZ_COMPLETED_NO_FINDING`只表示本次有限探索未发现问题，
不表示实现已证明、内核sanitizer已运行或硬件通过。报告失败或不完整时保留原目录；
缺工具、超时、诊断、缺少原始输出和截断结果均不能PASS。

LSan在ptrace沙箱内可能工具失败。保留该失败，在获授权的普通进程环境中另建输出
目录重跑，不关闭检测器。保留输入种子、扩展corpus、二进制、原始日志与coverage；
确认缺陷应最小化并补固定回归，重跑不能覆盖旧失败。
[完整范围与排除项](https://github.com/OpenSparklink/linux/blob/ddea575bff556d3884375603edd9003b1cc5ffc4/tools/testing/selftests/sparklink/fuzz/README)。

独立CI按固定内核提交执行PR短探索，定时执行较长探索，上传全部结果artifact。
CI的Clang18属于独立环境；记录其实际版本，不能自动继承本机Clang22资格。
内核codec/harness变更须评审更新该workflow的固定pin，否则不能声称CI覆盖了新源码。
