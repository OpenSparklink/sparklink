# SPDX-License-Identifier: GPL-2.0-only
"""Finite management observations through slctl; independent raw DLI matching.

No controller open, Host, data loop or radio configuration. A measurement is
neither application delivery nor RF/PHY policy qualification.
"""
import json
import re
import time
from ws73_capture import CaptureError, command_reply

TOKEN = 'ws73.link_measurements=1'
KINDS = ((1, 'rssi', 0x180c, 3), (2, 'phy', 0x1805, 10))
LOAD_TOKEN = 'ws73.load_link_probe=once-rssi-6s'
LOAD_REQUEST = 'load_link_probe_request'
LOAD_FIELD = 'load_link_probe'
LOAD_SPEC = dict(version=1, offset_ns=6_000_000_000, max_queries=2,
                 kind=1, timeout_ms=5000, child_budget_ns=7_000_000_000)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CaptureError('duplicate observation field')
        result[key] = value
    return result


def observation(row, entry, kind):
    owner, identity = entry['owner'], entry['object']
    args = row.get('args', [])
    if (len(args) != 7 or not re.fullmatch(r'(?:/bin|/usr/libexec/opensparklink/native-lab/[0-9a-f]{12})/slctl', args[0])
            or args[1:] != ['--adapter', owner['path'], 'link-measurement', identity['path'], dict((n, word) for n, word, _, _ in KINDS)[kind], '5000']
            or row.get('exit') != 0 or row.get('stderr')):
        raise CaptureError('actual successful slctl management observation required')
    text = row.get('stdout', '')
    prefix = 'Selected '+owner['path']+'\n'
    if text.startswith(prefix):
        text = text[len(prefix):]
    if len(text.encode()) > 4096 or not text.startswith('NativeLinkMeasurement: ') or text.count('\n') != 1 or not text.endswith('\n'):
        raise CaptureError('one bounded original observation receipt required')
    value = json.loads(text[len('NativeLinkMeasurement: '):], object_pairs_hook=unique_object)
    fields = {'generation','lifetime','handle','role','address_type','address','request_id',
              'deadline_monotonic_ns','kind','state','error','status','flags','data'}
    if type(value) is not dict or set(value) != fields:
        raise CaptureError('exact typed observation fields required')
    for name in fields-{'address','data'}:
        if type(value[name]) is not int:
            raise CaptureError('integer observation field required')
    if identity['generation'] != owner['generation'] or any(value[name] != identity[name] for name in ['generation','lifetime','handle','role','address_type','address']):
        raise CaptureError('full original physical lifetime required')
    if (value['kind'] != kind or not 0 < value['request_id'] < 1 << 64
            or not 0 < value['deadline_monotonic_ns'] < 1 << 64
            or (value['state'],value['error'],value['status'],value['flags']) != (2,0,0,7)):
        raise CaptureError('current available real successful Complete required')
    data = value['data']
    size = dict((n, size) for n, _, _, size in KINDS)[kind]
    if type(data) is not list or len(data) != size or any(type(n) is not int or not 0 <= n <= 255 for n in data):
        raise CaptureError('exact bounded reply bytes required')
    if int.from_bytes(bytes(data[:2]), 'little') != identity['handle'] or kind == 1 and data[2] == 127:
        raise CaptureError('echoed handle and available RSSI required')
    return value


def execute(run, entry):
    """Before application workloads; never refresh their leases or deadlines."""
    if 'link_measurements' in entry:
        raise CaptureError('observations must not be silently repeated')
    record = dict(version=1, status='RUNNING_NOT_QUALIFIED', queries=[])
    entry['link_measurements'] = record
    run.data.setdefault('link_measurement_attempts', []).append(dict(owner=entry['owner'], object=entry['object'], record=record))
    run.save()
    try:
        for kind, word, _, _ in KINDS:
            command = [str(run.args.slctl), '--adapter', entry['owner']['path'],
                       'link-measurement', entry['object']['path'], word, '5000']
            row = run.command(command, 7, collection='link_measurement_commands')
            query = dict(kind=kind, command=row)
            record['queries'].append(query); run.save()
            query['observation'] = observation(row, entry, kind)
            run.save()
        record['status'] = 'REAL_REPLY_PENDING_RAW_AUDIT'
    except BaseException as error:
        record.update(status='FAIL', error=type(error).__name__+': '+str(error))
        raise
    finally:
        record['end_monotonic_ns'] = time.monotonic_ns()
        run.save()


