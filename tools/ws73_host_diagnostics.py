#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only host USB evidence. No reset, detach, firmware or permission changes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

PORT = re.compile(r'\d+-\d+(?:\.\d+)*')


def journal_port(message, port):
    # End at whitespace/colon: port .1 must not capture sibling .10/.1.2.
    escaped = re.escape(port)
    parent, number = port.rsplit('.', 1) if '.' in port else (None, None)
    device = re.search(r'\busb '+escaped+r'(?:\s|:)', message)
    hub = parent is not None and re.search(r'\busb '+re.escape(parent)+r'-port'+number+r'(?:\s|:)', message)
    return bool(device or hub)


def usb_journal(lines, ports, controllers=()):
    records = []
    for line in lines.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        message = item.get('MESSAGE')
        if not isinstance(message, str):
            raise ValueError('journal MESSAGE must be a string')
        owners = [port for port in ports if journal_port(message, port)]
        controller_owners = [name for name in controllers if re.search(r'\bxhci_hcd '+re.escape(name)+r'(?:\s|:)', message)]
        if not owners and not controller_owners:
            continue
        if not all(str(item.get(key, '')).isdigit() for key in ['__REALTIME_TIMESTAMP', '__MONOTONIC_TIMESTAMP']):
            raise ValueError('kernel journal timestamps required')
        records.append({'ports': owners, 'controllers': controller_owners,
                        'wall_us': int(item['__REALTIME_TIMESTAMP']),
                        'monotonic_us': int(item['__MONOTONIC_TIMESTAMP']),
                        'boot_id': item.get('_BOOT_ID'), 'message': message})
    return records


def snapshot(port, root=Path('/sys/bus/usb/devices')):
    if not PORT.fullmatch(port):
        raise ValueError('explicit USB port required')
    device = root/port
    result = {'port': port, 'present': device.exists(), 'observed_wall_ns': time.time_ns(),
              'observed_monotonic_ns': time.monotonic_ns(), 'interfaces': [], 'errors': []}
    controller = (root/('usb'+port.split('-', 1)[0])).resolve().parent.name
    result['controller'] = controller if re.fullmatch(r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]', controller) else None
    if device.exists():
        for name in ['idVendor', 'idProduct', 'busnum', 'devnum', 'speed']:
            try:
                result[name] = (device/name).read_text().strip()
            except OSError as error:
                result['errors'].append({'attribute': name, 'errno': error.errno})
        for interface in sorted(root.glob(port+':*')):
            row = {'path': interface.name, 'driver': None}
            driver = interface/'driver'
            if driver.is_symlink():
                row['driver'] = driver.resolve().name
            result['interfaces'].append(row)
    if '.' in port:
        parent, number = port.rsplit('.', 1)
        hub_port = root/(parent+':1.0')/(parent+'-port'+number)
        for name in ['state', 'over_current_count', 'disable', 'connect_type']:
            try:
                result['hub_port_'+name] = (hub_port/name).read_text().strip()
            except OSError as error:
                result['errors'].append({'attribute': 'hub_port_'+name, 'errno': error.errno})
    return result


def classify(port, observed, records, journal_available):
    if observed.get('present'):
        if (observed.get('idVendor'), observed.get('idProduct')) != ('ffff', '3733'):
            return 'PRESENT_OTHER_DEVICE'
        return 'WS73_PRESENT_DRIVER_BOUND' if any(x['driver'] for x in observed['interfaces']) else 'WS73_PRESENT_UNBOUND'
    if not journal_available:
        return 'ABSENT_CAUSE_UNOBSERVED'
    owned = sorted((x for x in records if port in x['ports']), key=lambda x: x['wall_us'])
    failure = [x for x in owned if 'unable to enumerate USB device' in x['message']]
    if failure:
        last = failure[-1]
        later = [x for x in owned if x['wall_us'] > last['wall_us'] and 'New USB device found' in x['message']]
        if not later:
            return 'ABSENT_LAST_ENUMERATION_FAILED_BEFORE_DRIVER'
    return 'ABSENT_CAUSE_UNOBSERVED'


def collect(args):
    if not args.ports or len(args.ports) != len(set(args.ports)) or not all(PORT.fullmatch(p) for p in args.ports):
        raise ValueError('distinct explicit USB ports required')
    command = ['journalctl', '-k', '--no-pager', '-o', 'json', '--since', args.since]
    if args.until:
        command += ['--until', args.until]
    rows = [snapshot(p) for p in args.ports]
    journal = subprocess.run(command, capture_output=True, text=True, timeout=30)
    controllers = sorted({r['controller'] for r in rows if r['controller']})
    records = usb_journal(journal.stdout, args.ports, controllers) if journal.returncode == 0 else []
    result = {'format_version': 1, 'scope': 'read-only native-host USB diagnosis',
              'physical_acceptance': False, 'collected_at': datetime.now(timezone.utc).isoformat(),
              'journal_command': command, 'journal_available': journal.returncode == 0,
              'journal_exit': journal.returncode, 'journal_stderr': journal.stderr,
              'records': records, 'devices': rows,
              'classification': {r['port']: classify(r['port'], r, records, journal.returncode == 0) for r in rows},
              'limits': ['Enumeration failure localizes the boundary, not its electrical/controller root cause.',
                         'Zero over-current count does not establish adequate power or independent power switching.',
                         'Presence/binding is not protocol Ready or native-kernel acceptance.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2); stream.write('\n')
    print(json.dumps(result['classification'], sort_keys=True))
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ports', nargs='+', required=True)
    parser.add_argument('--since', required=True, help='journalctl time expression; never resets a port')
    parser.add_argument('--until')
    parser.add_argument('--output', type=Path, required=True, help='new private evidence file')
    raise SystemExit(collect(parser.parse_args()))
