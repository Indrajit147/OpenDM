"""The .ico file for the executables and the installer, written from the app icon."""

import struct
from pathlib import Path

from opendm.gui.icons import ICO_SIZES, write_ico

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_write_ico(qapp, tmp_path: Path) -> None:
    path = write_ico(tmp_path / "app.ico")
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data)
    assert (reserved, kind, count) == (0, 1, len(ICO_SIZES))
    sizes = []
    for i in range(count):
        w, h, _, _, planes, bpp, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        size = w or 256  # 0 means 256
        assert (h or 256) == size and planes == 1 and bpp == 32
        assert data[offset : offset + 8] == PNG_MAGIC
        assert offset + length <= len(data)
        sizes.append(size)
    assert sizes == list(ICO_SIZES)
    assert 16 in sizes and 256 in sizes
