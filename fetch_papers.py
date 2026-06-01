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

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9+ normally has zoneinfo
    ZoneInfo = None

from openai import OpenAI

from config import (
    SEARCH_TOPICS,
    MAX_PAPERS,
    DAYS_BACK,
    ARXIV_CATEGORIES,
    AI_MODEL,
    SUMMARY_LANGUAGE,
    SUMMARY_MAX_TOKENS,
    DAILY_OVERVIEW_MAX_TOKENS,
    LLM_MAX_CONTINUATIONS,
    POST_TITLE_TEMPLATE,
    MIN_PAPERS_PER_SECTION,
    POSTS_DIR,
    REPORT_TIMEZONE,
)

# ─────────────────────────────────────────
# arXiv 查询
# ─────────────────────────────────────────

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom",
      "arxiv": "http://arxiv.org/schemas/atom"}

# 全文截取字符上限（避免超出模型 context）
FULLTEXT_CHAR_LIMIT = 30000


def _get_report_timezone() -> datetime.tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo(REPORT_TIMEZONE)
        except Exception:
            pass
    return datetime.timezone(datetime.timedelta(hours=8), name="UTC+08:00")


REPORT_TZ = _get_report_timezone()


def get_default_target_date(now: datetime.datetime | None = None) -> datetime.date:
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)

    report_now = now.astimezone(REPORT_TZ)
    return report_now.date() - datetime.timedelta(days=1)


def iter_target_dates(
    date_str: str | None = None,
    start_date_str: str | None = None,
    end_date_str: str | None = None,
) -> list[datetime.date]:
    if date_str and (start_date_str or end_date_str):
        raise ValueError("--date 不能和 --start-date/--end-date 同时使用")

    if bool(start_date_str) != bool(end_date_str):
        raise ValueError("--start-date 和 --end-date 必须一起提供")

    if date_str:
        return [datetime.date.fromisoformat(date_str)]

    if start_date_str and end_date_str:
        start_date = datetime.date.fromisoformat(start_date_str)
        end_date = datetime.date.fromisoformat(end_date_str)
        if start_date > end_date:
            raise ValueError("--start-date 不能晚于 --end-date")

        days = (end_date - start_date).days
        return [
            start_date + datetime.timedelta(days=offset)
            for offset in range(days + 1)
        ]

    return [get_default_target_date()]


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


def _extract_response_text(message_content: object) -> str:
    if isinstance(message_content, str):
        return message_content

    if isinstance(message_content, list):
        chunks = []
        for block in message_content:
            if getattr(block, "type", None) != "text":
                continue

            block_text = getattr(block, "text", "")
            if isinstance(block_text, str):
                chunks.append(block_text)
            else:
                chunks.append(getattr(block_text, "value", ""))
        return "".join(chunks)

    return str(message_content or "")


def complete_with_continuation(
    client: OpenAI,
    prompt: str,
    *,
    max_tokens: int,
    continuation_prompt: str,
) -> str:
    messages = [{"role": "user", "content": prompt}]
    fragments: list[str] = []

    for _ in range(LLM_MAX_CONTINUATIONS):
        response = client.chat.completions.create(
            model=AI_MODEL,
            max_tokens=max_tokens,
            messages=messages,
        )
        choice = response.choices[0]
        fragment = _extract_response_text(choice.message.content).strip()
        if not fragment:
            raise RuntimeError("模型返回了空内容，无法生成日报。")

        fragments.append(fragment)
        if getattr(choice, "finish_reason", None) != "length":
            return "\n\n".join(fragments).strip()

        messages.extend(
            [
                {"role": "assistant", "content": fragment},
                {"role": "user", "content": continuation_prompt},
            ]
        )

    raise RuntimeError("模型输出多次续写后仍被截断，已停止以避免写入半截内容。")


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

请用{SUMMARY_LANGUAGE}输出一份“可以直接发给团队周会”的深读笔记，默认写得充分具体，不追求简短。
除非论文没有提供，否则不要省略模块名、目标函数、训练/推理路径、实验设置、baseline 名称和关键数字；如果论文没写，请明确写“论文未报告”，禁止脑补。
关键术语保留英文，请严格按以下结构输出，并保证每一节都有实质内容：

**论文定位**
用 4-6 句讲清楚论文解决的具体问题（召回/排序/序列建模/冷启动/长尾/工程扩展性等），以及它相比已有方法真正新在哪里。

**问题建模与输入输出**
说明模型输入是什么、监督信号是什么、预测目标是什么；如果有关键符号、状态表示、Semantic ID / Token，也在这里解释清楚。

