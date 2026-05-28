#!/usr/bin/env python3
"""
fetch_papers.py
从 arXiv 拉取论文，获取 HTML 全文，用 AI 生成深度解读，写入 Jekyll _posts/
用法：python fetch_papers.py [--date YYYY-MM-DD]
"""

import os
import re
import sys
import time
import html as html_lib
import argparse
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

from openai import OpenAI

from config import (
    SEARCH_TOPICS,
    MAX_PAPERS,
    DAYS_BACK,
    ARXIV_CATEGORIES,
    AI_MODEL,
    SUMMARY_LANGUAGE,
    SUMMARY_MAX_TOKENS,
    POST_TITLE_TEMPLATE,
    MIN_PAPERS_PER_SECTION,
    POSTS_DIR,
)

# ─────────────────────────────────────────
# arXiv 查询
# ─────────────────────────────────────────

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom",
      "arxiv": "http://arxiv.org/schemas/atom"}

# 全文截取字符上限（避免超出模型 context）
FULLTEXT_CHAR_LIMIT = 30000


def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "dailypaper/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _strip_html(raw: str) -> str:
    """粗略去掉 HTML 标签，保留可读文本。"""
    raw = re.sub(r"<style[^>]*>.*?</style>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html_lib.unescape(raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def fetch_fulltext(arxiv_id: str) -> tuple[str, str]:
    """
    尝试获取论文全文。
    返回 (text, source)，source 为 'html' / 'pdf' / 'abstract'。
    """
    # 第一步：arXiv HTML 全文
    for suffix in ["", "v1", "v2", "v3"]:
        try:
            url = f"https://arxiv.org/html/{arxiv_id}{suffix}"
            raw = _http_get(url, timeout=30).decode("utf-8", errors="replace")
            if "Introduction" in raw or "introduction" in raw:
                text = _strip_html(raw)[:FULLTEXT_CHAR_LIMIT]
                print(f"    [全文] HTML 获取成功 ({len(text)} 字符)")
                return text, "html"
        except Exception:
            pass
        time.sleep(1)

    # 第二步：下载 PDF 到临时文件，用 pypdf 提取
    try:
        import tempfile
        import pypdf

        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        pdf_bytes = _http_get(pdf_url, timeout=60)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        try:
            reader = pypdf.PdfReader(tmp_path)
            pages_text = []
            for page in reader.pages:
                pages_text.append(page.extract_text() or "")
            text = "\n".join(pages_text)[:FULLTEXT_CHAR_LIMIT]
            print(f"    [全文] PDF 提取成功 ({len(text)} 字符)")
            return text, "pdf"
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        print(f"    [全文] PDF 失败: {e}")

    # 降级：仅摘要
    print("    [全文] 降级为摘要")
    return "", "abstract"


def build_query() -> str:
    topic_parts = [f'all:"{t}"' for t in SEARCH_TOPICS]
    query = " OR ".join(topic_parts)
    if ARXIV_CATEGORIES:
        cat_parts = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
        query = f"({query}) AND ({cat_parts})"
    return query


def fetch_arxiv(target_date: datetime.date) -> list[dict]:
    query = build_query()
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": MAX_PAPERS * 3,   # 多拉一些，过滤后再截
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"
    print(f"[arXiv] 查询: {url[:120]}...")

    for attempt in range(5):
        try:
            time.sleep(3 + attempt * 5)  # 首次等3秒，每次重试多等5秒
            xml_data = _http_get(url, timeout=60)
            break
        except Exception as e:
            print(f"[arXiv] 第{attempt+1}次请求失败: {e}")
            if attempt == 4:
                raise

    root = ET.fromstring(xml_data)
    papers = []

    for entry in root.findall("atom:entry", NS):
        # 发布日期
        published_str = entry.findtext("atom:published", "", NS)
        if not published_str:
            continue
        pub_date = datetime.date.fromisoformat(published_str[:10])

        # 只允许抓取目标日期及之前的论文，避免历史日报混入“未来”论文
        if pub_date > target_date:
            continue

        # 日期过滤
        if DAYS_BACK > 0:
            cutoff = target_date - datetime.timedelta(days=DAYS_BACK)
            if pub_date < cutoff:
                continue

        arxiv_id = entry.findtext("atom:id", "", NS).split("/abs/")[-1]
        title = entry.findtext("atom:title", "", NS).strip().replace("\n", " ")
        abstract = entry.findtext("atom:summary", "", NS).strip().replace("\n", " ")

        authors = [
            a.findtext("atom:name", "", NS)
            for a in entry.findall("atom:author", NS)
        ]

        # 分类
        categories = [
            t.get("term", "")
            for t in entry.findall("atom:category", NS)
        ]

        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "categories": categories,
            "published": pub_date.isoformat(),
            "url": f"https://arxiv.org/abs/{arxiv_id}",
        })

    # 去重（同一 arxiv_id 可能出现多次）
    seen = set()
    unique = []
    for p in papers:
        if p["arxiv_id"] not in seen:
            seen.add(p["arxiv_id"])
            unique.append(p)

    result = unique[:MAX_PAPERS]
    print(f"[arXiv] 获取到 {len(result)} 篇论文")
    return result


# ─────────────────────────────────────────
# AI 深度解读（DeepSeek，兼容 OpenAI 格式）
# ─────────────────────────────────────────