def corroborate_entry(entry, capture):
    record = entry.get('link_measurements', {})
    if record.get('version') != 1 or record.get('status') != 'REAL_REPLY_PENDING_RAW_AUDIT' or len(record.get('queries', [])) != 2:
        raise CaptureError('two original completed observations required')
    proofs = []
    for query, (kind, _, opcode, _) in zip(record['queries'], KINDS):
        if query['kind'] != kind:
            raise CaptureError('original RSSI then PHY order required')
        row = query['command']
        value = observation(row, entry, kind)
        if value != query['observation']:
            raise CaptureError('observation differs from original command receipt')
        proof = command_reply(capture, entry['owner'], opcode, row['start_wall_ns'], row['end_wall_ns'],
                              entry['object']['handle'].to_bytes(2, 'little'), bytes(value['data']).hex())
        proofs.append(dict(kind=kind, scope=value, real_DLI=proof))
    if proofs[0]['scope']['request_id'] >= proofs[1]['scope']['request_id']:
        raise CaptureError('distinct monotonic query author IDs required')
    return dict(status='FINITE_REAL_LINK_OBSERVATIONS', queries=proofs,
                scope='Actual typed management/DLI RSSI and eight opaque PHY bytes;not application delivery,RF timing or PHY policy.')


def corroborate(run, capture, requested):
    if type(requested) is not bool:
        raise CaptureError('explicit observation scope required')
    phases = run.get('connection_control', {}).get('phases', [])
    entries = [entry for phase in phases for entry in phase.get('typed_objects', [])]
    present = [entry for entry in entries if 'link_measurements' in entry]
    commands = run.get('link_measurement_commands', [])
    if not requested:
        if present or commands or run.get('link_measurement_attempts'):
            raise CaptureError('unrequested observations cannot be awarded')
        return None
    if len(entries) != 4 or len(present) != 4 or len(commands) != 8:
        raise CaptureError('both controllers and both connection roles required')
    identity = run.get('application_identity', {})
    uids = identity.get('uids', [])
    if len(uids) != 4 or any(type(uid) is not int or uid <= 0 for uid in uids) or len(set(uids)) != 1 or any(int(identity.get(k, '1'),16) for k in ['cap_eff','cap_prm','cap_amb']):
        raise CaptureError('actual ordinary caller identity required')
    if len(phases) != 2 or any(len(p.get('typed_objects', [])) != 2 for p in phases):
        raise CaptureError('two complete connection phases required')
    registrations = [set(tuple(e['owner'][k] for k in ['bus','device','generation','path']) for e in p['typed_objects']) for p in phases]
    if len(registrations[0]) != 2 or registrations[0] != registrations[1]:
        raise CaptureError('same two distinct original registrations required')
    recorded = [query['command'] for entry in entries for query in entry['link_measurements']['queries']]
    if recorded != commands:
        raise CaptureError('all actual supervisor commands must be accounted for')
    if run.get('link_measurement_attempts') != [dict(owner=e['owner'], object=e['object'], record=e['link_measurements']) for e in entries]:
        raise CaptureError('all original attempts and outcomes must be retained')
    proofs, last_ids = [], {}
    for entry in entries:
        proof = corroborate_entry(entry, capture)
        key = tuple(entry['owner'][k] for k in ['bus','device','generation'])
        for query in proof['queries']:
            request_id = query['scope']['request_id']
            if request_id <= last_ids.get(key, 0):
                raise CaptureError('old query author ID reused in this registration')
            last_ids[key] = request_id
        proofs.append(proof)
    return proofs


