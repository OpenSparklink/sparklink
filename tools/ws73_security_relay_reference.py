#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""VM-only real reference-Host relay diagnostic; never an automatic recovery gate.

The reference Host and test-only warm CLOSE patch run only inside its private
VM, after Native stop/interface-unbind. This is not a production UserHost ABI.
USB/Complete and peer application results are deliberately separate.
"""
import argparse,sys,json,time,subprocess,shutil,uuid,hashlib,os,re
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import ws73_target as target
from ws73_capture import read_capture,check_capture_stats
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--prepared',type=Path,required=True)
parser.add_argument('--reference',type=Path,required=True)
parser.add_argument('--usb-include',type=Path,required=True,help='Directory containing libusb-1.0/libusb.h')
parser.add_argument('--usb-library',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--native-port',required=True)
parser.add_argument('--reload-native',action='store_true')
parser.add_argument('--failure-wire-index',type=lambda v:int(v,0),choices=[0x133,0x147,0x1ff],default=0x1ff,help='expected wire index; never changes Native policy/driver')
parser.add_argument('--diagnostic-class-control',action='store_true',help='explicit isolated133 physical control, NOT denial semantics or pairing qualification')
parser.add_argument('--survivor-port',required=True)
parser.add_argument('--oracle-port',required=True)
args=parser.parse_args()
if (args.failure_wire_index==0x133)!=args.diagnostic_class_control:parser.error('wire133 requires explicit diagnostic class control and its isolated kernel image')
if len(os.fsencode(str(args.output.resolve()/'native/qmp.sock')))>=108:parser.error('output path too long for Unix QMP socket')
target.ordinary_identity()
base=args.prepared.resolve(strict=True)
out=args.output.resolve();out.mkdir(exist_ok=False,mode=0o700)
reference=args.reference.resolve(strict=True)
ref_head=subprocess.check_output(['git','-C',str(reference),'rev-parse','HEAD'],text=True).strip()
if ref_head!='f4d85d0e95af2d0043432e1301fd2f6b660a4906' or subprocess.check_output(['git','-C',str(reference),'status','--porcelain'],text=True):
 raise ValueError('exact clean user-specified reference revision required')
ports=[args.native_port,args.survivor_port,args.oracle_port]
if len(set(ports))!=3:raise ValueError('three distinct WS73 physical ports required')
lab=target.lab_module();devices={d['path']:d for d in lab.inventory()}
for port in ports:
 target.usb_properties(port,0)
 if port not in devices or not devices[port]['writable'] or any(i['driver'] for i in devices[port]['interfaces']):raise ValueError('unowned writable WS73 required: '+port)
if not os.access('/dev/kvm',os.R_OK|os.W_OK):raise ValueError('ordinary KVM access required')
# Build a private reference-linked oracle; never modify the source checkout.
build=out/'oracle-build';build.mkdir()
fd=build/'src/ws73_usb_sle_fd.c';fd.parent.mkdir();(build/'src/sle73').mkdir();shutil.copy2(reference/'src/ws73_usb_sle_fd.c',fd)
with (build/'patch.log').open('wb') as log:
 subprocess.run(['patch','--batch','-p1','-i',str(HERE/'lab/security_relay_reference_warm.patch')],cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
sm=build/'src/sle73/sle73_sm.c';shutil.copy2(reference/'src/sle73/sle73_sm.c',sm)
with (build/'sdk111-patch.log').open('wb') as log:
 subprocess.run(['patch','--batch','-p1','-i',str(HERE/'lab/security_relay_reference_sdk111.patch')],cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
oracle=build/'oracle'
cold_source=HERE/'lab/security_relay_oracle.c'
if args.diagnostic_class_control:
 text=sm.read_text();marker='\n\tif (!sm_active()) {'
 if text.count(marker)!=1:raise ValueError('exact reference observer location required')
 text=text.replace(marker, '\n\tif (idx==0x133) {\n  extern void relay_control_receive(unsigned,unsigned,const unsigned char *,unsigned);\n  relay_control_receive(conn,idx,pl+5,n);\n }\n'+marker)
 sm.write_text(text)
sources=[p for p in (reference/'src').glob('ws73_*.c') if p.name!='ws73_usb_sle_fd.c']+[p for p in (reference/'src/sle73').glob('*.c') if p.name!='sle73_sm.c']+[sm]
command=['cc','-std=c11','-D_POSIX_C_SOURCE=200809L','-Wall','-Wextra','-Werror','-I'+str(reference/'include'),'-I'+str(reference/'src'),'-I'+str(reference/'src/sle73'),'-I'+str(args.usb_include.resolve(strict=True)),str(cold_source),str(fd),*[str(p) for p in sources],str(args.usb_library.resolve(strict=True)),'-lcrypto','-lpthread','-o',str(oracle)]
if args.diagnostic_class_control:command.insert(1,'-DWS73_RELAY_DIAGNOSTIC_CONTROL')
with (build/'build.log').open('wb') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
package=json.loads((base/'manifest.json').read_text());processes=[];monitors=[]
record={'status':'STARTING','vm_only':True,'kernel':package['native_vm']['kernel_head'],'service':package['native_vm']['userspace_head'],'reference':ref_head,'scope':'Real relay diagnostic; oracle original-image reload mandatory; not paired/encrypted/automatic recovery','vms':{}}
record['test_inputs']={str(p.name):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),cold_source,HERE/'lab/security_relay_reference_warm.patch',HERE/'lab/security_relay_reference_sdk111.patch',fd,sm,oracle]}
snapshots=out/'source-snapshots';snapshots.mkdir()
for source in [Path(__file__),cold_source,HERE/'lab/security_relay_reference_warm.patch',HERE/'lab/security_relay_reference_sdk111.patch',fd,sm]:shutil.copy2(source,snapshots/source.name)
if not target.usb_host_boundary(package['qemu']['path'])['supported']:raise ValueError('pinned QEMU USB opt-outs required')
def save():(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
def wait(path,predicate,proc,seconds):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:
  if path.exists() and predicate(path.read_text(errors='replace')):return
  if proc.poll() is not None:raise RuntimeError(f'VM exited early: {proc.returncode}: {path}')
  time.sleep(.1)
 raise TimeoutError(str(path))
finish=r'''
kill -TERM "$daemon" 2>/dev/null
[ -z "$daemon" ] || wait "$daemon"
kill -INT "$capture"; wait "$capture" || fail 'capture seal'
dmesg > /evidence/kernel.log
cat /proc/sys/kernel/tainted > /evidence/taint.txt
sync
poweroff -f
while :; do sleep 60; done
'''
try:
 for role,port in [('native',args.native_port),('oracle',args.oracle_port)]:
  row=out/role;row.mkdir();root=row/'root';shutil.copytree(base/'root',root,symlinks=True)
  evidence=row/'evidence';evidence.mkdir();rid=str(uuid.uuid4())
  if role=='native':
   init=(root/'init').read_text().split('if grep -qw ws73.early_bootstrap_fault=1')[0]+r'''
/bin/python3 -c "import sys;sys.path.insert(0,'/usr/share/sparklink/tools');from ws73_target_guest import ready;ready(0)" > /evidence/ready-supervisor.log 2>&1 || fail 'current registration Ready'
adapter=$(/bin/python3 -c "import json;print(json.load(open('/evidence/ready-0.json'))['path'])")
/bin/slctl --adapter "$adapter" advertise negotiable > /evidence/advertise.txt 2>&1 || fail 'advertise'
/bin/python3 -c "import sys;sys.path.insert(0,'/usr/share/sparklink/tools');from ws73_target_guest import ready;ready(1)" > /evidence/peer-ready-supervisor.log 2>&1 || fail 'peer Ready'
other=$(/bin/python3 -c "import json;print(json.load(open('/evidence/ready-1.json'))['path'])")
/bin/slctl --adapter "$other" scan on > /evidence/peer-scan-start.txt 2>&1 || fail 'peer scan start'
echo RELAY_NATIVE_ADVERTISING
for n in $(seq 1 1800); do
 /bin/slctl --adapter "$adapter" connection-objects > /evidence/connection-objects.txt 2>&1
 connection=$(/bin/busybox sed -n 's/^NativeConnectionObject:.* path=\(.*\)$/\1/p' /evidence/connection-objects.txt)
 [ -n "$connection" ] && break
 sleep 0.1
done
[ -n "$connection" ] || fail 'real connection object'
/bin/su ws73 -s /bin/sh -c "/bin/slktest --adapter $adapter channel peer $connection --check --count 1" > /evidence/channel.txt 2>&1 & binding=$!
for n in $(seq 1 3000); do [ -f /evidence/stop ] && break; sleep 0.1; done
/bin/slctl --adapter "$adapter" connections > /evidence/connections.txt 2>&1
/bin/slctl --adapter "$other" show > /evidence/peer-after.txt 2>&1 || fail 'peer still Ready'
/bin/slctl --adapter "$other" scan off > /evidence/peer-scan-stop.txt 2>&1 || fail 'peer scan stop'
'''+finish
  else:
   target.copy_elf(oracle,root/'bin/relay-oracle',root)
   init=(root/'init').read_text().split('if grep -qw ws73.early_bootstrap_fault=1')[0]+r'''
/bin/python3 -c "import sys;sys.path.insert(0,'/usr/share/sparklink/tools');from ws73_target_guest import ready;ready(0)" > /evidence/ready-supervisor.log 2>&1 || fail 'current registration Ready'
adapter=$(/bin/python3 -c "import json;print(json.load(open('/evidence/ready-0.json'))['path'])")
kill -TERM "$daemon"; wait "$daemon"; daemon=''
echo '1-1:1.0' > /sys/bus/usb/drivers/sparklink_ws73_usb/unbind || fail 'oracle exclusive handoff'
[ ! -e /sys/bus/usb/devices/1-1:1.0/driver ] || fail 'competing driver'
dmesg > /evidence/oracle-initial-kernel.log
if ! grep -q 'downloaded sparklink/ws73/ws73.bin' /evidence/oracle-initial-kernel.log; then
/bin/relay-oracle --reset-only > /evidence/controlled-reset.txt 2>&1
reset_ret=$?
echo "$reset_ret" > /evidence/controlled-reset-exit.txt
echo RELAY_CONTROLLED_RESET_TERMINAL
/bin/slkd $config_args --storage "$storage" -n > /evidence/slkd-reloaded.log 2>&1 & daemon=$!
/bin/python3 -c "import sys;sys.path.insert(0,'/usr/share/sparklink/tools');from ws73_target_guest import ready;ready(0)" > /evidence/reloaded-ready-supervisor.log 2>&1 || fail 'actual reloaded registration Ready'
dmesg > /evidence/reloaded-kernel.log
grep -q 'downloaded sparklink/ws73/ws73.bin' /evidence/reloaded-kernel.log || fail 'firmware file was not actually uploaded'
kill -TERM "$daemon"; wait "$daemon"; daemon=''
echo '1-1:1.0' > /sys/bus/usb/drivers/sparklink_ws73_usb/unbind || fail 'reloaded oracle exclusive handoff'
[ ! -e /sys/bus/usb/devices/1-1:1.0/driver ] || fail 'reloaded competing driver'
else
 dmesg > /evidence/reloaded-kernel.log
fi
local=$(/bin/python3 -c "import json;print(json.load(open('/evidence/ready-0.json'))['address'])")
peer=$(cat /evidence/peer-address.txt)
/bin/relay-oracle "$peer" "$local" > /evidence/oracle.log 2>&1
ret=$?
echo "$ret" > /evidence/oracle-exit.txt
cat /evidence/oracle.log
echo RELAY_ORACLE_TERMINAL
'''+finish
  if role=='native' and args.reload_native:
   target.copy_elf(oracle,root/'bin/relay-oracle',root)
   needle=r'''/bin/python3 -c "import sys;sys.path.insert(0,'/usr/share/sparklink/tools');from ws73_target_guest import ready;ready(0)" > /evidence/ready-supervisor.log 2>&1 || fail 'current registration Ready'
'''
   replacement=needle+r'''dmesg > /evidence/native-initial-kernel.log
if ! grep -q 'downloaded sparklink/ws73/ws73.bin' /evidence/native-initial-kernel.log; then
kill -TERM "$daemon"; wait "$daemon"; daemon=''
echo '1-1:1.0' > /sys/bus/usb/drivers/sparklink_ws73_usb/unbind || fail 'native maintenance ownership'
/bin/relay-oracle --reset-only > /evidence/native-controlled-reset.txt 2>&1
reset_ret=$?
echo "$reset_ret" > /evidence/native-controlled-reset-exit.txt
/bin/slkd $config_args --storage "$storage" -n > /evidence/slkd-native-reloaded.log 2>&1 & daemon=$!
/bin/python3 -c "import sys;sys.path.insert(0,'/usr/share/sparklink/tools');from ws73_target_guest import ready;ready(0)" > /evidence/native-reloaded-ready.log 2>&1 || fail 'native reloaded Ready'
fi
dmesg > /evidence/native-reloaded-kernel.log
grep -q 'downloaded sparklink/ws73/ws73.bin' /evidence/native-reloaded-kernel.log || fail 'native actual upload required'
/bin/python3 -c "import time,json;json.dump({'wall_ns':time.time_ns()},open('/evidence/native-upload-boundary.json','w'))"
echo RELAY_NATIVE_CONTROLLED_RELOAD_READY
'''
   assert needle in init;init=init.replace(needle,replacement,1)
  (root/'init').write_text(init);(root/'init').chmod(0o755)
  disk=row/'root.btrfs'
  with disk.open('wb') as f:f.truncate(512*1024*1024)
  with (row/'pack.log').open('wb') as f:subprocess.run(['mkfs.btrfs','-U',rid,'--rootdir',str(root),str(disk)],stdout=f,stderr=subprocess.STDOUT,check=True)
  qmp=row/'qmp.sock';console=row/'console.log'
  qemu_command=[package['qemu']['path'],'-L',str(base/'qemu-data'),'-machine','q35,accel=kvm','-cpu','host','-m','1024M','-smp','2','-display','none','-monitor','none','-no-reboot','-nic','none','-serial','file:'+str(console),'-qmp','unix:'+str(qmp)+',server=on,wait=off','-kernel',str(base/'bzImage'),'-initrd',str(base/'initramfs.cpio.gz'),'-append',f'console=ttyS0 loglevel=6 log_buf_len=4M panic=1 oops=panic root=UUID={rid} rootfstype=btrfs rw init=/init rd.plymouth=0 plymouth.enable=0 rd.shell=0 rd.retry=30 rd.timeout=45','-device','qemu-xhci,id=xhci,p2=8,p3=8','-fsdev',f'local,id=evidence,path={evidence},security_model=mapped-xattr','-device','virtio-9p-pci,fsdev=evidence,mount_tag=evidence','-drive',f'file={disk},if=none,id=scratch,format=raw','-device','nvme,drive=scratch,serial=SLK_VM_ROOT_ONLY']
  err=(row/'qemu-stderr.log').open('wb');proc=subprocess.Popen(qemu_command,stdout=subprocess.DEVNULL,stderr=err);processes.append(proc)
  if role=='oracle':
   owner=json.loads((out/'native/evidence/ready-0.json').read_text())
   (evidence/'peer-address.txt').write_text(owner['address']+'\n')
  record['vms'][role]={'port':port,'args':qemu_command,'pid':proc.pid,'root_uuid':rid};save()
  wait(console,lambda s:'WS73_TARGET_CAPTURE_READY' in s,proc,100)
  monitor=target.lab_module().Qmp(qmp,row/'qmp.jsonl');monitors.append(monitor)
  monitor.execute('device_add',target.usb_properties(port,0))
  if role=='native':
   if args.reload_native:wait(console,lambda s:'RELAY_NATIVE_CONTROLLED_RELOAD_READY' in s,proc,150)
   monitor.execute('device_add',target.usb_properties(args.survivor_port,1))
  if role=='native':wait(console,lambda s:'RELAY_NATIVE_ADVERTISING' in s,proc,150)
  else:
   wait(evidence/'oracle.log',lambda s:'RELAY_ORACLE_LINKED' in s,proc,60)
   wait(out/'native/evidence/channel.txt',lambda s:'NativeChannelInfo:' in s,processes[0],20)
   (evidence/'pair-allow').touch()
   wait(console,lambda s:'RELAY_ORACLE_TERMINAL' in s,proc,150)
  if role=='oracle':(out/'native/evidence/stop').touch()
 for proc in processes:proc.wait(timeout=30)
 record['exits']=[p.returncode for p in processes]
 if record['exits'] != [0,0]:raise RuntimeError('owned VM abnormal exit')
 proof={}
 for role in ['native','oracle']:
  evidence=out/role/'evidence';owner=json.loads((evidence/'ready-0.json').read_text())
  capture=read_capture(evidence/'ws73.pcap',[(owner['bus'],owner['device'])])
  assert check_capture_stats((evidence/'capture-stats.txt').read_text())==capture['packet_count']
  assert (evidence/'taint.txt').read_text().strip()=='0'
  if target.kernel_fault((evidence/'kernel.log').read_text()):raise RuntimeError('kernel warning/fault')
  proof[role]={'capture_sha256':hashlib.sha256((evidence/'ws73.pcap').read_bytes()).hexdigest(),
    'packet_count':capture['packet_count'],'commands':[p for p in capture['commands'] if p['opcode']==0x1812],
    'complete':[p for p in capture['complete'] if p['opcode']==0x1812],
    'received':[p for p in capture['native_events'] if p['event']==0x14]}
 record['relay']=proof
 from ws73_firmware_upload_evidence import successful_out,corroborate as upload_corroborate
 record['firmware_uploads']={}
 for firmware_role in (['native'] if args.reload_native else [])+['oracle']:
  evidence=out/firmware_role/'evidence'
  uploads=successful_out(evidence/'ws73.pcap')
  if firmware_role=='native':
   boundary=json.loads((evidence/'native-upload-boundary.json').read_text())['wall_ns']
   uploads=[r for r in uploads if r['wall_ns']<=boundary]
  record['firmware_uploads'][firmware_role]=upload_corroborate(uploads,base/'root/lib/firmware/sparklink/ws73')

 peer_result=(out/'oracle/evidence/oracle-exit.txt').read_text().strip()
 # A Complete or a normally shut down VM alone is never a successful gate.
 info=re.findall(r'^NativeChannelInfo: index=(\d+) generation=(\d+) lifetime=(\d+) handle=(\d+) ',(out/'native/evidence/channel.txt').read_text(),re.M)
 peer_handles=re.findall(r'PAIR_REQUEST handle=(\d+) result=0', (out/'oracle/evidence/oracle.log').read_text())
 if len(info)!=1 or len(peer_handles)!=1:raise ValueError('exact current Session and actual peer request receipt required')
 native_handle=int(info[0][3]);oracle_handle=int(peer_handles[0])
 if not 0<=native_handle<=0xfff or not 0<=oracle_handle<=0xfff:raise ValueError('12bit current handles required')
 expected=native_handle.to_bytes(2,'little').hex()+args.failure_wire_index.to_bytes(2,'little').hex()+'0102'
 peer_expected=oracle_handle.to_bytes(2,'little').hex()+args.failure_wire_index.to_bytes(2,'little').hex()+'0102'
 matching=(len(proof['native']['commands'])==1 and proof['native']['commands'][0]['params']==expected
   and len(proof['native']['complete'])==1 and proof['native']['complete'][0]['status']==0
   and proof['native']['complete'][0]['value']==expected[:8]
   and len(proof['oracle']['received'])==1 and proof['oracle']['received'][0]['params']==peer_expected)
 survivor=json.loads((out/'native/evidence/ready-1.json').read_text())
 after=(out/'native/evidence/peer-after.txt').read_text()
 if 'State:       Ready' not in after or 'Generation:  '+str(survivor['generation']) not in after:
  raise ValueError('survivor registration changed or not Ready')
 for phase in ['start','stop']:
  if 'state=3 errno=0 status=0x00' not in (out/'native/evidence'/('peer-scan-'+phase+'.txt')).read_text():raise ValueError('survivor actual scan transaction failed')
 record['survivor_scope']='same generation Ready and actual scan start/stop; not independent business or natural recovery qualification'
 record['status']='REAL_DENIAL_RELAY_PASS' if peer_result=='0' and matching else 'REAL_PEER_DELIVERY_FAIL'
 if args.failure_wire_index==0x133:
  text=(out/'oracle/evidence/oracle.log').read_text()
  checked=text.count(f'RELAY_CONTROL_RX_MATCH handle={oracle_handle} index=0133 bytes=02')==1 and 'RELAY_CONTROL_RX_MISMATCH' not in text
  record['supported_class_positive_control']=dict(matching_actual_usb_and_complete_and_peer=matching,peer_application_payload_checked=checked,denial_semantics=False,production_mapping=False)
  record['status']='REAL_SUPPORTED_CLASS_CONTROL_POSITIVE' if matching and checked else 'REAL_SUPPORTED_CLASS_CONTROL_FAIL'
  record['scope']='Isolated wire133 transport positive control; NOT PairingNotSupported/approved pairing/security qualification'
 record['denial_delivery_qualified']=record['status']=='REAL_DENIAL_RELAY_PASS'
 record['pairing_qualification']=False;record['automatic_recovery_qualification']=False
 save()
except BaseException as e:
 record['status']='FAILED';record['failure']=repr(e);save();raise
finally:
 for p in processes:
  if p.poll() is None:p.terminate()
 for p in processes:
  try:p.wait(timeout=10)
  except subprocess.TimeoutExpired:p.kill();p.wait()
 save()

raise SystemExit(0 if record["status"] in ["REAL_DENIAL_RELAY_PASS","REAL_SUPPORTED_CLASS_CONTROL_POSITIVE"] else 1)
