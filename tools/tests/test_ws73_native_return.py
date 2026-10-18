# SPDX-License-Identifier: GPL-2.0-only
"""Actual fixture C matcher/syscall and report parser; no SparkLink/USB I/O.

Only generic Unix sockets run on the host. Report/clock/table fixtures test
fail-closed evidence handling, not Native kernel concurrency or real delivery.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ws73_native_return as gate
from ws73_target import run_exit_code


class NativeReturn(unittest.TestCase):
    def test_actual_c_selector_and_forwarded_unix_syscall(self):
        source = Path(gate.__file__).with_name('ws73_native_return_fixture.c')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c = root/'fixture.c'
            c.write_text('#define bind fixture_bind\n#include '+json.dumps(str(source))+r'''
#include <assert.h>
#include <stddef.h>
#include <sys/un.h>
int main(int argc, char **argv) {
    assert(argc == 2);
    struct selection s = {.magic="SLKSEL1",.controller=1,.generation=7};
    struct native_address a = {.family=46,.version=2,.controller=1,.generation=7,
        .lifetime=8,.lease=19,.local=10,.remote=10,.directions=3};
    assert(selected(&a,&s));
    struct native_address good=a;
#define REJECT(field,value) do {a=good;a.field=value;assert(!selected(&a,&s));} while(0)
    REJECT(family,1);REJECT(version,3);REJECT(controller,2);REJECT(generation,6);
    REJECT(lifetime,0);REJECT(lease,0);REJECT(flags,1);REJECT(local,31);REJECT(remote,31);
    REJECT(pi,241);REJECT(reserved[0],1);REJECT(reserved[1],1);REJECT(reserved[2],1);
    REJECT(directions,1);REJECT(security,1);
    a=good;s.phase=2;s.kind=1;a.local=31;a.remote=31;a.pi=241;
    assert(selected(&a,&s));s.reserved=1;assert(!selected(&a,&s));s.reserved=0;
    s.phase=4;assert(!selected(&a,&s));s.phase=2;s.kind=0;assert(!selected(&a,&s));
    int first=socket(AF_UNIX,SOCK_DGRAM|SOCK_CLOEXEC,0);
    int second=socket(AF_UNIX,SOCK_DGRAM|SOCK_CLOEXEC,0);
    assert(first>=0 && second>=0);
    struct sockaddr_un address={.sun_family=AF_UNIX};
    assert(strlen(argv[1])<sizeof(address.sun_path));strcpy(address.sun_path,argv[1]);
    socklen_t length=offsetof(struct sockaddr_un,sun_path)+strlen(argv[1])+1;
    errno=EAGAIN;assert(fixture_bind(first,(void*)&address,length)==0);assert(errno==EAGAIN);
    assert(fixture_bind(second,(void*)&address,length)==-1 && errno==EADDRINUSE);
    /* Kernel syscall EFAULT, not a C application FFI pointer contract. */
    assert(fixture_bind(second,(void*)1,48)==-1 && errno==EFAULT);
    close(first);close(second);assert(unlink(argv[1])==0);
    return 0;
}
''')
            args = [os.environ.get('CC','cc'),'-std=gnu11','-O2','-Wall','-Wextra','-Werror',str(c),'-o',str(root/'probe')]
            built = subprocess.run(args, text=True, capture_output=True, timeout=30)
            self.assertEqual(built.returncode,0,built.stderr)
            result = subprocess.run([str(root/'probe'),str(root/'actual.sock')],capture_output=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_actual_observation_decoder_rejects_lengths_identity_and_bad_times(self):
        good = [b'SLKRET1\0',0,10,11,7,1,2,3,4,100,200,0,0,0,0]
        raw = gate.OBSERVATION.pack(*good)
        self.assertEqual(gate.decode(raw)['fd'],7)
        for bad in [raw[:-1],raw+b'\0',b'badmagic'+raw[8:]]:
            with self.assertRaises(ValueError):gate.decode(bad)
        for index,value in [(1,4),(2,0),(3,0),(4,-1),(5,16),(6,65536),
                            (7,0),(8,0),(9,0),(10,0),(11,1),(13,3),(14,1)]:
            bad=good.copy();bad[index]=value
            with self.subTest(index=index),self.assertRaises(ValueError):gate.decode(gate.OBSERVATION.pack(*bad))
        returned=good.copy();returned[11:14]=[150,250,1]
        self.assertEqual(gate.decode(gate.OBSERVATION.pack(*returned))['outcome'],1)
        returned[13]=2
        # Preserve expired raw evidence; it must never become a PASS summary.
        self.assertEqual(gate.decode(gate.OBSERVATION.pack(*returned))['outcome'],2)

    def test_explicit_request_rejects_synthetic_or_mixed_gates(self):
        args=SimpleNamespace(native_return_verify=True,passthrough=True,connection_verify=True,
                             channel_socket_verify=True,channel_socket_bytes=61,channel_socket_rounds=4)
        self.assertTrue(gate.requested(args))
        for key,value in [('passthrough',False),('connection_verify',False),('channel_socket_verify',False),
                          ('channel_socket_bytes',249),('channel_socket_rounds',3),
                          ('ssap_initialization_verify',True),('ssap_owned_verify',True),
                          ('security_agent','approve'),('channel_benchmark','rate')]:
            bad=copy.copy(args);setattr(bad,key,value)
            with self.subTest(key=key),self.assertRaises(ValueError):gate.requested(bad)
        with self.assertRaises(ValueError):gate.requested(SimpleNamespace(native_return_verify=1))
        self.assertFalse(gate.requested(SimpleNamespace()))

    def test_exit_gate_never_accepts_missing_native_evidence_or_failed_terminal(self):
        for value in [None,{}, {'status':gate.STATUS}, {'status':gate.STATUS,'slices':4}]:
            row=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,supervisor_exit=0,
                     native_return_requested=True,native_return_acceptance=True,
                     ordinary_channel_socket_acceptance=True,channel_socket_corroboration={'round_trips':8},
                     native_return_corroboration=value or {})
            self.assertEqual(run_exit_code(row),1)
        self.assertEqual(run_exit_code(dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,
                                           supervisor_exit=0,native_return_acceptance=True)),1)

    def test_summary_rejects_expiry_missing_wire_and_overstated_scope(self):
        # Verdict shape fixtures only; never count this as actual wire/kernel
        # acceptance. Actual VM corroboration must reconstruct every raw leg.
        phases=[]
        for n in range(4):
            held=gate.decode(gate.OBSERVATION.pack(b'SLKRET1\0',n,10,11,7,1,2,3,4,100,200,0,0,0,n//2))
            returned=dict(held,outcome=1,end_mono_ns=150,end_wall_ns=250)
            wire={'command':{'fixture':True},'status':{'fixture':True},'outcomes':[{'fixture':True}]*2}
            phases.append(dict(phase=n,kind=n//2,role=n%2,held=held,returned=returned,create=wire,disconnect=wire))
        proof=dict(status=gate.STATUS,slices=4,service_slices=2,user_slices=2,proofs=phases,
                   fixture_sha256='a'*64,
                   kernel_reference_or_uaf_proof=False,dynamic_creator=False,
                   actual_controller_removal=False,broker_new_admission_probe=False,physical_acceptance=False,automatic_recovery=False)
        self.assertTrue(gate.valid_summary(proof))
        mutations=[lambda p:p.update(proofs=None),lambda p:p.update(proofs=[0]*4),
                   lambda p:p.update(slices=4.0),lambda p:p.update(actual_controller_removal=True),
                   lambda p:p['proofs'][0]['returned'].update(outcome=2),
                   lambda p:p['proofs'][0]['returned'].update(end_mono_ns=2_000_000_100),
                   lambda p:p['proofs'][0]['returned'].update(lifetime=99),
                   lambda p:p['proofs'][0]['held'].update(fd=True),
                   lambda p:p['proofs'][0].update(held=None),
                   lambda p:p['proofs'][1].update(role=True),
                   lambda p:p['proofs'][0]['disconnect'].pop('outcomes')]
        for n,mutate in enumerate(mutations):
            bad=copy.deepcopy(proof);mutate(bad)
            with self.subTest(n=n):self.assertFalse(gate.valid_summary(bad))


if __name__ == '__main__':unittest.main()
