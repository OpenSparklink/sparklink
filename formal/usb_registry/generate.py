# SPDX-License-Identifier: GPL-2.0-only
# Actual production fragments; dependency types and logging only are fixtures.
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[3]
here=root/'linux/tools/testing/selftests/sparklink';sys.path.insert(0,str(here))
from run_connection_tx import function
from run_usb_discovery import block
net=root/'linux/net/sparklink';dev=(net/'sle_dev.rs').read_text();dli=(net/'sle_dli.rs').read_text()
head='''use std::sync::atomic::{AtomicU32,Ordering};
type Result<T=()>=std::result::Result<T,i32>;
const ENOSPC:i32=-28;
macro_rules! pr_info{($($t:tt)*)=>{}};
#[derive(Clone,Copy,Default)]pub enum SleBus{#[default]None,Usb}
#[derive(Default)]struct SleDevStats;
'''.replace('=>{}};','=>{}}')
import re
constants='\n'.join(re.search(r'(?m)^(?:pub(?:\(crate\))? )?const '+n+r'[^\n]+',dev).group() for n in ['SLE_DEV_NAME_LEN','SLE_DEV_MAX','SLE_DEV_SETUP'])
info=block(dli,dli.index('pub struct SleControllerInfo {'))+'\nimpl Default for SleControllerInfo{'+function(dli[dli.index('impl Default for SleControllerInfo'):],'default')+'}\n'
structure=block(dev,dev.index('pub(crate) struct SleDev {'))+'\nimpl SleDev{'+function(dev[dev.index('impl SleDev {'):],'new')+'}\n'+block(dev,dev.index('pub(crate) struct SleDevRegistry {'))+'\nimpl SleDevRegistry{'
for n in ['new','register_pending']:structure+=function(dev[dev.index('impl SleDevRegistry {'):].replace('const fn ','fn '),n)+'\n'
structure+='}\n'
Path(sys.argv[1]).write_text(head+constants+'\n'+info+structure)
