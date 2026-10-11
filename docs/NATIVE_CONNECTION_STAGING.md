# Native连接请求与异步operation：staging实现

2026-10-12，Linux `c8f2485dc3aadfc6581de310b7ef41b9b11f720c`。
本次写出了WS73字段codec与connection operation契约，尚未迁入生产Host。
它们明确放在selftests/connection，未加入net/sparklink或driver Makefile；
没有Native ioctl、D-Bus、slctl主动连接，也没有连接/SSAP实机验收。
此前新内核真实无连接RF20+2证据继续有效，不外推为连接功能。

## 字段与参考核对

对照本地libws73-usb/sle73_connection.c、communication_nearlink_service
cm/link/sle_access_dli.c以及T/XS10003-2025 8.4.1/8.4.2/8.4.3/9.1.14：

- WS73 v111 create是27字节：filter/own type/peer type/peer6、GT指示、frame1、
  scan interval/window、connection min/max、latency、supervision、event min/max。
  标准V2额外PHY/frame quartet不属于该已参考方言；旧6字节helper不能复用。
- disconnect为handle little-endian两字节+reason一字节。调用者显式提供每个值，
  不在codec中插入板级/功率/参数默认值；所有失败保持输出及尾部字节不变。
- 标准取消为0x1402、无参数、CommandComplete；完整NearLink Host也有相应
  callback。libws73-usb此路径没有使用它，111固件实际取消仍未验证，因此
  staging validate不将其宣布支持，不把作者取消解释为物理取消。

## Operation契约与已运行测试

Session按registration generation与command cookie约束一个待完成procedure，
这是Host admission policy，不是固件maximum-connections声明。分别保留
command status与outcome status，关联peer address type/address或disconnect
handle。queued、on-wire、awaiting outcome与terminal状态独立；OUT成功、
Status接受、异步outcome三种证据缺一不会成功，六种到达次序均覆盖。

作者取消保留Cancelled/-ECANCELED。在途OUT、Status或真实迟到建立不能
把它改成功；handle仍保留给独立物理观察域清理。传输不确定或sent deadline
保持fault/uncertain并阻止复用，取消作者errno与物理fault diagnostics分开。
只有never-selected取消/超时可在没有wire cleanup时清除reservation；
reservation clear不代表物理link clear，两者须在同一Host锁下共同判断。

8项Rust契约测试以及完整ASan/UBSan/Leak codec测试通过，合成bytes包括
27字节完整序列、6/31字节/错误opcode拒绝、handle边界、坏window/interval/
frame/地址及output保留。没有虚构Complete、模拟RF或实际Host消费者。

```sh
python3 tools/testing/selftests/sparklink/run_native_connection_contract.py \
  --output /absolute/path/new-staging-receipt.json
```

## 迁入生产的必须依赖

1. Native未发布UAPI添加gen/request ID/profile/完整参数的typed提交与非破坏
   查询；同步Rust/C/Python ABI、授权分类、每FD affinity/Managed权，不开放raw
   mutation，禁止legacy6字节回退。history/duplicate策略须接通真实bounded store；
   staging当前query仅当前operation，不能作为完整历史接口。
2. Driver-owned prepare/validate callback输出27/3字节计划，Host生成内部tag。
   同一credit scheduler保留原OUT reservation；仅该typed tag允许匹配成功
   Status释放wire slot，metadata/discovery仍按真实Complete处理。
3. 同一Runtime将driver-normalized物理outcome与operation关联；同时原始事件
   日志完整保留。未知/不匹配事件、loss、timeout和迟到success不得错误归属。
4. release/最后fd/daemon撤销要处理queued/accepted/connected/disconnecting，
   实际disconnect outcome才释放物理义务；不支持/不确定明确Faulted，不能
   仅凭作者Cancelled或radio Off宣布Free。0x1402需独立真实固件证明。
5. slkd/库/slctl接通消费者后迁移staging代码/有效测试，再真实双设备连接/断开
   与SSAP、安全互通；旧实现按调用迁移删除，不让重复状态长期并存。

这一步未接通生产，是原S4的依赖实施，完整目标不缩小为本契约。全部原28项/
S0–S6、完整Managed/权限/事件、默认四设备、在途强杀、自然RCA和非人工
恢复继续OPEN；VM-only，不关闭部分成果对应整项。
