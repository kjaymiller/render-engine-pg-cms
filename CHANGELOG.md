# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[CalVer](https://calver.org/) (`YYYY.MINOR.PATCH`) versioning derived from git
tags via setuptools-scm. Releases prior to `2026.7.10` are recorded only as git
tags / GitHub releases.

## [2026.11.0] - 2026-11-07

Performance release. Measured against the real (remote, Aiven) database, every
query ran in well under a millisecond — the felt slowness was network
round-trips and payload size. This release attacks both.

### Changed
- List and timeline reads no longer ship every post's full markdown body.
  `content` is truncated in SQL for bounded pages and dropped entirely for
  views that render no body (blog/notes timeline cards, plain-table list
  views). Tunable via `LIST_EXCERPT_CHARS`; internal/unbounded reads still
  get complete rows. On the live site `/c/microblog` fell from ~1.5 MB to
  ~79 KB and `/c/blog` from ~459 KB to ~45 KB.
- The timeline status tabs are one `UNION ALL` query instead of one `COUNT`
  per content type, and a page render shares a single database connection
  across its counts and list reads (the TLS handshake to a remote DB is
  ~200ms). `/` dropped from ~20 round-trips across 4+ connections to 4-7
  across one.
- The timeline is flatter: rail dots, pill badges, gradients, and hover
  lift removed in favour of a plain rule and cards.

### Added
- Every response carries an `X-Process-Time` header (milliseconds). Set
  `SLOW_REQUEST_MS` to also log requests at or above that threshold.
- `mise run explain` runs `EXPLAIN ANALYZE` against the real list/timeline
  statements (the diagnostic reuses `db.build_list_query`, so it can't
  drift from the app).

## [2026.8.0] - 2026-08-03

### Added
- The content editor keeps markdown reference-link definitions in sync. Writing
  `[link]`, `[text][ref]`, or `[text][]` appends a `[ref]:` stub to a
  definition block at the bottom of the content; definitions written elsewhere
  in the body are collected into that block. Renaming or deleting a reference
  drops its definition, and the URL is remembered for the session so retyping
  (or fixing a typo in) the reference restores it. Code fences, inline code,
  inline links/images, and task-list markers are ignored.

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
