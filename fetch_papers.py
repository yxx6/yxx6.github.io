#!/usr/bin/env python3
"""
fetch_papers.py
从 arXiv 拉取论文，用 AI API 生成中文摘要，写入 Jekyll _posts/
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
    for attempt in range(5):
        try:
            time.sleep(3 + attempt * 5)  # 首次等3秒，每次重试多等5秒
            with urllib.request.urlopen(req, timeout=60) as resp:
                xml_data = resp.read()
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
# AI 摘要（DeepSeek，兼容 OpenAI 格式）
# ─────────────────────────────────────────

def summarize_paper(client: OpenAI, paper: dict) -> dict:
    prompt = f"""你是一名推荐系统方向的资深研究员，正在为同行工程师写论文速读笔记。

论文标题：{paper['title']}
原文摘要：{paper['abstract']}

请按以下格式输出，语言为{SUMMARY_LANGUAGE}，每项要有实质内容，禁止废话和重复摘要原文：

**核心贡献**：一句话，说清楚这篇论文解决了什么问题、用什么手段解决的（不超过30字）

**技术方案**：
- 问题设定：（这篇论文针对的是什么具体问题或痛点）
- 方法：（核心技术思路是什么，2-3句，要具体，不要"提出了一个框架"这类废话）
- 关键设计：（最有创意或最值得关注的一个设计点）

**实验结果**：（列出具体数字，如果摘要没有就写"摘要未提供"，不要编造）

**工程价值**：（对工业界落地有什么启示？适合什么规模/场景？有什么局限？2句话）
"""

    response = client.chat.completions.create(
        model=AI_MODEL,
        max_tokens=SUMMARY_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    paper["summary_zh"] = response.choices[0].message.content
    return paper


def generate_daily_overview(client: OpenAI, papers: list[dict], date_str: str) -> str:
    titles_with_abstract = "\n".join(
        f"- 标题：{p['title']}\n  摘要：{p['abstract'][:200]}" for p in papers
    )
    prompt = f"""你是推荐系统方向的资深研究员，以下是 {date_str} arXiv 上的论文列表：

{titles_with_abstract}

请写一段**今日趋势分析**（200字以内），要求：
1. 指出今天论文整体在攻克哪些核心问题（不要逐篇列举）
2. 点出最值得工业界关注的1-2个技术方向，说明为什么
3. 语言简练，有观点，有判断，像一个有经验的研究员在做周会分享

直接输出正文，不要加任何标题或前缀。"""

    response = client.chat.completions.create(
        model=AI_MODEL,
        max_tokens=400,
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
    topics_yaml = "\n".join(f'  - "{t}"' for t in topics)
    frontmatter = textwrap.dedent(f"""\
        ---
        layout: single
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

    # 2. 逐篇生成摘要
    print(f"[DeepSeek] 开始生成 {len(papers)} 篇摘要，模型：{AI_MODEL}")
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
