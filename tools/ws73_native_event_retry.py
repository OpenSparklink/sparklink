"""Explicit VM-only execution of the actual Native EventTask unit-test binary.

No alternate event loop. The default daemon contains neither test rendezvous nor
this ignored test. Existing runner retains device leases, capture and RF gates.
"""
import hashlib
import json
from pathlib import Path

BINARY = '/bin/native-event-retry-test'
TEST = 'event_loop::tests::native_retry_real_subscription_vm'
TOKEN = 'ws73.native_event_retry'
CONFIG = '/usr/share/sparklink/native-event-test-dbus.conf'
SUITE = '/usr/share/sparklink/native-event-test-suite.json'
QUIET_TEST = 'event_loop::tests::native_quiet_real_subscription_vm'


def pin(path):
    path = Path(path)
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def boot_requested(tokens):
    values = [x for x in tokens if x == TOKEN or x.startswith(TOKEN + '=')]
    if values not in ([], [TOKEN + '=1']):
        raise ValueError('one explicit Native retry test selector required')
    return bool(values)


def requested(args, package=None, *, passthrough=None):
    value = getattr(args, 'native_event_retry_verify', False)
    if type(value) is not bool:
        raise ValueError('typed Native retry selector required')
    if value:
        real = getattr(args, 'qmp_hotplug', False) if passthrough is None else passthrough
        if not real or not getattr(args, 'connection_verify', False) or not getattr(args, 'channel_socket_verify', False):
            raise ValueError('Native retry requires existing real connection and ordinary channel gate')
        if package is not None and ('native_vm' not in package or type(package.get('native_event_retry_test', {}).get('version')) is not int or package['native_event_retry_test']['version'] not in (1, 2)):
            raise ValueError('explicit staged Native retry test binary required')
    return value


def stage(spec, root, manifest, copy_elf):
    spec = Path(spec).resolve(strict=True)
    data = json.loads(spec.read_text())
    if type(data.get('version')) is not int or data['version'] not in (1, 2) or data.get('source_head') != manifest['userspace_head']:
        raise ValueError('exact compiled test source identity required')
    source = Path(data['binary']['path']).resolve(strict=True)
    before = pin(source)
    if before != data['binary']:
        raise ValueError('compiled Native retry test bytes changed')
    target = root / BINARY.lstrip('/')
    copy_elf(source, target, root)
    target.chmod(0o755)
    if pin(source) != before:
        raise ValueError('Native retry test changed while staging')
    config = root / CONFIG.lstrip('/')
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=/tmp</listen>'
        '<auth>EXTERNAL</auth><policy context="default"><allow user="*"/>'
        '<allow own="*"/><allow send_destination="*"/><allow receive_sender="*"/>'
        '</policy></busconfig>\n')
    suite = root / SUITE.lstrip('/')
    suite.write_text(json.dumps(dict(version=data['version'])) + '\n')
    manifest['native_event_retry_test'] = dict(version=data['version'], source_head=data['source_head'],
        source_manifest=pin(spec), input=before, program=pin(target), config=pin(config), suite=pin(suite))
    manifest['inputs'].append(pin(spec))
    manifest['unstripped_programs'].append(before)


def parse(row, owner, sibling):
    expected_env = dict(SPARKLINK_NATIVE_EVENT_VM='1', SPARKLINK_TEST_DBUS_DAEMON='/bin/dbus-daemon',
        SPARKLINK_NATIVE_EVENT_TARGET=f"{owner['index']}:{owner['generation']}",
        SPARKLINK_NATIVE_EVENT_SIBLING=f"{sibling['index']}:{sibling['generation']}")
    if (type(row.get('exit')) is not int or row.get('exit') != 0 or row.get('stderr') or row.get('environment') != expected_env
            or row.get('args') != [BINARY, '--quiet', '--ignored', '--exact', TEST, '--nocapture', '--test-threads=1']
            or 'test result: ok. 1 passed; 0 failed; 0 ignored;' not in row.get('stdout', '')):
        raise ValueError('actual exact ignored test must complete successfully')
    lines = [x.removeprefix('NativeRetryVm: ') for x in row['stdout'].splitlines() if x.startswith('NativeRetryVm: ')]
    if len(lines) != 1:
        raise ValueError('exactly one actual Native retry receipt required')
    value = json.loads(lines[0])
    expected = dict(index=owner['index'], generation=owner['generation'],
        sibling_index=sibling['index'], sibling_generation=sibling['generation'],
        initial_kernel_snapshot=True, retry_pending_with_lock_held=True,
        joined_with_lock_held=True, subscription_fd_closed=True, both_still_ready=True)
    if value != expected or any(type(value[k]) is not type(v) for k, v in expected.items()):
        raise ValueError('Native identity/held lock/join/fd/peer receipt differs')
    if (any(type(row.get(k)) is not int for k in ('start_monotonic_ns','end_monotonic_ns'))
            or not 0 <= row['end_monotonic_ns'] - row['start_monotonic_ns'] <= 10_000_000_000):
        raise ValueError('Native test original supervisor deadline exceeded')
    return value



