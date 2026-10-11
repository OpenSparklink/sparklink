# WS73 原生 Linux 构建与产物检查

原生矩阵使用实际启动在主机上的项目内核。当前实机主机为 Fedora
7.2.8-200.fc44.x86_64，项目 fork 基线为7.0.0-rc6；原生实验镜像和全部模块
已独立构建及私有暂存，尚未安装或在主机启动。真实 USB 透传到 KVM 的结果按 QEMU
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

随后将`modules_install INSTALL_MOD_PATH=<新私有暂存根> INSTALL_MOD_STRIP=1`
限制在工作区新目录内运行，实际完成4974个模块的strip/sign和depmod；不向
主机`/lib/modules`安装。暂存WS73模块的signer为构建生成的内核key，摘要
sha512、vermagic一致、依赖为空。将该签名模块替换到上述空USB initramfs，
同一实验镜像再次两次加载/卸载成功，taint保持0，未出现签名失败日志。
保留未签名原始构建及其8192 taint证据，不覆盖旧结果。签名后的空USB测试
也不代表原生主机、强制签名策略或完整生产信任链已验收。完整部署/回退包
及原生硬件矩阵仍在推进，未改主机引导或安装系统文件。

## 完整 initramfs 的 NVMe/Btrfs 启动路径检查

私有暂存的全部模块用于生成 generic dracut initramfs。指定实验发行号和
`--kmoddir`，使用`--no-hostonly --no-hostonly-cmdline --no-hostonly-default-device`，
不封装当前主机根分区参数；省略WS73驱动，避免早期启动自动绑定真实设备。
生成路径、临时目录和日志均限制在新的私有工作区目录。完整部署仍需单独
处理启动项、主机硬件兼容、固件资格和受控加载，不能只复制空USB测试initramfs。

rootless dracut实际退出0，但报告`ldconfig -r`需要root、默认主机模块目录
不存在和无法fsfreeze输出目录；archive包含64位动态loader、systemd、
实验发行号的NVMe模块及depmod索引，没有`ld.so.cache`。保留这些诊断，
不能依据退出0宣称完整initramfs可用，也不能据此声称所有动态依赖已覆盖。

[`ws73_native_root_smoke.py`](../tools/ws73_native_root_smoke.py)用**实际生成的完整
initramfs**验证启动路径。它校验bzImage与native build manifest的hash、签名
WS73模块的架构/发行号/依赖和静态busybox，将输入及QEMU data复制并校验至
新目录，构造512MiB普通文件Btrfs测试盘。测试根目录含`os-release`和独立
init脚本，通过QEMU emulated NVMe暴露；没有主机磁盘、USB、网络、QMP或
人工输入。initramfs内的systemd/udev必须加载NVMe模块、按随机UUID找到Btrfs
根目录并switch-root，随后检查SparkLink节点和签名WS73模块的两轮生命周期。

```sh
python3 tools/ws73_native_root_smoke.py \
  --kernel-manifest /path/to/native-artifacts/manifest.json \
  --kernel /path/to/native-artifacts/artifacts/arch/x86/boot/bzImage \
  --initramfs /path/to/private/generic-initramfs.img \
  --module /path/to/private-stage/lib/modules/<release>/kernel/drivers/sparklink/sparklink_ws73_usb.ko \
  --busybox /path/to/static/busybox \
  --qemu /path/to/qemu-system-x86_64 --qemu-data /path/to/qemu-data \
  --output /path/to/new/private/root-smoke
```

检查器要求匹配发行号、实际`/dev/nvme0n1` Btrfs根挂载、随机UUID的内核挂载
日志、两轮LOAD/UNLOAD严格唯一顺序、taint始终0、完整0秒内核日志、正常关机
和QEMU退出0，才输出`PASS_ISOLATED_NATIVE_ROOT_SMOKE`。超时或任一失败保留
FAIL、日志及已有产物。动态终端控制字符去除后核对完整行，PASS不能覆盖
早期内核warning、签名失败或启动错误。

