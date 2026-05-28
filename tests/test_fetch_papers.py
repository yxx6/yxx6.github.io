import datetime
import unittest
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
