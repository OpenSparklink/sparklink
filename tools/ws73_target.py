#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare/run an isolated WS73 development guest; never install on the host.

Environment readiness is not physical North Star acceptance. The explicit
support command uses synthetic USB and cannot produce physical acceptance.
"""
import argparse
import copy
from datetime import datetime, timezone
import errno
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import select
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
from types import SimpleNamespace

from ws73_north_star import file_record, ordinary_identity
from ws73_capture import CaptureError, check_capture_stats, read_capture
import ws73_vm_native_root as native_vm
import ws73_lab_resources as resources
import ws73_firmware_upload_evidence as firmware_evidence
import ws73_firmware_profile as firmware_profile
from build_resources import build_lock, configuration as build_configuration, workspace as build_workspace, environment as build_environment

USERSPACE = Path(__file__).resolve().parents[1]
FIRMWARE_EVIDENCE_HELPERS = ('ws73_firmware_upload_evidence.py', 'ws73_boot_code_evidence.py',
                             'ws73_model_evidence.py', 'ws73_capture.py',
                             'ws73_firmware_profile.py', 'ws73_firmware.py')
# Local workspaces keep both repositories side by side. CI checks out the
# pinned kernel selftests inside its workspace instead of assuming that layout.
LINUX = Path(os.environ.get('SPARKLINK_KERNEL_SOURCE', USERSPACE.parent / 'linux')).resolve()
HERE = Path(__file__).resolve().parent


def lab_module():
    source = LINUX / 'tools/testing/selftests/sparklink/ws73-lab.py'
    spec = importlib.util.spec_from_file_location('ws73_lab', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def kernel_fault(text):
    source=LINUX/'tools/testing/selftests/sparklink/qemu_verdict.py'
    spec=importlib.util.spec_from_file_location('ws73_kernel_verdict',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return bool(module.KERNEL_FAULT.search(text))


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def config_required(path, module_profile=False):
    lines = path.read_text().splitlines()
    for name in ['RUST', 'SPARKLINK', 'SPARKLINK_WS73_USB',
                 'USB_MON', 'NET_9P', 'NET_9P_VIRTIO', '9P_FS', 'VIRTIO_PCI']:
        value = 'm' if module_profile and name in ['SPARKLINK_WS73_USB', 'NET_9P', 'NET_9P_VIRTIO', '9P_FS'] else 'y'
        if f'CONFIG_{name}={value}' not in lines:
            raise ValueError(f'CONFIG_{name}={value} required; do not silently omit capture or evidence export')


def board_files(directory):
    result = {}
    for name, size in [('bsle_custom.bin',140), ('pm_config.bin',4)]:
        source = directory / name
        if len(source.read_bytes()) != size:
            raise ValueError(f'{name}: expected exactly {size} raw bytes')
        result[name] = source
    return result


def copy_elf(source, target, root):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    dependencies = subprocess.check_output(['ldd', str(source)], text=True)
    for name in re.findall(r'(?:=>\s+)?(/[^\s()]+)', dependencies):
        p = Path(name)
        if p.is_file():
            dest = root / name.lstrip('/')
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)


def prepare(args):
    if getattr(args,'native_verification_openssl',None)is not None and getattr(args,'from_prepared',None)is None:
        raise ValueError('explicit verifier staging requires --from-prepared')
    # Hold through copying/sealing binaries from the shared debug target too.
    with build_lock() as build_fd:
        if getattr(args, 'from_prepared', None) is not None:
            return prepare_from_carrier(args)
        return prepare_locked(args, build_fd)


def carrier_root_files(root, expected=None):
    """Check the retained regular-file closure and snapshot link/mode inputs.

    The source is an explicitly retained private carrier, not an executing-image
    attestation. Never follow a source pathname outside that private root.
    """
    if root.is_symlink() or not root.is_dir():
        raise ValueError('regular retained carrier root directory required')
    root = root.resolve(strict=True)
    files, metadata = {}, {}
    for path in sorted(root.rglob('*')):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            metadata[relative] = dict(link=os.readlink(path))
        elif path.is_file():
            if path.resolve() != path or not path.is_relative_to(root):
                raise ValueError('retained carrier file escapes private root')
            files[relative] = file_record(path)
            metadata[relative] = dict(mode=path.stat().st_mode & 0o7777)
        elif not path.is_dir():
            raise ValueError('retained carrier contains unsupported special file')
    if expected is not None:
        records = {}
        for row in expected:
            relative = str(Path(row['path']).relative_to(root))
            if relative in records:
                raise ValueError('duplicate retained carrier file')
            records[relative] = row
        if files != records:
            raise ValueError('retained carrier root file closure changed')
    return dict(files=files, metadata=metadata)


def prepare_from_carrier(args):
    """Canonical per-leaf preparation; reuse frozen artifacts, not a second Host."""
    ordinary_identity()
    exclusive = ('kernel_build', 'qemu', 'busybox', 'dbus_daemon', 'tcpdump', 'python', 'firmware_dir',
                 'runtime_config_dir', 'board_model', *native_vm.OPTIONS,
                 'native_return_probe', 'native_channel_fd_probe',
                 'acb_probe_module', 'controller_directory_clients', 'discovery_lifetime_probe',
                 'native_return_fixture')
    if any(getattr(args, n, None) for n in exclusive) or getattr(args, 'native_runtime_only', False):
        raise ValueError('carrier preparation refuses global firmware, build and additional staging options')
    plan_path = getattr(args, 'device_inputs', None)
    if plan_path is None:
        raise ValueError('carrier preparation requires an explicit device input plan')
    plan_path = plan_path.resolve(strict=True)
    plan_identity = file_record(plan_path)
    selection = json.loads(plan_path.read_text())
    if (not isinstance(selection, dict) or set(selection) != {'version', 'entries'}
            or type(selection['version']) is not int or selection['version'] != 1):
        raise ValueError('version1 exact device input plan required')
    selections = copy.deepcopy(selection['entries'])
    if not isinstance(selections, list):
        raise ValueError('ordered device input entries required')
    for entry in selections:
        if not isinstance(entry, dict) or set(entry) != {'host_port', 'model', 'firmware_dir', 'board_dir'}:
            raise ValueError('exact explicit leaf/model/firmware/board fields required')
        for key in ('firmware_dir', 'board_dir'):
            value = Path(entry[key])
            entry[key] = str((plan_path.parent / value).resolve(strict=True))
    # Validate every leaf/file/provenance before copying or packing a carrier.
    with tempfile.TemporaryDirectory(prefix='ws73-input-check-') as temporary:
        selected = resources.prepare_device_inputs(Path(temporary), selections)
    source = args.from_prepared.resolve(strict=True)
    package = prepared(source)
    if ('native_vm' not in package or package['native_vm'].get('runtime_only')
            or not re.fullmatch('[0-9a-f]{40}', package.get('compiled_userspace_identity', ''))):
        raise ValueError('retained Native carrier with explicit compiled identity and boot inputs required')
    original_root = source / 'root'
    original = carrier_root_files(original_root, package['guest_files'])
    original_qemu = carrier_root_files((source / 'qemu-data').resolve(), package['native_vm']['qemu_data'])
    firmware_profile.verify(original_root, package['firmware_profiles'])
    output = args.output.resolve()
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('fresh sibling preparation directory required')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = copy.deepcopy(package)
    manifest.update(status='PREPARING', physical_acceptance=False,
                    scope='Explicit per-leaf preparation from retained Native artifacts;not a new compilation or hardware qualification',
                    started_at=datetime.now(timezone.utc).isoformat())
    try:
        root = output / 'root'
        subprocess.run(['cp', '--reflink=auto', '-a', str(original_root), str(root)], check=True)
        cloned = carrier_root_files(root)
        if ({n: r['sha256'] for n, r in cloned['files'].items()}
                != {n: r['sha256'] for n, r in original['files'].items()}
                or cloned['metadata'] != original['metadata']):
            raise ValueError('carrier clone differs from retained root')
        for name in ('bzImage', 'kernel.config', 'initramfs.cpio.gz'):
            native_vm.checked_copy(source / name, output / name)
        shutil.copytree(source / 'qemu-data', output / 'qemu-data', symlinks=True)
        manifest['native_vm']['qemu_data'] = [file_record(p) for p in sorted((output / 'qemu-data').rglob('*')) if p.is_file()]
        for entry in package['firmware_profiles']['entries'].values():
            shutil.rmtree(firmware_profile.inside(root, Path('lib/firmware') / entry['directory']))
        (root / firmware_profile.PLAN).unlink()
        staged = resources.prepare_device_inputs(root, selections)
        if staged != selected:
            raise ValueError('selected inputs changed while copying carrier')
        for key in ('explicit_firmware', 'board_configuration'):
            manifest.pop(key, None)
        manifest.update(staged)
        manifest['four_disconnect_progress_contract_version']=1
        manifest['four_dynamic_benchmark_contract_version']=1
        manifest['four_dynamic_benchmark_close_contract_version']=1
        manifest['four_dynamic_benchmark_pressure_contract_version']=1
        manifest['channel_sibling_business_contract_version']=4
        manifest['four_owned_contract_version']=1
        manifest['four_delivery_contract_version']=1
        manifest['four_subscription_contract_version']=1
        manifest['four_subscription_lifetime_contract_version']=1
        manifest['four_subscription_pressure_contract_version']=1
        inputs = [file_record(source / 'manifest.json'), file_record(source / 'root.btrfs'), plan_identity]
        # The current test entry point is source,not part of the frozen Rust ELF.
        shutil.copy2(HERE/'ws73_target_init.sh',root/'init');(root/'init').chmod(0o755)
        inputs.append(file_record(HERE/'ws73_target_init.sh'))
        tool_root = root / 'usr/share/sparklink/tools'
        # Existing carriers predate these shared fixture helpers. A fresh
        # preparation must stage the new dependency closure, not just refresh
        # filenames already present in the retained root.
        paths = set(tool_root.glob('*.py')) | {tool_root / name for name in
            ('ws73_native_pair.py', 'ws73_channel_sibling.py', 'ws73_ssap_command_policy.py', 'ws73_ssap_command_deadline.py', 'ws73_ssap_read_provider.py', 'ws73_ssap_sdk_read_provider.py','ws73_ssap_sdk_write_provider.py','ws73_ssap_write_unregister.py','ws73_ssap_write_owner_exit.py','ws73_ssap_write_down.py','ws73_native_event_retry.py','ws73_ssap_write_deadline.py', 'ws73_ssap_provider_unregister.py', 'ws73_ssap_provider_owner_exit.py', 'ws73_ssap_provider_deadline.py')}
        for path in sorted(paths):
            client = native_vm.STAGED_PYTHON_CLIENTS.get(path.name)
            current = HERE / (client if client is not None else path.name)
            if not current.is_file():
                raise ValueError('retained carrier contains a retired or private staged tool: ' + path.name)
            if client is not None and current.read_bytes() != path.read_bytes():
                raise ValueError('frozen SDK consumer differs from its current explicit source: ' + path.name)
            shutil.copy2(current, path)
            inputs.append(file_record(current))
        for entry in staged['device_inputs']['entries']:
            proof = entry['board_configuration']
            inputs += [file_record(Path(proof[key]['path'])) for key in ('manifest', 'source', 'exporter')]
        for entry in selections:
            inputs += [file_record(Path(entry['firmware_dir']) / n) for n in resources.IMAGES]
            inputs += [file_record(Path(entry['board_dir']) / n) for n in ('bsle_custom.bin', 'pm_config.bin')]
        inputs += [file_record(Path(__file__)), file_record(resources.POLICY)]
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=USERSPACE, text=True).strip()
        manifest.update(inputs=inputs, userspace_head=head,
                        carrier_parent=dict(manifest=file_record(source / 'manifest.json'),
                                            artifact=file_record(source / 'root.btrfs'), root_inputs=original),
                        new_production_compilation=False)
        manifest['native_vm']['parent_carrier_userspace_head'] = package['native_vm']['userspace_head']
        manifest['native_vm']['userspace_head'] = head
        if getattr(args,'native_discovery_config',None)is not None:
            native_vm.stage_discovery_config(args.native_discovery_config,native_vm.retained_daemon(root),root,manifest)
        if getattr(args,'native_verification_openssl',None)is not None:
            native_vm.stage_numeric_verifier(args.native_verification_openssl,root,manifest,copy_elf)
        ports = [s['host_port'] for s in selections]
        resources.check_firmware(manifest, ports, output)
        resources.check_board_configuration(manifest, ports, output)
        manifest['guest_files'] = [file_record(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()]
        staged_root = carrier_root_files(root, manifest['guest_files'])
        native_vm.pack(args, manifest, root)
        if (carrier_root_files(original_root, package['guest_files']) != original
                or carrier_root_files((source / 'qemu-data').resolve(), package['native_vm']['qemu_data']) != original_qemu
                or carrier_root_files(root, manifest['guest_files']) != staged_root
                or prepared(source) != package
                or any(file_record(r['path']) != r for r in inputs + package['userspace_sources'])):
            raise ValueError('carrier or source inputs changed while preparing')
        manifest['artifacts'] = [file_record(output / n) for n in ('bzImage', 'kernel.config', 'initramfs.cpio.gz', 'root.btrfs')]
        manifest['status'] = 'PREPARED'
    except Exception as error:
        manifest.update(status='FAIL', error=str(error))
    finally:
        manifest['finished_at'] = datetime.now(timezone.utc).isoformat()
        write_json(output / 'manifest.json', manifest)
    print(manifest['status'], output / 'manifest.json')
    return 0 if manifest['status'] == 'PREPARED' else 1


def prepare_locked(args, build_fd):
    ordinary_identity()
    if getattr(args, 'device_inputs', None) is not None:
        raise ValueError('per-leaf input preparation requires an explicit retained carrier')
    args.tcpdump = getattr(args, 'tcpdump', None) or Path('/usr/bin/tcpdump')
    args.python = getattr(args, 'python', None) or Path(sys.executable)
    required = ('kernel_build', 'qemu', 'busybox', 'dbus_daemon', 'firmware_dir', 'runtime_config_dir')
    if any(getattr(args, name, None) is None for name in required):
        raise ValueError('complete build, runtime and explicit model inputs required')
    if getattr(args, 'board_model', None) not in ['U', 'E']:
        raise ValueError('explicit U/E firmware input profile required;no global default')
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {'version':1, 'scope':'isolated development environment preparation',
                'physical_acceptance':False, 'status':'PREPARING', 'inputs':[],
                'board_qualification':'NOT_ASSERTED', 'started_at':datetime.now(timezone.utc).isoformat()}
    manifest['runtime_address_contract_version'] = 1
    manifest['four_disconnect_progress_contract_version'] = 1
    manifest['four_dynamic_benchmark_contract_version'] = 1
    manifest['four_dynamic_benchmark_close_contract_version'] = 1
    manifest['four_dynamic_benchmark_pressure_contract_version'] = 1
    manifest['channel_sibling_business_contract_version'] = 4
    manifest['four_owned_contract_version'] = 1
    manifest['four_delivery_contract_version'] = 1
    manifest['four_subscription_contract_version'] = 1
    manifest['four_subscription_lifetime_contract_version'] = 1
    manifest['four_subscription_pressure_contract_version'] = 1
    manifest['managed_prefix_geometry_contract_version'] = 1
    manifest['firmware_evidence_contract_version'] = 1
    manifest['link_measurement_contract_version'] = 1
    manifest['link_payload_preference_contract_version'] = 1
    manifest['socket_benchmark_role_contract_version'] = 1
    manifest['benchmark_ssap_contract_version'] = 2
    manifest['benchmark_credit_observation_contract_version'] = 1
    manifest['benchmark_hcc_observation_contract_version'] = 1
    manifest['benchmark_link_probe_contract_version'] = 1
    manifest['benchmark_trace_contract_version'] = 1
    manifest['benchmark_process_resource_contract_version'] = 1
    from ws73_ssap_initialization import CURRENT_EXCHANGE_CONTRACT
    manifest['ssap_exchange_contract_version'] = CURRENT_EXCHANGE_CONTRACT
    manifest['ssap_update_delivery_contract_version'] = 2
    manifest['application_role_contract_version'] = 2
    manifest['ssap_subscription_contract_version'] = 1
    manifest['ssap_subscription_shared_contract_version'] = 1
    manifest['ssap_subscription_shared_lifetime_contract_version'] = 1
    manifest['ssap_subscription_shared_pressure_contract_version'] = 1
    manifest['ssap_subscription_renewal_contract_version'] = 1
    manifest['ssap_subscription_pressure_contract_version'] = 1
    manifest['ssap_subscription_owner_loss_contract_version'] = 1
    manifest['ssap_subscription_inflight_release_contract_version'] = 1
    manifest['ssap_subscription_inflight_expiry_contract_version'] = 1
    manifest['ssap_subscription_snapshot_contract_version'] = 1
    try:
        module_profile = native_vm.enabled(args)
        lifetime_probe=getattr(args,'discovery_lifetime_probe',False)
        if lifetime_probe and not module_profile:raise ValueError('discovery lifetime SDK probe requires isolated native VM')
        config_required(args.kernel_build / '.config', module_profile)
        lab = lab_module()
        images = lab.firmware(args)
        board = board_files(args.runtime_config_dir)
        if getattr(args, 'board_model', None):
            manifest['explicit_firmware'] = resources.explicit_firmware(args.board_model, args.firmware_dir)
            manifest['board_configuration'] = resources.board_configuration(args.runtime_config_dir, args.board_model)
            manifest['board_configuration_contract_version'] = 1
            manifest['resource_contract_version'] = 1
        inputs = [args.kernel_build/'arch/x86/boot/bzImage',args.kernel_build/'.config',
                  args.qemu,args.busybox,args.dbus_daemon,args.tcpdump,args.python,
                  USERSPACE/'data/dbus/sparklink.conf',Path(__file__),HERE/'ws73_target_init.sh',
                  HERE/'ws73_usb_partial_diagnostic.py',HERE/'ws73_usb_lifecycle.py',
                  HERE/'ws73_vm_native_root.py',HERE/'ws73_application_client.py',HERE/'ws73_application_role.py',HERE/'ws73_role_snapshot.py',HERE/'ws73_application_discovery.py',
                  HERE/'ws73_discovery_policy_capture.py', HERE/'ws73_runtime_address.py', HERE/'ws73_firmware_profile.py',
                  HERE/'ws73_managed_queue_support.py',HERE/'ws73_model_hold.py',
                  HERE/'ws73_channel_daemon_crash.py',HERE/'ws73_ssap_daemon_restart.py',HERE/'ws73_daemon_channel_fd.py',HERE/'ws73_target_guest.py',HERE/'ws73_north_star.py',HERE/'ws73_capture.py',HERE/'ws73_rf_rounds.py',HERE/'ws73_parallel.py',HERE/'ws73_parallel_data.py',HERE/'ws73_credit_observation.py',
                  HERE/'ws73_security_install_hold.py',HERE/'ws73_security_agent.py',HERE/'ws73_security_cli.py',HERE/'ws73_target_control.py',HERE/'ws73_connection_control.py',HERE/'ws73_connection_objects.py',HERE/'ws73_link_measurement.py',HERE/'ws73_link_payload.py',HERE/'ws73_link_resync.py',HERE/'ws73_acb_transport_probe.py',HERE/'ws73_channel_socket.py',HERE/'ws73_benchmark.py',HERE/'ws73_socket_benchmark.py',HERE/'ws73_benchmark_ssap.py',HERE/'ws73_benchmark_timeline.py',HERE/'ws73_benchmark_resources.py',HERE/'ws73_dynamic_channels.py',HERE/'ws73_session_drain.py',HERE/'ws73_transport_watch.py',HERE/'ws73_hcc_memory.py',HERE/'ws73_channel_fairness.py',HERE/'ws73_ssap_value.py',HERE/'ws73_ssap_command.py',HERE/'ws73_ssap_command_policy.py',HERE/'ws73_ssap_command_deadline.py',HERE/'ws73_ssap_discovery.py',HERE/'ws73_ssap_access.py',HERE/'ws73_ssap_owned.py',HERE/'ws73_ssap_description.py',HERE/'ws73_ssap_read_provider.py',HERE/'ws73_ssap_sdk_read_provider.py',HERE/'ws73_ssap_sdk_write_provider.py',HERE/'ws73_ssap_write_unregister.py',HERE/'ws73_ssap_write_owner_exit.py',HERE/'ws73_ssap_write_down.py',HERE/'ws73_native_event_retry.py',HERE/'ws73_ssap_write_deadline.py',HERE/'ws73_ssap_provider_owner_exit.py',HERE/'ws73_ssap_provider_unregister.py',HERE/'ws73_ssap_provider_deadline.py',HERE/'ws73_ssap_owned_update.py',HERE/'ws73_ssap_update_delivery.py',HERE/'ws73_ssap_subscription.py',HERE/'ws73_ssap_shared.py',HERE/'ws73_ssap_receive_lifecycle.py',HERE/'ws73_ssap_sender_deadline.py',HERE/'ws73_ssap_owner_lifecycle.py',HERE/'ws73_ssap_requester_lifecycle.py',HERE/'ws73_ssap_initialization.py',HERE/'ws73_ssap_service_policy.py',HERE/'ws73_initialization_lifecycle.py',HERE/'ws73_observer_policy.py',HERE/'ws73_daemon_crash.py',
                  HERE/'ws73_target_recovery.py',HERE/'ws73_early_fault.py',
                  HERE/'ws73_event_copy_probe.py',
                  HERE/'ws73_diagnostic_probe.py',
                  HERE/'ws73_diagnostic_cancel.py',HERE/'ws73_diagnostic_hold.py',HERE/'ws73_diagnostic_deadline.py',HERE/'ws73_diagnostic_autonomous.py',HERE/'ws73_active_deadline.py',HERE/'ws73_management_setup.py',HERE/'ws73_management_queued.py',HERE/'ws73_management_queue_ready_peer.py',HERE/'ws73_connection_queued.py',HERE/'ws73_managed_queue_probe.c',HERE/'ws73_management_partial.py',HERE/'ws73_resource_file_gate.py',HERE/'ws73_connected_file_gate.py',HERE/'ws73_session_idle.py',HERE/'ws73_session_service.py',HERE/'ws73_trace_layout.py',HERE/'ws73_channel_grant.py',HERE/'ws73_channel_sibling.py',HERE/'ws73_native_pair.py',HERE/'ws73_revoke_prefix.py',HERE/'ws73_channel_prefix_hold.py',HERE/'ws73_channel_link_down.py',HERE/'ws73_channel_deadline.py',HERE/'ws73_security_capabilities.py',HERE/'ws73_security_numeric.py',HERE/'ws73_security_cancel.py',HERE/'ws73_key_agreement.py',HERE/'ws73_protected_grant.py',HERE/'ws73_management_ready_peer.py',HERE/'ws73_host_later_hold.py',HERE/'ws73_management_eviction.py',HERE/'ws73_daemon_hold.py',HERE/'ws73_daemon_removal.py',HERE/'ws73_vm_register_reset.py',HERE/'ws73_rom_chip.py',HERE/'ws73_register_reset_init.sh',
                  HERE/'ws73_native_return.py',HERE/'ws73_native_controller_return.py',HERE/'ws73_controller_directory.py',
                  LINUX/'tools/testing/selftests/sparklink/sparklink_event_copy_test.c',
                  LINUX/'tools/testing/selftests/sparklink/controller_event_copy_test.c',
                  LINUX/'tools/testing/selftests/sparklink/genl_registry_test.c',
                  LINUX/'tools/testing/selftests/sparklink/retired_uapi_test.c',
                  LINUX/'tools/testing/selftests/sparklink/retired_ioctl_cases.h',
                  LINUX/'tools/testing/selftests/sparklink/retired_ioctl_numbers.h',
                  LINUX/'tools/testing/selftests/sparklink/file_affinity_probe.h',
                  LINUX/'tools/testing/selftests/sparklink/sparklink_diagnostic_result_test.c',
                  LINUX/'tools/testing/selftests/sparklink/sparklink_setup_release_test.c',
                  LINUX/'tools/testing/selftests/sparklink/ssap_removed_uapi_test.c',
                  LINUX/'tools/testing/selftests/sparklink/sparklink_socket_type_test.c',
                  LINUX/'include/uapi/linux/sparklink_ioctl.h',
                  HERE/'ws73_bindings_probe.c',HERE/'ws73_bindings_probe.py',HERE/'ws73_registry_metadata.py',
                  LINUX/'tools/testing/selftests/sparklink/ws73-lab.py',
                  LINUX/'tools/testing/selftests/sparklink/qemu_verdict.py',
                  LINUX/'tools/testing/selftests/sparklink/daemon_radio_guest.sh',
                  *board.values(),*[args.firmware_dir/name for name in images]]
        if getattr(args, 'acb_probe_module', None) is not None:
            if not module_profile: raise ValueError('ACB selftest module requires native VM profile')
            inputs.append(args.acb_probe_module)
        if getattr(args,'native_channel_fd_probe',None) is not None:
            if not module_profile:raise ValueError('daemon fd client requires native VM profile')
            inputs.append(args.native_channel_fd_probe)
        manifest['inputs'] = [file_record(p) for p in inputs]
        for name in FIRMWARE_EVIDENCE_HELPERS:
            entry = file_record(HERE/name)
            if entry not in manifest['inputs']:
                manifest['inputs'].append(entry)
        manifest['inputs'] += [file_record(HERE / 'ws73_lab_resources.py'), file_record(resources.POLICY), file_record(HERE / 'build_resources.py'),
                               file_record(USERSPACE / 'project/build-resource-policy.json')]
        if 'board_configuration' in manifest:
            manifest['inputs'] += [file_record(Path(manifest['board_configuration'][key]['path'])) for key in ('manifest', 'source', 'exporter')]
        if lifetime_probe:manifest['inputs'].append(file_record(USERSPACE/'crates/libsparklink/examples/discovery_lifetime.rs'))
        source_files = subprocess.check_output(['git','ls-files','crates','bindings/python/sparklink','Cargo.toml','Cargo.lock'],cwd=USERSPACE,text=True).splitlines()
        source_files += subprocess.check_output(['git','ls-files','--others','--exclude-standard','crates','bindings/python/sparklink'],cwd=USERSPACE,text=True).splitlines()
        manifest['userspace_sources'] = [file_record(USERSPACE/p) for p in sorted(set(source_files))]
        manifest['userspace_head'] = subprocess.check_output(['git','rev-parse','HEAD'],cwd=USERSPACE,text=True).strip()
        build_env, manifest['build_resources'] = build_environment()
        default_target = build_workspace()/build_configuration()['cargo_native_development_target'] if module_profile else USERSPACE/'target'
        build_target = Path(build_env.get('CARGO_TARGET_DIR',default_target)).resolve()
        build_env['CARGO_TARGET_DIR'] = str(build_target)
        manifest['build_resources']['cargo_target_directory'] = str(build_target)
        with (output/'build.log').open('w') as log:
            subprocess.run(['cargo','build','--offline','--locked','-p','libsparklink','-p','slk-native','--lib'],cwd=USERSPACE,
                           env=build_env,pass_fds=(build_fd,),stdout=log,stderr=subprocess.STDOUT,check=True)
            subprocess.run(['cargo','build','--offline','--locked','-p','slkd','-p','slctl','-p','slktest','-p','slkconfig',
                            '-p','slkmon','-p','slkdump','--bins','--examples'],cwd=USERSPACE,
                           env=build_env,pass_fds=(build_fd,),stdout=log,stderr=subprocess.STDOUT,check=True)
            if lifetime_probe:
                subprocess.run(['cargo','build','--offline','--locked','-p','libsparklink','--example','discovery_lifetime'],cwd=USERSPACE,
                               env=build_env,pass_fds=(build_fd,),stdout=log,stderr=subprocess.STDOUT,check=True)
            subprocess.run(['gcc','-std=c11','-D_POSIX_C_SOURCE=200809L','-Wall','-Wextra','-Werror',
                            '-I'+str(USERSPACE/'crates/slk-native/include'),str(HERE/'ws73_bindings_probe.c'),
                            '-L'+str(build_target/'debug'),'-Wl,-rpath,/usr/lib','-l:libslk_native.so',
                            '-o',str(output/'native-bindings-probe')],stdout=log,stderr=subprocess.STDOUT,check=True)
        root = output/'root'
        for name in ['bin','usr/bin','dev','proc','sys','etc','tmp','run','evidence','boot']:
            (root/name).mkdir(parents=True,exist_ok=True)
        (root/'tmp').chmod(0o1777)
        shutil.copy2(args.busybox,root/'bin/busybox')
        for name in ['sh','mount','mdev','sleep','poweroff','dmesg','su','id','grep','awk','insmod','uname',
                     'seq','cat','pidof','chmod','mkdir','chown','kill','sync','setsid']:
            (root/'bin'/name).symlink_to('busybox')
        if getattr(args, 'native_return_fixture', False):
            if not module_profile: raise ValueError('Native return fixture requires native VM')
            source = HERE/'ws73_native_return_fixture.c'
            library = root/'usr/lib/sparklink/native-return-fixture.so'; library.parent.mkdir(parents=True,exist_ok=True)
            command = [os.environ.get('CC','cc'),'-std=gnu11','-O2','-fPIC','-shared','-fvisibility=hidden',
                       '-Wall','-Wextra','-Werror',str(source),'-o',str(library)]
            subprocess.run(command,check=True)
            manifest['native_return_fixture'] = dict(library=file_record(library),source=file_record(source),compile=command,
                compiler=file_record(Path(shutil.which(command[0])).resolve()),
                compiler_version=subprocess.check_output([command[0],'--version'],text=True).splitlines()[0])
            manifest['inputs'] += [file_record(source)]
            (root/'expected-native-return-sha256').write_text(file_record(library)['sha256']+'\n')
        if getattr(args, 'native_return_probe', None):
            if not getattr(args, 'native_return_fixture', False):raise ValueError('owner probe requires explicit Native return VM fixture')
            source=args.native_return_probe.resolve(strict=True)
            target=root/'bin/native-owner-probe';copy_elf(source,target,root);target.chmod(0o755)
            manifest['inputs'].append(file_record(source))
            manifest['native_return_probe']=dict(source=file_record(source),program=file_record(target),
                invocation='gdbus call --system --dest ORIGINAL_UNIQUE_OWNER --object-path OLD_CONNECTION --method org.sparklink.Connection.OpenChannel --timeout 1')
        programs = {'dbus-daemon':args.dbus_daemon,'tcpdump':args.tcpdump}
        if getattr(args,'controller_directory_clients',False):
            if not module_profile or not getattr(args,'native_service_bundle',None):
                raise ValueError('directory C/Python consumers require explicit native service bundle')
            source=HERE/'testing/controller_events/client.c';script=HERE/'testing/controller_events/client.py'
            header=USERSPACE/'crates/libsparklink/include/sparklink.h';probe=output/'controller-directory-client'
            command=[os.environ.get('CC','cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                     '-I'+str(header.parent),str(source),'-ldl','-o',str(probe)]
            subprocess.run(command,check=True);programs['controller-directory-client']=probe
            manifest['controller_directory_client_compile']=dict(command=command,source=file_record(source),
                header=file_record(header),script=file_record(script),compiler=file_record(Path(shutil.which(command[0])).resolve()),
                compiler_version=subprocess.check_output([command[0],'--version'],text=True).splitlines()[0])
            manifest['inputs'] += [file_record(source),file_record(script),file_record(header)]

        probe = output/'event-copy-probe'
        compile_probe = [os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                         str(LINUX/'tools/testing/selftests/sparklink/sparklink_event_copy_test.c'),'-o',str(probe)]
        subprocess.run(compile_probe, check=True)
        manifest['event_copy_probe_compile'] = compile_probe
        programs['event-copy-probe'] = probe
        current_probe = output/'controller-event-copy-probe'
        current_compile = [os.environ.get('CC','cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                           str(LINUX/'tools/testing/selftests/sparklink/controller_event_copy_test.c'),'-o',str(current_probe)]
        subprocess.run(current_compile, check=True)
        manifest['controller_event_copy_compile'] = current_compile
        programs['controller-event-copy-probe'] = current_probe
        registry_probe = output/'genl-registry-probe'
        registry_compile = [os.environ.get('CC','cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                            str(LINUX/'tools/testing/selftests/sparklink/genl_registry_test.c'),'-o',str(registry_probe)]
        subprocess.run(registry_compile, check=True)
        manifest['genl_registry_compile'] = registry_compile
        programs['genl-registry-probe'] = registry_probe
        retired_probe = output/'retired-uapi-probe'
        retired_compile = [os.environ.get('CC','cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                          str(LINUX/'tools/testing/selftests/sparklink/retired_uapi_test.c'),'-o',str(retired_probe)]
        subprocess.run(retired_compile,check=True)
        manifest['retired_uapi_compile'] = retired_compile
        programs['retired-uapi-probe'] = retired_probe
        diagnostic_probe = output/'diagnostic-result-probe'
        compile_diagnostic = [os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                              str(LINUX/'tools/testing/selftests/sparklink/sparklink_diagnostic_result_test.c'),
                              '-o',str(diagnostic_probe)]
        subprocess.run(compile_diagnostic, check=True)
        manifest['diagnostic_probe_compile'] = compile_diagnostic
        programs['diagnostic-result-probe'] = diagnostic_probe
        setup_probe = output/'setup-release-probe'
        compile_setup = [os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                         str(LINUX/'tools/testing/selftests/sparklink/sparklink_setup_release_test.c'),'-o',str(setup_probe)]
        subprocess.run(compile_setup, check=True)
        manifest['setup_release_probe_compile'] = compile_setup
        programs['setup-release-probe'] = setup_probe
        removed_probe = output/'ssap-removed-uapi-probe'
        compile_removed = [os.environ.get('CC','cc'),'-std=c11','-D_POSIX_C_SOURCE=200809L',
                           '-O2','-Wall','-Wextra','-Werror',
                           str(LINUX/'tools/testing/selftests/sparklink/ssap_removed_uapi_test.c'),
                           '-o',str(removed_probe)]
        subprocess.run(compile_removed, check=True)
        manifest['ssap_removed_uapi_probe_compile'] = compile_removed
        programs['ssap-removed-uapi-probe'] = removed_probe
        type_probe = output/'socket-type-probe'
        compile_type = [os.environ.get('CC','cc'),'-std=c11','-D_POSIX_C_SOURCE=200809L',
                        '-O2','-Wall','-Wextra','-Werror',
                        str(LINUX/'tools/testing/selftests/sparklink/sparklink_socket_type_test.c'),
                        '-o',str(type_probe)]
        subprocess.run(compile_type, check=True)
        manifest['socket_type_probe_compile'] = compile_type
        programs['socket-type-probe'] = type_probe
        queued_probe = output/'managed-queue-probe'
        compile_queued = [os.environ.get('CC','cc'),'-std=c11','-O2','-Wall','-Wextra','-Werror',
                          '-iquote'+str(LINUX/'include/uapi/linux'),str(HERE/'ws73_managed_queue_probe.c'),'-o',str(queued_probe)]
        subprocess.run(compile_queued, check=True)
        manifest['managed_queue_probe_compile'] = compile_queued
        programs['managed-queue-probe'] = queued_probe
        programs.update({name:build_target/'debug'/name for name in ['slkd','slctl','slktest','slkconfig','slkmon','slkdump']})
        programs['bus-policy-probe'] = build_target/'debug/examples/bus_policy_probe'
        programs['ws73-security-agent-probe'] = build_target/'debug/examples/native_security_agent_probe'
        programs['native-bindings-probe'] = output/'native-bindings-probe'
        if lifetime_probe:programs['discovery-lifetime-probe']=build_target/'debug/examples/discovery_lifetime'
        shared_library=build_target/'debug/liblibsparklink.so'
        native_shared_library=build_target/'debug/libslk_native.so'
        manifest['unstripped_programs'] = [file_record(p) for p in [*programs.values(),shared_library,native_shared_library]]
        for name, source in programs.items():
            copy_elf(source,root/'bin'/name,root)
            (root/'bin'/name).chmod(0o755)
            subprocess.run(['strip','--strip-debug',str(root/'bin'/name)],check=True)
        copy_elf(shared_library,root/'usr/lib/libsparklink.so',root)
        copy_elf(native_shared_library,root/'usr/lib/libslk_native.so',root)
        for filename in ('libsparklink.so', 'libslk_native.so'):
            subprocess.run(['strip','--strip-debug',str(root/'usr/lib'/filename)],check=True)
        manifest['native_security_agent_probe']=file_record(root/'bin/ws73-security-agent-probe')
        if lifetime_probe:manifest['discovery_lifetime_probe']=dict(binary=file_record(root/'bin/discovery-lifetime-probe'),source=file_record(USERSPACE/'crates/libsparklink/examples/discovery_lifetime.rs'))
        shutil.copytree(USERSPACE/'bindings/python/sparklink',root/'usr/share/sparklink/python/sparklink',
                        ignore=shutil.ignore_patterns('__pycache__'))
        python = args.python.resolve()
        copy_elf(python,root/'usr/bin'/python.name,root)
        (root/'bin/python3').symlink_to('/usr/bin/'+python.name)
        stdlib = Path(sysconfig.get_paths()['stdlib'])
        # This interpreter and stdlib must belong to the same running Python.
        if python != Path(sys.executable).resolve():
            raise ValueError('--python must be this interpreter; do not mix stdlib ABIs')
        destination = root/str(stdlib).lstrip('/')
        shutil.copytree(stdlib,destination,ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests'))
        for extension in (stdlib/'lib-dynload').glob('*.so'):
            copy_elf(extension,destination/'lib-dynload'/extension.name,root)
        share = root/'usr/share/sparklink/tools';share.mkdir(parents=True)
        for name in ['ws73_lab_resources.py', 'build_resources.py', 'ws73_native_return.py', 'ws73_native_controller_return.py', 'ws73_controller_directory.py', 'ws73_firmware_profile.py', 'ws73_firmware.py']:
            shutil.copy2(HERE/name, share/name)
        for name in ['ws73_runtime_address.py','ws73_role_snapshot.py','ws73_application_discovery.py','ws73_security_install_hold.py','ws73_security_agent.py','ws73_security_cli.py','ws73_north_star.py','ws73_capture.py','ws73_rf_rounds.py','ws73_parallel.py','ws73_parallel_data.py','ws73_credit_observation.py','ws73_discovery_policy_capture.py','ws73_target_guest.py','ws73_target_control.py','ws73_connection_control.py','ws73_connection_objects.py','ws73_link_measurement.py','ws73_link_payload.py','ws73_link_resync.py','ws73_acb_transport_probe.py','ws73_channel_socket.py','ws73_benchmark.py','ws73_socket_benchmark.py','ws73_benchmark_ssap.py','ws73_benchmark_timeline.py','ws73_benchmark_resources.py','ws73_dynamic_channels.py','ws73_session_drain.py','ws73_transport_watch.py','ws73_hcc_memory.py','ws73_channel_fairness.py','ws73_ssap_value.py','ws73_ssap_command.py','ws73_ssap_command_policy.py','ws73_ssap_command_deadline.py','ws73_ssap_discovery.py','ws73_ssap_access.py','ws73_ssap_owned.py','ws73_ssap_description.py','ws73_ssap_read_provider.py','ws73_ssap_sdk_read_provider.py','ws73_ssap_sdk_write_provider.py','ws73_ssap_write_unregister.py','ws73_ssap_write_owner_exit.py','ws73_ssap_write_down.py','ws73_native_event_retry.py','ws73_ssap_write_deadline.py','ws73_ssap_provider_owner_exit.py','ws73_ssap_provider_unregister.py','ws73_ssap_provider_deadline.py','ws73_ssap_owned_update.py','ws73_ssap_update_delivery.py','ws73_ssap_subscription.py','ws73_ssap_shared.py','ws73_ssap_receive_lifecycle.py','ws73_ssap_sender_deadline.py','ws73_ssap_owner_lifecycle.py','ws73_ssap_requester_lifecycle.py','ws73_ssap_initialization.py','ws73_ssap_service_policy.py','ws73_initialization_lifecycle.py','ws73_observer_policy.py','ws73_daemon_crash.py','ws73_target_recovery.py','ws73_early_fault.py','ws73_bindings_probe.py','ws73_registry_metadata.py','ws73_event_copy_probe.py','ws73_diagnostic_probe.py','ws73_diagnostic_cancel.py','ws73_diagnostic_hold.py','ws73_diagnostic_deadline.py','ws73_diagnostic_autonomous.py','ws73_active_deadline.py','ws73_management_setup.py','ws73_management_queued.py','ws73_management_queue_ready_peer.py','ws73_connection_queued.py','ws73_management_partial.py','ws73_resource_file_gate.py','ws73_connected_file_gate.py','ws73_session_idle.py','ws73_session_service.py','ws73_trace_layout.py','ws73_channel_grant.py','ws73_channel_sibling.py','ws73_native_pair.py','ws73_revoke_prefix.py','ws73_channel_prefix_hold.py','ws73_channel_link_down.py','ws73_channel_deadline.py','ws73_security_capabilities.py','ws73_security_numeric.py','ws73_security_cancel.py','ws73_key_agreement.py','ws73_protected_grant.py','ws73_channel_daemon_crash.py','ws73_ssap_daemon_restart.py','ws73_daemon_channel_fd.py','ws73_management_ready_peer.py','ws73_host_later_hold.py','ws73_management_eviction.py','ws73_daemon_hold.py','ws73_daemon_removal.py','ws73_model_hold.py','ws73_vm_register_reset.py','ws73_rom_chip.py']:
            shutil.copy2(HERE/name,share/name)
        shutil.copy2(LINUX/'tools/testing/selftests/sparklink/daemon_radio_guest.sh',root/'bin/test-radio')
        shutil.copy2(HERE/'ws73_register_reset_init.sh',root/'bin/rebootstrap-init');(root/'bin/rebootstrap-init').chmod(0o755)
        shutil.copy2(HERE/'ws73_target_init.sh',root/'init');(root/'init').chmod(0o755)
        shutil.copy2(args.kernel_build/'arch/x86/boot/bzImage',root/'boot/bzImage')
        shutil.copy2(root/'boot/bzImage',output/'bzImage')
        shutil.copy2(args.kernel_build/'.config',output/'kernel.config')
        firmware = root/'lib/firmware/sparklink/ws73';firmware.mkdir(parents=True)
        for name,data in images.items(): (firmware/name).write_bytes(data)
        for name,p in board.items(): shutil.copy2(p,firmware/name)
        (root/'etc/passwd').write_text('root:x:0:0:root:/:/bin/sh\nws73:x:1000:1002:application:/tmp:/bin/sh\nobserver:x:1001:1001:observer:/tmp:/bin/sh\ncapture:x:1003:1003:capture:/:/bin/sh\nchannel:x:1004:1004:channel-only:/tmp:/bin/sh\nservice:x:1005:1005:service-only:/tmp:/bin/sh\n')
        (root/'etc/group').write_text('root:x:0:\nsparklink:x:1000:ws73\nobserver:x:1001:observer\nws73:x:1002:ws73\ncapture:x:1003:\nsparklink-apps:x:1004:channel\nsparklink-services:x:1005:\n')
        (root/'etc/shadow').write_text('root:!:0:0:99999:7:::\nws73:!:0:0:99999:7:::\nobserver:!:0:0:99999:7:::\ncapture:!:0:0:99999:7:::\n')
        (root/'etc/shadow').chmod(0o600)
        shutil.copy2(USERSPACE/'data/dbus/sparklink.conf',root/'etc/sparklink.conf')
        (root/'etc/dbus.conf').write_text('''<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>system</type><listen>unix:path=/run/slkbus</listen><auth>EXTERNAL</auth>
<policy context="default"><allow user="*"/><allow own="*"/><allow send_destination="*"/><allow receive_sender="*"/></policy>
<include>/etc/sparklink.conf</include></busconfig>''')
        if module_profile:
            native_vm.stage(args, manifest, root, USERSPACE, copy_elf)
        else:
            manifest['firmware_profiles'] = firmware_profile.provision(root, args.board_model)
            manifest['firmware_input_contract_version'] = 1
            if getattr(args, 'acb_probe_module', None) is not None:
                from ws73_acb_transport_probe import stage_module
                stage_module(args.acb_probe_module, root, manifest)
        if getattr(args, 'native_event_retry_test', None) is not None:
            from ws73_native_event_retry import stage
            if not module_profile:raise ValueError('Native retry test requires native VM')
            stage(args.native_event_retry_test, root, manifest, copy_elf)
        if getattr(args,'native_channel_fd_probe',None) is not None:
            probe=args.native_channel_fd_probe.resolve(strict=True)
            before=file_record(probe);copy_elf(probe,root/'bin/ws73-channel-fd-probe',root)
            (root/'bin/ws73-channel-fd-probe').chmod(0o755)
            if file_record(probe)!=before:raise ValueError('fd client changed during staging')
            manifest['native_channel_fd_probe']=before

        if getattr(args,'controller_directory_clients',False):
            source=HERE/native_vm.STAGED_PYTHON_CLIENTS['ws73_controller_directory_client.py'];target=root/'usr/share/sparklink/tools/ws73_controller_directory_client.py'
            shutil.copy2(source,target)
            from ws73_controller_directory import stage_clients
            manifest['controller_directory_clients']=stage_clients(root,python.name,manifest['controller_directory_client_compile'])
        manifest['guest_files'] = [file_record(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()]
        archive = output/'initramfs.cpio.gz'
        if module_profile:
            native_vm.pack(args, manifest, root)
        else:
            with (output/'pack.log').open('wb') as log,archive.open('wb') as packed:
                files = subprocess.Popen(['find','.','-print0'],cwd=root,stdout=subprocess.PIPE)
                cpio = subprocess.Popen(['cpio','--null','-o','--format=newc','--owner=0:0'],cwd=root,
                                        stdin=files.stdout,stdout=subprocess.PIPE,stderr=log);files.stdout.close()
                gzip = subprocess.Popen(['gzip','-n'],stdin=cpio.stdout,stdout=packed,stderr=log);cpio.stdout.close()
                if any([files.wait(),cpio.wait(),gzip.wait()]): raise ValueError('packing failed')
        if any(file_record(r['path']) != r for r in manifest['inputs']+manifest['userspace_sources']):raise ValueError('inputs/sources changed during preparation')
        artifact_names = ['bzImage','kernel.config','initramfs.cpio.gz'] + (['root.btrfs'] if module_profile else [])
        manifest['artifacts'] = [file_record(output/name) for name in artifact_names]
        manifest['qemu'] = file_record(args.qemu)
        manifest['status'] = 'PREPARED'
    except Exception as error:
        manifest['status']='FAIL';manifest['error']=str(error)
    finally:
        manifest['finished_at']=datetime.now(timezone.utc).isoformat();write_json(output/'manifest.json',manifest)
    print(manifest['status'],output/'manifest.json')
    return 0 if manifest['status']=='PREPARED' else 1


def prepared(path):
    m=json.loads((path/'manifest.json').read_text())
    if m.get('status')!='PREPARED' or m.get('physical_acceptance') is not False:raise ValueError('prepared environment manifest required')
    artifacts=m['artifacts']
    expected = {'bzImage','kernel.config','initramfs.cpio.gz'} | ({'root.btrfs'} if 'native_vm' in m else set())
    if len(artifacts)!=len(expected) or {Path(r['path']).name for r in artifacts}!=expected:raise ValueError('exact kernel/config/initramfs/root artifact set required')
    for record in artifacts:
        if Path(record['path']).resolve()!=(path/Path(record['path']).name).resolve():raise ValueError('prepared artifact path differs from actual QEMU input')
    for record in artifacts+[m['qemu']]:
        if file_record(record['path']) != record:raise ValueError('prepared artifact changed: '+record['path'])
    if 'native_vm' in m:
        for record in m['native_vm']['qemu_data']:
            Path(record['path']).resolve().relative_to((path/'qemu-data').resolve())
            if file_record(record['path']) != record:raise ValueError('prepared QEMU data changed: '+record['path'])
    config_required(path/'kernel.config', 'native_vm' in m)
    return m


def usb_properties(port,index):
    if not re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*(?:\.[1-9][0-9]*)*',port):raise ValueError('explicit physical USB port required')
    bus,path=port.split('-',1)
    return {'driver':'usb-host','id':f'ws73_{index}','bus':'xhci.0','port':str(index+1),
            'hostbus':int(bus),'hostport':path,'vendorid':0xffff,'productid':0x3733,
            'guest-reset':False,'guest-resets-all':False,
            'kernel-driver-detach':False,'host-reset':False}


def usb_host_boundary(qemu):
    """Introspect properties without creating or opening any host USB device."""
    return lab_module().usb_host_boundary(qemu)


def opened_usb_node(pid,node,proc=Path('/proc')):
    """Read only this owned child's live fds; a lock/PID file is insufficient."""
    try:
        for link in (proc/str(pid)/'fd').iterdir():
            try:
                if os.readlink(link)==node:return True
            except FileNotFoundError:pass
    except FileNotFoundError:pass
    return False


def live_runtime_owner(port, pid, inventory):
    """Bind a test pulse to this child's current port after firmware re-enumeration."""
    matches = [row for row in inventory if row.get('path') == port]
    if len(matches) != 1:
        raise ValueError('one current selected host port required')
    row = matches[0]
    bus = usb_properties(port, 0)['hostbus']
    if (type(row.get('bus')) is not int or row['bus'] != bus
            or type(row.get('address')) is not int or not 1 <= row['address'] <= 127
            or row.get('node') != f"/dev/bus/usb/{bus:03}/{row['address']:03}"
            or row.get('writable') is not True
            or row.get('interfaces') not in [[dict(name=port+':1.0', endpoints=5, driver=driver)] for driver in [None, 'usbfs']]
            or not opened_usb_node(pid, row['node'])):
        raise ValueError('current runtime interface and live child USB fd required')
    return json.loads(json.dumps(row))


def verify_recovery_lifecycle(trace, armed_wall_ns, initial_devices):
    """Only proven initial ROM owners may close before the fault pulse."""
    from decimal import Decimal
    if type(armed_wall_ns) is not int or armed_wall_ns <= 0:
        raise ValueError('exact recovery arm time required')
    boot = {(r['bus'], r['address']) for r in initial_devices
            if r['interfaces'] and all(i['endpoints'] == 2 for i in r['interfaces'])}
    seen = set()
    for line in trace.splitlines():
        if not re.search(r'usb_host_(close|reset|open_failure) dev ', line):
            continue
        match = re.fullmatch(r'\d+@(\d+\.\d+):usb_host_(close|reset|open_failure) dev (\d+):(\d+)(?:,.*)?', line)
        if not match:
            raise ValueError('timestamped USB owner lifecycle action required')
        stamp, action, bus, address = match.groups()
        identity = (int(bus), int(address))
        if (action != 'close' or int(Decimal(stamp)*1_000_000_000) >= armed_wall_ns
                or identity not in boot or identity in seen):
            raise ValueError('protocol recovery unexpectedly closed/reset a USB owner')
        seen.add(identity)
    return sorted(seen)


USB_LIFECYCLE_EVENTS = (
    'usb_port_attach', 'usb_port_detach',
    'usb_host_open_started', 'usb_host_open_success', 'usb_host_open_failure',
    'usb_host_close', 'usb_host_claim_interface', 'usb_host_release_interface',
    'usb_host_req_complete', 'usb_host_req_data', 'usb_host_req_canceled',
    'usb_host_req_control', 'usb_host_req_emulated', 'usb_host_reset',
    'usb_xhci_slot_address', 'usb_xhci_slot_disable',
    'usb_xhci_ep_stop', 'usb_xhci_ep_reset', 'usb_xhci_ep_state',
    'usb_xhci_ep_set_dequeue', 'usb_xhci_ep_disable',
)


def lifecycle_trace(qemu, output):
    """Metadata-only tracing; no control/data payload or host mutation."""
    available = subprocess.check_output([str(qemu), '-trace', 'help'],
                                        stderr=subprocess.STDOUT, text=True).splitlines()
    missing = set(USB_LIFECYCLE_EVENTS) - set(available)
    if missing:
        raise ValueError('QEMU lifecycle trace events missing: ' + ','.join(sorted(missing)))
    events, log = output/'usb-lifecycle.events', output/'usb-lifecycle.log'
    if any(c in str(events) + str(log) for c in [',', '\n']):
        raise ValueError('QEMU trace paths must not contain option delimiters')
    events.write_text('\n'.join(USB_LIFECYCLE_EVENTS)+'\n')
    return ['-msg', 'timestamp=on', '-trace', f'events={events},file={log}']


class HostTimeline:
    """Persist initial/change/final WS73 inventory with observation timestamps.

    Absence is an observation, not a recovery claim. Include unselected WS73s
    to distinguish an owner-local incident from a hub-wide inventory change.
    """
    def __init__(self, path):
        self.path, self.previous, self.sequence = path, None, 0

    def observe(self, inventory, phase='poll'):
        if inventory == self.previous and phase == 'poll':
            return
        record = dict(sequence=self.sequence, phase=phase, wall_ns=time.time_ns(),
                      monotonic_ns=time.monotonic_ns(), devices=inventory)
        with self.path.open('a') as stream:
            stream.write(json.dumps(record, sort_keys=True)+'\n')
            stream.flush()
        self.previous = inventory
        self.sequence += 1


class SerialTimeoutSeal:
    """Cancel ordinary work, then exit only a newly observed ordinary shell.

    Never send Enter to a physical unplug/reinsert prompt. An interrupt may
    leave cleanup running, so a pre-existing prompt cannot authorize exit.
    """
    def __init__(self, transcript):
        text = transcript.decode(errors='replace')
        if 'WS73_TARGET_ENVIRONMENT_READY: physical_acceptance=0' not in text:
            raise ValueError('environment timeout before ordinary shell readiness; preserve partial capture')
        self.offset = len(transcript)
        self.phase = 'CLOSING' if 'WS73_TARGET_SHELL_CLOSED' in text or 'WS73_TARGET_FINISHED' in text else 'WAITING_ORDINARY_SHELL'
        self.initial_input = b'' if self.phase == 'CLOSING' else b'\x03'

    def feed(self, transcript):
        suffix = transcript[self.offset:].decode(errors='replace').replace('\r', '')
        if 'WS73_TARGET_SHELL_CLOSED' in suffix or 'WS73_TARGET_FINISHED' in suffix:
            self.phase = 'CLOSING'
        if self.phase == 'WAITING_ORDINARY_SHELL' and re.search(r'(?:^|\n)/ \$ (?:\x1b\[6n)?$', suffix):
            self.phase = 'EXIT_SENT'
            # The cancelled application's status remains in run.json. Return
            # success only from the shell to let the supervisor seal capture;
            # the host still records the original environment timeout as FAIL.
            return b'exit 0\n'
        return b''


def validate_channel_death_mode(args, package):
    incompatible=any(isinstance(v,bool) and v and k!='channel_daemon_crash' for k,v in vars(args).items())
    selectors=any(getattr(args,k,None) for k in ['daemon_hold_case','managed_partial_case','managed_connected_case','managed_connected_reply','managed_real_later_step'])
    if args.command!='run' or 'native_vm' not in package or 'native_channel_fd_probe' not in package or incompatible or selectors or getattr(args,'channel_daemon_index',0) not in [0,1]:
        raise ValueError('dedicated actual daemon-channel death native VM required')


def validate_down_failure_inputs(package):
    # A new Host flag must not silently run an older guest without its hook.
    for name in ['ws73_connection_control.py', 'ws73_target_control.py', 'ws73_target_init.sh']:
        expected = file_record(HERE/name)
        rows = [r for r in package.get('inputs', []) if Path(r['path']).name == name]
        if len(rows) != 1 or rows[0]['sha256'] != expected['sha256']:
            raise ValueError('passive Down capture requires freshly matched guest input: '+name)


def _run(args):
    ordinary_identity()
    sibling_business=getattr(args,'managed_channel_sibling_business',False)
    if type(sibling_business)is not bool:raise ValueError('boolean Native sibling request required')
    if sibling_business:
        from ws73_channel_sibling import requested as sibling_requested
        sibling_requested(args)
    output=args.output.resolve()
    support=args.command=='support'
    passthrough=bool(getattr(args,'qmp_hotplug',False))
    recovery=bool(getattr(args,'fault_recovery',False))
    disconnect_isolation=bool(getattr(args,'four_device_disconnect',False))
    parallel_burst=bool(getattr(args,'four_device_burst',False))
    parallel_owned=bool(getattr(args,'four_device_owned',False))
    parallel_delivery=bool(getattr(args,'four_device_update_delivery',False))
    parallel_subscription=bool(getattr(args,'four_device_shared_subscription',False))
    parallel_benchmark=bool(getattr(args,'four_device_dynamic_benchmark',False))
    parallel_benchmark_case=getattr(args,'four_device_benchmark_case','parallel')
    if type(parallel_benchmark_case)is not str or parallel_benchmark_case not in ('parallel','close-short','pressure')or parallel_benchmark_case!='parallel'and not parallel_benchmark:
        raise ValueError('explicit benchmark case requires dedicated four-device benchmark')
    business=parallel_benchmark or parallel_subscription or parallel_delivery or parallel_owned or parallel_burst or disconnect_isolation or bool(getattr(args,'four_device_business',False))
    if business:
        validate_business_mode(args)
    parallel=business or bool(getattr(args,'parallel_pairs',False))
    from ws73_runtime_address import requested as address_requested
    runtime_addresses=address_requested(args)
    early_fault=bool(getattr(args,'early_bootstrap_fault',False))
    if early_fault and (support or passthrough or recovery or parallel or any(getattr(args,n,False) for n in ['connection_verify','channel_socket_verify','diagnostic_verify','managed_partial_case','managed_connected_case','channel_daemon_crash'])):
        raise ValueError('early bootstrap fault requires separate native three-device VM')
    initializer_lifecycle=bool(getattr(args,'initializer_lifecycle',False))
    observer_policy=bool(getattr(args,'observer_policy',False))
    from ws73_native_event_retry import requested as retry_requested
    native_retry=retry_requested(args)
    channel_death=bool(getattr(args,'channel_daemon_crash',False))
    channel_death_index=getattr(args,'channel_daemon_index',0)
    daemon_crash=bool(getattr(args,'daemon_crash',False))
    connection_verify=bool(getattr(args,'connection_verify',False))
    acb_probe=bool(getattr(args,'acb_transport_probe',False))
    agent_mode=getattr(args,'security_agent',None)
    fairness=bool(getattr(args,'channel_fairness_verify',False))
    dynamic_channels=bool(getattr(args,'dynamic_channel_verify',False))
    dynamic_long=getattr(args,'dynamic_channel_long_bytes',None)
    dynamic_burst=bool(getattr(args,'dynamic_channel_burst',False))
    if dynamic_burst and (not dynamic_channels or dynamic_long!=2042):raise ValueError('dynamic burst requires explicit dynamic2042 workload')
    if dynamic_long is not None and (not dynamic_channels or type(dynamic_long) is not int or dynamic_long not in [249,250,253,254,255,1024,2042]):raise ValueError('dynamic long requires explicit dynamic gate and bounded supported size')
    benchmark_mode=getattr(args,'channel_benchmark',None)
    benchmark_window=getattr(args,'channel_benchmark_window',4)
    benchmark_xhci=getattr(args,'channel_benchmark_xhci','on')
    from ws73_socket_benchmark import requested_configuration,requested_channel,is_parallel,channel_boot,pressures_long
    benchmark_config=requested_configuration(args)
    benchmark_channel=requested_channel(args)
    import ws73_benchmark_ssap as benchmark_ssap
    benchmark_service=benchmark_ssap.requested(args)
    if pressures_long(benchmark_channel)and(benchmark_service is not None or benchmark_xhci!='on'):
        raise ValueError('pressure workload requires separate enabled-trace benchmark without concurrent SSAP')
    benchmark_verifier_names=['ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_benchmark_resources.py','ws73_application_role.py','ws73_role_snapshot.py']+(['ws73_dynamic_channels.py']if benchmark_channel is not None else[])+(['ws73_channel_fairness.py']if is_parallel(benchmark_channel)else[])
    if benchmark_service is not None:benchmark_verifier_names+=benchmark_ssap.verifiers(benchmark_service)
    if benchmark_xhci not in ('on','off') or (not benchmark_mode and benchmark_xhci!='on'):raise ValueError('explicit benchmark required for xHCI comparison')
    if benchmark_mode and (benchmark_mode not in ['rate','window','duplex'] or not passthrough or not connection_verify or support or parallel or acb_probe or agent_mode or dynamic_channels or getattr(args,'daemon_link_resync',False) or getattr(args,'channel_socket_verify',False)):
        raise ValueError('benchmark requires separate two-device real connection VM without other application gates')
    channel_socket=bool(getattr(args,'channel_socket_verify',False))
    link_measurements=bool(getattr(args,'link_measurements',False))
    link_payload=getattr(args,'link_payload_preference',None)
    if link_payload is not None and (link_payload!='reported-acb-maximum' or support or parallel or not passthrough or not connection_verify or not getattr(args,'qmp_hotplug',False) or not (channel_socket or benchmark_mode) or agent_mode or dynamic_channels or getattr(args,'fault_recovery',False)):
        raise ValueError('link payload preference requires separate explicit paired native workload gate')
    if link_measurements and (support or parallel or not passthrough or not connection_verify or not getattr(args,'qmp_hotplug',False) or not (channel_socket or benchmark_mode) or agent_mode or dynamic_channels or getattr(args,'fault_recovery',False)):
        raise ValueError('link observations require a dedicated real two-controller connection/application gate')
    from ws73_application_discovery import requested as discovery_requested
    application_discovery=discovery_requested(args)
    application_clients=bool(getattr(args,'application_client_verify',False))
    if application_clients and (not passthrough or not connection_verify or any([channel_socket,benchmark_mode,acb_probe,agent_mode,dynamic_channels,fairness,getattr(args,'daemon_link_resync',False)])):
        raise ValueError('application clients require a dedicated native real connection VM')
    if application_clients and (any(value for key,value in vars(args).items() if type(value) is bool and key not in ['qmp_hotplug','connection_verify','application_client_verify']) or any(getattr(args,key,None) for key in ['managed_partial_case','managed_connected_case','managed_connected_reply','managed_real_later_step','daemon_hold_case'])):
        raise ValueError('application client gate cannot combine fault/lifecycle selectors')
    service_policy=bool(getattr(args,'ssap_service_policy',False))
    if service_policy and (not channel_socket or not passthrough or agent_mode or dynamic_channels or fairness):raise ValueError('service-role gate requires separate ordinary native two-device socket baseline')
    channel_bytes=getattr(args,'channel_socket_bytes',61)
    channel_boundaries=bool(getattr(args,'channel_socket_boundaries',False))
    channel_close=bool(getattr(args,'channel_socket_close_prefix',False))
    channel_burst=bool(getattr(args,'channel_socket_burst',False))
    ssap_owned=bool(getattr(args,'ssap_owned_verify',False))
    from ws73_ssap_description import requested as description_requested
    description=description_requested(args,passthrough=passthrough)
    from ws73_ssap_read_provider import requested as provider_requested
    read_provider=provider_requested(args,passthrough=passthrough)
    from ws73_ssap_sdk_read_provider import requested as sdk_provider_requested
    sdk_read_provider=sdk_provider_requested(args,passthrough=passthrough)
    from ws73_ssap_sdk_write_provider import requested as sdk_write_provider_requested
    sdk_write_provider=sdk_write_provider_requested(args,passthrough=passthrough)
    from ws73_ssap_write_unregister import requested as write_unregister_requested
    write_unregister=write_unregister_requested(args,passthrough=passthrough)
    from ws73_ssap_write_owner_exit import requested as write_owner_exit_requested
    write_owner_exit=write_owner_exit_requested(args,passthrough=passthrough)
    from ws73_ssap_write_down import requested as write_down_requested
    write_down=write_down_requested(args,passthrough=passthrough)
    from ws73_ssap_write_deadline import requested as write_deadline_requested
    write_deadline=write_deadline_requested(args,passthrough=passthrough)
    from ws73_ssap_provider_owner_exit import requested as provider_exit_requested
    provider_exit=provider_exit_requested(args,passthrough=passthrough)
    from ws73_ssap_provider_unregister import requested as provider_unregister_requested
    provider_unregister=provider_unregister_requested(args,passthrough=passthrough)
    from ws73_ssap_provider_deadline import requested as provider_deadline_requested
    provider_deadline=provider_deadline_requested(args,passthrough=passthrough)
    from ws73_ssap_command import requested as command_requested
    write_command=command_requested(args,passthrough=passthrough)
    from ws73_ssap_command_policy import requested as command_policy_requested
    command_policy=command_policy_requested(args,passthrough=passthrough)
    from ws73_ssap_command_deadline import requested as command_deadline_requested
    command_deadline=command_deadline_requested(args,passthrough=passthrough)
    owned_update=bool(getattr(args,'ssap_owned_update_verify',False))
    from ws73_ssap_update_delivery import requested as delivery_requested
    update_delivery=delivery_requested(args,passthrough=passthrough)
    from ws73_ssap_subscription import requested as subscription_requested
    subscription=subscription_requested(args,passthrough=passthrough)
    subscription_shared=getattr(args,'ssap_subscription_shared_verify',False)
    from ws73_ssap_subscription import requested_shared_case
    subscription_shared_case=requested_shared_case(args,four_pair=parallel_subscription)
    subscription_renewal=getattr(args,'ssap_subscription_renewal_verify',False)
    subscription_pressure=getattr(args,'ssap_subscription_pressure_verify',False)
    subscription_owner_loss=getattr(args,'ssap_subscription_owner_loss_verify',False)
    subscription_inflight=getattr(args,'ssap_subscription_inflight_release_verify',False)
    from ws73_ssap_subscription import requested_inflight_case
    subscription_inflight_case=requested_inflight_case(args)
    from ws73_ssap_receive_lifecycle import requested as receive_lifecycle_requested
    receive_lifecycle=receive_lifecycle_requested(args,passthrough=passthrough)
    from ws73_ssap_sender_deadline import requested as sender_deadline_requested
    sender_deadline=sender_deadline_requested(args,passthrough=passthrough)
    from ws73_ssap_value import lengths_requested
    value_lengths=lengths_requested(args,passthrough=passthrough)
    owner_lifecycle=bool(getattr(args,'ssap_owner_lifecycle_verify',False))
    owner_publisher=getattr(args,'ssap_owner_publisher','cli')
    if owner_publisher not in ('cli','sdk') or (owner_publisher!='cli' and not owner_lifecycle):raise ValueError('SDK owner publisher requires explicit lifecycle gate')
    requester_lifecycle=bool(getattr(args,'ssap_requester_lifecycle_verify',False))
    from ws73_ssap_initialization import requested as initialization_requested
    ssap_initialization=initialization_requested(args,passthrough=passthrough)
    initialization_stage=getattr(args,'ssap_initialization_stage','cmtc')
    from ws73_native_return import requested as native_return_requested
    native_return = native_return_requested(args,passthrough=passthrough)
    from ws73_native_controller_return import requested as native_controller_requested
    native_controller = native_controller_requested(args,passthrough=passthrough)
    from ws73_controller_directory import requested as directory_requested
    directory_events=directory_requested(args,passthrough=passthrough)
    if requester_lifecycle and (not channel_socket or not passthrough or owner_lifecycle or ssap_owned or agent_mode or channel_close or channel_burst or channel_boundaries or dynamic_channels or fairness or parallel):raise ValueError('requester lifecycle requires separate ordinary basic socket baseline')
    if owned_update and (not channel_socket or not passthrough or owner_lifecycle or ssap_owned or requester_lifecycle or agent_mode or channel_close or channel_burst or channel_boundaries or dynamic_channels or fairness or parallel):raise ValueError('owned update requires dedicated ordinary socket gate')
    if owner_lifecycle and (not channel_socket or not passthrough or agent_mode or channel_close or channel_burst or channel_boundaries or dynamic_channels or fairness):raise ValueError('owner lifecycle requires separate ordinary basic socket baseline')
    if ssap_owned and (not channel_socket or channel_close or channel_burst or channel_boundaries or dynamic_channels or fairness):raise ValueError('owned SSAP requires separate ordinary socket baseline')
    if type(channel_bytes) is not int or not 29<=channel_bytes<=2042 or ((channel_bytes!=61 or channel_boundaries) and not channel_socket):raise ValueError('message size and boundaries require explicit supported socket gate')
    channel_rounds=getattr(args,'channel_socket_rounds',4)
    from ws73_connection_control import requested_down_failure_observation
    down_failure_observe=requested_down_failure_observation(args,passthrough=passthrough)
    if type(channel_rounds) is not int or not 1<=channel_rounds<=20 or (channel_rounds!=4 and not channel_socket):raise ValueError('bounded socket rounds require explicit socket gate')
    if channel_close and (not channel_socket or channel_bytes!=2042 or channel_rounds!=1 or channel_boundaries):raise ValueError('prefix-close requires explicit one-round 2042-byte socket gate')
    if channel_burst and (not channel_socket or channel_bytes!=2042 or channel_rounds!=16 or channel_close or channel_boundaries):raise ValueError('burst requires explicit16-round2042-byte socket gate')
    link_resync=bool(getattr(args,'daemon_link_resync',False))
    if fairness and (not channel_socket or dynamic_channels or agent_mode or channel_close or channel_burst or channel_boundaries or parallel or bool(getattr(args,'session_service_observe',False))):raise ValueError('concurrent channel gate requires separate ordinary baseline without trace or other special modes')
    if dynamic_channels and (not channel_socket or agent_mode or channel_close or channel_burst or channel_boundaries or parallel):raise ValueError('dynamic gate requires separate ordinary fixed-channel baseline without other special modes')
    if channel_socket and (not connection_verify or acb_probe or link_resync):raise ValueError('ordinary channel socket requires a separate real connection gate without test module')
    if acb_probe and (not connection_verify or link_resync):raise ValueError('ACB selftest requires separate explicit connection gate')
    if link_resync and not connection_verify:raise ValueError('link resync requires explicit ordinary native connection gate')
    if agent_mode is not None:
        from ws73_security_agent import MODES
        if agent_mode not in MODES or not channel_socket or not connection_verify or not passthrough or any(getattr(args,k,False) for k in ['channel_socket_close_prefix','managed_security_capabilities','managed_channel_grant']):
            raise ValueError('Agent gate requires separate ordinary native two-device connection/socket run with staged real Agent witness')
    connection_advertising=getattr(args,'connection_advertising','fixed-t')
    if connection_advertising!='fixed-t' and not connection_verify:
        raise ValueError('connection advertising contrast requires connection verification')
    if connection_verify and (args.command!='run' or not passthrough or recovery or parallel
            or any(getattr(args,k,False) for k in ['daemon_crash','observer_policy','initializer_lifecycle','hotplug','warm','empty_bulk','event_copy_verify','diagnostic_verify','diagnostic_cancel_verify','diagnostic_deadline_verify','diagnostic_autonomous_verify','active_deadline_verify','active_close_verify','setup_release_verify','daemon_hold_case','daemon_cancel_remove','managed_partial_case','managed_queue_verify','managed_ordinary_eviction','managed_ready_peer','managed_real_later_step'])):
        raise ValueError('connection verification requires separate real QMP-hotplug VM')
    if daemon_crash and (args.command != 'run' or not passthrough or recovery or parallel
            or any(getattr(args,k,False) for k in ['observer_policy','initializer_lifecycle','hotplug','warm','empty_bulk','event_copy_verify','diagnostic_verify','diagnostic_cancel_verify','diagnostic_deadline_verify','diagnostic_autonomous_verify','active_deadline_verify','active_close_verify','setup_release_verify','daemon_hold_case','daemon_cancel_remove','managed_partial_case','managed_queue_verify','managed_ordinary_eviction','managed_ready_peer','managed_real_later_step'])):
        raise ValueError('daemon crash requires separate real QMP-hotplug native VM')
    if observer_policy and (args.command != 'run' or not passthrough or recovery or parallel
            or any(getattr(args,k,False) for k in ['daemon_crash','initializer_lifecycle','hotplug','warm','empty_bulk','event_copy_verify','diagnostic_verify','diagnostic_cancel_verify','diagnostic_deadline_verify','diagnostic_autonomous_verify','active_deadline_verify','active_close_verify','setup_release_verify','daemon_hold_case','daemon_cancel_remove','managed_partial_case','managed_queue_verify','managed_ordinary_eviction','managed_ready_peer','managed_real_later_step'])):
        raise ValueError('observer policy requires separate real QMP-hotplug native VM')

    if initializer_lifecycle and (args.command != 'run' or not passthrough or recovery or parallel
            or any(getattr(args,k,False) for k in ['daemon_crash','observer_policy','hotplug','warm','empty_bulk','event_copy_verify','diagnostic_verify','diagnostic_cancel_verify','diagnostic_deadline_verify','diagnostic_autonomous_verify','active_deadline_verify','active_close_verify','setup_release_verify','daemon_hold_case','daemon_cancel_remove','managed_partial_case','managed_queue_verify','managed_ordinary_eviction','managed_ready_peer','managed_real_later_step'])):
        raise ValueError('initializer lifecycle requires separate real QMP-hotplug native VM')
    if parallel and (support or passthrough or recovery or any(getattr(args,k,False) for k in ['hotplug','warm','empty_bulk','event_copy_verify','diagnostic_verify','active_deadline_verify','active_close_verify','setup_release_verify','daemon_hold_case','daemon_cancel_remove','managed_partial_case','managed_queue_verify'])):
        raise ValueError('four-device parallel RF requires separate real VM without other gates')
    selected_count=3 if early_fault else 4 if parallel or sibling_business else 2
    parallel_offset=getattr(args,'parallel_start_offset_ms',0)
    if type(parallel_offset) is not int or not 0 <= parallel_offset <= 125 or (parallel_offset and not parallel):
        raise ValueError('bounded parallel start offset requires explicit four-device diagnostic gate')
    event_copy=bool(getattr(args,'event_copy_verify',False))
    diagnostic=bool(getattr(args,'diagnostic_verify',False))
    cancellation=bool(getattr(args,'diagnostic_cancel_verify',False))
    deadline_gate=bool(getattr(args,'diagnostic_deadline_verify',False))
    autonomous_gate=bool(getattr(args,'diagnostic_autonomous_verify',False))
    active_close_gate=bool(getattr(args,'active_close_verify',False))
    active_gate=bool(getattr(args,'active_deadline_verify',False)) or active_close_gate
    if active_close_gate and bool(getattr(args,'active_deadline_verify',False)):
        raise ValueError('select one active deadline or last-file-close gate')
    setup_gate=bool(getattr(args,'setup_release_verify',False))
    daemon_remove=bool(getattr(args,'daemon_cancel_remove',False))
    if daemon_remove and (support or not passthrough or recovery or diagnostic or active_gate or setup_gate or getattr(args,'daemon_hold_case',None) is not None or getattr(args,'managed_partial_case',None) is not None or getattr(args,'managed_queue_verify',False)):
        raise ValueError('held daemon cancel/removal requires separate real QMP-hotplug VM')
    daemon_hold=getattr(args,'daemon_hold_case',None)
    if daemon_hold not in [None,'supersede','caller-exit','cancel-caller-exit','cancel-busy','cancel-admission'] or daemon_hold is not None and (not recovery or support or diagnostic or active_gate or getattr(args,'managed_partial_case',None) is not None or getattr(args,'managed_queue_verify',False)):
        raise ValueError('separate real recovery VM for ordinary daemon held cancellation required')
    connected_case=getattr(args,'managed_connected_case',None)
    connected_index=getattr(args,'managed_connected_index',0)
    connected_reply=getattr(args,'managed_connected_reply',None)
    link_snapshot=bool(getattr(args,'managed_link_snapshot',False))
    peer_binding=bool(getattr(args,'managed_peer_binding',False))
    channel_grant=bool(getattr(args,'managed_channel_grant',False))
    channel_scm_rights=bool(getattr(args,'managed_channel_scm_rights',False))
    channel_revoke_prefix=bool(getattr(args,'managed_channel_revoke_prefix',False))
    channel_link_down=bool(getattr(args,'managed_channel_link_down',False))
    channel_deadline=bool(getattr(args,'managed_channel_deadline',False))
    session_idle=bool(getattr(args,'managed_channel_idle_observe',False))
    if session_idle and (not channel_revoke_prefix or channel_deadline or channel_link_down or connected_case!='release' or connected_reply or bool(getattr(args,'managed_channel_directions',False)) or channel_scm_rights):raise ValueError('separate release/prefix normal2s real Session idle observation required')
    session_service=bool(getattr(args,'session_service_observe',False))
    service_profile=getattr(args,'session_service_profile',None)
    if benchmark_ssap.observing(benchmark_service)and(not session_service or service_profile!='full-load-v2' or not getattr(args,'qmp_hotplug',False)):
        raise ValueError('bounded credit observation requires the separate full-load-v2 Session trace/QMP benchmark')
    if service_profile is not None and (service_profile!='full-load-v2' or not session_service):
        raise ValueError('explicit Session service profile requires separate service observation')
    queued_discard=bool(getattr(args,'managed_channel_queued_discard',False))
    if queued_discard and (not session_service or not channel_revoke_prefix or not channel_grant
            or connected_case not in ('release','close','dup') or connected_reply or session_idle
            or channel_scm_rights or bool(getattr(args,'managed_channel_directions',False))
            or getattr(args,'managed_channel_security',0) or getattr(args,'managed_security_capabilities',False)):
        raise ValueError('queued discard requires standalone basic Managed prefix/Session trace lifecycle gate')
    if session_service and (args.command!='run' or support or parallel or dynamic_channels or agent_mode or channel_close or session_idle or connected_reply or getattr(args,'managed_security_capabilities',False) or not (channel_socket or channel_grant or benchmark_mode)):
        raise ValueError('Session service trace requires separate real fixed-channel data or Managed Grant gate')
    protected=getattr(args,'managed_channel_security',0)
    if type(protected) is not int or protected not in (0,1,2):raise ValueError('unsupported lifecycle security requirement')
    if protected and (not channel_grant or not connected_case or not channel_revoke_prefix or connected_reply or session_idle or session_service or link_snapshot or peer_binding or channel_scm_rights or getattr(args,'managed_channel_directions',False) or getattr(args,'managed_security_capabilities',False)):
        raise ValueError('protected mechanism requires standalone bidirectional prefix lifecycle gate')
    security_capabilities=bool(getattr(args,'managed_security_capabilities',False))
    security_kind=getattr(args,'managed_security_kind','capabilities')
    numeric=security_kind if security_kind in ('numeric-approve','numeric-reject','numeric-late') else None
    if numeric and not security_capabilities:raise ValueError('numeric mechanism requires standalone explicit security gate')
    original_deadline=security_kind=='original-deadline'
    cancel_pending=security_kind in ['cancel-pending','original-deadline']
    if cancel_pending and not security_capabilities:raise ValueError('passive cancellation requires standalone explicit security gate')
    encryption=security_kind=='unauthenticated-encryption'
    key_agreement=security_kind in ['key-agreement','unauthenticated-encryption']
    if key_agreement and not security_capabilities:raise ValueError('key agreement requires standalone explicit security gate')
    if security_capabilities and (not channel_grant or connected_case!='release' or channel_revoke_prefix or channel_link_down or channel_deadline or channel_scm_rights or link_snapshot or peer_binding or bool(getattr(args,'managed_channel_directions',False))):raise ValueError('limited security capabilities require separate bidirectional ordinary channel gate')
    if channel_deadline and (channel_link_down or connected_case!='release' or not channel_revoke_prefix or channel_scm_rights or link_snapshot or peer_binding):raise ValueError('original deadline requires separate release-mode begun-prefix bidirectional channel gate')
    if channel_link_down and (connected_case!='release' or not channel_revoke_prefix or bool(getattr(args,'managed_channel_scm_rights',False)) or link_snapshot or peer_binding):raise ValueError('direct Down requires separate release-mode begun-prefix bidirectional channel gate')
    if channel_revoke_prefix and (not channel_grant or bool(getattr(args,'managed_channel_directions',False))):raise ValueError('revoke-prefix requires standalone bidirectional Managed channel gate')
    if channel_scm_rights and not channel_grant:raise ValueError('fd transfer requires standalone channel Grant')
    channel_directions=bool(getattr(args,'managed_channel_directions',False))
    if channel_directions and not channel_grant:raise ValueError('directional test requires standalone channel Grant')
    if channel_grant and (not connected_case or connected_reply or recovery):raise ValueError('channel Grant requires standalone real established File gate without fault injection')
    if peer_binding and (not connected_case or connected_reply):raise ValueError('peer binding requires separate established File gate')
    if link_snapshot and (not connected_case or connected_reply):raise ValueError('link snapshot requires separate established File gate')
    if connected_reply and not connected_case:raise ValueError('actual connection reply hold requires explicit File gate')
    if connected_case and (support or (not recovery and not channel_grant) or not setup_gate or passthrough or parallel or diagnostic or active_gate
            or any(getattr(args,k,False) for k in ['managed_partial_case','managed_queue_verify','daemon_hold_case','connection_verify'])):
        raise ValueError('connected File gate requires separate real recovery/Setup VM')
    if connected_index and not connected_case:raise ValueError('connected role requires explicit File gate')
    partial_case=getattr(args,'managed_partial_case',None)
    partial_gate=partial_case is not None
    partial_domain=getattr(args,'managed_partial_domain','advertising')
    selected_cleanup=bool(getattr(args,'managed_selected_cleanup',False))
    parameter_cleanup=bool(getattr(args,'managed_scan_parameter_cleanup',False))
    ready_peer=bool(getattr(args,'managed_ready_peer',False))
    real_step=getattr(args,'managed_real_later_step',None)
    real_later=real_step is not None
    resource_recreation=bool(getattr(args,'managed_resource_recreate',False))
    ordinary_eviction=bool(getattr(args,'managed_ordinary_eviction',False))
    if resource_recreation and (not partial_gate or partial_domain!='advertising' or not selected_cleanup or not ready_peer or parameter_cleanup or ordinary_eviction or real_step not in [None,1]):
        raise ValueError('resource recreation requires separate real selected advertising/Ready peer gate; only remove or configure step')
    if ordinary_eviction and (not partial_gate or not selected_cleanup or not ready_peer or real_later or parameter_cleanup!=(partial_domain=='scanning')):
        raise ValueError('ordinary eviction requires first actual partial step and Ready peer; scanning parameter cleanup')
    if real_later and (type(real_step) is not int or real_step not in [1,2] or not partial_gate or not selected_cleanup or not ready_peer or parameter_cleanup or partial_domain=='advertising' and real_step!=1):
        raise ValueError('bounded later real partial step with selected Ready peer required')
    if ready_peer and (not partial_gate or not selected_cleanup or partial_domain=='scanning' and not parameter_cleanup and not real_later or getattr(args,'managed_queue_verify',False)):
        raise ValueError('Ready peer requires separate selected real partial gate')
    if parameter_cleanup and (not selected_cleanup or partial_domain!='scanning'):raise ValueError('scan parameter cleanup requires selected scanning partial gate')
    if selected_cleanup and not partial_gate:raise ValueError('selected-domain cleanup requires explicit real partial gate')
    if partial_case not in (None,'release','close','dup') or partial_domain not in ('advertising','scanning'):
        raise ValueError('explicit supported Managed partial case/domain required')
    if partial_gate and (support or not recovery or not setup_gate or diagnostic or active_gate):
        raise ValueError('Managed partial gate requires separate real recovery/Setup VM without other hold gates')
    queued_gate=bool(getattr(args,'managed_queue_verify',False))
    queue_peer=bool(getattr(args,'managed_queue_ready_peer',False))
    queue_connections=bool(getattr(args,'managed_queue_connections',False))
    if queue_connections and not queue_peer:raise ValueError('native queued connections require confirmed-Off Ready peer gate')
    if queue_peer and (not queued_gate or not getattr(args,'managed_queue_confirmed_off',False) or partial_gate):raise ValueError('Ready queue peer requires separate confirmed-Off real queue gate')
    if getattr(args,'managed_queue_confirmed_off',False) and not queued_gate:raise ValueError('confirmed-Off requires explicit Managed queued gate')
    if queued_gate and (support or not recovery or not setup_gate):
        raise ValueError('Managed queued gate requires real recovery VM and Setup attachment gate')
    if setup_gate and (support or (not recovery and not channel_grant)):
        raise ValueError('Setup release requires explicit real fault-recovery VM mode')
    if active_gate and (support or not recovery or diagnostic or cancellation or deadline_gate or autonomous_gate):
        raise ValueError('active retirement requires separate real fault-recovery VM mode, without explicit-release diagnostic modes')
    if autonomous_gate and (support or not recovery or not diagnostic or not cancellation or not deadline_gate):
        raise ValueError('live autonomous gate requires real diagnostic/cancel/deadline/fault-recovery modes')
    if deadline_gate and (support or not recovery or not diagnostic or not cancellation):
        raise ValueError('live deadline gate requires real diagnostic/cancel/fault-recovery modes')
    if cancellation and (support or not recovery or not diagnostic):
        raise ValueError('live cancellation gate requires diagnostic and real fault-recovery VM modes')
    if event_copy and (support or not recovery):
        raise ValueError('live event copy gate requires real fault-recovery VM mode')
    if diagnostic and (support or not recovery):
        raise ValueError('live diagnostic gate requires real fault-recovery VM mode')
    firmware_mode = None if support else firmware_evidence.requested_mode(args)
    from ws73_usb_partial_diagnostic import requested as partial_rx_requested
    partial_rx_target=partial_rx_requested(args)
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    m={'version':1,'scope':'synthetic environment support' if support else 'physical development environment',
       'physical_acceptance':False,'status':'STARTING','started_at':datetime.now(timezone.utc).isoformat(),
       'synthetic_empty_bulk':bool(getattr(args,'empty_bulk',False)),
       'synthetic_hotplug':bool(getattr(args,'hotplug',False)),
       'synthetic_warm':bool(getattr(args,'warm',False))}
    m['runner_inputs']=[file_record(HERE/name) for name in ('ws73_target.py','ws73_vm_native_root.py','ws73_native_return.py','ws73_native_controller_return.py')]
    if not support:
        m['firmware_evidence_contract_version'] = 1
        m['firmware_evidence_mode'] = firmware_mode
        m['firmware_evidence_helpers'] = [file_record(HERE/name) for name in FIRMWARE_EVIDENCE_HELPERS]
        m['runner_inputs'] += m['firmware_evidence_helpers']
    if ssap_initialization:m['runner_inputs'] += [file_record(HERE/name) for name in ('ws73_ssap_initialization.py','ws73_diagnostic_hold.py','ws73_channel_prefix_hold.py','ws73_connection_control.py','ws73_connection_objects.py','ws73_daemon_hold.py') ]
    m['native_event_retry_requested']=native_retry
    m['native_event_retry_acceptance']=False
    if native_retry:m['runner_inputs'].append(file_record(HERE/'ws73_native_event_retry.py'))
    m['runtime_addresses_requested']=runtime_addresses
    if runtime_addresses:m['runtime_address_verifier']=file_record(HERE/'ws73_runtime_address.py')
    m['early_bootstrap_fault_requested']=early_fault
    if early_fault:m['early_bootstrap_verifier']=file_record(HERE/'ws73_early_fault.py')
    m['four_device_parallel_rf']=parallel and not business
    m['four_device_parallel_business']=business
    m['four_device_disconnect_requested']=disconnect_isolation
    m['four_device_burst_requested']=parallel_burst
    m['four_device_owned_requested']=parallel_owned
    m['four_device_update_delivery_requested']=parallel_delivery
    m['four_device_shared_subscription_requested']=parallel_subscription
    if parallel_benchmark:m['four_device_dynamic_benchmark_requested']=True
    if parallel_benchmark_case!='parallel':m['four_benchmark_case']=parallel_benchmark_case
    if business:m['parallel_business_verifier']=file_record(HERE/'ws73_parallel_data.py')
    m['parallel_start_offset_ms']=parallel_offset
    if parallel:
        m['scope']='four real WS73 two-pair dynamic short-long application benchmark'if parallel_benchmark else 'four real WS73 two-pair protected shared subscriptions'if parallel_subscription else 'four real WS73 two-pair protected update delivery'if parallel_delivery else 'four real WS73 two-pair owned SSAP approvals and owner loss'if parallel_owned else 'four real WS73 two-pair 2042-byte burst and observed budgets' if parallel_burst else 'four real WS73 controlled pair disconnect with surviving business' if disconnect_isolation else 'four real WS73 two-pair connected business' if business else 'four real WS73 two-pair RF timing contrast' if parallel_offset else 'four real WS73 two-pair RF'
    if parallel:m['parallel_verifier']=file_record(HERE/'ws73_parallel.py')
    m['qmp_guest_hotplug']=passthrough
    m['connection_verify_requested']=connection_verify
    m['live_daemon_link_resync']=link_resync
    m['acb_transport_selftest_requested']=acb_probe
    m['live_security_agent_requested']=agent_mode
    if agent_mode:m['security_agent_verifier']=file_record(HERE/'ws73_security_agent.py')
    if agent_mode and agent_mode.startswith('cli-'):m['security_cli_verifier']=file_record(HERE/'ws73_security_cli.py')
    m['channel_fairness_requested']=fairness
    m['channel_fairness_acceptance']=False
    if fairness:m['channel_fairness_verifier']=file_record(HERE/'ws73_channel_fairness.py')
    m['dynamic_channel_burst_requested']=dynamic_burst
    m['dynamic_channel_long_bytes_requested']=dynamic_long
    m['dynamic_channel_verification_requested']=dynamic_channels
    m['dynamic_channel_acceptance']=False
    m['socket_benchmark_requested']=benchmark_mode
    if benchmark_mode:
        m['socket_benchmark_role_contract_version']=1
        m['benchmark_trace_contract_version']=1
        m['benchmark_process_resource_contract_version']=1
        m['socket_benchmark_apps_acceptance']=False
        m['socket_benchmark_window_requested']=benchmark_window
        m['socket_benchmark_config_requested']=benchmark_config
        if benchmark_channel is not None:m['benchmark_channel_request']=benchmark_channel
        if benchmark_service is not None:
            m[benchmark_ssap.FIELD]=benchmark_service;m['benchmark_ssap_acceptance']=False
        m['socket_benchmark_xhci_requested']=benchmark_xhci
        m['benchmark_verifiers']=[file_record(HERE/name) for name in benchmark_verifier_names]
    m['socket_benchmark_acceptance']=False
    m['performance_qualified']=False
    m['channel_socket_verification_requested']=channel_socket
    m['application_discovery_requested']=application_discovery
    if application_discovery:m['application_discovery_case']=getattr(args,'application_discovery_case','release')
    m['application_discovery_acceptance']=False
    if application_discovery:m['application_discovery_verifier']=file_record(HERE/'ws73_application_discovery.py')
    m['application_client_verification_requested']=application_clients
    m['application_client_acceptance']=False
    if application_clients:
        m['application_client_verifier']=file_record(HERE/'ws73_application_client.py')
        m['application_role_verifier']=file_record(HERE/'ws73_application_role.py')
    m['channel_socket_rounds_requested']=channel_rounds if channel_socket else None
    m['connection_down_failure_observe_seconds']=down_failure_observe
    m['channel_socket_bytes_requested']=channel_bytes if channel_socket else None
    if link_payload is not None:
        m['link_payload_preference_requested']=link_payload
        m['link_payload_preference_verifier']=file_record(HERE/'ws73_link_payload.py')
        m['runner_inputs'].append(m['link_payload_preference_verifier'])
    if link_measurements:
        m['link_measurements_requested']=True
        m['link_measurement_verifier']=file_record(HERE/'ws73_link_measurement.py')
        m['runner_inputs'].append(m['link_measurement_verifier'])
    m['channel_socket_close_prefix_requested']=channel_close
    m['channel_socket_burst_requested']=channel_burst
    m['channel_socket_boundaries_requested']=channel_boundaries
    m['ordinary_channel_socket_acceptance']=False
    m['channel_info_verification_requested']=channel_socket
    m['ordinary_channel_info_acceptance']=False
    m['ssap_exchange_info_acceptance']=False
    m['ssap_value_acceptance']=False
    m['ssap_value_lengths_requested']=value_lengths
    m['ssap_value_lengths_acceptance']=False
    if value_lengths:m['ssap_value_lengths_contract_version']=4
    if value_lengths:m['ssap_value_lengths_verifier']=file_record(HERE/'ws73_ssap_value.py')
    m['ssap_access_acceptance']=False
    m['ssap_subscription_requested']=subscription
    m['ssap_subscription_acceptance']=False
    m['ssap_subscription_shared_requested']=subscription_shared
    m['ssap_subscription_shared_acceptance']=False
    m['ssap_subscription_shared_case']=subscription_shared_case
    if subscription_shared_case!='release':m['ssap_subscription_shared_pressure_contract_version'if subscription_shared_case=='pressure'else'ssap_subscription_shared_lifetime_contract_version']=1
    m['ssap_subscription_renewal_requested']=subscription_renewal
    m['ssap_subscription_renewal_acceptance']=False
    m['ssap_subscription_pressure_requested']=subscription_pressure
    m['ssap_subscription_pressure_acceptance']=False
    m['ssap_subscription_owner_loss_requested']=subscription_owner_loss
    m['ssap_subscription_owner_loss_acceptance']=False
    m['ssap_subscription_inflight_release_requested']=subscription_inflight
    m['ssap_subscription_inflight_release_acceptance']=False
    if subscription_inflight_case=='expiry':
        m['ssap_subscription_inflight_case']='expiry'
        m['ssap_subscription_inflight_expiry_acceptance']=False
    if subscription_inflight:m['ssap_subscription_inflight_verifier']=file_record(HERE/'ws73_ssap_sender_deadline.py')
    if subscription:m['ssap_subscription_verifier']=file_record(HERE/'ws73_ssap_subscription.py')
    m['ssap_update_delivery_requested']=update_delivery
    m['ssap_update_delivery_acceptance']=False
    m['ssap_receive_lifecycle_requested']=receive_lifecycle
    m['ssap_receive_lifecycle_acceptance']=False
    m['ssap_sender_deadline_requested']=sender_deadline
    from ws73_ssap_sender_deadline import lifecycle_case
    m['ssap_sender_lifecycle_case']=lifecycle_case(args)
    m['ssap_sender_deadline_acceptance']=False
    if sender_deadline:m['ssap_sender_deadline_verifier']=file_record(HERE/'ws73_ssap_sender_deadline.py')
    if receive_lifecycle:m['ssap_receive_lifecycle_verifier']=file_record(HERE/'ws73_ssap_receive_lifecycle.py')
    if update_delivery:m['ssap_update_delivery_verifier']=file_record(HERE/'ws73_ssap_update_delivery.py')
    m['ssap_owned_update_requested']=owned_update
    m['ssap_owned_update_acceptance']=False
    if owned_update:m['ssap_owned_update_verifier']=file_record(HERE/'ws73_ssap_owned_update.py')
    m['ssap_owned_verification_requested']=ssap_owned
    m['ssap_owned_acceptance']=False
    m['ssap_read_provider_requested']=read_provider
    m['ssap_read_provider_acceptance']=False
    m['ssap_sdk_read_provider_requested']=sdk_read_provider
    m['ssap_sdk_read_provider_acceptance']=False
    if sdk_read_provider:
        from ws73_ssap_sdk_read_provider import VERSION as sdk_provider_version
        m['ssap_sdk_read_provider_version']=sdk_provider_version
        m['ssap_sdk_read_provider_verifier']=file_record(HERE/'ws73_ssap_sdk_read_provider.py')
        m['ssap_sdk_read_provider_verifier']['bytes']=(HERE/'ws73_ssap_sdk_read_provider.py').stat().st_size
    m['ssap_sdk_write_provider_requested']=sdk_write_provider
    m['ssap_sdk_write_provider_acceptance']=False
    if sdk_write_provider:
        from ws73_ssap_sdk_write_provider import VERSION as sdk_write_provider_version
        m['ssap_sdk_write_provider_version']=sdk_write_provider_version
        m['ssap_sdk_write_provider_verifier']=file_record(HERE/'ws73_ssap_sdk_write_provider.py')
        m['ssap_sdk_write_provider_verifier']['bytes']=(HERE/'ws73_ssap_sdk_write_provider.py').stat().st_size
    m['ssap_write_provider_unregister_requested']=write_unregister
    m['ssap_write_provider_owner_exit_requested']=write_owner_exit
    m['ssap_write_provider_down_requested']=write_down
    m['ssap_write_provider_unregister_acceptance']=False
    m['ssap_write_provider_owner_exit_acceptance']=False
    m['ssap_write_provider_down_acceptance']=False
    if write_unregister:
        from ws73_ssap_write_unregister import VERSION as write_unregister_version
        m['ssap_write_provider_unregister_version']=write_unregister_version
        m['ssap_write_provider_unregister_verifier']=file_record(HERE/'ws73_ssap_write_unregister.py')
        m['ssap_write_provider_unregister_verifier']['bytes']=(HERE/'ws73_ssap_write_unregister.py').stat().st_size
    if write_owner_exit:
        from ws73_ssap_write_owner_exit import VERSION as write_owner_exit_version
        m['ssap_write_provider_owner_exit_version']=write_owner_exit_version
        m['ssap_write_provider_owner_exit_verifier']=file_record(HERE/'ws73_ssap_write_owner_exit.py')
        m['ssap_write_provider_owner_exit_verifier']['bytes']=(HERE/'ws73_ssap_write_owner_exit.py').stat().st_size
    if write_down:
        from ws73_ssap_write_down import VERSION as write_down_version
        m['ssap_write_provider_down_version']=write_down_version
        m['ssap_write_provider_down_verifier']=file_record(HERE/'ws73_ssap_write_down.py')
        m['ssap_write_provider_down_verifier']['bytes']=(HERE/'ws73_ssap_write_down.py').stat().st_size
    m['ssap_write_provider_deadline_requested']=write_deadline
    m['ssap_write_provider_deadline_acceptance']=False
    if write_deadline:
        from ws73_ssap_write_deadline import VERSION as write_deadline_version
        m['ssap_write_provider_deadline_version']=write_deadline_version
        m['ssap_write_provider_deadline_verifier']=file_record(HERE/'ws73_ssap_write_deadline.py')
        m['ssap_write_provider_deadline_verifier']['bytes']=(HERE/'ws73_ssap_write_deadline.py').stat().st_size
    if read_provider:
        from ws73_ssap_read_provider import VERSION as provider_version
        m['ssap_read_provider_version']=provider_version
        m['ssap_read_provider_verifier']=file_record(HERE/'ws73_ssap_read_provider.py')
    m['ssap_provider_owner_exit_requested']=provider_exit
    m['ssap_provider_owner_exit_acceptance']=False
    if provider_exit:
        from ws73_ssap_provider_owner_exit import VERSION as provider_exit_version
        m['ssap_provider_owner_exit_version']=provider_exit_version
        m['ssap_provider_owner_exit_verifier']=file_record(HERE/'ws73_ssap_provider_owner_exit.py')
    m['ssap_provider_unregister_requested']=provider_unregister
    m['ssap_provider_unregister_acceptance']=False
    if provider_unregister:
        from ws73_ssap_provider_unregister import VERSION as provider_unregister_version
        m['ssap_provider_unregister_version']=provider_unregister_version
        m['ssap_provider_unregister_verifier']=file_record(HERE/'ws73_ssap_provider_unregister.py')
    m['ssap_provider_deadline_requested']=provider_deadline
    m['ssap_provider_deadline_acceptance']=False
    if provider_deadline:
        from ws73_ssap_provider_deadline import VERSION as provider_deadline_version
        m['ssap_provider_deadline_version']=provider_deadline_version
        m['ssap_provider_deadline_verifier']=file_record(HERE/'ws73_ssap_provider_deadline.py')
    m['ssap_description_requested']=description
    m['ssap_description_acceptance']=False
    if description:
        m['ssap_description_version']=1
        m['ssap_description_verifier']=file_record(HERE/'ws73_ssap_description.py')
    m['ssap_write_command_requested']=write_command
    m['ssap_write_command_acceptance']=False
    if write_command:
        m['ssap_write_command_contract_version']=1
        m['ssap_write_command_verifier']=file_record(HERE/'ws73_ssap_command.py')
    m['ssap_command_policy_requested']=command_policy
    m['ssap_command_policy_acceptance']=False
    if command_policy:
        m['ssap_command_policy_contract_version']=1
        m['ssap_command_policy_verifier']=file_record(HERE/'ws73_ssap_command_policy.py')
    m['ssap_command_deadline_requested']=command_deadline
    m['ssap_command_deadline_acceptance']=False
    if command_deadline:
        m['ssap_command_deadline_contract_version']=1
        m['ssap_command_deadline_verifier']=file_record(HERE/'ws73_ssap_command_deadline.py')
    m['native_return_requested']=native_return
    m['native_return_acceptance']=False
    m['native_controller_return_requested']=native_controller
    m['native_controller_return_acceptance']=False
    m['controller_directory_requested']=directory_events
    m['controller_directory_acceptance']=False
    if directory_events:
        m['controller_directory_verifier']=file_record(HERE/'ws73_controller_directory.py')
    if native_return or native_controller:m['runner_inputs'] += [file_record(HERE/'ws73_native_return_fixture.c')]
    m['ssap_initialization_requested']=ssap_initialization
    m['ssap_initialization_stage']=initialization_stage if ssap_initialization else None
    m['ssap_initialization_acceptance']=False
    m['ssap_requester_lifecycle_requested']=requester_lifecycle
    m['ssap_requester_lifecycle_acceptance']=False
    m['ssap_owner_lifecycle_requested']=owner_lifecycle
    m['ssap_owner_publisher_requested']=owner_publisher
    m['ssap_owner_lifecycle_acceptance']=False
    m['ssap_service_policy_requested']=service_policy
    m['ssap_service_policy_acceptance']=False
    if service_policy:m['ssap_service_policy_verifier']=file_record(HERE/'ws73_ssap_service_policy.py')
    m['ssap_discovery_acceptance']=False
    m['connection_advertising_requested']=connection_advertising if connection_verify else None
    m['channel_daemon_crash_requested']=channel_death
    m['channel_daemon_index']=channel_death_index
    if channel_death:
        m['channel_daemon_verifier']=file_record(HERE/'ws73_channel_daemon_crash.py')
        m['channel_daemon_restart_version']=2
        m['channel_daemon_write_verifier']=file_record(HERE/'ws73_ssap_daemon_restart.py')
    m['daemon_crash_requested']=daemon_crash
    if daemon_crash:m['daemon_crash_verifier']=file_record(HERE/'ws73_daemon_crash.py')
    m['observer_policy_requested']=observer_policy
    if observer_policy:m['observer_policy_verifier']=file_record(HERE/'ws73_observer_policy.py')
    m['initializer_lifecycle_requested']=initializer_lifecycle
    if initializer_lifecycle:m['initializer_lifecycle_verifier']=file_record(HERE/'ws73_initialization_lifecycle.py')
    m['artificial_guest_transport_fault']=recovery or partial_rx_target is not None
    if partial_rx_target is not None:
        m['usb_partial_rx_diagnostic_requested']=True
        m['usb_partial_rx_diagnostic']={}
        m['runner_inputs'] += [file_record(HERE/name)for name in ('ws73_usb_partial_diagnostic.py','ws73_usb_lifecycle.py')]
    m['live_event_copy_requested']=event_copy
    m['live_diagnostic_requested']=diagnostic
    m['live_diagnostic_deadline_requested']=deadline_gate
    m['live_diagnostic_autonomous_requested']=autonomous_gate
    m['live_active_deadline_requested']=active_gate
    m['live_active_close_requested']=active_close_gate
    m['live_managed_resource_recreation']=resource_recreation
    m['live_managed_partial_case']=partial_case
    m['live_managed_partial_domain']=partial_domain if partial_gate else None
    m['live_managed_real_later_step']=real_step
    m['live_managed_ordinary_eviction']=ordinary_eviction
    m['live_daemon_cancel_removal']=daemon_remove
    if daemon_remove:m['daemon_removal_verifier']=file_record(HERE/'ws73_daemon_removal.py')
    m['live_daemon_hold_case']=daemon_hold
    if daemon_hold:m['daemon_hold_verifier']=file_record(HERE/'ws73_daemon_hold.py')
    if ordinary_eviction:m['managed_eviction_verifier']=file_record(HERE/'ws73_management_eviction.py')
    if real_later:m['managed_real_later_verifier']=file_record(HERE/'ws73_host_later_hold.py')
    m['live_managed_ready_peer']=ready_peer
    if ready_peer:m['managed_ready_peer_verifier']=file_record(HERE/'ws73_management_ready_peer.py')
    m['live_managed_selected_cleanup']=selected_cleanup
    m['live_managed_scan_parameter_cleanup']=parameter_cleanup
    m['live_managed_queue_connections']=queue_connections
    m['live_managed_queue_ready_peer']=queue_peer
    if queue_peer:m['managed_queue_ready_peer_verifier']=file_record(HERE/'ws73_management_queue_ready_peer.py')
    m['live_managed_queue_requested']=queued_gate
    m['live_setup_release_requested']=setup_gate
    m['live_connected_file_case']=connected_case
    m['live_connected_file_index']=connected_index if connected_case else None
    m['live_connected_reply_hold']=connected_reply
    m['live_link_snapshot_gate']=link_snapshot
    m['live_peer_binding_gate']=peer_binding
    m['live_channel_grant_gate']=channel_grant
    if sibling_business:m.update(channel_sibling_business_requested=True,channel_sibling_business_contract_version=4,sibling_verifier=file_record(HERE/'ws73_channel_sibling.py'))
    if protected:m.update(live_channel_security_required=protected,protected_security_verifiers=[file_record(HERE/name) for name in ['ws73_protected_grant.py','ws73_security_capabilities.py','ws73_security_numeric.py','ws73_key_agreement.py']])
    m['live_channel_scm_rights_gate']=channel_scm_rights
    m['live_channel_revoke_prefix_gate']=channel_revoke_prefix
    if queued_discard:m['queued_discard_contract_version']=1
    m['session_service_observation_requested']=session_service
    m['session_service_acceptance']=False
    if service_profile is not None:
        from ws73_session_service import FULL_LOAD_PROFILE
        m.update(session_service_collector_contract_version=2,session_service_collector_profile=dict(FULL_LOAD_PROFILE))
    if session_service:m['session_service_verifiers']=[file_record(HERE/name) for name in ['ws73_session_service.py','ws73_trace_layout.py']]
    m['session_idle_observation_requested']=session_idle
    if session_idle:m['session_idle_verifier']=file_record(HERE/'ws73_session_idle.py')
    m['live_security_capabilities_requested']=security_capabilities
    m['live_security_cancel_pending_requested']=cancel_pending
    m['live_security_original_deadline_requested']=original_deadline
    if cancel_pending:m['security_cancel_verifier']=file_record(HERE/'ws73_security_cancel.py')
    m['live_security_unauthenticated_encryption_requested']=encryption
    m['live_security_numeric_requested']=numeric
    if numeric:m['security_numeric_verifiers']=[file_record(HERE/name) for name in ['ws73_security_numeric.py','ws73_key_agreement.py']]
    m['live_security_key_agreement_requested']=key_agreement
    if key_agreement:m['security_key_agreement_verifier']=file_record(HERE/'ws73_key_agreement.py')
    if security_capabilities:m['security_capabilities_verifier']=file_record(HERE/'ws73_security_capabilities.py')
    m['live_channel_deadline_requested']=channel_deadline
    if channel_deadline:
        m['channel_deadline_verifier']=file_record(HERE/'ws73_channel_deadline.py')
        m['intent_phase_contract_version']=2
    m['live_channel_link_down_requested']=channel_link_down
    if channel_link_down:m['channel_link_down_verifier']=file_record(HERE/'ws73_channel_link_down.py')
    if channel_revoke_prefix:
        m['revoke_prefix_verifier']=file_record(HERE/'ws73_revoke_prefix.py')
        m['prefix_hold_verifier']=file_record(HERE/'ws73_channel_prefix_hold.py')
        m['managed_prefix_geometry_contract_version']=1
    m['live_channel_directions_gate']=channel_directions
    if channel_grant:m['channel_grant_verifier']=file_record(HERE/'ws73_channel_grant.py')
    if connected_case:m['connected_file_verifier']=file_record(HERE/'ws73_connected_file_gate.py');m['native_pair_verifier']=file_record(HERE/'ws73_native_pair.py')
    if queued_gate:
        m['managed_queue_verifier']=file_record(HERE/'ws73_management_queued.py')
    if partial_gate:
        m['managed_partial_verifier']=file_record(HERE/'ws73_management_partial.py')
        if resource_recreation:m['managed_resource_verifier']=file_record(HERE/'ws73_resource_file_gate.py')
    if setup_gate:
        m['setup_release_verifier']=file_record(HERE/'ws73_management_setup.py')
    if active_gate:
        m['active_deadline_verifier']=file_record(HERE/'ws73_active_deadline.py')
    process=monitor=channel=None
    partial_rx=None
    physical_boundary=None
    timeline=HostTimeline(output/'host-inventory.jsonl')
    try:
        package=prepared(args.prepared.resolve());m['prepared_manifest']=file_record(args.prepared.resolve()/'manifest.json')
        retry_requested(args, package)
        if native_retry:m['native_event_retry_test']=package['native_event_retry_test']
        if description:
            from ws73_ssap_description import validate_inputs as description_inputs
            description_inputs(package)
        if read_provider:
            from ws73_ssap_read_provider import validate_inputs as provider_inputs
            provider_inputs(package)
        if sdk_read_provider:
            from ws73_ssap_sdk_read_provider import validate_inputs as sdk_provider_inputs
            sdk_provider_inputs(package)
        if sdk_write_provider:
            from ws73_ssap_sdk_write_provider import validate_inputs as sdk_write_provider_inputs
            sdk_write_provider_inputs(package)
        if write_unregister:
            from ws73_ssap_write_unregister import validate_inputs as write_unregister_inputs
            write_unregister_inputs(package)
        if write_owner_exit:
            from ws73_ssap_write_owner_exit import validate_inputs as write_owner_exit_inputs
            write_owner_exit_inputs(package)
        if write_down:
            from ws73_ssap_write_down import validate_inputs as write_down_inputs
            write_down_inputs(package)
        if write_deadline:
            from ws73_ssap_write_deadline import validate_inputs as write_deadline_inputs
            write_deadline_inputs(package)
        if provider_exit:
            from ws73_ssap_provider_owner_exit import validate_inputs as provider_exit_inputs
            provider_exit_inputs(package)
        if provider_unregister:
            from ws73_ssap_provider_unregister import validate_inputs as provider_unregister_inputs
            provider_unregister_inputs(package)
        if provider_deadline:
            from ws73_ssap_provider_deadline import validate_inputs as provider_deadline_inputs
            provider_deadline_inputs(package)
        if sibling_business:
            from ws73_channel_sibling import require_preparation
            require_preparation(package,args.prepared.resolve())
        if channel_revoke_prefix and (type(package.get('managed_prefix_geometry_contract_version')) is not int or package['managed_prefix_geometry_contract_version']!=1):
            raise ValueError('new prepared buffer-geometry contract required before USB attachment;no old-root fallback')
        if partial_rx_target is not None:
            from ws73_usb_partial_diagnostic import validate_inputs as validate_partial_rx
            validate_partial_rx(package)
        from ws73_ssap_initialization import exchange_contract
        m['ssap_exchange_contract_version']=exchange_contract(package)
        if channel_death:
            from ws73_ssap_daemon_restart import validate_inputs as restart_inputs
            restart_inputs(package)
        from ws73_ssap_update_delivery import contract_version as delivery_contract
        m['ssap_update_delivery_contract_version']=delivery_contract(package)
        if directory_events:
            from ws73_controller_directory import staged_program
            m['controller_directory_program']=staged_program(args.prepared.resolve()/'root',package['guest_files'])
            from ws73_controller_directory import staged_clients
            m['controller_directory_clients']=staged_clients(args.prepared.resolve()/'root',package['guest_files'],package.get('controller_directory_clients'))

        if down_failure_observe:
            validate_down_failure_inputs(package)
        if (native_return or native_controller) and ('native_vm' not in package or 'native_return_fixture' not in package):
            raise ValueError('explicit staged real-bind fixture and native VM required')
        if native_return or native_controller:m['native_return_fixture']=package['native_return_fixture']
        if native_controller:
            if 'native_return_probe' not in package:raise ValueError('controller return requires pinned direct broker owner probe')
            probe=args.prepared/'root/bin/native-owner-probe'
            if file_record(probe)!=package['native_return_probe']['program']:raise ValueError('prepared owner probe changed')
            m['native_return_probe']=package['native_return_probe']
        if ssap_initialization:
            from ws73_ssap_initialization import validate_qemu,check_selector_contract
            selector_version=check_selector_contract(package,initialization_stage)
            validate_qemu(package['qemu']['path'], initialization_stage,selector_version)
        if sender_deadline:
            from ws73_ssap_sender_deadline import validate_qemu,validate_inputs
            validate_qemu(package['qemu']['path'])
            validate_inputs(package)
        if write_command:
            from ws73_ssap_command import validate_inputs as command_inputs
            if 'native_vm' not in package:raise ValueError('Write Command requires the existing native VM profile')
            command_inputs(package)
        if command_policy:
            from ws73_ssap_command_policy import validate_inputs as command_policy_inputs
            command_policy_inputs(package)
        if command_deadline:
            from ws73_ssap_command_deadline import validate_inputs as command_deadline_inputs
            command_deadline_inputs(package)
        if application_discovery and 'native_vm' not in package:
            raise ValueError('application discovery requires the verified native VM profile')
        if application_discovery and getattr(args,'application_discovery_case','release')=='ttl':
            if 'discovery_lifetime_probe' not in package:raise ValueError('TTL requires prepared actual SDK lifetime probe')
            from ws73_application_discovery import validate_probe
            probe=dict(path='/bin/discovery-lifetime-probe',sha256=package['discovery_lifetime_probe']['binary']['sha256'])
            validate_probe(probe,args.prepared/'root',package['guest_files']);m['application_discovery_probe']=probe
        if subscription:
            if type(package.get('ssap_subscription_contract_version'))is not int or package['ssap_subscription_contract_version']!=1 or 'native_vm'not in package:raise ValueError('subscription requires newly prepared native contract1')
            m['ssap_subscription_contract_version']=1
            if subscription_shared:
                if type(package.get('ssap_subscription_shared_contract_version'))is not int or package['ssap_subscription_shared_contract_version']!=1:raise ValueError('fresh shared-owner prepared contract1 required')
                from ws73_ssap_sender_deadline import validate_inputs
                validate_inputs(package,subscription=True,shared=True)
                if subscription_shared_case!='release':
                    field='ssap_subscription_shared_pressure_contract_version'if subscription_shared_case=='pressure'else'ssap_subscription_shared_lifetime_contract_version'
                    if type(package.get(field))is not int or package[field]!=1:raise ValueError('fresh prepared shared case contract1 required')
                m['ssap_subscription_shared_contract_version']=1
                m['ssap_subscription_shared_verifier']=file_record(HERE/'ws73_ssap_shared.py')
            if type(package.get('ssap_subscription_snapshot_contract_version'))is not int or package['ssap_subscription_snapshot_contract_version']!=1:raise ValueError('subscription requires new closed local phase snapshots')
            m['ssap_subscription_snapshot_contract_version']=1
            if subscription_renewal:
                if type(package.get('ssap_subscription_renewal_contract_version'))is not int or package['ssap_subscription_renewal_contract_version']!=1:raise ValueError('renewal requires explicit new prepared renewal contract1')
                m['ssap_subscription_renewal_contract_version']=1
            if subscription_pressure:
                if type(package.get('ssap_subscription_pressure_contract_version'))is not int or package['ssap_subscription_pressure_contract_version']!=1:raise ValueError('pressure requires explicit new prepared pressure contract1')
                m['ssap_subscription_pressure_contract_version']=1
            if subscription_owner_loss:
                if type(package.get('ssap_subscription_owner_loss_contract_version'))is not int or package['ssap_subscription_owner_loss_contract_version']!=1:raise ValueError('owner loss requires explicit new prepared contract1')
                m['ssap_subscription_owner_loss_contract_version']=1
            if subscription_inflight:
                if type(package.get('ssap_subscription_inflight_release_contract_version'))is not int or package['ssap_subscription_inflight_release_contract_version']!=1:raise ValueError('in-flight release requires explicit new prepared contract1')
                from ws73_ssap_sender_deadline import validate_qemu,validate_inputs
                validate_qemu(package['qemu']['path']);validate_inputs(package,subscription=True)
                m['ssap_subscription_inflight_release_contract_version']=1
                if subscription_inflight_case=='expiry':
                    if type(package.get('ssap_subscription_inflight_expiry_contract_version'))is not int or package['ssap_subscription_inflight_expiry_contract_version']!=1:raise ValueError('fresh explicit in-flight expiry prepared contract1 required')
                    m['ssap_subscription_inflight_expiry_contract_version']=1
        if benchmark_mode:
            from ws73_socket_benchmark import validate_role_sources
            validate_role_sources(package,dynamic=benchmark_channel is not None,parallel=is_parallel(benchmark_channel),ssap=benchmark_service is not None,observe=benchmark_ssap.observing(benchmark_service),hcc=benchmark_ssap.observing_hcc(benchmark_service),link_probe=benchmark_ssap.probing_link(benchmark_service))
        if application_clients and 'native_vm' not in package:
            raise ValueError('application clients require the verified native VM profile')
        if application_clients:
            if type(package.get('application_role_contract_version'))is not int or package['application_role_contract_version']!=2:raise ValueError('application role contract2 requires newly prepared exact artifacts')
            m['application_role_contract_version']=2
        if owner_publisher=='sdk' and 'native_vm' not in package:
            raise ValueError('SDK lifecycle publisher requires verified native VM')
        if agent_mode and ('native_vm' not in package or 'native_security_agent_probe' not in package):raise ValueError('Agent requires native VM and staged real witness')
        if agent_mode=='install-cancel':
            from ws73_security_install_hold import validate_qemu
            validate_qemu(package['qemu']['path'])
        if early_fault and 'native_vm' not in package:raise ValueError('early bootstrap fault requires signed native VM')
        if channel_death:validate_channel_death_mode(args,package)
        if acb_probe and 'acb_probe_module' not in package:raise ValueError('frozen signed ACB selftest module missing')
        if connection_verify and 'native_vm' not in package:
            raise ValueError('connection gate requires actual signed native VM')
        if daemon_crash and 'native_vm' not in package:
            raise ValueError('daemon crash requires qualified native module VM')
        if observer_policy and 'native_vm' not in package:
            raise ValueError('observer policy requires qualified native module VM')
        if initializer_lifecycle and 'native_vm' not in package:
            raise ValueError('initializer lifecycle requires qualified native module VM')
        native_vm.check_discovery_config_gate(package, args)
        if 'native_vm' in package:
            import tomllib
            ssap_requirement=tomllib.loads((args.prepared/'root/etc/sparklink/main.conf').read_text()).get('ssap',{}).get('channel_security',0)
            if type(ssap_requirement) is not int or ssap_requirement not in (0,1,2):raise ValueError('invalid frozen SMTC policy')
            m['live_ssap_security_requirement']=ssap_requirement
            if (parallel_subscription or parallel_delivery or update_delivery or subscription) and ssap_requirement!=2:raise ValueError('update delivery/subscription requires explicit protected2 SSAP prepared config')
            if ssap_requirement and ('numeric-approve'if parallel_delivery or parallel_subscription else agent_mode,ssap_requirement) not in [('approve',1),('numeric-approve',2)]:raise ValueError('protected SMTC qualification requires matching positive Agent mechanism')

        if 'discovery_config' in package:
            m['discovery_config'] = package['discovery_config']
            m['custom_policy_rf_acceptance'] = False
            m['default_policy_acceptance'] = False
        if parallel and 'native_vm' not in package:
            raise ValueError('four-device gate requires qualified scratch-root native VM')
        if parallel and 'policy_expectation' not in package:
            raise ValueError('current four-device gate requires frozen policy expectation')
        if disconnect_isolation:
            if (type(package.get('four_disconnect_progress_contract_version'))is not int
                    or package['four_disconnect_progress_contract_version']!=1):
                raise ValueError('current Disconnect gate requires new causal-progress preparation')
            for name in ['ws73_parallel_data.py','ws73_channel_socket.py','ws73_connection_control.py']:
                staged=args.prepared/'root/usr/share/sparklink/tools'/name
                if file_record(staged)['sha256']!=file_record(HERE/name)['sha256']:
                    raise ValueError('current Disconnect preparation/source mismatch: '+name)
            m['four_disconnect_progress_contract_version']=1
        if parallel_benchmark:
            require_benchmark_preparation(package,args.prepared,case=parallel_benchmark_case)
            m['four_dynamic_benchmark_contract_version']=1
            if parallel_benchmark_case=='close-short':m['four_dynamic_benchmark_close_contract_version']=1
            if parallel_benchmark_case=='pressure':m['four_dynamic_benchmark_pressure_contract_version']=1
        if parallel_owned:
            require_owned_preparation(package,args.prepared)
            m['four_owned_contract_version']=1
        if parallel_subscription:
            require_subscription_preparation(package,args.prepared,case=subscription_shared_case)
            m['four_subscription_contract_version']=1
            m['four_subscription_security_requirement']=2
            if subscription_shared_case!='release':m['four_subscription_pressure_contract_version'if subscription_shared_case=='pressure'else'four_subscription_lifetime_contract_version']=1
        if parallel_delivery:
            require_delivery_preparation(package,args.prepared)
            m['four_delivery_contract_version']=1
            m['four_delivery_security_requirement']=2
        if 'policy_expectation' in package:
            m['policy_expectation'] = package['policy_expectation']
        if event_copy:
            raise ValueError('legacy read-copy live gate is retired; canonical ControllerEvent copy gate is separate')
        if event_copy and 'native_vm' not in package:
            raise ValueError('live copy gate requires the qualified scratch-root VM profile')
        if setup_gate and ('setup_release_probe_compile' not in package or 'native_vm' not in package):
            raise ValueError('Setup release requires frozen probe and qualified scratch-root VM')
        if queued_gate and ('managed_queue_probe_compile' not in package or 'native_vm' not in package):
            raise ValueError('Managed queue gate requires frozen probe and scratch-root VM')
        if active_gate and 'native_vm' not in package:
            raise ValueError('active retirement requires qualified scratch-root VM')
        if diagnostic:
            raise ValueError('legacy poll-dependent live diagnostic matrix is retired; current Native queries remain available')
        if not support:
            if package.get('resource_contract_version') != 1:
                raise ValueError('old prepared guest lacks explicit model/HCC resource contract; prepare a new artifact')
            if link_payload is not None:
                if package.get('link_payload_preference_contract_version') != 1:
                    raise ValueError('new prepared link command and CLI artifact required')
                guest_path=str(args.prepared.resolve()/'root/usr/share/sparklink/tools/ws73_link_payload.py')
                pins=[row for row in package['guest_files'] if row['path']==guest_path]
                if len(pins)!=1 or pins[0]['sha256']!=m['link_payload_preference_verifier']['sha256']:
                    raise ValueError('prepared link payload helper differs from host verifier')
            if link_measurements:
                if package.get('link_measurement_contract_version') != 1:
                    raise ValueError('new prepared link observation contract required')
                guest_path=str(args.prepared.resolve()/'root/usr/share/sparklink/tools/ws73_link_measurement.py')
                guest_pins=[row for row in package['guest_files'] if row['path']==guest_path]
                if len(guest_pins)!=1 or guest_pins[0]['sha256']!=m['link_measurement_verifier']['sha256']:
                    raise ValueError('prepared guest link observation helper differs from host verifier')
            firmware_version = 2 if 'device_input_contract_version' in package else 1
            if (type(package.get('firmware_evidence_contract_version')) is not int
                    or package['firmware_evidence_contract_version'] != firmware_version):
                raise ValueError('old prepared artifact lacks explicit firmware evidence contract; prepare a new artifact')
            physical_boundary=resources.PhysicalBoundary(args.ports, package, args.prepared.resolve())
            if runtime_addresses and (physical_boundary.models!=['E','E'] or package.get('runtime_address_contract_version')!=1):
                raise ValueError('fresh explicitly prepared E/E volatile address guest required')
            if runtime_addresses:
                validate_runtime_address_guest(args.prepared.resolve()/'root', package,
                                               m['runtime_address_verifier'])
            m['physical_resource_allocation']={'policy':file_record(resources.POLICY),
                'guard':file_record(HERE/'ws73_lab_resources.py'),
                'selected_ports':list(args.ports),
                'live_vm_inventory':args._resource_vm_inventory,
                'firmware':physical_boundary.firmware,'observations':physical_boundary.observations,
                'firmware_scope':'STAGED_INPUT_HASHES_ONLY_NOT_A_LOADED_IMAGE_WITNESS',
                'model_basis':'USER_PLACEMENT_UNTIL_GUEST_HCC_CHECK', 'vm_only':True}
            m['board_configuration_contract_version']=2 if 'device_input_contract_version' in package else 1
            m['firmware_evidence_contract_version']=firmware_version
            m['physical_resource_allocation']['board_configuration']=physical_boundary.board_configuration
            m['firmware_input_contract_version']=1
            m['physical_resource_allocation']['input_profiles']=package['firmware_profiles']
        lab=lab_module();devices={d['path']:d for d in lab.inventory()};m['inventory_before']=devices
        if not support:
            native_vm.check_runtime_only(package, devices, args.ports)
        timeline.observe(devices, 'initial')
        if not support:
            m['usb_host_boundary']=usb_host_boundary(package['qemu']['path'])
            if not m['usb_host_boundary']['supported']:
                raise ValueError('QEMU lacks required USB host opt-outs; build the pinned patched QEMU before physical passthrough')
            if len(args.ports)!=selected_count or len(set(args.ports))!=selected_count:raise ValueError('exact distinct physical port count required')
            for index,port in enumerate(args.ports):
                usb_properties(port,index)
                if port not in devices or not devices[port]['writable']:raise ValueError(port+': writable WS73 required; no host permission changes')
                if any(i['driver'] for i in devices[port]['interfaces']):raise ValueError(port+': host driver already owns it; no detach')
        if not os.access('/dev/kvm',os.R_OK|os.W_OK):raise ValueError('KVM access required; nested virtualization is unnecessary')
        share=output/'guest-output';share.mkdir(mode=0o700)
        if any(c in str(share) for c in [',','\n']):raise ValueError('QEMU evidence share path must not contain option delimiters')
        with tempfile.TemporaryDirectory(prefix='ws73-target-') as tmp:
            serial=Path(tmp)/'serial.sock';qmp=Path(tmp)/'qmp.sock'
            command=[package['qemu']['path'],'-machine','q35,accel=kvm','-cpu','host','-m',('3072M'if parallel_benchmark else '2048M'if benchmark_mode else'1024M'),'-smp',('1' if queued_gate else '2'),
                     '-display','none','-monitor','none','-no-reboot','-nic','none',
                     '-chardev',f'socket,id=console,path={serial},server=on,wait=off','-serial','chardev:console',
                     '-qmp',f'unix:{qmp},server=on,wait=off','-kernel',str(args.prepared.resolve()/'bzImage'),
                     '-initrd',str(args.prepared.resolve()/'initramfs.cpio.gz'),
                     '-append','console=ttyS0 loglevel=5 log_buf_len=4M panic=1 oops=panic'+
                     (' ws73.expected_models='+','.join(physical_boundary.models) if physical_boundary else '')+
                     (' ws73.firmware_profiles=1' if physical_boundary else '')+
                     (' ws73.runtime_addresses='+','.join(runtime_addresses) if runtime_addresses else '')+
                     (' ws73.prefix_geometry=1' if channel_revoke_prefix else '')+
                     (' ws73.support=1' if support else '')+
                     (' ws73.passthrough=1' if passthrough else '')+
                     (' ws73.parallel=1' if parallel else '')+
                     (' ws73.parallel_business=1' if business else '')+
                     (' ws73.parallel_disconnect=1' if disconnect_isolation else '')+
                     (' ws73.parallel_burst=1' if parallel_burst else '')+
                     (' ws73.parallel_benchmark=1 ws73.socket_benchmark_apps=1'if parallel_benchmark else '')+
                     (f' ws73.parallel_benchmark_case={parallel_benchmark_case}'if parallel_benchmark_case!='parallel'else '')+
                     (' ws73.parallel_owned=1'if parallel_owned else '')+
                     (' ws73.parallel_delivery=1'if parallel_delivery else '')+
                     (' ws73.parallel_subscription=1 ws73.ssap_subscription=1 ws73.ssap_subscription_shared=1 ws73.subscription_snapshot=1'if parallel_subscription else '')+
                     (f' ws73.parallel_offset={parallel_offset}' if parallel else '')+
                     (' ws73.daemon_remove=1' if daemon_remove else '')+
                     (' ws73.initializer_lifecycle=1' if initializer_lifecycle else '')+
                     (' ws73.observer_policy=1' if observer_policy else '')+
                     (' ws73.daemon_crash=1' if daemon_crash else '')+
                     (f' ws73.connection_verify=1 ws73.connection_advertising={connection_advertising}' if connection_verify else '')+
                     (' ws73.link_resync=1' if link_resync else '')+
                     (' ws73.acb_probe=1' if acb_probe else '')+
                     (' ws73.channel_boundaries=1' if channel_boundaries else '')+
                     (' ws73.channel_prefix_close=1' if channel_close else '')+
                     (' ws73.channel_burst=1' if channel_burst else '')+
                     (' ws73.ssap_owned=1' if ssap_owned else '')+
                     (' ws73.ssap_description=1' if description else '')+
                     (' ws73.ssap_read_provider=1' if read_provider else '')+
                     (' ws73.ssap_sdk_read_provider=1' if sdk_read_provider else '')+
                     (' ws73.ssap_sdk_write_provider=1' if sdk_write_provider else '')+
                     (' ws73.ssap_write_provider_unregister=1' if write_unregister else '')+
                     (' ws73.native_event_retry=1' if native_retry else '')+
                     (' ws73.ssap_write_provider_owner_exit=1' if write_owner_exit else '')+
                     (' ws73.ssap_write_provider_down=1' if write_down else '')+
                     (' ws73.ssap_write_provider_deadline=1' if write_deadline else '')+
                     (' ws73.ssap_provider_owner_exit=1' if provider_exit else '')+
                     (' ws73.ssap_provider_unregister=1' if provider_unregister else '')+
                     (' ws73.ssap_provider_deadline=1' if provider_deadline else '')+
                     (' ws73.ssap_owned_update=1' if owned_update else '')+
                     (' ws73.ssap_update_delivery=1' if update_delivery else '')+
                     (' ws73.ssap_subscription=1' if subscription else '')+
                     (' ws73.ssap_subscription_shared=1' if subscription_shared else '')+
                     (' ws73.subscription_shared_case='+subscription_shared_case if subscription_shared_case!='release'else '')+
                     (' ws73.ssap_subscription_renewal=1' if subscription_renewal else '')+
                     (' ws73.ssap_subscription_pressure=1' if subscription_pressure else '')+
                     (' ws73.ssap_subscription_owner_loss=1' if subscription_owner_loss else '')+
                     (' ws73.ssap_subscription_inflight_release=1' if subscription_inflight else '')+
                     (' ws73.subscription_inflight_case=expiry' if subscription_inflight_case=='expiry' else '')+
                     (' ws73.subscription_snapshot=1' if subscription else '')+
                     (' ws73.ssap_receive_lifecycle=1' if receive_lifecycle else '')+
                     (' ws73.ssap_sender_deadline=1' if sender_deadline else '')+
                     (' ws73.ssap_write_command=1' if write_command else '')+
                     (' ws73.ssap_command_policy=1' if command_policy else '')+
                     (' ws73.ssap_command_deadline=1' if command_deadline else '')+
                     (' ws73.ssap_sender_case='+m['ssap_sender_lifecycle_case'] if sender_deadline and m['ssap_sender_lifecycle_case']!='deadline' else '')+
                     (' ws73.ssap_value_lengths=1' if value_lengths else '')+
                     (' ws73.application_clients=1' if application_clients else '')+
                     (' ws73.application_discovery=1' if application_discovery else '')+
                     (' ws73.application_discovery_case='+args.application_discovery_case if application_discovery and getattr(args,'application_discovery_case','release')!='release' else '')+
                     (' ws73.ssap_owner_lifecycle=1' if owner_lifecycle else '')+
                     (' ws73.ssap_owner_sdk=1' if owner_publisher=='sdk' else '')+
                     (' ws73.ssap_requester_lifecycle=1' if requester_lifecycle else '')+
                     (' ws73.native_return=1' if native_return else '')+
                     (' ws73.native_controller_return='+native_controller if native_controller else '')+
                     (' ws73.controller_directory_events=1' if directory_events else '')+
                     (' ws73.ssap_initialization=1' if ssap_initialization else '')+
                     (' ws73.ssap_initialization_stage='+initialization_stage if ssap_initialization else '')+
                     (' ws73.ssap_service_policy=1' if service_policy else '')+
                     (' ws73.dynamic_channels=1' if dynamic_channels else '')+
                     (' ws73.channel_fairness=1' if fairness else '')+
                     (' ws73.socket_benchmark_apps=1'if benchmark_mode else '')+
                     (f' ws73.benchmark_mode={benchmark_mode} ws73.benchmark_window={benchmark_window} ws73.benchmark_xhci={benchmark_xhci} ws73.benchmark_count={benchmark_config["count"]} ws73.benchmark_bytes={benchmark_config["bytes"]} ws73.benchmark_interval_us={benchmark_config["interval_us"]}' if benchmark_mode else '')+
                     (' '+ ' '.join(channel_boot(benchmark_channel))if benchmark_channel is not None else'')+
                     (' '+ ' '.join(benchmark_ssap.boot(benchmark_service))if benchmark_service is not None else'')+
                     (' ws73.dynamic_burst=1' if dynamic_burst else '')+
                     (f' ws73.dynamic_long={dynamic_long}' if dynamic_long is not None else '')+
                     (f' ws73.channel_socket=1 ws73.channel_rounds={channel_rounds} ws73.channel_bytes={channel_bytes}' if channel_socket else '')+
                     (f' ws73.down_failure_observe={down_failure_observe}' if down_failure_observe else '')+
                     (f' ws73.security_agent={agent_mode}' if agent_mode else '')+
                     (' ws73.recovery=1' if recovery else '')+
                     (' ws73.early_bootstrap_fault=1' if early_fault else '')+
                     (' ws73.event_copy=1' if event_copy else '')+
                     (' ws73.diagnostic=1' if diagnostic else '')+
                     (' ws73.diagnostic_cancel=1' if cancellation else '')+
                     (' ws73.diagnostic_deadline=1' if deadline_gate else '')+
                     (' ws73.diagnostic_autonomous=1' if autonomous_gate else '')+
                     (' ws73.active_deadline=1' if active_gate else '')+
                     (' ws73.active_close=1' if active_close_gate else '')+
                     (' ws73.setup_release=1' if setup_gate else '')+
                     (' ws73.managed_queue=1' if queued_gate else '')+
                     (' ws73.managed_queue_confirmed_off=1' if getattr(args,'managed_queue_confirmed_off',False) else '')+
                     (' ws73.managed_queue_ready_peer=1' if queue_peer else '')+
                     (' ws73.managed_queue_connections=1' if queue_connections else '')+
                     (f' ws73.managed_partial=1 ws73.partial_case={partial_case} ws73.partial_domain={partial_domain}' if partial_gate else '')+
                     (' ws73.managed_recreate=1' if resource_recreation else '')+
                     (f' ws73.connected_case={connected_case} ws73.connected_index={connected_index}' if connected_case else '')+
                     (' ws73.channel_sibling_business=1 ws73.channel_sibling_contract=4'if sibling_business else '')+
                     (f' ws73.connected_reply={connected_reply}' if connected_reply else '')+
                     (' ws73.link_snapshot=1' if link_snapshot else '')+
                     (' ws73.link_measurements=1' if link_measurements else '')+
                     (' ws73.link_payload_preference='+link_payload if link_payload is not None else '')+
                     (' ws73.peer_binding=1' if peer_binding else '')+
                     (' ws73.channel_daemon_crash=1 ws73.channel_daemon_index='+str(channel_death_index) if channel_death else '')+
                     (' ws73.channel_grant=1' if channel_grant else '')+
                     (f' ws73.channel_security={protected}' if protected else '')+
                     (' ws73.channel_revoke_prefix=1' if channel_revoke_prefix else '')+
                     (' ws73.channel_queued_discard=1' if queued_discard else '')+
                     (' ws73.channel_link_down=1' if channel_link_down else '')+
                     (' ws73.channel_deadline=1 ws73.intent_phase=2' if channel_deadline else '')+
                     (' ws73.session_idle=1' if session_idle else '')+
                     (' ws73.session_service=1' if session_service else '')+
                     (' ws73.session_service_profile=full-load-v2' if service_profile is not None else '')+
                     (' ws73.security_capabilities=1' if security_capabilities else '')+
                     (' ws73.security_cancel_pending=1' if cancel_pending else '')+
                     (' ws73.security_original_deadline=1' if original_deadline else '')+
                     (' ws73.security_key_agreement=1' if key_agreement else '')+
                     (' ws73.security_encryption=1' if encryption else '')+
                     (' ws73.security_numeric='+numeric if numeric else '')+
                     (' ws73.channel_scm_rights=1' if channel_scm_rights else '')+
                     (' ws73.channel_directions=1' if channel_directions else '')+
                     (' ws73.selected_domain_cleanup=1' if selected_cleanup else '')+
                     (' ws73.scan_parameter_cleanup=1' if parameter_cleanup else '')+
                     (' ws73.managed_ready_peer=1' if ready_peer else '')+
                     (' ws73.ordinary_queue_eviction=1' if ordinary_eviction else '')+
                     (f' ws73.daemon_hold={daemon_hold}' if daemon_hold else '')+
                     (f' ws73.real_later_step=1 ws73.partial_step={real_step}' if real_later else '')+
                     (' ws73.empty_bulk=1' if getattr(args,'empty_bulk',False) else '')+
                     (' ws73.hotplug=1' if getattr(args,'hotplug',False) else ''),
                     '-device',firmware_profile.QEMU_DEVICE,
                     '-fsdev',f'local,id=evidence,path={share},security_model=mapped-xattr',
                     '-device','virtio-9p-pci,fsdev=evidence,mount_tag=evidence']
            if not support:
                command += lifecycle_trace(package['qemu']['path'], output)
                # Keep lifecycle diagnostics in the console even when the
                # guest cannot seal dmesg after an environment timeout.
                index=command.index('-append')+1
                command[index]=command[index].replace('loglevel=5', 'loglevel=6')
            if 'native_vm' in package:
                options, append = native_vm.launch(args.prepared.resolve(), output, package)
                command += options
                command[command.index('-append')+1] += append
                m['native_vm'] = package['native_vm']
            m['qemu_args']=command;write_json(output/'manifest.json',m)
            with (output/'qemu-stderr.log').open('wb') as stderr,(output/'console.log').open('wb') as log:
                process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=stderr,
                                         pass_fds=getattr(args,'_resource_fds',()))
                deadline=time.monotonic()+args.timeout
                while not serial.exists() or not qmp.exists():
                    if process.poll() is not None or time.monotonic()>deadline:raise ValueError('QEMU socket startup failed')
                    time.sleep(0.05)
                channel=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);channel.connect(str(serial));channel.setblocking(False)
                monitor=lab.Qmp(qmp,output/'qmp.jsonl')
                if physical_boundary:
                    monitor=physical_boundary.monitor(monitor)
                hold=None
                install_hold=None
                initialization_hold=None
                receive_capture=None
                sender_hold=None
                if sender_deadline:
                    from ws73_ssap_sender_deadline import Coordinator
                    sender_hold=Coordinator(share,output,m.setdefault('ssap_sender_deadline_hold',{}),package['qemu']['path'])
                if subscription_inflight:
                    from ws73_ssap_sender_deadline import Coordinator
                    sender_hold=Coordinator(share,output,m.setdefault('ssap_subscription_inflight_hold',{}),package['qemu']['path'],purpose='subscription-'+subscription_inflight_case)
                if receive_lifecycle:
                    from ws73_ssap_receive_lifecycle import CaptureCoordinator
                    receive_capture=CaptureCoordinator(share,output,m.setdefault('ssap_receive_capture_observations',{}))
                if ssap_initialization:
                    from ws73_ssap_initialization import Coordinator
                    initialization_hold=Coordinator(share,m.setdefault('ssap_initialization_hold',{}),package['qemu']['path'],initialization_stage,exchange_contract(package))
                if agent_mode=='install-cancel':
                    from ws73_security_install_hold import InstallCoordinator
                    install_hold=InstallCoordinator(share,m.setdefault('security_install_hold',{}),package['qemu']['path'])
                if channel_revoke_prefix and not channel_deadline:
                    from ws73_channel_prefix_hold import PrefixCoordinator
                    hold=PrefixCoordinator(share,m.setdefault('channel_prefix_hold',{}),connected_index,package['qemu']['path'])
                if channel_deadline:
                    from ws73_channel_deadline import DeadlineCoordinator
                    hold=DeadlineCoordinator(share,m.setdefault('channel_deadline_hold',{}),connected_index)
                if connected_reply:
                    from ws73_connected_file_gate import ConnectedHoldCoordinator, ConnectedOutcomeCoordinator
                    kind=ConnectedHoldCoordinator if connected_reply=='status' else ConnectedOutcomeCoordinator
                    hold=kind(share,m.setdefault('connected_file_hold',{}),connected_index)
                if partial_gate:
                    from ws73_management_partial import PartialCoordinator
                    if real_later:
                        from ws73_host_later_hold import LaterHostCoordinator
                        hold=LaterHostCoordinator(share,m.setdefault('managed_partial_hold',{}),real_step)
                    else:hold=PartialCoordinator(share,m.setdefault('managed_partial_hold',{}))
                if daemon_remove:
                    from ws73_daemon_removal import RemovalCoordinator
                    hold=RemovalCoordinator(share,m.setdefault('daemon_removal',{}))
                if daemon_hold:
                    from ws73_daemon_hold import DaemonHoldCoordinator
                    hold=DaemonHoldCoordinator(share,m.setdefault('daemon_hold',{}))
                if active_gate:
                    from ws73_active_deadline import ActiveDeadlineCoordinator
                    hold=ActiveDeadlineCoordinator(share,m.setdefault('active_deadline_hold',{}))
                if cancellation:
                    from ws73_diagnostic_hold import HoldCoordinator
                    hold=HoldCoordinator(share,m.setdefault('diagnostic_hold',{}))
                active=0;addresses={port:devices[port]['address'] for port in getattr(args,'ports',[])};transcript=bytearray();support_input=False;hotplug_phase=0
                if partial_rx_target is not None:
                    from ws73_usb_partial_diagnostic import Coordinator,requested_phase
                    partial_rx=Coordinator(share,output,m['usb_partial_rx_diagnostic'],partial_rx_target,args.ports,phase=requested_phase(args))
                watcher=lab.ReattachmentWatcher(addresses,m.setdefault('reattach',[]),owned=opened_usb_node)
                timeout_seal=None
                while process.poll() is None:
                    if time.monotonic()>deadline:
                        if timeout_seal is not None:
                            raise ValueError('environment timeout; graceful capture sealing deadline exceeded')
                        if support or passthrough or recovery or parallel or early_fault:
                            raise ValueError('environment timeout; preserve partial console/capture')
                        timeout_seal=SerialTimeoutSeal(transcript)
                        m['graceful_timeout']={'reason':'ENVIRONMENT_TIMEOUT','state':timeout_seal.phase,
                                               'started_wall_ns':time.time_ns(),'grace_seconds':30,
                                               'automatic_hotplug_confirmation':False}
                        if timeout_seal.initial_input:channel.sendall(timeout_seal.initial_input)
                        deadline=time.monotonic()+30
                        write_json(output/'manifest.json',m)
                    readers=[channel]+([] if support or passthrough or recovery or parallel or early_fault or timeout_seal is not None else [sys.stdin])
                    readable,_,_=select.select(readers,[],[],0.1)
                    if channel in readable:
                        data=channel.recv(65536)
                        if data:
                            log.write(data);log.flush();transcript.extend(data);sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
                    if not support and not passthrough and not recovery and not parallel and not channel_grant and not channel_death and not early_fault and timeout_seal is None and sys.stdin in readable:
                        data=os.read(sys.stdin.fileno(),4096)
                        if data:channel.sendall(data)
                        else:raise ValueError('interactive physical environment requires a terminal; no automatic hotplug confirmation')
                    text=transcript.decode(errors='replace')
                    if partial_rx:
                        partial_rx.poll(monitor,lambda i:live_runtime_owner(args.ports[i],process.pid,lab.inventory()))
                    if hold:
                        if hold.phase == 'arm_ready' and (hold.folder/'hold-arm_ready.json').exists():
                            hold.record['host_identity_at_arm'] = live_runtime_owner(
                                args.ports[connected_index if connected_reply or channel_revoke_prefix else 0], process.pid, lab.inventory())
                        hold.poll(monitor)
                    if receive_capture:receive_capture.poll()
                    if sender_hold:sender_hold.poll(monitor,lambda i:live_runtime_owner(args.ports[i],process.pid,lab.inventory()))
                    if initialization_hold:
                        initialization_hold.poll(monitor,lambda i:live_runtime_owner(args.ports[i],process.pid,lab.inventory()))
                    if install_hold:
                        install_hold.poll(monitor,lambda i:live_runtime_owner(args.ports[i],process.pid,lab.inventory()))
                    if recovery and hotplug_phase==0 and 'WS73_TARGET_RECOVERY_INJECT_READY' in text:
                        host_at_arm = live_runtime_owner(args.ports[0], process.pid, lab.inventory())
                        target={'path':'/machine/peripheral/ws73_0'}
                        if monitor.execute('qom-get',{**target,'property':'test-runtime-in-errors'})!=0:
                            raise ValueError('fresh injection counter required')
                        monitor.execute('qom-set',{**target,'property':'test-runtime-in-error-once','value':True})
                        if monitor.execute('qom-get',{**target,'property':'test-runtime-in-error-once'}) is not True:
                            raise ValueError('one-shot fault pulse did not arm')
                        m['fault_injection']={'method':'QMP_GUEST_TRANSPORT_ERROR_ONCE','guest_slot':0,
                                              'armed_wall_ns':time.time_ns(),'host_identity_at_arm':host_at_arm,'physical_acceptance':False,
                                              'automatic_fault_recovery_acceptance':False}
                        channel.sendall(b'recovery-injected\n');hotplug_phase=1
                    if timeout_seal is not None:
                        action=timeout_seal.feed(transcript)
                        if action:
                            channel.sendall(action)
                            m['graceful_timeout']['exit_sent_wall_ns']=time.time_ns()
                        m['graceful_timeout']['state']=timeout_seal.phase
                    if support and not support_input and 'WS73_TARGET_INPUT_READY' in text:
                        channel.sendall(b'target-ordinary-input\n');support_input=True
                    if (support and getattr(args,'hotplug',False)) or passthrough:
                        prefix='WS73_TARGET_PASSTHROUGH_' if passthrough else 'WS73_TARGET_CONTROL_'
                        acknowledgement='passthrough' if passthrough else 'support'
                        if hotplug_phase==0 and prefix+'REMOVE_READY' in text:
                            if daemon_remove:hold.before_remove(monitor)
                            monitor.execute('device_del',{'id':'ws73_0'});monitor.wait_deleted('ws73_0')
                            if daemon_remove:hold.after_remove(monitor)
                            channel.sendall((acknowledgement+'-remove\n').encode());hotplug_phase=1
                        if hotplug_phase==1 and prefix+'READD_READY' in text:
                            props=dict(driver='usb-ws73-test',id='ws73_0',bus='xhci.0',port='1',
                                       **{'runtime-discovery':True,'runtime-policy':True,'runtime-fresh-advertiser':True,'runtime-sle-subtypes':True,'runtime-medium':1},
                                       **({'runtime-zlp':True} if getattr(args,'empty_bulk',False) else {}),
                                       **{'runtime-idle-scan-stop':True}, **({'runtime-warm':True} if getattr(args,'warm',False) else {}))
                            if passthrough:props=usb_properties(args.ports[0],0)
                            monitor.execute('device_add',props)
                            if daemon_remove:hold.after_readd(props)
                            channel.sendall((acknowledgement+'-readd\n').encode());hotplug_phase=2
                    if early_fault:
                        if hotplug_phase==0 and 'WS73_TARGET_EARLY_FAULT_REMOVE_READY' in text:
                            monitor.execute('device_del',{'id':'ws73_2'});monitor.wait_deleted('ws73_2')
                            channel.sendall(b'early-fault-remove\n');hotplug_phase=1
                        if hotplug_phase==1 and 'WS73_TARGET_EARLY_FAULT_READD_READY' in text:
                            monitor.execute('device_add',usb_properties(args.ports[2],2))
                            channel.sendall(b'early-fault-readd\n');hotplug_phase=2
                    peer_metadata = False
                    if setup_gate and active == 1:
                        from ws73_management_setup import metadata_ready
                        peer_metadata = metadata_ready(share)
                    elif active_gate and active == 1:
                        from ws73_active_deadline import metadata_ready
                        peer_metadata = metadata_ready(share)
                    sibling_attach=sibling_business and active in(2,3)and(share/f'connected-file/sibling/attach-{active}.json').is_file()
                    if active<selected_count and (sibling_attach if sibling_business and active>=2 else peer_metadata if (setup_gate or active_gate) and active==1 else ('WS73_TARGET_CAPTURE_READY' if active==0 else f'WS73_TARGET_ADDRESS_SETUP: slot={active-1}' if runtime_addresses else f'WS73_TARGET_READY: slot={active-1}') in text):
                        props=(dict(driver='usb-ws73-test',id=f'ws73_{active}',bus='xhci.0',port=str(active+1),
                                    **{'runtime-discovery':True,'runtime-policy':True,'runtime-fresh-advertiser':True,'runtime-sle-subtypes':True,'runtime-medium':1},
                                    **({'runtime-zlp':True} if getattr(args,'empty_bulk',False) else {}),
                                       **{'runtime-idle-scan-stop':True}, **({'runtime-warm':True} if getattr(args,'warm',False) else {})) if support else usb_properties(args.ports[active],active))
                        monitor.execute('device_add',props);active+=1
                    if not support:
                        current={d['path']:d for d in lab.inventory()}
                        timeline.observe(current)
                        for index,port in enumerate(args.ports[:active]):
                            if passthrough and hotplug_phase==1 and index==0:continue
                            if early_fault and hotplug_phase==1 and index==2:continue
                            watcher.poll(index,port,current.get(port),process.pid,monitor)
                # Drain bytes already delivered when QEMU powers down.
                channel.setblocking(True);channel.settimeout(1)
                try:
                    while data:=channel.recv(65536):log.write(data);transcript.extend(data)
                except (TimeoutError,ConnectionResetError):pass
                m['qemu_exit']=process.returncode
                text=transcript.decode(errors='replace').replace('\r','')
                # Generic dracut uses terminal control sequences immediately
                # before switch-root output; they are not part of markers.
                text=re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', text)
                text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
                if process.returncode or 'WS73_TARGET_FAILURE:' in text or 'WS73_TARGET_FINISHED' not in text:raise ValueError('guest environment failed')
                if kernel_fault(text+(share/'kernel.log').read_text()):raise ValueError('kernel fault in environment')
                if 'native_vm' in package:
                    marker = 'WS73_TARGET_NATIVE_VM_ROOT: ' + package['native_vm']['release'] + ' NVMe/Btrfs signed-module'
                    if text.splitlines().count(marker) != 1 or text.splitlines().count('WS73_TARGET_NATIVE_VM_TAINT: '+('4096' if acb_probe else '0')) != 1:
                        raise ValueError('native module VM root/signature proof missing')
                    status = (share/'slkd-process-status.txt').read_text() if not channel_grant else ''
                    if not channel_grant and (not re.search(r'^Name:\s+slkd$', status, re.M)
                            or not re.search(r'^Uid:\s+0\s+0\s+0\s+0$', status, re.M)):
                        raise ValueError('native module VM daemon is not root')
                if early_fault:
                    from ws73_early_fault import corroborate as early_corroborate
                    record=json.loads((share/'early-bootstrap-fault/run.json').read_text())
                    if hotplug_phase!=2 or text.count('WS73_TARGET_EARLY_FAULT_PASS')!=1:raise ValueError('complete controlled target-only fault/remove/readd gate required')
                    identities=[*record['healthy_before'],record['failed_usb'],record['replacement']]
                    packets=check_capture_stats((share/'capture-stats.txt').read_text())
                    capture=read_capture(share/'ws73.pcap',[(r['bus'],r['device']) for r in identities])
                    if packets!=capture['packet_count']:raise ValueError('sealed capture count mismatch')
                    if file_record(HERE/'ws73_early_fault.py')!=m['early_bootstrap_verifier']:raise ValueError('early fault verifier changed')
                    m['early_bootstrap_corroboration']=early_corroborate(record,capture,share)
                    m['capture_packets']=packets;m['guest_identities']=identities
                    m['status']='REAL_EARLY_BOOTSTRAP_FAULT_ISOLATION_PASS'
                elif channel_death:
                    from ws73_channel_daemon_crash import corroborate as death_corroborate
                    record=json.loads((share/'channel-daemon-crash/control/run.json').read_text())
                    if text.count('WS73_TARGET_DAEMON_CHANNEL_PASS')!=1 or text.count('WS73_TARGET_DAEMON_CHANNEL_FINISHED')!=1 or record['daemon_channel']['index']!=channel_death_index:raise ValueError('explicit completed daemon fd death gate required')
                    identities=record['initial'];packets=check_capture_stats((share/'capture-stats.txt').read_text())
                    capture=read_capture(share/'ws73.pcap',[(r['bus'],r['device']) for r in identities])
                    if packets!=capture['packet_count']:raise ValueError('sealed capture count mismatch')
                    if record['fd_probe']['sha256']!=package['native_channel_fd_probe']['sha256']:raise ValueError('actual fd probe differs from staged client')
                    if record.get('daemon_restart_version')!=2:raise ValueError('pending WRITE restart version 2 required')
                    from ws73_ssap_sdk_write_provider import validate_tools as write_tools
                    write_tools(record['pending_write_restart']['tools'],args.prepared/'root',package['guest_files'])
                    for row in record['successor_business']['channel_socket']:
                        write_tools(row['ssap_sdk_write_provider_tools'],args.prepared/'root',package['guest_files'])
                    observed=[json.loads((share/f'ready-{slot}.json').read_text()) for slot in range(len(args.ports))]
                    m['physical_resource_allocation']['hcc_checks']=resources.hcc_profile_checks(
                        args.ports,physical_boundary.models,observed,identities)
                    m['channel_daemon_corroboration']=death_corroborate(record,capture)
                    if file_record(HERE/'ws73_ssap_daemon_restart.py')!=m['channel_daemon_write_verifier']:raise ValueError('WRITE restart verifier changed during run')
                    m['capture_packets']=packets;m['guest_identities']=identities
                    if file_record(HERE/'ws73_channel_daemon_crash.py')!=m['channel_daemon_verifier']:raise ValueError('daemon verifier changed during run')
                    m['status']='REAL_DAEMON_CHANNEL_DEATH_PASS'
                else:
                    if support and ('WS73_TARGET_SUPPORT: PASS' not in text or 'WS73_TARGET_INPUT_PASS: uid=1000 caps=0 tty=1' not in text):raise ValueError('synthetic environment support/input proof missing')
                    if not support and not passthrough and not recovery and not parallel and not channel_grant and 'WS73_TARGET_ENVIRONMENT_READY: physical_acceptance=0' not in text:raise ValueError('physical environment readiness missing')
                    if passthrough and 'WS73_TARGET_PASSTHROUGH_SUPPORT: PASS' not in text:raise ValueError('QMP passthrough proof missing')
                    if recovery and (hotplug_phase!=1 or 'WS73_TARGET_RECOVERY_SUPPORT: PASS' not in text):
                        raise ValueError('artificial transport recovery proof missing')
                    if parallel and ('WS73_TARGET_PARALLEL_BUSINESS: PASS' if business else 'WS73_TARGET_PARALLEL_RF: PASS') not in text:raise ValueError('four-device parallel USB proof missing')
                    if channel_grant:
                        from ws73_connected_file_gate import verify_records as verify_connected
                        probe=json.loads((share/'connected-file/run.json').read_text())
                        snapshots=verify_connected(probe)
                        identities=[dict(probe['usb'][n],index=n,generation=value.generation,
                            address=':'.join(f'{v:02X}' for v in value.address),path=f'1-{n+1}') for n,value in enumerate(snapshots)]
                    else:
                        identities=[json.loads((share/f'ready-{n}.json').read_text()) for n in range(selected_count)]
                    hcc_rows=list(probe['hcc_observations'])if channel_grant else []
                    if sibling_business:
                        from ws73_channel_sibling import identities as sibling_identities
                        identities+=sibling_identities(probe)
                        hcc_rows+=probe['sibling_business']['hcc_observations']
                    if physical_boundary:
                        observed=hcc_rows if channel_grant else identities
                        m['physical_resource_allocation']['hcc_checks']=resources.hcc_profile_checks(
                            args.ports,physical_boundary.models,observed,identities)
                    if getattr(args,'hotplug',False) or passthrough:
                        if hotplug_phase!=2:raise ValueError('both synthetic hotplug phases required')
                        pattern=r'^WS73_TARGET_PASSTHROUGH_(REMOVE|READD)_READY$' if passthrough else r'^WS73_TARGET_CONTROL_(REMOVE|READD)_READY$'
                        markers=re.findall(pattern,text,re.M)
                        if markers!=['REMOVE','READD']:raise ValueError('missing/duplicate/out-of-order synthetic control confirmations')
                        control=json.loads((share/('application/passthrough-control/run.json' if passthrough else 'application/support-control/run.json')).read_text())
                        identities=[*control['initial'],control['replacement']]
                        if passthrough and initializer_lifecycle != ('initialization_lifecycle' in control):
                            raise ValueError('initializer lifecycle request and control evidence must agree')
                    if recovery:
                        control=json.loads((share/'application/recovery-control/run.json').read_text())
                        identities=[*control['initial'],control['replacement']]
                        injection=(output/'qemu-stderr.log').read_text()
                        markers=re.findall(r'WS73_TEST_RUNTIME_IN_ERROR: dev (\d+):(\d+) ep 81 host_status=0 discarded_bytes=(\d+) injected_count=(\d+)',injection)
                        expected=m['fault_injection']['host_identity_at_arm']
                        if len(markers)!=1 or tuple(map(int,markers[0][:2]))!=(expected['bus'],expected['address']) or int(markers[0][2])<=0 or markers[0][3]!='1':
                            raise ValueError('exact one target-only artificial successful-host-transfer injection required')
                        trace=(output/'usb-lifecycle.log').read_text()
                        m['fault_injection']['initial_rom_closes'] = verify_recovery_lifecycle(
                            trace, m['fault_injection']['armed_wall_ns'], [devices[p] for p in args.ports])
                        m['fault_injection']['consumed_marker']=markers[0]
                    if channel_grant:
                        if text.count('WS73_TARGET_CHANNEL_GRANT_FINISHED')!=1:raise ValueError('standalone Grant finish proof missing')
                        control={}
                    packets=check_capture_stats((share/'capture-stats.txt').read_text())
                    capture=read_capture(share/'ws73.pcap',[(r['bus'],r['device']) for r in identities],observe_rx=sender_deadline or subscription_inflight)
                    if packets!=capture['packet_count']:raise ValueError('sealed capture packet count mismatch')
                    m['capture_packets']=packets;m['guest_identities']=identities
                    if runtime_addresses:
                        m.update(corroborate_runtime_addresses(share,capture,runtime_addresses,m['runtime_address_verifier']))
                    if parallel:
                        if business:
                            from ws73_parallel_data import corroborate as corroborate_parallel
                        else:
                            from ws73_parallel import corroborate as corroborate_parallel
                        control_path=share/('application/parallel-business/run.json' if business else 'application/parallel-control/run.json')
                        control=json.loads(control_path.read_text())
                        if business and control.get('burst_mode',False)!=parallel_burst:
                            raise ValueError('explicit burst request and actual guest scope disagree')
                        if business and control.get('disconnect_isolation',False)!=disconnect_isolation:
                            raise ValueError('explicit disconnect request and actual guest scope disagree')
                        if not business and control['second_pair_start_offset_ms']!=parallel_offset:
                            raise ValueError('guest start offset differs from actual requested diagnostic')
                        expectation = control['policy_expectation']
                        if (expectation['data'] != package['policy_expectation']['data']
                                or expectation['file']['sha256'] != package['policy_expectation']['guest_sha256']):
                            raise ValueError('actual parallel policy expectation differs from frozen preparation')
                        if business:
                            from ws73_channel_socket import validate_application_tools
                            validate_application_tools(control,args.prepared/'root',package['guest_files'])
                        if control.get('dynamic_benchmark_mode',False)is not parallel_benchmark:raise ValueError('explicit paired benchmark request/worker mismatch')
                        from ws73_parallel_data import benchmark_case
                        if benchmark_case(control)!=parallel_benchmark_case:raise ValueError('explicit paired benchmark case/worker mismatch')
                        if parallel_benchmark:
                            from ws73_socket_benchmark import validate_role_tools
                            for worker in control['workers']:validate_role_tools(worker['run'],args.prepared/'root',package['guest_files'])
                        if control.get('owned_ssap_mode',False)is not parallel_owned:raise ValueError('original Owned request and worker evidence mismatch')
                        if control.get('update_delivery_mode',False)is not parallel_delivery:raise ValueError('original protected delivery request/worker mismatch')
                        if control.get('shared_subscription_mode',False)is not parallel_subscription:raise ValueError('original shared subscription request/worker mismatch')
                        if parallel_subscription:
                            from ws73_parallel_data import subscription_case as parallel_case
                            if parallel_case(control)!=subscription_shared_case:raise ValueError('original shared lifetime request/worker mismatch')
                            from ws73_ssap_subscription import validate_tools as validate_subscription_tools,require_current_output
                            for worker in control['workers']:
                                data=worker['run']
                                if data['artifacts']['security_agent_probe']!=delivery_probe_identity(args.prepared/'root',package['guest_files']):raise ValueError('executed subscription Agent witness differs from sealed artifact')
                                for row in data['channel_socket']:
                                    require_current_output(row)
                                    validate_subscription_tools(row['ssap_subscription_tools'],args.prepared/'root',package['guest_files'])
                        if parallel_delivery:
                            from ws73_ssap_update_delivery import validate_tools as validate_update_tools
                            for worker in control['workers']:
                                data=worker['run']
                                if data['artifacts']['security_agent_probe']!=delivery_probe_identity(args.prepared/'root',package['guest_files']):raise ValueError('executed Agent witness differs from sealed artifact')
                                for row in data['channel_socket']:
                                    if type(row.get('ssap_update_delivery_output_contract_version'))is not int or row['ssap_update_delivery_output_contract_version']!=1:raise ValueError('current delivery requires original bounded pipe observations')
                                    validate_update_tools(row['ssap_update_delivery_tools'],args.prepared/'root',package['guest_files'])
                        m['parallel_corroboration']=corroborate_parallel(control,capture,**({'evidence':share}if parallel_subscription or parallel_benchmark else{}))
                        m['parallel_control']=file_record(control_path)
                    if daemon_remove:
                        from ws73_daemon_removal import corroborate as corroborate_removal
                        m['daemon_removal']['corroboration']=corroborate_removal(control['daemon_removal'],hold.record,capture,(output/'qemu-stderr.log').read_text(),hold.record['host_identity_at_arm'])
                        m['live_daemon_removal']=file_record(share/'application/passthrough-control/run.json')
                    if passthrough and connection_verify != ('connection_control' in control):
                        raise ValueError('explicit connection request and guest evidence must agree')
                    if connection_verify:
                        from ws73_connection_control import corroborate as connection_corroborate
                        if control['connection_control']['advertising_kind']!=connection_advertising:
                            raise ValueError('guest connection posture differs from explicit parent request')
                        m['connection_corroboration']=connection_corroborate(control,capture)
                        if control['connection_control'].get('connection_objects'):
                            from ws73_connection_objects import corroborate as object_corroborate
                            m['connection_object_corroboration']=object_corroborate(control,capture,m['connection_corroboration'])
                        from ws73_link_measurement import corroborate as measurement_corroborate
                        if control.get('link_measurements_requested',False)!=link_measurements:
                            raise ValueError('explicit link observation request/evidence mismatch')
                        measured=measurement_corroborate(control,capture,link_measurements)
                        if link_measurements:
                            if file_record(HERE/'ws73_link_measurement.py')!=m['link_measurement_verifier']:
                                raise ValueError('link observation verifier changed during run')
                            m['link_measurement_corroboration']=measured
                            m['link_measurement_acceptance']=True
                        from ws73_link_payload import corroborate as payload_corroborate
                        if control.get('link_payload_preference_requested')!=link_payload:
                            raise ValueError('link payload boot/request mismatch')
                        payload_proof=payload_corroborate(control,capture,link_payload)
                        if link_payload is not None:
                            if file_record(HERE/'ws73_link_payload.py')!=m['link_payload_preference_verifier']:
                                raise ValueError('link payload verifier changed during run')
                            m['link_payload_preference_corroboration']=payload_proof
                            m['link_payload_preference_acceptance']=True
                        if link_resync != ('link_resync' in control):raise ValueError('explicit link resync request/evidence mismatch')
                        if link_resync:
                            from ws73_link_resync import corroborate as resync_corroborate
                            m['link_resync_corroboration']=resync_corroborate(control,capture)
                    if native_return != ('native_return' in control):raise ValueError('Native return request/evidence mismatch')
                    if native_return:
                        from ws73_native_return import verify_root, corroborate as native_corroborate
                        verify_root(control,share,package['native_return_fixture']['library']['sha256'])
                        m['native_return_corroboration']=native_corroborate(control,capture)
                        m['native_return_acceptance']=True
                    if bool(native_controller) != ('native_controller_return' in control):raise ValueError('controller Native return request/evidence mismatch')
                    if native_controller:
                        from ws73_native_controller_return import corroborate as controller_corroborate
                        proof=controller_corroborate(control,capture,share,package['native_return_fixture']['library']['sha256'])
                        if proof['role'] != native_controller:raise ValueError('controller Native return role mismatch')
                        if proof['owner_probe_binary']['sha256'] != package['native_return_probe']['program']['sha256']:raise ValueError('actual owner probe differs from pinned prepared binary')
                        m['native_controller_return_corroboration']=proof
                        m['native_controller_return_acceptance']=True
                    if directory_events:
                        from ws73_controller_directory import corroborate_all as directory_corroborate
                        if text.count('WS73_TARGET_CONTROLLER_DIRECTORY_PASS')!=1:raise ValueError('root-reaped ordinary directory observer required')
                        if file_record(HERE/'ws73_controller_directory.py')!=m['controller_directory_verifier']:raise ValueError('directory verifier changed during run')
                        observed=json.loads((share/'controller-directory/result.json').read_text())
                        m['controller_directory_corroboration']=directory_corroborate(observed,control,m['controller_directory_program']['sha256'],m['controller_directory_verifier']['sha256'],m['controller_directory_clients'])
                        m['controller_directory_acceptance']=True
                    if ssap_initialization != ('ssap_initialization' in control):raise ValueError('SSAP initialization request/evidence mismatch')
                    if ssap_initialization:
                        from ws73_ssap_initialization import corroborate as initialize_corroborate, verify_fd_supervisor
                        verify_fd_supervisor(control,share)
                        m['ssap_initialization_corroboration']=initialize_corroborate(control,capture,m['ssap_initialization_hold'],(output/'qemu-stderr.log').read_text())
                        m['ssap_initialization_acceptance']=True
                    if bool(agent_mode) != ('security_agent' in control):raise ValueError('Agent request/evidence mismatch')
                    if agent_mode:
                        from ws73_security_agent import corroborate as agent_corroborate
                        if any(v['mode']!=agent_mode for v in control['security_agent']):raise ValueError('explicit Agent mode mismatch')
                        if agent_mode.startswith('cli-'):
                            from ws73_security_cli import validate_binary
                            validate_binary(control['slctl'],args.prepared/'root',package['guest_files'])
                        m['security_agent_corroboration']=agent_corroborate(control,capture)
                        if any(v.get('ssap_security_requirement',0)!=m.get('live_ssap_security_requirement',0) for v in control['security_agent']):raise ValueError('actual SMTC witness differs from frozen configuration')

                        if agent_mode=='install-cancel':
                            from ws73_security_install_hold import corroborate as install_corroborate
                            m['security_install_hold']['corroboration']=install_corroborate(m['security_install_hold'],control,capture,(output/'qemu-stderr.log').read_text())
                    if acb_probe != ('acb_transport_probe' in control):raise ValueError('explicit ACB probe request/evidence mismatch')
                    if acb_probe:
                        from ws73_acb_transport_probe import corroborate as acb_corroborate
                        m['acb_transport_selftest_corroboration']=acb_corroborate(control,capture,(share/'kernel.log').read_text())
                        m['expected_external_selftest_taint']=4096
                    if bool(benchmark_mode) != ('socket_benchmark' in control):raise ValueError('benchmark explicit request/evidence mismatch')
                    if benchmark_mode:
                        from ws73_socket_benchmark import corroborate as benchmark_corroborate,row_channel
                        from ws73_channel_socket import validate_application_tools
                        validate_application_tools(control,args.prepared/'root',package['guest_files'])
                        if any(r['config']!=benchmark_config for r in control['socket_benchmark']):raise ValueError('actual benchmark differs from exact requested workload')
                        if any(row_channel(r)!=benchmark_channel for r in control['socket_benchmark']):raise ValueError('actual benchmark differs from original channel target')
                        if any(benchmark_ssap.selected(r)!=benchmark_service for r in control['socket_benchmark']):raise ValueError('actual concurrent SSAP differs from original request')
                        m['socket_benchmark_corroboration']=benchmark_corroborate(control,capture,share)
                        from ws73_benchmark_timeline import check_xhci
                        m['socket_benchmark_xhci_observation']=check_xhci(share,benchmark_xhci,pressure=pressures_long(benchmark_channel))
                        if m['benchmark_verifiers']!=[file_record(HERE/name) for name in benchmark_verifier_names]:raise ValueError('benchmark verifier changed during execution')
                        from ws73_socket_benchmark import verify_role_artifacts,validate_role_tools,valid_role_supervision
                        validate_role_tools(control,args.prepared/'root',package['guest_files'])
                        m['socket_benchmark_role_supervision']=verify_role_artifacts(control,share)
                        if not valid_role_supervision(m['socket_benchmark_role_supervision']):raise ValueError('actual benchmark apps-only supervisor required')
                        if benchmark_service is not None:
                            if not benchmark_ssap.valid_summary(m['socket_benchmark_corroboration']):raise ValueError('actual SSAP/channel before-during-after and original SDK proofs required')
                            m['benchmark_ssap_acceptance']=True
                        m['socket_benchmark_apps_acceptance']=True
                        m['socket_benchmark_acceptance']=True
                    if channel_socket != ('channel_socket' in control):raise ValueError('explicit socket request/evidence mismatch')
                    if application_discovery != ('application_discovery' in control):raise ValueError('explicit application discovery request/evidence mismatch')
                    if application_discovery:
                        from ws73_application_discovery import corroborate as discovery_corroborate,verify_supervisor_artifacts
                        verifier=m['application_discovery_verifier']
                        if file_record(HERE/'ws73_application_discovery.py')!=verifier:raise ValueError('discovery verifier changed during run')
                        staged=args.prepared/'root/usr/share/sparklink/tools/ws73_application_discovery.py'
                        if file_record(staged)['sha256']!=verifier['sha256']:raise ValueError('staged discovery verifier differs from host')
                        from ws73_application_discovery import validate_tool
                        validate_tool(control['slctl'],args.prepared/'root',package['guest_files'])
                        expected=dict(path='/usr/share/sparklink/tools/ws73_application_discovery.py',sha256=verifier['sha256'])
                        m['application_discovery_supervision']=verify_supervisor_artifacts(control,share,expected)
                        m['application_discovery_corroboration']=discovery_corroborate(control,capture)
                        from ws73_application_discovery import case as discovery_case
                        if discovery_case(m['application_discovery_corroboration'])!=m['application_discovery_case']:
                            raise ValueError('original explicit discovery termination differs from actual evidence')
                        if m['application_discovery_case']=='sdk-release':
                            from ws73_application_discovery import validate_sdk_clients
                            for row in control['application_discovery']:
                                validate_sdk_clients(row['request']['clients'],args.prepared/'root',package['guest_files'])
                        if m['application_discovery_case']=='ttl':
                            from ws73_application_discovery import validate_probe
                            validate_probe(m['application_discovery_corroboration']['probe'],args.prepared/'root',package['guest_files'])
                            if m['application_discovery_corroboration']['probe']!=m['application_discovery_probe']:raise ValueError('original actual SDK probe identity changed')
                        m['application_discovery_acceptance']=True
                    if native_retry != ('native_event_retry' in control):raise ValueError('Native retry request/evidence differs')
                    if native_retry:
                        from ws73_native_event_retry import corroborate as retry_corroborate
                        m['native_event_retry_corroboration']=retry_corroborate(control,package)
                        m['native_event_retry_acceptance']=True
                    if application_clients != ('application_clients' in control):raise ValueError('explicit application client request/evidence mismatch')
                    if application_clients:
                        from ws73_application_client import corroborate as client_corroborate
                        if file_record(HERE/'ws73_application_client.py')!=m['application_client_verifier']:raise ValueError('application client verifier changed during execution')
                        from ws73_application_role import verify_supervisor_artifacts
                        if file_record(HERE/'ws73_application_role.py')!=m['application_role_verifier']:raise ValueError('application role verifier changed during execution')
                        m['application_role_supervision']=verify_supervisor_artifacts(control,share)
                        m['application_client_corroboration']=client_corroborate(control,capture)
                        for row in control['application_clients']:
                            for key in ['c','python','library']:
                                receipt=row['tools'][key];staged=args.prepared/'root'/receipt['path'].lstrip('/')
                                matches=[x for x in package['guest_files'] if x['path']==str(staged)]
                                if not staged.is_file() or len(matches)!=1 or matches[0]['sha256']!=receipt['sha256'] or file_record(staged)['sha256']!=receipt['sha256']:raise ValueError('application client differs from sealed image')
                        m['application_client_acceptance']=True
                    if channel_socket:
                        from ws73_channel_socket import corroborate as channel_corroborate
                        if any(row.get('message_bytes',61)!=channel_bytes or row.get('boundary_check',False)!=channel_boundaries for row in control['channel_socket']):raise ValueError('socket message size or boundary request differs from actual gate')
                        if any(row['rounds']!=channel_rounds for row in control['channel_socket']):raise ValueError('socket round count differs from explicit request')
                        if not all(row.get('channel_info_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires original capability receipts')
                        from ws73_channel_socket import validate_application_tools
                        binary=validate_application_tools(control,args.prepared/'root',package['guest_files'])
                        if any(row.get('application_tool')!=binary for row in control['channel_socket']):raise ValueError('channel applications must use same sealed slktest')
                        if update_delivery:
                            from ws73_ssap_update_delivery import validate_tools as validate_delivery_tools
                            if file_record(HERE/'ws73_ssap_update_delivery.py')!=m['ssap_update_delivery_verifier']:raise ValueError('delivery verifier changed during execution')
                            for row in control['channel_socket']:validate_delivery_tools(row['ssap_update_delivery_tools'],args.prepared/'root',package['guest_files'])
                        if subscription:
                            from ws73_ssap_subscription import validate_tools as validate_subscription_tools,verify_supervisor_artifacts,require_current_output
                            if file_record(HERE/'ws73_ssap_subscription.py')!=m['ssap_subscription_verifier']:raise ValueError('subscription verifier changed during run')
                            for row in control['channel_socket']:
                                require_current_output(row)
                                validate_subscription_tools(row['ssap_subscription_tools'],args.prepared/'root',package['guest_files'])
                            m['ssap_subscription_supervision']=verify_supervisor_artifacts(control,share)
                            from ws73_ssap_subscription import renewal_required
                            if any(renewal_required(row)!=subscription_renewal for row in control['channel_socket']):raise ValueError('renewal request/evidence mismatch')
                            from ws73_ssap_subscription import pressure_required,owner_loss_required,inflight_required,inflight_case,shared_required
                            if any(shared_required(row)!=subscription_shared or pressure_required(row)!=subscription_pressure or owner_loss_required(row)!=subscription_owner_loss or inflight_required(row)!=subscription_inflight or inflight_case(row)!=subscription_inflight_case for row in control['channel_socket']):raise ValueError('subscription scenario request/evidence mismatch')
                        if any(bool(row.get('ssap_subscription_required',False))!=subscription for row in control['channel_socket']):raise ValueError('subscription request/evidence mismatch')
                        if any(bool(row.get('ssap_update_delivery_required',False))!=update_delivery for row in control['channel_socket']):raise ValueError('update delivery request/evidence mismatch')
                        if owned_update and file_record(HERE/'ws73_ssap_owned_update.py')!=m['ssap_owned_update_verifier']:raise ValueError('owned update verifier changed during execution')
                        if any(bool(row.get('ssap_owned_update_required',False))!=owned_update for row in control['channel_socket']):raise ValueError('owned update request/evidence mismatch')
                        if any(bool(row.get('ssap_owner_lifecycle_required',False))!=owner_lifecycle for row in control['channel_socket']):raise ValueError('owner lifecycle request/evidence mismatch')
                        if owner_lifecycle and any(row.get('ssap_owner_publisher','cli')!=owner_publisher for row in control['channel_socket']):raise ValueError('owner publisher selector/evidence mismatch')
                        if any(bool(row.get('ssap_requester_lifecycle_required',False))!=requester_lifecycle for row in control['channel_socket']):raise ValueError('requester lifecycle request/evidence mismatch')
                        if any(bool(row.get('ssap_owned_required',False))!=ssap_owned for row in control['channel_socket']):raise ValueError('owned SSAP request/evidence mismatch')
                        if receive_lifecycle:
                            from ws73_ssap_receive_lifecycle import validate_prefixes,validate_coordination
                            if file_record(HERE/'ws73_ssap_receive_lifecycle.py')!=m['ssap_receive_lifecycle_verifier']:raise ValueError('receive lifecycle verifier changed during execution')
                            validate_prefixes(control['channel_socket'],share/'ws73.pcap')
                            validate_coordination(control['channel_socket'],m['ssap_receive_capture_observations'])
                        if any(bool(row.get('ssap_receive_lifecycle_required',False))!=receive_lifecycle for row in control['channel_socket']):raise ValueError('receive lifecycle request/evidence mismatch')
                        from ws73_ssap_command_policy import validate_rows as command_policy_rows
                        command_policy_rows(control['channel_socket'],command_policy)
                        from ws73_ssap_command_deadline import validate_rows as command_deadline_rows
                        command_deadline_rows(control['channel_socket'],command_deadline)
                        from ws73_ssap_description import validate_rows as description_rows
                        description_rows(control['channel_socket'],description)
                        from ws73_ssap_read_provider import validate_rows as provider_rows
                        provider_rows(control['channel_socket'],read_provider)
                        from ws73_ssap_sdk_read_provider import validate_rows as sdk_provider_rows
                        sdk_provider_rows(control['channel_socket'],sdk_read_provider)
                        from ws73_ssap_sdk_write_provider import validate_rows as sdk_write_provider_rows
                        sdk_write_provider_rows(control['channel_socket'],sdk_write_provider)
                        from ws73_ssap_write_unregister import validate_rows as write_unregister_rows
                        write_unregister_rows(control['channel_socket'],write_unregister)
                        from ws73_ssap_write_owner_exit import validate_rows as write_owner_exit_rows
                        write_owner_exit_rows(control['channel_socket'],write_owner_exit)
                        from ws73_ssap_write_down import validate_rows as write_down_rows
                        write_down_rows(control['channel_socket'],write_down)
                        from ws73_ssap_write_deadline import validate_rows as write_deadline_rows
                        write_deadline_rows(control['channel_socket'],write_deadline)
                        from ws73_ssap_provider_owner_exit import validate_rows as provider_exit_rows
                        provider_exit_rows(control['channel_socket'],provider_exit,version=m.get('ssap_provider_owner_exit_version'))
                        from ws73_ssap_provider_unregister import validate_rows as provider_unregister_rows
                        provider_unregister_rows(control['channel_socket'],provider_unregister)
                        from ws73_ssap_provider_deadline import validate_rows as provider_deadline_rows
                        provider_deadline_rows(control['channel_socket'],provider_deadline,version=provider_deadline_version if provider_deadline else None)
                        m['channel_socket_corroboration']=channel_corroborate(control,capture)
                        if read_provider:
                            from ws73_ssap_read_provider import valid_summary as provider_summary
                            from ws73_ssap_update_delivery import validate_tools as provider_tools
                            for row in control['channel_socket']:
                                provider_tools(row['ssap_read_provider_tools'],args.prepared/'root',package['guest_files'])
                            if file_record(HERE/'ws73_ssap_read_provider.py')!=m['ssap_read_provider_verifier'] or not provider_summary(m['channel_socket_corroboration'],version=m['ssap_read_provider_version']):
                                raise ValueError('exact original read provider verifier and paired SDK/USB evidence required')
                        m['ssap_read_provider_acceptance']=read_provider
                        if sdk_read_provider:
                            from ws73_ssap_sdk_read_provider import valid_summary as sdk_provider_summary,validate_tools as sdk_provider_tools
                            for row in control['channel_socket']:
                                sdk_provider_tools(row['ssap_sdk_read_provider_tools'],args.prepared/'root',package['guest_files'])
                            if (dict(file_record(HERE/'ws73_ssap_sdk_read_provider.py'),bytes=(HERE/'ws73_ssap_sdk_read_provider.py').stat().st_size)!=m['ssap_sdk_read_provider_verifier']
                                    or not sdk_provider_summary(m['channel_socket_corroboration'],version=m['ssap_sdk_read_provider_version'])):
                                raise ValueError('exact SDK Provider verifier and independent application/paired-USB evidence required')
                        m['ssap_sdk_read_provider_acceptance']=sdk_read_provider
                        if sdk_write_provider:
                            from ws73_ssap_sdk_write_provider import valid_summary as sdk_write_provider_summary,validate_tools as sdk_write_provider_tools
                            for row in control['channel_socket']:
                                sdk_write_provider_tools(row['ssap_sdk_write_provider_tools'],args.prepared/'root',package['guest_files'])
                            if (dict(file_record(HERE/'ws73_ssap_sdk_write_provider.py'),bytes=(HERE/'ws73_ssap_sdk_write_provider.py').stat().st_size)!=m['ssap_sdk_write_provider_verifier']
                                    or not sdk_write_provider_summary(m['channel_socket_corroboration'],version=m['ssap_sdk_write_provider_version'])):
                                raise ValueError('exact SDK Provider verifier and independent application/paired-USB evidence required')
                        m['ssap_sdk_write_provider_acceptance']=sdk_write_provider
                        if write_unregister:
                            from ws73_ssap_write_unregister import valid_summary as write_unregister_summary,validate_tools as write_unregister_tools
                            for row in control['channel_socket']:
                                write_unregister_tools(row['ssap_write_provider_unregister_tools'],args.prepared/'root',package['guest_files'])
                            if (dict(file_record(HERE/'ws73_ssap_write_unregister.py'),bytes=(HERE/'ws73_ssap_write_unregister.py').stat().st_size)!=m['ssap_write_provider_unregister_verifier']
                                    or not write_unregister_summary(m['channel_socket_corroboration'],version=m['ssap_write_provider_unregister_version'])):
                                raise ValueError('exact SDK Provider verifier and independent application/paired-USB evidence required')
                        if write_owner_exit:
                            from ws73_ssap_write_owner_exit import valid_summary as write_owner_exit_summary,validate_tools as write_owner_exit_tools
                            for row in control['channel_socket']:
                                write_owner_exit_tools(row['ssap_write_provider_owner_exit_tools'],args.prepared/'root',package['guest_files'])
                            if (dict(file_record(HERE/'ws73_ssap_write_owner_exit.py'),bytes=(HERE/'ws73_ssap_write_owner_exit.py').stat().st_size)!=m['ssap_write_provider_owner_exit_verifier']
                                    or not write_owner_exit_summary(m['channel_socket_corroboration'],version=m['ssap_write_provider_owner_exit_version'])):
                                raise ValueError('exact SDK Provider verifier and independent application/paired-USB evidence required')
                        if write_down:
                            from ws73_ssap_write_down import valid_summary as write_down_summary,validate_tools as write_down_tools
                            for row in control['channel_socket']:
                                write_down_tools(row['ssap_write_provider_down_tools'],args.prepared/'root',package['guest_files'])
                            if (dict(file_record(HERE/'ws73_ssap_write_down.py'),bytes=(HERE/'ws73_ssap_write_down.py').stat().st_size)!=m['ssap_write_provider_down_verifier']
                                    or not write_down_summary(m['channel_socket_corroboration'],version=m['ssap_write_provider_down_version'])):
                                raise ValueError('exact SDK Provider verifier and independent application/paired-USB evidence required')
                        m['ssap_write_provider_unregister_acceptance']=write_unregister
                        m['ssap_write_provider_owner_exit_acceptance']=write_owner_exit
                        m['ssap_write_provider_down_acceptance']=write_down
                        if write_deadline:
                            from ws73_ssap_write_deadline import valid_summary as write_deadline_summary,validate_tools as write_deadline_tools
                            for row in control['channel_socket']:
                                write_deadline_tools(row['ssap_write_provider_deadline_tools'],args.prepared/'root',package['guest_files'])
                            if (dict(file_record(HERE/'ws73_ssap_write_deadline.py'),bytes=(HERE/'ws73_ssap_write_deadline.py').stat().st_size)!=m['ssap_write_provider_deadline_verifier']
                                    or not write_deadline_summary(m['channel_socket_corroboration'],version=m['ssap_write_provider_deadline_version'])):
                                raise ValueError('exact SDK Provider verifier and independent application/paired-USB evidence required')
                        m['ssap_write_provider_deadline_acceptance']=write_deadline
                        if provider_exit:
                            from ws73_ssap_provider_owner_exit import valid_summary as provider_exit_summary
                            from ws73_ssap_sdk_read_provider import validate_tools as sdk_exit_tools
                            for row in control['channel_socket']:
                                sdk_exit_tools(row['ssap_provider_owner_exit_tools'],args.prepared/'root',package['guest_files'])
                            if file_record(HERE/'ws73_ssap_provider_owner_exit.py')!=m['ssap_provider_owner_exit_verifier'] or not provider_exit_summary(m['channel_socket_corroboration'],version=m['ssap_provider_owner_exit_version']):
                                raise ValueError('exact original Provider owner-exit verifier and paired application/USB evidence required')
                        m['ssap_provider_owner_exit_acceptance']=provider_exit
                        if provider_unregister:
                            from ws73_ssap_provider_unregister import valid_summary as provider_unregister_summary
                            from ws73_ssap_sdk_read_provider import validate_tools as sdk_unregister_tools
                            for row in control['channel_socket']:
                                sdk_unregister_tools(row['ssap_provider_unregister_tools'],args.prepared/'root',package['guest_files'])
                            if file_record(HERE/'ws73_ssap_provider_unregister.py')!=m['ssap_provider_unregister_verifier'] or not provider_unregister_summary(m['channel_socket_corroboration']):
                                raise ValueError('exact original SDK pending unregister verifier and paired application/USB evidence required')
                        m['ssap_provider_unregister_acceptance']=provider_unregister
                        if provider_deadline:
                            from ws73_ssap_provider_deadline import valid_summary as provider_deadline_summary
                            from ws73_ssap_sdk_read_provider import validate_tools as deadline_tools
                            for row in control['channel_socket']:
                                deadline_tools(row['ssap_provider_deadline_tools'],args.prepared/'root',package['guest_files'])
                            if file_record(HERE/'ws73_ssap_provider_deadline.py')!=m['ssap_provider_deadline_verifier'] or not provider_deadline_summary(m['channel_socket_corroboration'],version=provider_deadline_version):
                                raise ValueError('exact original Provider deadline verifier and paired SDK/terminal/USB evidence required')
                        m['ssap_provider_deadline_acceptance']=provider_deadline
                        if description:
                            from ws73_ssap_description import valid_summary as description_summary
                            from ws73_ssap_update_delivery import validate_tools as description_tools
                            for row in control['channel_socket']:
                                description_tools(row['ssap_description_tools'],args.prepared/'root',package['guest_files'])
                            if file_record(HERE/'ws73_ssap_description.py')!=m['ssap_description_verifier'] or not description_summary(m['channel_socket_corroboration']):
                                raise ValueError('exact original description verifier and paired SDK/USB evidence required')
                        m['ssap_description_acceptance']=description
                        from ws73_ssap_command import validate_rows as command_rows,valid_summary as command_summary,validate_tools as command_tools
                        command_rows(control['channel_socket'],write_command)
                        if write_command:
                            for row in control['channel_socket']:
                                command_tools(row['ssap_write_command_tools'],args.prepared/'root',package['guest_files'])
                            if file_record(HERE/'ws73_ssap_command.py')!=m['ssap_write_command_verifier'] or not command_summary(m['channel_socket_corroboration']):
                                raise ValueError('exact Write Command verifier and both-end read/owner evidence required')
                        m['ssap_write_command_acceptance']=write_command
                        if command_policy:
                            from ws73_ssap_command_policy import valid_summary as command_policy_summary
                            for row in control['channel_socket']:
                                command_tools(row['ssap_command_policy_tools'],args.prepared/'root',package['guest_files'])
                            if file_record(HERE/'ws73_ssap_command_policy.py')!=m['ssap_command_policy_verifier'] or not command_policy_summary(m['channel_socket_corroboration']):
                                raise ValueError('exact command policy verifier and original deny/allow evidence required')
                        m['ssap_command_policy_acceptance']=command_policy
                        if command_deadline:
                            from ws73_ssap_command_deadline import valid_summary as command_deadline_summary
                            for row in control['channel_socket']:
                                command_tools(row['ssap_command_deadline_tools'],args.prepared/'root',package['guest_files'])
                            if file_record(HERE/'ws73_ssap_command_deadline.py')!=m['ssap_command_deadline_verifier'] or not command_deadline_summary(m['channel_socket_corroboration']):
                                raise ValueError('exact original command deadline and ordinary business evidence required')
                        m['ssap_command_deadline_acceptance']=command_deadline
                        if any(bool(row.get('ssap_sender_deadline_required',False))!=sender_deadline for row in control['channel_socket']):raise ValueError('sender deadline request/evidence mismatch')
                        if sender_deadline and any(row.get('ssap_sender_lifecycle_case','deadline')!=m['ssap_sender_lifecycle_case']for row in control['channel_socket']):raise ValueError('sender lifecycle case/evidence mismatch')
                        if sender_deadline:
                            from ws73_ssap_sender_deadline import valid_summary as sender_summary,corroborate_holds,validate_prefixes as sender_prefixes
                            if file_record(HERE/'ws73_ssap_sender_deadline.py')!=m['ssap_sender_deadline_verifier'] or not sender_summary(m['channel_socket_corroboration']):raise ValueError('exact sender deadline verifier and two-ended proof required')
                            sender_prefixes(m['ssap_sender_deadline_hold'],share/'ws73.pcap')
                            m['ssap_sender_deadline_corroboration']=corroborate_holds(m['ssap_sender_deadline_hold'],control,capture,(output/'qemu-stderr.log').read_text())
                        m['ssap_sender_deadline_acceptance']=sender_deadline
                        if any(bool(row.get('ssap_value_lengths_required',False))!=value_lengths for row in control['channel_socket']):raise ValueError('SSAP lengths request/evidence mismatch')
                        if value_lengths:
                            from ws73_ssap_update_delivery import validate_tools as validate_read_tools
                            for row in control['channel_socket']:validate_read_tools(row['ssap_read_limit_tools'],args.prepared/'root',package['guest_files'])
                            from ws73_ssap_value import valid_length_summary
                            if file_record(HERE/'ws73_ssap_value.py')!=m['ssap_value_lengths_verifier'] or not valid_length_summary(m['channel_socket_corroboration'],expected_version=4):raise ValueError('exact SSAP length verifier and complete evidence required')
                        m['ssap_value_lengths_acceptance']=value_lengths
                        m['ssap_receive_lifecycle_acceptance']=receive_lifecycle
                        if update_delivery:
                            from ws73_ssap_update_delivery import valid_summary as valid_delivery
                            if not valid_delivery(m['channel_socket_corroboration'],expected_version=m['ssap_update_delivery_contract_version']):raise ValueError('exact prepared update delivery version/length closure required')
                        if subscription:
                            from ws73_ssap_subscription import valid_summary as valid_subscription
                            if not valid_subscription(m['channel_socket_corroboration']):raise ValueError('complete continuous subscription proof required')
                            from ws73_ssap_subscription import valid_snapshot_supervision
                            if not valid_snapshot_supervision(m['ssap_subscription_supervision']):raise ValueError('complete closed local snapshot proof required')
                            if subscription_renewal:
                                from ws73_ssap_subscription import valid_renewal_summary,valid_renewal_supervision
                                if not valid_renewal_summary(m['channel_socket_corroboration'])or not valid_renewal_supervision(m['ssap_subscription_supervision']):raise ValueError('actual renewal and post-original-expiry closure required')
                            if subscription_pressure:
                                from ws73_ssap_subscription import valid_pressure_summary,valid_pressure_supervision
                                if not valid_pressure_summary(m['channel_socket_corroboration'])or not valid_pressure_supervision(m['ssap_subscription_supervision']):raise ValueError('actual full queue/drain/checked resume closure required')
                            if subscription_owner_loss:
                                from ws73_ssap_subscription import valid_owner_loss_summary,valid_owner_loss_supervision
                                if not valid_owner_loss_summary(m['channel_socket_corroboration'])or not valid_owner_loss_supervision(m['ssap_subscription_supervision']):raise ValueError('actual reader death,paired cleanup/read barrier and fresh lease replies required')
                            if subscription_inflight:
                                from ws73_ssap_subscription import valid_inflight_summary,valid_inflight_supervision
                                from ws73_ssap_sender_deadline import corroborate_holds,validate_prefixes
                                if file_record(HERE/'ws73_ssap_sender_deadline.py')!=m['ssap_subscription_inflight_verifier']:raise ValueError('in-flight physical verifier changed during run')
                                if not valid_inflight_summary(m['channel_socket_corroboration'],case=subscription_inflight_case)or not valid_inflight_supervision(m['ssap_subscription_supervision'],case=subscription_inflight_case):raise ValueError('actual in-flight release/discard and fresh-lease replies required')
                                validate_prefixes(m['ssap_subscription_inflight_hold'],share/'ws73.pcap')
                                cases=[row['ssap_subscription'][0]['leases'][1]['inflight_release']for row in control['channel_socket']]
                                m['ssap_subscription_inflight_corroboration']=corroborate_holds(m['ssap_subscription_inflight_hold'],control,capture,(output/'qemu-stderr.log').read_text(),cases=cases,purpose='subscription-'+subscription_inflight_case)
                        if subscription_shared:
                            from ws73_ssap_subscription import valid_shared_summary,valid_shared_supervision
                            from ws73_ssap_shared import configuration_wire
                            if file_record(HERE/'ws73_ssap_shared.py')!=m['ssap_subscription_shared_verifier']or not valid_shared_summary(m['channel_socket_corroboration'],case=subscription_shared_case)or not valid_shared_supervision(m['ssap_subscription_supervision'],case=subscription_shared_case):raise ValueError('exact shared owner/application/cleanup proofs required')
                            m['ssap_subscription_shared_wire']=configuration_wire(control,capture)
                        m['ssap_subscription_shared_acceptance']=subscription_shared
                        m['ssap_subscription_acceptance']=subscription
                        m['ssap_subscription_renewal_acceptance']=subscription_renewal
                        m['ssap_subscription_pressure_acceptance']=subscription_pressure
                        m['ssap_subscription_owner_loss_acceptance']=subscription_owner_loss
                        m['ssap_subscription_inflight_release_acceptance']=subscription_inflight and subscription_inflight_case=='release'
                        if subscription_inflight_case=='expiry':m['ssap_subscription_inflight_expiry_acceptance']=True
                        m['ssap_update_delivery_acceptance']=update_delivery
                        m['ssap_owned_update_acceptance']=owned_update
                        m['ssap_owned_acceptance']=ssap_owned
                        m['ssap_owner_lifecycle_acceptance']=owner_lifecycle
                        m['ssap_requester_lifecycle_acceptance']=requester_lifecycle
                        if not all(row.get('tx_status_required') is True for row in control['channel_socket']):raise ValueError('current gate requires actual TX-budget snapshots')
                        m['ordinary_channel_tx_status_acceptance']=True
                        m['ordinary_channel_info_acceptance']=True
                        if not all(row.get('ssap_exchange_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires real SMTC ExchangeInfo')
                        from ws73_ssap_initialization import exchange_contract
                        if any(row.get('ssap_exchange_contract',1)!=exchange_contract(package)for row in control['channel_socket']):raise ValueError('actual SSAP exchange differs from prepared source contract')
                        m['ssap_exchange_info_acceptance']=True
                        if not all(row.get('ssap_value_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires actual SSAP values')
                        m['ssap_value_acceptance']=True
                        if not channel_close and not channel_burst:
                            if not all(row.get('ssap_access_required') is True for row in control['channel_socket']):raise ValueError('current normal socket gate requires original per-attribute access evidence')
                            m['ssap_access_acceptance']=True
                        if not all(row.get('ssap_read_uuid_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires actual ReadByUUID values')
                        m['ssap_read_uuid_acceptance']=True
                        if not all(row.get('ssap_update_local_rejection_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires unsupported local update capability refusal')
                        from ws73_ssap_value import validate_update_rejections, UPDATE_REJECTION_VERSION
                        for row in control['channel_socket']:validate_update_rejections(row,expected_version=UPDATE_REJECTION_VERSION)
                        m['ssap_local_update_rejection_acceptance']=True
                        if not all(row.get('ssap_discovery_required') is True for row in control['channel_socket']):raise ValueError('current socket gate requires actual SSAP discovery')
                        m['ssap_discovery_acceptance']=True
                        if any(row.get('close_prefix',False)!=channel_close for row in control['channel_socket']):raise ValueError('prefix-close request and original evidence disagree')
                        if any(row.get('burst',False)!=channel_burst for row in control['channel_socket']):raise ValueError('burst request and original evidence disagree')
                        m['ordinary_software_backpressure_acceptance']=channel_burst
                        m['ordinary_prefix_close_acceptance']=channel_close
                        m['ordinary_channel_socket_acceptance']=not channel_close
                    if fairness != ('channel_fairness' in control):raise ValueError('concurrent channel request and original evidence disagree')
                    if fairness:
                        from ws73_channel_fairness import corroborate as fairness_corroborate
                        m['channel_fairness_corroboration']=fairness_corroborate(control,capture)
                        if file_record(HERE/'ws73_channel_fairness.py')!=m['channel_fairness_verifier']:raise ValueError('concurrent channel verifier changed during execution')
                        m['channel_fairness_acceptance']=True
                    if dynamic_channels != ('dynamic_channels' in control):raise ValueError('dynamic request and original evidence disagree')
                    if dynamic_channels:
                        from ws73_dynamic_channels import corroborate as dynamic_corroborate
                        m['dynamic_channel_corroboration']=dynamic_corroborate(control,capture)
                        expected_status='DYNAMIC_BASIC_CHANNEL_BURST_CREDIT_SCOPED_PASS' if dynamic_burst else 'DYNAMIC_BASIC_TWO_CHANNEL_USB_AND_APPLICATION_SCOPED_PASS' if dynamic_long is None else 'DYNAMIC_BASIC_CHANNEL_LONG_AND_SLOT_BOUND_SCOPED_PASS'
                        if m['dynamic_channel_corroboration']['status']!=expected_status or (dynamic_long is not None and m['dynamic_channel_corroboration'].get('long_bytes')!=dynamic_long):raise ValueError('original dynamic workload and requested long size disagree')
                        if dynamic_burst and any(p.get('post_close_drain',{}).get('status')!='POST_CLOSE_NATIVE_TERMINAL_AND_DEBT_ZERO_CORROBORATED' for p in m['dynamic_channel_corroboration']['proofs']):raise ValueError('current dynamic burst requires explicit post-close Native observation')
                        m['dynamic_channel_acceptance']=True
                    if daemon_crash != (share/'daemon-crash/run.json').exists():
                        raise ValueError('explicit daemon crash request and evidence must agree')
                    if daemon_crash:
                        crash_record=json.loads((share/'daemon-crash/run.json').read_text())
                        old_pid=crash_record['phases'][0]['pid']
                        if re.findall(r'^WS73_TARGET_DAEMON_CRASH_EXIT: pid=(\d+) status=(\d+)$',text,re.M)!=[(str(old_pid),'137')]:
                            raise ValueError('actual guest SIGKILL/reap console evidence required')
                        if re.findall(r'^WS73_TARGET_DAEMON_CRASH_PHASE: (\w+)$',text,re.M)!=['before','free','after']:
                            raise ValueError('ordered actual guest crash phases required')
                        from ws73_daemon_crash import corroborate as crash_corroborate
                        m['daemon_crash_corroboration']=crash_corroborate(json.loads((share/'daemon-crash/run.json').read_text()),control,capture)
                    if service_policy != (share/'service-policy/run.json').exists():raise ValueError('explicit service-role request/evidence mismatch')
                    if service_policy:
                        from ws73_ssap_service_policy import corroborate as service_policy_corroborate
                        m['ssap_service_policy_corroboration']=service_policy_corroborate(json.loads((share/'service-policy/run.json').read_text()),control)
                        m['ssap_service_policy_acceptance']=True
                    if observer_policy != (share/'observer-policy/run.json').exists():
                        raise ValueError('explicit observer policy request and evidence must agree')
                    if observer_policy:
                        from ws73_observer_policy import corroborate as observer_corroborate
                        policy_record=json.loads((share/'observer-policy/run.json').read_text())
                        m['observer_policy_corroboration']=observer_corroborate(policy_record,control,capture)
                    if initializer_lifecycle:
                        from ws73_initialization_lifecycle import corroborate_wire as initializer_wire
                        m['initializer_lifecycle_corroboration']=initializer_wire(control,capture)
                    if setup_gate:
                        from ws73_management_setup import corroborate as corroborate_setup
                        probe=json.loads((share/'setup-release/run.json').read_text())
                        m['setup_release_corroboration']=corroborate_setup(probe,capture)
                        m['live_setup_release']=file_record(share/'setup-release/run.json')
                    if connected_case:
                        from ws73_connected_file_gate import corroborate as connected_corroborate
                        probe=json.loads((share/'connected-file/run.json').read_text())
                        if channel_grant and not channel_directions and not probe.get('channel_grant',{}).get('tx_constraint_required'):raise ValueError('current lifecycle gate requires original typed TX intents')
                        if bool(probe.get('channel_grant',{}).get('directional',False))!=channel_directions:raise ValueError('requested directional Grant gate mismatch')
                        if bool(probe.get('channel_grant',{}).get('scm_rights',False))!=channel_scm_rights:raise ValueError('requested SCM_RIGHTS Grant gate mismatch')
                        if bool(probe.get('channel_grant'))!=channel_grant:raise ValueError('requested real channel Grant gate mismatch')
                        if probe.get('channel_security_requirement',0)!=protected:raise ValueError('requested protected Grant cannot downgrade')
                        if bool(probe.get('channel_grant',{}).get('revoke_prefix'))!=channel_revoke_prefix:raise ValueError('requested actual revoke-prefix gate mismatch')
                        if probe.get('channel_grant',{}).get('queued_discard_contract_version')!=(1 if queued_discard else None):raise ValueError('requested queued-discard profile mismatch')
                        if channel_link_down and not probe.get('prefix_hold',{}).get('primed',False):raise ValueError('requested primed-debt physicalDown barrier missing')
                        if bool(probe.get('data_link_down'))!=channel_link_down:raise ValueError('requested direct physical Down gate mismatch')
                        if bool(probe.get('prefix_hold'))!=(channel_revoke_prefix and not channel_deadline):raise ValueError('requested causal incomplete-PDU barrier missing or unexpected')
                        if channel_revoke_prefix and file_record(HERE/'ws73_channel_prefix_hold.py')!=m['prefix_hold_verifier']:raise ValueError('prefix barrier verifier changed during run')
                        if channel_revoke_prefix and probe.get('data_deadline'if channel_deadline else'prefix_hold',{}).get('geometry',{}).get('version')!=1:raise ValueError('requested actual reported-buffer geometry missing')
                        if bool(probe.get('data_deadline'))!=channel_deadline:raise ValueError('requested original PDU deadline gate mismatch')
                        if probe.get('channel_grant',{}).get('intent_phase_contract_version')!=(2 if channel_deadline else None):raise ValueError('requested live/retired intent phases mismatch')
                        if bool(probe.get('unauthenticated_encryption',False))!=encryption:raise ValueError('explicit installation gate mismatch')
                        if bool(probe.get('security_original_deadline',False))!=original_deadline:raise ValueError('original security deadline gate mismatch')
                        if bool(probe.get('security_cancel_pending',False))!=cancel_pending:raise ValueError('passive cancellation gate mismatch')
                        if probe.get('numeric_comparison')!=numeric:raise ValueError('requested original-author numeric mode mismatch')
                        if bool(probe.get('key_agreement',False))!=key_agreement:raise ValueError('requested candidate key agreement gate mismatch')
                        if bool(probe.get('security_capabilities'))!=security_capabilities:raise ValueError('requested limited security capability gate mismatch')
                        if channel_revoke_prefix and file_record(HERE/'ws73_revoke_prefix.py')!=m['revoke_prefix_verifier']:raise ValueError('revoke-prefix verifier changed during run')
                        if probe['case']!=connected_case or probe['index']!=connected_index or probe.get('reply_hold')!=connected_reply or bool(probe.get('link_snapshot_gate'))!=link_snapshot or bool(probe.get('peer_binding_gate'))!=peer_binding:raise ValueError('connected File request mismatch')
                        m['connected_file_corroboration']=connected_corroborate(probe,capture,hold.record if connected_reply or channel_revoke_prefix else None,
                            (output/'qemu-stderr.log').read_text() if connected_reply or channel_revoke_prefix else None,hold.record['host_identity_at_arm'] if connected_reply or channel_revoke_prefix else None)
                        if ('sibling_business'in probe)is not sibling_business:raise ValueError('requested sibling-business evidence mismatch')
                        if sibling_business:
                            from ws73_channel_sibling import valid_summary
                            if not valid_summary(m['connected_file_corroboration'].get('sibling_business',{}),victim_index=connected_index):raise ValueError('complete sibling-business proof required')
                            m['channel_sibling_business_acceptance']=True
                        if bool(probe.get('session_idle'))!=session_idle:raise ValueError('requested Session idle observation mismatch')
                        if session_idle:
                            from ws73_session_idle import corroborate as idle_corroborate
                            if file_record(HERE/'ws73_session_idle.py')!=m['session_idle_verifier']:raise ValueError('Session idle verifier changed during run')
                            m['session_idle_observation']=idle_corroborate(probe,share)
                        m['live_connected_file']=file_record(share/'connected-file/run.json')
                    if partial_gate:
                        from ws73_management_partial import corroborate as corroborate_partial
                        if resource_recreation:
                            from ws73_resource_file_gate import corroborate as corroborate_partial
                        probe=json.loads((share/'managed-partial/run.json').read_text())
                        if probe.get('selected_domain_cleanup',False) is not selected_cleanup:raise ValueError('actual selected-domain cleanup must match requested gate')
                        if probe.get('real_later_step',False) is not real_later or probe.get('initialization_step',0)!=(real_step if real_later else 0):raise ValueError('actual later selected step mismatch')
                        if probe.get('ordinary_queue_eviction',False) is not ordinary_eviction:raise ValueError('actual ordinary queue gate mismatch')
                        if probe.get('active_ready_peer',False) is not ready_peer:raise ValueError('actual Ready peer must match requested gate')
                        if probe.get('scan_parameter_cleanup',False) is not parameter_cleanup:raise ValueError('actual scan parameter cleanup must match requested gate')
                        m['managed_partial_hold']['corroboration']=corroborate_partial(probe,hold.record,capture,(output/'qemu-stderr.log').read_text(),hold.record['host_identity_at_arm'])
                        m['live_managed_partial']=file_record(share/'managed-partial/run.json')
                    if daemon_hold:
                        from ws73_daemon_hold import corroborate as corroborate_daemon
                        control=json.loads((share/'application/recovery-control/run.json').read_text())
                        record=control['daemon_hold']
                        if record.get('case')!=daemon_hold:raise ValueError('actual daemon held caller case mismatch')
                        m['daemon_hold']['corroboration']=corroborate_daemon(record,hold.record,capture,(output/'qemu-stderr.log').read_text(),hold.record['host_identity_at_arm'])
                        m['live_daemon_hold']=file_record(share/'application/recovery-control/run.json')
                    if queued_gate:
                        from ws73_management_queued import corroborate as corroborate_queued
                        probe=json.loads((share/'managed-queue/run.json').read_text())
                        if probe.get('ready_peer',False) is not queue_peer:raise ValueError('actual Ready queue peer selector mismatch')
                        if probe.get('connection_queue',False) is not queue_connections:raise ValueError('actual native connection queue request mismatch')
                        m['managed_queue_corroboration']=corroborate_queued(probe,capture)
                        m['live_managed_queue']=file_record(share/'managed-queue/run.json')
                    if active_gate:
                        from ws73_active_deadline import corroborate
                        probe=json.loads((share/'active-deadline/run.json').read_text())
                        if ('last_file_close' in probe) != active_close_gate:
                            raise ValueError('actual close evidence must match requested gate')
                        m['active_deadline_hold']['corroboration']=corroborate(
                            probe,hold.record,capture,(output/'qemu-stderr.log').read_text(),
                            (share/'kernel.log').read_text(),identities[0],identities[1],hold.record['host_identity_at_arm'])
                        m['live_active_deadline']=file_record(share/'active-deadline/run.json')
                    if event_copy:
                        from ws73_event_copy_probe import verify_cases
                        probe=json.loads((share/'application/event-copy/run.json').read_text())
                        if probe.get('status')!='LIVE_EVENT_COPY_PASS' or probe.get('probe_exit')!=0:
                            raise ValueError('live copy probe failure')
                        verify_cases(probe['cases'])
                        if (probe['daemon_before']!=probe['daemon_after'] or
                                probe['daemon_after']!=control['daemon_before'] or
                                probe['bus_before']!=probe['bus_after'] or
                                probe['bus_after']!=control['bus_before']):
                            raise ValueError('copy and RF gates require the same daemon/bus owner')
                        m['live_event_copy']=file_record(share/'application/event-copy/run.json')
                    if diagnostic:
                        from ws73_diagnostic_probe import verify_records
                        probe=json.loads((share/'diagnostic/run.json').read_text())
                        if probe.get('status')!='DIAGNOSTIC_RESULT_LIVE_PASS' or probe.get('probe_exit')!=0:
                            raise ValueError('live diagnostic probe failure')
                        if (probe.get('format_version') != (7 if autonomous_gate else 6 if deadline_gate else 5 if cancellation else 4)
                                or probe.get('cancellation_requested',False) is not cancellation
                                or probe.get('deadline_requested',False) is not deadline_gate
                                or probe.get('autonomous_requested',False) is not autonomous_gate
                                or probe.get('admission_copyout_requested') is not True
                                or probe.get('admission_eviction_requested') is not True
                                or probe.get('legacy_poll_copy_requested') is not True):
                            raise ValueError('current live diagnostic admission gate required')
                        verify_records(probe['records'], admission=True, eviction=True, legacy_poll=True,cancellation=cancellation,deadline=deadline_gate,autonomous=autonomous_gate)
                        if cancellation:
                            if not hold or not hold.record['complete'] or probe.get('host_hold_acknowledgements') != hold.record['observations']:
                                raise ValueError('actual host hold and matching guest acknowledgments required')
                            from ws73_diagnostic_hold import corroborate_host_hold
                            from ws73_capture import corroborate_diagnostic
                            _,cancel_proofs=corroborate_diagnostic(control,capture,probe)
                            m['diagnostic_hold']['corroboration']=corroborate_host_hold(
                                hold.record,probe,cancel_proofs,(output/'qemu-stderr.log').read_text(),hold.record['host_identity_at_arm'])
                        if len(probe['cli_queries'])!=4:
                            raise ValueError('actual diagnostic CLI query gates missing')
                        m['live_diagnostic']=file_record(share/'diagnostic/run.json')
                    m['empty_bulk_completions']=len(capture['empty_bulk_completions'])
                    if getattr(args,'empty_bulk',False) and not all(any((e['bus'],e['device'])==(r['bus'],r['device']) for e in capture['empty_bulk_completions']) for r in identities):
                        raise ValueError('successful empty bulk completions missing from either selected USB identity')
                    if daemon_remove:
                        # Re-read the final serialized record, not the live coordinator:
                        # later qualification must not erase/mutate earlier evidence.
                        from ws73_daemon_removal import verify_sealed_record
                        verify_sealed_record(control['daemon_removal'],m['daemon_removal'],capture,(output/'qemu-stderr.log').read_text())
                    m['status']='FOUR_DEVICE_PARALLEL_DYNAMIC_BENCHMARK_PASS'if parallel_benchmark else 'FOUR_DEVICE_PARALLEL_SHARED_SUBSCRIPTION_PASS'if parallel_subscription else 'FOUR_DEVICE_PARALLEL_UPDATE_DELIVERY_PASS'if parallel_delivery else 'FOUR_DEVICE_PARALLEL_OWNED_SSAP_PASS'if parallel_owned else 'FOUR_DEVICE_PARALLEL_BURST_PASS' if parallel_burst else 'FOUR_DEVICE_DISCONNECT_ISOLATION_PASS' if disconnect_isolation else 'FOUR_DEVICE_PARALLEL_BUSINESS_PASS' if business else 'REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS' if agent_mode else 'REAL_NUMERIC_COMPARISON_MECHANISM_PASS' if numeric else 'REAL_SECURITY_ORIGINAL_DEADLINE_PASS' if original_deadline else 'REAL_PASSIVE_AUTHOR_CANCEL_PASS' if cancel_pending else 'REAL_UNAUTHENTICATED_LINK_ENCRYPTION_PASS' if encryption else 'REAL_CANDIDATE_KEY_AGREEMENT_PASS' if key_agreement else 'REAL_LIMITED_SECURITY_CAPABILITIES_PASS' if security_capabilities else 'REAL_CHANNEL_ORIGINAL_DEADLINE_PREFIX_PASS' if channel_deadline else 'REAL_CHANNEL_LINK_DOWN_PREFIX_PASS' if channel_link_down else 'REAL_CHANNEL_GRANT_PASS' if channel_grant else ('FOUR_DEVICE_PARALLEL_RF_CONTRAST_PASS' if parallel_offset else 'FOUR_DEVICE_PARALLEL_RF_PASS') if parallel else 'FAULT_RECOVERY_SUPPORT_PASS' if recovery else 'PASSTHROUGH_SUPPORT_PASS' if passthrough else 'SUPPORT_PASS' if support else 'ENVIRONMENT_FINISHED'
                    if timeout_seal is not None:
                        m['graceful_timeout']['state']='SEALED'
                        m['status']='FAIL'
                        m['error']='environment timeout; capture sealed; physical control not accepted'
        if agent_mode and agent_mode.startswith('cli-') and file_record(HERE/'ws73_security_cli.py')!=m['security_cli_verifier']:
            raise ValueError('CLI witness changed during execution')
        if agent_mode and file_record(HERE/'ws73_security_agent.py')!=m['security_agent_verifier']:
            raise ValueError('Agent verifier changed during run')
        if business and file_record(HERE/'ws73_parallel_data.py')!=m['parallel_business_verifier']:
            raise ValueError('parallel business verifier changed during run')
        if parallel and file_record(HERE/'ws73_parallel.py')!=m['parallel_verifier']:
            raise ValueError('parallel verifier changed during run')
        prepared(args.prepared.resolve())
        if session_service:
            if m['status'] not in ['PASSTHROUGH_SUPPORT_PASS','REAL_CHANNEL_GRANT_PASS','REAL_CHANNEL_LINK_DOWN_PREFIX_PASS','REAL_CHANNEL_ORIGINAL_DEADLINE_PREFIX_PASS']:
                raise ValueError('Session observation cannot replace failed original real gate')
            from ws73_session_service import corroborate as service_corroborate
            control_path=share/('connected-file/run.json' if channel_grant else 'application/passthrough-control/run.json')
            m['session_service_observation']=service_corroborate(json.loads(control_path.read_text()),capture,share)
            if m.get('session_service_collector_profile')!=m['session_service_observation'].get('collector_profile'):
                raise ValueError('actual Session collector profile must match original request')
            if m['session_service_verifiers']!=[file_record(HERE/name) for name in ['ws73_session_service.py','ws73_trace_layout.py']]:
                raise ValueError('Session observation verifier changed during execution')
            m['session_service_acceptance']=True

        if queue_peer and file_record(HERE/'ws73_management_queue_ready_peer.py')!=m['managed_queue_ready_peer_verifier']:
            raise ValueError('Ready queue peer verifier changed during run')
        if queued_gate and file_record(HERE/'ws73_management_queued.py')!=m['managed_queue_verifier']:
            raise ValueError('Managed queue verifier changed during run')
        if real_later and file_record(HERE/'ws73_host_later_hold.py')!=m['managed_real_later_verifier']:
            raise ValueError('actual later host verifier changed during run')
        if daemon_remove and file_record(HERE/'ws73_daemon_removal.py')!=m['daemon_removal_verifier']:
            raise ValueError('daemon removal verifier changed during run')
        if daemon_hold and file_record(HERE/'ws73_daemon_hold.py')!=m['daemon_hold_verifier']:
            raise ValueError('daemon held verifier changed during run')
        if daemon_crash and file_record(HERE/'ws73_daemon_crash.py')!=m['daemon_crash_verifier']:
            raise ValueError('daemon crash verifier changed during run')
        if service_policy and file_record(HERE/'ws73_ssap_service_policy.py')!=m['ssap_service_policy_verifier']:raise ValueError('service-role verifier changed during run')
        if observer_policy and file_record(HERE/'ws73_observer_policy.py')!=m['observer_policy_verifier']:
            raise ValueError('observer policy verifier changed during run')
        if initializer_lifecycle and file_record(HERE/'ws73_initialization_lifecycle.py')!=m['initializer_lifecycle_verifier']:
            raise ValueError('initializer lifecycle verifier changed during run')
        if ordinary_eviction and file_record(HERE/'ws73_management_eviction.py')!=m['managed_eviction_verifier']:
            raise ValueError('ordinary queue verifier changed during run')
        if ready_peer and file_record(HERE/'ws73_management_ready_peer.py')!=m['managed_ready_peer_verifier']:
            raise ValueError('Ready peer verifier changed during run')
        if sibling_business and file_record(HERE/'ws73_channel_sibling.py')!=m['sibling_verifier']:raise ValueError('sibling verifier changed during run')
        if channel_grant and file_record(HERE/'ws73_channel_grant.py')!=m['channel_grant_verifier']:raise ValueError('channel Grant verifier changed during run')
        if channel_link_down and file_record(HERE/'ws73_channel_link_down.py')!=m['channel_link_down_verifier']:raise ValueError('direct Down verifier changed during run')
        if channel_deadline and file_record(HERE/'ws73_channel_deadline.py')!=m['channel_deadline_verifier']:raise ValueError('original deadline verifier changed during run')
        if cancel_pending and file_record(HERE/'ws73_security_cancel.py')!=m['security_cancel_verifier']:raise ValueError('passive cancel verifier changed during run')
        if numeric and [file_record(HERE/name) for name in ['ws73_security_numeric.py','ws73_key_agreement.py']]!=m['security_numeric_verifiers']:raise ValueError('numeric mechanism verifiers changed during run')
        if key_agreement and file_record(HERE/'ws73_key_agreement.py')!=m['security_key_agreement_verifier']:raise ValueError('candidate key agreement verifier changed during run')
        if protected and m['protected_security_verifiers']!=[file_record(HERE/name) for name in ['ws73_protected_grant.py','ws73_security_capabilities.py','ws73_security_numeric.py','ws73_key_agreement.py']]:raise ValueError('protected prelude verifier changed during execution')
        if security_capabilities and file_record(HERE/'ws73_security_capabilities.py')!=m['security_capabilities_verifier']:raise ValueError('limited capability verifier changed during run')
        if connected_case and file_record(HERE/'ws73_native_pair.py')!=m['native_pair_verifier']:raise ValueError('Native pair verifier changed during run')
        if connected_case and file_record(HERE/'ws73_connected_file_gate.py')!=m['connected_file_verifier']:
            raise ValueError('connected File verifier changed during run')
        if resource_recreation and file_record(HERE/'ws73_resource_file_gate.py')!=m['managed_resource_verifier']:
            raise ValueError('resource File verifier changed during run')
        if partial_gate and file_record(HERE/'ws73_management_partial.py')!=m['managed_partial_verifier']:
            raise ValueError('Managed partial verifier changed during run')
        if setup_gate and file_record(HERE/'ws73_management_setup.py')!=m['setup_release_verifier']:
            raise ValueError('Setup release verifier changed during run')
        if active_gate and file_record(HERE/'ws73_active_deadline.py')!=m['active_deadline_verifier']:
            raise ValueError('active deadline host verifier changed during run')
        if file_record(args.prepared.resolve()/'manifest.json')!=m['prepared_manifest']:raise ValueError('prepared manifest changed during run')
    except (Exception,KeyboardInterrupt) as error:
        m['status']='FAIL';m['error']=str(error) or type(error).__name__
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        if process is not None:m['qemu_exit']=process.returncode
        if partial_rx is not None:
            from ws73_usb_partial_diagnostic import finalize as finalize_partial_rx
            try:
                targets={(m['inventory_before'][p]['bus'],m['inventory_before'][p]['address'])for p in args.ports}
                finalize_partial_rx(m['usb_partial_rx_diagnostic'],(output/'qemu-stderr.log').read_text(),targets)
            except (ValueError,KeyError,OSError,TypeError,StopIteration)as error:
                m['usb_partial_rx_diagnostic'].update(status='DIAGNOSTIC_UNPROVED',complete=False,error=str(error))
        if monitor:monitor.close()
        if channel:channel.close()
        m['guest_files']=[file_record(p) for p in sorted((output/'guest-output').rglob('*')) if p.is_file() and not p.is_symlink()] if (output/'guest-output').exists() else []
        m['inventory_after']={d['path']:d for d in lab_module().inventory()}
        timeline.observe(m['inventory_after'], 'final')
        m['host_timeline']=file_record(output/'host-inventory.jsonl')
        m['host_lifecycle_files']=[file_record(output/name) for name in
            ['usb-lifecycle.events', 'usb-lifecycle.log'] if (output/name).is_file()]
        if (output/'root.btrfs').is_file():
            m['vm_disk_after'] = file_record(output/'root.btrfs')
        if not support:
            try:
                if m['firmware_evidence_helpers'] != [file_record(HERE/name) for name in FIRMWARE_EVIDENCE_HELPERS]:
                    raise ValueError('firmware evidence helper changed during execution')
                m['firmware_evidence'] = firmware_evidence.observe_run(
                    output/'guest-output', args.prepared.resolve(), args.ports, package,
                    m['physical_resource_allocation'])
            except Exception as error:
                # Failure is evidence unavailability, never a synthetic read
                # or upload. Preserve an earlier production failure unchanged.
                m['firmware_evidence'] = dict(version=1, result='UNPROVED',
                    error=str(error) or type(error).__name__, selected_ports=list(args.ports),
                    cold_power_verified=False, executing_firmware_attested=False)
        m['finished_at']=datetime.now(timezone.utc).isoformat();write_json(output/'manifest.json',m)
    code=run_exit_code(m, supervisor_pending=True, expected_firmware_mode=firmware_mode)
    m['supervisor_exit']=code
    if code and m['status']!='FAIL':
        if not firmware_evidence.exit_gate(m):
            m['behavior_status_before_firmware_gate'] = m['status']
            m['physical_acceptance'] = False
        m['status']='FAIL';m['error']='terminal success status lacks required corroborated exit contract'
    write_json(output/'manifest.json',m)
    print(m['status'],output/'manifest.json')
    return code


def validate_runtime_address_guest(root, package, verifier):
    """Reject a retained pre-journal guest before its first physical mutation."""
    path = root/'usr/share/sparklink/tools/ws73_runtime_address.py'
    if path.is_symlink() or not path.is_file():
        raise ValueError('current frozen address helper required')
    actual = file_record(path)
    pins = [row for row in package['guest_files'] if row['path'] == str(path)]
    if pins != [actual] or actual['sha256'] != verifier['sha256']:
        raise ValueError('prepared address helper differs from current originals contract')


def corroborate_runtime_addresses(share, capture, addresses, verifier):
    """Add address evidence only; never replace the remaining run verdict.

    Caller supplies the decoded, count-checked shared capture. Freeze the JSON
    bytes actually verified and recheck the source pin before publishing any
    metadata. No status, acceptance or supervisor completion is awarded here.
    """
    from ws73_runtime_address import check_originals, corroborate
    path = share/'runtime-address/run.json'
    raw = path.read_bytes()
    record = json.loads(raw)
    originals = check_originals(path.parent, record)
    proof = list(corroborate(record, capture, addresses).values())
    evidence = file_record(path)
    if path.stat().st_size != len(raw) or evidence['sha256'] != hashlib.sha256(raw).hexdigest():
        raise ValueError('address record changed during corroboration')
    if file_record(HERE/'ws73_runtime_address.py') != verifier:
        raise ValueError('address verifier changed during run')
    if check_originals(path.parent, record) != originals:
        raise ValueError('original address evidence changed during corroboration')
    return dict(runtime_address_corroboration=proof, runtime_address_record=evidence,
                runtime_address_originals_record=originals)


def delivery_probe_identity(root,guest_files):
    path=root/'bin/ws73-security-agent-probe'
    if path.is_symlink()or not path.is_file():raise ValueError('exact staged security witness required')
    expected=file_record(path)
    if expected not in guest_files:raise ValueError('security witness differs from sealed root')
    return dict(path='/bin/ws73-security-agent-probe',sha256=expected['sha256'])


def require_delivery_preparation(package,path):
    if type(package.get('four_delivery_contract_version'))is not int or package['four_delivery_contract_version']!=1:
        raise ValueError('protected delivery requires freshly matched preparation')
    root=path/'root'
    for name in ['ws73_parallel_data.py','ws73_channel_socket.py','ws73_connection_control.py','ws73_security_agent.py','ws73_ssap_update_delivery.py','ws73_ssap_owned.py','ws73_dynamic_channels.py']:
        if file_record(root/'usr/share/sparklink/tools'/name)['sha256']!=file_record(HERE/name)['sha256']:
            raise ValueError('protected delivery source mismatch: '+name)
    entry=root/'init'
    if entry.is_symlink()or not entry.is_file()or not entry.stat().st_mode&0o111 or file_record(entry)['sha256']!=file_record(HERE/'ws73_target_init.sh')['sha256']:
        raise ValueError('protected delivery requires current executable init')
    import tomllib
    level=tomllib.loads((root/'etc/sparklink/main.conf').read_text()).get('ssap',{}).get('channel_security',0)
    if type(level)is not int or level!=2:raise ValueError('protected delivery requires frozen level2 SMTC config')
    witness=delivery_probe_identity(root,package['guest_files'])
    if witness['sha256']!=package.get('native_security_agent_probe',{}).get('sha256'):
        raise ValueError('security witness must retain exact compiled artifact identity')
    verifier=package.get('native_verification_openssl',{})
    if verifier.get('guest_path')!='/usr/bin/openssl'or type(verifier.get('validation_exit'))is not int or verifier['validation_exit']!=0 or not verifier.get('files'):
        raise ValueError('explicit validated guest CMAC oracle required')
    if [r['sha256']for r in verifier['files']if r['guest_path']=='/usr/bin/openssl']!=[verifier.get('source',{}).get('sha256')]:
        raise ValueError('exact validated OpenSSL binary must be in guest closure')
    for row in verifier['files']:
        entry=firmware_profile.inside(root,Path(row['guest_path'].lstrip('/')))
        actual=file_record(entry)
        if actual['sha256']!=row['sha256']or actual not in package['guest_files']:
            raise ValueError('guest CMAC oracle closure differs from sealed inputs')


def require_benchmark_preparation(package,path,*,case='parallel'):
    if type(case)is not str or case not in ('parallel','close-short','pressure'):raise ValueError('explicit supported four benchmark case required')
    if case=='close-short'and(type(package.get('four_dynamic_benchmark_close_contract_version'))is not int or package['four_dynamic_benchmark_close_contract_version']!=1):
        raise ValueError('short close requires fresh four benchmark close contract1')
    if case=='pressure'and(type(package.get('four_dynamic_benchmark_pressure_contract_version'))is not int or package['four_dynamic_benchmark_pressure_contract_version']!=1):
        raise ValueError('software pressure requires fresh four benchmark pressure contract1')
    if type(package.get('four_dynamic_benchmark_contract_version'))is not int or package['four_dynamic_benchmark_contract_version']!=1:
        raise ValueError('four dynamic benchmark requires fresh explicit preparation')
    from ws73_socket_benchmark import validate_role_sources
    validate_role_sources(package,dynamic=True,parallel=True)
    for name in ['ws73_parallel_data.py','ws73_parallel.py','ws73_connection_control.py','ws73_trace_layout.py']:
        if file_record(path/'root/usr/share/sparklink/tools'/name)['sha256']!=file_record(HERE/name)['sha256']:
            raise ValueError('four benchmark preparation/source mismatch: '+name)
    entry=path/'root/init'
    if entry.is_symlink()or not entry.is_file()or not entry.stat().st_mode&0o111 or file_record(entry)['sha256']!=file_record(HERE/'ws73_target_init.sh')['sha256']:
        raise ValueError('four benchmark requires current executable VM init')


def require_subscription_preparation(package,path,*,case='release'):
    if type(package.get('four_subscription_contract_version'))is not int or package['four_subscription_contract_version']!=1:
        raise ValueError('shared subscriptions require explicit current preparation')
    if type(case)is not str or case not in ('release','expiry','owner-exit','pressure'):raise ValueError('explicit supported four-pair shared case required')
    field='four_subscription_pressure_contract_version'if case=='pressure'else'four_subscription_lifetime_contract_version'
    if case!='release'and(type(package.get(field))is not int or package[field]!=1):raise ValueError('selected shared case requires fresh preparation')
    require_delivery_preparation(package,path)
    for name in ['ws73_ssap_subscription.py','ws73_ssap_shared.py','ws73_role_snapshot.py','ws73_application_role.py','ws73_target_guest.py']:
        if file_record(path/'root/usr/share/sparklink/tools'/name)['sha256']!=file_record(HERE/name)['sha256']:
            raise ValueError('shared subscription source mismatch: '+name)


def require_owned_preparation(package,path):
    if type(package.get('four_owned_contract_version'))is not int or package['four_owned_contract_version']!=1:
        raise ValueError('Owned SSAP requires freshly matched explicit preparation')
    for name in ['ws73_parallel_data.py','ws73_ssap_owned.py','ws73_channel_socket.py','ws73_dynamic_channels.py']:
        if file_record(path/'root/usr/share/sparklink/tools'/name)['sha256']!=file_record(HERE/name)['sha256']:
            raise ValueError('Owned SSAP preparation/source mismatch: '+name)
    entry=path/'root/init'
    if entry.is_symlink()or not entry.is_file()or not entry.stat().st_mode&0o111 or file_record(entry)['sha256']!=file_record(HERE/'ws73_target_init.sh')['sha256']:
        raise ValueError('Owned SSAP requires current executable VM init')


def validate_business_mode(args):
    # Dedicated positive gate: never silently combine injection, RF diagnostics
    # or two-device options with a four-controller business qualification.
    case=getattr(args,'four_device_benchmark_case','parallel')
    if (type(case)is not str or case not in ('parallel','close-short','pressure')or case!='parallel'and not getattr(args,'four_device_dynamic_benchmark',False)
            or args.command!='run' or sum(bool(getattr(args,k,False)) for k in ['four_device_business','four_device_disconnect','four_device_burst','four_device_owned','four_device_update_delivery','four_device_shared_subscription','four_device_dynamic_benchmark'])!=1
            or any(v for k,v in vars(args).items()
            if isinstance(v,bool) and k not in ['four_device_business','four_device_disconnect','four_device_burst','four_device_owned','four_device_update_delivery','four_device_shared_subscription','four_device_dynamic_benchmark'])
            or getattr(args,'parallel_start_offset_ms',0)
            or any(getattr(args,k,None) for k in ['security_agent','daemon_hold_case',
                'managed_partial_case','managed_connected_case','managed_connected_reply',
                'managed_real_later_step'])
            or getattr(args,'connection_advertising','fixed-t')!='fixed-t'
            or getattr(args,'channel_socket_bytes',61)!=61
            or getattr(args,'channel_socket_rounds',4)!=4):
        raise ValueError('four-device business requires dedicated real VM without other gates')


def valid_parallel_benchmark(record):
    """Only the dedicated complete four-pair contract can accept this scope."""
    from ws73_parallel_data import verify_records,benchmark_parallel_proof,benchmark_case,benchmark_case_from_boot,benchmark_channel,BENCHMARK_SCOPE
    try:
        if (record.get('status')!='FOUR_DEVICE_PARALLEL_DYNAMIC_BENCHMARK_PASS'
                or record.get('scope')!=BENCHMARK_SCOPE
                or type(record.get('four_dynamic_benchmark_contract_version'))is not int
                or record['four_dynamic_benchmark_contract_version']!=1
                or record.get('four_device_dynamic_benchmark_requested')is not True
                or record.get('four_device_parallel_business')is not True
                or record.get('four_device_parallel_rf')is not False
                or any(record.get(k,False)is not False for k in ['four_device_disconnect_requested','four_device_burst_requested','four_device_owned_requested','four_device_update_delivery_requested','four_device_shared_subscription_requested'])
                or record.get('qemu_exit')!=0):return False
        case=record.get('four_benchmark_case','parallel')
        if type(case)is not str or case not in ('parallel','close-short','pressure')or 'four_benchmark_case'in record and case=='parallel':return False
        close=case=='close-short';pressure=case=='pressure'
        if pressure:
            if type(record.get('four_dynamic_benchmark_pressure_contract_version'))is not int or record['four_dynamic_benchmark_pressure_contract_version']!=1:return False
        elif 'four_dynamic_benchmark_pressure_contract_version'in record:return False
        if close:
            if type(record.get('four_dynamic_benchmark_close_contract_version'))is not int or record['four_dynamic_benchmark_close_contract_version']!=1:return False
        elif 'four_dynamic_benchmark_close_contract_version'in record:return False
        words=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()]
        if benchmark_case_from_boot(words)!=case:return False
        for token in ['ws73.parallel=1','ws73.parallel_business=1','ws73.parallel_benchmark=1','ws73.socket_benchmark_apps=1']:
            key=token.split('=')[0]
            if [w for w in words if w==key or w.startswith(key+'=')]!=[token]:return False
        if any(w.startswith(('ws73.parallel_burst=','ws73.parallel_disconnect=','ws73.parallel_owned=','ws73.parallel_delivery=','ws73.parallel_subscription=','ws73.benchmark_'))for w in words):return False
        proof=record['parallel_corroboration'];control=proof['parallel_benchmark_control'];owners=verify_records(control)
        if benchmark_case(control)!=case:return False
        if close:
            if proof.get('channel_close_isolation_acceptance')is not True:return False
        elif 'channel_close_isolation_acceptance'in proof:return False
        if pressure:
            if proof.get('software_backpressure_acceptance')is not True:return False
        elif 'software_backpressure_acceptance'in proof:return False
        if type(proof.get('parallel_benchmark_contract_version'))is not int or proof['parallel_benchmark_contract_version']!=1:return False
        if len(owners)!=4 or proof.get('status')!='FOUR_REAL_PARALLEL_DYNAMIC_BENCHMARK_CORROBORATED':return False
        if proof['dynamic_benchmark']!=benchmark_parallel_proof(proof['pairs'],control):return False
        from ws73_benchmark_timeline import verify_paired_trace
        verify_paired_trace(control,proof['paired_trace'])
        from ws73_socket_benchmark import parallel_replies
        replies=parallel_replies(benchmark_channel(control))
        for k,v in dict(controller_count=4,round_trips=2*replies,ordinary_uid=1004,coordinator_uid=1000,dynamic_channel_acceptance=True,fixed_basic_channel_business_acceptance=False,performance_qualified=False,fairness_acceptance=False,controller_credit_correctness_proof=False,fault_isolation_acceptance=False,automatic_fault_recovery_acceptance=False,protected_ssap_acceptance=False,full_goal_complete=False).items():
            if type(proof.get(k))is not type(v)or proof[k]!=v:return False
        overlaps=proof['overlaps']
        if len(overlaps)!=2:return False
        from ws73_parallel_data import overlap_window
        for phase,overlap in enumerate(overlaps):
            if overlap['role_phase']!=phase or overlap['overlap_wall_ns']!=overlap_window(overlap['business_windows']):return False
            expected=[]
            for pair in proof['pairs']:
                legs=pair['channel']['proofs'][phase]['legs']
                if len(legs)!=replies or len(pair['connections'])!=2:return False
                window=[min(v['tx']['wall_ns']for v in legs),max(v['rx']['wall_ns']for v in legs)]
                steps=pair['connections'][phase]['steps']
                if max(v['wall_ns']for v in steps[0]['outcomes'])>window[0]or min(v['wall_ns']for v in steps[1]['outcomes'])<window[1]:return False
                expected.append(window)
            if expected!=overlap['business_windows']:return False
        return True
    except(CaptureError,KeyError,TypeError,ValueError,IndexError,AttributeError):return False


def valid_parallel_burst(proof):
    if not all(proof.get(k) is True for k in ['long_pdu_acceptance','software_backpressure_acceptance',
            'observed_controller_pool_saturation_and_resumption']):return False
    if any(proof.get(k) is not False for k in ['controller_credit_correctness_proof','fairness_acceptance']):return False
    if len(proof.get('pairs',[]))!=2:return False
    for pair in proof['pairs']:
        if pair['channel'].get('credit_exhaustion_acceptance') is not False:return False
        if (pair['channel'].get('long_pdu_acceptance') is not True
                or pair['channel'].get('software_backpressure_acceptance') is not True):return False
        observations=pair.get('budget_observations',[])
        if len(observations)!=2:return False
        for n,obs in enumerate(observations):
            if obs.get('phase')!=n or obs.get('source_pool_refusals_delta',0)<=0 or len(obs.get('endpoints',[]))!=2:return False
            owners=pair['channel']['proofs'][n].get('owners',[])
            if len(owners)!=2:return False
            for endpoint,entry in zip(obs['endpoints'],owners):
                owner,obj=entry['owner'],entry['object']
                if any(endpoint.get(k)!=v for k,v in dict(controller=owner['index'],generation=owner['generation'],lifetime=obj['lifetime'],handle=obj['handle'],capacity=owner['buffers'][1]).items()):return False
                if (not 0<endpoint.get('capacity',0)==endpoint.get('wire_peak')
                    or endpoint.get('wire_final_debt')!=0
                    or type(endpoint.get('usb_submissions')) is not int or not 0<endpoint['usb_submissions']==endpoint.get('nocp_packets')
                    or not endpoint.get('full_nocp_resume_intervals')):return False
    return True


def run_exit_code(record, *, supervisor_pending=False, expected_firmware_mode=None):
    from ws73_native_event_retry import accepted as retry_accepted
    if not retry_accepted(record):return 1
    # One finalization contract for every mode, not just SSAP lifecycle gates.
    # _run alone computes its result before writing supervisor_exit. A saved
    # record without that receipt cannot be interpreted as a completed PASS.
    # A deliberately canceled USB observation can never qualify the original
    # unmodified application/recovery gate, even if some workloads completed.
    if 'usb_partial_rx_diagnostic_requested'in record:
        return 1
    if type(supervisor_pending) is not bool:
        return 1
    from ws73_link_payload import exit_gate as payload_exit_gate
    if not payload_exit_gate(record):
        return 1
    from ws73_link_measurement import exit_gate as measurement_exit_gate
    if not measurement_exit_gate(record):
        return 1
    if not firmware_evidence.exit_gate(record, expected_firmware_mode):
        return 1
    if not firmware_profile.exit_gate(record):
        return 1
    from ws73_lab_resources import board_configuration_exit_gate
    if not board_configuration_exit_gate(record):
        return 1
    if 'supervisor_exit' in record:
        if type(record['supervisor_exit']) is not int or record['supervisor_exit'] != 0:
            return 1
    elif not supervisor_pending:
        return 1
    if type(record.get('qemu_exit')) is not int or record['qemu_exit'] != 0:
        return 1
    # These summaries are reconstructed from raw evidence during _run. Saved
    # reports must retain them as well; a PASS label is not their replacement.
    addresses=record.get('runtime_addresses_requested')
    address_tokens=[v for arg in record.get('qemu_args',[]) if isinstance(arg,str) for v in arg.split() if v.startswith('ws73.runtime_addresses=')]
    if addresses is not None:
        from ws73_runtime_address import parse_addresses
        try:addresses=parse_addresses(addresses)
        except (ValueError,TypeError):return 1
        if (address_tokens!=['ws73.runtime_addresses='+','.join(addresses)] or
                len(record.get('runtime_address_corroboration',[]))!=2 or
                not record.get('runtime_address_record') or not record.get('runtime_address_verifier')):return 1
        originals=record.get('runtime_address_originals_record')
        if (not isinstance(originals,dict) or set(originals)!={'path','sha256'}
                or not isinstance(originals['path'],str) or Path(originals['path']).name!='originals.json'
                or not isinstance(originals['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',originals['sha256'])):return 1
    elif address_tokens or record.get('runtime_address_corroboration'):return 1
    connection=record.get('connection_verify_requested',False)
    channel=record.get('channel_socket_verification_requested',False)
    prefix=record.get('channel_socket_close_prefix_requested',False)
    if any(type(v) is not bool for v in [connection,channel,prefix]):return 1
    early=record.get('early_bootstrap_fault_requested',False)
    death=record.get('channel_daemon_crash_requested',False)
    if type(early)is not bool or type(death)is not bool or early and death:return 1
    if early or death:
        # Dedicated modes have their own actual corroborators and scopes, but
        # still require the common firmware/board/QEMU/supervisor contract.
        if addresses is not None or connection or channel or prefix:return 1
        if early:
            proof=record.get('early_bootstrap_corroboration',{})
            valid=(record.get('status')=='REAL_EARLY_BOOTSTRAP_FAULT_ISOLATION_PASS'
                and isinstance(proof,dict) and set(proof)=={'during_fault','after_retry'})
            if valid:
                for case in proof.values():
                    if not isinstance(case,dict):return 1
                    data=case.get('data',{});links=case.get('connection')
                    if (not isinstance(links,list) or len(links)!=2 or any(not isinstance(p,dict)or not p for p in links)
                        or not isinstance(data,dict)
                        or data.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'
                        or type(data.get('round_trips'))is not int or data['round_trips']!=4
                        or not isinstance(data.get('proofs'),list) or len(data['proofs'])!=2
                        or any(not isinstance(p,dict)or not p for p in data['proofs'])):return 1
            return 0 if valid else 1
        proof=record.get('channel_daemon_corroboration',{})
        if not isinstance(proof,dict):return 1
        valid=(record.get('status')=='REAL_DAEMON_CHANNEL_DEATH_PASS'
            and proof.get('status')=='REAL_DAEMON_CHANNEL_DEATH_USB_CORROBORATED'
            and type(record.get('channel_daemon_index'))is int and record['channel_daemon_index']in(0,1)
            and type(proof.get('first_blocked_errno'))is int and proof['first_blocked_errno']in(errno.EACCES,errno.ESTALE)
            and type(proof.get('business_round_trips'))is int and proof['business_round_trips']==2
            and isinstance(proof.get('legs'),list) and len(proof['legs'])==8
            and all(isinstance(p,dict)and p for p in proof['legs'])
            and isinstance(proof.get('original_up'),list) and len(proof['original_up'])==2
            and all(isinstance(p,dict)and p for p in proof['original_up'])
            and all(proof.get(k)is True for k in ['actual_daemon_death','successor_does_not_renew_old_fd','common_owner_both_leases_withdrawn'])
            and all(proof.get(k)is False for k in ['independent_device_business_isolation','physical_acceptance','automatic_recovery_acceptance','full_grant_complete'])
            and isinstance(proof.get('physical_down_before_wake'),list)
            and len(proof['physical_down_before_wake'])==(1 if proof.get('first_blocked_errno')==errno.ESTALE else 0)
            and all(isinstance(p,dict)and p for p in proof['physical_down_before_wake']))
        version=record.get('channel_daemon_restart_version',1)
        if type(version)is not int or version not in (1,2):return 1
        if proof.get('daemon_restart_version',1)!=version:return 1
        if version==2:
            from ws73_ssap_daemon_restart import summary_valid
            valid=valid and summary_valid(proof)
        return 0 if valid else 1
    if connection:
        for key in ['connection_corroboration','connection_object_corroboration']:
            proof=record.get(key)
            if not isinstance(proof,list) or len(proof)!=2 or any(not isinstance(p,dict) or not p for p in proof):return 1
    if channel:
        proof=record.get('channel_socket_corroboration',{})
        rounds=record.get('channel_socket_rounds_requested',4)
        if (not isinstance(proof,dict) or proof.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'
                or type(rounds) is not int or rounds<=0
                or type(proof.get('round_trips')) is not int or proof['round_trips']!=(0 if prefix else rounds*2)):
            return 1
    if prefix:
        proof=record.get('channel_socket_corroboration',{})
        phases=proof.get('proofs',[]) if isinstance(proof,dict) else []
        if (not channel or record.get('channel_socket_rounds_requested')!=1 or record.get('channel_socket_bytes_requested')!=2042
                or record.get('ordinary_prefix_close_acceptance') is not True
                or record.get('ordinary_channel_socket_acceptance') is not False
                or proof.get('physical_prefix_delivery_acceptance') is not True
                or type(proof.get('prefix_close_phases')) is not int or proof['prefix_close_phases']!=2
                or not isinstance(phases,list) or len(phases)!=2):return 1
        for n,phase in enumerate(phases):
            if (not isinstance(phase,dict) or phase.get('phase')!=n
                    or not isinstance(phase.get('prefix_close'),dict)
                    or phase['prefix_close'].get('other_channel_after_close') is not True
                    or not isinstance(phase.get('ssap_values'),list) or not phase['ssap_values']):return 1
    from ws73_application_discovery import valid_summary as valid_discovery, boot_case, case as discovery_case, supervision_summary
    discovery=record.get('application_discovery_requested',False)
    if type(discovery) is not bool:return 1
    discovery_tokens=sum(arg.split().count('ws73.application_discovery=1') for arg in record.get('qemu_args',[]) if isinstance(arg,str))
    if discovery_tokens!=int(discovery):return 1
    try:
        variant=boot_case([token for arg in record.get('qemu_args',[]) if isinstance(arg,str) for token in arg.split()])
        if record.get('application_discovery_case','release')!=variant:return 1
    except CaptureError:return 1
    if variant=='ttl':
        from ws73_application_discovery import validate_probe
        try:validate_probe(record.get('application_discovery_probe',{}))
        except (CaptureError,KeyError,TypeError):return 1
        if record.get('application_discovery_corroboration',{}).get('probe')!=record['application_discovery_probe']:return 1
    elif 'application_discovery_probe' in record:return 1
    if discovery:
        postures=[token for arg in record.get('qemu_args',[]) if isinstance(arg,str)
                  for token in arg.split() if token.startswith('ws73.connection_advertising=')]
        if postures!=['ws73.connection_advertising=negotiable-t']:return 1
        if (record.get('application_discovery_acceptance')is not True or not valid_discovery(record.get('application_discovery_corroboration',{})) or
                discovery_case(record.get('application_discovery_corroboration',{}))!=variant or
                record.get('application_discovery_supervision')!=supervision_summary(variant)):
            return 1
    elif record.get('application_discovery_acceptance') or record.get('application_discovery_corroboration'):
        return 1
    native_return=record.get('native_return_requested',False)
    if type(native_return) is not bool:return 1
    command=record.get('qemu_args',[])
    native_boot=any(isinstance(v,str) and 'ws73.native_return=1' in v.split() for v in command) if isinstance(command,list) else False
    if native_boot != native_return:return 1
    if native_return:
        from ws73_native_return import valid_summary
        if (record.get('status')!='PASSTHROUGH_SUPPORT_PASS' or record.get('native_return_acceptance')is not True
                or not valid_summary(record.get('native_return_corroboration',{}))
                or record.get('ordinary_channel_socket_acceptance')is not True
                or record.get('channel_socket_verification_requested')is not True
                or record.get('channel_socket_corroboration',{}).get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'
                or type(record.get('channel_socket_corroboration',{}).get('round_trips'))is not int
                or record['channel_socket_corroboration']['round_trips']!=8
                or record.get('native_return_corroboration',{}).get('fixture_sha256')!=record.get('native_return_fixture',{}).get('library',{}).get('sha256')):return 1
    elif record.get('native_return_acceptance') or record.get('native_return_corroboration'):return 1
    native_controller=record.get('native_controller_return_requested')
    controller_boot=[v.split('=',1)[1] for arg in command if isinstance(arg,str)
                     for v in arg.split() if v.startswith('ws73.native_controller_return=')] if isinstance(command,list) else []
    if native_controller is not None:
        from ws73_native_controller_return import valid_summary
        if (native_return or native_controller not in ('initiator','acceptor') or controller_boot != [native_controller]
                or record.get('status') != 'PASSTHROUGH_SUPPORT_PASS'
                or record.get('native_controller_return_acceptance') is not True
                or not valid_summary(record.get('native_controller_return_corroboration'))
                or record['native_controller_return_corroboration']['role'] != native_controller
                or record['native_controller_return_corroboration']['fixture_sha256'] != record.get('native_return_fixture',{}).get('library',{}).get('sha256')
                or record['native_controller_return_corroboration']['owner_probe_binary']['sha256'] != record.get('native_return_probe',{}).get('program',{}).get('sha256')
                or record.get('ordinary_channel_socket_acceptance') is not True
                or record.get('channel_socket_verification_requested') is not True
                or record.get('channel_socket_corroboration',{}).get('status') != 'ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'
                or type(record['channel_socket_corroboration'].get('round_trips')) is not int
                or record['channel_socket_corroboration']['round_trips'] != 8):return 1
    elif controller_boot or record.get('native_controller_return_acceptance') or record.get('native_controller_return_corroboration'):return 1
    directory_events=record.get('controller_directory_requested',False)
    if type(directory_events)is not bool:return 1
    directory_boot=[v.split('=',1)[1]for arg in command if isinstance(arg,str)for v in arg.split()if v.startswith('ws73.controller_directory_events=')]if isinstance(command,list)else []
    if directory_boot!=(['1']if directory_events else []):return 1
    if directory_events:
        from ws73_controller_directory import valid_all_summary as directory_summary
        if (native_controller is None or record.get('controller_directory_acceptance')is not True
                or not directory_summary(record.get('controller_directory_corroboration'))
                or record['controller_directory_corroboration']['program_sha256']!=record.get('controller_directory_program',{}).get('sha256')
                or record['controller_directory_corroboration']['verifier_sha256']!=record.get('controller_directory_verifier',{}).get('sha256')
                or record['controller_directory_corroboration'].get('prepared_clients')!=record.get('controller_directory_clients')):return 1
    elif record.get('controller_directory_acceptance')or record.get('controller_directory_corroboration'):return 1
    initialization=record.get('ssap_initialization_requested',False)
    if type(initialization)is not bool:return 1
    if initialization:
        from ws73_ssap_initialization import valid_summary, profile, exchange_contract
        try:
            selector_version=exchange_contract(record)
            spec=profile(record.get('ssap_initialization_stage','cmtc'),selector_version)
        except ValueError:return 1
        ordinary=record.get('channel_socket_corroboration',{})
        held=record.get('ssap_initialization_hold',{})
        if (record.get('status')!='PASSTHROUGH_SUPPORT_PASS' or record.get('ssap_initialization_acceptance')is not True
                or record.get('ordinary_channel_socket_acceptance')is not True
                or record.get('channel_socket_verification_requested')is not True
                or ordinary.get('status')!='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'
                or type(ordinary.get('round_trips'))is not int or ordinary['round_trips']!=8
                or held.get('method')!=spec['method'] or held.get('qemu_sha256')!=spec['qemu'] or held.get('complete')is not True
                or held.get('stage','cmtc')!=spec['stage']
                or type(held.get('exchange_contract',1)) is not int or held.get('exchange_contract',1)!=selector_version
                or record.get('ssap_initialization_corroboration',{}).get('stage','cmtc')!=spec['stage']
                or not valid_summary(record.get('ssap_initialization_corroboration',{}),expected_version=selector_version)):return 1
    elif record.get('ssap_initialization_acceptance')or record.get('ssap_initialization_corroboration'):return 1
    channel_proof=record.get('channel_socket_corroboration',{})
    if not isinstance(channel_proof,dict):return 1
    length_gate=record.get('ssap_value_lengths_requested',False)
    if type(length_gate)is not bool:return 1
    length_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.ssap_value_lengths=1']
    if length_boot!=(['ws73.ssap_value_lengths=1']if length_gate else[]):return 1
    if length_gate:
        from ws73_ssap_value import valid_length_summary
        if record.get('ssap_value_lengths_acceptance')is not True or record.get('ordinary_channel_socket_acceptance')is not True or record.get('qemu_exit')!=0 or not valid_length_summary(channel_proof,expected_version=record.get('ssap_value_lengths_contract_version',1)):return 1
    elif record.get('ssap_value_lengths_acceptance')or any(v.get('length_gate')for p in channel_proof.get('proofs',[])for v in p.get('ssap_values',[])):return 1
    parallel_subscription=record.get('status')=='FOUR_DEVICE_PARALLEL_SHARED_SUBSCRIPTION_PASS'
    subscription=record.get('ssap_subscription_requested',False)
    if type(subscription)is not bool or parallel_subscription and subscription:return 1
    subscription_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.ssap_subscription=1']
    if subscription_boot!=(['ws73.ssap_subscription=1']if subscription or parallel_subscription else[]):return 1
    if subscription:
        from ws73_ssap_subscription import valid_summary as subscription_summary,valid_supervision as subscription_supervision
        if (type(record.get('ssap_subscription_contract_version'))is not int or record['ssap_subscription_contract_version']!=1 or record.get('ssap_subscription_acceptance')is not True
                or record.get('status')!='REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS'
                or record.get('live_security_agent_requested')!='numeric-approve'
                or record.get('ordinary_channel_socket_acceptance')is not True
                or record.get('live_ssap_security_requirement')!=2
                or record.get('qemu_exit')!=0
                or not subscription_summary(record.get('channel_socket_corroboration',{}))
                or not subscription_supervision(record.get('ssap_subscription_supervision',{}))):return 1
    elif record.get('ssap_subscription_acceptance')or record.get('ssap_subscription_supervision')or any(p.get('ssap_subscription')for p in record.get('channel_socket_corroboration',{}).get('proofs',[])):return 1
    shared=record.get('ssap_subscription_shared_requested',False)
    if type(shared)is not bool or shared and not subscription:return 1
    from ws73_ssap_subscription import shared_boot,boot_shared_case,shared_case as validate_shared_case
    try:
        shared_case=validate_shared_case(dict(record,ssap_subscription_shared_required=shared or parallel_subscription,**({'ssap_subscription_shared_contract_version':1}if parallel_subscription else{})))
        if boot_shared_case([v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()],shared or parallel_subscription)!=shared_case:return 1
        if shared_boot([v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()])!=(shared or parallel_subscription):return 1
    except CaptureError:return 1
    if shared:
        from ws73_ssap_subscription import valid_shared_summary,valid_shared_supervision
        from ws73_ssap_shared import valid_configuration_summary
        wire=record.get('ssap_subscription_shared_wire',{})
        verifier=record.get('ssap_subscription_shared_verifier',{})
        if(type(record.get('ssap_subscription_shared_contract_version'))is not int or record['ssap_subscription_shared_contract_version']!=1
            or type(record.get('ssap_subscription_snapshot_contract_version'))is not int or record['ssap_subscription_snapshot_contract_version']!=1
            or set(verifier)!={'path','sha256'}or not isinstance(verifier['path'],str)or not verifier['path'].endswith('/ws73_ssap_shared.py')or not isinstance(verifier['sha256'],str)or not re.fullmatch('[0-9a-f]{64}',verifier['sha256'])
            or record.get('ssap_subscription_shared_acceptance')is not True or not valid_shared_summary(channel_proof,case=shared_case)or not valid_shared_supervision(record.get('ssap_subscription_supervision',{}),case=shared_case)
            or not valid_configuration_summary(wire)):return 1
    elif(record.get('ssap_subscription_shared_acceptance')or record.get('ssap_subscription_shared_contract_version')is not None
        or record.get('ssap_subscription_shared_wire')or record.get('ssap_subscription_supervision',{}).get('shared_contract_version')is not None
        or any(v.get('shared_contract_version')is not None for p in channel_proof.get('proofs',[])for v in p.get('ssap_subscription',[]))):return 1
    renewal=record.get('ssap_subscription_renewal_requested',False)
    snapshot=record.get('ssap_subscription_snapshot_contract_version')
    snapshot_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.subscription_snapshot=1']
    if snapshot is not None:
        from ws73_ssap_subscription import valid_snapshot_supervision
        if(type(snapshot)is not int or snapshot!=1 or not subscription or snapshot_boot!=['ws73.subscription_snapshot=1']
                or not valid_snapshot_supervision(record.get('ssap_subscription_supervision',{}))):return 1
    elif snapshot_boot!=(['ws73.subscription_snapshot=1']if parallel_subscription else[])or record.get('ssap_subscription_supervision',{}).get('snapshot_contract_version')is not None:return 1
    if type(renewal)is not bool or renewal and not subscription:return 1
    renewal_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.ssap_subscription_renewal=1']
    if renewal_boot!=(['ws73.ssap_subscription_renewal=1']if renewal else[]):return 1
    if renewal:
        from ws73_ssap_subscription import valid_renewal_summary,valid_renewal_supervision
        if (type(record.get('ssap_subscription_renewal_contract_version'))is not int or record['ssap_subscription_renewal_contract_version']!=1
                or record.get('ssap_subscription_renewal_acceptance')is not True
                or not valid_renewal_summary(channel_proof)or not valid_renewal_supervision(record.get('ssap_subscription_supervision',{}))):return 1
    elif(record.get('ssap_subscription_renewal_acceptance')or record.get('ssap_subscription_renewal_contract_version')is not None
            or record.get('ssap_subscription_supervision',{}).get('renewal_contract_version')is not None
            or any(v.get('renewal_contract_version')is not None for p in channel_proof.get('proofs',[])for v in p.get('ssap_subscription',[]))):return 1
    pressure=record.get('ssap_subscription_pressure_requested',False)
    if type(pressure)is not bool or pressure and(not subscription or renewal):return 1
    pressure_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.ssap_subscription_pressure=1']
    if pressure_boot!=(['ws73.ssap_subscription_pressure=1']if pressure else[]):return 1
    if pressure:
        from ws73_ssap_subscription import valid_pressure_summary,valid_pressure_supervision
        if(type(record.get('ssap_subscription_pressure_contract_version'))is not int or record['ssap_subscription_pressure_contract_version']!=1
                or record.get('ssap_subscription_pressure_acceptance')is not True
                or not valid_pressure_summary(channel_proof)or not valid_pressure_supervision(record.get('ssap_subscription_supervision',{}))):return 1
    elif(record.get('ssap_subscription_pressure_acceptance')or record.get('ssap_subscription_pressure_contract_version')is not None
            or record.get('ssap_subscription_supervision',{}).get('pressure_contract_version')is not None
            or any(v.get('pressure_contract_version')is not None for p in channel_proof.get('proofs',[])for v in p.get('ssap_subscription',[]))):return 1
    owner_loss=record.get('ssap_subscription_owner_loss_requested',False)
    if type(owner_loss)is not bool or owner_loss and(not subscription or renewal or pressure):return 1
    loss_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.ssap_subscription_owner_loss=1']
    if loss_boot!=(['ws73.ssap_subscription_owner_loss=1']if owner_loss else[]):return 1
    if owner_loss:
        from ws73_ssap_subscription import valid_owner_loss_summary,valid_owner_loss_supervision
        if(type(record.get('ssap_subscription_owner_loss_contract_version'))is not int or record['ssap_subscription_owner_loss_contract_version']!=1
                or record.get('ssap_subscription_owner_loss_acceptance')is not True
                or not valid_owner_loss_summary(channel_proof)or not valid_owner_loss_supervision(record.get('ssap_subscription_supervision',{}))):return 1
    elif(record.get('ssap_subscription_owner_loss_acceptance')or record.get('ssap_subscription_owner_loss_contract_version')is not None
            or record.get('ssap_subscription_supervision',{}).get('owner_loss_contract_version')is not None
            or any(v.get('owner_loss_contract_version')is not None for p in channel_proof.get('proofs',[])for v in p.get('ssap_subscription',[]))):return 1
    inflight=record.get('ssap_subscription_inflight_release_requested',False)
    if type(inflight)is not bool or inflight and(not subscription or renewal or pressure or owner_loss):return 1
    inflight_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.ssap_subscription_inflight_release=1']
    if inflight_boot!=(['ws73.ssap_subscription_inflight_release=1']if inflight else[]):return 1
    from ws73_ssap_subscription import boot_inflight_case,inflight_case as check_inflight_case
    try:
        case=check_inflight_case(dict(ssap_subscription_inflight_release_required=inflight,ssap_subscription_inflight_release_contract_version=record.get('ssap_subscription_inflight_release_contract_version'),**{k:record[k]for k in ('ssap_subscription_inflight_case','ssap_subscription_inflight_expiry_contract_version')if k in record}))
        if boot_inflight_case([v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()],inflight)!=case:return 1
    except (CaptureError,ValueError,KeyError):return 1
    if not inflight and record.get('ssap_subscription_inflight_expiry_acceptance')is not None:return 1
    if inflight:
        from ws73_ssap_subscription import valid_inflight_summary,valid_inflight_supervision
        from ws73_ssap_sender_deadline import valid_hold_summary
        if(type(record.get('ssap_subscription_inflight_release_contract_version'))is not int or record['ssap_subscription_inflight_release_contract_version']!=1
                or snapshot!=1 or (record.get('ssap_subscription_inflight_expiry_acceptance')is not True or record.get('ssap_subscription_inflight_release_acceptance')is not False if case=='expiry'else record.get('ssap_subscription_inflight_release_acceptance')is not True or record.get('ssap_subscription_inflight_expiry_acceptance')is not None)
                or not valid_inflight_summary(channel_proof,case=case)or not valid_inflight_supervision(record.get('ssap_subscription_supervision',{}),case=case)
                or not valid_hold_summary(record.get('ssap_subscription_inflight_hold',{}),record.get('ssap_subscription_inflight_corroboration',{}),purpose='subscription-'+case)):return 1
    elif(record.get('ssap_subscription_inflight_release_acceptance')or record.get('ssap_subscription_inflight_release_contract_version')is not None
            or record.get('ssap_subscription_inflight_hold')or record.get('ssap_subscription_inflight_corroboration')
            or record.get('ssap_subscription_supervision',{}).get('inflight_release_contract_version')is not None
            or any(v.get('inflight_release_contract_version')is not None for p in channel_proof.get('proofs',[])for v in p.get('ssap_subscription',[]))):return 1
    delivery=record.get('ssap_update_delivery_requested',False)
    from ws73_ssap_read_provider import valid_manifest as valid_provider_manifest
    if not valid_provider_manifest(record):return 1
    from ws73_ssap_sdk_read_provider import valid_manifest as valid_sdk_provider_manifest
    if not valid_sdk_provider_manifest(record):return 1
    from ws73_ssap_sdk_write_provider import valid_manifest as valid_sdk_write_provider_manifest
    if not valid_sdk_write_provider_manifest(record):return 1
    from ws73_ssap_write_unregister import valid_manifest as valid_write_unregister_manifest
    if not valid_write_unregister_manifest(record):return 1
    from ws73_ssap_write_owner_exit import valid_manifest as valid_write_owner_exit_manifest
    if not valid_write_owner_exit_manifest(record):return 1
    from ws73_ssap_write_down import valid_manifest as valid_write_down_manifest
    if not valid_write_down_manifest(record):return 1
    from ws73_ssap_provider_owner_exit import valid_manifest as valid_provider_exit_manifest
    if not valid_provider_exit_manifest(record):return 1
    from ws73_ssap_provider_unregister import valid_manifest as valid_provider_unregister_manifest
    if not valid_provider_unregister_manifest(record):return 1
    from ws73_ssap_provider_deadline import valid_manifest as valid_provider_deadline_manifest
    if not valid_provider_deadline_manifest(record):return 1
    from ws73_ssap_description import valid_manifest as valid_description_manifest
    if not valid_description_manifest(record):return 1
    from ws73_ssap_command import valid_manifest as valid_command_manifest
    if not valid_command_manifest(record):return 1
    from ws73_ssap_command_policy import valid_manifest as valid_command_policy_manifest
    if not valid_command_policy_manifest(record):return 1
    from ws73_ssap_command_deadline import valid_manifest as valid_command_deadline_manifest
    if not valid_command_deadline_manifest(record):return 1
    if type(delivery)is not bool:return 1
    delivery_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.ssap_update_delivery=1']
    if delivery_boot!=(['ws73.ssap_update_delivery=1']if delivery else[]):return 1
    if delivery:
        from ws73_ssap_update_delivery import valid_summary as delivery_summary
        if (record.get('status')!='REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS'
                or record.get('live_security_agent_requested')!='numeric-approve'
                or record.get('qemu_exit')!=0 or record.get('ssap_update_delivery_acceptance')is not True
                or record.get('ordinary_channel_socket_acceptance')is not True
                or record.get('live_ssap_security_requirement')!=2 or not delivery_summary(channel_proof,expected_version=record.get('ssap_update_delivery_contract_version',1))):return 1
    elif record.get('ssap_update_delivery_acceptance')or any(p.get('ssap_update_delivery')for p in channel_proof.get('proofs',[])):return 1
    receive=record.get('ssap_receive_lifecycle_requested',False)
    if type(receive)is not bool:return 1
    receive_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.ssap_receive_lifecycle=1']
    if receive_boot!=(['ws73.ssap_receive_lifecycle=1']if receive else[]):return 1
    if receive:
        from ws73_ssap_receive_lifecycle import valid_summary as receive_summary,valid_observer_summary
        if not delivery or record.get('ssap_receive_lifecycle_acceptance')is not True or not receive_summary(channel_proof)or not valid_observer_summary(record.get('ssap_receive_capture_observations')):return 1
    elif record.get('ssap_receive_lifecycle_acceptance')or record.get('ssap_receive_capture_observations')or any(p.get('ssap_receive_lifecycle')for p in channel_proof.get('proofs',[])):return 1
    sender=record.get('ssap_sender_deadline_requested',False)
    if type(sender)is not bool:return 1
    sender_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.ssap_sender_deadline=1']
    if sender_boot!=(['ws73.ssap_sender_deadline=1']if sender else[]):return 1
    if sender:
        from ws73_ssap_sender_deadline import valid_summary as sender_summary,valid_hold_summary,boot_case
        selected=record.get('ssap_sender_lifecycle_case','deadline')
        try:actual_case=boot_case([t for arg in record.get('qemu_args',[])if isinstance(arg,str)for t in arg.split()],True)
        except (ValueError,TypeError):return 1
        if (not delivery or record.get('ssap_sender_deadline_acceptance')is not True or not sender_summary(channel_proof)
                or actual_case!=selected or any(p['ssap_sender_deadline'][0].get('lifecycle_case','deadline')!=selected for p in channel_proof.get('proofs',[]))
                or not valid_hold_summary(record.get('ssap_sender_deadline_hold',{}),record.get('ssap_sender_deadline_corroboration',{}))):return 1
    elif record.get('ssap_sender_lifecycle_case','deadline')!='deadline' or any(t.startswith('ws73.ssap_sender_case=')for arg in record.get('qemu_args',[])if isinstance(arg,str)for t in arg.split())or record.get('ssap_sender_deadline_acceptance')or record.get('ssap_sender_deadline_hold')or any(p.get('ssap_sender_deadline')for p in channel_proof.get('proofs',[])):return 1
    update=record.get('ssap_owned_update_requested',False)
    if type(update)is not bool:return 1
    update_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.ssap_owned_update=1']
    if update_boot!=(['ws73.ssap_owned_update=1']if update else[]):return 1
    if update:
        from ws73_ssap_owned_update import valid_summary as update_summary
        if record.get('status')!='PASSTHROUGH_SUPPORT_PASS' or record.get('qemu_exit')!=0 or record.get('ssap_owned_update_acceptance')is not True or record.get('ordinary_channel_socket_acceptance')is not True or not update_summary(channel_proof):return 1
    elif record.get('ssap_owned_update_acceptance')or any(p.get('ssap_owned_updates')for p in channel_proof.get('proofs',[])):return 1
    lifecycle=record.get('ssap_owner_lifecycle_requested',False)
    owner_publisher=record.get('ssap_owner_publisher_requested','cli')
    if owner_publisher not in ('cli','sdk') or (owner_publisher!='cli' and lifecycle is not True):return 1
    if type(lifecycle)is not bool:return 1
    if lifecycle:
        from ws73_ssap_owner_lifecycle import valid_summary
        if (record.get('status')!='PASSTHROUGH_SUPPORT_PASS' or record.get('qemu_exit')!=0
                or record.get('ssap_owner_lifecycle_acceptance')is not True or record.get('ordinary_channel_socket_acceptance')is not True or not valid_summary(channel_proof,publisher=owner_publisher)):return 1
    elif record.get('ssap_owner_lifecycle_acceptance') or any(p.get('ssap_owner_lifecycle')for p in channel_proof.get('proofs',[])):return 1
    requester=record.get('ssap_requester_lifecycle_requested',False)
    if type(requester)is not bool:return 1
    if requester:
        from ws73_ssap_requester_lifecycle import valid_summary as valid_requester
        if (lifecycle or record.get('status')!='PASSTHROUGH_SUPPORT_PASS' or record.get('qemu_exit')!=0
                or record.get('ssap_requester_lifecycle_acceptance')is not True or record.get('ordinary_channel_socket_acceptance')is not True or not valid_requester(channel_proof)):return 1
    elif record.get('ssap_requester_lifecycle_acceptance')or any(p.get('ssap_requester_lifecycle')for p in channel_proof.get('proofs',[])):return 1
    clients=record.get('application_client_verification_requested',False)
    if type(clients) is not bool:return 1
    if not clients and (record.get('application_client_acceptance') or 'application_client_corroboration' in record):return 1
    if clients:
        from ws73_application_client import valid_summary
        from ws73_application_role import valid_supervision
        if type(record.get('application_role_contract_version'))is not int or record['application_role_contract_version']!=2:return 1
        if not valid_supervision(record.get('application_role_supervision',{})):return 1
        if record.get('status')!='PASSTHROUGH_SUPPORT_PASS' or record.get('qemu_exit')!=0 or record.get('application_client_acceptance') is not True or not valid_summary(record.get('application_client_corroboration',{})):return 1
    required=record.get('live_ssap_security_requirement',0)
    if type(required) is not int or required not in (0,1,2):return 1
    if not required and (any(v.get('ssap_security_requirement',0) for v in record.get('security_agent_corroboration',{}).get('phases',[])) or any(v.get('protected_ssap') for v in record.get('channel_socket_corroboration',{}).get('proofs',[]))):return 1
    # The dedicated four-pair status validates both per-pair security tuples below.
    if required and record.get('status')not in ('FOUR_DEVICE_PARALLEL_UPDATE_DELIVERY_PASS','FOUR_DEVICE_PARALLEL_SHARED_SUBSCRIPTION_PASS'):
        security=record.get('security_agent_corroboration',{}).get('phases',[])
        business=record.get('channel_socket_corroboration',{}).get('proofs',[])
        if (record.get('status')!='REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS'
                or len(security)!=2 or len(business)!=2
                or any(v.get('ssap_security_requirement')!=required for v in security)
                or any(v.get('protected_ssap',{}).get('required')!=required
                    or len(v.get('protected_ssap',{}).get('controllers',[]))!=2
                    or not v.get('ssap_values') or not v.get('ssap_discovery') for v in business)):
            return 1
    required=record.get('live_channel_security_required',0)
    connected=record.get('connected_file_corroboration',{})
    if not isinstance(connected,dict):return 1
    sibling=record.get('channel_sibling_business_requested',False)
    if type(sibling)is not bool:return 1
    sibling_tokens=[w for arg in record.get('qemu_args',[])if isinstance(arg,str)for w in arg.split()if w=='ws73.channel_sibling_business'or w.startswith('ws73.channel_sibling_business=')]
    if sibling:
        from ws73_channel_sibling import valid_summary,transition_flags,boot_request,valid_primary_binding
        try:
            transition=transition_flags(record.get('live_connected_file_case'),record.get('live_channel_link_down_requested',False),record.get('live_channel_deadline_requested',False))
        except ValueError:return 1
        words=[w for arg in record.get('qemu_args',[])if isinstance(arg,str)for w in arg.split()]
        try:
            request=boot_request(words)
        except ValueError:return 1
        if request is None or (request['case'],request['victim_index'],request['transition'])!=(record.get('live_connected_file_case'),record.get('live_connected_file_index'),transition):return 1
        for key,wanted in [('ws73.channel_link_down',transition=='down'),('ws73.channel_deadline',transition=='deadline')]:
            if[w for w in words if w==key or w.startswith(key+'=')]!=([key+'=1']if wanted else[]):return 1
        statuses={'withdrawal':'REAL_CHANNEL_GRANT_PASS','down':'REAL_CHANNEL_LINK_DOWN_PREFIX_PASS','deadline':'REAL_CHANNEL_ORIGINAL_DEADLINE_PREFIX_PASS'}
        if (sibling_tokens!=['ws73.channel_sibling_business=1']or type(record.get('channel_sibling_business_contract_version'))is not int or record['channel_sibling_business_contract_version']!=4
                or record.get('status')!=statuses[transition]or type(record.get('live_connected_file_index'))is not int or record['live_connected_file_index']not in(0,1)
                or record.get('live_channel_grant_gate')is not True or record.get('live_channel_revoke_prefix_gate')is not True
                or record.get('managed_prefix_geometry_contract_version')!=1
                or connected.get('sibling_business',{}).get('case')!=record.get('live_connected_file_case')
                or connected.get('sibling_business',{}).get('transition')!=transition
                or record.get('channel_sibling_business_acceptance')is not True or not valid_summary(connected.get('sibling_business',{}),victim_index=record['live_connected_file_index'])):return 1
        if not valid_primary_binding(record):return 1
        if transition=='withdrawal':
            native_grant=connected.get('channel_grant',{});begun=native_grant.get('begun_revoke',{})
            if (native_grant.get('status')!='REAL_BLOCKED_RX_GRANT_USB_CORROBORATED'
                or begun.get('status')!='ACTUAL_BEGUN_PDU_WITHDRAWAL_PREFIX_PASS'or begun.get('no_new_submit_after_withdrawal')is not True
                or type(begun.get('submitted_bytes'))is not int or not 0<begun['submitted_bytes']<2047
                or connected.get('held_reply',{}).get('status')!='REAL_INCOMPLETE_PDU_BARRIER_CORROBORATED'):return 1
        else:
            expected='REAL_BEGUN_LINK_DOWN_CORROBORATED'if transition=='down'else'REAL_ORIGINAL5S_BEGUN_DEADLINE_CORROBORATED'
            if (connected.get('status')!=expected or type(connected.get('submitted_bytes'))is not int or not 0<connected['submitted_bytes']<2047
                or connected.get('partial_pdu_application_round_trips')!=0):return 1
            if transition=='down':
                if connected.get('both_leases_preserved')is not True or connected.get('prefix_hold',{}).get('status')!='REAL_INCOMPLETE_PDU_BARRIER_CORROBORATED':return 1
            elif not connected.get('delayed_nocp_records')or connected.get('host_hold',{}).get('status')!='ACTUAL_HOST_HOLD_CORROBORATED':return 1
    elif sibling_tokens or any(w=='ws73.channel_sibling_contract'or w.startswith('ws73.channel_sibling_contract=')for arg in record.get('qemu_args',[])if isinstance(arg,str)for w in arg.split())or any(k in record for k in ['channel_sibling_business_contract_version','channel_sibling_business_acceptance'])or 'sibling_business'in connected:return 1
    geometry_tokens=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v.startswith('ws73.prefix_geometry=')]
    geometry_version=record.get('managed_prefix_geometry_contract_version')
    if geometry_version is not None or geometry_tokens:
        from ws73_channel_prefix_hold import valid_geometry_summary
        if (type(geometry_version)is not int or geometry_version!=1 or geometry_tokens!=['ws73.prefix_geometry=1']
                or record.get('live_channel_revoke_prefix_gate')is not True
                or not valid_geometry_summary(connected.get('prefix_geometry'))):return 1
    proof=connected.get('protected_security')
    if type(required) is not int or required not in (0,1,2):return 1
    if required:
        if (record.get('qemu_exit')!=0 or not isinstance(proof,dict) or type(proof.get('requirement')) is not int or proof['requirement']!=required
                or proof.get('status')!='ACTUAL_PROTECTED_PRELUDE_AND_LIFECYCLE_SCOPE'
                or not isinstance(proof.get('wire'),dict) or proof['wire'].get('status')!='REAL_POSITIVE_EXCHANGE_ONLY_CORROBORATED'):return 1
    elif proof is not None:return 1

    fairness=record.get('channel_fairness_requested',False)
    if type(fairness) is not bool:return 1
    if not fairness and (record.get('channel_fairness_acceptance') or 'channel_fairness_corroboration' in record):return 1
    if fairness:
        p=record.get('channel_fairness_corroboration',{})
        if (record.get('channel_fairness_acceptance') is not True or record.get('qemu_exit')!=0
                or p.get('status')!='REAL_CONCURRENT_SHORT_LONG_PDU_PROGRESS_SCOPED_PASS'
                or type(p.get('round_trips')) is not int or p['round_trips']!=72
                or p.get('full_fairness_acceptance') is not False or p.get('performance_qualified') is not False
                or p.get('natural_recovery') is not False or len(p.get('proofs',[]))!=2):return 1
    requested=record.get('session_service_observation_requested',False)
    if not requested and (record.get('session_service_acceptance') or 'session_service_observation' in record):return 1
    if requested:
        proof=record.get('session_service_observation',{})
        if (record.get('session_service_acceptance') is not True or record.get('qemu_exit')!=0
                or proof.get('status')!='REAL_SESSION_SERVICE_AND_USB_SUBMITS_CORROBORATED'
                or any(type(proof.get(k)) is not int or proof[k]<=0 for k in ['services','attempts','accepted_usb_packets','operations'])):return 1
    from ws73_session_service import FULL_LOAD_PROFILE,PROFILE_TOKEN
    collector_version=record.get('session_service_collector_contract_version')
    collector=record.get('session_service_collector_profile')
    collector_proof=record.get('session_service_observation',{})
    collector_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v.startswith(PROFILE_TOKEN)]
    if collector_version is not None:
        if (type(collector_version)is not int or collector_version!=2 or requested is not True
                or collector!=FULL_LOAD_PROFILE or collector_boot!=[PROFILE_TOKEN+'full-load-v2']
                or type(collector_proof.get('collector_contract_version'))is not int
                or collector_proof['collector_contract_version']!=2 or collector_proof.get('collector_profile')!=collector):return 1
    elif collector is not None or collector_boot or 'collector_profile'in collector_proof or 'collector_contract_version'in collector_proof:return 1
    from ws73_session_service import valid_queued_summary
    queued_version=record.get('queued_discard_contract_version')
    queued_proof=record.get('session_service_observation',{}).get('queued_discard_lifecycle')
    queued_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v.startswith('ws73.channel_queued_discard=')]
    if queued_version is not None:
        queued_mode='deadline' if record.get('live_channel_deadline_requested') else 'down' if record.get('live_channel_link_down_requested') else record.get('live_connected_file_case')
        if (type(queued_version)is not int or queued_version!=1 or queued_boot!=['ws73.channel_queued_discard=1']
                or not requested or not record.get('live_channel_grant_gate')or not record.get('live_channel_revoke_prefix_gate')
                or not valid_queued_summary(queued_proof)
                or queued_proof['mode']!=queued_mode or queued_proof['controller']!=record.get('live_connected_file_index')
                or record.get('session_service_observation',{}).get('queued_discarded_operations')!=2):return 1
    elif queued_proof is not None or queued_boot:return 1
    phase=record.get('intent_phase_contract_version')
    phase_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v.startswith('ws73.intent_phase=')]
    tx_phases=record.get('connected_file_corroboration',{}).get('tx_constraints',{})
    if phase is not None:
        if (type(phase)is not int or phase!=2 or phase_boot!=['ws73.intent_phase=2']
                or record.get('live_channel_deadline_requested')is not True
                or any(type(tx_phases.get(k))is not int for k in ['intent_phase_contract_version','expired_intent_refusals','retired_binding_refusals'])
                or tx_phases.get('intent_phase_contract_version')!=2
                or tx_phases.get('expired_intent_refusals')!=1 or tx_phases.get('retired_binding_refusals')!=2):return 1
    elif phase_boot or tx_phases.get('intent_phase_contract_version')is not None:return 1
    benchmark_role=record.get('socket_benchmark_role_contract_version')
    four_benchmark=record.get('four_device_dynamic_benchmark_requested',False)
    if type(four_benchmark)is not bool:return 1
    four_benchmark_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.parallel_benchmark'or v.startswith('ws73.parallel_benchmark=')]
    if four_benchmark:
        if four_benchmark_boot!=['ws73.parallel_benchmark=1']or not valid_parallel_benchmark(record):return 1
        if benchmark_role is not None or record.get('socket_benchmark_requested'):return 1
    elif four_benchmark_boot or any(k in record for k in ['four_dynamic_benchmark_contract_version','four_dynamic_benchmark_close_contract_version','four_dynamic_benchmark_pressure_contract_version','four_benchmark_case'])or any(v=='ws73.parallel_benchmark_case'or v.startswith('ws73.parallel_benchmark_case=')for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split())or record.get('status')=='FOUR_DEVICE_PARALLEL_DYNAMIC_BENCHMARK_PASS':return 1
    import ws73_benchmark_ssap as benchmark_ssap
    try:
        service=benchmark_ssap.selected(record)
        if benchmark_ssap.from_boot([v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()])!=service:return 1
        if service is not None:
            from ws73_socket_benchmark import record_configuration,row_channel
            benchmark_ssap.workload(record_configuration(record),row_channel(record))
            if (record.get('benchmark_ssap_acceptance')is not True
                or benchmark_ssap.selected(record.get('socket_benchmark_role_supervision',{}))!=service
                or not benchmark_ssap.valid_summary(record.get('socket_benchmark_corroboration',{}))):return 1
        elif(record.get('benchmark_ssap_acceptance')or benchmark_ssap.FIELD in record.get('socket_benchmark_role_supervision',{})
             or 'ssap'in record.get('socket_benchmark_corroboration',{})or any('ssap_concurrent_progress'in p for p in record.get('socket_benchmark_corroboration',{}).get('proofs',[]))):return 1
    except(ValueError,KeyError,TypeError):return 1
    trace_contract=record.get('benchmark_trace_contract_version')
    if trace_contract is not None:
        from ws73_benchmark_timeline import valid_trace_summary
        from ws73_socket_benchmark import row_channel,pressures_long
        try:pressure=pressures_long(row_channel(record))
        except(ValueError,KeyError,TypeError):return 1
        if(type(trace_contract)is not int or trace_contract!=1 or type(benchmark_role)is not int or benchmark_role!=1 or not record.get('socket_benchmark_requested')or not valid_trace_summary(record.get('socket_benchmark_xhci_observation',{}),record.get('socket_benchmark_xhci_requested'),pressure=pressure)):return 1
    elif record.get('socket_benchmark_xhci_observation',{}).get('trace_contract_version')is not None:return 1
    resource=record.get('benchmark_process_resource_contract_version')
    if resource is not None and(type(resource)is not int or resource!=1 or not record.get('socket_benchmark_requested')):return 1
    benchmark_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v.startswith('ws73.socket_benchmark_apps=')]
    if benchmark_role is not None:
        from ws73_socket_benchmark import valid_role_supervision
        if(type(benchmark_role)is not int or benchmark_role!=1 or not record.get('socket_benchmark_requested')or benchmark_boot!=['ws73.socket_benchmark_apps=1']or record.get('socket_benchmark_apps_acceptance')is not True or not valid_role_supervision(record.get('socket_benchmark_role_supervision',{}))):return 1
        names=[Path(v.get('path','')).name for v in record.get('benchmark_verifiers',[])]
        resource=record.get('benchmark_process_resource_contract_version')
        expected_names={'ws73_benchmark_resources.py'}if resource is not None else set()
        if service is not None:expected_names.update(benchmark_ssap.verifiers(service))
        if 'benchmark_channel_request'in record:
            expected_names.add('ws73_dynamic_channels.py')
            from ws73_socket_benchmark import row_channel,is_parallel
            try:
                if is_parallel(row_channel(record)):expected_names.add('ws73_channel_fairness.py')
            except(ValueError,KeyError,TypeError):return 1
        if len(names)!=5+len(expected_names) or set(names)!=expected_names|{'ws73_socket_benchmark.py','ws73_benchmark.py','ws73_benchmark_timeline.py','ws73_application_role.py','ws73_role_snapshot.py'}:return 1
    elif (benchmark_boot!=['ws73.socket_benchmark_apps=1']if four_benchmark else bool(benchmark_boot))or record.get('socket_benchmark_apps_acceptance')or record.get('socket_benchmark_role_supervision'):return 1
    extra_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v.startswith(('ws73.benchmark_dynamic=','ws73.benchmark_parallel=','ws73.benchmark_active=','ws73.benchmark_close=','ws73.benchmark_pressure='))]
    if not record.get('socket_benchmark_requested')and extra_boot:return 1
    if not record.get('socket_benchmark_requested') and (record.get('socket_benchmark_acceptance') or 'socket_benchmark_corroboration' in record or 'socket_benchmark_config_requested' in record or 'benchmark_channel_request'in record):return 1
    if record.get('socket_benchmark_requested'):
        proof=record.get('socket_benchmark_corroboration',{})
        mode=record['socket_benchmark_requested']
        window=record.get('socket_benchmark_window_requested',4)
        from ws73_socket_benchmark import record_configuration,configuration,validate_configuration,row_channel,is_parallel,channel_boot,valid_parallel_summary,parallel_replies
        try:config=record_configuration(record)
        except (ValueError,KeyError,TypeError):return 1
        try:channel=row_channel(record);proof_channel=row_channel(proof)
        except (ValueError,KeyError,TypeError):return 1
        dynamic_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v.startswith(('ws73.benchmark_dynamic=','ws73.benchmark_parallel=','ws73.benchmark_active=','ws73.benchmark_close=','ws73.benchmark_pressure='))]
        if channel!=proof_channel:return 1
        if channel is None:
            if dynamic_boot or any('dynamic_negotiation'in p or 'channel_requests'in p.get('application',{})for p in proof.get('proofs',[])):return 1
        elif (not benchmark_role or trace_contract!=1 or resource!=1 or dynamic_boot!=channel_boot(channel)
              or not is_parallel(channel)and(channel['ports']!=[24576,24577]or channel['aid']!=29441)):return 1
        if is_parallel(channel):
            if not valid_parallel_summary(proof,channel,config,record.get('socket_benchmark_role_supervision',{})):return 1
        elif record.get('socket_benchmark_role_supervision',{}).get('version',1)!=1:return 1
        resource=record.get('benchmark_process_resource_contract_version')
        from ws73_benchmark_resources import valid_summary
        if resource is not None:
            if type(resource)is not int or resource!=1 or not valid_summary(proof):return 1
        elif 'benchmark_process_resource_contract_version'in proof or any('resource_observations'in p for p in proof.get('proofs',[])):return 1
        if type(proof.get('window',4)) is not int or proof.get('window',4)!=window:return 1
        try:proof_config=proof['config'] if 'config' in proof else configuration(mode,window)
        except (ValueError,KeyError,TypeError):return 1
        try:validate_configuration(proof_config)
        except (ValueError,KeyError,TypeError):return 1
        if proof_config!=config:return 1
        count=config['count']
        if 'socket_benchmark_xhci_requested' in record:
            x=record.get('socket_benchmark_xhci_observation',{})
            if x.get('status')!='XHCI_CONFIGURATION_AND_SEAL_CORROBORATED' or x.get('mode')!=record['socket_benchmark_xhci_requested']:return 1
        if (mode not in ['rate','window','duplex'] or record.get('socket_benchmark_acceptance') is not True or record.get('performance_qualified') is not False or record.get('qemu_exit')!=0 or proof.get('status')!='REAL_WS73_LOAD_USB_AND_APPLICATION_OBSERVED_NOT_PERFORMANCE_QUALIFIED' or proof.get('mode')!=mode or proof.get('performance_qualified') is not False or proof.get('round_trips')!=(parallel_replies(channel)if is_parallel(channel)else count*(4 if mode=='duplex' else 2)) or len(proof.get('proofs',[]))!=2):return 1
        phases=proof['proofs']
        if not is_parallel(channel)and(not isinstance(phases,list) or any(not isinstance(p,dict) or p.get('phase')!=n or not isinstance(p.get('legs'),list) or len(p['legs'])!=count*(4 if mode=='duplex' else 2) or p.get('application',{}).get('status')!='LOAD_APPLICATION_REPORTS_CONSISTENT_NOT_QUALIFIED' or p['application'].get('performance_qualified') is not False or p['application'].get('fixture') is not False or p['application'].get('messages')!=([count,count] if mode=='duplex' else [count,0]) for n,p in enumerate(phases))):return 1
        if channel is not None and not is_parallel(channel):
            from ws73_socket_benchmark import application_request
            for phase in phases:
                expected=[application_request(dict(config=config,benchmark_channel_request=channel),i)for i in (0,1)]
                if phase['application'].get('channel_requests')!=expected or set(phase.get('dynamic_negotiation',{}))!={'request','response'}:return 1
                if any(set(phase['dynamic_negotiation'][key])!={'tx','rx'}for key in ('request','response')):return 1
    burst=record.get('dynamic_channel_burst_requested',False)
    if type(burst) is not bool or (burst and (record.get('dynamic_channel_verification_requested') is not True or record.get('dynamic_channel_long_bytes_requested')!=2042)):return 1
    if 'dynamic_channel_verification_requested' in record and type(record['dynamic_channel_verification_requested']) is not bool:return 1
    if record.get('dynamic_channel_long_bytes_requested') is not None and record.get('dynamic_channel_verification_requested') is not True:return 1
    if record.get('dynamic_channel_verification_requested'):
        dynamic=record.get('dynamic_channel_corroboration',{})
        size=record.get('dynamic_channel_long_bytes_requested')
        if size is not None and (type(size) is not int or size not in [249,250,253,254,255,1024,2042] or dynamic.get('long_bytes')!=size or dynamic.get('slot_exhaustion_refusals')!=2):return 1
        phases=dynamic.get('proofs',[])
        names=['A','B'] if size is None else ['A','B','C']
        if not isinstance(phases,list) or len(phases)!=2 or any(not isinstance(p,dict) or p.get('phase')!=n or [c.get('name') for c in p.get('channels',[])]!=names or any(len(c.get('business',[]))!=(40 if c.get('name')=='B' else 32 if burst and c.get('name')=='C' else 8) for c in p.get('channels',[])) for n,p in enumerate(phases)):return 1
        if (record.get('ordinary_channel_socket_acceptance') is not True or record.get('dynamic_channel_acceptance') is not True or dynamic.get('status')!=('DYNAMIC_BASIC_CHANNEL_BURST_CREDIT_SCOPED_PASS' if burst else 'DYNAMIC_BASIC_TWO_CHANNEL_USB_AND_APPLICATION_SCOPED_PASS' if size is None else 'DYNAMIC_BASIC_CHANNEL_LONG_AND_SLOT_BOUND_SCOPED_PASS') or dynamic.get('round_trips')!=(80 if burst else 48 if size is None else 56) or len(dynamic.get('proofs',[]))!=2 or record.get('qemu_exit')!=0):return 1
    if burst:
        for phase in record['dynamic_channel_corroboration']['proofs']:
            credit=phase.get('credit',{})
            if not isinstance(credit,dict) or credit.get('phase')!=phase['phase'] or any(type(credit.get(k)) is not int or credit[k]<=0 for k in ['source_pool_refusals_delta','source_full_samples']):return 1
            endpoints=credit.get('endpoints',[])
            if not isinstance(endpoints,list) or len(endpoints)!=2 or any(not isinstance(e,dict) for e in endpoints):return 1
            fields=phase['channels'][2].get('info',{})
            if not isinstance(fields,dict):return 1
            for endpoint,role in zip(endpoints,['initiator','peer']):
                identity=fields.get(role,[])
                if not isinstance(identity,(list,tuple)) or len(identity)!=11 or any(endpoint.get(k)!=v for k,v in zip(['controller','generation','lifetime','handle'],identity[:4])):return 1
                if endpoint.get('capacity')!=5 or endpoint.get('wire_peak')!=5 or endpoint.get('wire_final_debt')!=0 or not 0<endpoint.get('usb_submissions',0)==endpoint.get('nocp_packets') or not endpoint.get('full_nocp_resume_intervals'):return 1
    if four_benchmark:return 0  # complete dedicated proof checked above,after common gates
    if record.get('status') in ['FOUR_DEVICE_PARALLEL_BUSINESS_PASS','FOUR_DEVICE_DISCONNECT_ISOLATION_PASS','FOUR_DEVICE_PARALLEL_BURST_PASS','FOUR_DEVICE_PARALLEL_OWNED_SSAP_PASS','FOUR_DEVICE_PARALLEL_UPDATE_DELIVERY_PASS','FOUR_DEVICE_PARALLEL_SHARED_SUBSCRIPTION_PASS']:
        isolation=record['status']=='FOUR_DEVICE_DISCONNECT_ISOLATION_PASS'
        burst=record['status']=='FOUR_DEVICE_PARALLEL_BURST_PASS'
        owned=record['status']=='FOUR_DEVICE_PARALLEL_OWNED_SSAP_PASS'
        delivery=record['status']=='FOUR_DEVICE_PARALLEL_UPDATE_DELIVERY_PASS'
        subscription=record['status']=='FOUR_DEVICE_PARALLEL_SHARED_SUBSCRIPTION_PASS'
        proof=record.get('parallel_corroboration',{})
        overlaps=proof.get('overlaps',[])
        if 'four_disconnect_progress_contract_version'in record:
            from ws73_parallel_data import verify_records as verify_parallel_records
            try:
                control=proof['disconnect_progress_control']
                if control.get('disconnect_progress_contract_version')!=1:return 1
                verify_parallel_records(control)
            except (CaptureError,KeyError,TypeError,ValueError,IndexError):return 1
        delivery_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.parallel_delivery=1']
        if delivery_boot!=(['ws73.parallel_delivery=1']if delivery else[]):return 1
        if delivery:
            from ws73_parallel_data import verify_records,delivery_parallel_proof
            try:
                if type(record.get('four_delivery_contract_version'))is not int or record['four_delivery_contract_version']!=1 or type(record.get('four_delivery_security_requirement'))is not int or record['four_delivery_security_requirement']!=2:return 1
                if record.get('live_ssap_security_requirement')!=2:return 1
                control=proof['parallel_delivery_control']
                if control.get('update_delivery_mode')is not True:return 1
                verify_records(control)
                if type(proof.get('parallel_delivery_contract_version'))is not int or proof['parallel_delivery_contract_version']!=1:return 1
                if delivery_parallel_proof(proof['pairs'])!=proof.get('update_delivery'):return 1
            except (CaptureError,KeyError,TypeError,ValueError,IndexError):return 1
        elif 'four_delivery_contract_version'in record or any(k in proof for k in ['parallel_delivery_contract_version','parallel_delivery_control','update_delivery']):return 1
        subscription_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.parallel_subscription=1']
        if subscription_boot!=(['ws73.parallel_subscription=1']if subscription else[]):return 1
        if subscription:
            from ws73_parallel_data import verify_records,subscription_parallel_proof,subscription_case as parallel_case
            try:
                if type(record.get('four_subscription_contract_version'))is not int or record['four_subscription_contract_version']!=1 or type(record.get('four_subscription_security_requirement'))is not int or record['four_subscription_security_requirement']!=2:return 1
                if record.get('live_ssap_security_requirement')!=2:return 1
                words=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()]
                if any(words.count(k)!=1 for k in ['ws73.ssap_subscription=1','ws73.ssap_subscription_shared=1','ws73.subscription_snapshot=1']):return 1
                if any(v.startswith(('ws73.ssap_subscription_renewal=','ws73.ssap_subscription_pressure=','ws73.ssap_subscription_owner_loss=','ws73.ssap_subscription_inflight_release='))for v in words):return 1
                control=proof['parallel_subscription_control']
                if control.get('shared_subscription_mode')is not True:return 1
                case=parallel_case(control)
                if case!=shared_case:return 1
                for field in ('four_subscription_lifetime_contract_version','four_subscription_pressure_contract_version'):
                    expected=case=='pressure'if field=='four_subscription_pressure_contract_version'else case in ('expiry','owner-exit')
                    if expected:
                        if type(record.get(field))is not int or record[field]!=1:return 1
                    elif field in record:return 1
                verify_records(control)
                if type(proof.get('parallel_subscription_contract_version'))is not int or proof['parallel_subscription_contract_version']!=1:return 1
                if subscription_parallel_proof(proof['pairs'],case=case)!=proof.get('shared_subscription'):return 1
                if any(p['subscription_supervision']['daemon']!=w['run']['daemon_before'] for p,w in zip(proof['pairs'],control['workers'],strict=True)):return 1
            except (CaptureError,KeyError,TypeError,ValueError,IndexError):return 1
        elif any(k in record for k in ['four_subscription_contract_version','four_subscription_lifetime_contract_version','four_subscription_pressure_contract_version'])or any(k in proof for k in ['parallel_subscription_contract_version','parallel_subscription_control','shared_subscription']):return 1
        owned_boot=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()if v=='ws73.parallel_owned=1']
        if owned_boot!=(['ws73.parallel_owned=1']if owned else[]):return 1
        if owned or delivery or subscription:
            # The declared scope and actual guest selectors must agree. The
            # shell must not pick Owned by silently overriding another mode.
            words=[v for arg in record.get('qemu_args',[])if isinstance(arg,str)for v in arg.split()]
            if words.count('ws73.parallel=1')!=1 or words.count('ws73.parallel_business=1')!=1:return 1
            if any(v in words for v in ['ws73.parallel_burst=1','ws73.parallel_disconnect=1']):return 1
        if owned:
            from ws73_parallel_data import verify_records,owned_parallel_proof
            try:
                if type(record.get('four_owned_contract_version'))is not int or record['four_owned_contract_version']!=1:return 1
                control=proof['parallel_owned_control']
                if control.get('owned_ssap_mode')is not True:return 1
                verify_records(control)
                if type(proof.get('parallel_owned_contract_version'))is not int or proof['parallel_owned_contract_version']!=1:return 1
                if owned_parallel_proof(proof['pairs'])!=proof.get('owned_ssap'):return 1
            except (CaptureError,KeyError,TypeError,ValueError,IndexError):return 1
        elif any(k in record for k in ['four_owned_contract_version'])or any(k in proof for k in ['parallel_owned_contract_version','parallel_owned_control','owned_ssap']):return 1
        valid=(record.get('four_device_shared_subscription_requested',False)is subscription
               and proof.get('shared_subscription_acceptance',False)is subscription
               and record.get('four_device_update_delivery_requested',False)is delivery
               and proof.get('update_delivery_acceptance',False)is delivery
               and proof.get('protected_ssap_acceptance')is (delivery or subscription)
               and record.get('four_device_owned_requested',False)is owned
               and proof.get('owned_ssap_acceptance',False)is owned
               and record.get('four_device_burst_requested',False) is burst
               and record.get('four_device_disconnect_requested',False) is isolation
               and record.get('four_device_parallel_business') is True
               and record.get('four_device_parallel_rf') is False
               and record.get('qemu_exit')==0
               and proof.get('status')==('FOUR_REAL_PARALLEL_SHARED_SUBSCRIPTION_CORROBORATED'if subscription else 'FOUR_REAL_PARALLEL_UPDATE_DELIVERY_CORROBORATED'if delivery else 'FOUR_REAL_PARALLEL_OWNED_SSAP_CORROBORATED'if owned else 'FOUR_REAL_PARALLEL_BURST_CORROBORATED' if burst else 'FOUR_REAL_DISCONNECT_ISOLATION_CORROBORATED' if isolation else 'FOUR_REAL_PARALLEL_BUSINESS_CORROBORATED')
               and proof.get('controller_count')==4 and proof.get('round_trips')==(64 if burst else 48 if isolation else 80)
               and proof.get('ordinary_uid')==1000
               and proof.get('fixed_basic_channel_business_acceptance') is True
               and proof.get('controlled_disconnect_isolation_acceptance',False) is isolation
               and ('four_disconnect_progress_contract_version'not in record
                    or (isolation and type(record['four_disconnect_progress_contract_version'])is int
                        and record['four_disconnect_progress_contract_version']==1
                        and proof.get('disconnect_progress_contract_version')==1))
               and all(proof.get(k) is False for k in ['fault_isolation_acceptance',
                    'dynamic_channel_acceptance','automatic_fault_recovery_acceptance',
                    'full_goal_complete'])
               and len(proof.get('pairs',[]))==2 and len(overlaps)==2
               and all(p.get('channel',{}).get('status')=='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'
                    and p['channel'].get('round_trips')==(32 if burst else 24 if isolation else 40)
                    and len(p['channel'].get('proofs',[]))==2
                    and all(len(v.get('legs',[]))==(32 if burst else 8 if isolation and n==pair else 40)
                            for n,v in enumerate(p['channel']['proofs']))
                    and len(p.get('connections',[]))==2
                    and all(bool(v.get('ssap_owned',[]))is owned and bool(v.get('ssap_update_delivery',[]))is delivery and bool(v.get('ssap_subscription',[]))is subscription for v in p['channel']['proofs']) for pair,p in enumerate(proof['pairs']))
               and (not burst or valid_parallel_burst(proof))
               and (not isolation or (proof.get('controlled_disconnect_isolation_acceptance') is True
                    and len(proof.get('disconnect_proofs',[]))==2
                    and all(x.get('role_phase')==n and x.get('victim_pair')==n
                        and x.get('survivor_pair')==1-n and len(x.get('before_sequences',[]))>=2
                        and len(x.get('after_down_sequences',[]))>=4
                        for n,x in enumerate(proof['disconnect_proofs']))))
               and all(x.get('role_phase')==n
                    and isinstance(x.get('overlap_wall_ns'),list)
                    and len(x['overlap_wall_ns'])==2
                    and all(type(t) is int for t in x['overlap_wall_ns'])
                    and x['overlap_wall_ns'][0]<x['overlap_wall_ns'][1]
                    for n,x in enumerate(overlaps)))
        return 0 if valid else 1
    if record.get('status') == 'REAL_NUMERIC_COMPARISON_MECHANISM_PASS':
        proof=record.get('connected_file_corroboration',{})
        mode=record.get('live_security_numeric_requested')
        return 0 if (mode in ('numeric-approve','numeric-reject','numeric-late')
            and proof.get('status')=='REAL_NUMERIC_COMPARISON_MECHANISM_CORROBORATED'
            and proof.get('numeric_mode')==mode and proof.get('business_round_trips')==4
            and len(proof.get('controllers',[]))==2 and len(proof.get('business_legs',[]))==16
            and record.get('qemu_exit')==0) else 1
    if record.get('status') == 'REAL_AGENT_POLICY_AND_NATIVE_DELIVERY_PASS':
        proof = record.get('security_agent_corroboration', {})
        business = record.get('channel_socket_corroboration', {})
        phases = proof.get('phases', [])
        mode = record.get('live_security_agent_requested')
        valid = (mode in ['approve','reject','timeout','cancel','agent-exit','caller-exit','cli-approve','cli-reject','install-cancel','numeric-approve','numeric-reject','numeric-late']
                 and proof.get('status') == 'REAL_AGENT_AND_NATIVE_WIRE_AND_APPLICATION_SCOPED_PASS'
                 and len(phases) == 2 and all(p.get('mode') == mode for p in phases)
                 and record.get('ordinary_channel_socket_acceptance') is True
                 and business.get('status') == 'ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED'
                 and business.get('round_trips') == proof.get('business_round_trips')
                 and type(business.get('round_trips')) is int and business['round_trips'] > 0
                 and record.get('qemu_exit') == 0)
        if mode=='install-cancel':
            gate=record.get('security_install_hold',{})
            valid=valid and gate.get('complete') is True and gate.get('qemu_sha256')=='dea80cfc383881b83b16744904be1fff82a8e4d523dfa65f2d96d5268e885e68' and gate.get('corroboration',{}).get('status')=='TWO_ROLE_ACTUAL_INSTALL_WITHDRAWAL_LATE_REPLY_SCOPED_PASS' and len(gate.get('corroboration',{}).get('phases',[]))==2
        return 0 if valid else 1
    return 0 if record.get('status') in ['REAL_SECURITY_ORIGINAL_DEADLINE_PASS','REAL_PASSIVE_AUTHOR_CANCEL_PASS','REAL_UNAUTHENTICATED_LINK_ENCRYPTION_PASS','REAL_CANDIDATE_KEY_AGREEMENT_PASS','REAL_LIMITED_SECURITY_CAPABILITIES_PASS','REAL_CHANNEL_ORIGINAL_DEADLINE_PREFIX_PASS','REAL_CHANNEL_LINK_DOWN_PREFIX_PASS','REAL_CHANNEL_GRANT_PASS','SUPPORT_PASS','PASSTHROUGH_SUPPORT_PASS','FAULT_RECOVERY_SUPPORT_PASS','FOUR_DEVICE_PARALLEL_RF_PASS','FOUR_DEVICE_PARALLEL_RF_CONTRAST_PASS','ENVIRONMENT_FINISHED'] else 1


def run(args):
    # Share the actual flock inode with the existing firmware lab. A lock file
    # alone is never treated as evidence that another process is live.
    if args.command == 'support':
        lab=lab_module()
        with lab.lab_lock(SimpleNamespace(action='target-support',build_dir=args.prepared)):
            return _run(args)
    allocation=resources.policy()
    resources.selected(args.ports, allocation)
    firmware_evidence.requested_mode(args)
    resources.check_paths(args.output, args.prepared, allocation)
    lab=lab_module()
    root=build_workspace()/allocation['run_root'];root.mkdir(parents=True,exist_ok=True)
    # Per-thread VM/run inode; the shared per-port leases still exclude races.
    from build_resources import real_device_vm
    with resources.port_leases(args.ports, allocation) as port_fds:
        # Recheck live assignments after our leaf leases and before launching
        # QEMU. A paused VM's vendor filter can be unsafe without an open fd.
        args._resource_vm_inventory=resources.check_live_vms(list(allocation['ports']), allocation)
        with real_device_vm() as vm_fd:
            args._resource_fds=(*port_fds,vm_fd)
            with lab.lab_lock(SimpleNamespace(action='target-run',build_dir=args.prepared),path=root/'lab.lock'):
                return _run(args)


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    pack=commands.add_parser('prepare')
    for name in ['kernel-build','qemu','busybox','dbus-daemon','firmware-dir','runtime-config-dir']:
        pack.add_argument('--'+name,type=Path)
    pack.add_argument('--output',type=Path,required=True)
    pack.add_argument('--board-model',choices=['U','E'],help='explicit SDK110 single-model build inputs;no cold ROM auto selection')
    pack.add_argument('--from-prepared',type=Path,help='reuse an explicit retained Native carrier with separate compiled identity;no new compilation')
    pack.add_argument('--device-inputs',type=Path,help='version1 ordered leaf/model/firmware_dir/board_dir JSON plan;requires --from-prepared')
    pack.add_argument('--native-verification-openssl',type=Path,help='explicit public-transcript CMAC oracle for retained carriers;validate vector and preserve frozen runtime libraries')
    pack.add_argument('--tcpdump',type=Path)
    pack.add_argument('--python',type=Path)
    for name in native_vm.OPTIONS:
        pack.add_argument('--'+name.replace('_','-'),type=Path,
                          help='optional signed module/NVMe scratch-root VM profile; all three options required')
    pack.add_argument('--controller-directory-clients',action='store_true',help='stage actual C/Python SDK directory consumers for the explicit VM observer gate')
    pack.add_argument('--discovery-lifetime-probe',action='store_true',help='compile/stage optional public Rust SDK TTL consumer only in the isolated native VM;no production install')
    pack.add_argument('--native-return-fixture',action='store_true',help='compile VM-only real SYS_bind return barrier; never default daemon instrumentation')
    pack.add_argument('--native-return-probe',type=Path,help='explicit gdbus executable staged only for direct original-owner retirement observation')
    pack.add_argument('--native-event-retry-test',type=Path,help='explicit compiled test manifest; ignored actual Native receiver VM test only')
    pack.add_argument('--native-channel-fd-probe',type=Path,help='explicit isolated real D-Bus fd client binary; native VM only')
    pack.add_argument('--acb-probe-module',type=Path,help='explicit signed external selftest; never ordinary socket qualification')
    pack.add_argument('--native-discovery-config', type=Path,
                      help='freeze a private slkd TOML config in the native VM; checked by staged slkd, no RF qualification')
    for name in ['run','support']:
        cmd=commands.add_parser(name);cmd.add_argument('--prepared',type=Path,required=True);cmd.add_argument('--output',type=Path,required=True)
        cmd.add_argument('--timeout',type=float,default=120 if name=='support' else 1800)
        if name=='run':
            cmd.add_argument('--ports',nargs='+',required=True)
            cmd.add_argument('--link-payload-preference',choices=['reported-acb-maximum'],help='one explicit Managed payload preference per controller/lifetime;acknowledgment is not effective length or performance')
            cmd.add_argument('--link-measurements',action='store_true',help='finite actual Managed RSSI/PHY observations before the ordinary workload;not RF policy or performance proof')
            cmd.add_argument('--runtime-addresses',nargs=2,help='explicit temporary volatile E pair addresses;Native setup before daemon,not official identity')
            cmd.add_argument('--firmware-evidence',choices=firmware_evidence.MODES,
                             help='required physical scope: rom-upload demands actual inputs before every observed Runtime; runtime-observation grants no loaded-image qualification')
            cmd.add_argument('--four-device-shared-subscription',action='store_true',help='two pairs/full shared release,original-expiry or reader-exit matrix with actual UID1004 readers/1005 publishers and closed snapshots;protected2/original80socketreplies')
            cmd.add_argument('--four-device-update-delivery',action='store_true',help='two real pairs/full update-v2 matrix after actual numeric protected2;original80socketreplies and real receivercheck/reply')
            cmd.add_argument('--four-device-owned',action='store_true',help='two real pairs/two roles;existing Owned SSAP approval,denial,owner loss and actual wire overlap plus original80shortreplies')
            cmd.add_argument('--four-device-dynamic-benchmark',action='store_true',help='two pairs of existing Root supervised apps-only short/long dynamic channels;144actual peer replies/16applications;not performance or full fairness qualification')
            cmd.add_argument('--four-device-benchmark-case',choices=['parallel','close-short','pressure'],default='parallel',help='explicit v3 short close or v4 software EAGAIN recovery;336 replies;default parallel144 unchanged')
            cmd.add_argument('--four-device-burst',action='store_true',help='two real pairs,2roles16replies2042bytes each:64actual app replies,USB fragmentation,finite-queue pressure and observed pool/NOCP resumption;not fairness or credit correctness proof')
            cmd.add_argument('--four-device-disconnect',action='store_true',help='dedicated four-real-device controlled pair Disconnect/Down while other pair continues actual replies; alternates victims, no fault/recovery claim')
            cmd.add_argument('--four-device-business',action='store_true',help='four real controllers, two physical pairs, two connection roles, 80 ordinary app round trips; positive fixed-channel slice only')
            cmd.add_argument('--parallel-pairs',action='store_true',help='four actual radios, two live pairs; per-round match barrier and raw START/OFF overlap proof, no hotplug or injection')
            cmd.add_argument('--parallel-start-offset-ms',type=int,default=0,help='0..125 ms explicit second-pair timing contrast; never replaces the default parallel gate')
            cmd.add_argument('--early-bootstrap-fault',action='store_true',help='separate native three-real-device missing-custom fault, ordinary Core diagnostics and peer business; controlled QMP retry only')
            from ws73_usb_partial_diagnostic import target_value,phase_value
            cmd.add_argument('--usb-partial-rx-target',type=target_value,help='0,1,peer-of-unfinished orsource-of-unfinished within explicit pair;single VM USB detach after declared PB prefix and2s quiet;diagnostic only,never business/recovery PASS')
            cmd.add_argument('--usb-partial-rx-phase',type=phase_value,default=1,help='0,1 oractive within original phases;default1 preserves old diagnostic scope;requires explicit target')
            cmd.add_argument('--daemon-cancel-remove',action='store_true',help='cancel while actual reply held, remove/re-add only that guest owner; requires --qmp-hotplug; excludes physical/automatic recovery')
            cmd.add_argument('--channel-daemon-crash',action='store_true',help='actual slkd SIGKILL with ordinary retained business fd, successor and no USB reset')
            cmd.add_argument('--security-agent',choices=['approve','reject','timeout','cancel','agent-exit','caller-exit','cli-approve','cli-reject','install-cancel','numeric-approve','numeric-reject','numeric-late'],help='actual ordinary Agent policy plus current native relay and peer application evidence; requires separate connection/socket gate')
            cmd.add_argument('--channel-daemon-index',type=int,choices=[0,1],default=0)
            cmd.add_argument('--daemon-crash',action='store_true',help='actual active-radio SIGKILL/last-File cleanup and successor before native RF22; separate --qmp-hotplug mode')
            cmd.add_argument('--observer-policy',action='store_true',help='actual default observer/control read and denial roles before/after native RF22; separate --qmp-hotplug mode')
            cmd.add_argument('--initializer-lifecycle',action='store_true',help='real initializer withdrawal, eviction and guest-generation gate; separate native --qmp-hotplug mode')
            cmd.add_argument('--daemon-hold-case',choices=['supersede','caller-exit','cancel-caller-exit','cancel-busy','cancel-admission'],help='ordinary D-Bus callers cancel an original successful held reply with same daemon and active peer')
            cmd.add_argument('--managed-ordinary-eviction',action='store_true',help='two SCHED_OTHER ioctl submitters and terminal result eviction under actual held first reply; separate Ready-peer VM gate')
            cmd.add_argument('--managed-partial-case',choices=['release','close','dup'],help='one actual first-step held-reply cleanup case; requires separate Setup/recovery VM')
            cmd.add_argument('--managed-connected-case',choices=['release','close','dup'],help='actual established-link File cleanup before daemon; separate Setup/recovery VM')
            cmd.add_argument('--managed-link-snapshot',action='store_true',help='actual canonical physical table/lifetime/barrier and VFS read errors; established File gate only')
            cmd.add_argument('--managed-peer-binding',action='store_true',help='actual peer/lifetime mismatch rejection without wire commands; established File gate only')
            cmd.add_argument('--managed-connected-reply',choices=['status','outcome'],help='retain actual original Create Status or outcome frame before File withdrawal')
            cmd.add_argument('--managed-channel-scm-rights',action='store_true',help='ordinary receiver gets real channel via SCM_RIGHTS after inherited authority closes')
            cmd.add_argument('--managed-channel-directions',action='store_true',help='real TX-only/RX-only one-way delivery and opposite-action/protected-bind denial')
            cmd.add_argument('--managed-channel-security',type=int,choices=[0,1,2],default=0,help='VM-only existing positive mechanism before first protected CUTC bind;then original prefix/File/Down/deadline lifecycle,not Agent/Bond/recovery')
            cmd.add_argument('--managed-channel-sibling-business',action='store_true',help='dedicated same-kernel four-controller basic File/Down/deadline victim index0|1 prefix and real ordinary sibling-link replies;no daemon policy qualification')
            cmd.add_argument('--managed-channel-grant',action='store_true',help='real ordinary blocked socket RX across Managed release/final File/dup and successor; separate established File gate')
            cmd.add_argument('--managed-security-kind',choices=['capabilities','key-agreement','unauthenticated-encryption','cancel-pending','original-deadline','numeric-approve','numeric-reject','numeric-late'],default='capabilities',help='explicit capability, candidate proof or unauthenticated encryption mechanism; not Agent/identity/Bond')
            cmd.add_argument('--managed-security-capabilities',action='store_true',help='explicit Managed security negotiation gate; select bounded kind, never Pair/Encrypted')
            cmd.add_argument('--managed-channel-deadline',action='store_true',help='original5s begun-PDU deadline with separate bounded8s real IN81 hold, not recovery')
            cmd.add_argument('--managed-channel-link-down',action='store_true',help='direct physical Disconnect after actual begun PDU while both Managed leases remain held; separate from revoke/deadline/recovery')
            cmd.add_argument('--session-service-observe',action='store_true',help='dedicated default-off real Session service/queue/atomic USB trace;not performance or peer delivery proof')
            cmd.add_argument('--session-service-profile',choices=['full-load-v2'],help='explicit bounded8MiB/CPU32MiBtext100k-event collector;requires service observation,not performance qualification')
            cmd.add_argument('--managed-channel-queued-discard',action='store_true',help='explicit two queued2042B admissions behind held begunPDU;requires Managed prefix and Session trace,not business/recovery proof')
            cmd.add_argument('--managed-channel-idle-observe',action='store_true',help='dedicated VM ftrace of drained Session idle between real business and controlled prefix;not performance qualification')
            cmd.add_argument('--managed-channel-revoke-prefix',action='store_true',help='actual partial2042-byte USB PDU across per-controller Managed withdrawal, never natural recovery')
            cmd.add_argument('--managed-connected-index',type=int,choices=[0,1],default=0,help='actual Create caller in established-link File gate')
            cmd.add_argument('--managed-resource-recreate',action='store_true',help='actual changed advertising set removal/creation File cancellation; requires selected advertising Ready-peer partial gate')
            cmd.add_argument('--managed-partial-domain',choices=['advertising','scanning'],default='advertising')
            cmd.add_argument('--managed-real-later-step',type=int,choices=[1,2],help='real host later frame selector; requires selected partial and Ready peer; adv only step1')
            cmd.add_argument('--managed-ready-peer',action='store_true',help='real Ready Managed scanning peer across target cancellation/Free')
            cmd.add_argument('--managed-selected-cleanup',action='store_true',help='new real first-step gate: untouched Unknown is not Ready; requires --managed-partial-case')
            cmd.add_argument('--managed-scan-parameter-cleanup',action='store_true',help='new scan first-step gate: Unknown remains Setup; requires selected scanning partial gate')
            cmd.add_argument('--managed-queue-connections',action='store_true',help='native queued Create release/last File/dup and privacy, requires confirmed-Off Ready peer queue gate')
            cmd.add_argument('--managed-queue-ready-peer',action='store_true',help='real independently Ready scanner On across never-selected cancellations')
            cmd.add_argument('--managed-queue-confirmed-off',action='store_true',help='complete initialization before full scanning initializer queue cancellation; requires --managed-queue-verify')
            cmd.add_argument('--managed-queue-verify',action='store_true',help='bounded one-vCPU FIFO real queued-policy cancellation; requires Setup and recovery gates; not ordinary concurrency acceptance')
            cmd.add_argument('--setup-release-verify',action='store_true',help='pre-daemon untouched Setup release/last-fd/dup gate; requires real fault-recovery scratch VM')
            cmd.add_argument('--native-event-retry-verify',action='store_true',help='actual Native subscriber retry lock/cancel/join; requires staged test and ordinary connection gate')
            cmd.add_argument('--event-copy-verify',action='store_true',help='opt-in live VFS usercopy gate before real recovery/RF; requires --fault-recovery')
            cmd.add_argument('--active-deadline-verify',action='store_true',help='separate pre-daemon real IN81 timeout/abort gate; requires real fault-recovery and excludes explicit-release diagnostic modes')
            cmd.add_argument('--active-close-verify',action='store_true',help='actual held IN81 original/last dup close and bounded original-deadline retirement; requires separate real fault-recovery VM')
            cmd.add_argument('--diagnostic-verify',action='store_true',help='opt-in live diagnostic owner/CAP/copy/retirement and metadata CLI gate; requires --fault-recovery')
            cmd.add_argument('--diagnostic-autonomous-verify',action='store_true',help='queued expiry already counted before first result after a passive800ms window; requires all diagnostic/cancel/deadline/fault-recovery gates')
            cmd.add_argument('--diagnostic-deadline-verify',action='store_true',help='100ms queued expiry with continuous same-ID retries; requires --diagnostic-cancel-verify and real fault-recovery mode')
            cmd.add_argument('--diagnostic-cancel-verify',action='store_true',help='hold one real IN81 to test active/queued cancel and late reply; requires --diagnostic-verify and --fault-recovery')
            cmd.add_argument('--daemon-link-resync',action='store_true',help='actual VM subscriber pause, real event ring overflow and canonical resync; requires connection verification')
            cmd.add_argument('--channel-socket-bytes',type=int,default=61,help='application message size 29..2042 within the negotiated basic channel')
            cmd.add_argument('--channel-socket-burst',action='store_true',help='actual16-message software queue EAGAIN/poll recovery and opposite application replies; not hardware credit depletion')
            cmd.add_argument('--channel-socket-close-prefix',action='store_true',help='require captured first USB submit, final fd close, remaining PDU and actual peer/other-channel traffic')
            cmd.add_argument('--channel-socket-boundaries',action='store_true',help='require original EMSGSIZE and no USB traffic for oversized messages')
            cmd.add_argument('--channel-socket-rounds',type=int,choices=range(1,21),default=4,help='bounded application rounds per connection role')
            cmd.add_argument('--connection-down-failure-observe-seconds',type=int,choices=[0,6,12],default=0,
                             help='passive capture before cleanup after original Down timeout; original gate remains failed')
            cmd.add_argument('--dynamic-channel-burst',action='store_true',help='require actual dynamic C16x2042 burst/credit/peer-reply evidence;requires dynamic2042 gate')
            cmd.add_argument('--dynamic-channel-long-bytes',type=int,choices=[249,250,253,254,255,1024,2042],help='extend dynamic gate with long C channel and explicit lifetime slot exhaustion;requires --dynamic-channel-verify')
            cmd.add_argument('--channel-fairness-verify',action='store_true',help='separate short20/long16x2042 real concurrent channel progress,not fullfairness/performance proof')
            cmd.add_argument('--dynamic-channel-verify',action='store_true',help='actual two-channel CMTC/asymmetricTCID/app delivery/close isolation, separate bounded VM gate')
            cmd.add_argument('--channel-benchmark-window',type=int,default=4,help='bounded application window1..min(count,256),not protocol credit')
            cmd.add_argument('--channel-benchmark-count',type=int,default=20,help='messages per initiator per role,1..10000')
            cmd.add_argument('--channel-benchmark-bytes',type=int,default=61,help='application datagram bytes29..2042,including29byte test header')
            cmd.add_argument('--channel-benchmark-interval-us',type=int,help='rate-only absolute interval10..1000000us,default100000;totalplan<=600s')
            cmd.add_argument('--channel-benchmark-xhci',choices=['on','off'],default='on',help='VM-only xHCI trace comparison;usbmon remains enabled')
            cmd.add_argument('--channel-benchmark',choices=['rate','window','duplex'],help='separate bounded real application benchmark in both connection roles;not performance qualification')
            cmd.add_argument('--channel-benchmark-dynamic',action='store_true',help='explicit basic dynamic endpoint target;requires real CMTC and paired business evidence')
            cmd.add_argument('--channel-benchmark-parallel',action='store_true',help='finite four-app short/long load on two dynamic channels;requires default window workload')
            cmd.add_argument('--channel-benchmark-close-short',action='store_true')
            cmd.add_argument('--channel-benchmark-pressure',action='store_true',help='explicit two-device v4 short20x61/window4 andlong64x2042/window16;requires actual EAGAIN then timely peer replies,not credit truth or full fairness')
            cmd.add_argument('--channel-benchmark-ssap-owned',action='store_true',help='fixed128x2042/window8 dynamic correctness load with actual ordinary Owned SSAP callers;not performance')
            cmd.add_argument('--channel-benchmark-ssap-duplex',action='store_true',help='pair actual opposite-controller SDK steps with USB pending overlap;requires --channel-benchmark-ssap-owned;not a sequential-gate replacement')
            cmd.add_argument('--channel-benchmark-credit-observe',action='store_true',help='explicit finite ordinary GetTransportStatus observation during Owned SSAP load;not credit/drain/performance qualification')
            cmd.add_argument('--channel-benchmark-hcc-memory-observe',action='store_true',help='opt-in root-only bounded fixed HCC memory query during original observed SSAP load;raw/unsupported,not verified credit or recovery')
            cmd.add_argument('--channel-benchmark-link-probe',action='store_true',help='one existing Managed RSSI attempt per endpoint six seconds after each phase start;requires initial link/credit observations;not RF delivery,drain or performance')
            cmd.add_argument('--channel-benchmark-active-endpoint',type=int,choices=[0,1],help='dynamic negotiation role independent of business direction;default0 when dynamic')
            cmd.add_argument('--ssap-service-policy',action='store_true',help='actual guest system-bus service-only role matrix;separate from RF and full authorization')
            cmd.add_argument('--native-return-verify',action='store_true',help='VM-only actual Native bind-return/physical Down/parent cleanup,then ordinary data preservation')
            cmd.add_argument('--native-controller-return',choices=['initiator','acceptor'],help='actual User bind return across existing one-leaf QMP removal; original socket gate runs after re-add')
            cmd.add_argument('--controller-directory-events',action='store_true',help='actual Rust/C/Python ordinary directory observers;requires prepared --controller-directory-clients and existing controller-return gate')
            cmd.add_argument('--ssap-initialization-verify',action='store_true',help='real negotiation-stage lease revoke/fd convergence then ordinary same-artifact connection/socket preservation')
            cmd.add_argument('--ssap-initialization-stage',choices=['cmtc','exchange'],default='cmtc')
            cmd.add_argument('--ssap-owned-update-verify',action='store_true')
            cmd.add_argument('--ssap-subscription-verify',action='store_true',help='real protected continuous caller-owned lease,multiple random updates and actual apps-only distinct replies')
            cmd.add_argument('--ssap-subscription-shared-verify',action='store_true',help='two actual SDK subscribers,partial retained release and last physical cleanup;dedicated gate')
            cmd.add_argument('--ssap-subscription-shared-case',choices=('release','expiry','owner-exit','pressure'),default='release',help='separate release,original expiry,reader exit or bounded slow-reader isolation;not kernel Grant revocation')
            cmd.add_argument('--ssap-subscription-renewal-verify',action='store_true',help='actual same-token long renewal and checked replies beyond original short lease expiry;requires subscription gate')
            cmd.add_argument('--ssap-subscription-pressure-verify',action='store_true',help='actual bounded subscriber queue full/refusal,ordered drain and checked resume;separate from controller credit pressure')
            cmd.add_argument('--ssap-subscription-owner-loss-verify',action='store_true',help='actual guest reader death,paired cleanup/read barrier and fresh same-Session subscription;not full lifecycle qualification')
            cmd.add_argument('--ssap-subscription-inflight-release-verify',action='store_true',help='release while real indication ACK RX is withheld;actual disableTX barrier,discard and fresh lease business;not expiry qualification')
            cmd.add_argument('--ssap-subscription-inflight-case',choices=['release','expiry'],default='release',help='explicit original lease expiry or application release,through same bounded in-flight gate')
            cmd.add_argument('--ssap-update-delivery-verify',action='store_true',help='real typed/authenticated CPCD,notification/indication and C/Python peer business reply')
            cmd.add_argument('--ssap-update-lifecycle-verify',action='store_true',help='dedicated same-actor receiver exit,original deadline and confirmed CPCD cleanup;requires update delivery')
            cmd.add_argument('--ssap-sender-deadline-verify',action='store_true',help='original1s SDK deadline with bounded2s real IN81 hold,late ACK and actual peer reply;requires dedicated update delivery')
            cmd.add_argument('--ssap-sender-lifecycle-case',choices=['deadline','owner-after-deadline'],default='deadline',help='same controlled barrier;owner-after-deadline requires actual owner death andpaired oldservice refusals')
            cmd.add_argument('--ssap-value-lengths-verify',action='store_true',help='dedicated real value lengths, bounded SSAP sequence fragmentation and MTU refusal gate;not full protocol qualification')
            cmd.add_argument('--ssap-owner-lifecycle-verify',action='store_true',help='actual owner exit/stale prompt/original deadline with ordinary CUTC afterwards')
            cmd.add_argument('--ssap-owner-publisher',choices=['cli','sdk'],default='cli',help='explicit owner frontend;SDK selects C/Python per role,no fallback')
            cmd.add_argument('--ssap-requester-lifecycle-verify',action='store_true',help='actual C/Python requester death/old reply drain and ordinary CUTC while real owner prompt held')
            cmd.add_argument('--ssap-owned-verify',action='store_true',help='real owner authorization and exit cleanup;not complete SSAP or service-only policy qualification')
            cmd.add_argument('--ssap-description-verify',action='store_true',help='with --ssap-owned-verify: actual public read-only UTF-8 description discovery and C/Python read')
            cmd.add_argument('--ssap-read-provider-verify',action='store_true',help='with --ssap-owned-verify: actual Owned dynamic READ callbacks and C/Python peer value comparison')
            cmd.add_argument('--ssap-sdk-read-provider-verify',action='store_true',help='with --ssap-read-provider-verify: actual C/Python Provider values and opposite-language peer verification')
            cmd.add_argument('--ssap-sdk-write-provider-verify',action='store_true',help='with --ssap-owned-verify: actual C/Python WRITE Provider rejection and2037/2042-byte verified values, paired USB evidence')
            cmd.add_argument('--ssap-write-provider-unregister-verify',action='store_true',help='dedicated Owned/ordinary gate: pending C/Python WRITE unregister, original deadline, paired peer refusal and independent guard')
            cmd.add_argument('--ssap-write-provider-owner-exit-verify',action='store_true',help='dedicated Owned/ordinary gate: pending C/Python WRITE owner death, original deadline, paired peer refusal and independent guard')
            cmd.add_argument('--ssap-write-provider-down-verify',action='store_true',help='dedicated Owned/ordinary gate: actual pending WRITE callback before typed Disconnect and two-end Down')
            cmd.add_argument('--ssap-write-provider-deadline-verify',action='store_true',help='dedicated Owned/ordinary gate: pending C/Python WRITE original expiry, rejected late reply, paired request and independent ordinary business')
            cmd.add_argument('--ssap-provider-owner-exit-verify',action='store_true',help='with --ssap-read-provider-verify: version2 C/Python pending SDK Provider owner loss, peer refusal and independent guard delivery')
            cmd.add_argument('--ssap-provider-unregister-verify',action='store_true',help='with --ssap-read-provider-verify: C/Python pending explicit unregister, retained request/fd, peer refusal and live independent guard')
            cmd.add_argument('--ssap-provider-deadline-verify',action='store_true',help='with --ssap-provider-owner-exit-verify: SDK Provider original deadline, actual late ETIMEDOUT and independent ordinary CUTC delivery; no same-actor recovery')
            cmd.add_argument('--ssap-write-command-verify',action='store_true',help='actual C/Python WRITE_NO_RSP with remote Read,owner readback and paired capture;not admission-only delivery')
            cmd.add_argument('--ssap-write-command-policy-verify',action='store_true',help='add actual command refusal and same-owner deny/allow after each phase positives;retain all24 cases;requires --ssap-write-command-verify')
            cmd.add_argument('--ssap-write-command-deadline-verify',action='store_true',help='original command authorization timeout and ordinary business;requires policy gate;not automatic recovery')
            cmd.add_argument('--channel-socket-verify',action='store_true',help='ordinary dual application real channel round trips and CMTC, without test module')
            cmd.add_argument('--application-discovery-verify',action='store_true',help='actual apps-only shared discovery, two scanner roles; optional ordinary connection/socket preservation')
            cmd.add_argument('--application-discovery-case',choices=['release','owner-loss','ttl','sdk-release'],default='release',help='bounded release/caller-loss/TTL;TTL requires prepared live-caller SDK probe;not full lifecycle/recovery qualification')
            cmd.add_argument('--application-client-verify',action='store_true',help='dedicated real public C/Python SDK one-shot/dup/final-close gate;not fullSDK orpermission qualification')
            cmd.add_argument('--acb-transport-probe',action='store_true',help='explicit signed external-module real ACB transport probe; excludes ordinary socket acceptance')
            cmd.add_argument('--connection-verify',action='store_true',help='real typed Connect/Disconnect plus raw outcomes; requires separate --qmp-hotplug VM')
            cmd.add_argument('--connection-advertising',choices=['fixed-t','negotiable-t'],default='fixed-t',help='explicit announcement contrast for --connection-verify')
            modes=cmd.add_mutually_exclusive_group()
            modes.add_argument('--qmp-hotplug',action='store_true',help='real RF with QMP guest-only disconnect/reconnect; never physical unplug or automatic recovery acceptance')
            modes.add_argument('--fault-recovery',action='store_true',help='one opt-in artificial guest bulk IN81 error with real radios; never natural-fault or physical unplug acceptance')
        else:
            cmd.add_argument('--empty-bulk',action='store_true',help='inject successful zero-length bulk IN before synthetic runtime replies; never a physical option')
            cmd.add_argument('--hotplug',action='store_true',help='run the full control orchestrator with explicitly synthetic USB removal/replug; never physical acceptance')
            cmd.add_argument('--warm',action='store_true',help='synthetic one-shot BSP already consumed; require warm restore')
    args=parser.parse_args()
    if not math.isfinite(getattr(args,'timeout',1)) or getattr(args,'timeout',1)<=0:parser.error('timeout must be finite and positive')
    return prepare(args) if args.command=='prepare' else run(args)


if __name__=='__main__':raise SystemExit(main())