实际检查已通过上述路径。此前两轮失败也保留：测试根目录缺少`os-release`
时systemd拒绝switch-root；补全后旧脚本重复挂载sysfs失败。脚本现复用dracut
移入的proc/sysfs/devtmpfs并核对类型。另一次移动QEMU二进制后默认相对data
路径失效，现显式封存data并传入`-L`。这些失败均正常关机且QEMU退出0，
验证了必须检查完整启动证据。当前成功不等于解决了rootless ldconfig诊断，
也不覆盖发行版完整systemd根目录、真实主机NVMe/USB/电源管理或全部库路径。
`native_acceptance`和`physical_acceptance`仍为false；原生硬件及恢复issues继续开放。

## 普通用户生成完整 loader cache

已验证非特权user namespace可用，但不能把整个dracut放入只映射当前用户的
namespace：主机源文件属主无法映射时，dracut-install保留ownership失败；实际
发生多次安装错误却仍退出0。这一镜像已拒绝，保留失败记录。

使用[`ws73_dracut_ldconfig.sh`](../tools/ws73_dracut_ldconfig.sh)仅隔离cache生成
阶段：dracut仍由普通用户运行并复制文件；`ldconfig -r <private-initdir>`在
仅映射当前用户的namespace中chroot。它不授予主机root或USB/引导权限。
当前Fedora的dracut使用`-pN`只读cache查询和`-r DIR -f /etc/ld.so.conf`生成
cache；helper仅接受这两种调用，其他形式失败。

```sh
# 在新的私有目录内准备 tmp 和 dracut-internal.log；输出镜像必须尚不存在。
DRACUT_LDCONFIG=/absolute/path/to/tools/ws73_dracut_ldconfig.sh \
dracut --no-hostonly --no-hostonly-cmdline --no-hostonly-default-device \
  --no-uefi --no-early-microcode --kver '<release>' \
  --kmoddir '/path/to/private-stage/lib/modules/<release>' \
  --omit-drivers sparklink_ws73_usb --tmpdir /path/to/new/private/tmp \
  --logfile /path/to/new/private/dracut-internal.log \
  '/path/to/new/private/initramfs-<release>.img'
```

实际新镜像的`etc/ld.so.cache`为有效glibc cache，6023字节，126个库，包含
64位loader和libc；无ldconfig及ownership复制错误。同一检查器再次实际启动
该镜像、随机NVMe/Btrfs根目录及签名WS73模块成功，taint0。初始`realpath`
默认主机模块目录诊断来自dracut先查默认路径、随后以显式`--kmoddir`覆盖的
代码路径；工作区输出fsfreeze不可用的诊断也保留。旧镜像未覆盖或改记通过。
cache存在及此启动路径不等于全部动态依赖/生产配置资格。

## 独立启动 payload 与安装/回滚

[`ws73_native_boot_bundle.py`](../tools/ws73_native_boot_bundle.py)将已校验的原生
artifact snapshot、完整暂存模块和**实际通过根启动检查的同字节initramfs**封存
到新的私有目录。它检查build的模块顺序与暂存ko顺序对应、完整模块集合与
depmod索引、builtin元数据一致、原始启动日志的严格证明和匹配的三个输入
hash，以及有效loader cache。拒绝多余模块、私钥/未知文件和意外symlink，
明确排除指向构建目录的`build`链接。每个文件复制前后核对hash。

```sh
python3 tools/ws73_native_boot_bundle.py \
  --artifacts /path/to/native-artifacts \
  --module-root '/path/to/private-stage/lib/modules/<release>' \
  --initramfs '/path/to/private/initramfs-<release>.img' \
  --smoke /path/to/passed/root-smoke \
  --root-uuid '<current-root-filesystem-UUID>' --rootflags subvol=root \
  --output /path/to/new/private/boot-bundle
```

当前包实际封存4974个模块、4992个payload文件、787269326字节；包含独立
`vmlinuz/config/System.map/initramfs-<release>`及`usr/lib/modules/<release>`。
文件hash/大小清单、SHA256SUMS、完整启动证明、loader cache和具体部署/回滚
计划保留在包内。BLS候选项单独生成，明确指定根UUID及Btrfs子卷，两个
blacklist参数阻止WS73自动绑定；不会自动发布候选项、改变默认或重启。
当前主机`/boot`为独立ext4，根目录为Btrfs的`root`子卷；根参数必须根据
目标主机核对，不能把模拟根盘UUID当作实机参数。

