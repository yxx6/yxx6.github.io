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

    def test_daily_report_content_lines_do_not_end_with_truncated_phrases(self) -> None:
        sentence_endings = ("。", "！", "？", ".", "!", "?", "”", '"', "）", ")", "`")

        for path in Path("_posts").glob("*-daily-report.md"):
            lines = path.read_text(encoding="utf-8").splitlines()

            for index, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped == "---":
                    continue
                if stripped.startswith(
                    (
                        "layout:",
                        "title:",
                        "date:",
                        "permalink:",
                        "paper_count:",
                        "share:",
                        "related:",
                        "read_time:",
                        "comments:",
                        "topics:",
                        "##",
                        "###",
                        "<div",
                        "</div",
                    )
                ):
                    continue
                if stripped.startswith("  - "):
                    continue
                if stripped.startswith("**") and stripped.endswith("**"):
                    continue

                if stripped.endswith("："):
                    next_non_empty = ""
                    for candidate in lines[index + 1:]:
                        candidate = candidate.strip()
                        if candidate:
                            next_non_empty = candidate
                            break

                    if next_non_empty.startswith(("- ", "1.", "2.", "3.", "4.", "5.")):
                        continue

                self.assertTrue(
                    stripped.endswith(sentence_endings),
                    f"{path.as_posix()} has a suspiciously truncated line: {stripped}",
                )


if __name__ == "__main__":
    unittest.main()
