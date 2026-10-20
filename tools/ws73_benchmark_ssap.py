# SPDX-License-Identifier: GPL-2.0-only
"""One explicit concurrent correctness profile in the existing VM supervisor.

All SDK operations, Engine behavior, application loops and USB decoding are
reused. This module only selects the finite workload and checks interleaving.
"""
from pathlib import Path
import time
from ws73_capture import CaptureError

FIELD='benchmark_ssap_request'
SOURCE='benchmark_ssap_source'
TOKEN='ws73.benchmark_ssap=owned'
VERIFIERS=('ws73_benchmark_ssap.py','ws73_application_client.py','ws73_ssap_value.py',
           'ws73_ssap_discovery.py','ws73_ssap_owned.py')
RUNTIME=('/bin/ws73-application-client-c','/usr/share/sparklink/tools/ws73-application-client.py',
         '/usr/lib/libsparklink.so.0',*('/usr/share/sparklink/python/sparklink/'+n+'.py'for n in
         ('client','ssap','local_services','service_authorization','_library','_validation')))


def profile():
    return dict(version=1,kind='owned-sdk-read-write',rounds=4,value_bytes=32)


def selected(row):
    if type(row)is not dict:raise CaptureError('typed concurrent SSAP record required')
    if FIELD not in row:return None
    value=row[FIELD]
    if (type(value)is not dict or value!=profile()or type(value.get('version'))is not int
        or any(type(value.get(k))is not int for k in ('rounds','value_bytes'))):
        raise CaptureError('exact explicit concurrent Owned SSAP profile1 required')
    return value


def workload(config,channel):
    from ws73_socket_benchmark import configuration
    if (config!=configuration('window',8,count=128,size=2042)or type(channel)is not dict
        or type(channel.get('version'))is not int or channel['version']!=1 or channel.get('kind')!='dynamic_basic'
        or channel.get('ports')!=[24576,24577]or channel.get('aid')!=29441):
        raise CaptureError('concurrent SSAP requires the fixed128x2042/window8 dynamic route')


def requested(args):
    enabled=getattr(args,'channel_benchmark_ssap_owned',False)
    if type(enabled)is not bool:raise CaptureError('typed concurrent SSAP selector required')
    if not enabled:return None
    from ws73_socket_benchmark import requested_configuration,requested_channel
    workload(requested_configuration(args),requested_channel(args))
    return profile()


def boot(value):
    return [TOKEN]if value is not None else[]


def from_boot(words):
    values=[w for w in words if w.startswith('ws73.benchmark_ssap=')]
    if not values:return None
    if (values!=[TOKEN]or words.count('ws73.socket_benchmark_apps=1')!=1
        or words.count('ws73.benchmark_mode=window')!=1):raise CaptureError('one exact enabled concurrent SSAP boot profile required')
    return profile()


def execute(run,row):
    """Called only after the actual benchmark start barrier,with apps live."""
    from ws73_application_role import require_vm,prepare_ssap_commands
    from ws73_application_client import ssap_phase
    require_vm('ws73.socket_benchmark_apps=1')
    if selected(row)!=from_boot(Path('/proc/cmdline').read_text().split())or selected(row)is None:
        raise CaptureError('explicit concurrent SSAP request/boot required')
    workload(row['config'],row['benchmark_channel_request'])
    source=dict(phase=row['phase'],owners=row['owners'],start_wall_ns=time.time_ns(),status='RUNNING')
    row[SOURCE]=source;run.save();prepare_ssap_commands(run,source)
    ssap_phase(run,source,application_uid=1004,vm_token='ws73.socket_benchmark_apps=1')
    source.update(end_wall_ns=time.time_ns(),status='OWNED_SDK_CONCURRENT_EVIDENCE_PENDING');run.save()


