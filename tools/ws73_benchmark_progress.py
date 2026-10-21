# SPDX-License-Identifier: GPL-2.0-only
"""Original failed window/peer progress only, never a successful load verdict.

Reuse the existing frame decoder and strict ACB reassembler. This deliberately
supports a closed socket-fault window/peer slice without per-message rejection,
timeout or corruption; other failure shapes are refused, not zero-filled.
"""
import hashlib
from pathlib import Path

from ws73_benchmark import (GRACE_NS, INCOMING_FIELDS, OUTGOING_FIELDS, PACKET_FAILURES, REQUEST_NS,
                            RUN_NS, channel_requests, exact_counts, frame, integer,
                            ordered, read_report, require, resource_check)
from ws73_capture import CaptureError, reassemble_acb_retired


def read_failed_reports(directory, phase, verified_snapshot):
    """Bind decoded bytes to the already verified original failed export.

    This does not verify the snapshot itself; the existing failed-phase guard
    must do that first. Retained exports are not checked as live uid1004 files.
    """
    require(type(phase)is int and phase in(0,1),'original failed phase')
    reports,records=[],[]
    for i in(0,1):
        name=f'reports/benchmark-{phase}-{i}.json'
        report,record=read_report(Path(directory)/name)
        require({k:record[k]for k in('bytes','sha256')}==verified_snapshot['files'].get(name),
                'read report bytes must match original closed snapshot')
        reports.append(report);records.append(record)
    return reports,records


