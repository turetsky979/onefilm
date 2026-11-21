# Changelog

All notable changes to this project are documented here.

## [1.0.0] - 2026-11-21

First public release.

### Added
- Baidu group file-library real-time search (`basembox/group/search`), no index, no full crawl.
- One-click download pipeline: transfer → OpenList direct link → curl resume download.
- Recursive folder download preserving videos, subtitles and artwork.
- Read-only folder browsing without creating temporary copies.
- Folder size display via Baidu `sharedir/file/dirsize`.
- Robust transfer-landing detection for nested paths and duplicate-name suffixes.
- Async task submission with live progress polling (2s).
- Per-task deletion and bulk clear of finished records.
- Auto cleanup of temporary transferred copies after a batch completes.
- OpenWrt/iStoreOS procd init script and generic Linux start script.
- Full documentation (install, configuration, cookie, API, architecture).

### Changed
- Replaced aria2 with curl (`-C -` resume, `pan.baidu.com` UA) for large-file stability.
- Removed login password (LAN-only design); kept legacy login/logout endpoints for compatibility.
- All paths made relative and overridable via environment variables.

### Security
- Credentials (`config.json`, `baidu_cookie.txt`) excluded via `.gitignore`.
- Signing constants moved into config template instead of hard-coded in source.
