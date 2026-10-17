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
            from ws73_registry_metadata import execute as registry_metadata
            registry_metadata(self, a, b)
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
    parser.add_argument('--daemon-link-resync',action='store_true')
    parser.add_argument('--security-agent',choices=['approve','reject','timeout','cancel','agent-exit','caller-exit','cli-approve','cli-reject','install-cancel','numeric-approve','numeric-reject','numeric-late'])
    parser.add_argument('--channel-socket-bytes',type=int,default=61)
    parser.add_argument('--channel-socket-burst',action='store_true')
    parser.add_argument('--channel-socket-close-prefix',action='store_true')
    parser.add_argument('--channel-socket-boundaries',action='store_true')
    parser.add_argument('--channel-socket-rounds',type=int,choices=range(1,21),default=4)
    parser.add_argument('--dynamic-channel-burst',action='store_true')
    parser.add_argument('--dynamic-channel-long-bytes',type=int,choices=[249,250,253,254,255,1024,2042])
    parser.add_argument('--dynamic-channel-verify',action='store_true')
    parser.add_argument('--channel-fairness-verify',action='store_true')
    parser.add_argument('--channel-benchmark',choices=['rate','window','duplex'])
    parser.add_argument('--channel-benchmark-window',type=int,default=4)
    parser.add_argument('--channel-benchmark-count',type=int,default=20)
    parser.add_argument('--channel-benchmark-bytes',type=int,default=61)
    parser.add_argument('--channel-benchmark-interval-us',type=int)
    parser.add_argument('--ssap-owned-verify',action='store_true',help='real owner authorization and exit cleanup;not complete SSAP or service-only policy qualification')
    parser.add_argument('--channel-socket-verify',action='store_true')
    parser.add_argument('--acb-transport-probe',action='store_true')
    parser.add_argument('--connection-verify',action='store_true',help='ordinary typed real Connect/Disconnect before RF; excludes connected release/close/dup')
    parser.add_argument('--connection-advertising',choices=['fixed-t','negotiable-t'],default='fixed-t')
    args=parser.parse_args()
    if args.ssap_owned_verify and (not args.channel_socket_verify or args.channel_socket_close_prefix or args.channel_socket_burst or args.channel_socket_boundaries or args.dynamic_channel_verify or args.channel_fairness_verify):parser.error('owned SSAP requires separate ordinary socket baseline')
    from ws73_socket_benchmark import requested_configuration
    try:requested_configuration(args)
    except ValueError as error:parser.error(str(error))
    if args.channel_benchmark and (not args.connection_verify or args.channel_socket_verify or args.acb_transport_probe or args.security_agent or args.daemon_link_resync):parser.error('benchmark requires separate real connection without other application gates')
    if args.channel_fairness_verify and (not args.channel_socket_verify or args.dynamic_channel_verify or args.security_agent or args.channel_socket_close_prefix or args.channel_socket_burst or args.channel_socket_boundaries):parser.error('concurrent channel gate requires separate ordinary baseline')
    if args.dynamic_channel_burst and (not args.dynamic_channel_verify or args.dynamic_channel_long_bytes!=2042):parser.error('dynamic burst requires explicit2042dynamic gate')
    if args.dynamic_channel_long_bytes is not None and not args.dynamic_channel_verify:parser.error('dynamic long requires explicit dynamic gate')
    if args.dynamic_channel_verify and (not args.channel_socket_verify or args.security_agent or args.channel_socket_close_prefix or args.channel_socket_burst or args.channel_socket_boundaries):parser.error('dynamic gate requires separate ordinary fixed-channel baseline without other special modes')
    if args.security_agent and (not args.connection_verify or not args.channel_socket_verify):parser.error('Agent requires explicit connection/socket gate')
    if args.daemon_cancel_remove and not args.passthrough:
        parser.error('held cancellation/removal requires real passthrough mode')
    if args.initializer_lifecycle and (not args.passthrough or args.daemon_cancel_remove):
        parser.error('initializer lifecycle requires separate real passthrough mode')
    if args.connection_verify and (not args.passthrough or args.daemon_cancel_remove or args.initializer_lifecycle):
        parser.error('connection gate requires separate real passthrough mode')
    if args.daemon_link_resync and not args.connection_verify:parser.error('link resync requires explicit connection gate')
    if not 29<=args.channel_socket_bytes<=2042 or ((args.channel_socket_bytes!=61 or args.channel_socket_boundaries) and not args.channel_socket_verify):parser.error('message size and boundaries require explicit supported socket gate')
    if args.channel_socket_rounds!=4 and not args.channel_socket_verify:parser.error('round count requires explicit socket gate')
    if args.channel_socket_close_prefix and (not args.channel_socket_verify or args.channel_socket_bytes!=2042 or args.channel_socket_rounds!=1 or args.channel_socket_boundaries):parser.error('prefix-close requires explicit one-round 2042-byte socket gate')
    if args.channel_socket_burst and (not args.channel_socket_verify or args.channel_socket_bytes!=2042 or args.channel_socket_rounds!=16 or args.channel_socket_close_prefix or args.channel_socket_boundaries):parser.error('burst requires explicit16-round2042-byte socket gate')
    if args.channel_socket_verify and (not args.connection_verify or args.acb_transport_probe or args.daemon_link_resync):parser.error('ordinary socket requires separate connection gate without test module')
    if args.acb_transport_probe and (not args.connection_verify or args.daemon_link_resync):parser.error('ACB probe requires a separate explicit connection gate')
    if args.connection_advertising!='fixed-t' and not args.connection_verify:
        parser.error('connection advertising contrast requires explicit connection gate')
    args.ports=['1-1','1-2'];args.artifact=['qmp_control='+str(Path(__file__).resolve())]
    if args.connection_verify:
        args.artifact += ['registry_probe=/bin/native-bindings-probe','registry_cli=/bin/slkconfig','registry_tool='+str(Path(__file__).with_name('ws73_registry_metadata.py').resolve())]
    if args.daemon_cancel_remove:
        args.artifact.append('daemon_removal='+str(Path(__file__).with_name('ws73_daemon_removal.py').resolve()))
    if args.initializer_lifecycle:
        args.artifact.append('initializer_lifecycle='+str(Path(__file__).with_name('ws73_initialization_lifecycle.py').resolve()))
    return (ConnectionControlRun if args.connection_verify else InitializerLifecycleRun if args.initializer_lifecycle else CancelRemovalRun if args.daemon_cancel_remove else PassthroughControlRun if args.passthrough else SyntheticControlRun)(args).execute()


if __name__=='__main__':
    raise SystemExit(main())
