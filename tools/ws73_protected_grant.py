# SPDX-License-Identifier: GPL-2.0-only
"""VM-only protected-fd prelude over existing typed mechanism orchestration.

No Host, crypto, relay encoder or synthetic controller result. The existing
Grant/File/Down/deadline gates own the subsequent business and cleanup.
"""
import errno
import time
from ws73_management_setup import decode,query,setup
from sparklink.structs import (SleLinkSnapshot,SleControllerSnapshot,
    SleConnectionSecurity,SleSecurityNegotiationSubmit as Submit,
    SleSecurityNegotiationResult as Result)


def execute(outer,save,observers,writers,snapshots,required):
    if type(required) is not int or required not in (1,2):raise ValueError('explicit supported protected requirement')
    context=dict(index=outer['index'],protected_requirement=required,status='STARTING')
    if required==1:context.update(key_agreement=True,unauthenticated_encryption=True)
    else:context['numeric_comparison']='numeric-approve'
    outer.update(channel_security_requirement=required,protected_security=context);save()
    def observe():
        result=[]
        for n,observer in enumerate(observers):
            table=observer.link_snapshot()
            if table.flags!=1 or table.count!=1:raise ValueError('one actual protected lifetime required')
            link=table.links[0]
            result.append(bytes(writers[n].connection_security(snapshots[n].generation,link.lifetime,link.handle)).hex())
        return result
    context['before']=observe();context['before_wall_ns']=time.time_ns();save()
    from ws73_security_capabilities import negotiate
    row,_=negotiate(context,save,observers,writers,snapshots)
    context['after']=observe();context['after_wall_ns']=time.time_ns()
    context.update(status='ACTUAL_POSITIVE_MECHANISM_OBSERVED',end_wall_ns=time.time_ns());save()
    requirement(outer)


