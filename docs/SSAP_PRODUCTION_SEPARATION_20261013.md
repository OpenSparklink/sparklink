# WP18：旧SSAP生产剥离调用审计

当前整改记录，执行依赖只维护IMPLEMENTATION_PLAN；不是第二套规划。
审计源码：Linuxd3abbdc0c13a、用户态6bd9260（应用源码与afb5ee2相同）。
审计前Linux干净，用户态仅本批文档；保留当前新40轮短消息、249八轮与历史失败证据。
本批先剥离旧业务，再WP08唯一用户态Engine；整个生产架构整改优先于功能扩展。

## 已核对调用链与事实

* `sparklink_core.rs`默认编入`sle_ssap`，每`SparkLinkInner`分配`SsapInner`；
  `ioctl_ssap_local`实现本地服务/属性注册、读写、handle与列表。
  `ioctl_start_adv`从该本地DB收集UUID。它不是远端服务发布。
* `sle_conn.rs`在旧连接事件创建`SsapSession`，附`RemoteServiceDb`、MTU/版本/
  ExchangeInfo/remote events；可靠TCID的部分通道元数据被塞进该业务对象。
  `sparklink_core`连接info读取这些字段；`sle_workers`和注入分支据此筛选SSAP。
* **旧远端wire已经拒绝**：`ioctl_ssap_remote`/`process_incoming`、无callback的
  method和notify/indicate返回EOPNOTSUPP。不得描述为本批首次修复echo，也不得恢复它。
* 默认slkd仍编译`service.rs`；`adapters::publish`发布ServiceManager，旧连接事件
  发布RemoteService。其方法经libsparklink旧ioctl访问本地staging/已拒绝远端能力，
  不存在合格生产用户态Engine。`write_property`确实用`value.len().min(252)`静默截断。
* libsparklink有旧Adapter方法和六类C导出，Python有三个SSAP包装；slkconfig及
  slctl的service命令分别调用旧Adapter/D-Bus。旧UAPI有18个SSAP ioctl，连接info
  携带SSAP业务字段；C/Rust/Python结构与生成头必须同步。
* 实验Profile已在slk-experimental，默认Native不自动注册；显式legacy feature仍
  调用`ssap_add_svc/prop`。actor/cancel/drain/panic生命周期测试有独立价值。
* `run_ssap_containment.py`当前复制整份生产local DB/session并追加测试；历史codec
  已在selftests。剥离后runner应直接读取test-only模型，不能继续声称生产模块证明。

## 三类清单

| 分类 | 生产消费者/实际功能 | 剥离、替代或保留方式 | issues/回归条件 |
|---|---|---|---|
| 立即删除 | core `SsapInner`、local ioctl、服务/属性/描述符、handle allocator | 从默认内核删除；调用者先拒绝/同步删除未发布ioctl；未来唯一DB归slkd | K6/K5/K19/U3；默认生产构建不依赖DB，旧调用实际不成功 |
| 立即删除 | legacy连接`SsapSession/RemoteServiceDb`及SSAP info字段 | 移除业务字段/缓存/事务；通道身份搬回kernel channel对象；不为避免迁移保留空业务session | K6/K17/U3；连接ABI同步、Runtime/数据回归 |
| 立即删除 | 广播UUID自动消费旧DB | 删除旧服务业务依赖，保留显式广播数据构造；Native发现的已验证参数保持 | K2/K6/K19；双角色真实RF/连接/socket/249回归 |
| 立即删除 | service静默截断、旧“已发布/Engine在slkd”声明 | 超限在锁/ioctl前拒绝；未实现facade明确NotSupported；不返回假零列表/echo/notify成功 | U3/K5；实际D-Bus错误、锁持有时快速拒绝、CLI错误显示 |
| 移入测试 | `sle_ssap.rs`中有价值local DB、错误传播/权限/分配失败模型 | test-only历史staging模型；标记非wire/nonconformance；默认内核不编入 | K6/K19/U3；保留现有9项包含拒绝及OOM的回归 |
| 移入测试 | historical offset codec、远端拒绝、method/notify fail-closed | 专用selftests；不复制为新生产codec或伪Complete | K6/K13/K19；原malformed/重复片/无假成功测试保留 |
| 移入测试 | 实验Profile注册适配器和callback生命周期 | 脱离kernel staging，使用专用模型或显式Unsupported；同一actor测试保留 | U3/WP18；all-features严格检查、cancel/最后关闭/卸载回归 |
| 等待替代（本批必须先拒绝/退出生产依赖） | ServiceManager/RemoteService、Adapter/FFI/Python/CLI旧接口 | 同步明确拒绝或删除；旧SSAP ioctl迁移后直接移除，无兼容期；再接通用户Engine | K5/K6/U3；实际调用及跨语言契约，不能仅DTO测试 |
| 等待替代 | 旧conn内可靠TCID bookkeeping/worker筛选分支 | 审计后保留通用DTAP/信令机制，去掉服务session依赖；未合格模式拒绝 | K17/K6；不机械删除TransportChannel/CMTC/TCID/credit |
| 保留生产机制 | Runtime/gen/life、真实CMTC/CUTC、DLI PB、ACB账本、socket、安全 | 保留已验证Native唯一数据路径；Session/Ticket/Grant按目标架构继续整改 | K4/K6/K17/K19；新精确提交40短消息及249/超限资格保持 |
| 保留规范语义 | C `SL_SSAP_OP_*`、Rust `SsapOperations`、Python `SsapOperations`及权限测试 | 复用既有0x73f/32-bit语义；去掉旧staging宽度依赖，不另造权限定义 | U3/K5/K19；C/Rust/Python权限对照、保留非法/reserved/高位用例 |

“等待替代”不允许旧业务无限期留在默认生产；本批先退出调用或返回不支持。
新wire Engine不在本批恢复。历史模块级dead_code抑制随生产模块退出；不新增全局抑制掩盖缺调用者。

## 本批门禁和当前状态

审计/清单已形成。Ue49fa39已修复六类入口的静默输入截断；198 workspace及严格all-features clippy通过。
Kfbc92f删除core本地DB/广播UUID消费者；K167f468将1008行旧业务module移入selftests，
删除默认kernel的SsapSession/RemoteServiceDb依赖及消费，保留通用通道机制并拒绝旧未合格动态协商。
历史/reject10、Native20和连接发送边界通过，Rust对象编译零warning；串行make避免了原jobserver环境warning。
18个ioctl/连接业务字段的跨语言删除、D-Bus/CLI/实验Profile退出旧依赖、完整新镜像/VM验收仍待实施。
小提交顺序：入口拒绝/截断→core业务退出/test-only→连接元数据与通用通道分离→
删除未发布UAPI及同步所有调用者/CI pin→严格构建/实际调用→VM真实路径回归。
任何中间状态不称本批完成、不关闭issues。仅本批退出后再WP08新用户态Engine。

必要回归：fmt/check/clippy default与all-features；C/Rust/Python实际布局与调用；
historical selftests及callback故障；VM两只真实WS73独立Ready、RF22、两角色建链/断链、
40短消息及249/超限两端peer校验/USB/HCC/NOCP证据，同行generation/业务保持。
不是自然故障恢复或独立PHY嗅探资格。根因/非人工恢复及原整项scope仍开放。
