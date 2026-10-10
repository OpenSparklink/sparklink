# 系统 D-Bus 观察与控制权限

生产部署使用 `data/dbus/sparklink.conf` 与系统总线。普通应用经 slctl 调用
slkd，不需要 sudo、setid 或 capability；管理员在安装阶段部署规则、创建
`sparklink` 组并将获准控制设备的用户加入组。新登录会话取得组成员资格后，
该用户可执行广播、扫描和停止。当前 systemd 服务以 root 运行并拥有
`org.sparklink`；普通观察者和控制组均不能拥有或排队取得这个服务名称。

例如，管理员一次性执行 `groupadd --system sparklink`（该组不存在时）及
`usermod -aG sparklink <获准用户>`，并安装项目的系统总线/服务/设备节点规则。
用户重新登录后确认 `id` 的组列表再运行 slctl；开发工具不替管理员修改组、
加载主机内核或覆盖运行中的系统总线策略。

| 调用者 | 查看 | 控制 | 拥有服务 |
| --- | --- | --- | --- |
| 未授权用户 | 明确列出的观察方法与 Properties.Get/GetAll | 拒绝 | 拒绝 |
| sparklink 组 | 查看 | 允许方法调用 | 拒绝 |
| root | 查看 | 允许 | 允许 |

默认规则先拒绝向服务 owner 发送消息，再逐项允许观察方法。新增方法、未知
接口、省略接口名的调用和 Properties.Set 不会自动获得观察权限。授权组使用
静态组成员身份作为等价授权；尚未提供逐动作 polkit 提示。组授权涵盖控制
方法，管理员应将组成员视为可信设备管理者。

Properties.Get/GetAll 与 ObjectManager 是公共属性读取入口，XML 无法检查其
消息体中的属性名称。现有导出属性均为公开状态；新增秘密或凭据不能作为
这些公共属性导出，须增加有授权检查的方法。这里的未知接口拒绝指请求头
中的方法接口，不能当作对属性消息体的访问控制。

观察允许项以 XML 为准，包括 Manager 的版本/adapter 列表、Adapter 的设备/
报告/带时间报告/非破坏操作结果、Device 的缓存数据、Controller 的状态统计、
ExtAdv.GetInfo、Security 的概要/Bond 地址列表和本地服务的概要/列表/属性读。
RemoteService.Read 会请求远端操作，DequeueNotification 会消费队列，GetPasskey
会暴露口令，因此这些方法需要控制权限。接口自省、对象枚举、Peer 查询与
已请求调用的响应允许；属性写入需要授权。

规则限制目标 **owner**：直接使用其 `:1.N` unique name 不能绕过限制。规则
的默认→组→用户顺序及 owner 匹配语义见
[dbus-daemon 官方说明](https://dbus.freedesktop.org/doc/dbus-daemon.1.html)。不要
把其他文件中的后置通配 allow 叠加到此规则上；部署须审查实际总线配置。

`slkd --session` 是显式开发选项。普通会话总线不会自动加载系统策略，不能
据此宣称生产授权通过。下面的 guest 门禁在隔离私有总线上显式加载生产
XML，使用不同真实 UID 验证；它不修改主机总线或组成员。

## 可复现开发门禁

```sh
python3 linux/tools/testing/selftests/sparklink/run_daemon_lifecycle.py \
  --kernel-build /absolute/path/kernel-build \
  --qemu /absolute/path/custom-qemu-system-x86_64 \
  --busybox /absolute/path/static-busybox \
  --userspace /absolute/path/sparklink \
  --dbus-daemon /absolute/path/dbus-daemon \
  --radio-policy --production-policy \
  --output /absolute/path/new-evidence-directory
```

需要包含 usb-ws73-test 的自定义 QEMU 和本项目内核。guest 用 root slkd、
uid1000 slctl（主组1002、补充组sparklink/1000）、uid1001 非组观察者；后者
不能直接访问 chardev，但可读取动态 adapter、报告、
属性、自省和非破坏结果，但广播/扫描/停止、属性写入、unique owner、省略
接口、未来方法、未知接口、远端读取、出队与口令调用必须得到总线 AccessDenied。
两名普通用户都不能取得服务名。拒绝调用后状态不变，没有 native admission。
授权用户再走实际 slctl 的合成20轮交换、同 daemon owner/PID 拔插后2轮及 TX-off。
记录实际 daemon UID、命令拒绝矩阵、源码/策略/程序/内核 hash 与完整内核日志。

这只证明实际 D-Bus/daemon/CLI/内核与合成 USB 的权限及控制集成，不能替代
真实 WS73、固件/板级资格或 RF 验收。完整 Managed/Diagnostic owner lease、
raw DLI 与直接 chardev/ioctl/其他入口的内核授权仍待实现；目前设备节点的
组权限与 D-Bus 权限是两个入口，静态策略不提供内核单 owner 隔离。K#5/U#6
及北极星整项保持开放。系统安装与实际用户的权限验收须单独记录。
