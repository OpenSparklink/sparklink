"""Real hierarchical/UUID discovery, never source a client handle from staging."""
import re
from ws73_capture import CaptureError


def execute(run,row,command,local):
    row['ssap_discovery_required']=True;row['ssap_discoveries']=[]
    for sender,target in [(0,1),(1,0)]:
        source=row['owners'][sender];prop=local[target]
        for mode,args in [('hierarchy',[]),('service',['service',prop['service_uuid']]),('property',['property',prop['property_uuid']]),('structure',['structure',prop['service_uuid']])]:
            receipt=command(source,['ssap-discover',source['object']['path'],*args])
            row['ssap_discoveries'].append(dict(sender=sender,target=target,mode=mode,receipt=receipt));run.save()
            if mode=='hierarchy':
                found=re.findall(r'^SsapRemoteEntry: category=10 handle=(\d+) end=\d+ uuid='+prop['property_uuid']+r' operations=5 descriptors= members=0$',receipt['stdout'],re.M)
                if len(found)!=1 or int(found[0])!=prop['handle']:raise CaptureError('client must obtain property handle from actual peer discovery')
                prop['discovered_handle']=int(found[0])


def corroborate(row,matched):
    owners=row['owners'];registrations=row.get('ssap_local_registrations',[]);rows=row.get('ssap_discoveries',[])
    if len(registrations)!=2 or len(rows)!=8:raise CaptureError('both directions hierarchy and all three UUID discovery modes required')
    keys=set();credit={0:0,1:0};proof=[]
    for item in rows:
        sender,target=item['sender'],item['target'];mode=item['mode'];key=(sender,mode)
        if sender not in (0,1) or target!=1-sender or mode not in ['hierarchy','service','property','structure'] or key in keys:raise CaptureError('independent discovery modes required')
        keys.add(key);local=registrations[target];receipt=item['receipt'];source=owners[sender];destination=owners[target]
        start=local['start'];handle=local['handle'];suuid=bytes.fromhex(local['service_uuid']);puuid=bytes.fromhex(local['property_uuid'])
        if start<16 or handle!=start+1 or len(suuid)!=16 or len(puuid)!=16:raise CaptureError('actual custom service/handle namespace required')
        pattern=r'^SsapRemoteEntry: category=(\d+) handle=(\d+) end=(\d+) uuid=([0-9a-f]+) operations=(\d+) descriptors=([0-9a-f]*) members=(\d+)$'
        entries=[(int(a),int(b),int(c),d,int(e),f,int(g)) for a,b,c,d,e,f,g in re.findall(pattern,receipt['stdout'],re.M)]
        service=(8,start,handle,suuid.hex(),0,'',2);property_entry=(10,handle,handle,puuid.hex(),5,'',0)
        expected={'hierarchy':[service,property_entry],'service':[service],'property':[property_entry],'structure':[(8,start,0,suuid.hex(),0,'',0),property_entry]}[mode]
        if receipt['exit'] or entries!=expected:raise CaptureError('actual peer metadata differs from opposite local database')
        summary=rf'^SsapRemoteDiscovery: path={re.escape(source["object"]["path"])} kind=(\d+) entries=(\d+) requests=([0-9a-f|]+) responses=([0-9a-f|]+)$'
        found=re.findall(summary,receipt['stdout'],re.M)
        if len(found)!=1:raise CaptureError('one original discovery trace required')
        kind,size,queries,responses=found[0];queries=list(map(bytes.fromhex,queries.split('|')));responses=list(map(bytes.fromhex,responses.split('|')))
        primary=b'\x05\x0b\x81'+start.to_bytes(2,'little')+handle.to_bytes(2,'little')+suuid+b'\x02'
        property_response=b'\x05\x0b\x81'+handle.to_bytes(2,'little')+puuid+b'\x05\0\0\0\0'
        next_handle=(handle+1).to_bytes(2,'little')
        if mode=='hierarchy':
            eq=[b'\x04\x11\x01\0\xff\xff',b'\x04\x11'+next_handle+b'\xff\xff',b'\x04\x13'+start.to_bytes(2,'little')+handle.to_bytes(2,'little')]
            er=[primary,b'\x01\0\x04'+next_handle+b'\x0b',property_response];ek=1
        else:
            control={'service':17,'property':19,'structure':16}[mode];uuid=puuid if mode=='property' else suuid
            eq=[bytes([6,control,1,0,255,255])+uuid,bytes([6,control])+next_handle+b'\xff\xff'+uuid]
            full=b'\x07\x0b'+start.to_bytes(2,'little')+b'\x08'+suuid+b'\0'+handle.to_bytes(2,'little')+b'\x0a'+puuid+b'\x05\0\0\0\0'
            er=[(bytes([7])+primary[1:] if mode=='service' else bytes([7])+property_response[1:] if mode=='property' else full),b'\x01\0\x06'+next_handle+b'\x0b'];ek=control&7
        if int(kind)!=ek or int(size)!=len(expected) or queries!=eq or responses!=er:raise CaptureError('exact request schema/page/terminal error required')
        wire=[]
        for req,rsp in zip(queries,responses):
            for a,b,payload in [(source,destination,req),(destination,source,rsp)]:
                frame=b'\x0a\0'+len(payload).to_bytes(2,'little')+payload
                wire.append(dict(tx=matched(a,'out',frame,receipt),rx=matched(b,'in',frame,receipt)));credit[0 if a==owners[0] else 1]+=1
        proof.append(dict(sender=sender,target=target,mode=mode,entries=expected,wire=wire,receipt=receipt))
    return proof,credit
