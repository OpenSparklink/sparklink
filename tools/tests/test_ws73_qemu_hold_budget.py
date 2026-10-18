# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ws73_qemu_hold_budget import transform,BASE_SHA256,HOLD_MS

class BudgetSource(unittest.TestCase):
    def test_unpinned_partial_or_already_changed_source_rejected(self):
        for bad in [b'',b'timer_mod(s->test_runtime_hold_timer,\n                  qemu_clock_get_ms(QEMU_CLOCK_REALTIME) + 2000);',b'WS73 real device source']:
            with self.assertRaises(ValueError):transform(bad)
        self.assertEqual(HOLD_MS,8000)
        self.assertEqual(len(BASE_SHA256),64)

    def test_exact_three_edits_and_read_only_budget(self):
        # Isolate text transformation only. The real pinned source is separately
        # hashed and compiled in the lab; this is not a QEMU/hardware proof.
        text='\n'.join(['    uint64_t                         test_runtime_holds;',
          'timer_mod(s->test_runtime_hold_timer,\n                  qemu_clock_get_ms(QEMU_CLOCK_REALTIME) + 2000);',
          '    object_property_add_bool(obj, "test-runtime-in-hold-once",',
          'unchanged_reset_and_detach_guard'])
        with patch('ws73_qemu_hold_budget.BASE_SHA256',hashlib.sha256(text.encode()).hexdigest()):
            out=transform(text.encode()).decode()
            self.assertIn('s->test_runtime_hold_ms = 8000;',out)
            self.assertIn('&s->test_runtime_hold_ms, OBJ_PROP_FLAG_READ',out)
            self.assertIn(' + s->test_runtime_hold_ms);',out)
            self.assertIn('unchanged_reset_and_detach_guard',out)
            with self.assertRaises(ValueError):transform(out.encode())