def requirement(outer):
    required=outer.get('channel_security_requirement',0);context=outer.get('protected_security')
    if type(required) is not int or required not in (0,1,2):raise ValueError('invalid lifecycle security requirement')
    if not required:
        if context is not None:raise ValueError('protected prelude cannot downgrade to plain lifecycle')
        return 0
    if (not context or context.get('protected_requirement')!=required or context.get('index')!=outer['index']
            or context.get('status')!='ACTUAL_POSITIVE_MECHANISM_OBSERVED'):raise ValueError('complete actual protected mechanism required')
    if required==1:
        if context.get('key_agreement') is not True or context.get('unauthenticated_encryption') is not True or context.get('numeric_comparison'):raise ValueError('noMITM requires real candidate proof and installation')
    elif context.get('numeric_comparison')!='numeric-approve' or context.get('key_agreement') or context.get('unauthenticated_encryption'):raise ValueError('explicit positive numeric mechanism required')
    if len(context['before'])!=2 or len(context['after'])!=2 or len(outer['initial_snapshots'])!=2:raise ValueError('exactly two security observers required')
    row=context['security_capabilities'];i=outer['index']
    if not context['before_wall_ns']<=row['start_wall_ns']<=row['g_start_before_wall_ns']<=row['observed_wall_ns']<=context['after_wall_ns']<=context['end_wall_ns']:raise ValueError('actual prelude chronology required')
    snapshots=[setup(v,n) for n,v in enumerate(outer['initial_snapshots'])]
    for n in (0,1):
        table=decode(SleLinkSnapshot,row['before_links'][n]);link=table.links[0]
        req=decode(Submit,row['requests'][n]);result=decode(Result,row['results'][n]);before=decode(SleConnectionSecurity,context['before'][n]);after=decode(SleConnectionSecurity,context['after'][n])
        if table.flags!=1 or table.count!=1 or table.generation!=snapshots[n].generation:raise ValueError('original known protected lifetime required')
        identity=(table.generation,link.lifetime,link.handle)
        if ((req.generation,req.lifetime,req.handle)!=identity or req.version!=2 or req.profile!=1 or req.flags!=(3 if required==1 else 4)
                or req.request_id!=1 or req.role!=(0 if n==i else 1) or req.role!=link.role or req.action!=(2 if n==i else 1)
                or req.address_type!=link.address_type or bytes(req.address)!=bytes(link.address) or any(req.reserved) or req.timeout_ms!=5000):raise ValueError('exact original typed security request required')
        if not row['request_before_monotonic_ns']+5_000_000_000<=req.deadline_monotonic_ns<=row['request_after_monotonic_ns']+5_000_000_000 or row['observed_monotonic_ns']>=req.deadline_monotonic_ns:raise ValueError('mechanism original deadline required')
        if ((result.generation,result.lifetime,result.handle,result.request_id,result.role,result.version,result.profile,result.state,result.error,result.status,result.flags)!=(*identity,1,req.role,1,1,9 if required==1 else 11,0,0,7 if required==1 else 119)):raise ValueError('real positive original native terminal required')
        from ws73_security_capabilities import OFFER
        offer=bytes([1,0,4,16,0,2,2,2,2,0]) if required==2 else OFFER
        if bytes(result.local_caps)!=offer or bytes(result.peer_caps)!=offer or result.comparison_code:raise ValueError('actual terminal capabilities required')
        for state,level in [(before,0),(after,required)]:
            facts=(0,0,0) if not level else (13,3,16) if level==1 else (15,4,16)
            if ((state.generation,state.lifetime,state.handle)!=identity or state.version!=1 or state.profile!=1
                    or state.level!=level or (state.flags,state.method,state.key_size)!=facts or state.error):raise ValueError('current mechanism query must match lifetime and grade')
        if before.security_epoch!=1 or after.security_epoch!=(2 if n==i else 3):raise ValueError('fresh per-role observed receipt epoch required')
        ready=decode(SleControllerSnapshot,row['before_ready'][n])
        if ready.flags!=1 or ready.generation!=identity[0]:raise ValueError('same Ready registration required')
        query(row['management_before'][n],identity[0],1)
        expected={'generation':errno.ENODEV,'lifetime':errno.ESTALE,'address':errno.ESTALE,'role':errno.ESTALE,'profile':errno.EOPNOTSUPP,'flags':errno.EINVAL,'reserved':errno.EINVAL,'nonowner_submit':errno.EPERM,'nonowner_result':errno.EPERM,'same_lifetime_restart':errno.EBUSY,'version':errno.EOPNOTSUPP,'deadline_expired':errno.ETIMEDOUT,'deadline_future':errno.EINVAL}
        negatives=[v for v in row['negative'] if v['index']==n]
        if len(negatives)!=len(expected) or {v['kind']:v['errno'] for v in negatives}!=expected:raise ValueError('all original native authority and identity refusals required')
    passive=decode(Submit,row['requests'][1-i]);armed=decode(Result,row['t_armed'])
    if ((armed.version,armed.profile,armed.generation,armed.lifetime,armed.handle,armed.request_id,armed.role,armed.state,armed.status,armed.flags,armed.error)!=(1,1,passive.generation,passive.lifetime,passive.handle,1,1,1,0,0,0)
            or bytes(armed.local_caps)!=offer or any(armed.peer_caps) or armed.comparison_code):raise ValueError('passive approval cannot synthesize physical success')
    ordinary=row['ordinary_denial']
    if ordinary['credentials']['uids']!=[1000]*4 or any(int(v,16) for v in ordinary['credentials']['caps'].values()) or ordinary['submit_errno']!=errno.EPERM or ordinary['result_errno']!=errno.EPERM:raise ValueError('ordinary inherited management fd is not security author')
    if required==2:
        from ws73_security_numeric import verify_exchange
        verify_exchange(context)
    return required


def corroborate(outer,capture):
    required=requirement(outer)
    if not required:raise ValueError('protected corroboration requires nonzero requirement')
    context=dict(outer['protected_security'],channel_grant=outer['channel_grant'],usb=outer['usb'])
    for b in outer['channel_grant']['business']:
        if b['start_wall_ns']<context['end_wall_ns']:raise ValueError('protected business must follow actual mechanism query')
    from ws73_key_agreement import corroborate as exchange_wire
    proof=exchange_wire(context,capture,prefix_only=True)
    return dict(status='ACTUAL_PROTECTED_PRELUDE_AND_LIFECYCLE_SCOPE',requirement=required,wire=proof,
                scope='Explicit privileged mechanism approval followed by existing ordinary protected fd lifecycle;not daemon Agent/human identity/Bond/RF attestation/natural recovery')
