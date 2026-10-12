#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit QMP guest-disconnect gates; never a physical unplug recorder."""
import argparse
from pathlib import Path
import sys
import time

from ws73_north_star import Run, USB_ROOT, _registration


class SyntheticControlRun(Run):
    SCOPE = 'synthetic WS73 USB control support'
    SUCCESS = 'CONTROL_SUPPORT_EVIDENCE_PENDING'

    def __init__(self, args):
        self.confirmations = 0
        super().__init__(args)
        self.data['hotplug_method'] = 'SYNTHETIC_QMP_DEVICE_DEL_ADD'
        self.save()

    def read_registration(self, port):
        return _registration(port, USB_ROOT, True)

    def confirm(self, message):
        if not sys.stdin.isatty():
            raise ValueError('synthetic control confirmation requires ordinary console TTY')
        self.confirmations += 1
        if self.confirmations not in [1,2]:
            raise ValueError('unexpected synthetic control phase')
        phase = 'REMOVE' if self.confirmations == 1 else 'READD'
        print(f'WS73_TARGET_CONTROL_{phase}_READY',flush=True)
        if input() != 'support-'+phase.lower():
            raise ValueError('synthetic control confirmation mismatch')


class PassthroughControlRun(Run):
    """Real radios, deliberately virtual disconnect/reconnect of one owner."""
    SCOPE = 'real WS73 RF with QMP guest-detach control support'
    SUCCESS = 'CONTROL_PASSTHROUGH_EVIDENCE_PENDING'

    def __init__(self, args):
        self.confirmations = 0
        super().__init__(args)
        self.data['hotplug_method'] = 'QMP_DEVICE_DEL_ADD'
        self.data['physical_acceptance'] = False
        self.save()

    def confirm(self, message):
        if not sys.stdin.isatty():
            raise ValueError('passthrough control confirmation requires ordinary console TTY')
        self.confirmations += 1
        if self.confirmations not in [1,2]:
            raise ValueError('unexpected passthrough control phase')
        phase = 'REMOVE' if self.confirmations == 1 else 'READD'
        print(f'WS73_TARGET_PASSTHROUGH_{phase}_READY',flush=True)
        if input() != 'passthrough-'+phase.lower():
            raise ValueError('passthrough QMP confirmation mismatch')


class ConnectionControlRun(PassthroughControlRun):
    def phase(self, a, b, count, label):
        if label == 'initial':
            from ws73_connection_control import execute
            execute(self, a, b)
        return super().phase(a, b, count, label)


class CancelRemovalRun(PassthroughControlRun):
    def __init__(self, args):
        super().__init__(args)
        from ws73_daemon_removal import RemovalSession
        self.removal = RemovalSession(self)

    def confirm(self, message):
        if self.confirmations == 0:
            self.removal.begin()
            super().confirm(message)
            self.removal.record['remove_ack_observed_wall_ns'] = time.time_ns()
            self.removal.removed()
        else:
            self.removal.record['readd_ready_wall_ns'] = time.time_ns()
            self.save()
            super().confirm(message)
            self.removal.record['readd_ack_observed_wall_ns'] = time.time_ns()
            self.save()

    def execute(self):
        try:
            return super().execute()
        finally:
            self.removal.close()

    def phase(self, a, b, count, label):
        if label == 'replug':
            r = self.removal.record
            row = self.command([str(self.args.slctl), '--adapter', r['target']['path'], 'show'], 3, field='removal_retired_after_readd')
            r['retired_after_readd'] = row
            r['replacement'] = a
            self.save()
            if not row['exit'] or 'not a live registration' not in row['stderr']:
                raise ValueError('re-added owner must not revive old selection')
        return super().phase(a, b, count, label)


class InitializerLifecycleRun(PassthroughControlRun):
    def __init__(self, args):
        super().__init__(args)
        from ws73_initialization_lifecycle import LifecycleSession
        self.lifecycle = LifecycleSession(self)

    def phase(self, a, b, count, label):
        if label == 'initial':
            self.lifecycle.withdrawal(a, b)
        elif label == 'replug':
            self.lifecycle.replacement_eviction(a, b)
        return super().phase(a, b, count, label)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slctl',type=Path,required=True)
    parser.add_argument('--slkd-pid',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--passthrough',action='store_true',help='real RF, QMP guest-only disconnect; excludes physical unplug acceptance')
    parser.add_argument('--daemon-cancel-remove',action='store_true',help='cancel during original held reply, then remove only that guest owner; requires passthrough')
    parser.add_argument('--initializer-lifecycle',action='store_true',help='actual initializer withdrawal, eviction and guest-generation gate; excludes private File close/dup')
    parser.add_argument('--connection-verify',action='store_true',help='ordinary typed real Connect/Disconnect before RF; excludes connected release/close/dup')
    parser.add_argument('--connection-advertising',choices=['fixed-t','negotiable-t'],default='fixed-t')
    args=parser.parse_args()
    if args.daemon_cancel_remove and not args.passthrough:
        parser.error('held cancellation/removal requires real passthrough mode')
    if args.initializer_lifecycle and (not args.passthrough or args.daemon_cancel_remove):
        parser.error('initializer lifecycle requires separate real passthrough mode')
    if args.connection_verify and (not args.passthrough or args.daemon_cancel_remove or args.initializer_lifecycle):
        parser.error('connection gate requires separate real passthrough mode')
    if args.connection_advertising!='fixed-t' and not args.connection_verify:
        parser.error('connection advertising contrast requires explicit connection gate')
    args.ports=['1-1','1-2'];args.artifact=['qmp_control='+str(Path(__file__).resolve())]
    if args.daemon_cancel_remove:
        args.artifact.append('daemon_removal='+str(Path(__file__).with_name('ws73_daemon_removal.py').resolve()))
    if args.initializer_lifecycle:
        args.artifact.append('initializer_lifecycle='+str(Path(__file__).with_name('ws73_initialization_lifecycle.py').resolve()))
    return (ConnectionControlRun if args.connection_verify else InitializerLifecycleRun if args.initializer_lifecycle else CancelRemovalRun if args.daemon_cancel_remove else PassthroughControlRun if args.passthrough else SyntheticControlRun)(args).execute()


if __name__=='__main__':
    raise SystemExit(main())
