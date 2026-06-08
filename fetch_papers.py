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
import urllib.error
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

ARXIV_API = "https://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom",
      "arxiv": "http://arxiv.org/schemas/atom"}

# 全文截取字符上限（避免超出模型 context）
FULLTEXT_CHAR_LIMIT = 30000
ARXIV_USER_AGENT = os.environ.get(
    "ARXIV_USER_AGENT",
    "dailypaper/1.0 (https://yxx6.github.io; automated daily paper fetcher)",
)
ARXIV_MAX_ATTEMPTS = int(os.environ.get("ARXIV_MAX_ATTEMPTS", "8"))
ARXIV_RETRY_SLEEP_SECONDS = int(os.environ.get("ARXIV_RETRY_SLEEP_SECONDS", "60"))


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
    req = urllib.request.Request(url, headers={"User-Agent": ARXIV_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _retry_after_seconds(headers) -> int | None:
    if not headers:
        return None

    value = headers.get("Retry-After")
    if not value:
        return None

    try:
        return max(0, int(value))
    except ValueError:
        return None


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

    for attempt in range(ARXIV_MAX_ATTEMPTS):
        has_more_attempts = attempt < ARXIV_MAX_ATTEMPTS - 1
        try:
            time.sleep(min(30, 3 + attempt * 5))  # 首次等3秒，每次重试多等5秒
            xml_data = _http_get(url, timeout=60)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and has_more_attempts:
                retry_after = _retry_after_seconds(e.headers)
                backoff = min(180, ARXIV_RETRY_SLEEP_SECONDS * (attempt + 1))
                extra_sleep = max(ARXIV_RETRY_SLEEP_SECONDS, retry_after or 0, backoff)
                print(f"[arXiv] 第{attempt+1}次请求被限流: {e}，{extra_sleep} 秒后重试")
                time.sleep(extra_sleep)
                continue
            if has_more_attempts:
                extra_sleep = min(60, 10 * (attempt + 1))
                print(f"[arXiv] 第{attempt+1}次请求失败: {e}，{extra_sleep} 秒后重试")
                time.sleep(extra_sleep)
                continue
            print(f"[arXiv] 第{attempt+1}次请求失败: {e}")
            raise
        except Exception as e:
            if has_more_attempts:
                extra_sleep = min(60, 10 * (attempt + 1))
                print(f"[arXiv] 第{attempt+1}次请求失败: {e}，{extra_sleep} 秒后重试")
                time.sleep(extra_sleep)
                continue
            print(f"[arXiv] 第{attempt+1}次请求失败: {e}")
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


def _looks_like_complete_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    if stripped.endswith(("```", "---")):
        return True

    lines = [line.rstrip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return False

    last_line = lines[-1].strip()
    if not last_line:
        return False

    if last_line.startswith(("#", "##", "###", "- ", "* ")):
        return False

    if re.search(r"[，、：；（\[【\-\*\/]$", last_line):
        return False

    if re.search(r"(和|与|及|或|并|以及|因为|所以|如果|但|而且|其中|例如|包括)$", last_line):
        return False

    return bool(re.search(r"[。！？.!?）\]】\"”'》]$", last_line))


def _clean_generated_markdown(text: str) -> str:
    lines = text.splitlines()
    first_pass_lines: list[str] = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            first_pass_lines.append(line)
            continue

        if not in_code_block:
            if stripped == "**":
                continue
            if stripped.startswith("|") and stripped.count("|") <= 1:
                continue
            if (
                stripped
                and re.match(r"^[，。；：、]", stripped)
                and first_pass_lines
                and any(existing.strip() for existing in first_pass_lines)
            ):
                while first_pass_lines and not first_pass_lines[-1].strip():
                    first_pass_lines.pop()
                if first_pass_lines and not first_pass_lines[-1].strip().startswith(("|", "```")):
                    first_pass_lines[-1] = first_pass_lines[-1].rstrip() + stripped
                    continue
            if (
                stripped
                and re.match(r"^[，。；：、]", stripped)
                and first_pass_lines
                and first_pass_lines[-1].strip()
                and not first_pass_lines[-1].strip().startswith(("|", "```"))
            ):
                first_pass_lines[-1] = first_pass_lines[-1].rstrip() + stripped
                continue

        if stripped or not first_pass_lines or first_pass_lines[-1].strip():
            first_pass_lines.append(line)

    final_lines: list[str] = []
    for index, line in enumerate(first_pass_lines):
        stripped = line.strip()
        if (
            stripped.startswith("**")
            and "：" in stripped
            and not stripped.endswith(("。", "！", "？", ".", "!", "?", "：", ":", "**"))
        ):
            next_non_empty = ""
            for candidate in first_pass_lines[index + 1:]:
                candidate = candidate.strip()
                if candidate:
                    next_non_empty = candidate
                    break
            if next_non_empty.startswith(("**", "##", "###", ">", "-", "*", "|", "```")):
                continue
        final_lines.append(line)

    return _normalize_generated_math_markdown("\n".join(final_lines)).strip()


def _normalize_math_markdown(text: str) -> str:
    """
    Keep generated math compatible with Kramdown + MathJax.

    Kramdown treats \( and \[ as Markdown escapes before MathJax runs, and it
    parses bare | characters before MathJax sees formulas. Normalize math
    delimiters to dollar syntax and remove literal pipes inside math spans.
    """
    def escape_math_content(content: str) -> str:
        content = re.sub(r"\\\|(.+?)\\\|", r"\\lVert \1\\rVert", content)
        content = re.sub(
            r"(?<!\\)\|([^|\n]+?)(?<!\\)\|",
            r"\\lvert \1\\rvert",
            content,
        )
        return re.sub(r"(?<!\\)\|", r"\\vert", content)

    def apply_outside_code_blocks(block: str) -> str:
        block = re.sub(
            r"\\\[(.*?)\\\]",
            lambda match: f"$${match.group(1)}$$",
            block,
            flags=re.S,
        )
        block = re.sub(
            r"\\\((.*?)\\\)",
            lambda match: f"${match.group(1)}$",
            block,
        )

        replacements = [
            (re.compile(r"\$\$(.*?)\$\$", flags=re.S), "$$", "$$"),
            (re.compile(r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\\)\$(?!\$)"), "$", "$"),
        ]

        for pattern, open_delim, close_delim in replacements:
            block = pattern.sub(
                lambda match: (
                    f"{open_delim}{escape_math_content(match.group(1))}{close_delim}"
                ),
                block,
            )
        return block

    parts = re.split(r"(```.*?```)", text, flags=re.S)
    for index, part in enumerate(parts):
        if part.startswith("```"):
            continue
        parts[index] = apply_outside_code_blocks(part)
    return "".join(parts)


def _latexify_formula_text(text: str) -> str:
    formula = text.strip()
    formula = formula.replace("ŷ", r"\hat{y}")
    formula = re.sub(r"\by_hat\b", r"\\hat{y}", formula)
    formula = re.sub(r"\b([A-Za-z])_\{([^}]+)\}", r"\1_{\2}", formula)
    formula = re.sub(r"\b([A-Za-z])_([A-Za-z0-9]+)\b", r"\1_{\2}", formula)
    formula = re.sub(r"([A-Za-z])\^\(([^)]+)\)", r"\1^{(\2)}", formula)

    greek_names = {
        "α": "alpha",
        "β": "beta",
        "γ": "gamma",
        "δ": "delta",
        "η": "eta",
        "θ": "theta",
        "λ": "lambda",
        "μ": "mu",
        "ρ": "rho",
        "σ": "sigma",
        "τ": "tau",
        "φ": "phi",
        "ω": "omega",
    }
    for symbol, name in greek_names.items():
        formula = re.sub(fr"{symbol}_?([A-Za-z0-9]+)", fr"\\{name}_{{\1}}", formula)
        formula = formula.replace(symbol, fr"\{name}")

    formula = re.sub(r"\bomega\b", r"\\omega", formula)
    formula = re.sub(r"\btau\b", r"\\tau", formula)
    formula = re.sub(r"\blambda\b", r"\\lambda", formula)
    formula = formula.replace("∈", r"\in")
    formula = formula.replace("ℝ", r"\mathbb{R}")
    formula = formula.replace("⊙", r"\odot")
    formula = formula.replace("·", r"\cdot")
    formula = re.sub(r"\bexp\s*\(", r"\\exp(", formula)
    return formula


def _normalize_common_bare_formula_tokens(text: str) -> str:
    """
    Convert common LLM-style pseudo math into MathJax spans.

    This is intentionally conservative: it handles the recurring report
    artifacts we have seen, while leaving plaintext flow diagrams alone.
    """

    def math_span(formula: str) -> str:
        return f"${_latexify_formula_text(formula)}$"

    def apply_outside_math(block: str, transform) -> str:
        parts = re.split(
            r"(\$\$.*?\$\$|(?<!\$)\$(?!\$)[^$\n]+?(?<!\\)\$(?!\$))",
            block,
            flags=re.S,
        )
        for index, part in enumerate(parts):
            if part.startswith("$"):
                continue
            parts[index] = transform(part)
        return "".join(parts)

    def normalize_phrases(segment: str) -> str:
        segment = re.sub(
            r"`([^`\n]*(?:y_hat|h\^|x\^|g\^|ω|τ|λ|α|β|η|δ|θ|ρ|φ|exp\(|\^\(|_\{|[A-Za-z]_[A-Za-z])[^`\n]*)`",
            lambda match: math_span(match.group(1)),
            segment,
        )
        segment = re.sub(
            r"(?:omega|ω)\s*=\s*exp\(-H\(y_hat\)\s*/\s*(?:tau|τ)\)",
            lambda match: r"$\omega = \exp(-H(\hat{y})/\tau)$",
            segment,
        )
        segment = re.sub(
            r"(?:omega|ω)\s*=\s*exp\(-H\(ŷ\)\s*/\s*(?:tau|τ)\)",
            lambda match: r"$\omega = \exp(-H(\hat{y})/\tau)$",
            segment,
        )
        segment = re.sub(
            r"(?:omega|ω)\s*=\s*exp\(-H\s*/\s*(?:tau|τ)\)",
            lambda match: r"$\omega = \exp(-H/\tau)$",
            segment,
        )
        segment = re.sub(
            r"(?<![\w$\\])\|([A-Za-z])\|(?![\w$])",
            lambda match: rf"$\lvert {match.group(1)}\rvert$",
            segment,
        )
        segment = re.sub(r"\bH\(y_hat\)", lambda match: r"$H(\hat{y})$", segment)
        segment = re.sub(
            r"\by_hat\^\(([^)]+)\)",
            lambda match: rf"$\hat{{y}}^{{({match.group(1)})}}$",
            segment,
        )
        segment = re.sub(r"\by_hat\b", lambda match: r"$\hat{y}$", segment)
        segment = re.sub(
            r"\b([A-Za-z])\^\(([^)]+)\)",
            lambda match: rf"${match.group(1)}^{{({match.group(2)})}}$",
            segment,
        )
        segment = re.sub(
            r"([δ])\^\(([^)]+)\)",
            lambda match: rf"${_latexify_formula_text(match.group(1))}^{{({match.group(2)})}}$",
            segment,
        )
        segment = re.sub(r"\bh\^z\b", r"$h^z$", segment)
        segment = re.sub(
            r"\b([A-Za-z])_([A-Za-z0-9]+)\b",
            lambda match: rf"${match.group(1)}_{{{match.group(2)}}}$",
            segment,
        )
        return segment

    def wrap_standalone_greek(segment: str) -> str:
        greek_names = {
            "α": "alpha",
            "β": "beta",
            "γ": "gamma",
            "δ": "delta",
            "η": "eta",
            "θ": "theta",
            "λ": "lambda",
            "μ": "mu",
            "ρ": "rho",
            "σ": "sigma",
            "τ": "tau",
            "φ": "phi",
            "ω": "omega",
        }
        for symbol, name in greek_names.items():
            segment = re.sub(
                fr"(?<![A-Za-z0-9_\\$]){symbol}_?([A-Za-z0-9]+)",
                lambda match: rf"$\{name}_{{{match.group(1)}}}$",
                segment,
            )
            segment = re.sub(
                fr"(?<![A-Za-z0-9_\\$]){symbol}(?![A-Za-z0-9_])",
                lambda match, name=name: rf"$\{name}$",
                segment,
            )
        return segment

    parts = re.split(r"(```.*?```)", text, flags=re.S)
    for index, part in enumerate(parts):
        if part.startswith("```"):
            continue
        normalized = apply_outside_math(part, normalize_phrases)
        parts[index] = apply_outside_math(normalized, wrap_standalone_greek)
    return "".join(parts)


def _normalize_generated_math_markdown(text: str) -> str:
    text = _normalize_math_markdown(text)
    return _normalize_common_bare_formula_tokens(text)


def complete_with_continuation(
    client: OpenAI,
    prompt: str,
    *,
    max_tokens: int,
    continuation_prompt: str,
) -> str:
    messages = [{"role": "user", "content": prompt}]
    fragments: list[str] = []
    empty_response_retries = 2

    for _ in range(LLM_MAX_CONTINUATIONS):
        fragment = ""
        choice = None
        for attempt in range(empty_response_retries + 1):
            response = client.chat.completions.create(
                model=AI_MODEL,
                max_tokens=max_tokens,
                messages=messages,
            )
            choice = response.choices[0]
            fragment = _extract_response_text(choice.message.content).strip()
            if fragment:
                break
            if attempt == empty_response_retries:
                raise RuntimeError("模型连续返回空内容，无法生成日报。")
            time.sleep(1)

        fragments.append(fragment)
        merged_text = "\n\n".join(fragments).strip()
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason != "length" and _looks_like_complete_text(merged_text):
            return _clean_generated_markdown(merged_text)

        messages.extend(
            [
                {"role": "assistant", "content": fragment},
                {"role": "user", "content": continuation_prompt},
            ]
        )

    merged_text = "\n\n".join(fragments).strip()
    if _looks_like_complete_text(merged_text):
        return _clean_generated_markdown(merged_text)

    raise RuntimeError("模型输出多次续写后仍像是半截内容，已停止以避免写入截断文本。")


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

    prompt = f"""你是推荐系统方向的资深研究员，要为推荐系统从业者写一份“可落地的读书笔记”，不是普通论文摘要。

论文标题：{paper['title']}
{content_for_prompt}

请用{SUMMARY_LANGUAGE}输出，保留关键英文术语，风格像团队周会里的深度解读，重点回答：这篇论文到底解决了什么问题、为什么值得工业界关注、落地代价是什么、结论哪些可信哪些要谨慎。

这是一篇“日报里的单篇论文解读”，请做以下适配：
1. 不要输出 H1 标题，不要重复论文标题。
2. 不要重复论文链接、作者、机构、arXiv 信息，这些页面上已经有。
3. 直接从正文开始，使用 `## 一、...`、`## 二、...` 这种中文编号章节。
4. 多用“关键洞察”“工程挑战”“反直觉发现”“对从业者的建议”这类小节。
5. 关键结论用 `>` blockquote 或单独加粗段落突出。
6. 表格必须使用标准 Markdown 表格。
7. 方法流程、训练/推理链路、Semantic ID / Token 路径优先用 `plaintext` 代码块；代码块只放流程图，不放公式推导；只有结构确实复杂时才用 Mermaid。
8. 除非论文没有提供，否则不要省略模块名、目标函数、训练/推理路径、实验设置、baseline 名称和关键数字；如果论文没写，请明确写“论文未报告”，禁止脑补。
9. 数学变量和公式必须使用标准 LaTeX，并用 `$...$` 或 `$$...$$` 包裹；不要裸写 `y_hat`、`h^(k)`、`omega = exp(...)`、`ω = exp(...)`，也不要用反引号包公式。示例：`$\hat{{y}}^{{(k)}}$`、`$\omega = \exp(-H(\hat{{y}})/\tau)$`、`$\lvert V\rvert$`。

请尽量遵循下面这套结构，但要根据论文内容灵活取舍；如果某一节明显不适用，可以说明“不适用”或“论文未涉及”，不要硬编：

## 一、论文定位：为什么这篇论文重要？
说明它在推荐系统、生成式推荐或 Semantic ID 方向里的位置，强调它解决的是学术问题、工业问题，还是二者之间的落地 gap。

> **相比已有方法，这篇论文最值得关注的是**：用 2-4 句点明真正的新意。

## 二、核心架构：方法到底是什么？
先用 1 段话解释整体方法，再补一个 `plaintext` 代码块把数据流画出来，例如“用户行为 / Item 内容 / 多模态特征 -> 编码器 / Tokenizer / Quantizer -> Semantic ID / Token 序列 -> 生成式推荐模型 / 排序模型 / 检索系统 -> 候选 item / 排序结果”。

如果论文明确涉及 Semantic ID、tokenizer、量化编码或 ID 体系，请增加一个对比表：
### Semantic ID vs Atomic ID 对比
至少比较基数、冷启动、长尾、部署代价；若论文未涉及，就明确写“论文未涉及 SID / Atomic ID 对比”。

## 三、关键机制拆解
按论文内容选择 2-4 个最重要的小节，例如：
- SID 如何构造：embedding 来源、RQ-VAE、K-means、层级聚类、残差量化、tokenizer 训练。
- 模型如何训练：LM loss、next item prediction、contrastive learning、multi-task loss。
- 推理如何落地：beam search、constrained decoding、trie、SID-to-item 解析、ANN / 倒排索引。

每个小节都要说明：它解决了什么问题、为什么有效、代价是什么、部署时要注意什么。

## 四、实验结果：效果是否可信？
优先用表格汇总数据集、baseline、指标、提升幅度，必须区分离线指标和线上 A/B；如果没有线上实验，要明确写“论文未报告线上结果”。

> **关键洞察 1**：提炼一个最值得记住的实验结论。
> **关键洞察 2**：提炼一个容易被忽略但对工程实践有意义的实验结论。

## 五、工程挑战与设计选择（核心精华）
至少展开 2 个挑战。每个挑战都要包含：
### 挑战 X：一句话点题
> **问题描述**：...

然后说明根因、论文的解法、为什么可行、代价是什么、有哪些前置条件。

## 六、反直觉发现 / 最有价值的结论
总结一个最反直觉、最会改变后续做法，或最值得工业界重新思考的发现。

## 七、总结与评价
需要包含以下三个小节：
### 亮点
### 局限 / 可改进
### 对从业者的建议

“对从业者的建议”优先用 Markdown 表格，总结不同场景下的建议与风险。

最后用一个 blockquote 输出：
> **一句话总结**：不超过 40 字，说清楚核心贡献和最适合的场景。
"""

    paper["summary_zh"] = source_note + complete_with_continuation(
        client,
        prompt,
        max_tokens=SUMMARY_MAX_TOKENS,
        continuation_prompt="继续未完成的深读笔记，直接从上文中断处接着写，不要重复已经写过的内容，也不要重新输出开头。",
    )
    return paper


def summarize_paper_with_abstract_fallback(
    client: OpenAI,
    paper: dict,
    error: Exception,
) -> dict:
    prompt = f"""你是推荐系统方向的资深研究员。由于完整版解读失败，请仅基于摘要生成一份精简但仍然可用的中文读书笔记，保留关键英文术语，禁止脑补未提供的细节。

论文标题：{paper['title']}
摘要：{paper['abstract']}

请直接输出正文，不要重复论文标题，使用以下结构：

## 一、论文定位
说明论文在推荐系统里的问题定义与价值。

## 二、核心方法
仅根据摘要解释输入、核心模块、输出目标；如果摘要信息不足，请明确写“摘要未提供足够细节”。

## 三、实验与可信度
概括数据集、baseline、指标、提升；没有数字就明确写“论文未报告具体数字”。

## 四、工程含义
说明它对工业落地最有价值的一点、主要风险，以及什么场景下值得尝试。

格式要求：数学变量和公式必须使用标准 LaTeX，并用 `$...$` 或 `$$...$$` 包裹；不要裸写 `y_hat`、`h^(k)`、`omega = exp(...)`，也不要用反引号包公式。

> **降级说明**：这份笔记基于摘要生成，因为完整版解读失败，错误原因：{type(error).__name__}: {error}
> **一句话总结**：不超过 40 字。
"""

    paper = dict(paper)
    paper["summary_zh"] = complete_with_continuation(
        client,
        prompt,
        max_tokens=min(SUMMARY_MAX_TOKENS, 1400),
        continuation_prompt="继续未完成的摘要版读书笔记，直接从上文中断处接着写，不要重复已经输出的内容。",
    )
    return paper


def build_static_summary_fallback(paper: dict, error: Exception) -> dict:
    paper = dict(paper)
    summary = (
        "## 一、论文定位\n"
        "这篇论文的自动深读在生成时失败，以下仅保留基于摘要的最小化信息，建议后续人工复查原文。\n\n"
        "## 二、核心方法\n"
        f"摘要显示其主要关注的问题是：{paper['abstract']}\n\n"
        "## 三、实验与可信度\n"
        "本次自动流程未能稳定生成完整实验解读，论文的具体数据集、baseline 与提升数字请以原文为准。\n\n"
        "## 四、工程含义\n"
        "建议仅将这篇论文视为待补读条目，暂时不要直接据此做工程决策。\n\n"
        f"> **降级说明**：自动解读失败，错误原因：{type(error).__name__}: {error}\n"
        "> **一句话总结**：该论文需要人工补读后再纳入正式日报结论。"
    )
    paper["summary_zh"] = _clean_generated_markdown(summary)
    return paper


def summarize_paper_safely(client: OpenAI, paper: dict) -> dict:
    try:
        return summarize_paper(client, paper)
    except Exception as exc:
        print(f"    [警告] 完整版解读失败，降级为摘要版：{exc}")
        try:
            return summarize_paper_with_abstract_fallback(client, paper, exc)
        except Exception as fallback_exc:
            print(f"    [警告] 摘要版解读也失败，改用静态兜底：{fallback_exc}")
            return build_static_summary_fallback(paper, fallback_exc)


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


def generate_daily_overview_with_fallback(
    client: OpenAI,
    papers: list[dict],
    date_str: str,
) -> str:
    try:
        return generate_daily_overview(client, papers, date_str)
    except Exception as exc:
        print(f"[警告] 今日概述生成失败，降级为简版综述：{exc}")
        titles = "；".join(p["title"] for p in papers[:3])
        prompt = f"""你是推荐系统方向的研究员。请仅基于以下论文标题与摘要，写一段 180-260 字的中文简版综述，说明共同主题、最值得工业界关注的方向，以及一个风险提醒。

日期：{date_str}
论文：{titles}

要求：
1. 直接输出正文，不加标题
2. 不要逐篇复述
3. 写完整，不要半句话收尾
"""
        try:
            return complete_with_continuation(
                client,
                prompt,
                max_tokens=min(DAILY_OVERVIEW_MAX_TOKENS, 420),
                continuation_prompt="继续未完成的简版综述，直接接着上文写完，不要重复。",
            )
        except Exception as fallback_exc:
            print(f"[警告] 简版综述也失败，改用静态兜底：{fallback_exc}")
            return (
                f"{date_str} 这批论文主要围绕推荐表示学习、序列建模与生成式推荐展开。"
                "由于自动综述生成失败，这里先保留静态占位版本：建议优先关注能在不明显增加线上延迟的前提下提升表示质量、长期兴趣建模或冷启动效果的方法；"
                "涉及复杂生成链路、额外索引结构或多阶段训练的方案，需要重点评估训练成本、可解释性和部署风险。"
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
    day_dir = os.path.join(POSTS_DIR, date_str)
    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, "index.md")
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
        papers[i - 1] = summarize_paper_safely(client, paper)
        if i < len(papers):
            time.sleep(0.3)  # 避免触发速率限制

    print("[DeepSeek] 生成今日概述...")
    overview = generate_daily_overview_with_fallback(client, papers, date_str)

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
    failed_dates = []
    for target_date in target_dates:
        try:
            path = generate_post_for_date(client, target_date)
        except Exception as exc:
            failed_dates.append((target_date.isoformat(), str(exc)))
            print(f"[错误] {target_date.isoformat()} 生成失败：{exc}")
            continue
        if path:
            generated_paths.append(path)

    if failed_dates:
        print("[警告] 以下日期生成失败：")
        for date_str, error in failed_dates:
            print(f"  - {date_str}: {error}")

    if not generated_paths:
        print("[完成] 没有生成任何日报。")
        if failed_dates:
            sys.exit(1)


if __name__ == "__main__":
    main()
