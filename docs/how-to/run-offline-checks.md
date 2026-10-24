# 运行不访问硬件的开发检查

本页的操作可以在主机运行，不安装内核、不加载模块、不访问 WS73。
在 SparkLink 仓库根目录执行。

## 用户态检查

使用当前保留资格构建的 Rust 1.96.1 工具链（其他版本作为独立前向兼容检查）；完整用户态测试还需要 `dbus-daemon`。
以下命令创建私有测试总线，不部署系统服务：

```sh
cargo +1.96.1 fmt --all -- --check
python3 tools/build_resources.py -- cargo +1.96.1 check --locked --workspace --all-targets --all-features
python3 tools/build_resources.py -- cargo +1.96.1 test --locked --workspace --all-features
python3 tools/build_resources.py -- cargo +1.96.1 clippy --locked --workspace --all-targets --all-features -- -D warnings
```

## 控制本机主线程构建资源

本工作区的共享入口默认最多12路，与真实设备 VM 回归并行时最多8路；CPU affinity
不足时再下调。`make build/check/test/clippy` 已接入同一预算及 workspace 文件锁，
避免多个主线程构建各开12路。直接 Cargo 命令可改用：

```sh
python3 tools/build_resources.py --record "$NEW_BUILD_RECORD" -- cargo +1.96.1 check --workspace --all-targets --all-features
```

同一时刻有真实设备 VM 回归时加 `--with-vm`；通过 make 或 bundle/prepare 脚本运行
时设置 `SPARKLINK_BUILD_WITH_VM=1`。`SPARKLINK_BUILD_JOBS` 可显式下调，现有
`CARGO_BUILD_JOBS` 必须与它一致；冲突直接拒绝，不静默另开一个预算。
锁被其它构建占用时，等待其结束再重做，不能另开绕过锁的12路构建。历史冻结脚本
不受新锁保护，运行它们时须自行串行；不要把已接入的根 Makefile 再套一层 wrapper。

占用错误附带同一锁文件的 device/inode、最后一次获取的 supervisor PID、启动身份和
可见内核锁表。记录不包含命令参数或环境；PID namespace 或权限可能使持锁者不可见。
这些都是诊断线索，不能据此释放锁：子进程继承的 fd 可在 supervisor 退出后继续持锁，
而旧元数据也可留在已经释放的文件中。不要删除或重建锁文件，也不要仅凭 PID 消失
终止其他任务；真正的准入条件仍是对原 inode 成功取得 `flock`。
若 stat 与内核锁表中的 device 编号不同，错误中也保留同 inode 的候选行。
inode 数值可在不同文件系统重复；候选行必须再用实际 fd／路径独立确认，不能当作持有者。

内核编译使用已配置的固定开发 `O=` 目录，例如本工作区
`.dev/session-wake-kernel-build-v1`；每次源码提交不更换路径。直接内核 make 可用：

```sh
python3 tools/build_resources.py --record "$NEW_KERNEL_BUILD_RECORD" -- make -C "$KERNEL_SOURCE" O="$KERNEL_BUILD" LLVM=1 RUSTC_BOOTSTRAP=1 BINDGEN="$BINDGEN" bzImage modules
```

该命令只编译，不安装或运行驱动。Native bundle 的 Cargo target 默认固定于
workspace `.dev/cargo-native-dev`，可用 `--build-dir` 指定另一稳定的配置目录。
资格产物与 manifest 另行封存后才能复用开发目录；不要修改旧记录、prepared 根或
历史工具来套用新默认值。新记录保留实际jobs、CPU/affinity、可用内存及完整命令，
构建来源、配置、工具链和后续 VM 门禁仍须另外核对。构建资源记录不授功能资格。

内核 ABI 和部分工具测试需要匹配的 Linux 源码或 CI 中的固定 UAPI 提交；
不要用另一版本的头文件解释结果。

## 形式化与证据工具

具体模型、实际生产函数的映射、依赖及未证明范围，请查看
[验证入口](https://github.com/OpenSparklink/sparklink/blob/670674736ac90ec0f89ca0330849e22b1bc8f81b/formal/README.md)。
运行前核对所选模型的当前实现和预算，不将工具安装自检当成协议性质证明。

离线模型、合成后端和人工故障注入各有资格边界。需要真实 USB/HCC/对端业务
证据的事项，继续使用 VM-only 的独立实机门禁。

## 核对已封存的退休 ioctl 收据

先取得匹配的 VM run、prepared 根及其 manifest，设置 `RUN_ROOT`、`PREPARED_ROOT`，
将 `KERNEL_COMMIT`、`USERSPACE_COMMIT` 设为准确的40位编译提交，`NEW_RECEIPT_REPORT`
设为尚不存在的新文件。以下步骤只读已封存材料，不运行驱动或访问设备：

```sh
python3 tools/ws73_raw_uapi.py --run "$RUN_ROOT" --prepared "$PREPARED_ROOT" --kernel "$KERNEL_COMMIT" --userspace "$USERSPACE_COMMIT" --output "$NEW_RECEIPT_REPORT"
```

检查输出的有限范围、每角色/每设备收据和负对照。缺少收据、实际 probe、hash不符、
源身份不符或退出非零均应失败，不能用旧83项报告代替当前101项ENOTTY/303检查。
该收据只说明实际guest C探针的结果；业务交付仍须另外核对对端应用和双端捕获。
无法取得私有prepared根或原始材料时，保持未核验，不用日志截图补成PASS。


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

包含监督器修复 `c39a1765fc60` 的 checkout 会先写入未合格报告，再读取 Git、源码
及工具身份。外部元数据命令各有30秒原始期限，超时保留分阶段日志并拒绝资格；
监督器只终止自己创建的命令进程组，包含持有输出管道的取数子进程。
这不说明历史 CI 取消的根因已查明，也不允许省略身份、放宽 fuzz 预算或覆盖旧失败。
