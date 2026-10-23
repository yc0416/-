import unittest
from unittest.mock import patch
from server import cloud

class CloudDiagnosticsTests(unittest.TestCase):
    def test_database_diagnostics_do_not_echo_credentials(self):
        cases = [('password authentication failed','DB_AUTH'), ('certificate verify failed','DB_TLS'), ('Network is unreachable','DB_NETWORK'), ('invalid percent encoding in URI','DB_URI'), ('server certificate does not match host name','DB_TLS_HOSTNAME'), ('unable to get local issuer certificate','DB_TLS_ISSUER')]
        for detail, code in cases:
            with self.subTest(code=code):
                message=cloud.database_error_message(Exception(detail+' postgresql://user:PRIVATE_PASSWORD@example.invalid/db'))
                self.assertIn('['+code+']',message)
                self.assertNotIn('PRIVATE_PASSWORD',message)
                self.assertNotIn('example.invalid',message)

    def test_separate_password_avoids_uri_encoding(self):
        url='postgresql://postgres.example:[YOUR-PASSWORD]@localhost:5432/postgres'
        password='Dummy:@#%/[]? password'
        with patch.object(cloud,'DATABASE_URL',url), patch.dict('os.environ',{'DATABASE_PASSWORD':password}), patch('psycopg.connect') as connect:
            cloud.connect_database()
            self.assertEqual(connect.call_args.args[0],url.replace('[YOUR-PASSWORD]',''))
            self.assertEqual(connect.call_args.kwargs['password'],password)
            self.assertEqual(connect.call_args.kwargs['sslmode'],'verify-full')

    def test_ca_file_errors_are_distinct(self):
        import tempfile
        with patch.dict('os.environ',{'GALLERY_DB_CA_FILE':'/file-not-present/gallery-ca.pem'}):
            with self.assertRaisesRegex(cloud.SetupError,'DB_CA_MISSING'):
                with cloud.database_trust(): pass
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            invalid = Path(folder) / 'invalid.pem'
            invalid.write_text('not a PEM certificate')
            with patch.dict('os.environ',{'GALLERY_DB_CA_FILE':str(invalid)}):
                with self.assertRaisesRegex(cloud.SetupError,'DB_CA_FORMAT'):
                    with cloud.database_trust(): pass

    def test_storage_failures_are_distinct_and_safe(self):
        for status, code in [(401,'STORAGE_KEY'),(403,'STORAGE_KEY'),(404,'STORAGE_BUCKET'),(503,'STORAGE_NETWORK')]:
            with self.subTest(status=status), patch.object(cloud,'storage_request',side_effect=cloud.StorageError('PRIVATE_UPSTREAM_BODY',status)):
                with self.assertRaises(cloud.SetupError) as result:cloud.verify_storage()
                self.assertIn('['+code+']',str(result.exception))
                self.assertNotIn('PRIVATE_UPSTREAM_BODY',str(result.exception))
        with patch.object(cloud,'storage_request',return_value=b'{"public":true}'):
            with self.assertRaisesRegex(cloud.SetupError,'STORAGE_PUBLIC'):cloud.verify_storage()

if __name__=='__main__':unittest.main()
