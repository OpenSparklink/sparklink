"""Receipt/staging fixtures only; no kernel, USB or firmware qualification."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ws73_rom_chip as rom


def receipt():
    value={'schema':1,'status':'ROM_BYTES_OBSERVED_NOT_MODEL_AUTHENTICATION',
           'scope':'VM_ROM_READ_ONLY_NOT_HOST_OR_RECOVERY','guest_port':'1-1.2',
           'command':rom.COMMAND.decode(),'reply':[8,0,0,0]}
    for key,ep,requested,actual in [('out',1,len(rom.COMMAND),len(rom.COMMAND)),('in',129,512,4)]:
        value[key]={'endpoint':ep,'requested':requested,'stage':'USB_COMPLETION_NOT_PROTOCOL_DELIVERY',
                    'pending_after':0,'completion':{'actual':actual,'buffer_length':actual,'status':'Ok(())'}}
    return value


class DirectUsbRom(unittest.TestCase):
    def test_complete_receipt_reuses_existing_chip_observer_not_selector(self):
        value=receipt()
        self.assertEqual(rom.validate_directusb_reply(value,'1-1.2'),b'\x08\0\0\0')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.write_bytes(b'fixture-not-ELF')
            manifest={};rom.stage_directusb(source,root,manifest,lambda src,dst,unused:(dst.parent.mkdir(parents=True,exist_ok=True),shutil.copyfile(src,dst)))
            binary=root/'bin/ws73-directusb-rom';record={}
            with patch.object(rom,'DIRECTUSB_BINARY',binary),patch.object(rom.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(value),'')) as run,patch.object(rom.fcntl,'ioctl',side_effect=AssertionError('no fallback')):
                rows=rom.rom_observations(None,record,lambda:None,'E',directusb='1-1.2')
            self.assertEqual(run.call_count,3)
            self.assertTrue(all(not row['candidate']['automatic_selection_permitted'] for row in rows))
            self.assertEqual(manifest['directusb_rom_probe']['source']['sha256'],rows[0]['directusb_executor']['sha256'])

    def test_foreign_failed_late_truncated_and_undrained_receipts_fail(self):
        variants=[]
        for key,value in [('schema',True),('guest_port','1-1.3'),('command','WRITE'),('reply',[8,0,0]),('reply',[True,0,0,0]),('error','late')]:
            bad=receipt();bad[key]=value;variants.append(bad)
        for key,value in [('pending_after',1),('pending_after',False),('cancel_requested',True),('stage','QUARANTINED_UNDRAINED')]:
            bad=receipt();bad['in'][key]=value;variants.append(bad)
        for key,value in [('actual',3),('buffer_length',512),('status','Err(Cancelled)')]:
            bad=receipt();bad['in']['completion'][key]=value;variants.append(bad)
        for bad in variants:
            with self.subTest(value=bad),self.assertRaises(ValueError):rom.validate_directusb_reply(bad,'1-1.2')

    def test_changed_binary_and_supervisor_timeout_are_not_success_or_drain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.write_bytes(b'fixture')
            rom.stage_directusb(source,root,{},lambda src,dst,unused:(dst.parent.mkdir(parents=True,exist_ok=True),shutil.copyfile(src,dst)))
            binary=root/'bin/ws73-directusb-rom'
            with patch.object(rom,'DIRECTUSB_BINARY',binary),patch.object(rom.subprocess,'run') as run:
                binary.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'changed'):
                    rom.directusb_exchange('1-1.2',{},lambda:None)
                run.assert_not_called()
                binary.write_bytes(b'fixture'); row={}
                run.side_effect=subprocess.TimeoutExpired([str(binary)],15,output=b'partial')
                with self.assertRaises(subprocess.TimeoutExpired):
                    rom.directusb_exchange('1-1.2',row,lambda:None)
                self.assertEqual(row['directusb_failure']['kind'],'SUPERVISOR_TIMEOUT_NOT_DRAIN')
                self.assertNotIn('reply',row)
                self.assertEqual(run.call_count,1)

    def test_failed_executor_preserves_report_and_never_retries_usbfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.write_bytes(b'fixture')
            rom.stage_directusb(source,root,{},lambda src,dst,unused:(dst.parent.mkdir(parents=True,exist_ok=True),shutil.copyfile(src,dst)))
            row={};bad=receipt();bad['status']='REFUSED_OR_FAILED'
            with patch.object(rom,'DIRECTUSB_BINARY',root/'bin/ws73-directusb-rom'),patch.object(rom.subprocess,'run',return_value=subprocess.CompletedProcess([],1,json.dumps(bad),'')) as run,patch.object(rom.fcntl,'ioctl',side_effect=AssertionError('no fallback')),self.assertRaises(ValueError):
                rom.rom_observations(None,row,lambda:None,'E',directusb='1-1.2')
            self.assertEqual(run.call_count,1)
            self.assertEqual(row['rom_chip_reads'][0]['directusb_result']['exit'],1)


if __name__=='__main__':unittest.main()
