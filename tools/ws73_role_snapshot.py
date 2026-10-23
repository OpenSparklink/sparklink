# SPDX-License-Identifier: GPL-2.0-only
"""Closed phase snapshots for the existing VM role supervisor,not a wire path.

Hot append files stay on guest-local bounded tmpfs. An immutable phase directory
is published only after all known producer processes and file handles close.
No retry conceals filesystem errors;no source stdout/stderr bytes are rewritten.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import shutil
import stat
import subprocess

from ws73_capture import CaptureError

VERSION=1
TOKEN='ws73.subscription_snapshot=1'
LIMIT=16*1024*1024
FILES=64
NAME='snapshot.json'
HELPER='/usr/share/sparklink/tools/ws73_role_snapshot.py'
SUPERVISOR='/usr/share/sparklink/tools/ws73_application_role.py'


def profile(kind,pair=None):
    if pair is not None and(type(pair)is not int or pair not in(0,1)or kind!='subscription'):
        raise CaptureError('fixed subscription pair0/1 only')
    if kind=='subscription':
        suffix=''if pair is None else'-pair-'+str(pair)
        return dict(root='/run/ws73-subscription-role'+suffix,artifact='/evidence/subscription-role'+suffix,token=TOKEN,vm_token='ws73.ssap_subscription=1',limit=LIMIT,file_limit=4*1024*1024,mount='32M')
    if kind=='benchmark':return dict(root='/run/ws73-benchmark-role',artifact='/evidence/benchmark-role',token='ws73.socket_benchmark_apps=1',vm_token='ws73.socket_benchmark_apps=1',limit=512*1024*1024,file_limit=256*1024*1024,mount='768M')
    raise CaptureError('fixed role snapshot profile required')


def helper_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def requested(row):
    version=row.get('ssap_subscription_snapshot_contract_version')
    if version is not None and(type(version)is not int or version!=VERSION):
        raise CaptureError('explicit snapshot contract1 required')
    return version is not None


def remap_outputs(value,source,destination,*,_seen=None):
    """Only structured file references change;raw process strings stay exact."""
    # The existing SSAP value receipts intentionally share the actual child
    # record with their client index. Remap that object once,without treating
    # an arbitrary pre-mapped destination as trusted source input.
    seen=set()if _seen is None else _seen
    if isinstance(value,(list,dict)):
        if id(value)in seen:return
        seen.add(id(value))
    if isinstance(value,list):
        for item in value:remap_outputs(item,source,destination,_seen=seen)
    elif isinstance(value,dict):
        for key,item in value.items():
            if key=='output_files':
                if not isinstance(item,list)or len(item)!=2:raise CaptureError('exact stdout/stderr pair required')
                mapped=[]
                for name in item:
                    path=Path(name);relative=path.relative_to(source)
                    if '..'in relative.parts or path.suffix not in('.stdout','.stderr'):raise CaptureError('fixed local process output required')
                    mapped.append(str(destination/relative))
                value[key]=mapped
            else:remap_outputs(item,source,destination,_seen=seen)


def inventory(root,*,kind='subscription'):
    bounds=profile(kind)
    root=Path(root)
    if root.is_symlink()or not root.is_dir():raise CaptureError('regular snapshot root required')
    result={};total=0;entries=0
    for path in root.rglob('*'):
        entries+=1
        if entries>FILES*2:raise CaptureError('finite snapshot entry budget exceeded')
        info=path.lstat()
        if stat.S_ISDIR(info.st_mode):continue
        if not stat.S_ISREG(info.st_mode)or path.is_symlink()or info.st_nlink!=1:
            raise CaptureError('regular unique snapshot files only')
        if path.name==NAME and path.parent==root:continue
        total+=info.st_size
        if len(result)>=FILES or info.st_size>bounds['file_limit'] or total>bounds['limit']:raise CaptureError('finite closed snapshot budget exceeded')
        before=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
        with path.open('rb')as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        after=path.stat()
        if before!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise CaptureError('snapshot changed during hash')
        result[path.relative_to(root).as_posix()]=dict(bytes=info.st_size,sha256=sha)
    if not result:raise CaptureError('nonempty closed snapshot required')
    return result


def publish(source,destination,*,phase,success,kind='subscription',pair=None):
    """Caller has joined fixed children/closed files. No replacement/retry."""
    bounds=profile(kind,pair)
    source=Path(source);destination=Path(destination)
    if type(phase)is not int or phase not in(0,1)or type(success)is not bool:raise CaptureError('fixed completed phase required')
    if destination.exists()or destination.is_symlink():raise CaptureError('never replace original evidence')
    files=inventory(source,kind=kind)
    if NAME in [p.name for p in source.iterdir()]:raise CaptureError('producer cannot predeclare snapshot')
    staging=destination.with_name('.'+destination.name+'.staging')
    # An interrupted staging directory is diagnostic data,never a completed
    # phase;do not remove it or reuse its old success state.
    shutil.copytree(source,staging,symlinks=True)
    if inventory(source,kind=kind)!=files or inventory(staging,kind=kind)!=files:raise CaptureError('closed source/copy mismatch')
    manifest=dict(version=VERSION,status='CLOSED_PHASE_BYTES_EXPORTED',phase=phase,success=success,helper_sha256=helper_hash(),
        source_root=str(source),artifact_root=bounds['artifact']+'/phase-'+str(phase),
        files=files,bytes=sum(v['bytes']for v in files.values()),budget_bytes=bounds['limit'],max_files=FILES)
    (staging/NAME).write_text(json.dumps(manifest,indent=2)+'\n')
    if inventory(staging,kind=kind)!=files:raise CaptureError('export changed before commit')
    staging.rename(destination)
    return manifest


def _verify_export(destination,*,phase,runtime_root=None,expected_helper=None,kind='subscription',pair=None,success):
    bounds=profile(kind,pair)
    destination=Path(destination);path=destination/NAME
    if path.is_symlink()or not path.is_file()or not 0<path.stat().st_size<65536:raise CaptureError('closed phase manifest missing/budget')
    proof=json.loads(path.read_text())
    if (set(proof)!={'version','status','phase','success','source_root','artifact_root','files','bytes','budget_bytes','max_files','helper_sha256'}
            or type(proof['version'])is not int or proof['version']!=VERSION
            or type(proof['phase'])is not int or proof['phase']!=phase or proof['success']is not success
            or proof['status']!='CLOSED_PHASE_BYTES_EXPORTED'
            or proof['helper_sha256']!=(expected_helper or helper_hash())
            or proof['source_root']!=str(runtime_root or Path(bounds['root'])/('phase-'+str(phase)))
            or proof['artifact_root']!=bounds['artifact']+'/phase-'+str(phase)
            or proof['budget_bytes']!=bounds['limit'] or proof['max_files']!=FILES
            or proof['files']!=inventory(destination,kind=kind)
            or type(proof['bytes'])is not int or proof['bytes']!=sum(v['bytes']for v in proof['files'].values())):
        raise CaptureError('complete original phase snapshot required')
    return proof


def verify(destination,*,phase,runtime_root=None,expected_helper=None,kind='subscription',pair=None):
    """Qualified consumers still require an actual successful phase."""
    return _verify_export(destination,phase=phase,runtime_root=runtime_root,
                          expected_helper=expected_helper,kind=kind,pair=pair,success=True)


def verify_failed(destination,*,phase,runtime_root=None,expected_helper=None,kind='subscription',pair=None):
    """Verify only exported failure bytes; never a successful phase receipt."""
    return _verify_export(destination,phase=phase,runtime_root=runtime_root,
                          expected_helper=expected_helper,kind=kind,pair=pair,success=False)


@contextmanager
def local_root(*,kind='subscription',pair=None):
    bounds=profile(kind,pair)
    from ws73_application_role import require_vm
    require_vm(bounds['vm_token'])
    if pair is not None and Path('/proc/cmdline').read_text().split().count('ws73.parallel_subscription=1')!=1:
        raise CaptureError('explicit four-pair subscription boot required')
    if Path('/proc/cmdline').read_text().split().count(bounds['token'])!=1:raise CaptureError('explicit VM snapshot boot required')
    root=Path(bounds['root']);root.mkdir(mode=0o755)
    mounted=False
    try:
        subprocess.run(['/bin/busybox','mount','-t','tmpfs','-o','size='+bounds['mount']+',mode=0755,nosuid,nodev,noexec','slk-role-evidence',str(root)],check=True)
        mounted=True
        if not any(row.split()[4]==str(root)and' - tmpfs 'in row for row in Path('/proc/self/mountinfo').read_text().splitlines()):
            raise CaptureError('actual local tmpfs required;no fallback')
        yield root
    finally:
        if mounted:subprocess.run(['/bin/busybox','umount',str(root)],check=True)
        root.rmdir()
