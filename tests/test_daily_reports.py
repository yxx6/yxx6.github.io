from pathlib import Path
import unittest


class DailyReportContentTests(unittest.TestCase):
    def _iter_daily_report_paths(self):
        yield from Path("_posts").glob("*-daily-report.md")
        yield from Path("daily").glob("*/index.md")

    def test_daily_report_front_matter_has_no_smart_quotes(self) -> None:
        for path in self._iter_daily_report_paths():
            text = path.read_text(encoding="utf-8")
            frontmatter = text.split("---", 2)[1]

            self.assertNotIn("“", frontmatter, path.as_posix())
            self.assertNotIn("”", frontmatter, path.as_posix())

    def test_daily_report_overview_paragraph_ends_cleanly(self) -> None:
        sentence_endings = ("。", "！", "？", ".", "!", "?")

        for path in self._iter_daily_report_paths():
            lines = path.read_text(encoding="utf-8").splitlines()
            overview_index = next(
                i for i, line in enumerate(lines) if line.strip() in {"## 今日概述", "## 今日概览"}
            )

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

        for path in self._iter_daily_report_paths():
            lines = path.read_text(encoding="utf-8").splitlines()
            in_code_block = False

            for index, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block:
                    continue
                if stripped == "---":
                    continue
                if stripped == "<!--more-->":
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
                        "excerpt:",
                        "excerpt_separator:",
                        "topics:",
                        "##",
                        "###",
                        "> ",
                        "|",
                    )
                ):
                    continue
                if stripped.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.")):
                    continue
                if stripped.startswith("  - "):
                    continue
                if stripped.startswith("**") and stripped.endswith("**"):
                    continue
                if stripped.startswith("- **") and stripped.endswith("**"):
                    continue
                if stripped in {"\\[", "\\]", "$$", "$"}:
                    continue
                if stripped.startswith("\\"):
                    continue

                if stripped.endswith("："):
                    next_non_empty = ""
                    for candidate in lines[index + 1:]:
                        candidate = candidate.strip()
                        if candidate:
                            next_non_empty = candidate
                            break

                    if next_non_empty.startswith(("- ", "1.", "2.", "3.", "4.", "5.", "\\[", "$$")):
                        continue

                self.assertTrue(
                    stripped.endswith(sentence_endings),
                    f"{path.as_posix()} has a suspiciously truncated line: {stripped}",
                )


if __name__ == "__main__":
    unittest.main()
