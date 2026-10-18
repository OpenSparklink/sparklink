# OpenHarmony DLI/HAL 参考如何用于 SparkLink

这份说明补充现有分层的参考依据，不新增实现计划。核对本地
[drivers_peripheral 固定提交](https://gitcode.com/openharmony/drivers_peripheral/tree/879984db5c71d6922e37a529ea467dcadcd46958)
的 `nearlink/dli/dli_service`，工作区干净；这是本地版本身份，不表示远端最新版本。
GitCode 页面本轮无法读取，源码核对基于 origin 指向该仓库的本地 clone。
[逐文件 hash、职责映射和边界](../evidence/openharmony-peripheral-reference-20261015.json)
保留可追溯记录。所读 NearLink DLI 文件标注 Apache-2.0；本批没有复制实现。

## 两份 OpenHarmony 参考各回答什么

既有 `communication_nearlink_service`（`f0872dfaac33`）用于协议 Host、SM、DTAP、
SSAP 和命令/事件语义；新增 `drivers_peripheral`（`879984db5c71`）用于 HDI/HAL、
厂商库入口、DLI 字节流和 callback/关闭边界。SDK111 与 `libws73-usb`
（`f4d85d0e95af`）继续用于 WS73 方言对照。接口存在、README 的功能描述以及
两份参考能拼接起来，都不能证明当前 WS73 路径通过验收。

## 包边界和成功阶段

| 参考实现中的事实 | 在本项目中的对应契约 |
|---|---|
| A1/A2/A3/A4 区分 command/event/ACB/ICB；字节流先读 type，再读四字节头和长度指定的载荷 | USB/HCC/BSLE 与 DLI 分层校验；HDI 回调中的 packet 不带该 type，转换时不能重复或遗漏 |
| `SleHalInit` 请求返回与 `initializationComplete` 分开 | Runtime 必须等真实匹配结果；transport 可用不能发布 Native Ready |
| 地址初始化内部使用 0405，并由匹配响应推进 opened | 作为该版本初始化序列参考，不能替代 WS73 当前实际 DLI 查询和原期限 |
| `SleSendHciPacket`/vendor send 返回传输写入结果 | 不代表命令 Complete、NOCP、加密、对端协议接收或对端应用处理 |

四字节头中的 length 为偏移 2 的两字节长度；它与 H4 之前的 type 合计五字节。
这只能帮助核对 DLI framing，不能推导 USB 分片、ACB credit、固件支持的安全消息或
实际 MTU。仍按实际 WS73 codec、SDK111、两端捕获和对端应用回复分别验收。

## 生命周期和厂商边界

参考实现的 `Close` 和 `OnRemoteDied` 进入 vendor cleanup；watcher 停止时先唤醒并
join，再关闭厂商 channel、清空 callback 和卸载库。一些排队 event 使用 weak_ptr。
这些提供清理顺序的检查点。SparkLink 还必须验证 controller/generation/lifetime/epoch、
准入撤销、锁外排空和未结清物理义务；引用仍存在不表示身份仍有效。

参考的 `VendorInterface` 是进程级单例，通过 `init/op/close` 动态加载厂商库。
不能由它推定每 controller 故障隔离，也不能把它直接接成 Native Backend。
当前仍采用 drivers 的设备传输、net 的 Native Host/Session/credit、安全机制与
slkd 的策略/SSAP/Agent 分层。未来若适配完整 OHOS Host，应单独核对其 HDI 包契约，
服从低优先级 [UserHost 独占决策](../decisions/0003-optional-exclusive-user-host.md)。
本批不实现 UserHost、不承诺 SDK/厂商 API 与 slctl 兼容。

## 需要保留本项目约束的地方

所读同步 promise 等待、EAGAIN 重试和 H4 短写循环没有提供本项目要求的原始绝对
期限；`CheckOnBoardState` 直接返回 true，也不是硬件 Ready 的证据。这些是局部源码
差异，不是对 OpenHarmony 全系统的缺陷结论。SparkLink 保持有限队列、有限重试、
零进展错误、真实状态确认和同行隔离，不能借参考代码弱化现有门禁。

参考审计没有运行驱动、加载固件或改变当前资格。后续实现只按
[唯一计划](../../project/implementation-plan.md)推进；实测结果只见
[当前能力与限制](../../project/current-capabilities.md)。
