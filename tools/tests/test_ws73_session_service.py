# SPDX-License-Identifier: GPL-2.0-only
"""Parser/association fixtures only;no actual kernel tracing or hardware."""
import copy
import unittest
from unittest.mock import patch

from ws73_session_service import EVENTS, STATUS, parse, join, vm_guard, cleanup
from ws73_trace_layout import buffer_kib


BASE=100_000_000_000
WALL=1_700_000_000_000_000_000


def fixture():
    row=dict(status=STATUS,cookie='a'*32,instance_removed=True,clock='mono',requested_buffer_kb=2048,
             readbacks=dict(current_tracer='nop',trace_clock='local [mono]',buffer_size_kb='2051',buffer_subbuf_size_kb='4'),
             enabled=dict.fromkeys(EVENTS,'1'),disabled=dict.fromkeys(EVENTS,'0'),
             header_page='field: char data; offset:16; size:4080;',anchors=[],stats={})
    for kind,t in [('begin',BASE),('end',BASE+1_000_000)]:
        row['anchors'].append(dict(kind=kind,mono_before=t-4000,mono_after=t-2000,wall_ns=t-3000+WALL,mark_before=t-1000,mark_after=t+1000))
    records=[];owners={};capture=dict(acb_packets=[])
    for ctl in range(2):
        ident=dict(ctl=ctl,gen=ctl+1,life=1)
        def event(kind,delta,**kw):
            data=ident|kw
            body=' '.join(k+'='+str(data[k]) for k in EVENTS['sparklink_session_'+kind])
            records.append((BASE+delta,ctl,'sparklink_session_'+kind,body))
        w=dict(epoch=4,service=1,stage=0,attempts=0,bytes=0,stop=0,elapsed_ns=0,planned_delay=2**64-1,error=0)
        event('work',100_000,**w)
        queue=dict(epoch=4,sequence=1,slot=0,bytes=8,deadline=5042)
        for stage,delta in [(0,50_000),(1,110_000),(2,150_000)]:event('queue',delta,stage=stage,**queue)
        tx=dict(service=1,sequence=1,slot=0,pb=0,len=8,offset=0,wait=0)
        for stage,delta,result in [(0,120_000,-115),(2,130_000,0),(1,140_000,0)]:event('tx',delta,stage=stage,result=result,**tx)
        event('work',160_000,**(w|dict(stage=1,attempts=1,bytes=8,elapsed_ns=60_000)))
        owners[ctl,ctl+1,1]=dict(bus=1,device=ctl+2,handle=0,epoch=4)
        capture['acb_packets'].append(dict(bus=1,device=ctl+2,handle=0,direction='out',boundary=0,data='00'*8,wall_ns=WALL+BASE+125_000))
    def line(t,cpu,name,body):return f' worker-123 [{cpu:03d}] .... {t//10**9}.{t%10**9//1000:06d}: {name}: {body}'
    rows=[line(BASE,0,'tracing_mark_write','SLK_SERVICE_BEGIN:'+row['cookie'])]
    rows.extend(line(t,cpu,name,body) for t,cpu,name,body in sorted(records))
    rows.append(line(BASE+1_000_000,0,'tracing_mark_write','SLK_SERVICE_END:'+row['cookie']))
    text=f'# tracer: nop\n# entries-in-buffer/entries-written: {len(rows)}/{len(rows)}\n'+'\n'.join(rows)+'\n'
    for cpu,n in [('cpu0',10),('cpu1',8)]:row['stats'][cpu]=f'entries: {n}\noverrun: 0\ncommit overrun: 0\ndropped events: 0\n'
    return text,row,owners,capture


