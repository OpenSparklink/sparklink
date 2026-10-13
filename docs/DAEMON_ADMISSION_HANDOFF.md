# WS73 daemon 交权期间的业务 admission

<!-- documentation-scope: 20261014 -->
> **阅读范围：历史审计／验收资料。** daemon 交权准入与另一只设备隔离的限定证据。
> [主题归纳与去向](project/uppercase-document-guide.md)；[推荐入口](CURRENT_CAPABILITIES.md)。
> 原文中的源码、失败、PASS 与命令仅适用于其记录版本；当前资格以 [CURRENT_CAPABILITIES](CURRENT_CAPABILITIES.md) 为准。

生产修复 U0acafc943f94，真实门禁与本轮实际编译服务 Uac3bbf33e392；内核
K060011963b5e/current K4ee4af55f38c，固件仍 combined-1.10.111。实验只在 VM。

此前业务提交对每设备 authority 使用 `lock_owned().await`。若 cancel 已
持有 guard 并等待原回复排空，后来 RPC 会排在 guard 后；交权完成后可能
在新凭据下继续执行，调用者不能据原调用时刻判断其 admission 的管理轮次。
现在使用 `try_lock_owned`，guard 被占用时立即返回 D-Bus Failed：
`device management admission or handoff busy`。调用者须显式重试；不会为
该 RPC 建立后台等待或在新管理权下补交。取得 guard 后原 present/accepting/
token、真实 snapshot/recipe/ioctl 及 guard 持有范围不变，独立设备不共用锁。
四个业务方法与初始化只读查询使用相同 busy 原因，查询实际结果和 management
仍可在 handoff 中观察原内核状态。没有新增成功 Complete 或修改 radio 来源。

## 实机与源码复核

完整 Rust workspace/all-features、严格 all-target/all-features clippy、355项
工具测试通过。新增 `/dev/null` 真实 ENOTTY/busy 回归证明业务 guard 不等待
后继管理权、busy 不触达请求构造、同行独立，不能替代 USB 实机资格。
单文件 fixture 首次因缺少 PYTHONPATH 导入失败，按工具既有路径配置重跑后
通过，原报错保留；拒绝条件未放宽。

VM70 已正常退出，独立核对 capture、host 暂留计数/原回复 SHA、完整 RF 和
冻结 inputs，并与 guest/parent 逐项封存 proof 一致：

- 普通 UID1000/caps0 的 CLI 启动扫描，实际成功1001参数回复在专用 QEMU
  host IN81 暂留，原请求由真实内核撤销为 Cancelled/-ECANCELED。管理查询
  仍为 Revoking，不能提前确认交权完成。
- 第二个 cancel 被拒绝，广告 ON/OFF、扫描 ON/OFF、广告/扫描初始化 OFF
  六个独立 CLI 均 busy；耗时7.85–8.79ms，没有业务 Accepted/成功 result，
  完整原始暂留区间没有这些 RPC 的额外命令或 Complete。原取消 CLI 仍等候
  原 reservation，原 Cancelled 历史可读，同行自己的原扫描结果保持 On。
- 原调用到放行332.98ms，保持原500ms期限，门禁仍拒绝达到400ms的放行。
  放行的是原178字节成功回复，未重放/改写；清理与重获 Managed/owned Held
  后，实际新扫描 START/STOP 成功。同行注册、slkd PID与 authenticated bus
  全程保持。不能将原 Cancelled 改为业务成功。
- 同一新镜像初段 RF20 与后段 RF2通过，随机数据/地址/RSSI在10秒内匹配；
 1191包/零drop/taint0/QEMU0。后段重新注册来自单次**人工 guest bulk 错误**，
  与自然故障自动恢复、物理拔插、默认四设备并行资格分别记录。
- 同镜像前置 Setup release/最后关闭/dup 零radio命令门禁也重新核对；这只
  支撑 untouched Setup 的安静撤销，不能替代部分初始化的整套 fd/在途矩阵。

[公开 receipt](evidence/ws73-daemon-handoff-admission-real-20261012.json) SHA256
`e54ad1f158ef9378ff4fd398e4e0bb36d6cb6640e2bb38371fa9c4ebce844f99`。
[生产提交CI38176146086](https://github.com/OpenSparklink/sparklink/actions/runs/38176146086)
和[工具/编译提交CI38176169984](https://github.com/OpenSparklink/sparklink/actions/runs/38176169984)
各九项最终成功；CI不授予自然故障或完整 Managed 资格。

历史 first-step/never-selected/last-close/dup 证据的 K4ece91aa5c7c，与实际
K060011963b5e/current K4ee4af55f38c 的 `net/sparklink` 和 canonical UAPI
对象哈希完全相同；之后变化仅 selftests/QEMU诊断。历史后续步骤九例也实际
使用 K060011963b5e。保留这些证据的原门禁范围，不倒填为本轮 daemon 方法或
完整并发验收；source audit 在公开 receipt 中。既有失败和回复缺失保持原样。

## 复现与剩余范围

准备含新 daemon、匹配签名模块、专用成功回复暂留 QEMU 与 default policy
的新 Native PREPARED。工具拒绝复用不匹配 frozen inputs 或混入其他 held gate：

```sh
python3 tools/ws73_target.py run --prepared <fresh-native-prepared> \
  --output <new-evidence-directory> --ports 1-2.1.1 1-2.1.4 \
  --timeout 450 --fault-recovery --setup-release-verify \
  --daemon-hold-case cancel-admission
```

先等 producer/QEMU 正常终止，再用 `ws73_daemon_hold.corroborate` 与
`corroborate_recovery` 独立重算；不能从 console PASS 或不完整输出认定成功。
剩余 result/event/权限与全部 RPC 组合、强杀 daemon 的接任、当前镜像物理
拔插、四设备默认并行、自然启动/重枚举/消失根因、每设备有限非人工恢复及
完整 S0–S6仍开放。正常VM70/维护20、四设备9/默认资格0；部分成果不关整项。
