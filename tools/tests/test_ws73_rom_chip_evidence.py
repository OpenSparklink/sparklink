# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic parser negatives, no device/cold-power acceptance."""
import copy
from pathlib import Path
import struct
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from ws73_rom_chip import COMMAND
from ws73_rom_chip_evidence import corroborate_rows, corroborate_directusb_read_only
from ws73_capture import CaptureError
from test_ws73_model_evidence import fixture as hcc_fixture
from test_ws73_directusb_rom import receipt


def fixture(model='E'):
    raw=bytes([10,0,0,0]) if model=='E' else bytes(4)
    outgoing,incoming=hcc_fixture()
    for r in outgoing:
        r['record']+=40;r['completion_record']+=40
    incoming[0]['submit_record']+=40;incoming[0]['record']+=40;incoming[0]['raw'][108]=2 if model=='E' else 0
    romout=[];romin=[]
    for n in range(3):
        i=1+n*6;common=dict(bus=1,device=3)
        romout.append(common|dict(record=i,completion_record=i+1,raw=COMMAND))
        romin.append(common|dict(submit_record=i+2,record=i+3,raw=raw,successful=True,requested=512,length=4))
    romout.append(dict(bus=1,device=3,record=30,completion_record=31,raw=b'WRITEM 4 0x40004000 1 '))
    p=dict(boot_origin='SOFTWARE_REGISTER_RESET_NOT_COLD_POWER',automatic_firmware_selection=False,read_validity_proven=False,rom_chip_expected=model,rom_chip_reads=[dict(command=COMMAND.hex(),reply=raw.hex(),out_actual=len(COMMAND),in_actual=4) for _ in range(3)],runtime_chip_before=[dict(raw=raw.hex()) for _ in range(3)],runtime_chip_after=[dict(raw=raw.hex()) for _ in range(3)])
    return romout+outgoing,romin+incoming,p

class RomEvidence(unittest.TestCase):
    def test_e_and_zero_u_bytes_are_observations_not_identification(self):
        for model in ['E','U']:
            r=corroborate_rows(*fixture(model))
            self.assertEqual(len(r['pairs']),3);self.assertFalse(r['cold_power_verified']);self.assertFalse(r['automatic_selection_permitted']);self.assertFalse(r['access_validity_proven'])
            self.assertEqual(r['pairs'][0]['zero_reply_ambiguous'],model=='U')
    def test_missing_foreign_short_long_failed_unpaired_or_late_reads_fail(self):
        for kind in ['missing','duplicate','foreign','short','long','failed','request','late','bad-command','wrong-bytes','runtime-missing','runtime-stale','missing-upload','early-mutation','hcc-wrong','hcc-missing','upgrade-cold','upgrade-selection','upgrade-validity']:
            out,inc,p=fixture()
            if kind=='missing':inc.pop(0)
            elif kind=='duplicate':inc.append(copy.deepcopy(inc[0]))
            elif kind=='foreign':inc[0]['device']=8
            elif kind=='short':inc[0]['raw']=b'\x0a'*3;inc[0]['length']=3
            elif kind=='long':inc[0]['raw']=b'\x0a'*5;inc[0]['length']=5
            elif kind=='failed':inc[0]['successful']=False
            elif kind=='request':inc[0]['requested']=4
            elif kind=='late':inc[0]['record']=32
            elif kind=='bad-command':out[0]['raw']=COMMAND[:-1]
            elif kind=='wrong-bytes':p['rom_chip_reads'][0]['reply']='00'*4
            elif kind=='runtime-missing':p['runtime_chip_after'].pop()
            elif kind=='runtime-stale':p['runtime_chip_before'][0]['raw']='00'*4
            elif kind=='missing-upload':out.pop(3)
            elif kind=='early-mutation':out[3]['record']=0
            elif kind=='hcc-wrong':inc[-1]['raw'][108]=0
            elif kind=='hcc-missing':inc.pop()
            elif kind=='upgrade-cold':p['boot_origin']='COLD'
            elif kind=='upgrade-selection':p['automatic_firmware_selection']=True
            else:p['read_validity_proven']=True
            with self.subTest(kind=kind),self.assertRaises(CaptureError):corroborate_rows(out,inc,p)

