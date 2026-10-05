"""
Render tools/icon.svg into the app icon files.

    python tools/make_icon.py

Writes web/favicon.ico and web/icon.png (used by the app window and the
browser tab) and tools/icon.ico (used by build_exe.py). Needs PySide6 only
for the drawing.
"""

import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(svg_path, size):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    renderer = QSvgRenderer(str(svg_path))
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    return bytes(data)


def write_ico(path, pngs):
    """An .ico file that holds PNG images (supported since Windows Vista)."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = b"", b""
    for size, png in pngs:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    path.write_bytes(header + entries + blobs)


def main():
    svg = HERE / "icon.svg"
    pngs = [(s, render(svg, s)) for s in SIZES]
    write_ico(HERE / "icon.ico", pngs)
    write_ico(ROOT / "web" / "favicon.ico", pngs)
    (ROOT / "web" / "icon.png").write_bytes(pngs[-1][1])
    print("wrote tools/icon.ico, web/favicon.ico, web/icon.png")


if __name__ == "__main__":
    main()
