from pathlib import Path
import unittest


class DailyArchiveTemplateTests(unittest.TestCase):
    def test_daily_archive_only_collects_daily_posts(self) -> None:
        template = Path("_pages/daily.html").read_text(encoding="utf-8")

        self.assertIn("p.paper_count and p.url contains '/daily/'", template)
        self.assertNotIn("p.path contains '_posts'", template)


if __name__ == "__main__":
    unittest.main()