[`ws73_native_deploy.py`](../tools/ws73_native_deploy.py)要求显式`--target-root`：

```sh
python3 tools/ws73_native_deploy.py check \
  --bundle /path/to/private/boot-bundle --target-root /path/to/scratch-root
# 临时根先准备 usr/lib/modules、boot/loader/entries 和 var/lib。
python3 tools/ws73_native_deploy.py install \
  --bundle /path/to/private/boot-bundle --target-root /path/to/scratch-root
python3 tools/ws73_native_deploy.py rollback \
  --bundle /path/to/private/boot-bundle --target-root /path/to/scratch-root
```

工具先验证完整包和BLS内容、拒绝路径穿越/父目录symlink/现有目标，然后把
每个单元复制到同一父目录的临时位置，用Linux`renameat2(RENAME_NOREPLACE)`
原子发布；BLS最后发布。复制后的模块/启动文件由执行者拥有，文件0644、
目录0755，不保留工作区文件属主。记录安装单元和状态到目标根内的
`var/lib/opensparklink/native-lab/<release>.json`；正常进程失败移除本次已发布
的匹配单元，拒绝删除未知/修改内容。回滚先核对**全部**单元，再先删除BLS、
随后启动文件和本实验模块目录。完成后的日志保留；再次安装同一包会归档
上次已回滚日志。进程失败测试不等于断电/存储崩溃矩阵。

已将整个实际787MB包安装到工作区临时根，以独立`sha256sum --strict --check`
核对4992个文件、权限及候选项，再回滚，所有实验单元移除，原发行版内核、
BLS和grubenv测试标记逐字节不变。另有小型文件系统测试覆盖冲突、并发目标
创建、symlink、损坏payload、中途复制失败、未知模块和修改BLS的拒绝路径。
这些结果仅证明文件系统生命周期，**没有运行真实主机的grubby分支**。

当前用户只授权**虚拟机部署和设备测试**。不得在本次开发中将目标改为主机
`/`、安装主机引导项、重启主机或修改主机服务/权限。此前未执行主机安装。
下面的主机路径说明仅保留为将来的部署设计，不是待执行动作或权限请求。

实际主机安装路径需管理员权限；工具要求sudo/root，
安装前后读取`grubby --default-kernel`并要求相同，不覆盖现有发行版文件或
保存的默认选择，也不运行grub配置重建/内核安装hooks或自动重启。实际回滚
前必须已启动保留的发行版内核；若默认已被外部修改，先恢复原发行版默认，
工具才执行移除。选择实验项并重启会中断主机任务，需要单独安排。

没有向主机安装或更改
BLS。该包是**受控加载前的内核启动包**；固件/板级校准、slkd/slctl及
udev/D-Bus/systemd策略部署仍需独立核对和封存，不能将安装包通过记为原生
WS73 Ready或普通用户应用通过。原生1/2/4、物理隔离、无人工恢复、完整
动态依赖/PM/兼容和S0–S6继续开放，两个acceptance标记保持false。

## 用户态部署准备

`slctl`的全局选项现在在创建runtime和连接D-Bus之前解析。`--help`、
`--version`和单独`help`无需服务或设备；`--session`和一轮命令的`--adapter`
选择继续支持，缺少adapter参数/命令先以退出2报错。命令开始后的参数保留
给原dispatcher，包括`txpower -12`，不会把负数误解析成全局选项。
旧封存binary在无bus环境中`--help`失败，新release binary对应离线查询
退出0；现有真实CLI/隔离D-Bus扫描鲜度及Complete后完整10秒窗口测试已通过。
这只验证参数与测试peer行为，不增加真实硬件验收项。

系统服务增加`StateDirectory=sparklink`和`StateDirectoryMode=0700`，使systemd
负责创建`/var/lib/sparklink`后再应用已有`ReadWritePaths`限制。服务仍以root
身份拥有系统D-Bus名称；普通用户的slctl授权由已有`sparklink`组策略管理。
当前未安装`/usr/sbin/slkd`，未启动实际systemd服务，也未将状态目录声明
计为完整服务sandbox或native Bond/key持久化资格。实际daemon/固件/权限包
及系统总线测试继续推进。

