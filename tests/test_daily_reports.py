from pathlib import Path
import re
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

    def test_daily_report_math_delimiters_are_kramdown_safe(self) -> None:
        for path in self._iter_daily_report_paths():
            text = path.read_text(encoding="utf-8")

            self.assertNotIn(r"\(", text, path.as_posix())
            self.assertNotIn(r"\)", text, path.as_posix())
            self.assertNotIn(r"\[", text, path.as_posix())
            self.assertNotIn(r"\]", text, path.as_posix())
            self.assertNotIn("|V|", text, path.as_posix())

    def test_daily_report_has_no_common_bare_formula_tokens(self) -> None:
        patterns = {
            "bare y_hat": r"\by_hat\b",
            "bare h^(...)": r"\bh\^\(",
            "bare h^z": r"\bh\^z\b",
            "bare single-letter subscript": r"\b[A-Za-z]_([A-Za-z0-9]+)\b",
            "bare single-letter superscript": r"\b[A-Za-z]\^\(",
            "bare exp weight": r"\b(?:omega|ω)\s*=\s*exp\s*\(",
            "bare alpha": r"(?<![A-Za-z])α(?![A-Za-z])",
            "bare beta": r"(?<![A-Za-z])β(?![A-Za-z])",
            "bare lambda": r"(?<![A-Za-z])λ(?![A-Za-z])",
            "bare eta": r"(?<![A-Za-z])η(?![A-Za-z])",
            "bare theta": r"(?<![A-Za-z])θ(?![A-Za-z])",
            "bare rho": r"(?<![A-Za-z])ρ(?![A-Za-z])",
            "bare phi": r"(?<![A-Za-z])φ(?![A-Za-z])",
            "bare omega": r"(?<![A-Za-z])ω(?![A-Za-z])",
            "bare tau": r"(?<![A-Za-z])τ(?![A-Za-z])",
            "inline-code formula": r"`[^`\n]*(?:y_hat|h\^|ω|τ|ŷ|exp\(|\^\(|_\{|[A-Za-z]_[A-Za-z])[^`\n]*`",
        }

        for path in self._iter_daily_report_paths():
            text = path.read_text(encoding="utf-8")
            text = re.sub(r"```.*?```", "", text, flags=re.S)
            text = re.sub(r"\$\$.*?\$\$", "", text, flags=re.S)
            text = re.sub(r"(?<!\$)\$(?!\$)[^$\n]+?(?<!\\)\$(?!\$)", "", text)

            for label, pattern in patterns.items():
                self.assertIsNone(
                    re.search(pattern, text),
                    f"{path.as_posix()} has {label}",
                )

    def test_daily_report_content_lines_do_not_end_with_truncated_phrases(self) -> None:
        sentence_endings = ("。", "！", "？", ".", "!", "?", "”", '"', "）", ")", "`", "**")

        for path in self._iter_daily_report_paths():
            lines = path.read_text(encoding="utf-8").splitlines()
            in_code_block = False
            in_math_block = False
            in_bracket_math_block = False

            for index, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if stripped == "$$":
                    in_math_block = not in_math_block
                    continue
                if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
                    continue
                if stripped == "\\[":
                    in_bracket_math_block = True
                    continue
                if stripped == "\\]":
                    in_bracket_math_block = False
                    continue
                if in_code_block:
                    continue
                if in_math_block:
                    continue
                if in_bracket_math_block:
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
                if stripped in {"$"}:
                    continue
                if stripped.startswith("\\"):
                    continue
                if stripped.startswith("<") and stripped.endswith(">"):
                    continue
                if stripped.endswith(("：", ":")):
                    continue
                if stripped.endswith(("——", "—")):
                    next_non_empty = ""
                    for candidate in lines[index + 1:]:
                        candidate = candidate.strip()
                        if candidate:
                            next_non_empty = candidate
                            break
                    if next_non_empty.startswith(("1.", "2.", "3.", "4.", "5.", "- ", "* ")):
                        continue

                self.assertTrue(
                    stripped.endswith(sentence_endings),
                    f"{path.as_posix()} has a suspiciously truncated line: {stripped}",
                )


if __name__ == "__main__":
    unittest.main()
