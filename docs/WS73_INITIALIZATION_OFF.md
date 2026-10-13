# WS73 初始化 OFF 出处与失败清理

<!-- documentation-scope: 20261014 -->
> **阅读范围：历史审计／验收资料。** 初始化 OFF 出处、失败清理和独立 owner 实测。
> [主题归纳与去向](project/uppercase-document-guide.md)；[推荐入口](CURRENT_CAPABILITIES.md)。
> 原文中的源码、失败、PASS 与命令仅适用于其记录版本；当前资格以 [CURRENT_CAPABILITIES](CURRENT_CAPABILITIES.md) 为准。

初始化请求已经由真实设备执行，但原 slkd 丢弃了 op5/6 的请求 ID；首轮失败
时，对业务尚未开启的扫描重复发 OFF，111 固件可能返回原生 0x0b。出处查询
用于读取仍有效的初始化结果，不能把 0x0b 转成成功或伪造新 STOP 的 Complete。

签名生产实现 U51158a8107d6、核对器 U7b1bd0464ec9：每次注册的管理对象仅保存
实际提交成功的 initializer generation、request ID、operation 和内部 lease。
lease 是内核按注册递增的管理凭据，既用于区分管理轮次，也保持私有；D-Bus
结果不包含该凭据。保存相关 ID 不等于保存成功，也不建立第二份硬件状态。

`org.sparklink.Adapter.GetInitializationOff(u32)` 只接受 op5 或 op6。
普通用户可以显式选择真实 adapter 后调用：

```sh
slctl --adapter /org/sparklink/slk0_g1 advertise initialized-off
slctl --adapter /org/sparklink/slk0_g1 scan initialized-off
```

查询期间持有该设备的 admission guard，读取当前 Ready WS73 snapshot、内核
管理状态和真实 discovery result，再读管理状态；同时核对注册仍 present。
generation、凭据或模式变化、管理撤销、结果 absent/evicted、radio Unknown/
Error/所属 domain On、Host fault、失败 state/errno/status 均拒绝。独立 domain
可以保持已知 On；不得将其状态误用为本 domain OFF 的否定或成功依据。
业务提交在 ioctl 前作废所属 domain 的初始化出处，即使后续 admission 失败
也不重新使用；cancel/handoff/removal 作废两份出处。新管理权不会恢复旧出处。

返回的是内核真实 `NativeOperationResult`：广告 op5 的最终 0c05、step1/2；
扫描 op6 的最终 1002、step2/3。op6 原有 recipe 是参数/ON/OFF 探测，只有
真实最终成功 OFF 才建立扫描 Off。输出保留原 ID/operation/selected power，
不改写为新 op2/4，也不提交命令。原 `SubmitStop*` 继续报告实际新请求的结果。

失败清理先区分有业务历史的 domain 与未开启的 domain。前者保留真实业务
STOP/查询或发实际新 STOP，后者只查询真实初始化出处；缺失出处使清理失败，
没有隐式重初始化或缓存 idle 降级。四设备核对器对所有初始化查询独立核对
完整参数/enable/OFF 顺序和原始成功 Complete，并验证业务后查询被拒绝。
runner 原 aggregate `STOP_CONFIRMED` 标签包括已有真实 Off 的再观察；具体
来源分别保存在 `stop_confirmations` 与 `initialization_off_confirmations`，
后者的 wire proof 明确 `new_stop_submission=false`，不能据标签宣称新 STOP。

## 回归与范围

严格 all-target/all-features clippy、Rust workspace/all-features 回归和 349 项
工具回归通过。合成整数/字节 fixture 只验证拒绝边界，不作真实空口证据。
首次 fixture 编译的长 tuple Debug 约束及工具缺失显式 capture targets 报错
保留在本地记录，修正后重新执行，未放宽拒绝条件。

