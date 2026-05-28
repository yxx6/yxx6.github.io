from pathlib import Path
import unittest


class DailyReportContentTests(unittest.TestCase):
    def test_daily_report_front_matter_has_no_smart_quotes(self) -> None:
        for path in Path("_posts").glob("*-daily-report.md"):
            text = path.read_text(encoding="utf-8")
            frontmatter = text.split("---", 2)[1]

            self.assertNotIn("“", frontmatter, path.as_posix())
            self.assertNotIn("”", frontmatter, path.as_posix())

    def test_daily_report_overview_paragraph_ends_cleanly(self) -> None:
        sentence_endings = ("。", "！", "？", ".", "!", "?")

        for path in Path("_posts").glob("*-daily-report.md"):
            lines = path.read_text(encoding="utf-8").splitlines()
            overview_index = lines.index("## 今日概述")

            paragraph = ""
            for line in lines[overview_index + 1:]:
                stripped = line.strip()
                if stripped:
                    paragraph = stripped
                    break

            self.assertTrue(paragraph, path.as_posix())
            self.assertTrue(
                paragraph.endswith(sentence_endings),
                f"{path.as_posix()} has a truncated overview paragraph",
            )


if __name__ == "__main__":
    unittest.main()
