"""Copy existing local uploads to Cloudinary without changing database names."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from auction.storage import _cloudinary_sdk, _is_cloudinary_not_found, cloudinary_public_id


class Command(BaseCommand):
    help = 'Upload existing MEDIA_ROOT files to Cloudinary, preserving their Django names.'

    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.is_dir():
            raise CommandError(f'MEDIA_ROOT does not exist: {media_root}')

        sdk = _cloudinary_sdk()
        uploaded = 0
        skipped = 0
        failures = []

        for path in sorted(media_root.rglob('*')):
            if not path.is_file():
                continue

            name = path.relative_to(media_root).as_posix()
            public_id = cloudinary_public_id(name)
            try:
                sdk.api.resource(public_id, resource_type='image')
            except Exception as exc:
                if not _is_cloudinary_not_found(exc):
                    failures.append(name)
                    self.stderr.write(f'Could not check {name}: {type(exc).__name__}')
                    continue
            else:
                skipped += 1
                continue

            try:
                sdk.uploader.upload(
                    str(path),
                    public_id=public_id,
                    resource_type='image',
                    overwrite=False,
                    unique_filename=False,
                )
                uploaded += 1
                self.stdout.write(f'Uploaded {name}')
            except Exception as exc:
                failures.append(name)
                self.stderr.write(f'Could not upload {name}: {type(exc).__name__}')

        self.stdout.write(f'Uploaded {uploaded}; already present {skipped}; failed {len(failures)}.')
        if failures:
            raise CommandError('Some media files were not synchronized; see the filenames above.')