def exit_gate(record):
    requested = record.get('link_measurements_requested', False)
    if type(requested) is not bool:
        return False
    if not requested:
        return not any(k in record for k in ['link_measurement_acceptance','link_measurement_corroboration','link_measurement_verifier'])
    args = record.get('qemu_args', [])
    append = [args[i+1] for i, word in enumerate(args[:-1]) if word == '-append']
    if len(append) != 1 or append[0].split().count(TOKEN) != 1 or record.get('link_measurement_acceptance') is not True:
        return False
    proofs = record.get('link_measurement_corroboration', [])
    verifier = record.get('link_measurement_verifier', {})
    return (len(proofs) == 4 and bool(re.fullmatch('[0-9a-f]{64}', verifier.get('sha256', '')))
            and all(p.get('status') == 'FINITE_REAL_LINK_OBSERVATIONS'
                    and [q.get('kind') for q in p.get('queries', [])] == [1,2] for p in proofs))


def load_command(entry):
    return ['/bin/slctl','--adapter',entry['owner']['path'],
            'link-measurement',entry['object']['path'],'rssi','5000']


def _load_query(entry, stop):
    from ws73_transport_watch import collect_process, ordinary
    row=collect_process(load_command(entry),stop,
        credentials=dict(user=1000,group=1000,extra_groups=[],umask=0o077),
        budget_ns=LOAD_SPEC['child_budget_ns'])
    if row['outcome']=='EXITED':
        try:
            if not ordinary(row['credentials']):
                raise CaptureError('ordinary management caller credentials required')
            row['observation']=observation(row,entry,1)
            row['outcome']='LINK_REPLY_OBSERVED'
        except (CaptureError,KeyError,ValueError)as error:
            row['observation_error']=str(error)
            row['outcome']='LINK_QUERY_NOT_SUCCESSFUL'
    return row


class LoadProbe:
    """Two finite CLI attempts,using the existing child collector,not a Host.

    Thread publication happens only after join. Child reap/author cancellation
    never means that the Native physical command obligation has drained.
    """
    def __init__(self,owners,phase,barrier_monotonic_ns,*,query_fn=None):
        import copy,threading
        if (len(owners)!=2 or type(phase)is not int or phase not in (0,1)
                or type(barrier_monotonic_ns)is not int or barrier_monotonic_ns<=0):
            raise CaptureError('two original owners and actual phase start barrier required')
        self.owners=copy.deepcopy(owners);self.query_fn=query_fn or _load_query
        self.stop=threading.Event();self.armed=threading.Event();self.closed=False
        self.thread=threading.Thread(target=self._run,name='ws73-load-link-probe',daemon=False)
        self.report=dict(version=1,spec=dict(LOAD_SPEC),phase=phase,samples=[],
            barrier_monotonic_ns=barrier_monotonic_ns,
            planned_monotonic_ns=barrier_monotonic_ns+LOAD_SPEC['offset_ns'],
            status='STARTING_NOT_QUALIFIED',performance_qualified=False,
            physical_drain_qualified=False,application_delivery_qualified=False)

    def start(self):
        from pathlib import Path
        from ws73_transport_watch import require_environment
        from ws73_benchmark_ssap import from_boot,probing_link
        require_environment();words=Path('/proc/cmdline').read_text().split()
        if words.count(LOAD_TOKEN)!=1 or not probing_link(from_boot(words)):
            raise CaptureError('one explicit fixed load link probe VM required')
        self.thread.start()
        if not self.armed.wait(1):
            self.close();raise CaptureError('finite link probe did not arm')
        return self

    def _run(self):
        try:
            self.report.update(start_wall_ns=time.time_ns(),start_monotonic_ns=time.monotonic_ns(),
                               status='RUNNING_NOT_QUALIFIED')
            self.armed.set()
            if not self.stop.wait(max(0,(self.report['planned_monotonic_ns']-time.monotonic_ns())/1e9)):
                for endpoint,entry in enumerate(self.owners):
                    if self.stop.is_set():break
                    receipt=self.query_fn(entry,self.stop)
                    self.report['samples'].append(dict(endpoint=endpoint,receipt=receipt))
                    if receipt.get('reaped')is not True:
                        raise CaptureError('unreaped query;no further observer admission')
            self.report['status']='COLLECTED_NOT_QUALIFIED'
        except BaseException as error:
            self.report.update(status='OBSERVER_ERROR',error=type(error).__name__+': '+str(error))
        finally:
            self.report.update(worker_end_wall_ns=time.time_ns(),worker_end_monotonic_ns=time.monotonic_ns())
            self.armed.set()

    def close(self):
        if self.closed:return self.report
        if not self.stop.is_set():
            self.report_stop_wall_ns=time.time_ns();self.report_stop_monotonic_ns=time.monotonic_ns()
            self.stop.set()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise CaptureError('finite link observer join timeout;not physical drain or PASS')
        self.closed=True
        self.report.update(stop_wall_ns=self.report_stop_wall_ns,stop_monotonic_ns=self.report_stop_monotonic_ns,
            end_wall_ns=time.time_ns(),end_monotonic_ns=time.monotonic_ns(),thread_joined=True,
            unattempted_endpoints=list(range(len(self.report['samples']),2)))
        return self.report