class DirectUsbReadOnlyEvidence(unittest.TestCase):
    """Raw pcap fixtures, not OS completion/drain or hardware qualification."""

    def run_case(self, root, bad=None, zero=False):
        result=receipt();result.update(bus=1,device_number_observation=2)
        raw=bytes(4) if zero else b'\x08\0\0\0';result['reply']=list(raw)
        # URB IDs are distinct between OUT and IN, identical within each pair.
        rows=[(1,'S',1,COMMAND,len(COMMAND),0,0),
              (1,'C',1,b'',len(COMMAND),62,0),
              (2,'S',129,b'',512,60,0),
              (2,'C',129,raw,4,0,0)]
        if bad=='missing':rows.pop()
        elif bad=='duplicate':rows+=rows[:]
        elif bad=='pending':rows.append((3,'S',129,b'',512,60,0))
        elif bad=='wrong-command':rows[0]=(1,'S',1,b'WRITEM 4 0 1 ',13,0,0);rows[1]=(1,'C',1,b'',13,62,0)
        elif bad=='failed-out':rows[1]=(1,'C',1,b'',19,62,-32)
        elif bad=='failed-in':rows[3]=(2,'C',129,b'',0,62,-110)
        elif bad=='short':rows[3]=(2,'C',129,raw[:3],3,0,0)
        elif bad=='wrong-bytes':rows[3]=(2,'C',129,b'\x04\0\0\0',4,0,0)
        elif bad=='order':rows=rows[2:]+rows[:2]
        elif bad=='receipt-foreign':result['device_number_observation']=3
        elif bad=='receipt-bool':result['bus']=True
        elif bad=='receipt-undrained':result['in']['pending_after']=1
        elif bad=='receipt-late':result['in']['stage']='LATE_COMPLETION_REJECTED'
        packets=[]
        for tick,(urb,kind,ep,value,length,flag,status) in enumerate(rows,1):
            device=3 if bad=='foreign-in' and ep==129 else 2
            packet=struct.pack('<QBBBBHBBqiiII',urb,ord(kind),3,ep,device,1,0,flag,10,tick,status,length,len(value))+bytes(24)+value
            packets.append(struct.pack('<IIII',10,tick,len(packet),len(packet))+packet)
        body=struct.pack('<IHHIIII',0xa1b2c3d4,2,4,0,0,65535,220)+b''.join(packets)
        if bad=='truncated':body=body[:-1]
        path=root/'fixture.pcap';path.write_bytes(body)
        stats=f'{len(rows)} packets captured\n{len(rows)} packets received by filter\n{1 if bad=="capture-drop" else 0} packets dropped by kernel\n'
        return corroborate_directusb_read_only(path,stats,result,'1-1.2')

    def test_exact_exchange_does_not_grant_cold_selection_or_access_validity(self):
        with tempfile.TemporaryDirectory() as tmp:
            for zero in [False,True]:
                report=self.run_case(Path(tmp),zero=zero)
                self.assertFalse(report['cold_power_verified'])
                self.assertFalse(report['access_validity_proven'])
                self.assertFalse(report['automatic_selection_permitted'])
                self.assertEqual(report['candidate']['zero_reply_ambiguous'],zero)
                self.assertEqual(report['receive_completion'],4)

    def test_missing_extra_failed_foreign_stale_and_truncated_records_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ['missing','duplicate','pending','wrong-command','failed-out','failed-in','short',
                        'wrong-bytes','order','receipt-foreign','receipt-bool','receipt-undrained',
                        'receipt-late','foreign-in','truncated','capture-drop']:
                with self.subTest(bad=bad),self.assertRaises(CaptureError):
                    self.run_case(Path(tmp),bad)


if __name__=='__main__':unittest.main()
