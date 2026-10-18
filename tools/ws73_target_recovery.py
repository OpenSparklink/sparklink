#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Real WS73 radios with one artificial guest transport fault, never physical acceptance."""
import argparse
import os
from pathlib import Path
import re
import stat
import time

from ws73_north_star import Run, daemon_identity, file_record, ordinary_identity, parse_result, stable


def recovery_budget(value):
    fields = ('attempts', 'limit', 'uploads', 'upload_limit', 'cause', 'result',
              'exhausted', 'deadline_ms', 'stable_since_ms')
    pattern = ' '.join(name + r'=(-?\d+)' for name in fields)
    match = re.fullmatch(pattern, value)
    if not match:
        raise ValueError('complete driver recovery budget required')
    result = dict(zip(fields, map(int, match.groups())))
    if (result['limit'] != 2 or result['upload_limit'] != 3
            or not 0 <= result['attempts'] <= 2 or not 0 <= result['uploads'] <= 3
            or result['exhausted'] not in (0, 1) or result['deadline_ms'] < 0
            or result['stable_since_ms'] <= 0):
        raise ValueError('healthy bounded driver recovery budget required')
    return result


class RecoveryRun(Run):
    SCOPE = 'real WS73 RF with artificial guest transport recovery support'
    SUCCESS = 'RECOVERY_CONTROL_EVIDENCE_PENDING'

    def __init__(self, args):
        super().__init__(args)
        self.data.update(physical_acceptance=False, automatic_fault_recovery_acceptance=False,
                         fault_method='QMP_GUEST_TRANSPORT_ERROR_ONCE')
        self.save()

    def diagnostics(self, port):
        root = Path('/sys/bus/usb/devices') / port
        result = {'wall_ns': time.time_ns(), 'port_present': root.exists()}
        for interface in root.glob(port + ':*'):
            for name in ('boot_stage', 'boot_error', 'native_runtime', 'failure_diagnostics',
                         'warm_recovery', 'recovery_budget'):
                if (interface / name).exists():
                    result[name] = (interface / name).read_text().strip()
        return result

    def wait_stable_budget(self, a, b):
        """Observe the driver's existing 60s reset; never write/reset a budget."""
        record = {'method': 'OBSERVE_DRIVER_STABLE_BUDGET_RESET', 'samples': [],
                  'start_monotonic_ns': time.monotonic_ns()}
        self.data['recovery_budget_rearm'] = record
        deadline = time.monotonic() + 75
        while True:
            self.alive()
            if not stable(a, self.ready(a['port'])) or not stable(b, self.ready(b['port'])):
                raise ValueError('stable budget observation changed controller identity')
            sample = self.diagnostics(a['port'])
            sample['monotonic_ns'] = time.monotonic_ns()
            budget = recovery_budget(sample.get('recovery_budget', ''))
            record['samples'].append(sample)
            self.save()
            if budget['exhausted']:
                raise ValueError('budget exhausted before the next independent fault')
            if all(budget[k] == 0 for k in ('attempts', 'uploads', 'cause', 'result', 'deadline_ms')):
                record['end_monotonic_ns'] = time.monotonic_ns()
                record['target'] = a; record['peer'] = b
                self.save()
                return
            if time.monotonic() >= deadline:
                raise TimeoutError('existing stable driver budget did not reset')
            time.sleep(0.25)

    def execute(self):
        try:
            self.data['application_identity'] = ordinary_identity()
            self.args.slctl = self.args.slctl.resolve()
            mode = self.args.slctl.stat().st_mode
            if (not stat.S_ISREG(mode) or mode & (stat.S_ISUID | stat.S_ISGID)
                    or 'security.capability' in os.listxattr(self.args.slctl)):
                raise ValueError('ordinary slctl without setid/file capabilities required')
            self.data['slctl'] = file_record(self.args.slctl)
            self.data['sources'] = [file_record(Path(__file__))]
            self.pid = daemon_identity(self.args.slkd_pid)
            self.data['daemon_before'] = self.pid
            self.data['bus_before'] = self.bus_identity()
            a, b = [self.ready(port) for port in self.args.ports]
            self.data['initial'] = [a, b]
            self.phase(a, b, 20, 'initial')
            case=getattr(self.args,'daemon_hold_case',None)
            boot=[v.split('=',1)[1] for v in Path('/proc/cmdline').read_text().split() if v.startswith('ws73.daemon_hold=')]
            if boot!=([case] if case is not None else []):raise ValueError('matching explicit daemon hold boot gate required')
            if case is not None:
                from ws73_daemon_hold import execute as held_cancel
                held_cancel(self,a,b,case)
            if 'ws73.active_deadline=1' in Path('/proc/cmdline').read_text().split():
                self.wait_stable_budget(a, b)
            self.data['fault_before'] = self.diagnostics(a['port'])
            print('WS73_TARGET_RECOVERY_INJECT_READY', flush=True)
            if input() != 'recovery-injected':
                raise ValueError('explicit host QMP injection acknowledgement required')
            fault = self.command([str(self.args.slctl), '--adapter', a['path'], 'scan', 'on'],
                                 30, field='fault_command')
            if not isinstance(fault['exit'], int) or not fault['exit']:
                raise ValueError('injected transport error did not reject the old scan')
            self.data['fault_samples'] = []
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                self.alive()
                self.data['fault_samples'].append(self.diagnostics(a['port']))
                stale = self.command([str(self.args.slctl), '--adapter', a['path'], 'show'],
                                     10, collection='retirement_checks')
                if (isinstance(stale['exit'], int) and stale['exit']
                        and 'not a live registration' in stale['stderr']):
                    self.data['stale_selection'] = stale
                    self.data['retirement_observed_wall_ns'] = stale['end_wall_ns']
                    break
                time.sleep(0.1)
            else:
                raise ValueError('failed native owner did not retire within deadline')
            survivor = self.ready(b['port'])
            if not stable(b, survivor):
                raise ValueError('fault changed survivor identity')
            scan = self.ctl(b, 'scan', 'on')
            parse_result(scan['stdout'], b, 3)
            self.stop(b, 'scan')
            self.data['survivor_control'] = {'identity': survivor, 'scan_request': scan}
            deadline = time.monotonic() + 125
            while time.monotonic() < deadline:
                self.data['fault_samples'].append(self.diagnostics(a['port']))
                self.alive()
                if not stable(b, self.ready(b['port'])):
                    raise ValueError('recovery changed survivor registration')
                try:
                    new = self.ready(a['port'])
                except (OSError, ValueError):
                    self.save()
                    time.sleep(0.2)
                    continue
                if new['generation'] != a['generation'] and new['path'] != a['path']:
                    break
                time.sleep(0.2)
            else:
                raise ValueError('automatic protocol recovery did not reach fresh Ready')
            if (new['device'], new['bus'], new['address']) != (a['device'], a['bus'], a['address']):
                raise ValueError('protocol recovery unexpectedly re-enumerated or changed radio')
            self.data['replacement'] = new
            self.data['fault_after'] = self.diagnostics(a['port'])
            self.phase(new, b, 2, 'recovery')
            self.data['daemon_after'] = daemon_identity(self.args.slkd_pid)
            self.data['bus_after'] = self.bus_identity()
            if self.data['bus_before'] != self.data['bus_after']:
                raise ValueError('recovery restarted bus owner')
            self.data['status'] = self.SUCCESS
        except (Exception, KeyboardInterrupt) as error:
            self.data.update(status='FAIL', error=str(error) or type(error).__name__)
        finally:
            self.data['cleanup'] = []
            if self.pid:
                for port in self.args.ports:
                    try:
                        owner = self.ready(port)
                        self.stop(owner, 'advertise')
                        self.stop(owner, 'scan')
                        self.data['cleanup'].append({'port': port, 'status': 'STOP_CONFIRMED'})
                    except (OSError, ValueError) as error:
                        self.data['cleanup'].append({'port': port, 'status': 'FAILED', 'error': str(error)})
                        self.data['status'] = 'FAIL'
            self.save()
        print(self.data['status'], str(self.output / 'run.json'), flush=True)
        return 0 if self.data['status'] == self.SUCCESS else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daemon-hold-case',choices=['supersede','caller-exit','cancel-caller-exit','cancel-busy','cancel-admission'],help='actual ordinary D-Bus cancellation while original successful host reply is held')
    parser.add_argument('--slctl', type=Path, required=True)
    parser.add_argument('--slkd-pid', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.ports = ['1-1', '1-2']
    raise SystemExit(RecoveryRun(args).execute())
