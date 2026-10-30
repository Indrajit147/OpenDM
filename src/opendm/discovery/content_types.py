"""Content-Type to file extension mapping.

Our own table rather than ``mimetypes``: on Windows that module reads the registry,
so results would differ between machines.
"""

_EXTENSIONS: dict[str, str] = {
    # archives
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/gzip": ".gz",
    "application/x-gzip": ".gz",
    "application/x-7z-compressed": ".7z",
    "application/vnd.rar": ".rar",
    "application/x-rar-compressed": ".rar",
    "application/x-tar": ".tar",
    "application/x-bzip2": ".bz2",
    "application/x-xz": ".xz",
    "application/x-iso9660-image": ".iso",
    # programs
    "application/x-msdownload": ".exe",
    "application/vnd.microsoft.portable-executable": ".exe",
    "application/x-msi": ".msi",
    "application/x-ms-installer": ".msi",
    "application/vnd.android.package-archive": ".apk",
    # documents
    "application/pdf": ".pdf",
    "application/epub+zip": ".epub",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/json": ".json",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "text/plain": ".txt",
    "text/html": ".html",
    "text/csv": ".csv",
    # images
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
    # audio
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    # video and streaming manifests
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/mp2t": ".ts",
    "application/vnd.apple.mpegurl": ".m3u8",
    "application/x-mpegurl": ".m3u8",
    "application/dash+xml": ".mpd",
}


def parse_content_type(value: str | None) -> str:
    """Media type without parameters, lowercased; empty string if missing."""
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def extension_for(content_type: str | None) -> str:
    """Extension (with dot) for a Content-Type, or empty string if unknown/generic."""
    return _EXTENSIONS.get(parse_content_type(content_type), "")