## VM 中的模块、daemon 与普通用户控制

用户只授权 VM。`ws73_native_service_bundle.py`在新私有目录以独立 Cargo target
离线构建 release workspace，核对三个 firmware hash header 和选定 combined SHA256，
按版本目录封存五个程序、cdylib、五个固件/板级文件及策略配置。输出不安装或
启动主机服务；板级文件仅检查长度，`board_qualification=NOT_ASSERTED`。
每个文件记录 SHA256、尺寸和权限，Rust/策略 source scope 必须干净且构建前后
不变；其他开发脚本变化不被声称为编译输入。

```sh
python3 tools/ws73_native_service_bundle.py \
  --source /path/to/sparklink \
  --kernel-manifest /path/to/native-artifacts/manifest.json \
  --firmware-dir /path/to/selected-111-files \
  --runtime-config-dir /path/to/explicit-board-files \
  --combined-sha256 <selected-combined-sha256> \
  --output /path/to/new-private-service-bundle
```

`ws73_target.py prepare`可选三个必须同时提供的参数，增加模块 VM profile。
它复用成功的 NVMe/Btrfs scratch boot 证据，逐项匹配 kernel/config、QEMU、
initramfs、签名 WS73 module 和 release daemon 的 Rust/策略源文件。`modprobe
--show-depends`只读取私有模块树；所有 insmod 在 guest 内进行。9p及其依赖必须
为模块，WS73也必须为模块；原有 builtin profile 的条件保持独立。

```sh
python3 tools/ws73_target.py prepare \
  --kernel-build /path/to/native-build \
  --qemu /path/to/qualified-qemu \
  --busybox /path/to/static-busybox \
  --dbus-daemon /path/to/dbus-daemon \
  --firmware-dir /path/to/selected-111-files \
  --runtime-config-dir /path/to/explicit-board-files \
  --native-module-tree /path/to/stage/lib/modules/<release> \
  --native-boot-smoke /path/to/passed-root-smoke/manifest.json \
  --native-service-bundle /path/to/private-service-bundle \
  --output /path/to/new-private-vm-profile

python3 tools/ws73_target.py support \
  --prepared /path/to/private-vm-profile --output /path/to/new-support-run \
  --timeout 240 --hotplug --empty-bulk --warm

python3 tools/ws73_target.py run \
  --prepared /path/to/private-vm-profile --output /path/to/new-real-run \
  --ports <first-host-usb-port> <second-host-usb-port> --qmp-hotplug
```

每轮从封存的1GiB Btrfs文件复制独立可写根，guest只挂载该 emulated NVMe和
本轮私有 evidence 9p目录。完整 initramfs先完成 NVMe/Btrfs启动，再 switch-root；
guest将复制来的代码树属主规范为root，启用9p依赖及usbmon捕获后才加载签名
WS73模块。guest创建专属用户/组，root运行slkd、uid1000无capabilities运行slctl，
系统类型D-Bus应用仓库策略，uid1001 observer检查控制拒绝。不会修改主机组、
udev、服务、引导项或磁盘；真实 USB透传仍遵循既有显式端口、禁止隐式reset和
detach的边界。日志记录真实slkd exec后的凭据、根路径和最终taint0。

root daemon使用`/var/lib/sparklink`（0700），版本化release executable与部署包
一致。此profile的PID1是受控init脚本，**未运行根目录systemd unit及sandbox**；
静态unit校验不替代实际服务sandbox验收。合成support不计真实空口；真实RF加
QMP移除/重接不计物理拔插或自动故障恢复。原生主机对照条件继续开放，完整
S0–S6方案和原issue验收清单保持不变。

### 真实物理拔插的 VM 记录