def parse_quiet(row, owner, sibling):
    # Share the exact command/environment/identity/fd checks, but retain the
    # original ten-second retry deadline. Quiet observation has its own bound.
    if (type(row.get('exit')) is not int or row['exit'] != 0 or row.get('stderr')
            or row.get('args') != [BINARY, '--quiet', '--ignored', '--exact', QUIET_TEST, '--nocapture', '--test-threads=1']
            or 'test result: ok. 1 passed; 0 failed; 0 ignored;' not in row.get('stdout', '')):
        raise ValueError('actual quiet test must run exactly once and succeed')
    env = dict(SPARKLINK_NATIVE_EVENT_VM='1', SPARKLINK_TEST_DBUS_DAEMON='/bin/dbus-daemon',
        SPARKLINK_NATIVE_EVENT_TARGET=f"{owner['index']}:{owner['generation']}",
        SPARKLINK_NATIVE_EVENT_SIBLING=f"{sibling['index']}:{sibling['generation']}")
    if row.get('environment') != env:
        raise ValueError('quiet test environment differs')
    lines = [x.removeprefix('NativeQuietVm: ') for x in row['stdout'].splitlines() if x.startswith('NativeQuietVm: ')]
    if len(lines) != 1:
        raise ValueError('exactly one actual quiet receipt required')
    value = json.loads(lines[0])
    validate_quiet(value, owner, sibling)
    if any(type(row.get(k)) is not int for k in ('start_monotonic_ns', 'end_monotonic_ns')):
        raise ValueError('quiet supervisor timestamps required')
    elapsed = row['end_monotonic_ns'] - row['start_monotonic_ns']
    if not value['quiet_ms'] * 1_000_000 <= elapsed <= 40_000_000_000:
        raise ValueError('quiet observation/supervisor original deadline differs')
    return value


def validate_quiet(value, owner, sibling):
    expected = dict(index=owner['index'], generation=owner['generation'],
        sibling_index=sibling['index'], sibling_generation=sibling['generation'],
        receive_completions=0, actual_native_loop=True, kernel_watermark_unchanged=True,
        query_verified=True, scan_rejected_without_lease=True, connect_rejected_without_lease=True,
        subscription_fd_closed=True, both_still_ready=True)
    if set(value) != set(expected) | {'quiet_ms', 'rounds', 'pending_polls'}:
        raise ValueError('quiet receipt fields differ')
    if any(type(value[k]) is not type(v) or value[k] != v for k, v in expected.items()):
        raise ValueError('quiet identity/real receive/handler/peer check differs')
    if (type(value['quiet_ms']) is not int or not 30_000 <= value['quiet_ms'] <= 35_000
            or type(value['rounds']) is not int or not 10 <= value['rounds'] <= 140
            or type(value['pending_polls']) is not int or value['pending_polls'] <= 0):
        raise ValueError('actual quiet duration/queries/live receiver required')

