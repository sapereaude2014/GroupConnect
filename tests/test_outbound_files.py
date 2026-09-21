import os
import tempfile
import unittest
from groupconnect.engine import _extract_outbound_files, _strip_sendfile_tags


class TestOutboundFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace = self.tmpdir.name

        # Create sample files
        self.sample_report = os.path.join(self.workspace, "sample_report.pdf")
        with open(self.sample_report, "w", encoding="utf-8") as f:
            f.write("dummy report content")

        self.sample_code = os.path.join(self.workspace, "code.py")
        with open(self.sample_code, "w", encoding="utf-8") as f:
            f.write("print('hello')")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_extract_explicit_chinese_bracket_tag(self):
        text = f"这是导出的报表：\n【SendFile: {self.sample_report} | 9月开支报表】"
        files = _extract_outbound_files(text, self.workspace)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0][0], self.sample_report)
        self.assertEqual(files[0][1], "9月开支报表")

    def test_extract_explicit_english_bracket_tag(self):
        text = f"Here is the file: [SendFile: {self.sample_report}]"
        files = _extract_outbound_files(text, self.workspace)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0][0], self.sample_report)
        self.assertIsNone(files[0][1])

    def test_extract_chinese_alias_tag(self):
        text = f"请查收：【发文件: {self.sample_report} | 附件台账】"
        files = _extract_outbound_files(text, self.workspace)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0][0], self.sample_report)
        self.assertEqual(files[0][1], "附件台账")

    def test_markdown_links_not_extracted(self):
        # Crucial regression test: markdown file links should NOT trigger file upload
        text = f"你可以参考模块实现：[{os.path.basename(self.sample_code)}](file://{self.sample_code})"
        files = _extract_outbound_files(text, self.workspace)
        self.assertEqual(len(files), 0, "Markdown file links must not trigger file upload")

    def test_bare_file_uri_not_extracted(self):
        # Crucial regression test: bare file:// URIs should NOT trigger file upload
        text = f"日志位于：file://{self.sample_report}"
        files = _extract_outbound_files(text, self.workspace)
        self.assertEqual(len(files), 0, "Bare file:// URIs must not trigger file upload")

    def test_nonexistent_file_ignored(self):
        text = "【SendFile: /non/existent/path/file.pdf】"
        files = _extract_outbound_files(text, self.workspace)
        self.assertEqual(len(files), 0)

    def test_strip_sendfile_tags(self):
        raw = f"报告已生成完毕。\n【SendFile: {self.sample_report} | 9月开支报表】\n请蓉总和小马查阅。"
        stripped = _strip_sendfile_tags(raw)
        self.assertNotIn("SendFile", stripped)
        self.assertIn("报告已生成完毕。", stripped)
        self.assertIn("请蓉总和小马查阅。", stripped)


if __name__ == "__main__":
    unittest.main()
