# Native WS73 默认观察者权限

<!-- documentation-scope: 20261014 -->
> **阅读范围：历史审计／验收资料。** 普通观察者的权限参数与真实回归记录。
> [主题归纳与去向](project/uppercase-document-guide.md)；[推荐入口](reference/interfaces.md)。
> 原文中的源码、失败、PASS 与命令仅适用于其记录版本；当前资格以 [CURRENT_CAPABILITIES](CURRENT_CAPABILITIES.md) 为准。

生产策略 U09fe426773cf，独立角色门禁与本轮实际编译服务/工具
Uf572f7890d42；内核 K060011963b5e/current K4ee4af55f38c。固件保持
combined-1.10.111，实验仅在 VM，无主机安装、权限变更、USB reset 或切电。

此前新 Native 只读方法未加入默认 observer allowlist。特别是 WS73 的
`slctl show` 会读取 `GetDiscoveryPolicy`，所以不在 control group 的观察者
不能完整显示状态。现在只增加三个精确的 `org.sparklink.Adapter` method-call
规则：

| 方法 | 允许观察的依据 |
| --- | --- |
| GetDiscoveryPolicy | 当前注册不可变的发现参数；不发硬件命令 |
| GetManagementStatus | 实际内核管理状态的非消费查询；不返回 lease |
| GetInitializationOff | 当前有效原 op5/6 结果；校验注册/内部管理权/所属domain，不提交或补造 OFF |

公开 management 的 owned flag 描述 daemon 的实际控制 fd；观察者不因此取得
kernel authority。初始化查询继续要求原结果和内部出处有效，业务使用后拒绝，
不能凭“允许读”恢复旧凭据或缓存 Off。raw token、capability、chardev/capture
权限与服务名 ownership 均未授予观察者。广告、扫描、取消、Properties.Set、
interface-less、未分类未来方法、敏感读与 remote 操作仍由原精确策略拒绝。

## 实机与完整参数核对

VM71 已正常终止，实际普通角色 observer UID/GID1001、control UID1000/
主GID1002/附加sparklink GID1000，caps0。使用实际安装的生产策略和 EXTERNAL
认证 system-type 隔离总线，同 slkd/bus，真实双设备：

- RF前、RF20/guest-only退役重注册/RF2后分别执行两个角色。通过 well-known
  service 与它实际的 unique owner 读取不可变 policy、token-redacted 管理状态。
- 初段16项初始化观察均保留原请求ID/op5或6，并与实际普通历史查询完全一致。
  完整49/8字节参数、enable/OFF顺序、实际选中功率和真实成功Complete从USB
  捕获独立核对。初始化 wire proof 已复用同一核对函数，无第二套判断。
- 后段两个domain均被真实业务使用，初始化观察返回原实际UnknownObject/
  `initializer provenance absent or invalidated`，不是AccessDenied，也没有
  新提交或cached成功。观察者 `show`/`management` 前后均完整成功。
- 观察者共68项实际bus拒绝（每次17项）：包括取消、广播扫描、unique-owner写、
  interface-less读写、敏感操作、未来方法和服务名占用。control的服务名占用
  另4项均拒绝。观察者前后对两只检查均无直接chardev/usbmon读写权限。
- 两段完整角色窗口均零设备命令，成功读和拒绝写均未修改硬件。daemon/同行
  注册保持，普通control的20+2轮随机数据/地址/RSSI在10秒内匹配全部通过。
  共1265包、零drop、taint0、QEMU0；没有注入或物理拔插动作。

[独立封存 receipt](evidence/ws73-default-observer-policy-real-20261012.json)
SHA256 `8c7ddc7f281fc378f2a72bc9cc2f94b63ecb2bdfa8361497a153e68a19f9ce69`。
parent/guest的RF22及角色proof逐项独立重算，冻结源码、程序、策略和模块输入
再次检查。生产[CI38177321606](https://github.com/OpenSparklink/sparklink/actions/runs/38177321606)
与工具/编译[CI38177363887](https://github.com/OpenSparklink/sparklink/actions/runs/38177363887)
各九项最终成功。完整Rust/all-features、严格all-target/all-features clippy及
360工具测试通过。角色客户端最初编译因dev依赖缺失及14元组无PartialEq失败，
加入仅dev使用的serde_json并作无损序列化比较后重跑；不改变生产结果或拒绝
条件。合成fixtures只证明核对器拒绝边界，不授予真实权限或空口资格。

## 复现及剩余范围

按Native prepare工作流建立含新策略、角色客户端、新daemon和匹配签名module/
QEMU的**新**冻结镜像，随后独立运行：

```sh
python3 tools/ws73_target.py run --prepared <fresh-native-prepared> \
  --output <new-evidence-directory> --ports 1-2.1.1 1-2.1.4 \
  --qmp-hotplug --observer-policy --timeout 450
```

此模式拒绝与注入、Managed/held gate、initializer-lifecycle、四设备或自定义
策略混用。guest监督器只在VM内切换真实角色；客户端自身始终ordinary/caps0。
producer终止后使用 `ws73_observer_policy.corroborate`、`corroborate_passthrough`
与完整capture独立重算，不能仅凭console PASS或未完成输出认定成功。

这限定验收当前Native发现方法与真实角色策略，完整Backend/Proxy/SSAP/PDU/
Security、所有event/result/权限并发及daemon强杀接任仍开放。QMP重注册仍不能
算物理拔插或自然故障自动恢复。正常VM71/维护20，四设备9/默认资格0；历史
失败、未查明根因/非人工恢复、完整Managed及S0–S6/原28项均保持OPEN。
