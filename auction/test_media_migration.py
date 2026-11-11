from io import StringIO
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cloudinary.exceptions import AuthorizationRequired, NotFound
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings

from auction.storage import cloudinary_public_id


class CloudinaryMediaMigrationCommandTests(SimpleTestCase):
    def setUp(self):
        workspace_root = Path(__file__).resolve().parents[1]
        self.temp_dir = tempfile.TemporaryDirectory(dir=workspace_root)
        self.addCleanup(self.temp_dir.cleanup)
        self.media_root = Path(self.temp_dir.name)
        self.relative_name = 'product_images/cycle.jpeg'
        self.local_file = self.media_root / self.relative_name
        self.local_file.parent.mkdir(parents=True)
        self.local_file.write_bytes(b'local image data for mocked upload')

    def _sdk(self, *, resource_result=None, resource_error=None, upload_error=None):
        resource = Mock(return_value=resource_result)
        if resource_error is not None:
            resource.side_effect = resource_error
        upload = Mock(return_value={'public_id': cloudinary_public_id(self.relative_name)})
        if upload_error is not None:
            upload.side_effect = upload_error
        return SimpleNamespace(
            api=SimpleNamespace(resource=resource),
            uploader=SimpleNamespace(upload=upload),
        )

    def _run_command(self, stdout, stderr):
        return call_command(
            'sync_media_to_cloudinary',
            stdout=stdout,
            stderr=stderr,
        )

    @override_settings(DEBUG=True)
    @patch('auction.management.commands.sync_media_to_cloudinary._cloudinary_sdk')
    def test_missing_resource_is_uploaded_and_reported_as_success(self, sdk_factory):
        sdk = self._sdk(resource_error=NotFound('not found'))
        sdk_factory.return_value = sdk
        stdout, stderr = StringIO(), StringIO()

        with override_settings(MEDIA_ROOT=self.media_root):
            self._run_command(stdout, stderr)

        sdk.api.resource.assert_called_once_with(
            cloudinary_public_id(self.relative_name), resource_type='image'
        )
        sdk.uploader.upload.assert_called_once_with(
            str(self.local_file),
            public_id=cloudinary_public_id(self.relative_name),
            resource_type='image',
            overwrite=False,
            unique_filename=False,
        )
        self.assertIn('Uploaded 1; already present 0; failed 0.', stdout.getvalue())
        self.assertEqual(stderr.getvalue(), '')

    @override_settings(DEBUG=True)
    @patch('auction.management.commands.sync_media_to_cloudinary._cloudinary_sdk')
    def test_existing_resource_is_skipped_without_overwriting(self, sdk_factory):
        sdk = self._sdk(resource_result={'public_id': 'already-there'})
        sdk_factory.return_value = sdk
        stdout, stderr = StringIO(), StringIO()

        with override_settings(MEDIA_ROOT=self.media_root):
            self._run_command(stdout, stderr)

        sdk.uploader.upload.assert_not_called()
        self.assertIn('Uploaded 0; already present 1; failed 0.', stdout.getvalue())
        self.assertEqual(stderr.getvalue(), '')

    @override_settings(DEBUG=True)
    @patch('auction.management.commands.sync_media_to_cloudinary._cloudinary_sdk')
    def test_cloudinary_authentication_failure_is_reported_not_treated_as_missing(self, sdk_factory):
        sdk = self._sdk(resource_error=AuthorizationRequired('invalid credentials'))
        sdk_factory.return_value = sdk
        stdout, stderr = StringIO(), StringIO()

        with override_settings(MEDIA_ROOT=self.media_root):
            with self.assertRaises(CommandError):
                self._run_command(stdout, stderr)

        sdk.uploader.upload.assert_not_called()
        self.assertIn('AuthorizationRequired', stderr.getvalue())
        self.assertIn('Uploaded 0; already present 0; failed 1.', stdout.getvalue())

    @override_settings(DEBUG=True)
    @patch('auction.management.commands.sync_media_to_cloudinary._cloudinary_sdk')
    def test_cloudinary_upload_api_failure_is_reported(self, sdk_factory):
        sdk = self._sdk(
            resource_error=NotFound('not found'),
            upload_error=AuthorizationRequired('upload denied'),
        )
        sdk_factory.return_value = sdk
        stdout, stderr = StringIO(), StringIO()

        with override_settings(MEDIA_ROOT=self.media_root):
            with self.assertRaises(CommandError):
                self._run_command(stdout, stderr)

        self.assertIn('AuthorizationRequired', stderr.getvalue())
        self.assertIn('Uploaded 0; already present 0; failed 1.', stdout.getvalue())
