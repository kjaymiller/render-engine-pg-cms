# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[CalVer](https://calver.org/) (`YYYY.MINOR.PATCH`) versioning derived from git
tags via setuptools-scm. Releases prior to `2026.7.10` are recorded only as git
tags / GitHub releases.

## [2026.7.10] - 2026-07-26

### Added
- HEIC/HEIF upload support. Uploaded iPhone photos are now decoded via
  `pillow-heif` and transcoded to WebP through the existing optimize pipeline
  (downscale to 2200px, strip EXIF/GPS). The raw HEIC is never stored — if a
  file fails to decode, it falls through to the blob-storage content-type
  allow-list and is rejected rather than persisted.

### Changed
- `image_optimize` now emits WebP (not JPEG) for opaque HEIC/HEIF sources;
  existing WebP uploads still stay WebP, and other opaque images (JPEG/PNG)
  continue to encode to JPEG.