精确查询提交 [CI38173504308](https://github.com/OpenSparklink/sparklink/actions/runs/38173504308)
与实际新服务/工具提交 [CI38173684866](https://github.com/OpenSparklink/sparklink/actions/runs/38173684866)
分别核对九项成功；CI 不授予真实设备资格。

新服务 U7b1bd0464ec9/K060011963b5e 的默认双设备回归在 VM 中已终止通过：
20轮交换角色，guest-only 退役/重注册后2轮，同 slkd/bus，普通 UID1000/caps0，
1265包/零drop/taint0/QEMU0。全部原始 RF/参数/策略查询与父进程封存证明独立
重算；[receipt](evidence/ws73-initialization-off-default-two-real-20261012.json)
SHA256 `07ec4e31560b4f8690e03a82dd5eac7337220a27ea498d861fe0ae4a416fda61`。
这条 RF22 保留已验证路径，未执行初始化查询或完整 Managed 验收，不扩大范围。

新四设备功率0、启动偏移0的 VM 已终止：第二组首轮在真实成功 Scan Complete
后10秒超时，第一组有一次真实匹配但等待共同 ACK，完整轮数仍0/0，原始整轮
FAIL保留。四只本轮失败清理均通过，独立封存12项真实 op5/6 查询及完整
initializer wire recipe、4项业务后出处拒绝、4项真实新业务 STOP；没有对
未用 domain 重发 OFF，也未把控制器失败改为成功。D1:AC/F9 查询广告初始化
OFF时各自扫描仍 On，所属domain/独立domain区分已经通过真实设备检查。

[首轮失败清理 receipt](evidence/ws73-initialization-off-first-round-cleanup-real-20261012.json)
SHA256 `d31525f3f5d0003acd4c67cbdbbeaeca2f2f4a5152f4679f735833957534600e`。
837包/零drop、QEMU0、同行有限abort无强杀，同slkd在清理后仍存活，失败分支
未输出taint，明确记未测。功率请求0/实际选中-2、全部完整参数和冻结inputs
独立重验；完整RF核对器仍拒绝。这只验收本次 initializer/query/失败清理
范围，不等于修复射频超时、完整并发或自动恢复。

正常VM累计68/维护20、四设备尝试9/默认资格仍0。后续还需
覆盖当前/旧 generation、管理撤销/release/最后 fd/dup/在途回复及同行隔离；
现有历史相应用例保留，不能从源码测试或 RF22 扩展为本 API 的完整矩阵。
默认并行、完整 Managed、物理拔插、自然根因与不依赖人工拔插的自动恢复及
完整 S0–S6/原28项 issues 继续开放，历史三例失败不改写。

## 管理权、真实结果淘汰和 guest generation 的独立验收

工具提交 U232c3b3a702b 新增单独的 `--initializer-lifecycle` 模式；仅允许
默认配置的 Native VM 与 `--qmp-hotplug`，拒绝与注入、其他 Managed gate、
四设备或自定义策略混用。353 项工具回归通过，合成 fixture 仍只验核对器。
实际 daemon 保持 U7b1bd0464ec9、内核 K060011963b5e，测试工具的新 HEAD
不能冒充本轮编译服务版本。生产源码和策略文件冻结哈希分别重新核对。

真实双设备 VM69 已正常终止并独立重算原始 USB capture：

- 初始真实 op5/6 结果可查询；目标 `cancel-discovery` 完成撤销/重获管理权后，
  两个 initialized-off 查询都被拒绝。旧 op5/6 普通历史查询仍保持原 ID 和
  operation，不能凭“历史仍可读”恢复旧管理轮次的初始化出处。目标 handoff
  没有重复提交 radio 命令。
- 另一只 WS73 的真实扫描保持 On，目标交接期间没有同行扫描控制命令；
  同行未使用的广告初始化 OFF 仍可查询，随后真实扫描 STOP 成功。
- 完成初段 20 轮角色交换后，只用 QMP 退役/重加目标 guest owner，旧 adapter
  两个初始化查询均拒绝，generation 从 1 变为 3，同 slkd/bus 保持运行。
- 新注册下完成 32 次真实广告 ON/OFF，即 64 个不同请求的终态业务操作，
  超过当前容量 64 的保留边界。未被业务触碰的扫描初始化出处此时因真实
  result 已 absent/evicted 而拒绝；普通历史查询也拒绝。不能因 radio 仍 Off
  而生成新成功结果。最新真实业务 OFF 仍可读，同行继续扫描且注册不变。
- 原始 capture 独立证明七项初始化查询 recipe、64 项完整真实业务 recipe、
  两段同行真实扫描 ON/OFF，并与父进程、guest 的 proof 逐项一致；完整参数、
  地址、随机数据、成功 Complete 和实际 selected power 均核对。最后两轮
  RF 仍成功，整例 20+2 轮，1837 包/零 drop/taint0/QEMU0，UID1000/caps0。

复现时先按已有 Native prepare 工作流准备**新**冻结镜像，随后：

```sh
python3 tools/ws73_target.py run --prepared <fresh-native-prepared> \
  --output <new-evidence-directory> --ports 1-2.1.1 1-2.1.4 \
  --qmp-hotplug --initializer-lifecycle --timeout 1800
```

[独立封存 receipt](evidence/ws73-initializer-lifecycle-real-20261012.json) 的 SHA256
为 `f06b6e04af4ed66e967245c77192350220c26477d287c0a8bd3195ee6fde4aca`。
另有18个只读观察窗口独立核对无所属设备 DLI 命令；结果淘汰拒绝不是重新提交
初始化。精确工具提交的[CI38175391837](https://github.com/OpenSparklink/sparklink/actions/runs/38175391837)
九项成功，CI与实机资格分别记录。

此例没有关闭或 dup slkd 私有 fd，也没有暂停真实在途回复；这些 API 与 fd
组合边界仍须独立验收。QMP 重新注册不能算物理拔插或自然故障自动恢复。
正常 VM 累计69/维护20，四设备尝试仍9/默认资格0；原四设备失败及清理 receipt
保持原状态，完整 Managed、物理拔插、自动恢复/根因与全部 S0–S6 仍开放。
