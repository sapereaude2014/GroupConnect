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
        self.assertIn("项目", lines[0])
        self.assertIn("金额(元)", lines[0])
        self.assertTrue(all(c == "-" for c in lines[1]))
        # Numbers and English remain halfwidth ASCII
        self.assertIn("486.5", lines[2])
        self.assertIn("生鲜采购", lines[2])

    def test_ragged_rows_normalized(self):
        text = table_rows_to_preformatted_text(
            ["A", "B"], [["x"], ["y", "z", "extra"]]
        )
        lines = text.split("\n")
        self.assertEqual(len(lines), 4)
        self.assertTrue("A" in lines[0] and "B" in lines[0])
        self.assertTrue("y" in lines[3] and "z" in lines[3])

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
        self.assertGreater(len(lines), 4)
        self.assertIn("-", text)
        self.assertIn("01_家庭成员档", text)
        self.assertIn("02_健康与医疗/", text)

    def test_table_custom_max_col_width(self):
        headers = ["项目", "描述"]
        data_rows = [["A", "1234567890abcdefghij"]]
        # With max_col_width=8, description column must be capped at 8
        text = table_rows_to_preformatted_text(headers, data_rows, max_col_width=8)
        lines = text.split("\n")
        self.assertGreater(len(lines), 3)
        self.assertIn("12345678", lines[2])

    def test_display_width_and_wrapping(self):
        from groupconnect.channels.extensions.telegraph import _display_width, _wrap_cell
        self.assertEqual(_display_width("abc"), 3)
        self.assertEqual(_display_width("测试"), 4)
        self.assertEqual(_display_width("✅"), 2)
        # Word-boundary wrapping: does not cut English word in middle if possible
        chunks = _wrap_cell("allow_open_access test", 18)
        self.assertEqual(chunks, ["allow_open_access", "test"])

    def test_mobile_golden_width_budget_and_separator_tail(self):
        from groupconnect.channels.extensions.telegraph import _display_width
        headers = ["目录", "归档范围"]
        data_rows = [
            ["01_家庭成员档案/", "每人一份基础档案（身份、称呼、工作地点、设备绑定、权限、生活习惯、长期偏好）+ 双人合画像"],
            ["02_健康与医疗/", "体检报告、健康台账、饮食调理方案、就医记录"],
        ]
        text = table_rows_to_preformatted_text(headers, data_rows)
        lines = text.split("\n")
        # Line width on mobile must not exceed 36 chars to avoid horizontal scrolling
        max_w = max(_display_width(l) for l in lines)
        self.assertLessEqual(max_w, 36)
        # Separator line length matches max line length closely
        sep_lines = [l for l in lines if all(c == "-" for c in l)]
        self.assertTrue(len(sep_lines) > 0)
        self.assertEqual(_display_width(sep_lines[0]), max_w)


class TestMarkdownTableToPreNode(unittest.TestCase):
    def test_markdown_table_becomes_pre_node(self):
        md = "前言段落。\n\n| 项目 | 金额 |\n| --- | --- |\n| 生鲜 | 486.5 |\n"
        nodes = markdown_to_nodes(md)
        pres = [n for n in nodes if isinstance(n, dict) and n.get("tag") == "pre"]
        self.assertEqual(len(pres), 1)
        content = pres[0]["children"][0]
        self.assertIn("生鲜", content)
        self.assertIn("486.5", content)
        self.assertIn("-", content)

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
        self.assertIn("方案", out)
        self.assertIn("已上线", out)

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


