import unittest
from unittest.mock import patch
from server import cloud

class CloudDiagnosticsTests(unittest.TestCase):
    def test_database_diagnostics_do_not_echo_credentials(self):
        cases = [('password authentication failed','DB_AUTH'), ('certificate verify failed','DB_TLS'), ('Network is unreachable','DB_NETWORK'), ('invalid percent encoding in URI','DB_URI')]
        for detail, code in cases:
            with self.subTest(code=code):
                message=cloud.database_error_message(Exception(detail+' postgresql://user:PRIVATE_PASSWORD@example.invalid/db'))
                self.assertIn('['+code+']',message)
                self.assertNotIn('PRIVATE_PASSWORD',message)
                self.assertNotIn('example.invalid',message)

    def test_storage_failures_are_distinct_and_safe(self):
        for status, code in [(401,'STORAGE_KEY'),(403,'STORAGE_KEY'),(404,'STORAGE_BUCKET'),(503,'STORAGE_NETWORK')]:
            with self.subTest(status=status), patch.object(cloud,'storage_request',side_effect=cloud.StorageError('PRIVATE_UPSTREAM_BODY',status)):
                with self.assertRaises(cloud.SetupError) as result:cloud.verify_storage()
                self.assertIn('['+code+']',str(result.exception))
                self.assertNotIn('PRIVATE_UPSTREAM_BODY',str(result.exception))
        with patch.object(cloud,'storage_request',return_value=b'{"public":true}'):
            with self.assertRaisesRegex(cloud.SetupError,'STORAGE_PUBLIC'):cloud.verify_storage()

if __name__=='__main__':unittest.main()