def validate_load(row,capture,requested,*,failed=False):
    """Strict collection/real-reply evidence;never repairs a failed workload."""
    from ws73_transport_watch import ordinary, SPEC
    if type(requested)is not bool or type(failed)is not bool:
        raise CaptureError('explicit original load probe scope required')
    report=row.get(LOAD_FIELD)
    if not requested:
        if report is not None:raise CaptureError('unrequested load probe')
        if capture is not None:
            starts=[e['wall_ns']for e in row.get('events',[])if e['kind']=='start']
            if starts and any(q['opcode']==0x180c and max(starts)<=q['wall_ns']<=row['end_wall_ns']
                    and any((q['bus'],q['device'])==(e['owner']['bus'],e['owner']['device'])for e in row['owners'])
                    for q in capture.get('commands',[])):
                raise CaptureError('unrequested in-load RSSI command cannot disappear with profile removal')
        return None
    if failed and(row.get('status')!='FAIL'or not row.get('error')):
        raise CaptureError('original failed phase/error required')
    if not failed and row.get('status')=='FAIL':raise CaptureError('failed phase is not qualified')
    starts=[e for e in row['events']if e['kind']=='start']
    if (len(starts)!=2 or {e['application']for e in starts}!={0,1}
            or any(type(e.get('monotonic_ns'))is not int for e in starts)):
        raise CaptureError('two actual application start barriers required')
    barrier=max(e['monotonic_ns']for e in starts)
    if (type(report)is not dict or type(report.get('version'))is not int or report['version']!=1
            or report.get('spec')!=LOAD_SPEC or any(type(v)is not int for v in report['spec'].values())
            or report.get('thread_joined')is not True or report.get('status')!='COLLECTED_NOT_QUALIFIED'
            or type(report.get('phase'))is not int or report['phase']!=row['phase']
            or any(report.get(k)is not False for k in ('performance_qualified','physical_drain_qualified','application_delivery_qualified'))
            or report.get('barrier_monotonic_ns')!=barrier
            or report.get('planned_monotonic_ns')!=barrier+LOAD_SPEC['offset_ns']):
        raise CaptureError('original finite stopped/joined load probe required')
    if len(json.dumps(report).encode())>65536:
        raise CaptureError('finite load probe report byte budget')
    clocks=('start_wall_ns','start_monotonic_ns','worker_end_wall_ns','worker_end_monotonic_ns',
            'stop_wall_ns','stop_monotonic_ns','end_wall_ns','end_monotonic_ns','barrier_monotonic_ns','planned_monotonic_ns')
    if (any(type(report.get(k))is not int for k in clocks)
            or not row['start_wall_ns']<=report['start_wall_ns']<=report['worker_end_wall_ns']<=report['end_wall_ns']<=row['end_wall_ns']
            or not report['start_wall_ns']<=report['stop_wall_ns']<=report['end_wall_ns']
            or not barrier<=report['start_monotonic_ns']<=report['worker_end_monotonic_ns']<=report['end_monotonic_ns']
            or not report['start_monotonic_ns']<=report['stop_monotonic_ns']<=report['end_monotonic_ns']):
        raise CaptureError('original joined observer clocks required')
    samples=report['samples']
    if (type(samples)is not list or len(samples)>2
            or report.get('unattempted_endpoints')!=list(range(len(samples),2))
            or type(report.get('unattempted_endpoints'))is not list
            or any(type(i)is not int for i in report['unattempted_endpoints'])):
        raise CaptureError('all finite attempts and unattempted endpoints required')
    success=[];previous=report['planned_monotonic_ns']
    for endpoint,sample in enumerate(samples):
        receipt=sample['receipt'];entry=row['owners'][endpoint]
        if (type(sample.get('endpoint'))is not int or sample['endpoint']!=endpoint
                or receipt.get('args')!=load_command(entry) or receipt.get('reaped')is not True
                or type(receipt.get('pid'))is not int or receipt['pid']<=0
                or receipt.get('outcome')not in ('LINK_REPLY_OBSERVED','LINK_QUERY_NOT_SUCCESSFUL','CANCELLED_OBSERVER_STOP','QUERY_TIMEOUT')
                or any(type(receipt.get(k))is not int for k in ('start_wall_ns','end_wall_ns','start_monotonic_ns','end_monotonic_ns','deadline_monotonic_ns','exit'))
                or receipt['deadline_monotonic_ns']!=receipt['start_monotonic_ns']+LOAD_SPEC['child_budget_ns']
                or not previous<=receipt['start_monotonic_ns']<=report['stop_monotonic_ns']
                or not receipt['start_monotonic_ns']<=receipt['end_monotonic_ns']<=report['worker_end_monotonic_ns']
                or not report['start_wall_ns']<=receipt['start_wall_ns']<=receipt['end_wall_ns']<=report['worker_end_wall_ns']
                or max(len(receipt[k].encode())for k in ('stdout','stderr'))>SPEC['stream_limit_bytes']):
            raise CaptureError('original bounded reaped same-lifetime query attempt required')
        previous=receipt['end_monotonic_ns']
        if receipt['outcome']=='LINK_REPLY_OBSERVED':
            value=observation(receipt,entry,1)
            if (receipt.get('observation')!=value or not ordinary(receipt['credentials'])
                    or not receipt['start_monotonic_ns']<value['deadline_monotonic_ns']<=receipt['deadline_monotonic_ns']):
                raise CaptureError('actual current original-deadline observation required')
            initial=entry.get('link_measurements',{}).get('queries',[])
            if len(initial)!=2 or value['request_id']<=max(q['observation']['request_id']for q in initial):
                raise CaptureError('new author ID after original initial observations required')
            wire=None if capture is None else command_reply(capture,entry['owner'],0x180c,
                receipt['start_wall_ns'],receipt['end_wall_ns'],entry['object']['handle'].to_bytes(2,'little'),bytes(value['data']).hex())
            success.append(dict(endpoint=endpoint,observation=value,real_DLI=wire))
        elif 'observation'in receipt:
            raise CaptureError('failed/cancelled query cannot publish an observation')
    if not failed and(len(samples)!=2 or len(success)!=2):
        raise CaptureError('both finite actual queries must succeed;missing is not zero')
    raw_counts=raw_completions=None
    if capture is not None:
        raw_counts=[];raw_completions=[]
        for endpoint,entry in enumerate(row['owners']):
            counts=[q for q in capture['commands']if q['opcode']==0x180c
                and (q['bus'],q['device'])==(entry['owner']['bus'],entry['owner']['device'])
                and max(e['wall_ns']for e in starts)<=q['wall_ns']<=row['end_wall_ns']]
            if len(counts)>1:raise CaptureError('at most one actual in-load RSSI submission per endpoint')
            if counts and endpoint>=len(samples):raise CaptureError('unattempted endpoint cannot hide a raw query')
            raw_counts.append(len(counts))
            replies=[q for q in capture['complete']if q['opcode']==0x180c
                and (q['bus'],q['device'])==(entry['owner']['bus'],entry['owner']['device'])
                and max(e['wall_ns']for e in starts)<=q['wall_ns']<=row['end_wall_ns']]
            # Failed/unavailable typed result is not absence of a wire reply.
            # Retain duplicates/late candidates without attributing them a
            # lifetime or upgrading them to successful observation/air delivery.
            raw_completions.append(dict(endpoint=endpoint,candidates=replies))
    return dict(status='FAILED_ROLE_LINK_PROBE_OBSERVED_NOT_QUALIFIED'if failed else'FINITE_LOAD_LINK_REPLIES_PENDING_WHOLE_GATE',
        attempts=len(samples),successful_replies=len(success),unattempted_endpoints=report['unattempted_endpoints'],
        queries=success,raw_command_counts=raw_counts,raw_completion_candidates=raw_completions,
        original_role_qualified=False if failed else None,
        physical_drain_qualified=False,application_delivery_qualified=False,performance_qualified=False)


