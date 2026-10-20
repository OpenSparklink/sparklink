#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""This thread's physical USB boundary. No USB opens, resets or downloads.

VID/PID and the user's placement are not chip identification. The serial pin
detects replacement; HCC must independently confirm the declared model in VM.
Pure usb_properties and historical decoders intentionally remain unrestricted.
"""
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

from build_resources import workspace

POLICY = Path(__file__).resolve().parents[1] / 'project/lab-resource-policy.json'
IMAGES = ('ws73.bin', 'wifi_cali.bin', 'btc_cali.bin')


def policy():
    data = json.loads(POLICY.read_text())
    if data['schema_version'] != 1 or set(data['ports']) & set(data['forbidden_ports']):
        raise ValueError('invalid disjoint thread USB allocation')
    return data



def execution_state_errors(state, allocation):
    """Validate current execution views only; historical evidence is immutable.

    This is not a device/model/firmware qualification. Never repair an
    authorization mismatch from an old status field or silently widen policy.
    """
    current = state.get('hardware_resource_allocation')
    if not isinstance(current, dict):
        return ['goal: missing hardware resource allocation']
    expected = {
        'policy': 'project/lab-resource-policy.json',
        'owner': allocation['owner'],
        'allowed_U': sorted(p for p, v in allocation['ports'].items() if v['expected_model'] == 'U'),
        'allowed_E': sorted(p for p, v in allocation['ports'].items() if v['expected_model'] == 'E'),
        'forbidden': allocation['forbidden_ports'],
        'runtime_directory': allocation['run_root'],
        'source_worktree': allocation['worktree'],
    }
    errors = ['goal: hardware allocation differs from policy: ' + key
              for key, value in expected.items() if current.get(key) != value]
    constraint = state.get('hardware_constraint', {})
    if not isinstance(constraint, dict):
        errors.append('goal: invalid hardware constraint')
    else:
        for key in ['current_operational_scope', 'topology_revision']:
            if key in constraint:
                errors.append('goal: stale independent hardware authority: ' + key)
        if constraint.get('operational_scope_ref') != 'hardware_resource_allocation.policy':
            errors.append('goal: hardware constraint must reference the current policy')
    return errors


def selected(ports, allocation=None):
    data = allocation if allocation is not None else policy()
    if not ports or len(ports) != len(set(ports)):
        raise ValueError('explicit distinct allocated topology ports required')
    if any(p not in data['ports'] for p in ports):
        raise ValueError('port outside this thread whitelist; no fallback: ' + repr(ports))
    return [data['ports'][p]['expected_model'] for p in ports]


def check_paths(output, prepared, allocation=None):
    data = allocation if allocation is not None else policy()
    root = (workspace() / data['run_root']).resolve()
    for value in [output, prepared]:
        if not Path(value).resolve().is_relative_to(root):
            raise ValueError('new physical runs/prepared artifacts must be inside ' + str(root))
    if Path(__file__).resolve().parents[1] != (workspace() / data['worktree']).resolve():
        raise ValueError('physical execution requires this thread independent worktree')


def snapshot(port, allocation=None, sysfs=Path('/sys/bus/usb/devices')):
    data = allocation if allocation is not None else policy()
    selected([port], data)
    root = sysfs / port
    if not root.exists():
        raise ValueError(port + ': allocated device missing; coordinate, no replacement')
    def read(p, name):
        return (p / name).read_text().strip()
    hub = port.rsplit('.', 1)[0]
    parent = sysfs / hub
    expected = data['hubs'][hub]
    if (read(parent, 'idVendor'), read(parent, 'idProduct')) != (expected['vid'], expected['pid']):
        raise ValueError(port + ': upstream hub identity changed')
    if data['controller'] not in root.resolve().parts or root.resolve().parent != parent.resolve():
        raise ValueError(port + ': controller or parent topology changed')
    if (read(root, 'idVendor'), read(root, 'idProduct')) != ('ffff', '3733'):
        raise ValueError(port + ': unexpected USB descriptor identity')
    serial = read(root, 'serial')
    if hashlib.sha256(serial.encode()).hexdigest() != data['ports'][port]['serial_sha256']:
        raise ValueError(port + ': serial changed; coordinate mapping, no inherited model')
    interfaces = []
    for interface in sorted(root.glob(port + ':*')):
        driver = interface / 'driver'
        interfaces.append(dict(name=interface.name, endpoints=int(read(interface, 'bNumEndpoints'), 16),
                               driver=driver.resolve().name if driver.exists() else None))
    if len(interfaces) != 1 or interfaces[0]['endpoints'] not in [2, 5]:
        raise ValueError(port + ': expected one ROM/runtime interface')
    return dict(port=port, declared_model=data['ports'][port]['expected_model'],
                model_basis=data['ports'][port]['model_basis'], serial_sha256=data['ports'][port]['serial_sha256'],
                controller=data['controller'], hub=hub, interfaces=interfaces,
                bus=int(read(root, 'busnum')), device=int(read(root, 'devnum')))


def check_firmware(package, ports, prepared_root, allocation=None):
    """Current driver has one image directory. Mixed cold boot is forbidden.

    Check the actual prepared root as well as preparation provenance. Neither
    a user label nor a runtime-only root proves which image is in device RAM.
    """
    data = allocation if allocation is not None else policy()
    models = selected(ports, data)
    if len(set(models)) != 1:
        raise ValueError('mixed E/U disabled: qualified per-device firmware flow missing')
    expected = data['firmware'][models[0]]
    selection = package.get('explicit_firmware')
    if selection != dict(model=models[0], **expected):
        raise ValueError('explicit matching SDK110 E/US three-image provenance required; no old default')
    if package.get('native_vm', {}).get('runtime_only'):
        raise ValueError('runtime-only adoption needs independently bound per-device image provenance')
    for directory in ['lib/firmware/sparklink/ws73', 'usr/lib/firmware/sparklink/ws73']:
        for name, expected_file in expected['images'].items():
            path = prepared_root / 'root' / directory / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('regular prepared firmware file required: ' + str(path))
            raw = path.read_bytes()
            if dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)) != expected_file:
                raise ValueError('actual prepared image differs from explicit SDK110 model: ' + str(path))
    return selection


def explicit_firmware(model, directory, allocation=None):
    data = allocation if allocation is not None else policy()
    if model not in data['firmware']:
        raise ValueError('explicit U/E board model required; no automatic ROM selection')
    expected = data['firmware'][model]
    for name, record in expected['images'].items():
        raw = (directory / name).read_bytes()
        if dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw)) != record:
            raise ValueError('SDK110 model/image mismatch: ' + name)
    return dict(model=model, **expected)


def board_configuration(directory, model=None):
    """Host preparation only: reuse the actual exporter, never manifest code."""
    import importlib.util
    if model is not None and model not in ('U', 'E'):
        raise ValueError('explicit U/E board configuration selection required')
    path = Path(__file__).with_name('ws73-board-config.py')
    spec = importlib.util.spec_from_file_location('ws73_board_input', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(selected_model=model, **module.verify(directory))


def check_board_configuration(package, ports, prepared, allocation=None):
    models = selected(ports, allocation)
    proof = package.get('board_configuration', {})
    if (len(set(models)) != 1 or type(package.get('board_configuration_contract_version')) is not int
            or package['board_configuration_contract_version'] != 1
            or proof.get('selected_model') != models[0]):
        raise ValueError('fresh board inputs bound to explicit homogeneous model required')
    current = board_configuration(Path(proof['manifest']['path']).parent, models[0])
    if current != proof:
        raise ValueError('board input provenance changed after preparation')
    for directory in ('lib/firmware/sparklink/ws73', 'usr/lib/firmware/sparklink/ws73'):
        for name, expected in proof['images'].items():
            path = Path(prepared) / 'root' / directory / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('regular prepared board payload required')
            raw = path.read_bytes()
            if dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()) != expected:
                raise ValueError('prepared board payload differs from provenance: ' + name)
    return proof


def board_configuration_exit_gate(record):
    """Decode a sealed receipt, not a hardware or current-file qualification.

    Old captures retain their original contract. All new live physical runs
    obtain this version and proof from PhysicalBoundary before any attach.
    """
    allocation = record.get('physical_resource_allocation', {})
    if not isinstance(allocation, dict):
        return False
    if ('board_configuration_contract_version' not in record
            and 'board_configuration' not in allocation):
        return True  # Historical decoder only; not a live fallback.
    try:
        proof = allocation['board_configuration']
        if (type(record['board_configuration_contract_version']) is not int
                or record['board_configuration_contract_version'] != 1
                or type(proof['version']) is not int or proof['version'] != 1
                or proof['scope'] != 'INPUT_PROVENANCE_ONLY_NO_HARDWARE_ACCEPTANCE'
                or proof['profile'] != 'ws73-sdk-efuse-customization-v1'
                or proof['selected_model'] not in ('U', 'E')
                or proof['selected_model'] != allocation['firmware']['model']
                or type(proof['usb_link_check']) is not int
                or proof['usb_link_check'] not in (0, 1)
                or set(proof['images']) != {'bsle_custom.bin', 'pm_config.bin'}):
            return False
        import re
        for key in ('source', 'manifest', 'exporter'):
            item = proof[key]
            if not isinstance(item['path'], str) or not item['path'].startswith('/'):
                return False
            if key != 'exporter' and (type(item['size']) is not int or item['size'] <= 0):
                return False
            if not isinstance(item['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', item['sha256']):
                return False
        for name, size in [('bsle_custom.bin', 140), ('pm_config.bin', 4)]:
            item = proof['images'][name]
            if (type(item['size']) is not int or item['size'] != size
                    or not isinstance(item['sha256'], str)
                    or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
                return False
        return True
    except (KeyError, TypeError, AttributeError):
        return False


def check_available(row, proc=Path('/proc')):
    """Read-only occupancy check, never detach. Root fds may be unobservable.

    Actual passthrough additionally refuses kernel-driver detach/reset. This
    cooperative lease does not prevent an uncoordinated privileged operator.
    """
    if row['interfaces'][0]['driver'] is not None:
        raise ValueError(row['port'] + ': interface occupied; coordinate, never detach')
    node = f"/dev/bus/usb/{row['bus']:03}/{row['device']:03}"
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            for fd in (process / 'fd').iterdir():
                try:
                    if os.readlink(fd) == node:
                        raise ValueError(row['port'] + ': USB fd occupied by pid ' + process.name)
                except (FileNotFoundError, PermissionError):
                    pass
        except (FileNotFoundError, PermissionError):
            pass


def assigned_usb_port(address, sysfs=Path('/sys/bus/usb/devices')):
    """Resolve a live assignment to topology, never use its number as identity."""
    bus = int(address['bus'], 10)
    if 'port' in address:
        return f"{bus}-{address['port']}"
    device = int(address['device'], 10)
    matches = []
    for root in sysfs.iterdir():
        if ':' in root.name or not (root / 'devnum').exists():
            continue
        try:
            if (int((root / 'busnum').read_text()), int((root / 'devnum').read_text())) == (bus, device):
                matches.append(root.name)
        except FileNotFoundError:
            continue  # Removal cannot turn an unresolved assignment into free.
    return matches[0] if len(matches) == 1 else None


def check_vm_xml(raw, ports, allocation=None, sysfs=Path('/sys/bus/usb/devices')):
    """Only live host assignments. Explicit other-thread leaves are allowed.

    An unresolved/matching WS73 vendor filter could claim our next enumeration;
    it requires coordination. A shared hub/controller assignment also conflicts.
    No inactive configuration, management intent, or cached device number proves
    that the current device is free. This supplements drivers/fds/port leases.
    """
    data = allocation if allocation is not None else policy()
    selected(ports, data)
    root = ET.fromstring(raw)
    if root.tag != 'domain' or root.find('devices') is None:
        raise ValueError('invalid live domain XML; coordinate')
    assignments = []
    for dev in root.findall('./devices/hostdev'):
        kind = dev.get('type')
        source = dev.find('source')
        if source is None:
            raise ValueError('live VM hostdev without source; coordinate')
        address = source.find('address')
        if kind == 'pci':
            if address is None:
                raise ValueError('unresolved live PCI assignment; coordinate')
            bdf = '{:04x}:{:02x}:{:02x}.{:x}'.format(
                *[int(address.get(k), 0) for k in ['domain', 'bus', 'slot', 'function']])
            assignments.append(dict(type=kind, controller=bdf))
            if bdf == data['controller']:
                raise ValueError('shared USB controller assigned to a live VM; coordinate')
        elif kind == 'usb':
            vendor, product = source.find('vendor'), source.find('product')
            vid = int(vendor.get('id'), 0) if vendor is not None else None
            pid = int(product.get('id'), 0) if product is not None else None
            port = assigned_usb_port(address.attrib, sysfs) if address is not None else None
            assignments.append(dict(type=kind, port=port, vid=vid, pid=pid))
            if port is not None:
                if any(p == port or p.startswith(port + '.') for p in ports):
                    raise ValueError(port + ': allocated leaf or ancestor assigned to a live VM; coordinate')
            elif vid in (None, 0xffff) and pid in (None, 0x3733):
                raise ValueError('unresolved live WS73 USB selector; coordinate, no enumeration fallback')
    return assignments


def check_live_vms(ports, allocation=None):
    """Read-only libvirt inventory before our QEMU launch; failure stops launch.

    Only current assignments are relevant. Privileged fd visibility and later
    uncoordinated QMP changes remain outside this observation, not a proof that
    every process is harmless. Never stop/detach or acquire another VM's device.
    """
    data = allocation if allocation is not None else policy()
    selected(ports, data)
    deadline = time.monotonic() + 5
    def query(*args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('live VM inventory deadline; coordinate')
        try:
            result = subprocess.run(['virsh', '-c', 'qemu:///system', *args],
                                    capture_output=True, text=True, timeout=remaining, check=True)
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError('live VM inventory unavailable; coordinate, no hardware launch') from error
        if len(result.stdout.encode()) > 1024 * 1024:
            raise ValueError('live VM inventory exceeds bounded report')
        return result.stdout
    names = query('list', '--name').splitlines()
    names = [name for name in names if name]
    if len(names) > 64 or len(set(names)) != len(names):
        raise ValueError('live VM inventory invalid or over budget')
    observations = []
    for name in names:
        raw = query('dumpxml', '--', name)
        try:
            assignments = check_vm_xml(raw, ports, data)
        except (ValueError, TypeError, ET.ParseError) as error:
            raise ValueError(name + ': ' + str(error)) from error
        observations.append(dict(name=name, xml_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                                 assignments=assignments))
    return dict(status='NO_CONFLICT_OBSERVED_NOT_HARDWARE_QUALIFICATION', checked_ports=list(ports), live_vms=observations,
                limits='Read-only live libvirt assignments; drivers/visible fds/leases are checked separately. '
                       'Privileged fd visibility and uncoordinated later changes are not proven absent.')


@contextmanager
def port_leases(ports, allocation=None):
    """Shared workspace inodes, per-port exclusion; no global hub ownership."""
    data = allocation if allocation is not None else policy()
    selected(ports, data)
    root = workspace() / '.dev/ws73-port-leases'
    root.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        descriptors = []
        for port in sorted(ports):
            stream = stack.enter_context((root / (port + '.lock')).open('a+'))
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError(port + ': leased by another task; coordinate') from error
            descriptors.append(stream.fileno())
        yield tuple(descriptors)


def check_hcc(raw, expected):
    wanted = f'source=HCC_GET_CHIP_TYPE model=WS73{expected} model_id={2 if expected == "E" else 0} bus=USB bus_id=0'
    if expected not in ['U', 'E'] or raw != wanted:
        raise ValueError('actual HCC model/bus differs from explicit board/firmware')
    return dict(source='HCC_GET_CHIP_TYPE', model=expected, bus='USB', raw=raw)


def observe_guest_hcc(identity, expected, sysfs=Path('/sys/bus/usb/devices')):
    """Bind existing driver HCC metadata to a live registration, without slkd.

    This observes runtime metadata; it neither downloads nor attests RAM/cold
    ROM. Read registration on both sides so replacement cannot reuse a cached
    chip result. Never manufacture a daemon Ready document for Native gates.
    """
    from ws73_north_star import registration, stable
    before = registration(identity['port'], sysfs)
    keys = ('port', 'index', 'generation', 'bus', 'device', 'address')
    if any(before[k] != identity[k] for k in keys):
        raise ValueError('HCC observation differs from selected Native registration')
    root = sysfs / identity['port']
    interfaces = list(root.glob(identity['port'] + ':*'))
    if len(interfaces) != 1:
        raise ValueError('one current guest HCC interface required')
    chip = check_hcc((interfaces[0] / 'chip_information').read_text().strip(), expected)
    if not stable(before, registration(identity['port'], sysfs)):
        raise ValueError('guest registration changed during HCC observation')
    return dict(before, hcc_chip=chip)


class PhysicalBoundary:
    """Recheck the same allocation on *every* QMP attach, including ROM return.

    usb_properties stays a pure codec usable by historical independent audits.
    This wrapper is exclusively on the live monitor, not the evidence decoder.
    """
    def __init__(self, ports, package, prepared, allocation=None):
        self.allocation = allocation if allocation is not None else policy()
        self.ports = list(ports)
        self.package, self.prepared = package, prepared
        self.models = selected(ports, self.allocation)
        self.firmware = check_firmware(package, ports, prepared, self.allocation)
        self.board_configuration = check_board_configuration(package, ports, prepared, self.allocation)
        self.observations = []
        for port in ports:
            self.check(port)

    def check(self, port):
        if port not in self.ports:
            raise ValueError('unselected device; no automatic replacement')
        row = snapshot(port, self.allocation)
        check_available(row)
        self.observations.append(row)
        return row

    def monitor(self, actual):
        boundary = self
        class Monitor:
            def __getattr__(self, name):
                return getattr(actual, name)

            def execute(self, command, arguments=None):
                if command == 'device_add':
                    args = arguments or {}
                    port = f"{args.get('hostbus')}-{args.get('hostport')}"
                    if port not in boundary.ports:
                        raise ValueError('live USB attach outside selected whitelist')
                    index = boundary.ports.index(port)
                    from ws73_target import usb_properties
                    if args != usb_properties(port, index):
                        raise ValueError('only individually guarded USB device passthrough permitted')
                    boundary.check(port)
                    check_firmware(boundary.package, boundary.ports, boundary.prepared, boundary.allocation)
                    check_board_configuration(boundary.package, boundary.ports, boundary.prepared, boundary.allocation)
                elif command == 'device_del':
                    if arguments not in [dict(id=f'ws73_{i}') for i in range(len(boundary.ports))]:
                        raise ValueError('may remove only this VM selected leaf devices')
                return actual.execute(command, arguments)
        return Monitor()
