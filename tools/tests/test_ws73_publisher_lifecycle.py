"""Original receipt parser fixtures;not SDK,daemon,USB or firmware proof."""
import copy
import json
import unittest
from ws73_application_client import publisher_lifecycle_trace,verify_owned_publishers
from ws73_capture import CaptureError


def fixture():
    owner=dict(owner=dict(index=2,generation=7))
    base=dict(version=1,api='c',pid=123,index=2,generation=7,start=16,property=17,
              created_ns=10,deadline_ns=30_000_000_010,wall_ns=1000,error=0,
              token=0,request_id=0,call_started_ns=0,call_returned_ns=0)
    rows=[dict(base,stage='observed',sampled_ns=50),
          dict(base,stage='approval_return',sampled_ns=120,token=2,request_id=5,call_started_ns=100,call_returned_ns=110),
          dict(base,stage='cleanup_begin',sampled_ns=200),dict(base,stage='cleanup_end',sampled_ns=220)]
    app=dict(api='c',pid=123,start=16,handle=17,
             lifecycle_observation=dict(start_monotonic_ns=40,end_monotonic_ns=80,receipt=copy.deepcopy(rows[0])))
    return app,owner,rows


def output(app,rows):
    return dict(app,stdout=''.join('SdkOwnedLifecycle: '+json.dumps(r)+'\n'for r in rows))


class PublisherLifecycle(unittest.TestCase):
    def test_original_budget_api_return_and_frontend_cleanup_are_distinct(self):
        app,owner,rows=fixture()
        self.assertEqual(publisher_lifecycle_trace(output(app,rows),owner),rows)
        self.assertEqual(publisher_lifecycle_trace(output(app,rows[:1]),owner,terminal=False),rows[:1])
        self.assertNotIn('remote_cleaned',rows[-1])

    def test_changed_identity_clock_budget_and_observation_refused(self):
        for key,value in [('pid',124),('index',3),('generation',8),('start',15),('property',18),
                          ('version',True),('created_ns',11),('deadline_ns',30_000_000_011),
                          ('error',1),('sampled_ns',0),('sampled_ns',True),('api','python'),('extra',0)]:
            app,owner,rows=fixture();rows[1][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(CaptureError):
                publisher_lifecycle_trace(output(app,rows),owner)
        app,owner,rows=fixture();app['lifecycle_observation']['receipt']['sampled_ns']=51
        with self.assertRaises(CaptureError):publisher_lifecycle_trace(output(app,rows),owner)

    def test_missing_duplicate_reordered_and_unrequested_records_refused(self):
        for case in range(6):
            app,owner,rows=fixture()
            if case==0:rows.pop()
            elif case==1:rows.insert(1,copy.deepcopy(rows[0]))
            elif case==2:rows[-2:]=rows[-2:][::-1]
            elif case==3:del app['lifecycle_observation']
            elif case==4:rows[1]['call_returned_ns']=99
            else:rows[1]['token']=0
            with self.subTest(case=case),self.assertRaises(CaptureError):publisher_lifecycle_trace(output(app,rows),owner)
        app,owner,rows=fixture();row=output(app,rows);row['stdout']=row['stdout'].replace('"version": 1','"version": 0, "version": 1',1)
        with self.assertRaises(CaptureError):publisher_lifecycle_trace(row,owner)

    def test_original_expiration_is_retained_as_diagnostic_not_success(self):
        app,owner,rows=fixture()
        rows[-2].update(error=-110,sampled_ns=30_000_000_020)
        rows[-1].update(sampled_ns=30_000_000_030)
        trace=publisher_lifecycle_trace(output(app,rows),owner)
        self.assertEqual(trace[-2]['error'],-110)
        self.assertEqual(trace[0]['deadline_ns'],trace[-1]['deadline_ns'])
        self.assertIsNone(publisher_lifecycle_trace(dict(stdout=''),owner))

    def test_full_publisher_verifier_binds_every_return_to_original_decision(self):
        from test_ws73_application_client import fixture as original_fixture
        run,_=original_fixture();row=run['application_clients'][0]
        row['publisher_lifecycle_observation_version']=1
        for app,registered in zip(row['ssap_owned_publishers'],row['ssap_local_registrations']):
            owner=registered['owner']['owner'];app.update(start=registered['start'],handle=registered['handle'])
            base=dict(version=1,api=app['api'],pid=app['pid'],index=owner['index'],generation=owner['generation'],
                start=app['start'],property=app['handle'],created_ns=8_000_000_000,deadline_ns=38_000_000_000,
                wall_ns=1,error=0,token=0,request_id=0,call_started_ns=0,call_returned_ns=0)
            observed=dict(base,stage='observed',sampled_ns=8_000_000_050)
            app['lifecycle_observation']=dict(start_monotonic_ns=8_000_000_040,end_monotonic_ns=8_000_000_080,receipt=observed)
            rows=[observed]
            for line in app['stdout'].splitlines():
                if line.startswith('SdkAuthorizationDecision: '):
                    d=json.loads(line.split(': ',1)[1]);rows.append(dict(base,stage='approval_return',token=d['token'],
                        request_id=d['request_id'],call_started_ns=d['decision_ns'],call_returned_ns=d['decision_ns']+1,
                        sampled_ns=d['decision_ns']+2))
            rows+=[dict(base,stage='cleanup_begin',sampled_ns=11_000_000_000),dict(base,stage='cleanup_end',sampled_ns=11_000_000_001)]
            app['stdout']+=''.join('SdkOwnedLifecycle: '+json.dumps(r)+'\n'for r in rows)
        self.assertEqual(len(verify_owned_publishers(row)),2)
        app=row['ssap_owned_publishers'][0];old=app['stdout']
        app['stdout']=old.replace('"call_returned_ns": 9000000002','"call_returned_ns": 0',1)
        with self.assertRaises(CaptureError):verify_owned_publishers(row)
        app['stdout']=old.replace('"request_id": 11, "call_started_ns"','"request_id": 999, "call_started_ns"',1)
        with self.assertRaises(CaptureError):verify_owned_publishers(row)


if __name__=='__main__':unittest.main()
