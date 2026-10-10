#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Explicit guest-only synthetic control gate. Never a physical recorder."""
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slctl',type=Path,required=True)
    parser.add_argument('--slkd-pid',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.ports=['1-1','1-2'];args.artifact=['synthetic_control='+str(Path(__file__).resolve())]
    return SyntheticControlRun(args).execute()


if __name__=='__main__':
    raise SystemExit(main())
