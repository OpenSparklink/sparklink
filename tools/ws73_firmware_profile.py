#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit per-device OS input closure; no USB access or identity inference.

The provisioner owns a private, quiescent root. Profiles are input selections,
not silicon identities or attestations of running RAM. The C driver decodes
this unpublished format independently; live HCC must still match the model.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from ws73_firmware import HEADER, MAX_PAYLOAD, NAMES, split_combined

FILES = (*NAMES, 'bsle_custom.bin', 'pm_config.bin')
MODELS = {'U': 0, 'E': 2}
MAGIC = b'WS73P001'
CONTROLLER = '0000:00:02.0'
QEMU_DEVICE = 'qemu-xhci,id=xhci,addr=0x2,p2=8,p3=8'
BASE = Path('lib/firmware/sparklink/ws73')
INPUTS = Path('usr/share/sparklink/firmware-inputs')
PLAN = 'ws73-firmware-profiles.json'


def directory(controller, route):
    if (not isinstance(controller, str) or not re.fullmatch(r'[A-Za-z0-9:._-]{1,63}', controller)
            or not isinstance(route, str) or not 1 <= len(route) <= 15
            or any(not re.fullmatch(r'[1-9][0-9]{0,2}', p) or int(p) > 255 for p in route.split('.'))):
        raise ValueError('explicit bounded controller name and USB2 physical route required')
    return Path('sparklink/ws73/by-path') / (controller + '-usb2-' + route)


def record(blob):
    return dict(bytes=len(blob), sha256=hashlib.sha256(blob).hexdigest())


