from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cdmw.constants import DEFAULT_UI_THEME
from cdmw.ui.themes import UI_THEME_SCHEMES


ASSETS_DIR = ROOT / "assets"
THEME_ICON_DIR = ASSETS_DIR / "theme_icons"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)


def _mix(left: QColor, right: QColor, amount: float) -> QColor:
    t = max(0.0, min(1.0, float(amount)))
    return QColor(
        round(left.red() * (1.0 - t) + right.red() * t),
        round(left.green() * (1.0 - t) + right.green() * t),
        round(left.blue() * (1.0 - t) + right.blue() * t),
    )


def _hex(color: QColor) -> str:
    return color.name(QColor.HexRgb)


def _valid_color(value: object, fallback: str) -> QColor:
    color = QColor(str(value or fallback))
    return color if color.isValid() else QColor(fallback)


def _relative_luminance(color: QColor) -> float:
    def channel(value: int) -> float:
        raw = value / 255.0
        return raw / 12.92 if raw <= 0.03928 else ((raw + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())


def _palette(theme_key: str) -> dict[str, str]:
    theme = UI_THEME_SCHEMES[theme_key]
    window = _valid_color(theme.get("window"), "#1e1e1e")
    surface = _valid_color(theme.get("surface"), "#252526")
    surface_alt = _valid_color(theme.get("surface_alt"), "#2d2d30")
    accent = _valid_color(theme.get("accent"), "#007acc")
    text = _valid_color(theme.get("text"), "#cccccc")
    muted = _valid_color(theme.get("text_muted"), "#9da0a6")
    light_theme = _relative_luminance(window) > 0.55

    if light_theme:
        bg0 = _mix(window, accent, 0.10).darker(104)
        bg1 = _mix(surface, accent, 0.18).darker(108)
        dark = _mix(text, QColor("#0b1220"), 0.62)
        top = _mix(surface_alt, accent, 0.28).darker(106)
        left = _mix(muted, accent, 0.18)
        active = accent.lighter(115)
        shadow_alpha = "0.16"
        highlight_alpha = "0.12"
    else:
        bg0 = _mix(window, QColor("#020711"), 0.28)
        bg1 = _mix(surface, accent, 0.14)
        dark = _mix(window, QColor("#020711"), 0.62)
        top = _mix(surface_alt, accent, 0.25).lighter(106)
        left = _mix(muted, accent, 0.18)
        active = accent.lighter(135)
        shadow_alpha = "0.20"
        highlight_alpha = "0.07"

    return {
        "bg0": _hex(bg0),
        "bg1": _hex(bg1),
        "dark": _hex(dark),
        "top": _hex(top),
        "left": _hex(left),
        "active0": _hex(active.lighter(115)),
        "active1": _hex(accent),
        "shadow_alpha": shadow_alpha,
        "highlight_alpha": highlight_alpha,
    }


def _svg(theme_key: str) -> str:
    p = _palette(theme_key)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{p['bg0']}"/>
      <stop offset="1" stop-color="{p['bg1']}"/>
    </linearGradient>
    <linearGradient id="active" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{p['active0']}"/>
      <stop offset="1" stop-color="{p['active1']}"/>
    </linearGradient>
  </defs>
  <rect x="118" y="132" width="840" height="840" rx="196" fill="#000000" opacity="0.10"/>
  <rect x="92" y="92" width="840" height="840" rx="196" fill="url(#bg)"/>
  <rect x="270" y="270" width="258" height="258" rx="64" fill="{p['dark']}"/>
  <rect x="496" y="270" width="258" height="258" rx="64" fill="{p['top']}"/>
  <rect x="270" y="496" width="258" height="258" rx="64" fill="{p['left']}"/>
  <rect x="496" y="496" width="258" height="258" rx="64" fill="url(#active)"/>
  <path d="M496 496h258v258H496z" fill="#000000" opacity="{p['shadow_alpha']}"/>
  <path d="M288 92h448q196 0 196 196v132H92V288q0-196 196-196z" fill="#ffffff" opacity="{p['highlight_alpha']}"/>
</svg>
"""


def _render_svg(svg_path: Path, png_path: Path, ico_path: Path) -> None:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid SVG: {svg_path}")
    images: list[QImage] = []
    for size in ICON_SIZES:
        image = QImage(QSize(size, size), QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        if size == 1024 and not image.save(str(png_path), "PNG"):
            raise RuntimeError(f"Could not save {png_path}")
        images.append(image)

    from PIL import Image

    ico_images = []
    for image in images:
        if image.width() > 256:
            continue
        ptr = image.bits()
        data = bytes(ptr[: image.sizeInBytes()])
        ico_images.append(Image.frombytes("RGBA", (image.width(), image.height()), data, "raw", "BGRA"))
    ico_images[-1].save(
        str(ico_path),
        sizes=[(image.width, image.height) for image in ico_images],
        append_images=ico_images[:-1],
    )


def generate(theme_keys: Iterable[str] = UI_THEME_SCHEMES.keys()) -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    _ = app
    THEME_ICON_DIR.mkdir(parents=True, exist_ok=True)
    for theme_key in theme_keys:
        if theme_key not in UI_THEME_SCHEMES:
            continue
        svg_path = THEME_ICON_DIR / f"cdmw_{theme_key}.svg"
        png_path = THEME_ICON_DIR / f"cdmw_{theme_key}.png"
        ico_path = THEME_ICON_DIR / f"cdmw_{theme_key}.ico"
        svg_path.write_text(_svg(theme_key), encoding="utf-8")
        _render_svg(svg_path, png_path, ico_path)
    default_svg = THEME_ICON_DIR / f"cdmw_{DEFAULT_UI_THEME}.svg"
    default_png = THEME_ICON_DIR / f"cdmw_{DEFAULT_UI_THEME}.png"
    default_ico = THEME_ICON_DIR / f"cdmw_{DEFAULT_UI_THEME}.ico"
    (ASSETS_DIR / "cdmw.svg").write_text(default_svg.read_text(encoding="utf-8"), encoding="utf-8")
    (ASSETS_DIR / "cdmw.png").write_bytes(default_png.read_bytes())
    (ASSETS_DIR / "cdmw.ico").write_bytes(default_ico.read_bytes())


if __name__ == "__main__":
    generate()