class ServiceTrace(unittest.TestCase):
    def test_software_and_usb_acceptance_are_not_peer_completion(self):
        text,row,owners,capture=fixture();p=parse(text,row);out=join(p,owners,capture)
        self.assertEqual(out['services'],2);self.assertEqual(out['accepted_usb_packets'],2)
        self.assertEqual(out['complete_transport_operations'],2);self.assertEqual(out['partial_retired_operations'],0)
        self.assertEqual(p['offset_ns'],[WALL-1000,WALL+1000]);self.assertNotIn('peer_delivery',out)

    def test_capture_loss_markers_clocks_and_configuration_fail_closed(self):
        for kind in ['cookie','loss','stats','count','marker','clock','clock-step','buffer','float-buffer','schema','unknown','outside']:
            text,row,_,_=fixture()
            if kind=='cookie':row['cookie']='b'*32
            elif kind=='loss':text+='CPU LOST EVENTS\n'
            elif kind=='stats':row['stats']['cpu1']=row['stats']['cpu1'].replace('overrun: 0','overrun: 1')
            elif kind=='count':row['stats']['cpu1']=row['stats']['cpu1'].replace('entries: 8','entries: 0')
            elif kind=='marker':text=text.replace('SLK_SERVICE_END','SLK_SERVICE_BEGIN')
            elif kind=='clock':row['readbacks']['trace_clock']='[global] mono'
            elif kind=='clock-step':row['anchors'][1]['wall_ns']+=1_000_000
            elif kind=='buffer':row['readbacks']['buffer_size_kb']='1024'
            elif kind=='float-buffer':row['requested_buffer_kb']=2048.0
            elif kind=='schema':text=text.replace('gen=1','gen=1.0')
            elif kind=='unknown':text=text.replace('sparklink_session_tx','unknown_event')
            else:text=text.replace('100.000120','101.000120')
            with self.subTest(kind=kind),self.assertRaises(ValueError):parse(text,row)

    def test_identity_accounting_and_physical_submit_negatives(self):
        for kind in ['old-generation','wrong-epoch','float-owner','missing-commit','duplicate-stage','count','stop','deadline','pb','offset','usb-length','usb-time','missing-usb','extra-usb','outside-worker','retire-missing']:
            text,row,owners,capture=fixture();p=parse(text,row)
            if kind=='old-generation':p['rows'][0]['gen']+=4
            elif kind=='wrong-epoch':owners[0,1,1]['epoch']+=1
            elif kind=='float-owner':owners[0,1,1]['handle']=0.0
            elif kind=='missing-commit':p['rows']=[v for v in p['rows'] if not(v['event']=='tx' and v['stage']==2)]
            elif kind=='duplicate-stage':p['rows'].append(copy.deepcopy(p['rows'][0]))
            elif kind=='count':next(v for v in p['rows'] if v['event']=='work' and v['stage']==1)['attempts']=2
            elif kind=='stop':next(v for v in p['rows'] if v['event']=='work' and v['stage']==1)['stop']=1
            elif kind=='deadline':next(v for v in p['rows'] if v['event']=='queue' and v['stage']==2)['deadline']+=1
            elif kind=='pb':next(v for v in p['rows'] if v['event']=='tx')['pb']=1
            elif kind=='offset':next(v for v in p['rows'] if v['event']=='tx')['offset']=1
            elif kind=='usb-length':capture['acb_packets'][0]['data']='00'*7
            elif kind=='usb-time':capture['acb_packets'][0]['wall_ns']+=1_000_000
            elif kind=='missing-usb':capture['acb_packets'].pop()
            elif kind=='extra-usb':capture['acb_packets'].append(copy.deepcopy(capture['acb_packets'][0]))
            elif kind=='outside-worker':next(v for v in p['rows'] if v['event']=='tx')['mono_ns']+=1_000_000
            else:p['rows']=[v for v in p['rows'] if not(v['event']=='queue' and v['stage']==2)]
            with self.subTest(kind=kind),self.assertRaises(ValueError):join(p,owners,capture)

    def test_no_host_trace_configuration(self):
        with patch('ws73_session_service.os.geteuid',return_value=1000),self.assertRaises(ValueError):vm_guard()

    def test_accepted_uncertain_failure_is_not_a_completed_operation(self):
        text,row,owners,capture=fixture();p=parse(text,row)
        next(v for v in p['rows'] if v['event']=='tx' and v['ctl']==0 and v['stage']==1)['result']=-5
        out=join(p,owners,capture)
        self.assertEqual(out['uncertain_acceptances'],1)
        self.assertEqual(out['accepted_usb_packets'],2)
        self.assertEqual(out['complete_transport_operations'],1)
        self.assertEqual(out['partial_retired_operations'],1)

    def test_two_fragment_stream_cannot_be_interleaved_by_control(self):
        text,row,owners,capture=fixture();p=parse(text,row)
        first=[v for v in p['rows'] if v['event']=='tx' and v['ctl']==0]
        for v in first:v.update(len=4,pb=1)
        for v in p['rows']:
            if v['ctl']==0 and v['event']=='queue' and v['stage']==2:v['mono_ns']=BASE+170_000
            if v['ctl']==0 and v['event']=='work' and v['stage']==1:v.update(attempts=2,mono_ns=BASE+180_000,elapsed_ns=80_000)
        for v in first:
            n=copy.deepcopy(v);n.update(offset=4,pb=3,mono_ns=BASE+{0:150_000,2:151_000,1:152_000}[v['stage']]);p['rows'].append(n)
        capture['acb_packets'][0].update(data='00'*4,boundary=1)
        packet=copy.deepcopy(capture['acb_packets'][0]);packet.update(boundary=3,wall_ns=WALL+BASE+150_500);capture['acb_packets'].insert(1,packet)
        self.assertEqual(join(p,owners,capture)['complete_transport_operations'],2)
        for v in first:
            n=copy.deepcopy(v);n.update(slot=-1,sequence=123,len=1,pb=0,mono_ns=BASE+{0:142_000,2:143_000,1:144_000}[v['stage']]);p['rows'].append(n)
        with self.assertRaisesRegex(ValueError,'interleaved'):join(p,owners,capture)

    def test_requeued_unstarted_eagain_requires_no_physical_acceptance(self):
        text,row,owners,capture=fixture();p=parse(text,row)
        old=[copy.deepcopy(v) for v in p['rows'] if v['ctl']==0]
        for v in old:
            if v['event']=='work':
                v['service']=2
                if v['stage']==1:v.update(error=-11)
            elif v['event']=='tx':
                v['service']=2
                if v['stage']==1:v.update(result=-11,wait=1)
                if v['stage']==2:continue
            elif v['stage']!=1:continue
            v['mono_ns']-=40_000;p['rows'].append(v)
        p['rows'].sort(key=lambda v:v['mono_ns'])
        out=join(p,owners,capture)
        self.assertEqual(out['credit_waits'],1)
        self.assertEqual(out['accepted_usb_packets'],2)
        self.assertEqual(out['complete_transport_operations'],2)
        next(v for v in p['rows'] if v['event']=='tx' and v['service']==2 and v['stage']==1)['result']=-5
        with self.assertRaisesRegex(ValueError,'repeated dequeue'):join(p,owners,capture)

    def test_runner_never_promotes_trace_over_original_gate(self):
        from ws73_target import run_exit_code
        good=dict(status='PASSTHROUGH_SUPPORT_PASS',qemu_exit=0,
                  session_service_observation_requested=True,session_service_acceptance=True,
                  session_service_observation=dict(status='REAL_SESSION_SERVICE_AND_USB_SUBMITS_CORROBORATED',
                                                   services=2,attempts=2,accepted_usb_packets=2,operations=2))
        self.assertEqual(run_exit_code(good),0)
        for changes in [dict(status='FAIL'),dict(qemu_exit=1),dict(session_service_acceptance=False),
                        dict(session_service_observation_requested=False),dict(session_service_observation={})]:
            with self.subTest(changes=changes):self.assertEqual(run_exit_code(good|changes),1)
        for value in [True,0,1.0]:
            bad=copy.deepcopy(good);bad['session_service_observation']['attempts']=value
            self.assertEqual(run_exit_code(bad),1)

    def test_runner_rejects_unsupported_trace_before_prepare_or_device_access(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        import ws73_target
        for changes in [dict(),dict(dynamic_channel_verify=True,channel_socket_verify=True,connection_verify=True,qmp_hotplug=True),
                        dict(command='support')]:
            with tempfile.TemporaryDirectory() as d:
                fields=dict(command='run',session_service_observe=True,output=Path(d)/'absent')|changes
                with patch.object(ws73_target,'ordinary_identity'),patch.object(ws73_target,'prepared') as prepare, self.assertRaisesRegex(ValueError,'Session service trace'):
                    ws73_target._run(SimpleNamespace(**fields))
                prepare.assert_not_called();self.assertFalse(fields['output'].exists())

    def test_partial_initialization_disables_only_own_instance(self):
        writes=[]
        class TracePath:
            def __init__(self,name):self.name=name
            def __truediv__(self,name):return TracePath(self.name+'/'+name)
            def exists(self):return True
            def write_text(self,text):writes.append((self.name,text))
            def rmdir(self):writes.append((self.name,'rmdir'))
        with patch('ws73_session_service.INSTANCE',TracePath('own-instance')):
            row=dict(created=False);cleanup(row);self.assertEqual(writes,[])
            row=dict(created=True);cleanup(row);self.assertEqual(row['cleanup_errors'],[])
        self.assertEqual(len(writes),5);self.assertEqual(writes[-1],('own-instance','rmdir'))
        self.assertTrue(all(v[1]=='0\n' for v in writes[:-1]))

    def test_trace_buffer_rounding_shared_with_benchmark(self):
        self.assertEqual(buffer_kib('field: char data; offset:16; size:4080;',1024,4),(1027,4080))
        for value in [True,1024.0,-1,9000]:
            with self.assertRaises(ValueError):buffer_kib('field: char data; offset:16; size:4080;',value,4)