class TestTelegraphAutolink(unittest.TestCase):
    def test_bare_url_autolinked(self):
        text = "全文：https://telegra.ph/morning-brief-1001 请查收"
        nodes = markdown_to_nodes(text)
        # Should have an 'a' tag node with correct href and children
        p_node = nodes[0]
        self.assertEqual(p_node["tag"], "p")
        a_nodes = [c for c in p_node["children"] if isinstance(c, dict) and c.get("tag") == "a"]
        self.assertEqual(len(a_nodes), 1)
        self.assertEqual(a_nodes[0]["attrs"]["href"], "https://telegra.ph/morning-brief-1001")
        self.assertEqual(a_nodes[0]["children"], ["https://telegra.ph/morning-brief-1001"])
        # Check text before and after is not truncated
        self.assertIn("全文：", p_node["children"])
        self.assertIn(" 请查收", p_node["children"])

    def test_chinese_punctuation_preserved_outside_link(self):
        text = "链接：https://telegra.ph/test-slug。还有：https://github.com/repo，请查看！"
        nodes = markdown_to_nodes(text)
        p_node = nodes[0]
        a_nodes = [c for c in p_node["children"] if isinstance(c, dict) and c.get("tag") == "a"]
        self.assertEqual(len(a_nodes), 2)
        self.assertEqual(a_nodes[0]["attrs"]["href"], "https://telegra.ph/test-slug")
        self.assertEqual(a_nodes[1]["attrs"]["href"], "https://github.com/repo")
        self.assertIn("。还有：", p_node["children"])
        self.assertIn("，请查看！", p_node["children"])

    def test_urls_in_code_blocks_not_linked(self):
        text = "```\nhttps://example.com/code\n```"
        nodes = markdown_to_nodes(text)
        self.assertEqual(nodes[0]["tag"], "pre")
        # In pre/code tag, no 'a' tag should be created
        code_tag = nodes[0]["children"][0]
        self.assertEqual(code_tag["tag"], "code")
        self.assertIn("https://example.com/code", code_tag["children"][0])

    def test_existing_markdown_links_not_double_wrapped(self):
        text = "[官方文档](https://telegra.ph/official-doc)"
        nodes = markdown_to_nodes(text)
        p_node = nodes[0]
        a_nodes = [c for c in p_node["children"] if isinstance(c, dict) and c.get("tag") == "a"]
        self.assertEqual(len(a_nodes), 1)
        self.assertEqual(a_nodes[0]["attrs"]["href"], "https://telegra.ph/official-doc")
        self.assertEqual(a_nodes[0]["children"], ["官方文档"])


class TestVoidTagNestingFix(unittest.TestCase):
    def test_br_in_table_does_not_swallow_subsequent_content(self):
        text = """| 标题 | 内容 |
| --- | --- |
| 项目 | 规则<br>• 说明一<br>• 说明二 |

---

💡 **今日温馨提醒**：
1. **下班时间**：建议 18:02 离岗；
2. **爱车别忘了**：去三林东站接车！"""
        nodes = markdown_to_nodes(text)
        last_node = nodes[-1]
        self.assertEqual(last_node["tag"], "p")
        # Ensure 'br' is never a container with children
        for child in last_node["children"]:
            if isinstance(child, dict) and child.get("tag") == "br":
                self.assertNotIn("children", child)
        # Ensure all reminder texts exist
        full_text_in_node = str(last_node)
        self.assertIn("今日温馨提醒", full_text_in_node)
        self.assertIn("下班时间", full_text_in_node)
        self.assertIn("爱车别忘了", full_text_in_node)


class TestPublishRetry(unittest.IsolatedAsyncioTestCase):
    async def test_publish_retries_on_network_failure(self):
        with patch("groupconnect.channels.extensions.telegraph.get_or_create_telegraph_token", return_value="fake_token"):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__.return_value = mock_client
                mock_success_res = unittest.mock.MagicMock()
                mock_success_res.json.return_value = {"ok": True, "result": {"url": "https://telegra.ph/test-url"}}
                mock_client.post.side_effect = [Exception("Connection reset"), mock_success_res]

                with patch("asyncio.sleep", new_callable=AsyncMock):
                    url = await tg.publish_to_telegraph("hello world", title="test")
                self.assertEqual(url, "https://telegra.ph/test-url")
                self.assertEqual(mock_client.post.call_count, 2)

    async def test_publish_fails_after_two_attempts(self):
        with patch("groupconnect.channels.extensions.telegraph.get_or_create_telegraph_token", return_value="fake_token"):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__.return_value = mock_client
                mock_client.post.side_effect = [Exception("Connection error 1"), Exception("Connection error 2")]

                with patch("asyncio.sleep", new_callable=AsyncMock):
                    url = await tg.publish_to_telegraph("hello world", title="test")
                self.assertIsNone(url)
                self.assertEqual(mock_client.post.call_count, 2)


if __name__ == "__main__":
    unittest.main()