**核心架构**
用 2-4 段解释整体方法，说清楚数据流：输入是什么 → 经过什么模块 → 输出什么。不要只写“提出了某框架”，而要把主干、辅助模块、损失函数之间的关系讲明白。

**关键机制拆解**
拆 2-3 个最值得关注的设计点，解释为什么这个设计有效、它解决了什么旧方法痛点、代价是什么。

**训练与推理细节**
交代训练目标、采样/负样本、是否只在训练阶段使用辅助模块、推理时保留什么，以及这对部署意味着什么。

**实验结果**
列出数据集、最重要的 baseline、指标、最关键的提升数字。没有数字就写“论文未报告具体数字”，不要只写“效果更好”。

**工业落地价值**
从工业界角度看：特征接入成本、线上延迟、冷启动、可扩展性、监控风险分别意味着什么，并给出一条最值得尝试的落地建议。

**局限与风险**
明确写出论文的边界条件、可能失败的场景、没有解决的问题，以及读者最该警惕的一点。

**一句话总结**
不超过 40 字，说清楚论文的核心贡献和最适合的场景。
"""

    paper["summary_zh"] = source_note + complete_with_continuation(
        client,
        prompt,
        max_tokens=SUMMARY_MAX_TOKENS,
        continuation_prompt="继续未完成的深读笔记，直接从上文中断处接着写，不要重复已经写过的内容，也不要重新输出开头。",
    )
    return paper


def generate_daily_overview(client: OpenAI, papers: list[dict], date_str: str) -> str:
    papers_info = "\n\n".join(
        f"标题：{p['title']}\n摘要：{p['abstract'][:300]}" for p in papers
    )
    prompt = f"""你是推荐系统方向的资深研究员，以下是 {date_str} arXiv 上的论文：

{papers_info}

请写 2-3 段**今日趋势分析**，总长度控制在 350-600 字，默认写得比摘要更具体。要求：
1. 指出今天这批论文整体在攻克哪些核心问题，不要逐篇列举
2. 点出最值得工业界关注的 1-2 个技术方向，说清楚为什么值得关注、对落地有什么意义
3. 如果有反直觉或值得警惕的研究倾向，也指出来
4. 最后一段给出面向工业界的判断，不要只写“值得关注”
5. 语言简练但不要过短，像一个有经验的研究员在做周会分享，不要用"本日"、"今天"等口水话开头
6. 必须写完整，不能以半句话收尾

直接输出正文，不加任何标题或前缀。"""

    return complete_with_continuation(
        client,
        prompt,
        max_tokens=DAILY_OVERVIEW_MAX_TOKENS,
        continuation_prompt="继续未完成的趋势分析，直接接着上文写完，不要重复已经输出的内容。",
    )


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


def generate_post_for_date(client: OpenAI, target_date: datetime.date) -> str | None:
    date_str = target_date.isoformat()
    print(f"[开始] 生成 {date_str} 的日报")

    papers = fetch_arxiv(target_date)
    if not papers:
        print(f"[跳过] {date_str} 没有符合条件的论文。")
        return None

    print(f"[DeepSeek] 开始解读 {len(papers)} 篇论文，模型：{AI_MODEL}")
    for i, paper in enumerate(papers, 1):
        print(f"  [{i}/{len(papers)}] {paper['title'][:60]}...")
        papers[i - 1] = summarize_paper(client, paper)
        if i < len(papers):
            time.sleep(0.3)  # 避免触发速率限制

    print("[DeepSeek] 生成今日概述...")
    overview = generate_daily_overview(client, papers, date_str)

    content = render_post(papers, overview, date_str)
    path = write_post(content, date_str)
    print(f"[完成] 文章已写入：{path}")
    return path


# ─────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        help=f"生成哪天的日报，格式 YYYY-MM-DD；默认按 {REPORT_TIMEZONE} 时区取昨天",
    )
    parser.add_argument(
        "--start-date",
        help="批量补日报的开始日期，格式 YYYY-MM-DD，需要和 --end-date 一起使用",
    )
    parser.add_argument(
        "--end-date",
        help="批量补日报的结束日期，格式 YYYY-MM-DD，需要和 --start-date 一起使用",
    )
    args = parser.parse_args()

    try:
        target_dates = iter_target_dates(args.date, args.start_date, args.end_date)
    except ValueError as exc:
        parser.error(str(exc))

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("错误：请设置环境变量 DEEPSEEK_API_KEY")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    generated_paths = []
    for target_date in target_dates:
        path = generate_post_for_date(client, target_date)
        if path:
            generated_paths.append(path)

    if not generated_paths:
        print("[完成] 没有生成任何日报。")


if __name__ == "__main__":
    main()
