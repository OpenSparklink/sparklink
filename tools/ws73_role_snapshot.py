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


def helper_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def requested(row):
    version=row.get('ssap_subscription_snapshot_contract_version')
    if version is not None and(type(version)is not int or version!=VERSION):
        raise CaptureError('explicit snapshot contract1 required')
    return version is not None


def remap_outputs(value,source,destination):
    """Only structured file references change;raw process strings stay exact."""
    if isinstance(value,list):
        for item in value:remap_outputs(item,source,destination)
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
            else:remap_outputs(item,source,destination)


def inventory(root):
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
        if len(result)>=FILES or info.st_size>4*1024*1024 or total>LIMIT:raise CaptureError('finite closed snapshot budget exceeded')
        before=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
        with path.open('rb')as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        after=path.stat()
        if before!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise CaptureError('snapshot changed during hash')
        result[path.relative_to(root).as_posix()]=dict(bytes=info.st_size,sha256=sha)
    if not result:raise CaptureError('nonempty closed snapshot required')
    return result


def publish(source,destination,*,phase,success):
    """Caller has joined fixed children/closed files. No replacement/retry."""
    source=Path(source);destination=Path(destination)
    if type(phase)is not int or phase not in(0,1)or type(success)is not bool:raise CaptureError('fixed completed phase required')
    if destination.exists()or destination.is_symlink():raise CaptureError('never replace original evidence')
    files=inventory(source)
    if NAME in [p.name for p in source.iterdir()]:raise CaptureError('producer cannot predeclare snapshot')
    staging=destination.with_name('.'+destination.name+'.staging')
    # An interrupted staging directory is diagnostic data,never a completed
    # phase;do not remove it or reuse its old success state.
    shutil.copytree(source,staging,symlinks=True)
    if inventory(source)!=files or inventory(staging)!=files:raise CaptureError('closed source/copy mismatch')
    manifest=dict(version=VERSION,status='CLOSED_PHASE_BYTES_EXPORTED',phase=phase,success=success,helper_sha256=helper_hash(),
        source_root=str(source),artifact_root='/evidence/subscription-role/phase-'+str(phase),
        files=files,bytes=sum(v['bytes']for v in files.values()),budget_bytes=LIMIT,max_files=FILES)
    (staging/NAME).write_text(json.dumps(manifest,indent=2)+'\n')
    if inventory(staging)!=files:raise CaptureError('export changed before commit')
    staging.rename(destination)
    return manifest


def verify(destination,*,phase,runtime_root=None,expected_helper=None):
    destination=Path(destination);path=destination/NAME
    if path.is_symlink()or not path.is_file()or not 0<path.stat().st_size<65536:raise CaptureError('closed phase manifest missing/budget')
    proof=json.loads(path.read_text())
    if (set(proof)!={'version','status','phase','success','source_root','artifact_root','files','bytes','budget_bytes','max_files','helper_sha256'}
            or type(proof['version'])is not int or proof['version']!=VERSION
            or type(proof['phase'])is not int or proof['phase']!=phase or proof['success']is not True
            or proof['status']!='CLOSED_PHASE_BYTES_EXPORTED'
            or proof['helper_sha256']!=(expected_helper or helper_hash())
            or proof['source_root']!=str(runtime_root or Path('/run/ws73-subscription-role')/('phase-'+str(phase)))
            or proof['artifact_root']!='/evidence/subscription-role/phase-'+str(phase)
            or proof['budget_bytes']!=LIMIT or proof['max_files']!=FILES
            or proof['files']!=inventory(destination)
            or type(proof['bytes'])is not int or proof['bytes']!=sum(v['bytes']for v in proof['files'].values())):
        raise CaptureError('complete original phase snapshot required')
    return proof


@contextmanager
def local_root():
    from ws73_application_role import require_vm
    require_vm('ws73.ssap_subscription=1')
    if Path('/proc/cmdline').read_text().split().count(TOKEN)!=1:raise CaptureError('explicit VM snapshot boot required')
    root=Path('/run/ws73-subscription-role');root.mkdir(mode=0o755)
    mounted=False
    try:
        subprocess.run(['/bin/busybox','mount','-t','tmpfs','-o','size=32M,mode=0755,nosuid,nodev,noexec','slk-role-evidence',str(root)],check=True)
        mounted=True
        if not any(row.split()[4]==str(root)and' - tmpfs 'in row for row in Path('/proc/self/mountinfo').read_text().splitlines()):
            raise CaptureError('actual local tmpfs required;no fallback')
        yield root
    finally:
        if mounted:subprocess.run(['/bin/busybox','umount',str(root)],check=True)
        root.rmdir()