2026-10-10 UTC，使用上述模块 profile 和 SDK111文件选择完成真实两设备测试。
去除私有路径和原始USB padding的可共享记录在
[`ws73-vm-physical-20261010.json`](evidence/ws73-vm-physical-20261010.json)。
实际运行仍保留完整私有pcap、capture stats、console、QMP、usb lifecycle、
主机inventory、slkd/slctl日志、源/产物hash和失败历史，未将专有镜像或raw
padding提交。record中的`data`是接收端上报的本轮随机广播数据，不是完整USB
包或PHY嗅探器捕获。DLI版本不能证明设备正在运行哪个文件版本。

本轮host A为`1-2.1.4`、B为`1-2.1.1`，guest为`1-1`和`1-2`：两只分别Ready，
20轮交换角色成功。用户实际拔出A后，host inventory确认A消失、B及未选两只
地址不变；B的generation2、Ready和扫描启停保持有效，旧A选择被拒绝。
用户将A插回原口，A重新初始化为generation3，完成另外两轮闭环。slkd
PID522/start_ticks338及D-Bus owner保持不变。QMP只有两次初始device_add，
后续仅查询attached，没有注入device_del/readd/reset；QEMU未关闭或重开B。
双方STOP_CONFIRMED，应用uid1000、无effective/permitted/ambient capability。

guest退出后tcpdump封存1373条记录、0drop；在host独立执行既有验证器：

```sh
python3 tools/ws73_north_star.py verify \
  --run /path/to/run/guest-output/application/control/run.json \
  --pcap /path/to/run/guest-output/ws73.pcap \
  --capture-stats /path/to/run/guest-output/capture-stats.txt \
  --output /path/to/new-verification
```

结果`RX_CORROBORATED`：22个逐轮原始接收证明，包含命令Complete/扫描窗口、
随机数据、地址/RSSI、广播停止阴性对照及移除期间survivor控制。完整物理流程
通过不等于故障恢复通过：实际拔出时还有一条xHCI `WARN Set TR Deq Ptr cmd
failed due to incorrect slot or ep state`，taint仍0且B未中断；该警告保留待定位，
不被通用panic/oops匹配器遗漏后称为“无告警”。无人工恢复、原生主机对照、
四设备两组并行、完整systemd sandbox及其他S0–S6条件仍未验收。

### 真实 WS73 的人工传输错误恢复支持

`ws73_target.py run --fault-recovery`与`--qmp-hotplug`互斥。先完成20轮真实
交换，随后仅arm第一个USB对象的测试脉冲，再用普通用户发起扫描。一次成功的
host bulk IN81数据被明确丢弃并向guest报IOERROR；整个测试没有人工拔插、
QMP device_del/readd或主机USB reset/detach。这是人工错误下的恢复支持证据，
不能关闭自然故障根因、消失恢复、原生主机或完整恢复矩阵条件。

```sh
python3 tools/ws73_target.py run \
  --prepared /absolute/private/native-module-prepared-with-new-qemu \
  --ports 1-2.1.4 1-2.1.1 --fault-recovery --timeout 420 \
  --output /absolute/private/fresh-artificial-recovery-run
```

新QEMU必须重新通过同一镜像/签名模块的空USB scratch-root boot，随后重新
prepare；旧prepared目录不能替换二进制或就地改镜像。native profile在加载
WS73前启用guest xHCI trace，成功及失败都封存trace和各CPU统计。

[2026-10-10记录](evidence/ws73-vm-artificial-recovery-20261010.json)中第4只
host地址101与guest地址2均保持不变。QEMU只注入一次178字节成功回复；guest
xHCI报告USB Transaction Error并成功Reset Endpoint。回复已丢失，因此
1001最终超时为-110，并非native直接收到-71。恢复预算由1/2变为2/2，经
4秒协议恢复产生新generation3；第1只始终generation2且实际扫描启停成功。
从故障命令开始到重新观察Ready为10.28秒。slkd PID522/start_ticks333与bus
owner保持不变，两轮真实恢复RF成功；独立host校验1163条USB记录、零capture
丢包、22份RX证明，xHCI ringbuffer零overrun。公开JSON仅含解码结果、诊断
和工件hash；原始抓包留在私有目录。

北极星仍为7/8：人工错误恢复支持已增加，但自然故障根因、物理拔出时的xHCI
warning、单/双/四设备矩阵及未经授权的原生主机对照均未完成。
