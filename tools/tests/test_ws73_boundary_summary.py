"""Actual saved-report validator; finite structural fixtures, no hardware proof."""
import copy
import unittest
from ws73_channel_socket import valid_boundary_summary
from ws73_target import run_exit_code


def fixture():
    packet={'fragments':[{'record':1}]}
    return dict(status='PASSTHROUGH_SUPPORT_PASS',supervisor_exit=0,qemu_exit=0,
        channel_socket_verification_requested=True,channel_socket_boundaries_requested=True,
        channel_socket_bytes_requested=249,channel_socket_rounds_requested=4,
        ordinary_channel_socket_acceptance=True,qemu_args=['ws73.channel_boundaries=1'],
        channel_socket_corroboration=dict(status='ORDINARY_CHANNEL_SOCKET_USB_CORROBORATED',round_trips=8,
            application_message_bytes=249,dtap_pdu_bytes=254,application_boundary_rejections=16,
            proofs=[dict(phase=n,legs=[dict(sequence=i//2,tx=copy.deepcopy(packet),rx=copy.deepcopy(packet)) for i in range(8)]) for n in range(2)]))


class BoundarySummaryTests(unittest.TestCase):
    def test_actual_exit_requires_complete_scope_and_both_legs(self):
        original=fixture()
        self.assertTrue(valid_boundary_summary(original))
        self.assertEqual(run_exit_code(original),0)
        for change in ['proofs','phase','leg','rx','fragments','sequence','length','pdu','count','rounds','bool','token','selector']:
            bad=copy.deepcopy(original);proof=bad['channel_socket_corroboration']
            if change=='proofs':proof['proofs']=[]
            elif change=='phase':proof['proofs'][1]['phase']=0
            elif change=='leg':proof['proofs'][0]['legs'].pop()
            elif change=='rx':proof['proofs'][0]['legs'][0].pop('rx')
            elif change=='fragments':proof['proofs'][0]['legs'][0]['rx']['fragments']=[]
            elif change=='sequence':proof['proofs'][0]['legs'][0]['sequence']=True
            elif change=='length':proof['application_message_bytes']=61
            elif change=='pdu':proof['dtap_pdu_bytes']=249
            elif change=='count':proof['application_boundary_rejections']=0
            elif change=='rounds':proof['round_trips']=7
            elif change=='bool':bad['channel_socket_boundaries_requested']=1
            elif change=='token':bad['qemu_args']=[]
            elif change=='selector':bad.pop('channel_socket_boundaries_requested')
            with self.subTest(change=change):
                self.assertFalse(valid_boundary_summary(bad));self.assertNotEqual(run_exit_code(bad),0)

    def test_length_changes_do_not_inherit_original_payload_scope(self):
        record=fixture();record['channel_socket_bytes_requested']=2042
        self.assertFalse(valid_boundary_summary(record))
        record['channel_socket_corroboration'].update(application_message_bytes=2042,dtap_pdu_bytes=2047)
        self.assertTrue(valid_boundary_summary(record))


if __name__=='__main__':unittest.main()
