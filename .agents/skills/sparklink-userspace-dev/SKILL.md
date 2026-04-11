---
name: sparklink-userspace-dev
description: 'SparkLink 纯用户态开发工作流（不涉及内核修改）。适用于给 slkd 添加 D-Bus 接口/方法、给 slctl 添加 CLI 命令、在 libsparklink Adapter 补全 ioctl 封装、添加 profile 插件、扩展 bonding/transport/hid 模块。当用户说"添加命令"、"新增 D-Bus 方法"、"用户态"、"slkd"、"slctl"、"Adapter"、"profile"时触发。'
argument-hint: '要添加的功能描述（如"给 afh 子系统添加 D-Bus get/set 方法"）'
---

# SparkLink 纯用户态开发

## 工作区结构

```
~/Documents/sparklink/
├── crates/
│   ├── slk-protocol/      ← ioctl 号 + FFI 结构体（不可感知上层）
│   │   ├── src/ioctl.rs   ← ioctl 包装函数（unsafe syscall）
│   │   ├── src/types.rs   ← Rust FFI 结构体（与内核 C ABI 1:1）
│   │   ├── src/advdata.rs ← TLV 广播数据解析器
│   │   └── src/tests.rs   ← struct size 断言（ABI 守卫）
│   ├── libsparklink/
│   │   └── src/
│   │       ├── adapter.rs ← 公开 API（Adapter struct）
│   │       └── lib.rs     ← Event 枚举、错误类型
│   ├── slkd/              ← D-Bus 守护进程
│   │   ├── src/main.rs    ← 启动、事件循环、模块注册
│   │   ├── src/state.rs   ← AdapterState（持有 Adapter 和设备表）
│   │   ├── src/dbus_iface.rs ← 主 D-Bus 接口（DeviceIface）
│   │   ├── src/controller.rs ← ControllerIface、ExtAdvIface
│   │   ├── src/security.rs   ← SecurityIface（含 bonding）
│   │   ├── src/ssap.rs       ← SsapIface
│   │   ├── src/bonding.rs    ← 配对信息持久化（TOML）
│   │   ├── src/profile.rs    ← Profile 插件框架
│   │   ├── src/hid.rs        ← HID 内置 profile（TXS-30004）
│   │   └── src/transport.rs  ← CLTP/LWCTP 传输协议（TXS-20007）
│   └── slctl/
│       ├── src/main.rs    ← 分发表（match command）+ help 文本
│       └── src/commands.rs ← 命令实现（每个命令一个方法）
└── data/                  ← 系统文件
    ├── systemd/slkd.service
    ├── dbus/sparklink.conf   ← D-Bus 策略
    ├── udev/99-sparklink.rules
    └── pkgconfig/sparklink.pc
```

---

## 场景 1：给 Adapter 添加 ioctl 包装

**适用**：内核已有 ioctl，但用户态 `Adapter` 没有对应方法。

### 步骤

**1. 在 `slk-protocol/src/ioctl.rs` 加 wrapper**

```rust
pub fn sl_new_feature(fd: RawFd, req: &mut SleNewFeature) -> io::Result<isize> {
    ioctl(fd, SL_IOCTL_NEW_FEATURE, req as *mut _ as usize)
}
```

**2. 在 `libsparklink/src/adapter.rs` 加方法**

找到对应的功能区块（`// --- AFH ---`、`// --- Security ---` 等），在末尾添加：

```rust
pub fn new_feature(&self, param: u16) -> Result<(), Error> {
    let mut req = SleNewFeature { field_a: 0, _pad: 0, field_b: param };
    sl_new_feature(self.fd, &mut req).map(|_| ()).map_err(Error::Io)
}
```

**3. 在 `slk-protocol/src/tests.rs` 加 size 断言**（如结构体是新增的）

```rust
#[test]
fn struct_size_new_feature() {
    assert_eq!(size_of::<SleNewFeature>(), 4);
}
```

---

## 场景 2：添加 D-Bus 接口方法

**适用**：需要把 Adapter 方法暴露为 D-Bus 远程调用，供 slctl 或第三方使用。

### 步骤

**1. 确定放在哪个接口文件**

| ioctl 域 | 接口文件 | 接口名 |
|---------|---------|--------|
| PHY/Role/PM/Stats/Meas | `controller.rs` | `ControllerIface` |
| ExtAdv | `controller.rs` | `ExtAdvIface` |
| Security/Pairing | `security.rs` | `SecurityIface` |
| SSAP/Profile | `ssap.rs` | `SsapIface` |
| Conn/Device 操作 | `dbus_iface.rs` | `DeviceIface` |
| AFH/RAL/RPA/Sync | `controller.rs` | `ControllerIface` |

