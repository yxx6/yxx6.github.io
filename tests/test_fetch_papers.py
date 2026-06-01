import datetime
import unittest
from types import SimpleNamespace
from unittest import mock

import fetch_papers


def _build_entry(arxiv_id: str, published: str, title: str) -> str:
    return f"""
    <entry>
      <id>http://arxiv.org/abs/{arxiv_id}</id>
      <published>{published}T00:00:00Z</published>
      <title>{title}</title>
      <summary>{title} abstract</summary>
      <author><name>Test Author</name></author>
      <category term="cs.IR" />
    </entry>
    """


class FetchArxivTests(unittest.TestCase):
    def test_complete_text_heuristic_rejects_half_sentence(self) -> None:
        self.assertFalse(fetch_papers._looks_like_complete_text("这是一个还没写完的结论，因为"))
        self.assertFalse(fetch_papers._looks_like_complete_text("> **关键洞察**："))
        self.assertTrue(fetch_papers._looks_like_complete_text("这是一个完整结论。"))
        self.assertTrue(
            fetch_papers._looks_like_complete_text("> **一句话总结**：这是一句完整总结。")
        )

    def test_clean_generated_markdown_fixes_common_format_glitches(self) -> None:
        raw = "\n".join(
            [
                "## 二、核心方法",
                "**",
                "",
                "**主要风险**：需要更多验证",
                "",
                "，实际部署前需先灰度验证。",
                "",
                "**解决的问题**：使用未来交互",
                "",
                "**为什么有效**：用熵控制未来监督强度。",
                "",
                "| ML-20",
                "| 数据集 | 指标 |",
                "|--------|------|",
            ]
        )

        cleaned = fetch_papers._clean_generated_markdown(raw)

        self.assertNotIn("\n**\n", cleaned)
        self.assertIn("**主要风险**：需要更多验证，实际部署前需先灰度验证。", cleaned)
        self.assertNotIn("**解决的问题**：使用未来交互", cleaned)
        self.assertNotIn("| ML-20", cleaned)
        self.assertIn("| 数据集 | 指标 |", cleaned)

    def test_get_default_target_date_uses_report_timezone(self) -> None:
        now = datetime.datetime(2026, 5, 31, 21, 5, tzinfo=datetime.timezone.utc)

        self.assertEqual(
            fetch_papers.get_default_target_date(now),
            datetime.date(2026, 5, 31),
        )

    def test_iter_target_dates_supports_backfill_range(self) -> None:
        self.assertEqual(
            fetch_papers.iter_target_dates(
                start_date_str="2026-05-30",
                end_date_str="2026-05-31",
            ),
            [datetime.date(2026, 5, 30), datetime.date(2026, 5, 31)],
        )

    def test_fetch_arxiv_excludes_papers_after_target_date(self) -> None:
        feed = f"""<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          {_build_entry("future-paper", "2026-05-29", "Future paper")}
          {_build_entry("target-day-paper", "2026-05-28", "Target day paper")}
          {_build_entry("previous-day-paper", "2026-05-27", "Previous day paper")}
          {_build_entry("too-old-paper", "2026-05-24", "Too old paper")}
        </feed>
        """.encode("utf-8")

        with (
            mock.patch.object(fetch_papers, "_http_get", return_value=feed),
            mock.patch.object(fetch_papers, "MAX_PAPERS", 10),
            mock.patch.object(fetch_papers, "DAYS_BACK", 2),
            mock.patch("fetch_papers.time.sleep"),
        ):
            papers = fetch_papers.fetch_arxiv(datetime.date(2026, 5, 28))

        self.assertEqual(
            [paper["arxiv_id"] for paper in papers],
            ["target-day-paper", "previous-day-paper"],
        )

    def test_complete_with_continuation_retries_after_length_finish(self) -> None:
        class FakeCompletions:
            def __init__(self) -> None:
                self.calls = []
                self.responses = [
                    ("第一段未写完", "length"),
                    ("第二段补完。", "stop"),
                ]

            def create(self, **kwargs):
                self.calls.append(kwargs)
                content, finish_reason = self.responses.pop(0)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=content),
                            finish_reason=finish_reason,
                        )
                    ]
                )

        fake_completions = FakeCompletions()
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))

        text = fetch_papers.complete_with_continuation(
            fake_client,
            "prompt",
            max_tokens=100,
            continuation_prompt="继续",
        )

        self.assertEqual(text, "第一段未写完\n\n第二段补完。")
        self.assertEqual(len(fake_completions.calls), 2)
        self.assertEqual(fake_completions.calls[1]["messages"][-1]["content"], "继续")

    def test_complete_with_continuation_retries_after_empty_response(self) -> None:
        class FakeCompletions:
            def __init__(self) -> None:
                self.calls = []
                self.responses = [
                    ("", "stop"),
                    ("这是补回来的完整结果。", "stop"),
                ]

            def create(self, **kwargs):
                self.calls.append(kwargs)
                content, finish_reason = self.responses.pop(0)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=content),
                            finish_reason=finish_reason,
                        )
                    ]
                )

        fake_completions = FakeCompletions()
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))

        with mock.patch("fetch_papers.time.sleep"):
            text = fetch_papers.complete_with_continuation(
                fake_client,
                "prompt",
                max_tokens=100,
                continuation_prompt="继续",
            )

        self.assertEqual(text, "这是补回来的完整结果。")
        self.assertEqual(len(fake_completions.calls), 2)

    def test_summarize_paper_safely_uses_static_fallback_after_double_failure(self) -> None:
        paper = {
            "arxiv_id": "2606.00001v1",
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authors": ["Test Author"],
            "categories": ["cs.IR"],
            "published": "2026-06-01",
            "url": "https://arxiv.org/abs/2606.00001v1",
        }

        with (
            mock.patch.object(fetch_papers, "summarize_paper", side_effect=RuntimeError("full failed")),
            mock.patch.object(
                fetch_papers,
                "summarize_paper_with_abstract_fallback",
                side_effect=RuntimeError("fallback failed"),
            ),
        ):
            result = fetch_papers.summarize_paper_safely(SimpleNamespace(), paper)

        self.assertIn("自动解读失败", result["summary_zh"])
        self.assertIn("fallback failed", result["summary_zh"])

    def test_render_post_uses_plain_yaml_quotes_and_permalink(self) -> None:
        content = fetch_papers.render_post(
            papers=[
                {
                    "arxiv_id": "2605.28493v1",
                    "title": "Looking Farther with Confidence",
                    "abstract": "Abstract",
                    "authors": ["Ziqiang Cui", "Xing Tang", "Peiyang Liu", "Another Author"],
                    "categories": ["cs.IR", "cs.LG"],
                    "published": "2026-05-27",
                    "url": "https://arxiv.org/abs/2605.28493v1",
                    "summary_zh": "这是一段测试摘要。",
                }
            ],
            overview="这是一段测试概述。",
            date_str="2026-05-28",
        )

        frontmatter = content.split("---", 2)[1]
        self.assertIn('title: "推荐算法日报 2026-05-28"', frontmatter)
        self.assertIn("permalink: /daily/2026-05-28/", frontmatter)
        self.assertIn('  - "cs.IR"', frontmatter)
        self.assertIn('  - "cs.LG"', frontmatter)
        self.assertNotIn("“", frontmatter)
        self.assertNotIn("”", frontmatter)


if __name__ == "__main__":
    unittest.main()