def application_prefixes(reports, config):
    require(type(reports) is list and len(reports) == 2, 'two original failed reports')
    require(set(config)=={'mode','count','bytes','window','interval_us'}
            and config.get('mode') == 'window' and integer(config.get('count'),1,10000)
            and integer(config.get('bytes'),29,2042) and integer(config.get('window'),1,min(config['count'],256))
            and type(config.get('interval_us')) is int and config['interval_us'] == 0, 'bounded original window workload')
    configs=[r['config']for r in reports]
    require(configs == [config,config | dict(mode='peer')], 'original window/peer order and complete offered load')
    requests=channel_requests(reports,configs)
    require(requests is not None, 'explicit dynamic request required for this failed slice')
    catalog=[];received=[];validated=[];outstanding=[];summaries=[]
    for endpoint,(report,c)in enumerate(zip(reports,configs)):
        require(type(report.get('schema_version'))is int and report['schema_version']==2
                and report.get('status')=='INCOMPLETE' and report.get('correctness')is False
                and report.get('performance_qualified')is False and 'test_fixture'not in report,
                'original incomplete reports only')
        require(report.get('clock')=='process-local-Rust-Instant-relative-nanoseconds'
                and report.get('window_domain')=='application-awaiting-validated-reply-not-protocol-credit',
                'separate original application clock/window')
        for k,v in [('request_deadline_ns',REQUEST_NS),('late_observation_grace_ns',GRACE_NS),('maximum_run_ns',RUN_NS)]:
            require(type(report.get(k))is int and report[k]==v,'unchanged original budget '+k)
        o=report['observation'];end=report['finalization']
        require(type(o.get('error'))is str and bool(o['error']) and integer(o.get('elapsed_ns'),1,RUN_NS)
                and integer(o.get('active_elapsed_ns'),1,o['elapsed_ns']), 'actual bounded failed observation')
        require(end.get('completed')is False and type(end.get('error'))is str and bool(end['error'])
                and type(end.get('budget_ns'))is int and end['budget_ns']==30_000_000_000
                and integer(end.get('elapsed_ns'),0,end['budget_ns']), 'original failed finalization,not success')
        identity=report['channel_identity']
        require(all(integer(identity.get(k),lo,hi)for k,lo,hi in [('controller',0,15),('generation',1,2**64-1),
                ('lifetime',1,2**64-1),('handle',0,4095),('mtu',c['bytes'],2042),('mps',c['bytes']+5,2047),
                ('local_tcid',128,223),('remote_tcid',128,223)])
                and all(type(identity.get(k))is int and identity[k]==v for k,v in [('mode',0),('pi',241),('directions',3)]),
                'actual original basic channel identity and budgets')
        require(identity['mtu']+5<=identity['mps'] and identity['mtu']<=requests[endpoint]['mtu']
                and identity['mps']<=requests[endpoint]['mps'],'actual capabilities within original request')
        resource_check(report['process_resources'])
        rows=report['outgoing'] if endpoint==0 else report['incoming']
        require(type(rows)is list and (len(rows)==c['count']if endpoint==0 else 0<=len(rows)<=c['count'])
                and report['incoming'if endpoint==0 else'outgoing']==[], 'all scheduled and observed records retained')
        admitted=0;replies=0;previous=0;unused=False;nonces=set();sequences=set()
        for index,row in enumerate(rows):
            require(type(row)is dict and set(row)==(OUTGOING_FIELDS if endpoint==0 else INCOMING_FIELDS)
                    and type(row.get('index'))is int and row['index']==index,'all original typed indices')
            require(row['errno']is None and row['timed_out']is False and integer(row['send_attempts'])
                    and integer(row['would_block']), 'this slice has no per-message errno/timeout;others unsupported')
            if endpoint==0 and row['admitted_ns']is None:
                require(row['local_budget_rejected']is False and row['late']is False
                        and row['send_attempts']==row['would_block']==0 and all(row[k]is None for k in
                        ('planned_ns','dispatch_ns','first_syscall_ns','syscall_ns','deadline_ns','read_ns','validated_ns'))
                        and row['frame_hex']==''
                        and type(row['reply_count'])is int and row['reply_count']==0,'whole untouched scheduled tail')
                unused=True;continue
            payload,nonce,sequence=frame(row['frame_hex'],c['bytes'],endpoint)
            require(nonce not in nonces and sequence not in sequences,'unique original frame identities')
            nonces.add(nonce);sequences.add(sequence)
            if endpoint==0:
                catalog.append(payload)
                require(row['local_budget_rejected']is False and row['late']is False,'no hidden rejection/late')
                require(not unused and row['send_attempts']==row['would_block']+1,'admitted prefix and exact attempts')
                ordered(row,['planned_ns','dispatch_ns','first_syscall_ns','syscall_ns','admitted_ns'],o['active_elapsed_ns'])
                require(row['planned_ns']>=previous and integer(row['deadline_ns'])
                        and row['deadline_ns']==row['planned_ns']+REQUEST_NS,'original source deadline')
                previous=row['planned_ns'];admitted+=1
                if row['validated_ns']is None:
                    require(row['read_ns']is None and type(row['reply_count'])is int and row['reply_count']==0,'unanswered is not a reply')
                    outstanding.append(index)
                else:
                    ordered(row,['admitted_ns','read_ns','validated_ns'],o['active_elapsed_ns'])
                    require(row['validated_ns']<row['deadline_ns'] and type(row['reply_count'])is int and row['reply_count']==1,
                            'actual one timely validated reply')
                    replies+=1;validated.append(index)
            else:
                require(row['send_attempts']==row['would_block']+1,'actual peer reply admission')
                ordered(row,['read_ns','validated_ns','reply_syscall_ns','reply_admitted_ns'],o['active_elapsed_ns'])
                require(row['read_ns']>=previous and integer(row['deadline_ns'])and row['deadline_ns']==row['read_ns']+REQUEST_NS
                        and row['reply_admitted_ns']<row['deadline_ns'],'original peer reply deadline')
                previous=row['read_ns'];received.append(payload)
        n=c['count']if endpoint==0 else 0;nin=len(rows)if endpoint else 0
        summary=dict(scheduled=n,dispatched=admitted,unattempted=n-admitted,admitted=admitted,validated_replies=replies,
            timed_out=0,late=0,local_budget_rejected=0,kernel_rejected=0,missing_admitted_replies=admitted-replies,
            expired_before_admission=0,admitted_reply_timeouts=0,successful_timely_replies=replies,
            peer_reply_deadline_exceeded=0,peer_validated_requests=nin,peer_reply_admissions=nin,peer_validated_application_bytes=nin*c['bytes'])
        exact_counts(report['summary'],summary,'original failed summary')
        counters=report['counters']
        require(set(counters)==set(PACKET_FAILURES+['rx_packets','inflight_peak','reply_queue_peak','poll_calls','iterations'])
                and all(integer(v)for v in counters.values()) and counters['rx_packets']==replies+nin
                and all(counters[k]==0 for k in PACKET_FAILURES),
                'original failed socket slice,no hidden packet corruption or duplicates')
        summaries.append(summary)
    require(reports[0]['channel_identity']['controller']!=reports[1]['channel_identity']['controller']
            and all(reports[0]['channel_identity'][a]==reports[1]['channel_identity'][b]
                for a,b in [('local_tcid','remote_tcid'),('remote_tcid','local_tcid')]),'cross-end ownership')
    require(received==catalog[:len(received)] and len(received)<=summaries[0]['admitted']
            and validated==list(range(len(validated))) and all(i<len(received)for i in validated),
            'actual peer records match source admissions,not clocks')
    return dict(status='FAILED_WINDOW_APPLICATION_PREFIXES_NOT_QUALIFIED',original_result='FAIL',
                summaries=summaries,validated_indices=validated,unanswered_indices=outstanding,
                unattempted_indices=list(range(summaries[0]['admitted'],config['count'])),
                catalog=catalog,performance_qualified=False,original_gate_qualified=False)