def summarize_paper(client: OpenAI, paper: dict) -> dict:
    fulltext, source = fetch_fulltext(paper["arxiv_id"])

    if source == "abstract":
        source_note = "> ⚠️ 未能获取全文，以下解读仅基于摘要，结论请谨慎参考。\n\n"
        content_for_prompt = f"摘要：{paper['abstract']}"
    else:
        source_note = ""
        content_for_prompt = f"摘要：{paper['abstract']}\n\n全文内容：{fulltext}"

    prompt = f"""你是推荐系统方向的资深研究员，正在为工业界同行写论文深度解读笔记。

论文标题：{paper['title']}
{content_for_prompt}

请用{SUMMARY_LANGUAGE}按以下结构输出，要有实质内容，禁止用"提出了一个框架"这类废话敷衍，关键术语保留英文：

**论文定位**
这篇论文在推荐系统里解决的是什么具体问题（召回/排序/序列建模/冷启动/长尾/工程扩展性等），以及它相比已有方法的核心差异是什么。

**核心架构**
用 1-2 段解释整体方法，说清楚数据流：输入是什么 → 经过什么模块 → 输出什么。如果是生成式方法，说明生成目标；如果涉及 Semantic ID / Token，说明 ID 如何构造。

**关键机制拆解**
重点说 1-2 个最值得关注的设计点，解释为什么这个设计有效、代价是什么。

**实验结果**
列出数据集、对比 baseline、核心指标提升数字。没有数字就写"论文未报告具体数字"，禁止编造。

**工程挑战与落地建议**
从工业界角度看：特征接入成本、线上延迟影响、冷启动怎么处理、有什么局限，以及对从业者最有参考价值的一点建议。

**一句话总结**
不超过 30 字，说清楚这篇论文的核心贡献和适用场景。
"""

    response = client.chat.completions.create(
        model=AI_MODEL,
        max_tokens=SUMMARY_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    paper["summary_zh"] = source_note + response.choices[0].message.content
    return paper


def generate_daily_overview(client: OpenAI, papers: list[dict], date_str: str) -> str:
    papers_info = "\n\n".join(
        f"标题：{p['title']}\n摘要：{p['abstract'][:300]}" for p in papers
    )
    prompt = f"""你是推荐系统方向的资深研究员，以下是 {date_str} arXiv 上的论文：

{papers_info}

请写一段**今日趋势分析**（不超过 250 字），要求：
1. 指出今天这批论文整体在攻克哪些核心问题，不要逐篇列举
2. 点出最值得工业界关注的 1-2 个技术方向，说清楚为什么值得关注、对落地有什么意义
3. 如果有反直觉或值得警惕的研究倾向，也指出来
4. 语言简练有观点，像一个有经验的研究员在做周会分享，不要用"本日"、"今天"等口水话开头

直接输出正文，不加任何标题或前缀。"""

    response = client.chat.completions.create(
        model=AI_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


# ─────────────────────────────────────────
# Jekyll Post 生成
# ─────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def render_post(papers: list[dict], overview: str, date_str: str) -> str:
    title = POST_TITLE_TEMPLATE.format(date=date_str)
    topics = list(dict.fromkeys(  # 保持顺序去重
        t for p in papers for t in p.get("categories", [])
        if t in {"cs.IR", "cs.LG", "cs.AI", "cs.CL"}
    ))

    # YAML front matter
    frontmatter_lines = [
        "---",
        "layout: single",
        f'title: "{title}"',
        f"date: {date_str} 08:00:00 +0800",
        f"permalink: /daily/{date_str}/",
        f"paper_count: {len(papers)}",
        "share: false",
        "related: false",
        "read_time: false",
        "comments: false",
        "topics:",
    ]
    frontmatter_lines.extend(f'  - "{t}"' for t in topics)
    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines)

    # 正文
    body_parts = [f"## 今日概述\n\n{overview}\n"]

    body_parts.append(f"## 论文列表（共 {len(papers)} 篇）\n")

    for i, p in enumerate(papers, 1):
        authors_str = "、".join(p["authors"][:3])
        if len(p["authors"]) > 3:
            authors_str += f" 等{len(p['authors'])}人"

        body_parts.append(f"### {i}. {p['title']}\n")
        body_parts.append(
            f'<div class="paper-card">\n'
            f'<div class="paper-authors">{authors_str}</div>\n'
            f'<div class="paper-arxiv"><a href="{p["url"]}" target="_blank">'
            f'arXiv:{p["arxiv_id"]}</a> · {p["published"]}</div>\n'
            f"</div>\n"
        )
        body_parts.append(p.get("summary_zh", "（摘要生成失败）") + "\n")

    return frontmatter + "\n" + "\n".join(body_parts)


def write_post(content: str, date_str: str) -> str:
    os.makedirs(POSTS_DIR, exist_ok=True)
    filename = f"{date_str}-daily-report.md"
    path = os.path.join(POSTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ─────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    parser.add_argument("--date", default=yesterday,
                        help="生成哪天的日报，格式 YYYY-MM-DD，默认昨天")
    args = parser.parse_args()
    target_date = datetime.date.fromisoformat(args.date)
    date_str = target_date.isoformat()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("错误：请设置环境变量 DEEPSEEK_API_KEY")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    # 1. 拉取论文
    papers = fetch_arxiv(target_date)
    if not papers:
        print("今日没有符合条件的论文，跳过生成。")
        sys.exit(0)

    # 2. 逐篇获取全文并生成深度解读
    print(f"[DeepSeek] 开始解读 {len(papers)} 篇论文，模型：{AI_MODEL}")
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] {paper['title'][:60]}...")
        papers[i - 1] = summarize_paper(client, paper)
        if i < len(papers):
            time.sleep(0.3)  # 避免触发速率限制

    # 3. 生成今日概述
    print("[DeepSeek] 生成今日概述...")
    overview = generate_daily_overview(client, papers, date_str)

    # 4. 写入 Jekyll post
    content = render_post(papers, overview, date_str)
    path = write_post(content, date_str)
    print(f"[完成] 文章已写入：{path}")


if __name__ == "__main__":
    main()
