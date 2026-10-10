# SPDX-License-Identifier: GPL-2.0-only
"""Explicit synthetic byte/manifest fixtures; none are real RF evidence."""
import copy
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
from ws73_capture import CaptureError, check_capture_stats, corroborate, corroborate_synthetic, hcc_receive, marker_data, read_capture
from ws73_north_star import parse_match, parse_result, registration, reports


def aggregate(payload):
    slot = max(64, (len(payload)+4+31)//32*32)
    b = bytearray(92+slot)
    struct.pack_into('<II',b,0,2,len(b));struct.pack_into('<H',b,12,slot)
    struct.pack_into('<BBH',b,92,0xa0,8,len(payload));b[96:96+len(payload)]=payload
    return bytes(b)


def report_payload(marker, address):
    header = bytearray(23);header[2:8]=bytes.fromhex(address.replace(':',''));header[21]=214;header[22]=43
    return b'\xa2\x0b\x18\x42\x00'+header+marker_data(marker)


def pcap(records, endian='<', nano=False):
    magic = (b'\x4d\x3c\xb2\xa1' if nano else b'\xd4\xc3\xb2\xa1')
    if endian=='>':magic=magic[::-1]
    blob = magic+struct.pack(endian+'HHiiII',2,4,0,0,65535,220)
    for bus,device,timestamp,payload,kind,endpoint,status in records:
        sec,ns=divmod(timestamp,1_000_000_000)
        packet=struct.pack(endian+'QBBBBHBBqiiII',123,ord(kind),3,endpoint,device,bus,0,0,sec,ns//1000,status,len(payload),len(payload))+bytes(24)+payload
        fraction=ns if nano else ns//1000
        blob+=struct.pack(endian+'IIII',sec,fraction,len(packet),len(packet))+packet
    return blob


def identity(gen):
    return {'port': '1-2' if gen==2 else '1-1','generation':gen,'index':int(gen==2),
            'path':f'/org/sparklink/slk{int(gen==2)}_g{gen}','address':f'02:73:00:00:00:0{gen}',
            'bus':1,'device':gen+1,'version':'0201000120','features':f'{gen:02x}'*10,
            'buffers':[254,5,0,0],'observed_wall_ns':1_000_000_000,
            'descriptors':{'manufacturer':'unit test vendor','product':'WS73 USB','serial':'sample-'+str(gen)}}


def output_result(d,op,request):
    details={1:'0c05 step=2/3 power=-8 power_valid=1 adv=2 scan=1',3:'1002 step=1/2 power=0 power_valid=0 adv=1 scan=2',2:'0c05 step=0/1 power=0 power_valid=0 adv=1 scan=1',4:'1002 step=0/1 power=0 power_valid=0 adv=1 scan=1'}
    return f'NativeOperationResult: generation={d["generation"]} request={request} operation={op} state=3 errno=0 status=0x00 opcode=0x{details[op]} profile=1\n'


def fixture():
    a,b,new=identity(1),identity(2),identity(3)
    new['observed_wall_ns']=8_900_000_000
    run={'format_version':1,'scope':'physical','status':'CONTROL_PASS_EVIDENCE_PENDING',
         'application_identity':{'uids':[1000]*4,'cap_eff':'0','cap_prm':'0','cap_amb':'0'},'daemon_before':{'pid':100,'start_ticks':20},
         'daemon_after':{'pid':100,'start_ticks':20},'bus_before':{'owner':':1.4','pid':100,'uid':0},
         'bus_after':{'owner':':1.4','pid':100,'uid':0},'initial':[a,b],
         'survivor_control':{'identity':b,'scan_request':{'stdout':output_result(b,3,40)}},
         'stale_selection':{'exit':1,'stderr':'adapter is not a live registration'},'replacement':new,'unplug_observed_wall_ns':8_500_000_000,
         'cleanup':[{'status':'STOP_CONFIRMED'}]*2,'slctl':{'path':'/usr/bin/slctl'},'commands':[], 'rounds':[], 'negatives':[]}
    records=[];seqs={};start=2_000_000_000
    for d in [a,b,new]:
        for op,value in [(0x0404,bytes.fromhex(d['version'])),(0x0403,bytes.fromhex(d['features'])),(0x0406,bytes.fromhex(d['address'].replace(':',''))),(0x0402,struct.pack('<HBHB',*d['buffers']))]:
            data=b'\xa2\x02\x00'+struct.pack('<H',4+len(value))+struct.pack('<H',op)+b'\x01\x00'+value
            records.append((1,d['device'],8_800_000_000 if d is new else 500_000_000,aggregate(data),'C',0x81,0))
    for phase,count,tx,rx in [('initial',20,a,b),('replug',2,new,b)]:
        for n in range(1,count+1):
            marker=f'{len(run["rounds"])+1:032x}'
            payload=report_payload(marker,tx['address']);seq=seqs.get(rx['generation'],0)+1;seqs[rx['generation']]=seq
            match={'generation':rx['generation'],'seq':seq,'address':tx['address'],'rssi':-42,'marker':marker,'data':marker_data(marker).hex(),'kernel_boottime_ns':start,'elapsed_ms':50,'lost':0}
            text=(f'NativeDiscoveryMatch: generation={rx["generation"]} seq={seq} address={tx["address"]} RSSI=-42 marker={marker} data={match["data"]} kernel_boottime_ns={start} elapsed_ms=50 lost=0\n')
            indices=[]
            for op,owner,args in [(1,tx,['advertise','on']),(3,rx,['scan','on',marker,tx['address']]),(2,tx,['advertise','off']),(4,rx,['scan','off'])]:
                command_start = start + {1:0,3:20_000_000,2:110_000_000,4:130_000_000}[op]
                command_end = start + {1:10_000_000,3:100_000_000,2:120_000_000,4:140_000_000}[op]
                for opcode in {1:[0x0c02,0x0c03,0x0c05],3:[0x1001,0x1002],2:[0x0c05],4:[0x1002]}[op]:
                    value=b'\xf8' if opcode==0x0c02 else b''
                    complete=b'\xa2\x02\x00'+struct.pack('<H',4+len(value))+struct.pack('<H',opcode)+b'\x01\x00'+value
                    records.append((1,owner['device'],command_start+5_000_000,aggregate(complete),'C',0x81,0))
                request=100+len(run['commands'])
                admission=f'NativeAdvertisementAccepted: request={request} marker={marker} data={marker_data(marker).hex()}\n' if op==1 else ''
                indices.append(len(run['commands']));run['commands'].append({'args':['/usr/bin/slctl','--adapter',owner['path'],*args],'exit':0,'stdout':admission+output_result(owner,op,request)+(text if op==3 else ''),'start_wall_ns':command_start,'end_wall_ns':command_end,'start_monotonic_ns':command_start,'end_monotonic_ns':command_end})
            run['rounds'].append({'phase':phase,'round':n,'tx':tx,'rx':rx,'marker':marker,'watermark':seq-1,'match':match,'header':payload[5:28].hex(),'scan_window_wall_ns':[start+20_000_000,start+100_000_000],'command_indices':indices})
            records.append((1,rx['device'],start+50_000_000,aggregate(payload),'C',0x81,0));start+=200_000_000
            tx,rx=rx,tx
        run['negatives'].append({'phase':phase,'rx':rx,'transmitter_addresses':[tx['address'],rx['address']],'window_wall_ns':[start,start+2_000_000_000], 'scan_window_wall_ns':[start-1000,start], 'stop_window_wall_ns':[start+2_000_000_000,start+2_000_001_000]})
        for moment in [start-1000,start+2_000_000_000]:
            complete=b'\xa2\x02\x00\x04\x00\x02\x10\x01\x00'
            records.append((1,rx['device'],moment,aggregate(complete),'C',0x81,0))
        start+=3_000_000_000
    return run,records


class CaptureTests(unittest.TestCase):
    def read(self, blob, targets={(1,2),(1,3),(1,4)}):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'fixture.pcap';p.write_bytes(blob);return read_capture(p,targets)
    def test_complete_endian_precision_variants(self):
        run,records=fixture()
        for endian,nano in [('<',False),('>',False),('<',True),('>',True)]:
            with self.subTest(endian=endian,nano=nano):
                parsed=self.read(pcap(records,endian,nano));self.assertEqual(len(corroborate(run,parsed)),22)
    def test_synthetic_corroboration_cannot_be_physical_acceptance(self):
        run,records=fixture();run.update(scope='synthetic WS73 USB control support',status='CONTROL_SUPPORT_EVIDENCE_PENDING')
        for r in [*run['initial'],run['replacement']]:
            r['descriptors']={'manufacturer':'OpenSparklink synthetic test','product':'WS73 runtime fixture (NO RF)','serial':'WS73-TEST'}
        parsed=self.read(pcap(records))
        self.assertEqual(len(corroborate_synthetic(run,parsed)),22)
        with self.assertRaisesRegex(CaptureError,'simulations excluded'):corroborate(run,parsed)
        run['initial'][0]['descriptors']['manufacturer']='real vendor'
        with self.assertRaisesRegex(CaptureError,'fixture descriptors'):corroborate_synthetic(run,parsed)
    def test_physical_record_cannot_enter_synthetic_corroboration(self):
        run,records=fixture()
        with self.assertRaisesRegex(CaptureError,'explicit synthetic'):corroborate_synthetic(run,self.read(pcap(records)))
    def test_renaming_synthetic_status_does_not_promote_record(self):
        run,records=fixture()
        run['initial'][0]['descriptors']['product']='WS73 runtime fixture (NO RF)'
        with self.assertRaisesRegex(CaptureError,'synthetic descriptors excluded'):corroborate(run,self.read(pcap(records)))
    def test_missing_descriptor_boundary_is_rejected(self):
        run,records=fixture();del run['replacement']['descriptors']
        with self.assertRaisesRegex(CaptureError,'recorded USB descriptors'):corroborate(run,self.read(pcap(records)))
    def test_submit_out_cannot_be_rx_proof(self):
        run,records=fixture();records=[(*r[:4],'S',0x01,r[6]) if r[4]=='C' else r for r in records]
        with self.assertRaises(CaptureError):corroborate(run,self.read(pcap(records)))
    def test_wrong_usb_identity(self):
        run,records=fixture()
        with self.assertRaises(CaptureError):corroborate(run,self.read(pcap(records),{(1,99)}))
    def test_truncated_capture_header_record_and_data(self):
        _,records=fixture();blob=pcap(records)
        for data in [b'',blob[:12],blob[:28],blob[:-1]]:
            with self.subTest(size=len(data)),self.assertRaises(CaptureError):self.read(data)
    def test_wrong_linktype(self):
        _,records=fixture();blob=bytearray(pcap(records));struct.pack_into('<I',blob,20,189)
        with self.assertRaises(CaptureError):self.read(blob)
    def test_full_aggregate_atomic_validation(self):
        good=aggregate(report_payload('01'*16,'02:73:00:00:00:01'))
        for mutation in ['length','hole','subtype','tail','oversize']:
            b=bytearray(good)
            if mutation=='length':struct.pack_into('<H',b,94,65535)
            if mutation=='hole':struct.pack_into('<H',b,12,0);struct.pack_into('<H',b,14,64)
            if mutation=='subtype':b[92]=0xa1
            if mutation=='tail':b+=b'\0';struct.pack_into('<I',b,4,len(b))
            if mutation=='oversize':b=bytearray(20481)
            with self.subTest(mutation=mutation),self.assertRaises(CaptureError):hcc_receive(b)
    def test_unknown_service_valid_slot_is_not_discovery(self):
        b=bytearray(aggregate(report_payload('01'*16,'02:73:00:00:00:01')));b[92]=0x70
        self.assertEqual(self.read(pcap([(1,2,1000,bytes(b),'C',0x81,0)]))['reports'],[])
    def test_successful_empty_bulk_is_observation_not_dli(self):
        parsed=self.read(pcap([(1,2,1000,b'','C',0x81,0)]))
        self.assertEqual((parsed['reports'],parsed['complete'],parsed['failures']),([],[],[]))
        self.assertEqual(len(parsed['empty_bulk_completions']),1)
        self.assertEqual(parsed['empty_bulk_completions'][0]['wall_ns'],1000)
    def test_failed_empty_bulk_retains_transport_error(self):
        parsed=self.read(pcap([(1,2,1000,b'','C',0x81,-32)]))
        self.assertEqual(parsed['empty_bulk_completions'],[])
        self.assertEqual(parsed['failures'][0]['status'],-32)
    def test_empty_bulk_declared_length_cannot_hide_payload(self):
        blob=bytearray(pcap([(1,2,1000,b'not-empty','C',0x81,0)]))
        struct.pack_into('<I',blob,24+16+32,0)
        with self.assertRaises(CaptureError):self.read(blob)
    def test_snaplen_drops_payload(self):
        _,records=fixture();blob=bytearray(pcap(records));struct.pack_into('<I',blob,20-4,64)
        with self.assertRaises(CaptureError):self.read(blob)
    def test_usb_data_flag_no_bytes_is_not_full_proof(self):
        _,records=fixture();blob=bytearray(pcap(records));blob[24+16+15]=1
        with self.assertRaises(CaptureError):self.read(blob)
    def test_in_error_during_round_rejected_but_hotplug_cancel_recorded(self):
        run,records=fixture();r=run['rounds'][0];start=r['scan_window_wall_ns'][0]
        records.append((1,r['rx']['device'],start,b'','C',0x81,-32))
        with self.assertRaises(CaptureError):corroborate(run,self.read(pcap(records)))
        records[-1]=(1,r['rx']['device'],99_000_000_000,b'','C',0x81,-2)
        parsed=self.read(pcap(records));self.assertEqual(len(parsed['failures']),1);self.assertEqual(len(corroborate(run,parsed)),22)
    def test_negative_raw_report_rejected(self):
        run,records=fixture();n=run['negatives'][0]
        records.append((1,n['rx']['device'],n['window_wall_ns'][0],aggregate(report_payload('ff'*16,n['transmitter_addresses'][0])),'C',0x81,0))
        with self.assertRaises(CaptureError):corroborate(run,self.read(pcap(records)))
    def test_manifest_mutations_fail_closed(self):
        run,records=fixture();capture=self.read(pcap(records))
        mutations={
            'synthetic':lambda r:r.update(scope='synthetic'),
            'failed_control':lambda r:r.update(status='FAIL'),
            'root':lambda r:r['application_identity'].update(uids=[0]*4),
            'caps':lambda r:r['application_identity'].update(cap_eff='1'),
            'ambient_caps':lambda r:r['application_identity'].update(cap_amb='1'),
            'overlap':lambda r:r['commands'][1].update(start_monotonic_ns=1),
            'daemon_restart':lambda r:r['daemon_after'].update(start_ticks=21),
            'bus_reconnect':lambda r:r['bus_after'].update(owner=':1.5'),
            'stale_accepted':lambda r:r['stale_selection'].update(exit=0),
            'no_final_stop':lambda r:r['cleanup'][0].update(status='FAILED'),
            'lost':lambda r:r['rounds'][0]['match'].update(lost=1),
            'timeout':lambda r:r['rounds'][0]['match'].update(elapsed_ms=10000),
            'wrong_receiver':lambda r:r['rounds'][0]['match'].update(generation=1),
            'cached':lambda r:r['rounds'][0].update(watermark=100),
            'missing_round':lambda r:r['rounds'].pop(),
            'missing_negative':lambda r:r['negatives'].pop(),
            'wrong_admission':lambda r:r['commands'][0].update(stdout=r['commands'][0]['stdout'].replace('Accepted: request=100','Accepted: request=99')),
            'failed_result':lambda r:r['commands'][0].update(stdout=r['commands'][0]['stdout'].replace('state=3','state=4')),
            'negative_short':lambda r:r['negatives'][0].update(window_wall_ns=[0,1]),
        }
        for name,change in mutations.items():
            bad=copy.deepcopy(run);change(bad)
            with self.subTest(name=name),self.assertRaises((CaptureError,ValueError)):corroborate(bad,capture)
    def test_no_metadata_startup_capture(self):
        run,records=fixture();capture=self.read(pcap(records));capture['complete']=[]
        with self.assertRaises(CaptureError):corroborate(run,capture)
    def test_actual_power_not_requested_preference(self):
        d=identity(1);r=parse_result(output_result(d,1,50),d,1);self.assertEqual(r['selected_power'],-8)
        with self.assertRaises(ValueError):parse_result(output_result(d,1,50).replace('generation=1','generation=3'),d,1)
    def test_report_header_address_and_rssi_must_agree(self):
        d=identity(2);payload=report_payload('01'*16,identity(1)['address'])
        line=f'seq=1 generation=2 time_ms=100 address=02:73:00:00:00:01 RSSI=-42 header={payload[5:28].hex()} data={marker_data("01"*16).hex()} lost=0\n'
        self.assertEqual(len(reports(line,d)),1)
        with self.assertRaises(ValueError):reports(line.replace('RSSI=-42','RSSI=-41'),d)
    def test_missing_or_synthetic_device_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError):registration('1-1',Path(tmp))
            d=Path(tmp)/'1-1';d.mkdir();(d/'idVendor').write_text('ffff');(d/'idProduct').write_text('3733');(d/'product').write_text('WS73 runtime fixture')
            with self.assertRaisesRegex(ValueError,'synthetic'):registration('1-1',Path(tmp))
    def test_capture_drop_stats_required(self):
        check_capture_stats('200 packets captured\n210 packets received by filter\n0 packets dropped by kernel\n')
        for text in ['', '1 packets captured\n1 packets dropped by kernel\n', '0 packets captured\n0 packets dropped by kernel\n', '1 packets captured\n0 packets dropped by kernel\n0 packets dropped by kernel\n']:
            with self.subTest(text=text),self.assertRaises(CaptureError):check_capture_stats(text)
    def test_marker_never_interprets_missing_bytes_as_success(self):
        with self.assertRaises(CaptureError):marker_data('ab')
        with self.assertRaises(ValueError):parse_match('no fresh match\n')


if __name__=='__main__':unittest.main()
