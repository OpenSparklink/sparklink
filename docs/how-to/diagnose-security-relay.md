# 定位真实 WS73 安全 relay 交付失败

这是维护者诊断，不是已通过的配对教程。当前能力见
[唯一资格入口](../../project/current-capabilities.md)；批准配对、可信安装、加密业务和
Bond 均未取得资格。仅在隔离 VM 中运行，主机不安装驱动、服务或修改权限。

## 前置条件与版本

- 已用现有 [VM 环境指南](prepare-vm-gate.md) 制作含签名 WS73 模块、普通用户
  slctl/slkd、捕获及 SDK111 输入的私有 prepared 镜像。本批运行镜像 K `8cb44f8d3a9a`、
  编译服务 U `c590576bcc61`；其他提交须重新回归，不能继承本批结果。
- 三只可写且未由主机驱动或其他 VM 占用的真实 WS73：Native 目标、Native 同行及
  reference Host 对端。使用明确 USB 物理端口，不依赖易变 device number。
- 普通用户可访问 KVM/所选 USB，已固定的 QEMU 支持禁止主机 reset/driver detach
  等 opt-outs；环境工具不得自动获得 sudo。
- 用户指定的干净 libws73-usb `f4d85d0e95af2d0043432e1301fd2f6b660a4906` 源码；
  C 编译器、OpenSSL 开发文件、libusb 头与共享库、patch、mkfs.btrfs。
  标准/OHOS Host `f0872df` 和 SDK111 是封装审查依据，不复制受限材料到文档站。

## 执行与收集

在用户态仓库运行，设置路径为本地已有输入，输出使用一个尚不存在的私有目录：

```sh
python3 tools/ws73_security_relay_reference.py \
  --prepared "$WS73_PREPARED" \
  --reference "$WS73_REFERENCE" \
  --usb-include "$WS73_USB_HEADERS" \
  --usb-library "$WS73_USB_LIBRARY" \
  --output "$WS73_DIAGNOSTIC_OUTPUT" \
  --native-port 1-2.1.1 \
  --survivor-port 1-2.1.3 \
  --oracle-port 1-2.1.4
```

`--usb-include` 指向含 `libusb-1.0/libusb.h` 的目录；三端口必须核对本机实际拓扑。
工具私下编译 reference-linked 测试应用，不改 reference checkout。对端先由自己的
VM 原生驱动启动，停 slkd 并在 **guest** 中 unbind，然后参考 Host 独占；测试 warm
patch 有界排空、发送真实 CLOSE 并要求 `(4,3)` ACK，随后仍要求真实 customize/open
响应。它不是生产 UserHost 接口，也不是自然恢复验收；ACK 不证明固件全部状态清除。

Native 普通用户 channel 启动原 CMTC 期限；参考库只回答查询，测试应用额外发送真实
id7 capability 查询。观测到实际通道信息后再调用真实配对请求。第三只保持扫描，
最后核对同代际 Ready 与实际扫描停止。本轮业务 payload 回归另行进行，不能用该
扫描检查代替独立业务隔离资格。

## 结果检查与限制

输出 `manifest.json` 必须分别检查：

1. Native 收到当前连接的真实 `0014/0134`；提交 `1812/0147`，载荷 reason `02`。
2. 实际 USB OUT 与成功 `1812 Complete` 回显的 handle/index 匹配冻结提交。
3. 对端 `0014/0147` 的精确数据，以及 reference 应用当前 handle 的拒绝结果。
4. 两端捕获完整、零内核丢包、taint0/无 kernel warning；同行同代际 Ready/扫描启停。

缺对端包或应用结果时返回 `REAL_PEER_DELIVERY_FAIL`/退出1，即使两只 VM 正常退出、
USB 与 Complete 成功也不能通过。本批这个失败已经实际出现，保留
[原始身份、反例和限定证据](../evidence/relay-production-20261014.json)。
即使未来 `REAL_DENIAL_RELAY_PASS`，也只表示默认未批准配对的拒绝 relay，不代表
批准配对、可信安全或对端业务处理。handle/index 回显没有 generation/lifetime，
不能证明复用屏障或晚到消息归属。

## 失败处理

保留整个私有输出，包括失败、QMP/console、两端 USB/HCC 数据和应用结果。不要编辑
失败为 PASS，也不要重复发送或人工切电后将其记录为自动恢复。启动/重枚举失败、
协商超时与对端收包缺失分别定位；下一轮换新输出目录，保持输入 hash。设备需要
恢复时按原恢复任务记录，而不是用重枚举推断状态清除。公开证据只保存必要包摘要、
源码及原始文件 hash；SDK、固件、受限标准和大抓包保留私有。
