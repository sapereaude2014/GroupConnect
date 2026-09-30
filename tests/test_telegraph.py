"""Tests for Telegraph table rendering (fullwidth preformatted code cards)."""

import asyncio
import unicodedata
import unittest
from unittest.mock import AsyncMock, patch

from groupconnect.channels.extensions import telegraph as tg
from groupconnect.channels.extensions.telegraph import (
    _to_fullwidth,
    extract_first_paragraph,
    extract_title,
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

    async def test_first_paragraph_prepended_before_telegraph_link(self):
        intro = "核心结论：四道闹钟已全部撤销。"
        body = "详细执行日志说明：\n- 闹钟1: 07:00 已删除\n- 闹钟2: 07:30 已删除\n" * 5
        full_text = f"{intro}\n\n{body}"
        with patch.object(
            tg, "publish_to_telegraph", AsyncMock(return_value="https://telegra.ph/alarm123")
        ):
            out = await tg.process_outbound_text(full_text, threshold=60)
        self.assertTrue(out.startswith(intro))
        self.assertIn(f"{intro}\n📄 [", out)
        self.assertIn("https://telegra.ph/alarm123", out)


class TestExtractFirstParagraph(unittest.TestCase):
    def test_extract_paragraph_with_blank_line(self):
        text = "结论：任务已完成。\n\n详细步骤：\n1. 编译代码\n2. 运行测试"
        self.assertEqual(extract_first_paragraph(text), "结论：任务已完成。")

    def test_extract_paragraph_with_single_newline(self):
        text = "好的，这是查询结果：\n- 项目A\n- 项目B"
        self.assertEqual(extract_first_paragraph(text), "好的，这是查询结果：")

    def test_no_extract_for_table(self):
        text = "| 序号 | 名称 |\n| --- | --- |\n| 1 | 测试 |"
        self.assertEqual(extract_first_paragraph(text), "")

    def test_no_extract_for_code_block(self):
        text = "```python\nprint(1)\n```\n其余内容"
        self.assertEqual(extract_first_paragraph(text), "")

    def test_truncate_over_60_chars(self):
        text = "这是一段非常冗长的开篇引言说明文字，内容详实且完整地介绍了本次系统自动化重构的所有背景信息和各项校验指标，并且进行了多次验证。\n\n后续详情..."
        result = extract_first_paragraph(text)
        self.assertTrue(result.endswith("…"))
        # 60 chars + 1 ellipsis char
        self.assertEqual(len(result), 61)

    def test_no_newline_text_truncates_not_empty(self):
        text = "纯一段话没有任何换行，但是超过了六十个字，我们测试一下它会不会正常截断并加上省略号，而不是像之前一样直接返回空字符串。测试更多文字。"
        result = extract_first_paragraph(text)
        self.assertTrue(result.endswith("…"))
        self.assertEqual(len(result), 61)

    def test_skip_leading_headers_to_get_body_paragraph(self):
        text = "# 2026年三亚度假行程规划\n\n详细安排如下：抵达海棠湾入住酒店。\n\n第二天去蜈支洲岛。"
        self.assertEqual(extract_first_paragraph(text), "详细安排如下：抵达海棠湾入住酒店。")

    def test_strip_markdown_links_and_formatting_in_preview(self):
        text = "本总管方才特意调阅验真了小马哥（@Zheng Ma）的最新改动（[`489a7cce4e`](https://github.com/sapereaude2014/GroupConnect/commit/489a7cce4e27cf1009fc40348ccf64068540e7fe)），这版改得不仅巧妙，而且真正拿捏住了手机端阅读的“黄金屏占比”！\n\n后续详情..."
        result = extract_first_paragraph(text)
        # Markdown link syntax must be stripped and not cut in half
        self.assertNotIn("https://github.com", result)
        self.assertNotIn("[", result)
        self.assertNotIn("]", result)
        self.assertIn("489a7cce4e", result)
        self.assertTrue(result.endswith("…"))


class TestExtractTitle(unittest.TestCase):
    def test_extract_markdown_h1(self):
        text = "# 2026年三亚度假行程规划\n\n详细安排如下：\n- 第一天：抵达海棠湾"
        self.assertEqual(extract_title(text), "2026年三亚度假行程规划")

    def test_extract_markdown_h2(self):
        text = "## 家庭资产月度汇总与分析\n\n以下是本月开销表："
        self.assertEqual(extract_title(text), "家庭资产月度汇总与分析")

    def test_extract_bracketed_title(self):
        text = "【九月份家庭开支报表】\n\n本月合计支出 12,500 元。"
        self.assertEqual(extract_title(text), "九月份家庭开支报表")

    def test_extract_conversational_first_sentence(self):
        text = "已为您整理好相关调研数据，主要包括以下几个核心维度。"
        self.assertEqual(extract_title(text), "已为您整理好相关调研数据")

    def test_extract_fallback_on_empty(self):
        self.assertEqual(extract_title("", default_author="管家"), "管家 详细汇报")


if __name__ == "__main__":
    unittest.main()