def streams(row):
    if selected(row)is None:
        if SOURCE in row:raise CaptureError('unrequested SSAP source cannot change benchmark scope')
        return []
    source=row[SOURCE]
    if (source['phase']!=row['phase']or source['owners']!=row['owners']
        or source['status']!='OWNED_SDK_CONCURRENT_EVIDENCE_PENDING'
        or not row['start_wall_ns']<=source['start_wall_ns']<=source['end_wall_ns']<=row['end_wall_ns']
        or len(source.get('ssap_language_clients',[]))!=24):
        raise CaptureError('complete original same-lifetime concurrent SSAP source required')
    from ws73_application_client import verify_owned_publishers,ssap_receipt
    owners=verify_owned_publishers(source)
    for app in source['ssap_language_clients']:ssap_receipt(app,source['owners'][app['position']],expected_uid=1004)
    return [*owners,*source['ssap_language_clients']]


def packet_times(packet):
    if type(packet)is not dict:raise CaptureError('actual decoded USB packet required')
    fragments=packet.get('fragments',[packet])
    stamps=[p['wall_ns']for p in fragments]
    if not stamps or any(type(v)is not int or v<=0 for v in stamps):raise CaptureError('original USB fragment timestamps required')
    return min(stamps),max(stamps)


def progress(channel,service):
    """Only same-guest USB wall time,not application Instant or host clocks."""
    if len(channel['legs'])!=256 or len(service['values'])!=8:raise CaptureError('complete concurrent business matrix required')
    legs=[leg for value in service['values']for leg in value['wire']]
    if len(legs)!=48:raise CaptureError('all SSAP read/write/read USB legs required')
    if (any(bytes.fromhex(leg['tx']['data'])[:1]==b'\x0a'for leg in channel['legs'])
        or any(bytes.fromhex(leg['tx']['data'])[:2]!=b'\x0a\0'for leg in legs)):
        raise CaptureError('distinct actual dynamic channel and SSAP SMTC required')
    start=min(packet_times(p['tx'])[0]for p in legs);end=max(packet_times(p['rx'])[1]for p in legs)
    result=dict(SSAP_start_wall_ns=start,SSAP_end_wall_ns=end,before=[],during=[],after=[],clock='same-guest USB wall_ns;no application/cross-clock subtraction')
    if not start<end:raise CaptureError('actual SSAP wire window required')
    for sequence in range(128):
        pair=channel['legs'][sequence*2:sequence*2+2]
        times=[packet_times(leg[side])for leg in pair for side in ('tx','rx')]
        begin=min(t[0]for t in times);finish=max(t[1]for t in times)
        if finish<start:result['before'].append(sequence)
        if start<begin<=finish<end:result['during'].append(sequence)
        if end<begin:result['after'].append(sequence)
    if any(not result[k]for k in ('before','during','after')):
        raise CaptureError('actual complete channel replies before,during AND after SSAP wire work required')
    result.update(full_fairness_qualified=False,performance_qualified=False)
    return result


def corroborate(rows,capture,phases):
    from ws73_application_client import corroborate_ssap
    if len(rows)!=2 or len(phases)!=2 or any(selected(r)!=profile()for r in rows):raise CaptureError('two original concurrent SSAP phases required')
    for row in rows:streams(row)
    service=corroborate_ssap([r[SOURCE]for r in rows],capture)
    for phase,ssap in zip(phases,service['proofs'],strict=True):phase['ssap_concurrent_progress']=progress(phase,ssap)
    return service


def valid_summary(proof):
    try:
        if selected(proof)!=profile():return False
        service=proof['ssap'];phases=proof['proofs']
        if (service['status']!='C_PYTHON_SSAP_VALUE_USB_CORROBORATED'or len(service['proofs'])!=2 or len(phases)!=2
            or any(type(service[k])is not int or service[k]!=v for k,v in dict(operations=16,api_calls=48,authorization_requests=80).items())):return False
        from ws73_application_client import ssap_receipt
        from ws73_ssap_value import valid_wire
        for phase,ssap in zip(phases,service['proofs'],strict=True):
            if (ssap['phase']!=phase['phase']or len(ssap['applications'])!=24 or len(ssap['publishers'])!=2
                or ssap['authorization_requests']!=40 or phase['ssap_concurrent_progress']!=progress(phase,ssap)):
                return False
            for app in ssap['applications']:ssap_receipt(app,phase['owners'][app['position']],expected_uid=1004)
            if any(not valid_wire(leg)for value in ssap['values']for leg in value['wire']):return False
        return True
    except(KeyError,ValueError,TypeError,IndexError,AttributeError):return False
