# SPDX-License-Identifier: GPL-2.0-only
import copy
import unittest

from ws73_managed_queue_support import properties, verify_transport


def commands():
    sent = [dict(execute='qmp_capabilities', id=1)]
    sent += [dict(execute='device_add', id=i+2, arguments=properties(i)) for i in [0, 1]]
    return [dict(direction='tx', message=m) for m in sent] + [
        dict(direction='rx', message={'id': m['id'], 'return': {}}) for m in sent]


class SyntheticTransportTests(unittest.TestCase):
    def test_partial_model_controls_cannot_target_host_or_survivor(self):
        for prop,value,path in [('test-runtime-in-hold-once',True,'/machine/peripheral/ws73_0'),
                                ('model-terminal-release',True,'/machine/peripheral/ws73_1'),
                                ('model-terminal-release',False,'/machine/peripheral/ws73_0')]:
            rows=commands()
            for i in [0,1]:rows[i+1]['message']['arguments']=properties(i,True)
            rows+=[dict(direction='tx',message=dict(execute='qom-set',id=4,arguments=dict(path=path,property=prop,value=value))),
                   dict(direction='rx',message={'id':4,'return':{}})]
            with self.subTest(prop=prop,path=path,value=value),self.assertRaises(ValueError):verify_transport(rows,True)

    def test_successful_exact_simulated_objects(self):
        verify_transport(commands())

    def test_host_usb_and_extra_owner_options_rejected(self):
        for kind in ['driver', 'hostport', 'hostbus', 'guest-reset']:
            rows = commands()
            rows[1]['message']['arguments'][kind] = 'usb-host' if kind == 'driver' else 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                verify_transport(rows)

    def test_extra_reset_command_missing_or_failed_reply_rejected(self):
        variants = []
        extra = commands(); extra.insert(3, {'direction': 'tx', 'message': {'execute': 'system_reset', 'id': 4}})
        variants.append(extra)
        absent = commands(); absent.pop(); variants.append(absent)
        failed = commands(); failed[-1]['message'] = {'id': 3, 'error': {'desc': 'failure'}}
        variants.append(failed)
        duplicate = commands(); duplicate.append(copy.deepcopy(duplicate[-1])); variants.append(duplicate)
        for rows in variants:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                verify_transport(rows)

    def test_wrong_or_boolean_slot_rejected(self):
        for slot in [True, False, -1, 2, '0']:
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                properties(slot)

    def test_later_selector_cannot_mutate_peer_or_accept_bool_or_unrequested_step(self):
        for step in [1,2]:
            rows=commands()
            for i in [0,1]:rows[i+1]['message']['arguments']=properties(i,True)
            rows+=[dict(direction='tx',message=dict(execute='qom-set',id=4,arguments=dict(path='/machine/peripheral/ws73_0',property='model-terminal-skip-count',value=step))),dict(direction='rx',message={'id':4,'return':{}})]
            verify_transport(rows,True,False,step)
            for change in ['bool','wrong-step','peer','readonly']:
                bad=copy.deepcopy(rows);args=bad[-2]['message']['arguments']
                if change=='bool':args['value']=True
                if change=='wrong-step':args['value']=3-step
                if change=='peer':args['path']='/machine/peripheral/ws73_1'
                if change=='readonly':args['property']='model-terminal-skipped'
                with self.subTest(step=step,change=change),self.assertRaises(ValueError):verify_transport(bad,True,False,step)
            with self.assertRaises(ValueError):verify_transport(rows,True)