def execute(run, owners):
    suite = json.loads(Path(SUITE).read_text())
    if type(suite.get('version')) is not int or suite['version'] not in (1, 2):
        raise ValueError('explicit staged suite version required')
    evidence = dict(version=suite['version'], binary=pin(BINARY), owners=owners, receipts=[])
    if suite['version'] == 2:
        evidence['quiet_receipts'] = []
    run.data['native_event_retry'] = evidence
    run.save()
    for owner, sibling in (owners, owners[::-1]):
        row = run.command([BINARY, '--quiet', '--ignored', '--exact', TEST, '--nocapture', '--test-threads=1'],
            10, collection='native_event_retry_commands', environment=dict(
                SPARKLINK_NATIVE_EVENT_VM='1', SPARKLINK_TEST_DBUS_DAEMON='/bin/dbus-daemon',
                SPARKLINK_NATIVE_EVENT_TARGET=f"{owner['index']}:{owner['generation']}",
                SPARKLINK_NATIVE_EVENT_SIBLING=f"{sibling['index']}:{sibling['generation']}"))
        evidence['receipts'].append(parse(row, owner, sibling))
        run.save()
        if suite['version'] == 2:
            quiet_row = run.command([BINARY, '--quiet', '--ignored', '--exact', QUIET_TEST, '--nocapture', '--test-threads=1'],
                40, collection='native_event_quiet_commands', environment=row['environment'])
            evidence['quiet_receipts'].append(parse_quiet(quiet_row, owner, sibling))
        run.check(owner)
        run.check(sibling)
        run.save()


def corroborate(control, package):
    evidence = control['native_event_retry']
    owners = control['connection_control']['owners']
    rows = control['native_event_retry_commands']
    staged = package['native_event_retry_test']['program']
    if (type(evidence.get('version')) is not int or evidence['version'] not in (1, 2)
            or type(package['native_event_retry_test']['version']) is not int
            or evidence['version'] != package['native_event_retry_test']['version'] or evidence['owners'] != owners or len(rows) != 2
            or evidence['binary'] != dict(path=BINARY, sha256=staged['sha256'])):
        raise ValueError('two actual selected subscriptions and exact test binary required')
    receipts = [parse(row, a, b) for row, (a, b) in zip(rows, (owners, owners[::-1]), strict=True)]
    if receipts != evidence['receipts']:
        raise ValueError('recorded Native receipt differs from original output')
    proof = dict(version=evidence['version'], actual_subscriptions=2, owners=owners, receipts=receipts, binary=evidence['binary'])
    if evidence['version'] == 2:
        quiet_rows = control['native_event_quiet_commands']
        if len(quiet_rows) != 2:
            raise ValueError('quiet gate must run on both selected controllers')
        quiet = [parse_quiet(row, a, b) for row, (a, b) in zip(quiet_rows, (owners, owners[::-1]), strict=True)]
        if quiet != evidence['quiet_receipts']:
            raise ValueError('quiet receipt differs from actual output')
        proof['quiet_receipts'] = quiet
    elif 'quiet_receipts' in evidence or 'native_event_quiet_commands' in control:
        raise ValueError('legacy v1 cannot claim Native quiet coverage')
    return proof


def accepted(record):
    value = record.get('native_event_retry_requested', False)
    if type(value) is not bool:
        return False
    if not value:
        return not record.get('native_event_retry_acceptance', False) and 'native_event_retry_corroboration' not in record
    proof = record.get('native_event_retry_corroboration', {})
    try:
        owners = proof['owners']
        if (record.get('native_event_retry_acceptance') is not True
                or type(proof['version']) is not int or proof['version'] not in (1, 2)
                or type(record['native_event_retry_test']['version']) is not int
                or proof['version'] != record['native_event_retry_test']['version']
                or type(proof['actual_subscriptions']) is not int or proof['actual_subscriptions'] != 2
                or len(owners) != 2 or owners[0]['index'] == owners[1]['index']
                or len(proof['receipts']) != 2
                or proof['binary'] != dict(path=BINARY, sha256=record['native_event_retry_test']['program']['sha256'])):
            return False
        for receipt, (owner, sibling) in zip(proof['receipts'], (owners, owners[::-1]), strict=True):
            for key, expected in dict(index=owner['index'],generation=owner['generation'],
                    sibling_index=sibling['index'],sibling_generation=sibling['generation']).items():
                if type(receipt.get(key)) is not int or receipt[key] != expected:
                    return False
            if not all(receipt.get(k) is True for k in ['initial_kernel_snapshot', 'retry_pending_with_lock_held',
                    'joined_with_lock_held', 'subscription_fd_closed', 'both_still_ready']):
                return False
        if proof['version'] == 2:
            if len(proof['quiet_receipts']) != 2:
                return False
            for receipt, (owner, sibling) in zip(proof['quiet_receipts'], (owners, owners[::-1]), strict=True):
                validate_quiet(receipt, owner, sibling)
        elif 'quiet_receipts' in proof:
            return False
        return True
    except (KeyError,TypeError,ValueError):
        return False