def transport_prefixes(capture, reports, application, owners):
    complete,retired=reassemble_acb_retired(capture)
    catalog=application['catalog'];result=[]
    require(len(owners)==len(reports)==2,'two original owners')
    usb=[(e['owner']['bus'],e['owner']['device'])for e in owners]
    require(len(set(usb))==2,'distinct original USB owners')
    for report,entry in zip(reports,owners):
        i=report['channel_identity'];o=entry['owner'];c=entry['object']
        require((i['controller'],i['generation'],i['lifetime'],i['handle'])
                ==(o['index'],o['generation'],c['lifetime'],c['handle']),'original controller/generation/lifetime binding')
    for stream in retired:
        endpoint=next((i for i,identity in enumerate(usb)if identity==(stream['bus'],stream['device'])),None)
        if endpoint is None:raise CaptureError('retired stream outside original endpoints')
        identity=reports[endpoint]['channel_identity'];raw=b''.join(bytes.fromhex(p['data'])for p in stream['fragments'])
        if len(raw)<34 or int.from_bytes(raw[:2],'little')not in (identity['local_tcid'],identity['remote_tcid'])or raw[4]!=241:
            continue
        require(stream['handle']==identity['handle'] and stream['retired_by']['event']in(5,0x1405),
                'original physical disconnection retirement,not a passing complete SDU')
        reply=raw[33]
        require(reply in(0,1)and(endpoint==0)==((stream['direction']=='out')!=bool(reply)),
                'request/reply direction belongs to original endpoint')
        require(int.from_bytes(raw[:2],'little')==identity['remote_tcid'if stream['direction']=='out'else'local_tcid'],
                'actual local/remote TCID direction')
        candidates=[(i,frame)for i,frame in enumerate(catalog)if raw[5:]==(frame[:28]+bytes([reply])+frame[29:])[:len(raw)-5]]
        require(reply in (0,1) and len(candidates)==1,'one actual known random application prefix')
        index,payload=candidates[0];full=raw[:5]+payload[:28]+bytes([reply])+payload[29:]
        require(int.from_bytes(raw[2:4],'little')+4==len(full) and len(raw)<len(full),'genuinely incomplete original PDU')
        opposite=1-endpoint
        peer=[p for p in complete if (p['bus'],p['device'],p['direction'],p['handle'],p['data'])
              ==(*usb[opposite],'out'if stream['direction']=='in'else'in',owners[opposite]['object']['handle'],full.hex())]
        require(len(peer)<=1,'unique opposite complete PDU')
        result.append(dict(endpoint=endpoint,direction=stream['direction'],application_index=index,reply=bool(reply),
            prefix_bytes=len(raw),expected_PDU_bytes=len(full),fragments=len(stream['fragments']),
            first_record=stream['fragments'][0]['record'],last_record=stream['fragments'][-1]['record'],
            prefix_sha256=hashlib.sha256(raw).hexdigest(),retirement_record=stream['retired_by']['record'],
            retirement_event=stream['retired_by']['event'],opposite_complete_records=[p['record']for p in peer],
            application_delivery_qualified=False,hardware_cause_proved=False))
    return dict(status='FAILED_WINDOW_RETIRED_TRANSPORT_PREFIXES_ONLY',retired_streams=len(retired),
                matched_application_prefixes=result,unclassified_retirements=len(retired)-len(result),
                hardware_cause_proved=False,original_gate_qualified=False)


