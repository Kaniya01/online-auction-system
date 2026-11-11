"""Django storage backend for production image uploads to Cloudinary."""

from io import BytesIO
import os
from pathlib import PurePosixPath
from urllib.request import urlopen
from uuid import uuid4

from django.conf import settings
from django.core.files import File
from django.core.files.storage import Storage
from django.core.exceptions import ImproperlyConfigured
from django.utils.deconstruct import deconstructible


def cloudinary_public_id(name):
    """Create an extension-aware ID that remains stable for old media names."""
    normalized = name.replace('\\', '/')
    stem, extension = os.path.splitext(normalized)
    return f'{stem}__{extension[1:].lower()}' if extension else stem


def _cloudinary_sdk():
    """Load and configure Cloudinary lazily so local development stays local."""
    try:
        import cloudinary
        import cloudinary.api  # noqa: F401
        import cloudinary.uploader  # noqa: F401
        import cloudinary.utils  # noqa: F401
    except ImportError as exc:
        raise ImproperlyConfigured(
            'Install the pinned cloudinary package to use production image storage.'
        ) from exc

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    return cloudinary


def _is_cloudinary_not_found(exc):
    """Only recognize Cloudinary's explicit missing-asset API response."""
    try:
        from cloudinary.exceptions import NotFound
    except ImportError:
        return False
    return isinstance(exc, NotFound)


@deconstructible
class CloudinaryMediaStorage(Storage):
    """Store ImageField files remotely while retaining Django's file API."""

    def get_available_name(self, name, max_length=None):
        # A random public ID avoids collisions without an Admin API lookup for
        # every upload. Keep the upload_to directory and original extension.
        path = PurePosixPath(name.replace('\\', '/'))
        filename = f'{uuid4().hex}{path.suffix.lower()}'
        available_name = str(path.parent / filename) if str(path.parent) != '.' else filename
        if max_length and len(available_name) > max_length:
            raise ValueError('The generated Cloudinary image name exceeds max_length.')
        return available_name

    def _save(self, name, content):
        sdk = _cloudinary_sdk()
        sdk.uploader.upload(
            content,
            public_id=cloudinary_public_id(name),
            resource_type='image',
            overwrite=False,
            unique_filename=False,
        )
        return name

    def _open(self, name, mode='rb'):
        if mode not in ('rb', 'r'):
            raise ValueError('Cloudinary media files can only be opened for reading.')
        with urlopen(self.url(name), timeout=20) as response:
            return File(BytesIO(response.read()), name=name)

    def url(self, name):
        sdk = _cloudinary_sdk()
        return sdk.utils.cloudinary_url(cloudinary_public_id(name), secure=True)[0]

    def exists(self, name):
        sdk = _cloudinary_sdk()
        try:
            sdk.api.resource(cloudinary_public_id(name), resource_type='image')
        except Exception as exc:
            if _is_cloudinary_not_found(exc):
                return False
            raise
        return True

    def delete(self, name):
        sdk = _cloudinary_sdk()
        sdk.uploader.destroy(
            cloudinary_public_id(name), resource_type='image', invalidate=True
        )

    def size(self, name):
        sdk = _cloudinary_sdk()
        return sdk.api.resource(
            cloudinary_public_id(name), resource_type='image'
        )['bytes']
