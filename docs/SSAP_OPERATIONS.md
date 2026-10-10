# SSAP 权限契约与旧接口迁移

日期2026-10-11；Linux bde171beb2e0aee6d10515235ec4f0bb03e99663。依照用户提供T/XS 20001-2025 V1.2.0
表32，不宣称联盟最新版本、服务互通或标准Engine已完成。

| 命名 | 值 | 含义 |
|---|---|---|
| READ | 0x01 | 读取 |
| WRITE_NO_RSP | 0x02 | 无响应写入 |
| WRITE_WITH_RSP | 0x04 | 有响应写入 |
| NOTIFY | 0x08 | 通知，无ACK |
| INDICATE | 0x10 | 指示，需ACK |
| BROADCAST | 0x20 | 广播 |
| DESC_WRITABLE | 0x100 | 数据值说明描述符可写 |
| CLIENT_CFG_WR | 0x200 | 客户端配置描述符可写 |
| SERVER_CFG_WR | 0x400 | 服务端配置描述符可写 |

有效mask=0x73f。b6、b7、b11..b31保留，必须拒绝。read+notify是0x09，不能获得
任何写权限；两种写权限不能相互替代。操作声明与认证/加密/授权是独立约束，
不能把设置权限位当作已经授予调用者访问。标准Engine须同时核对peer安全上下文。

## 实现和实际调用者

- canonical kernel C UAPI提供SL_SSAP_OP_*及valid/allows/fits_legacy helpers；
  实际内核OpIndicator构造器在数据库操作前拒绝保留位，staging reserved bytes
  必须为0，超长注册值拒绝。字段布局/ioctl编号不变。
- Rust slk-protocol::SsapOperations是32位验证类型；显式to_legacy_bits拒绝
  descriptor权限向8位staging缩窄。SsapAddProperty构造和raw验证不截断值。
  libsparklink真实syscall入口验证raw输入；slkd实际D-Bus方法在锁前拒绝无效
  掩码或大于248字节值，返回InvalidArgs。旧D-Bus ops:u8不能表达descriptor权。
- Python SsapOperations验证范围/保留位/类型，拒绝bool/负数/超过32位；显式
  narrowing拒绝descriptor位。ssap_write超252字节先拒绝，不能u16回绕后成功。
- 实验Battery/HID/DeviceInfo采用命名权限；Battery按T/XS 30011-2025附录A改为
  service0x060A/property0x1034。ProfileRegistry在任何service创建前验证全部
  属性定义。不默认链接实验crate、不自动注册这些Profile，Native不发布旧服务。

## 回归与边界

C/Rust/Python编译实际头/库模块，比对2052组输入（所有低11位组合加高位边界）
与独立标准表：有效性、九种权限及legacy narrowing；未知required位也不能授予。
33项Python包含原29项ABI及新4项操作/FFI边界。167项完整all-features Rust测试及
strict Clippy通过；实际library /dev/null测试证明非法值先拒绝、有效值保留真实
ENOTTY；实际D-Bus方法在故意持有state锁时仍及时返回InvalidArgs。Kernel实际
模块9项含全部保留位/权限表及超长注册前不变，核心对象构建无代码warning。
make已有jobserver警告仍记录。新完整image/VM真实WS73回归另行记录。

这是R07的掩码/转换/调用入口整改及Engine基础类型。R04/R07/R08、U3/K6/K19
整项继续OPEN：标准消息控制码、PDU socket/owner/预算、协商/事务/deadline/取消、
每peer数据库/security、descriptor配置、notify提交/indication ACK、Profile实际
路由、完整HID/DeviceInfo标准及真实服务互通尚未验收。旧remote接口仍不支持。
自然恢复根因、历史物理xHCI警告、四设备及native对照不因本批变化关闭。
