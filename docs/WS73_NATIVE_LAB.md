# WS73 原生 Linux 构建与产物检查

原生矩阵使用实际启动在主机上的项目内核。当前实机主机为 Fedora
7.2.8-200.fc44.x86_64，项目 fork 基线为7.0.0-rc6；当前正在单独构建原生
实验镜像和模块，尚未安装或启动。真实 USB 透传到 KVM 的结果按 QEMU
路径记录。原生单只、双只、四只、故障隔离和无需人工拔插恢复继续开放。

## 独立构建

输出目录与已有 QEMU/kernel97 的输出分开。以当前主机的 `/boot/config-<release>`
为输入，通过当前 fork 的 `olddefconfig` 归一化；记录原始及归一化配置hash和
有意修改，不能称为与发行版配置完全相同。使用已验证的 Rust/LLVM/bindgen
工具链，先运行 `make rustavailable`，归一化后再次检查 Rust和WS73未被关闭。

原生实验配置要求 `RUST=y`、`SPARKLINK=y`、`SPARKLINK_DRIVERS=y`、
`SPARKLINK_WS73_USB=m`、`SPARKLINK_GENL=y`、`SPARKLINK_SLE=y`和
`SPARKLINK_DEBUGFS=y`，关闭`SPARKLINK_VIRTUAL`。保留主机启动需要的
存储、根文件系统、USB控制器和平台驱动；当前主机NVMe为模块、Btrfs为内建。
启用`USB_MON`、`IKCONFIG`和`IKCONFIG_PROC`供运行证据使用。当前环境无
pahole，实验配置关闭BTF，记录这个差异；后续BPF/兼容矩阵不能据此计为通过。
实验`LOCALVERSION`独立命名，不覆盖现有发行版版本号。

执行完整`bzImage modules`后保存真实构建退出状态。以下记录器示例只写指定
私有构建目录；先准备配置和工具链，替换两个路径及需要的显式编译器参数：

```python
import hashlib, json, subprocess
from pathlib import Path

source = Path('/path/to/linux').resolve()
build = Path('/path/to/private/native-build').resolve()
record = build / 'build-record.json'
assert not record.exists()
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source)
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
config_hash = hashlib.sha256((build / '.config').read_bytes()).hexdigest()
command = ['make', '-C', str(source), 'O=' + str(build), 'LLVM=1',
           '-j8', 'bzImage', 'modules']  # append pinned RUSTC/HOSTRUSTC/BINDGEN as needed
result = {'status': 'BUILDING', 'source_head': head,
          'normalized_config_sha256': config_hash, 'command': command}
record.write_text(json.dumps(result, indent=2) + '\n')
with (build / 'build.log').open('x') as log:
    process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
same_head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() == head
clean = not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source)
same_config = hashlib.sha256((build / '.config').read_bytes()).hexdigest() == config_hash
result.update(build_exit=process.returncode, source_unchanged=same_head and clean,
              config_unchanged=same_config)
result['status'] = 'BUILD_PASSED' if process.returncode == 0 and same_head and clean and same_config else 'BUILD_FAILED'
record.write_text(json.dumps(result, indent=2) + '\n')
assert result['status'] == 'BUILD_PASSED', result
```

## 产物校验与封存

完成构建后，从用户态仓库运行：

```sh
python3 tools/ws73_native_build_check.py \
  --build /path/to/private/native-build --source /path/to/linux \
  --source-head <recorded-clean-kernel-HEAD> \
  --build-record /path/to/private/native-build/build-record.json \
  --output /path/to/new/private/artifact-snapshot
```

检查器要求成功终态记录和匹配的源码HEAD/配置；校验x86_64可执行vmlinux、
可重定位WS73模块、Linux启动镜像头及其嵌入配置与构建配置逐字节一致、
模块名称/license/vermagic、
`modules.order`中的唯一对象，以及链接镜像和`Module.symvers`中的原生GPL
exports，包括新的健康查询。拒绝Rust或驱动关闭、WS73内建的QEMU镜像、
Virtual混入、错误架构、跨版本模块、缺失export和仍在运行/失败的构建记录。
配置中不可见的关闭选项可缺省为n；必须开启的选项必须实际存在。

仅在所有检查通过且复制前后内容相同时写入
`NATIVE_BUILD_ARTIFACTS_VERIFIED`。manifest保留源文件hash、模块信息和记录来源；
vmlinux仅记录hash，其余必要检查产物复制到新目录。检查器不安装文件、
生成initramfs、加载模块、改变引导项或访问USB。这个快照不包含其他全部模块，
部署包仍需完整modules/dependencies、适配主机的initramfs、固件/板级资格、
保留原引导项的安装和回退步骤。源码HEAD/配置一致也不能独立证明全部编译
输入来源；编译命令与实际输入冻结仍需保存。

产物状态始终`native_acceptance=false`、`physical_acceptance=false`。原生验收
需要实际引导该镜像、运行日志与模块身份、每设备Ready、普通用户slctl、
真实双端随机广播发现、物理拔插和有限故障恢复；沿用
[北极星](WS73_DISCOVERY_NORTH_STAR.md)与[恢复矩阵](WS73_RECOVERY.md)原条件。
只通过产物检查不关闭原生驱动、恢复、兼容或完整方案issues。

## 空 USB 模块启动检查

当前原生实验构建已完成`bzImage modules`，并通过上述产物正例检查。
在没有任何WS73或其他USB设备传入的KVM中，已实际引导该镜像，运行
[`ws73_native_module_init.sh`](../tools/ws73_native_module_init.sh)：验证发行号和
内建`/dev/sparklink`，两次加载/卸载独立WS73模块，每次检查USB驱动注册与
移除，保留从0秒开始的完整内核日志并正常关机。未观察到内核warning/oops。

复现时将静态busybox及必要applet软链接、该脚本作为可执行`/init`、已校验的
`sparklink_ws73_usb.ko`和`include/config/kernel.release`作为`/expected-release`
打包为cpio newc initramfs。当前模块`modinfo depends`为空；若其他配置产生
模块依赖，先处理依赖，不能忽略insmod失败。用同一个已校验的bzImage启动：

```sh
qemu-system-x86_64 -machine q35,accel=kvm -cpu host -m 1024M -smp 2 \
  -nodefaults -display none -monitor none -serial stdio -no-reboot -nic none \
  -kernel /path/to/verified/bzImage -initrd /path/to/smoke-initramfs.cpio.gz \
  -append 'console=ttyS0 loglevel=6 log_buf_len=4M panic=1 oops=panic'
```

不增加usb-host或WS73模型设备。脚本在加载模块前也拒绝已存在的ffff:3733。
通过记录必须含预期发行号、LOAD1/UNLOAD1/LOAD2/UNLOAD2的唯一顺序、完整
早期内核日志、唯一`PASS (EMPTY_USB_KVM_ONLY)`、无FAIL/warning/oops以及正常
QEMU退出；不能只依据末尾PASS标签。设置有限观察截止，保留失败日志。

当前直接构建的模块未签名，实验配置未强制模块签名，加载后taint从0变为
8192；记录该事实，不计作模块签名/信任链验收。完整部署包需处理安装阶段
签名和对应内核信任。这个检查仅证明实验镜像启动及空USB模块生命周期；
原生主机引导、WS73 probe/启动、真实RF和故障恢复继续开放。
