# SPDX-License-Identifier: GPL-2.0-only
"""Bind daemon-normalized configuration, registration readback and actual DLI.

No TOML parser or controller simulation. The daemon produces the expectation;
USB capture proves initialization and START used it, including raw Complete.
"""
import re

from ws73_capture import CaptureError, command_reply

FIELDS = r'version=(\d+) adv_slots=(\d+)\.\.(\d+) tx_power_dbm=(-?\d+) scan_slots=(\d+)/(\d+)'
ADDRESS = r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}'
DEFAULT = [3, 1200, 1200, 127, 1600, 800]


def normalized_dump(text):
    lines = text.splitlines()
    if not lines:
        raise CaptureError('actual daemon policy dump required')
    first = re.fullmatch('Ws73DefaultPolicy: ' + FIELDS, lines[0])
    if not first:
        raise CaptureError('normalized default policy required')
    result = {'defaults': list(map(int, first.groups())), 'adapters': {}}
    for line in lines[1:]:
        match = re.fullmatch('Ws73AdapterPolicy: address=(' + ADDRESS + ') ' + FIELDS, line)
        if not match or match[1] == '00:00:00:00:00:00' or match[1] in result['adapters']:
            raise CaptureError('unique normalized adapter policy required')
        result['adapters'][match[1]] = list(map(int, match.groups()[1:]))
    if any(v[0] != 3 for v in [result['defaults'], *result['adapters'].values()]):
        raise CaptureError('explicit current policy version3 required')
    return result


def expected_policy(expectation, address):
    return expectation['policies']['adapters'].get(address, expectation['policies']['defaults'])


def checked_expectation(value):
    if (type(value.get('custom_configuration')) is not bool
            or not re.fullmatch('[0-9a-f]{64}', value.get('config_sha256', ''))
            or normalized_dump(value.get('daemon_dump', '')) != value.get('policies')):
        raise CaptureError('frozen daemon-normalized policy expectation required')
    return value


def query_proofs(run, expectation):
    checked_expectation(expectation)
    owners = run['initial']
    shows = [c for c in run['commands'] if c['args'][-1:] == ['show']]
    if len(shows) != 4:
        raise CaptureError('before/after policy readback for both registrations required')
    proofs = []
    for c, owner in zip(shows, owners * 2):
        prefix = (f"Adapter {owner['path']}:\n  State:       Ready\n"
                  f"  Generation:  {owner['generation']}\n  Address:     {owner['address']}\n  Profile:     1")
        match = re.findall('^  Radio policy: ' + FIELDS + '$', c['stdout'], re.M)
        if (c['exit'] != 0 or c['args'] != [run['slctl']['path'], '--adapter', owner['path'], 'show']
                or prefix not in c['stdout'] or len(match) != 1
                or list(map(int, match[0])) != expected_policy(expectation, owner['address'])):
            raise CaptureError('policy readback disagrees with configured native registration')
        proofs.append({'owner': owner, 'query': c, 'policy': list(map(int, match[0]))})
    first = run['commands'][run['rounds'][0]['command_indices'][0]]
    last = run['commands'][run['rounds'][-1]['command_indices'][-1]]
    if (any(c['end_wall_ns'] > first['start_wall_ns'] for c in shows[:2])
            or any(c['start_wall_ns'] < last['end_wall_ns'] for c in shows[2:])):
        raise CaptureError('policy queries must bracket the actual RF run')
    return proofs


def wire_proofs(capture, owners, expectation):
    checked_expectation(expectation)
    recipes = []
    for owner in owners:
        version, minimum, maximum, power, interval, window = expected_policy(expectation, owner['address'])
        if version != 3:
            raise CaptureError('current policy wire proof requires version3')
        # SDK frame-1, one nonconnectable fixed-T advertiser, all channels,
        # queried public address, no response, known validated tail200.
        adv = bytearray(49)
        adv[2] = 2
        adv[3:6] = minimum.to_bytes(3, 'little')
        adv[6:9] = maximum.to_bytes(3, 'little')
        adv[9] = 7
        adv[12:18] = bytes.fromhex(owner['address'].replace(':', ''))
        adv[25] = power & 255
        adv[43:45] = (200).to_bytes(2, 'little')
        scan = b'\0\0\1\0' + interval.to_bytes(2, 'little') + window.to_bytes(2, 'little')
        commands = sorted((c for c in capture['commands'] if (c['bus'], c['device']) ==
                           (owner['bus'], owner['device'])), key=lambda c: c['wall_ns'])
        counts = {0x0c02: 0, 0x1001: 0}
        for i, command in enumerate(commands):
            opcode = command['opcode']
            if opcode not in counts:
                continue
            params = bytes(adv) if opcode == 0x0c02 else scan
            if command['params'] != params.hex():
                raise CaptureError('actual initialization/START parameters disagree with configured policy')
            end = commands[i+1]['wall_ns']-1 if i+1 < len(commands) else max(c['wall_ns'] for c in capture['complete'])
            proof = command_reply(capture, owner, opcode, command['wall_ns'], end,
                                  params, None if opcode == 0x0c02 else '')
            if opcode == 0x0c02 and len(bytes.fromhex(proof['reply']['value'])) != 1:
                raise CaptureError('actual selected power byte required')
            counts[opcode] += 1
            recipes.append({'owner': owner, 'policy': expected_policy(expectation, owner['address']), **proof})
        if not all(counts.values()):
            raise CaptureError('both actual parameter domains required for each registration')
    return recipes
