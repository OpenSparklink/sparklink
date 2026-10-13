"""Compare provider bus identifiers in live kernel, Rust, generated C and Python."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from sparklink.structs import BusType

ROOT = Path(__file__).resolve().parents[3]
KERNEL = Path(os.environ.get('SPARKLINK_KERNEL_UAPI', ROOT.parent/'linux/include/uapi/linux/sparklink_ioctl.h')).resolve().parent
NAMES = ('Virtual', 'Uart', 'Spi', 'Sdio', 'Usb', 'Mmio', 'Test')


class BusContract(unittest.TestCase):
    def test_live_declarations_agree(self):
        text = (ROOT/'crates/slk-protocol/src/types.rs').read_text()
        match = re.search(r'(?s)#\[repr\(u8\)\]\s*pub enum BusType\s*\{.*?\n\}', text)
        self.assertIsNotNone(match)
        rust = match.group(0) + '\nfn main(){println!("{:?}",[' + ','.join(f'BusType::{n} as u8' for n in NAMES) + ']);}'
        def c_probe(header, prefix):
            return '#include <stdio.h>\n#include "' + str(header) + '"\nint main(void){printf("[%u,%u,%u,%u,%u,%u,%u]",' + ','.join(prefix(n) for n in NAMES) + ');return 0;}\n'
        sources = {
            'kernel': c_probe(KERNEL/'sparklink.h', lambda n: 'SPARKLINK_BUS_'+n.upper()),
            'sdk': c_probe(ROOT/'crates/libsparklink/include/sparklink.h', lambda n: 'BusType_'+n),
        }
        observed = {'python': [int(BusType[n]) for n in NAMES]}
        with tempfile.TemporaryDirectory(prefix='sparklink-bus-contract-') as tmp:
            directory = Path(tmp)
            for name, source in sources.items():
                path = directory/(name+'.c'); path.write_text(source)
                exe = directory/name
                subprocess.run([os.environ.get('CC','cc'),'-std=c11','-Wall','-Wextra','-Werror',str(path),'-o',str(exe)],check=True)
                observed[name] = json.loads(subprocess.check_output([str(exe)],text=True))
            path = directory/'rust.rs';path.write_text(rust);exe=directory/'rust'
            subprocess.run([os.environ.get('RUSTC','rustc'),'--edition=2021','-D','warnings',str(path),'-o',str(exe)],check=True)
            observed['rust'] = json.loads(subprocess.check_output([str(exe)],text=True))
        for name, values in observed.items():
            self.assertEqual(observed['kernel'], values, name)
        self.assertNotEqual(BusType.Test, BusType.Usb)
        self.assertNotEqual(BusType.Test, BusType.Virtual)
