# SPDX-License-Identifier: GPL-2.0-only
"""Local credential/fd rejection regression, never an RF/death qualification."""
import array
import copy
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_daemon_channel_fd import receive


class RealLocalFd(unittest.TestCase):
    def test_identity_ancillary_truncation_and_descriptor_cleanup(self):
        a,b=socket.socketpair(socket.AF_UNIX,socket.SOCK_DGRAM)
        with a,b,socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as data:
            b.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1)
            row=dict(stage='daemon_channel_fd',token='a'*32,path='/test',pid=os.getpid(),daemon_pid=17,daemon_owner=':1.2',inode=os.fstat(data.fileno()).st_ino,process_status=Path('/proc/self/status').read_text(),wall_ns=str(time.time_ns()))
            before=set(os.listdir('/proc/self/fd'))
            for kind in ['good','token','owner','pid','inode','shape','multiple','truncated','payload_truncated','missing_fd','family']:
                changed=copy.deepcopy(row);count=1;family=socket.AF_UNIX
                if kind=='token':changed['token']='b'*32
                elif kind=='owner':changed['daemon_owner']=':1.3'
                elif kind=='pid':changed['pid']+=1
                elif kind=='inode':changed['inode']+=1
                elif kind=='shape':changed['extra']=True
                elif kind=='multiple':count=2
                elif kind=='truncated':count=32
                elif kind=='payload_truncated':changed['process_status']='x'*20000
                elif kind=='missing_fd':count=0
                elif kind=='family':family=46
                rights=[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[data.fileno()]*count))] if count else []
                a.sendmsg([json.dumps(changed).encode()],rights)
                def take():return receive(b,token=row['token'],path='/test',daemon_pid=17,daemon_owner=':1.2',expected_identity=(os.getuid(),os.getgid()),expected_family=family)
                if kind=='good':
                    received,receipt=take()
                    with received:self.assertEqual(receipt['kernel_sender']['pid'],os.getpid())
                else:
                    with self.subTest(kind=kind),self.assertRaises(ValueError):take()
                self.assertEqual(set(os.listdir('/proc/self/fd')),before)