def valid_load_summary(proof):
    """Final metadata gate needs both raw corroborations,not collection only."""
    try:
        if (proof['status']!='FINITE_LOAD_LINK_REPLIES_PENDING_WHOLE_GATE'
                or type(proof['attempts'])is not int or proof['attempts']!=2
                or type(proof['successful_replies'])is not int or proof['successful_replies']!=2
                or proof['raw_command_counts']!=[1,1]or any(type(v)is not int for v in proof['raw_command_counts'])
                or proof['unattempted_endpoints']!=[] or proof['original_role_qualified']is not None
                or any(proof[k]is not False for k in ('physical_drain_qualified','application_delivery_qualified','performance_qualified'))
                or len(proof['queries'])!=2):return False
        for endpoint,query in enumerate(proof['queries']):
            value=query['observation'];wire=query['real_DLI']
            if (type(query['endpoint'])is not int or query['endpoint']!=endpoint
                    or any(type(value[k])is not int for k in ('generation','lifetime','handle','kind','state','error','status','flags'))
                    or (value['kind'],value['state'],value['error'],value['status'],value['flags'])!=(1,2,0,0,7)
                    or len(value['data'])!=3 or any(type(v)is not int or not 0<=v<=255 for v in value['data'])
                    or type(wire['reply']['status'])is not int
                    or wire['command']['opcode']!=0x180c or wire['reply']['opcode']!=0x180c
                    or wire['reply']['status']!=0 or wire['reply']['value']!=bytes(value['data']).hex()
                    or wire['command']['params']!=value['handle'].to_bytes(2,'little').hex()):return False
        return True
    except (KeyError,TypeError,ValueError,AttributeError):return False


