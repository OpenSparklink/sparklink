# SPDX-License-Identifier: GPL-2.0-only
"""Actual source-manifest validation;no guest/kernel/hardware qualification."""
import copy
from pathlib import Path
import unittest
from ws73_target import file_record,HERE
from ws73_ssap_sender_deadline import validate_inputs

class FreshInputs(unittest.TestCase):
    def test_inflight_requires_actual_subscription_and_supervisor_source(self):
        names=['ws73_ssap_sender_deadline.py','ws73_target_control.py','ws73_target_guest.py','ws73_target_init.sh','testing/application_client/client.c','testing/application_client/client.py']
        package=dict(inputs=[file_record(HERE/n)for n in names if not n.startswith('testing/')],application_client_tools=dict(sources=[file_record(HERE/n)for n in names if n.startswith('testing/')]))
        validate_inputs(package)
        with self.assertRaises(ValueError):validate_inputs(package,subscription=True)
        for n in ('ws73_ssap_subscription.py','ws73_application_role.py'):package['inputs'].append(file_record(HERE/n))
        validate_inputs(package,subscription=True)
        for n in names+['ws73_ssap_subscription.py','ws73_application_role.py']:
            bad=copy.deepcopy(package);rows=bad['application_client_tools']['sources']if n.startswith('testing/')else bad['inputs']
            next(v for v in rows if Path(v['path']).resolve()==(HERE/n).resolve())['sha256']='0'*64
            with self.subTest(source=n),self.assertRaises(ValueError):validate_inputs(bad,subscription=True)