def encode(model, records):
    if model not in MODELS or set(records) != set(FILES):
        raise ValueError('explicit U/E and all five file records required')
    hashes = []
    for name in FILES:
        item = records[name]
        if (not isinstance(item, dict) or type(item.get('bytes')) is not int or item['bytes'] <= 0
                or not isinstance(item.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', item['sha256']) or item['sha256'] == '0' * 64):
            raise ValueError('bounded file identity required: ' + name)
        size = item['bytes']
        if ((name in NAMES and not HEADER < size <= HEADER + MAX_PAYLOAD)
                or (name == 'bsle_custom.bin' and size != 140) or (name == 'pm_config.bin' and size != 4)):
            raise ValueError('selected file outside its input bound: ' + name)
        hashes.append(bytes.fromhex(item['sha256']))
    return MAGIC + bytes([MODELS[model], 0, 0, 0]) + b''.join(hashes)


def validate_blobs(blobs):
    if set(blobs) != set(FILES) or any(not isinstance(v, bytes) for v in blobs.values()):
        raise ValueError('five explicit byte inputs required')
    # Reuse the existing bounded SDK image parser, not a new firmware codec.
    if split_combined(b''.join(blobs[n] for n in NAMES)) != {n: blobs[n] for n in NAMES}:
        raise ValueError('image boundaries differ from explicit input files')
    if len(blobs['bsle_custom.bin']) != 140 or len(blobs['pm_config.bin']) != 4:
        raise ValueError('explicit 140-byte custom and four-byte PM inputs required')
    return {n: record(blobs[n]) for n in FILES}


def private_root(root):
    root = Path(root).resolve(strict=True)
    if root == Path('/') or not root.is_dir():
        raise ValueError('private quiescent staging root required')
    return root


def inside(root, relative):
    path = root / relative
    path.resolve().relative_to(root)
    return path


def stage(root, entries, controller=CONTROLLER):
    """Validate the whole plan before mutation; publish complete directories only.

    entries explicitly maps USB2 routes to (model, five byte inputs). No device
    scan or VID/PID selector. The caller serializes writes to this private root.
    IO failures retire this preparation; directories created here are rolled back.
    """
    root = private_root(root)
    if not isinstance(entries, dict) or not 1 <= len(entries) <= 8:
        raise ValueError('one to eight explicit routes required')
    planned = []
    for route, (model, blobs) in entries.items():
        name = directory(controller, route)
        target = inside(root, Path('lib/firmware') / name)
        if target.exists() or target.is_symlink():
            raise ValueError('refuse existing profile directory')
        files = validate_blobs(blobs)
        profile = encode(model, files)
        files['profile.bin'] = record(profile)
        planned.append((route, model, blobs, profile, files, name, target))
    if inside(root, PLAN).exists() or inside(root, PLAN).is_symlink():
        raise ValueError('refuse existing profile plan')
    published = []
    plan = dict(version=1, controller=controller, namespace='usb2', entries={},
                scope='Explicit OS inputs only;not cold-ROM identification,upload or executing-image attestation')
    try:
        for route, model, blobs, profile, files, name, target in planned:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.profile-', dir=target.parent) as tmp:
                temporary = Path(tmp) / target.name
                temporary.mkdir(mode=0o755)
                for filename, data in {**blobs, 'profile.bin': profile}.items():
                    p = temporary / filename
                    p.write_bytes(data)
                    p.chmod(0o644)
                if target.exists() or target.is_symlink():
                    raise ValueError('profile destination changed during staging')
                temporary.rename(target)
            published.append(target)
            plan['entries'][route] = dict(model=model, directory=str(name), files=files)
        inside(root, PLAN).write_text(json.dumps(plan, indent=2) + '\n')
        inside(root, PLAN).chmod(0o644)
    except BaseException:
        for path in published:
            shutil.rmtree(path)
        inside(root, PLAN).unlink(missing_ok=True)
        raise
    return plan


def verify(root, plan, routes=None, boot=True):
    root = private_root(root)
    if (not isinstance(plan, dict) or type(plan.get('version')) is not int
            or plan.get('version') != 1 or plan.get('namespace') != 'usb2'
            or not isinstance(plan.get('entries'), dict) or not 1 <= len(plan['entries']) <= 8):
        raise ValueError('versioned per-device input plan required')
    exported = inside(root, PLAN)
    if (exported.is_symlink() or not exported.is_file() or exported.stat().st_size > 65536
            or json.loads(exported.read_text()) != plan):
        raise ValueError('actual guest profile plan differs from prepared input')
    if routes is None:
        routes = list(plan['entries'])
    if not routes or len(set(routes)) != len(routes):
        raise ValueError('explicit distinct profile routes required')
    for route in routes:
        item = plan['entries'].get(route)
        if not item or item.get('directory') != str(directory(plan['controller'], route)):
            raise ValueError('profile route differs from its explicit controller input')
        records = item['files']
        if set(records) != {*FILES, 'profile.bin'}:
            raise ValueError('complete input closure required')
        profile = encode(item['model'], {n: records[n] for n in FILES})
        if record(profile) != records['profile.bin']:
            raise ValueError('profile identity differs from selected files')
        base = Path('lib/firmware') / item['directory']
        for name in [*FILES, 'profile.bin']:
            p = inside(root, base / name)
            if not boot and name in NAMES:
                if p.exists() or p.is_symlink():
                    raise ValueError('runtime-only root retains boot image')
                continue
            if p.is_symlink() or not p.is_file() or record(p.read_bytes()) != records[name]:
                raise ValueError('selected regular input missing or changed: ' + str(p))
        if inside(root, base / 'profile.bin').read_bytes() != profile:
            raise ValueError('actual encoded profile mismatch')
    return plan


def boot_paths(root, plan):
    verify(root, plan)
    return [inside(private_root(root), Path('lib/firmware') / item['directory'] / name)
            for item in plan['entries'].values() for name in NAMES]


def provision(root, model, service=None, routes=('1', '2', '3', '4')):
    """Consume preparation inputs into explicit direct guest USB2 slots.

    A homogeneous preparation is not permission to attach a different model.
    The live physical boundary still checks each selected leaf before every add.
    """
    root = private_root(root)
    blobs = {}
    for name in FILES:
        p = inside(root, BASE / name)
        if p.is_symlink() or not p.is_file():
            raise ValueError('regular explicit preparation input required')
        blobs[name] = p.read_bytes()
    files = validate_blobs(blobs)
    consumed = [inside(root, BASE / name) for name in FILES]
    if service is not None:
        selected = service.get('firmware_inputs', {})
        if (type(service.get('firmware_input_contract_version')) is not int
                or service.get('firmware_input_contract_version') != 1 or selected.get('model') != model
                or selected.get('directory') != str(INPUTS / model) or selected.get('files') != files):
            raise ValueError('service bundle firmware inputs differ from explicit preparation')
        for name in FILES:
            p = inside(root, INPUTS / model / name)
            if p.is_symlink() or not p.is_file() or p.read_bytes() != blobs[name]:
                raise ValueError('actual service input differs from preparation: ' + name)
            consumed.append(p)
    # Old global search-path files are not a live fallback in the new root.
    old_usr = Path('usr/lib/firmware/sparklink/ws73')
    for name in FILES:
        p = inside(root, old_usr / name)
        if p.exists() or p.is_symlink():
            raise ValueError('retired global service firmware path must not be staged')
    plan = stage(root, {route: (model, blobs) for route in routes})
    for p in consumed:
        p.unlink()
    verify(root, plan)
    return plan


def observed(raw, plan, route, expected):
    item = plan['entries'].get(route)
    if (not item or item['model'] != expected or item['directory'] != str(directory(plan['controller'], route))
            or raw != f"source=os-input directory={item['directory']} expected_model=WS73{expected} bus=USB filesystem_checked=18 execution_attested=0"):
        raise ValueError('current driver input selection differs from explicit plan')
    return dict(source='os-input', model=expected, directory=item['directory'], raw=raw,
                execution_attested=False)


def guest_observation(interface, expected, route, plan_path=Path('/') / PLAN,
                      cmdline=Path('/proc/cmdline')):
    required = 'ws73.firmware_profiles=1' in cmdline.read_text().split()
    if not plan_path.exists():
        if required:
            raise ValueError('required per-device input plan missing in guest')
        return None  # Historical/test observer without the new contract only.
    plan = json.loads(plan_path.read_text())
    return observed((interface / 'firmware_profile').read_text().strip(), plan, route, expected)


def exit_gate(result):
    if 'firmware_input_contract_version' not in result:
        return True  # Historical decoder, never a live preparation fallback.
    try:
        if type(result['firmware_input_contract_version']) is not int or result['firmware_input_contract_version'] != 1:
            return False
        allocation = result['physical_resource_allocation']
        plan = allocation['input_profiles']
        ports, checks = allocation['selected_ports'], allocation['hcc_checks']
        args = result['qemu_args']
        appends = [args[i+1] for i, value in enumerate(args[:-1]) if value == '-append']
        if (not ports or len(checks) != len(ports) or type(plan['version']) is not int or plan['version'] != 1
                or plan['controller'] != CONTROLLER or plan['namespace'] != 'usb2'
                or args.count(QEMU_DEVICE) != 1
                or sum(args[i] == '-device' and args[i+1] == QEMU_DEVICE for i in range(len(args)-1)) != 1
                or len(appends) != 1 or appends[0].split().count('ws73.firmware_profiles=1') != 1):
            return False
        for slot, (port, check) in enumerate(zip(ports, checks), 1):
            route = str(slot)
            if check['host_port'] != port or check['guest_port'] != '1-' + route:
                return False
            expected = plan['entries'][route]['model']
            if check['model'] != expected or check['bus'] != 'USB':
                return False
            if check['input_profile'] != observed(check['input_profile']['raw'], plan, route, expected):
                return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