def diagnose_load(directory,phase):
    """Read only retained failed artifacts;never launches a VM or a query."""
    from ws73_rx_gap import failed_phase_inputs
    from ws73_benchmark_ssap import selected,probing_link,from_boot
    from ws73_capture import read_capture,check_capture_stats
    root,manifest,control,request,row,exported=failed_phase_inputs(directory,phase)
    args=manifest['qemu_args'];tokens=args[args.index('-append')+1].split()
    if not probing_link(selected(request))or selected(request)!=selected(row)or selected(row)!=from_boot(tokens):
        raise CaptureError('original explicit load-probe request/boot/profile required')
    owners=[*control['initial'],*([control['replacement']]if 'replacement'in control else [])]
    capture=read_capture(root/'guest-output/ws73.pcap',{(o['bus'],o['device'])for o in owners},observe_rx=True,observe_rx_span=True)
    if check_capture_stats((root/'guest-output/capture-stats.txt').read_text())!=capture['packet_count']:
        raise CaptureError('complete retained capture required')
    return dict(version=1,status='OBSERVED_FAILED_ROLE_NOT_QUALIFIED',original_result='FAIL',
        original_phase=phase,original_error=row['error'],load_link_probe=validate_load(row,capture,True,failed=True),
        scope='Actual query attempts/real replies only;not whole-role PASS,application delivery,physical drain,fresh RF or root-cause proof.')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Offline finite load-query evidence,not a device operator')
    parser.add_argument('command',choices=['diagnose-load'])
    parser.add_argument('--directory',required=True)
    parser.add_argument('--phase',required=True,type=int,choices=[0,1])
    args=parser.parse_args()
    print(json.dumps(diagnose_load(args.directory,args.phase),indent=2))
