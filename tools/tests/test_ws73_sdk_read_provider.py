"""Runner admission only; no callback, daemon, kernel or hardware qualification."""
import unittest

from ws73_application_client import owned_arguments
from ws73_capture import CaptureError
from ws73_ssap_owned import publisher


class ProviderOwnerAdmission(unittest.TestCase):
    owner = dict(owner=dict(index=7, generation=11), object=dict(path='/connection'))

    def arguments(self, **kwargs):
        return owned_arguments('c', self.owner, '1234', '5678', 'ab', 'allow', **kwargs)

    def test_explicit_provider_uses_original_readonly_consumer_and_policy(self):
        for api in ('c', 'python'):
            for policy in ('none', 'allow', 'deny', 'ask'):
                args = owned_arguments(api, self.owner, '1234', '5678', 'ab', policy,
                                       read_only=True, read_provider=True)
                prefix = ['/bin/ws73-application-client-c'] if api == 'c' else [
                    '/bin/python3', '/usr/share/sparklink/tools/ws73-application-client.py']
                self.assertEqual(args, prefix + ['owned-readonly', '7', '11', '1234',
                    '5678', 'ab'] + ([] if policy == 'none' else [policy]))

    def test_historical_entry_and_restrictions_are_unchanged(self):
        self.assertEqual(self.arguments(), ['/bin/ws73-application-client-c', 'owned',
            '7', '11', '1234', '5678', 'ab', 'allow'])
        self.assertEqual(self.arguments(update_connection='/connection'), [
            '/bin/ws73-application-client-c', 'owned-updates', '7', '11', '1234',
            '5678', 'ab', 'allow', '/connection'])
        with self.assertRaises(CaptureError):
            self.arguments(read_only=True)
        for api in ('c', 'python'):
            original = owned_arguments(api, self.owner, '1234', '5678', 'ab',
                                       'none', read_only=True)
            explicit = owned_arguments(api, self.owner, '1234', '5678', 'ab',
                                       'none', read_only=True, read_provider=False)
            self.assertEqual(original, explicit)
            self.assertEqual(original[-6:], ['owned-readonly', '7', '11',
                                            '1234', '5678', 'ab'])

    def test_provider_rejects_nonreadonly_updates_and_nonboolean_optin(self):
        for options in (dict(read_provider=True),
                        dict(read_provider=1, read_only=True),
                        dict(read_provider=True, read_only=1),
                        dict(read_provider=True, read_only=True, update_connection='/connection')):
            with self.subTest(options=options), self.assertRaises(CaptureError):
                self.arguments(**options)

    def test_publisher_rejects_mislabelled_provider_before_access_or_spawn(self):
        for options in (dict(read_provider=True),
                        dict(read_provider=True, sdk_api='c', read_only=True, operations=5),
                        dict(read_provider=True, sdk_api='python', read_only=True, operations=1, updates=True),
                        dict(read_provider=True, sdk_api='c', read_only=False, operations=1),
                        dict(read_provider=True, sdk_api='c', read_only=True, operations=True),
                        dict(read_provider=True, sdk_api='c', read_only=True, operations=1.0),
                        dict(read_provider=1, sdk_api='c', read_only=True, operations=1),
                        dict(sdk_api='c', operations=1)):
            with self.subTest(options=options), self.assertRaises(CaptureError):
                # None inputs deliberately ensure malformed scopes are rejected
                # before touching a run directory, owner or subprocess.
                with publisher(None, None, 0, 'allow', **options):
                    self.fail('invalid scope reached publisher')


if __name__ == '__main__':
    unittest.main()
