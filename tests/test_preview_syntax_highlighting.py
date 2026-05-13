import unittest

from PySide6.QtGui import QTextDocument

from cdmw.ui.widgets import PreviewSyntaxHighlighter


def _formatted_fragments(text: str, extension: str) -> list[str]:
    document = QTextDocument()
    highlighter = PreviewSyntaxHighlighter(document, "graphite")
    highlighter.set_language_for_extension(extension)
    document.setPlainText(text)
    highlighter.rehighlight()

    fragments: list[str] = []
    block = document.firstBlock()
    while block.isValid():
        block_text = block.text()
        for format_range in block.layout().formats():
            fragments.append(block_text[format_range.start : format_range.start + format_range.length])
        block = block.next()
    return fragments


class PreviewSyntaxHighlightingTests(unittest.TestCase):
    def test_plain_hkx_preview_summary_gets_generic_coloring(self) -> None:
        fragments = _formatted_fragments(
            "\n".join(
                [
                    "HKX tagfile preview for object/03_cube.hkx",
                    "",
                    "Format summary:",
                    "- Declared size: 1,928 bytes",
                    "- TAG0: offset 4, flags=0x40000000",
                    "hknpShapeInstance",
                ]
            ),
            ".hkx",
        )

        self.assertIn("object/03_cube.hkx", fragments)
        self.assertIn("Format summary:", fragments)
        self.assertIn("Declared size:", fragments)
        self.assertIn("1,928", fragments)
        self.assertIn("flags", fragments)
        self.assertIn("0x40000000", fragments)
        self.assertIn("hknpShapeInstance", fragments)

    def test_unknown_text_preview_uses_generic_coloring(self) -> None:
        fragments = _formatted_fragments(
            "\n".join(
                [
                    "Preview Diagnostics",
                    "source=character/texture/item_diffuse.dds",
                    "Status: ready",
                ]
            ),
            ".unknown",
        )

        self.assertIn("source", fragments)
        self.assertIn("character/texture/item_diffuse.dds", fragments)
        self.assertIn("Status:", fragments)
        self.assertIn("ready", fragments)


if __name__ == "__main__":
    unittest.main()
