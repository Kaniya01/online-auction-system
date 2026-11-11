from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from auction.storage import CloudinaryMediaStorage, cloudinary_public_id


class CloudinaryMediaStorageTests(SimpleTestCase):
    def test_public_id_preserves_path_and_distinguishes_extensions(self):
        self.assertEqual(
            cloudinary_public_id('product_images/cycle.jpeg'),
            'product_images/cycle__jpeg',
        )
        self.assertNotEqual(
            cloudinary_public_id('product_images/item.jpg'),
            cloudinary_public_id('product_images/item.png'),
        )

    @patch('auction.storage._cloudinary_sdk')
    def test_save_uploads_image_and_keeps_django_file_name(self, sdk_factory):
        sdk = SimpleNamespace(uploader=SimpleNamespace(upload=Mock()))
        sdk_factory.return_value = sdk
        storage = CloudinaryMediaStorage()

        saved_name = storage.save(
            'product_images/cycle.jpeg', ContentFile(b'image-bytes', name='cycle.jpeg')
        )

        self.assertRegex(saved_name, r'^product_images/[0-9a-f]{32}\.jpeg$')
        sdk.uploader.upload.assert_called_once()
        upload_options = sdk.uploader.upload.call_args.kwargs
        self.assertEqual(upload_options['public_id'], cloudinary_public_id(saved_name))
        self.assertEqual(upload_options['resource_type'], 'image')
        self.assertFalse(upload_options['overwrite'])

    @patch('auction.storage._cloudinary_sdk')
    def test_url_uses_cloudinary_id_for_existing_field_name(self, sdk_factory):
        utils = SimpleNamespace(cloudinary_url=Mock(return_value=('https://cdn.example/image', {})))
        sdk_factory.return_value = SimpleNamespace(utils=utils)

        url = CloudinaryMediaStorage().url('profile_pictures/meow.jpg')

        self.assertEqual(url, 'https://cdn.example/image')
        utils.cloudinary_url.assert_called_once_with(
            'profile_pictures/meow__jpg', secure=True
        )

    @patch('auction.storage._cloudinary_sdk')
    def test_missing_cloudinary_resource_is_reported_as_absent(self, sdk_factory):
        from cloudinary.exceptions import NotFound

        api = SimpleNamespace(resource=Mock(side_effect=NotFound('not found')))
        sdk_factory.return_value = SimpleNamespace(api=api)

        self.assertFalse(CloudinaryMediaStorage().exists('product_images/cycle.jpeg'))
