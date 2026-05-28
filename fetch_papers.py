#!/usr/bin/env python3
"""
fetch_papers.py
从 arXiv 拉取论文，用 Claude API 生成中文摘要，写入 Jekyll _posts/
用法：python fetch_papers.py [--date YYYY-MM-DD]
"""

import os
import re
import sys
import time
import argparse
import datetime
import textwrap
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

import anthropic

from config import (
    SEARCH_TOPICS,
    MAX_PAPERS,
    DAYS_BACK,
    ARXIV_CATEGORIES,
    CLAUDE_MODEL,
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

    req = urllib.request.Request(url, headers={"User-Agent": "dailypaper/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    papers = []

    for entry in root.findall("atom:entry", NS):
        # 发布日期
        published_str = entry.findtext("atom:published", "", NS)
        if not published_str:
            continue
        pub_date = datetime.date.fromisoformat(published_str[:10])

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
# Claude 摘要
# ─────────────────────────────────────────

def summarize_paper(client: anthropic.Anthropic, paper: dict) -> dict:
    prompt = f"""请用{SUMMARY_LANGUAGE}简明总结以下论文，面向工业界机器学习工程师。

标题：{paper['title']}
摘要（原文）：{paper['abstract']}

请按以下格式输出（不要输出多余内容）：

**一句话结论**：（20字以内，论文最核心的贡献）

**方法**：（2-3句，描述技术方案）

**效果**：（如果有具体数字就列出，没有就写"论文未给出具体指标"）

**适用场景**：（这个工作对哪类工程实践有参考价值）
"""

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=SUMMARY_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    paper["summary_zh"] = message.content[0].text
    return paper


def generate_daily_overview(client: anthropic.Anthropic, papers: list[dict], date_str: str) -> str:
    titles = "\n".join(f"- {p['title']}" for p in papers)
    prompt = f"""今日（{date_str}）arXiv 推荐系统方向共有以下论文：

{titles}

请用{SUMMARY_LANGUAGE}写一段今日概述（150字以内），总结：
1. 今天的主要研究趋势
2. 最值得关注的1-2个方向

直接输出概述文字，不要加标题。"""

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


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
    topics_yaml = "\n".join(f'  - "{t}"' for t in topics)
    frontmatter = textwrap.dedent(f"""\
        ---
        layout: post
        title: "{title}"
        date: {date_str} 08:00:00 +0800
        paper_count: {len(papers)}
        summary: "{overview[:80].replace('"', "'")}"
        topics:
        {topics_yaml}
        ---
    """)

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
    parser.add_argument("--date", default=datetime.date.today().isoformat(),
                        help="生成哪天的日报，格式 YYYY-MM-DD，默认今天")
    args = parser.parse_args()
    target_date = datetime.date.fromisoformat(args.date)
    date_str = target_date.isoformat()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("错误：请设置环境变量 ANTHROPIC_API_KEY")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # 1. 拉取论文
    papers = fetch_arxiv(target_date)
    if not papers:
        print("今日没有符合条件的论文，跳过生成。")
        sys.exit(0)

    # 2. 逐篇生成摘要
    print(f"[Claude] 开始生成 {len(papers)} 篇摘要，模型：{CLAUDE_MODEL}")
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] {paper['title'][:60]}...")
        papers[i - 1] = summarize_paper(client, paper)
        if i < len(papers):
            time.sleep(0.3)  # 避免触发速率限制

    # 3. 生成今日概述
    print("[Claude] 生成今日概述...")
    overview = generate_daily_overview(client, papers, date_str)

    # 4. 写入 Jekyll post
    content = render_post(papers, overview, date_str)
    path = write_post(content, date_str)
    print(f"[完成] 文章已写入：{path}")


if __name__ == "__main__":
    main()