def business_legs(capture, reports, application, owners, timings):
    """Associate actual random payloads and accepted USB records, not queue IDs.

    Unsubmitted software work cannot acquire an application identity here.
    Missing legs stay missing; a retired prefix never becomes a complete SDU.
    """
    complete, retired = reassemble_acb_retired(capture)
    partial = transport_prefixes(capture, reports, application, owners)
    catalog = application['catalog']
    by_payload = {payload: index for index, payload in enumerate(catalog)}
    usb = [(v['owner']['bus'], v['owner']['device']) for v in owners]
    operations = {}
    for operation in timings['operations']:
        records = operation['accepted_usb_records']
        if records:
            require(records[0] not in operations, 'unique original operation USB record')
            operations[records[0]] = operation
    rows, seen = [], set()

    def add(endpoint, direction, index, reply, pieces, whole):
        key = endpoint, direction, index, reply
        require(key not in seen, 'one original business leg')
        seen.add(key)
        identity = reports[endpoint]['channel_identity']
        records = [p['record'] for p in pieces]
        row = dict(endpoint=endpoint, direction=direction, application_index=index, reply=reply,
                   complete_sdu=whole, bytes=sum(len(bytes.fromhex(p['data'])) for p in pieces),
                   fragment_records=records, first_wall_ns=pieces[0]['wall_ns'],
                   last_wall_ns=pieces[-1]['wall_ns'],
                   frame_sha256=hashlib.sha256(catalog[index]).hexdigest(), operation=None)
        if direction == 'out':
            operation = operations.get(records[0])
            require(operation is not None and operation['accepted_usb_records'] == records
                    and (operation['controller'], operation['generation'], operation['lifetime'])
                    == (identity['controller'], identity['generation'], identity['lifetime']),
                    'actual business fragments and original Session operation must agree')
            row['operation'] = {k: operation[k] for k in ('controller','generation','lifetime',
                'epoch','slot','admission_sequence','admission_ns','retirement_ns','deadline_jiffies',
                'dtap_bytes','accepted_fragments','reported_credit_waits')}
        rows.append(row)

    for packet in complete:
        if (packet['bus'], packet['device']) not in usb:
            continue
        endpoint = usb.index((packet['bus'], packet['device']))
        identity = reports[endpoint]['channel_identity']
        raw = bytes.fromhex(packet['data'])
        tcid = identity['remote_tcid' if packet['direction'] == 'out' else 'local_tcid']
        if len(raw) < 5 or int.from_bytes(raw[:2], 'little') != tcid or raw[4] != 241:
            continue
        require(packet['handle'] == identity['handle']
                and int.from_bytes(raw[2:4], 'little') + 4 == len(raw), 'original DTAP/handle')
        reply = raw[33] if len(raw) > 33 else -1
        normalized, _, _ = frame(raw[5:].hex(), reports[endpoint]['config']['bytes'], reply)
        require(reply in (0, 1) and normalized in by_payload
                and (endpoint == 0) == ((packet['direction'] == 'out') != bool(reply)),
                'known actual random payload and direction')
        add(endpoint, packet['direction'], by_payload[normalized], bool(reply), packet['fragments'], True)
    for p in partial['matched_application_prefixes']:
        owner = owners[p['endpoint']]['owner']
        matches = [s for s in retired if (s['bus'],s['device'],s['direction'])
                   == (owner['bus'],owner['device'],p['direction'])
                   and s['fragments'][0]['record'] == p['first_record']
                   and s['fragments'][-1]['record'] == p['last_record']]
        require(len(matches) == 1, 'one original retired prefix stream')
        add(p['endpoint'], p['direction'], p['application_index'], p['reply'], matches[0]['fragments'], False)
    full = {(r['endpoint'],r['direction'],r['application_index'],r['reply']) for r in rows if r['complete_sdu']}
    for index in range(len(reports[1]['incoming'])):
        require((0,'out',index,False) in full and (1,'in',index,False) in full,
                'actual peer-validated request needs both captured complete legs')
    for index in application['validated_indices']:
        require((1,'out',index,True) in full and (0,'in',index,True) in full,
                'actual source-validated reply needs both captured complete legs')
    return rows
