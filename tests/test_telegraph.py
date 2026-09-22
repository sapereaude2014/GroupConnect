"""Tests for Telegraph table rendering (fullwidth preformatted code cards)."""

import asyncio
import unicodedata
import unittest
from unittest.mock import AsyncMock, patch

from groupconnect.core import telegraph as tg
from groupconnect.core.telegraph import (
    _to_fullwidth,
    has_markdown_table,
    markdown_to_nodes,
    table_rows_to_preformatted_text,
)


def _is_em_width(ch: str) -> bool:
    """True if the glyph is guaranteed to advance exactly 1em in CJK fonts."""
    if ch in "\u3000\uff5c\uff0b\uff0d":
        return True
    return unicodedata.east_asian_width(ch) in ("W", "F")


class TestFullwidthConversion(unittest.TestCase):
    def test_ascii_maps_to_fullwidth(self):
        self.assertEqual(_to_fullwidth("A1.5"), "Ａ１．５")
        self.assertEqual(_to_fullwidth("a b"), "ａ\u3000ｂ")
        self.assertEqual(_to_fullwidth("()"), "（）")

    def test_cjk_passthrough(self):
        self.assertEqual(_to_fullwidth("中文"), "中文")

    def test_mixed_cjk_numbers_alignment(self):
        text = table_rows_to_preformatted_text(
            ["项目", "金额(元)", "备注"],
            [
                ["生鲜采购", "486.5", "示例数据"],
                ["水电燃气", "312.0", "示例数据"],
                ["合计", "798.5", "示例数据"],
            ],
        )
        lines = text.split("\n")
        self.assertEqual(len(lines), 5)  # header + separator + 3 rows
        for line in lines:
            self.assertTrue(all(_is_em_width(c) for c in line), f"non-1em char in: {line!r}")
        # identical code-point length on every line == pixel-perfect alignment
        self.assertEqual(len({len(l) for l in lines}), 1)
        self.assertIn("｜", lines[0])
        self.assertIn("＋", lines[1])
        self.assertIn("４８６", lines[2])

    def test_ragged_rows_normalized(self):
        text = table_rows_to_preformatted_text(
            ["A", "B"], [["x"], ["y", "z", "extra"]]
        )
        self.assertEqual(len({len(l) for l in text.split("\n")}), 1)

    def test_empty_table(self):
        self.assertEqual(table_rows_to_preformatted_text([], []), "")
        self.assertEqual(table_rows_to_preformatted_text(["a"], []), "")

    def test_table_cell_wrapping_alignment(self):
        headers = ["目录", "归档范围"]
        data_rows = [
            [
                "01_家庭成员档案/",
                "每人一份基础档案（身份、称呼、工作地点、设备绑定、权限、生活习惯、长期偏好）+ 双人合画像",
            ],
            ["02_健康与医疗/", "体检报告、健康台账、饮食调理方案、就医记录"],
        ]
        text = table_rows_to_preformatted_text(headers, data_rows, max_col_width=14)
        lines = text.split("\n")
        # Ensure row wrapping occurred:
        # Header (1) + Sep (1) + Row 1 (4 lines) + Sep (1) + Row 2 (2 lines) = 9 lines
        self.assertGreater(len(lines), 4)
        # All lines strictly equal length (pixel-perfect alignment)
        self.assertEqual(len({len(l) for l in lines}), 1)
        # All characters are 1em em-width characters
        for line in lines:
            self.assertTrue(all(_is_em_width(c) for c in line), f"non-1em char in: {line!r}")
        self.assertIn("＋", text)
        self.assertIn("｜", text)

    def test_table_custom_max_col_width(self):
        headers = ["项目", "描述"]
        data_rows = [["A", "1234567890abcdefghij"]]
        # With max_col_width=8, description column must be capped at 8
        text = table_rows_to_preformatted_text(headers, data_rows, max_col_width=8)
        lines = text.split("\n")
        self.assertEqual(len({len(l) for l in lines}), 1)
        # Check that header line length is 2 (header '项目') + 1 ('｜') + 8 = 11
        self.assertEqual(len(lines[0]), 11)


class TestMarkdownTableToPreNode(unittest.TestCase):
    def test_markdown_table_becomes_pre_node(self):
        md = "前言段落。\n\n| 项目 | 金额 |\n| --- | --- |\n| 生鲜 | 486.5 |\n"
        nodes = markdown_to_nodes(md)
        pres = [n for n in nodes if isinstance(n, dict) and n.get("tag") == "pre"]
        self.assertEqual(len(pres), 1)
        content = pres[0]["children"][0]
        self.assertIn("生鲜", content)
        self.assertIn("４８６．５", content)
        lines = content.split("\n")
        self.assertEqual(len({len(l) for l in lines}), 1)
        self.assertTrue(all(_is_em_width(c) for l in lines for c in l))

    def test_has_markdown_table(self):
        self.assertTrue(has_markdown_table("| a | b |\n| --- | --- |\n| 1 | 2 |\n"))
        self.assertFalse(has_markdown_table("plain text only"))


class TestOutboundTableRouting(unittest.IsolatedAsyncioTestCase):
    TABLE_MD = "| 方案 | 状态 |\n| --- | --- |\n| 黑底代码块 | 已上线 |\n开场摘要一句。"

    async def test_short_table_stays_in_chat_as_monospace(self):
        # Under threshold: body stays in chat; table rendered as monospace code
        # block (Telegram has no native table support).
        with patch.object(
            tg, "publish_to_telegraph", AsyncMock(return_value="https://telegra.ph/y")
        ) as mock_pub:
            out = await tg.process_outbound_text(self.TABLE_MD, threshold=60)
        mock_pub.assert_not_awaited()
        self.assertIn("```", out)
        self.assertIn("│", out)

    async def test_long_table_goes_to_telegraph(self):
        # Over threshold: whole body (tables included) is one Telegraph page.
        long_md = self.TABLE_MD + "补充说明文字。" * 10
        with patch.object(
            tg, "publish_to_telegraph", AsyncMock(return_value="https://telegra.ph/x")
        ) as mock_pub:
            out = await tg.process_outbound_text(long_md, threshold=60)
        mock_pub.assert_awaited_once()
        self.assertIn("📄 [", out)
        self.assertIn("https://telegra.ph/x", out)

    async def test_telegraph_disabled_falls_back_inline(self):
        with patch.object(tg, "publish_to_telegraph", AsyncMock()) as mock_pub:
            out = await tg.process_outbound_text(self.TABLE_MD, threshold=0)
        mock_pub.assert_not_awaited()
        self.assertIn("```", out)

    async def test_publish_failure_falls_back_blockquote_escaped(self):
        # Over threshold + publish failure -> expandable blockquote whose body
        # is HTML-entity-escaped so Telegram HTML parsing cannot break.
        long_md = self.TABLE_MD + "含<b>标签</b>和&符号的正文。" * 5
        with patch.object(
            tg, "publish_to_telegraph", AsyncMock(return_value=None)
        ) as mock_pub:
            out = await tg.process_outbound_text(long_md, threshold=60)
        mock_pub.assert_awaited_once()
        self.assertIn("<blockquote expandable>", out)
        self.assertIn("&lt;b&gt;", out)
        self.assertIn("&amp;", out)

    async def test_long_text_without_table_still_telegraph(self):
        long_text = "这是很长的一段文字" * 20
        with patch.object(
            tg, "publish_to_telegraph", AsyncMock(return_value="https://telegra.ph/z")
        ):
            out = await tg.process_outbound_text(long_text, threshold=60)
        self.assertIn("https://telegra.ph/z", out)

if __name__ == "__main__":
    unittest.main()
