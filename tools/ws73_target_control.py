#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit QMP guest-disconnect gates; never a physical unplug recorder."""
import argparse
from pathlib import Path
import sys

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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slctl',type=Path,required=True)
    parser.add_argument('--slkd-pid',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--passthrough',action='store_true',help='real RF, QMP guest-only disconnect; excludes physical unplug acceptance')
    args=parser.parse_args()
    args.ports=['1-1','1-2'];args.artifact=['qmp_control='+str(Path(__file__).resolve())]
    return (PassthroughControlRun if args.passthrough else SyntheticControlRun)(args).execute()


if __name__=='__main__':
    raise SystemExit(main())
