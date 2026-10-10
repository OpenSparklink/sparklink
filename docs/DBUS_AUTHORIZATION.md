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
  --radio-policy --production-policy --kernel-authorization \
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

`--kernel-authorization` 还让 uid1001、补充组 uid1000、uid0 无 capability
进程继承实际已打开的 chardev/configfs fd。每名调用者的101条受保护 ioctl、
5个configfs store与5条已实现genl管理操作必须拒绝；观察与fd选择可用，
注册/元数据/提交计数未变，读取不触发待同步的全局idle电源策略。未知 ioctl
保持 ENOTTY。这验证实际调用时的凭据，覆盖“特权打开后传 fd”和无capability
的root，不只是文件权限下的失败open。编译静态测试程序须准备 static libc。

## 内核权限边界与迁移

内核明确分类138个唯一声明 ioctl（35观察、2fd选择、101受保护），在参数复制/
电源同步/命令提交前检查实际调用者在初始user namespace中的 CAP_NET_ADMIN。
raw DLI、破坏性事件读取、远端操作、口令读取也属于受保护操作，不能凭
ioctl读方向判断权限。五个configfs写入口和genl mutation bridge同样检查；
genl的已实现管理请求保留 GENL_ADMIN_PERM。公开观察不改变电源模式。

设备组只提供节点访问，不授予直接管理权。普通 slctl 通过授权 D-Bus 调用
有 CAP_NET_ADMIN 的 slkd；项目systemd服务已有该capability边界。使用
slkconfig/raw/破坏性DLI旧工具直接管理设备需要管理员权限，它们不是普通
应用接口。开发session fixture现在也使用root daemon；普通uid1000 slkd
管理原生WS73的旧合成记录是历史结果，不能代表当前权限下可继续写入。
观察端仍可读取chardev的状态/非破坏事件，不能用 raw poll 消费控制器队列。

这些是实际 D-Bus/daemon/CLI/内核与合成 USB 的权限及控制集成，不能替代
真实 WS73、固件/板级资格或 RF 验收。原生 WS73 的文件 ownership 已接入；
跨全部 Backend 的 Managed/Diagnostic、Proxy/PDU/Security owner、自动原地
恢复和其余接口 canonical writer 迁移仍待实现。profile 0 继续旧迁移窗口，
不能用原生路径证明全部 ownership 完成。K#5/U#6及北极星整项保持开放，
实际安装与普通用户的实机权限验收须单独记录。

## 原生每设备 owner 的迁移

原生 WS73 现由 registration-bound Managed/Diagnostic fd 互斥控制；slkd
在发布 adapter 前取得 Managed，所有管理方法共用一个 fd。观察 fd 独立，
无 fd ownership 的 native genl mutation 不再作为写入口。释放/最后关闭后
保留已上线回复并以真实停止确认清理；失败/timeout 为 Fault/Unknown，成功
清理可同代次换 owner，不确定故障当前须重插。profile 0、Proxy/PDU/Security
及其余 canonical 接口仍待迁移。详见[ownership 契约与测试](MANAGEMENT_OWNERSHIP.md)。
原生路径的结果不能推及全部 Backend 或自动原地恢复；K#5/U#6和真实
北极星继续保持开放。
