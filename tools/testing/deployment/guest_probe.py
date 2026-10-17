#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Destructive disposable-guest deployment gate, without SparkLink hardware.

Only run in an explicitly marked dedicated QEMU/KVM guest. The root data disk
contains exact source.tar, input-manifest.json, a pinned toolchain and public
Cargo registry cache. Never use on a host or a VM containing administrator data.
This does not qualify RF, native permissions, cross-version upgrades or packages.
"""
from pathlib import Path
import argparse
import os
import subprocess
import json
import hashlib
import time
import shlex
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disposable-guest-only', action='store_true', required=True)
    parser.parse_args()
    marker = Path('/etc/slkr6-disposable-guest')
    if os.geteuid() != 0 or not marker.is_file() or marker.read_text() != 'sparklink-clean-deployment-v1\n':
        raise SystemExit('dedicated guest marker and guest root required; no action taken')
    virt = subprocess.run(['systemd-detect-virt', '--vm'], capture_output=True, text=True, check=True).stdout.strip()
    if virt not in ('kvm', 'qemu'):
        raise SystemExit('dedicated QEMU/KVM guest required; no action taken')
    root=Path('/opt/slkr6');out=root/'outputs';out.mkdir(exist_ok=True)
    record={'status':'RUNNING_NOT_QUALIFIED','start_ns':time.time_ns(),'scope':'Clean Debian system bus/service/install and external SDK consumers without SparkLink hardware. Not RF, kernel Grant, cross-version upgrade or Debian package qualification.','gates':[]}
    def save():
     p=out/'result.tmp';p.write_text(json.dumps(record,indent=2)+'\n');p.replace(out/'result.json')
    def run(name,args,env=None,timeout=1200):
     log=out/(name+'.log');start=time.time_ns()
     with log.open('w')as f:
      p=subprocess.run(args,env=env,stdout=f,stderr=subprocess.STDOUT,text=True,timeout=timeout)
     record['gates'].append({'name':name,'command':args,'exit':p.returncode,'start_ns':start,'end_ns':time.time_ns(),'log':log.name,'sha256':hashlib.file_digest(log.open('rb'),'sha256').hexdigest()});save()
     print(f'GATE {name} exit={p.returncode}',flush=True)
     if p.returncode: print(log.read_text()[-10000:],flush=True);p.check_returncode()
     return log.read_text()
    def check(value,label):
     if not value:raise AssertionError(label)
    try:
     save();record['os_release']=Path('/etc/os-release').read_text();record['kernel']=os.uname().release
     record['probe_sha256']=hashlib.file_digest(Path(__file__).open('rb'),'sha256').hexdigest()
     inputs=json.loads((root/'input-manifest.json').read_text());check(inputs['source_archive_sha256']==hashlib.file_digest((root/'source.tar').open('rb'),'sha256').hexdigest(),'input source hash mismatch');record['input_identity']=inputs
     env=os.environ|{'DEBIAN_FRONTEND':'noninteractive'}
     run('apt-update',['apt-get','update'],env)
     run('apt-install',['apt-get','install','-y','--no-install-recommends','build-essential','pkgconf','python3-venv','python3-pip','python3-setuptools','python3-wheel','python3-dbus','debhelper','git','binutils'],env)
     run('package-versions',['dpkg-query','-W','-f=${Package}\t${Version}\n'])
     source=root/'source';source.mkdir();run('source-extract',['tar','-xf',str(root/'source.tar'),'-C',str(source)])
     record['source_archive_sha256']=hashlib.file_digest((root/'source.tar').open('rb'),'sha256').hexdigest()
     env=os.environ|{'PATH':str(root/'toolchain/bin')+':'+os.environ['PATH'],'CARGO_HOME':str(root/'cargo-home'),'CARGO_TARGET_DIR':str(root/'target'),'SPARKLINK_BUILD_JOBS':'8','CARGO_BUILD_JOBS':'8','CARGO_NET_OFFLINE':'true'}
     run('rust-version',[str(root/'toolchain/bin/rustc'),'-vV'],env)
     run('cargo-version',[str(root/'toolchain/bin/cargo'),'-vV'],env)
     run('source-build',['python3',str(source/'tools/build_resources.py'),'--record',str(out/'build-budget.json'),'--',str(root/'toolchain/bin/cargo'),'build','--manifest-path',str(source/'Cargo.toml'),'--locked','--offline','--release','--workspace'],env)
     artifact=root/'target/release'
     record['artifact_sha256']={n:hashlib.file_digest((artifact/n).open('rb'),'sha256').hexdigest()for n in ['slkd','slctl','slktest','slkconfig','slkmon','slkdump','liblibsparklink.so','libslk_native.so']};save()
     # No installer step below touches the host: this process runs only in the disposable guest.
     make=['make','--no-print-directory','-C',str(source),'install-files','PREFIX=/usr','ARTIFACT_DIR='+str(artifact),'INSTALL_GENERATED_DIR='+str(root/'generated')]
     run('install',make,env)
     run('groups',['systemd-sysusers','/usr/lib/sysusers.d/sparklink.conf'])
     run('udev-reload',['udevadm','control','--reload-rules'])
     run('ldconfig',['ldconfig'])
     run('dbus-reload',['systemctl','reload','dbus'])
     run('unit-reload',['systemctl','daemon-reload'])
     run('unit-verify',['systemd-analyze','verify','/usr/lib/systemd/system/sparklink.service'])
     run('service-start',['systemctl','start','sparklink'],timeout=60)
     run('service-active',['systemctl','is-active','sparklink'])
     run('config',['/usr/sbin/slkd','--config','/etc/sparklink/main.conf','--check-config'])
     for label,group in [('observer',None),('application','sparklink-apps'),('publisher','sparklink-services'),('manager','sparklink')]:
      args=['useradd','--create-home','--shell','/bin/sh']
      if group:args+=['--groups',group]
      run('user-'+label,args+['slkr6-'+label])
     policy=out/'policy.py';policy.write_text('''import dbus,sys,json,os
    mode=sys.argv[1];bus=dbus.SystemBus();dest='org.sparklink';rows=[]
    def call(path,iface,member,signature='',args=()):
     try:return ('OK',bus.call_blocking(dest,path,iface,member,signature,args,timeout=5))
     except dbus.DBusException as e:return(e.get_dbus_name(),str(e))
    def expected(label,path,iface,member,wanted):
     status,value=call(path,iface,member);assert status==wanted,(mode,label,status,str(value));rows.append([label,status])
    status,values=call('/org/sparklink','org.sparklink.Manager','ListAdapters');assert status=='OK' and len(values)==0,(status,str(values))
    try:bus.request_name(dest,4)
    except dbus.DBusException as e:assert e.get_dbus_name()=='org.freedesktop.DBus.Error.AccessDenied';rows.append(['own-service',e.get_dbus_name()])
    else:raise AssertionError('nonroot took service name')
    unknown='org.freedesktop.DBus.Error.UnknownObject';denied='org.freedesktop.DBus.Error.AccessDenied'
    expected('channel','/org/sparklink/missing','org.sparklink.Connection','OpenChannel',unknown if mode in ('application','manager')else denied)
    expected('owned-registration','/org/sparklink/missing','org.sparklink.ServiceManager','RegisterOwnedLocalService',unknown if mode in ('publisher','manager')else denied)
    expected('controller-stop','/org/sparklink/missing','org.sparklink.Adapter','SubmitStopScanning',unknown if mode=='manager'else denied)
    expected('unknown-method','/org/sparklink/missing','org.sparklink.Future','Unapproved',unknown if mode=='manager'else denied)
    assert os.getuid()!=0 and all(int(x,16)==0 for line in open('/proc/self/status')if line.startswith(('CapEff:','CapPrm:','CapAmb:'))for x in line.split()[1:])
    print(json.dumps(dict(mode=mode,uid=os.getuid(),groups=os.getgroups(),adapters=0,checks=rows)))
    ''');policy.chmod(0o644);out.chmod(0o755)
     for label in ['observer','application','publisher','manager']:run('system-bus-'+label,['runuser','-u','slkr6-'+label,'--','python3',str(policy),label])
     # External consumers compile and load only installed files via pkg-config/ldconfig.
     for kind in ['sparklink','sparklink-native']:
      flags=shlex.split(run('pkgconfig-'+kind,['pkg-config','--cflags','--libs',kind]));c=out/(kind+'.c');exe=c.with_suffix('')
      if kind=='sparklink':c.write_text('#include <sparklink.h>\n#include <errno.h>\n#include <string.h>\nint main(void){struct SleChannelInfo v,b;memset(&v,0xa5,sizeof v);b=v;if(slk_ssap_access_error(0,0,0)!=0 || slk_channel_info(-1,&v)!=-EBADF || memcmp(&v,&b,sizeof v))return 1;return 0;}\n')
      else:c.write_text('#include <sparklink_native.h>\n#include <errno.h>\n#include <string.h>\nint main(void){SlkAdapter *a=slk_adapter_open("/dev/null");if(!a)return 1;SleControllerSnapshot v,b;memset(&v,0xa5,sizeof v);b=v;int e=slk_controller_snapshot(a,1,&v);slk_adapter_free(a);return e!=-ENOTTY || memcmp(&v,&b,sizeof v);}\n')
      run('compile-'+kind,['cc','-std=c11','-Wall','-Wextra','-Werror',str(c),*flags,'-o',str(exe)])
      run('external-'+kind,['runuser','-u','slkr6-observer','--',str(exe)])
      dyn=run('needed-'+kind,['readelf','--dynamic',str(exe)]);check(('libsparklink.so.0'if kind=='sparklink'else'libslk_native.so.0')in dyn,'SONAME consumer missing')
     # Python runtime must not depend on development linker symlinks.
     Path('/usr/lib/libsparklink.so').unlink();Path('/usr/lib/libslk_native.so').unlink()
     pyroot=source/'bindings/python';run('python-wheel',['python3','-m','pip','wheel','--no-index','--no-deps','--no-build-isolation','-w',str(out/'wheel'),str(pyroot)])
     run('python-venv',['runuser','-u','slkr6-observer','--','python3','-m','venv','/home/slkr6-observer/venv'])
     wheel=list((out/'wheel').glob('*.whl'));check(len(wheel)==1,'one wheel required')
     run('python-install',['runuser','-u','slkr6-observer','--','/home/slkr6-observer/venv/bin/pip','install','--no-index',str(wheel[0])])
     py=out/'external.py';py.write_text('''import sparklink,errno,os
    assert '/home/slkr6-observer/venv/' in sparklink.__file__
    assert not hasattr(sparklink,'Adapter') and not hasattr(sparklink,'NativeAdapter')
    assert sparklink.SsapAccess(0).error(0)==0
    try:sparklink.channel_info(-1)
    except OSError as e:assert e.errno==errno.EBADF
    else:raise AssertionError('bad fd succeeded')
    from sparklink.native import registration_snapshot
    try:registration_snapshot(0,dev_path='/dev/null')
    except OSError as e:assert e.errno==errno.ENOTTY
    else:raise AssertionError('non SparkLink device succeeded')
    print('INSTALLED_VENV_APPLICATION_AND_EXPLICIT_NATIVE_NEGATIVES_PASS')
    ''')
     run('external-python',['runuser','-u','slkr6-observer','--','/home/slkr6-observer/venv/bin/python',str(py)])
     # Reinstall is not cross-version upgrade. Preserve explicit administrator state.
     config=Path('/etc/sparklink/main.conf');config.write_text(config.read_text()+'\n# R6 administrator marker\n');config.chmod(0o600);config.parent.chmod(0o700);state=Path('/var/lib/sparklink');(state/'retain').write_text('administrator state\n');before=hashlib.file_digest(config.open('rb'),'sha256').hexdigest()
     run('reinstall',make,env);check(hashlib.file_digest(config.open('rb'),'sha256').hexdigest()==before and config.stat().st_mode&0o777==0o600 and config.parent.stat().st_mode&0o777==0o700,'config changed')
     run('service-restart',['systemctl','restart','sparklink'],timeout=60)
     run('service-active-after-reinstall',['systemctl','is-active','sparklink'])
     run('service-stop',['systemctl','stop','sparklink'],timeout=60)
     foreign=Path('/usr/lib/libsparklink.so.99');foreign.write_text('unrelated version\n')
     run('uninstall',['make','--no-print-directory','-C',str(source),'uninstall','PREFIX=/usr'],env)
     check(not Path('/usr/sbin/slkd').exists()and not Path('/usr/lib/libsparklink.so.0').exists(),'installed file remains')
     check(config.is_file()and hashlib.file_digest(config.open('rb'),'sha256').hexdigest()==before and config.stat().st_mode&0o777==0o600 and (state/'retain').read_text()=='administrator state\n'and foreign.read_text()=='unrelated version\n','uninstall damaged administrator data')
     run('journal',['journalctl','--no-pager','-b','-u','sparklink'])
     run('kernel-log',['dmesg','--color=never'])
     required=['apt-update','apt-install','package-versions','source-extract','rust-version','cargo-version','source-build','install','groups','udev-reload','ldconfig','dbus-reload','unit-reload','unit-verify','service-start','service-active','config',*[prefix+mode for prefix in ['user-','system-bus-']for mode in ['observer','application','publisher','manager']],*[prefix+kind for kind in ['sparklink','sparklink-native']for prefix in ['pkgconfig-','compile-','external-','needed-']],'python-wheel','python-venv','python-install','external-python','reinstall','service-restart','service-active-after-reinstall','service-stop','uninstall','journal','kernel-log']
     record['required_gates']=required
     check(len({x['name']for x in record['gates']})==len(record['gates']),'duplicate gate')
     check(set(required)=={x['name']for x in record['gates']} and all(x['exit']==0 for x in record['gates']),'required gate missing or failed')
     record['status']='CLEAN_VM_GENERIC_INSTALL_SYSTEM_BUS_AND_EXTERNAL_SDK_LIMITED_PASS';save()
    except BaseException as e:
     record.update(status='FAIL',error=repr(e),traceback=traceback.format_exc());save();print(record['traceback'],flush=True)
     try:run('failure-service-status',['systemctl','status','--no-pager','sparklink'],timeout=10)
     except BaseException:pass
    finally:
     record['end_ns']=time.time_ns();save();os.sync();print('SLKR6_FINAL '+record['status'],flush=True)
     subprocess.run(['systemctl','poweroff'])


if __name__ == '__main__':
    main()