**2. 添加方法实现**

在对应 `impl XXXIface` 块中：

```rust
fn new_feature(&self, param: u16) -> zbus::fdo::Result<()> {
    let ss = self.state.lock().unwrap();
    let s = ss.adapter.as_ref().ok_or_else(|| zbus::fdo::Error::Failed("not open".into()))?;
    s.new_feature(param).map_err(|e| zbus::fdo::Error::Failed(e.to_string()))
}
```

**3. 在 `#[interface]` 宏的 impl 块中注册**

zbus 会自动通过反射注册所有 `fn` 方法，无需额外注册步骤。

**4. 如需新接口，在 `main.rs` 注册**

```rust
let new_iface = NewIface::new(state.clone());
let _iface_ref = zbus_conn.object_server()
    .at("/org/sparklink/Adapter0/NewFeature", new_iface)?;
```

**5. 更新 D-Bus 策略文件**

`data/dbus/sparklink.conf` — 添加新接口的 `<allow>` 规则：

```xml
<allow send_destination="org.sparklink"
       send_interface="org.sparklink.NewFeature"/>
```

---

## 场景 3：添加 slctl CLI 命令

**适用**：给 slctl 新增一个用户可以在命令行执行的操作。

### 步骤

**1. 在 `slctl/src/main.rs` 的 match 分发表中添加**

```rust
"new-feature" => cmds.cmd_new_feature(&args[2..])?,
```

**2. 在 `slctl/src/commands.rs` 实现方法**

```rust
pub fn cmd_new_feature(&self, args: &[String]) -> Result<()> {
    let param: u16 = args.get(0)
        .ok_or("usage: slctl new-feature <param>")?
        .parse()?;
    let proxy = self.controller_proxy()?;
    proxy.new_feature(param)?;
    println!("ok");
    Ok(())
}
```

**3. 更新 help 文本**

在 `main.rs` 的 `print_help()` 函数中，找到对应分组，添加：

```
  new-feature <param>     说明文字
```

---

## 场景 4：添加 Profile 插件

**适用**：实现一个新的蓝牙风格 profile（如 Battery、Health Thermometer）。

### 步骤

**1. 在 `slkd/src/profile.rs` 中实现 `Profile` trait**

```rust
pub struct MyProfile { /* 状态字段 */ }

impl Profile for MyProfile {
    fn name(&self) -> &str { "MyProfile" }
    fn uuid16(&self) -> u16 { 0x1234 }  // TXS 分配的 UUID
    fn characteristics(&self) -> Vec<CharacteristicDef> { vec![...] }
    
    fn on_read(&self, handle: u16) -> Vec<u8> { vec![...] }
    fn on_write(&mut self, handle: u16, data: &[u8]) { ... }
}
```

**2. 在 `main.rs` 初始化时注册**

```rust
registry.register(Box::new(MyProfile::new()));
```

---

## 场景 5：扩展 Event 枚举

**适用**：内核新增了事件类型，用户态需要解码。

### 步骤

**1. 在 `libsparklink/src/lib.rs` 的 `Event` 枚举中添加变体**

```rust
pub enum Event {
    // ...
    NewEvent { field: u8 },
}
```

**2. 在 `adapter.rs` 的 `decode_event()` 中添加解码**

```rust
EVT_NEW_EVENT => {
    // data[0] 是 field
    Ok(Event::NewEvent { field: data.get(0).copied().unwrap_or(0) })
}
```

**3. 在 `slkd/src/main.rs` 的事件循环中处理**

```rust
Event::NewEvent { field } => {
    // 触发 D-Bus 信号或更新状态
}
```

---

## 构建与测试

```bash
cd ~/Documents/sparklink

# 构建
cargo build --workspace

# 测试
cargo test --workspace

# 仅测试某个 crate
cargo test -p slkd
cargo test -p slk-protocol
```

**测试基准**（截至 2026-04-06）：
- slk-protocol: 56 个
- libsparklink: 6 个
- slkconfig: 7 个
- slkd: 49 个（含 bonding 3 + transport 12 + hid 10）
- **总计: 118 个**，0 failed

---

## 提交规范

```bash
cd ~/Documents/sparklink
git add -A
git commit -m "<crate>: <动作>: <描述（<50字符）>

详细说明...

Tests: N passed."
```

示例：
- `slkd: add GetConnectionInfo D-Bus method`
- `slctl: add afh channel-map commands`
- `libsparklink: add RPA timeout and enable methods`
