"""
Telegraph Publishing and Outbound Auto-Formatting Utilities for GroupConnect.
Provides seamless publishing to Telegraph for long messages and Markdown tables.
"""

import json
import logging
import os
import re
import unicodedata
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("groupconnect.channels.extensions.telegraph")

ALLOWED_TAGS = {
    'a', 'aside', 'b', 'blockquote', 'br', 'code', 'em',
    'figcaption', 'figure', 'h3', 'h4', 'hr', 'i', 'iframe',
    'img', 'li', 'ol', 'p', 'pre', 's', 'strong', 'u', 'ul', 'video'
}


# ── Table Rendering ──
#
# Two converters exist:
# 1. Fullwidth preformatted text (preferred, used inside Telegraph pages):
#    Telegraph does not support <table> nodes, so tables are emitted as <pre>
#    blocks. Telegram's Instant View renders those as monospaced dark "code"
#    cards. To guarantee column alignment on ANY client font, the table is
#    written entirely in fullwidth characters (CJK glyphs and fullwidth forms
#    all share the exact same 1em advance width in CJK fonts), so the layout
#    never depends on the device's monospace font metrics.
# 2. Inline monospace code block (fallback only, delivered directly in chat
#    when Telegraph is disabled or publishing fails).


def _to_fullwidth(s: str) -> str:
    """Map ASCII to fullwidth forms (kept for backward compatibility)."""
    out = []
    for ch in s:
        o = ord(ch)
        if ch == ' ':
            out.append('\u3000')
        elif 0x21 <= o <= 0x7E:
            out.append(chr(o + 0xFEE0))
        elif ch == '\u00B7':
            out.append('\u30FB')
        else:
            out.append(ch)
    return ''.join(out)


def _display_width(s: str) -> int:
    """Calculate display width of a string in monospace columns (CJK/Emoji = 2, ASCII = 1)."""
    w = 0
    for ch in s:
        if unicodedata.category(ch) in ('Mn', 'Me', 'Cf'):
            continue
        o = ord(ch)
        if (0x1F300 <= o <= 0x1F9FF) or (0x2600 <= o <= 0x27BF) or unicodedata.east_asian_width(ch) in ('W', 'F'):
            w += 2
        else:
            w += 1
    return w


def _pad_right(s: str, target_width: int) -> str:
    """Pad string to target display width with standard ASCII trailing spaces."""
    return s + ' ' * max(0, target_width - _display_width(s))


def _wrap_cell(text: str, max_width: int) -> List[str]:
    """Wrap cell text on natural word boundaries (spaces, slashes, punctuation) within max_width."""
    if not text or max_width <= 0:
        return [text]
    lines = []
    for raw_part in text.split("\n"):
        part = raw_part.strip()
        while _display_width(part) > max_width:
            cur_w = 0
            best_split = -1
            delims = {" ", "/", ",", ";", "-", "|", "，", "、", "；", "：", ":", "+", "（", "）", "(", ")"}
            for i, ch in enumerate(part):
                w = 2 if ((0x1F300 <= ord(ch) <= 0x1F9FF) or (0x2600 <= ord(ch) <= 0x27BF) or unicodedata.east_asian_width(ch) in ('W', 'F')) else 1
                if cur_w + w > max_width:
                    break
                cur_w += w
                if ch in delims:
                    best_split = i + 1

            if best_split > 0 and (
                _display_width(part[:best_split]) >= max(max_width * 0.4, 4)
                or part[best_split - 1] in {" ", "，", "、", "；", "：", ":"}
            ):
                lines.append(part[:best_split].strip())
                part = part[best_split:].strip()
            else:
                # No delimiter found within max_width, break by character
                cut_idx = 0
                cw = 0
                for i, ch in enumerate(part):
                    w = 2 if ((0x1F300 <= ord(ch) <= 0x1F9FF) or (0x2600 <= ord(ch) <= 0x27BF) or unicodedata.east_asian_width(ch) in ('W', 'F')) else 1
                    if cw + w > max_width:
                        break
                    cw += w
                    cut_idx = i + 1
                lines.append(part[:cut_idx].strip())
                part = part[cut_idx:].strip()

        if part:
            lines.append(part)
    return lines if lines else [""]


def table_rows_to_preformatted_text(
    headers: List[str],
    data_rows: List[List[str]],
    max_col_width: Optional[int] = None,
) -> str:
    """Render a table as a clean, borderless monospace table (WeChat-style).

    - No vertical lines (│) or crosses (┼); columns are separated by clean whitespace gaps.
    - Every column is strictly left-aligned at its designated horizontal offset.
    - Clean horizontal divider rules (───) separate headers and multi-line rows.
    - Natural halfwidth ASCII numbers/English preserved without distortion.
    - Dynamic mobile budgeting guarantees tables stay within screen width (<= 34 chars).
    """
    if not data_rows:
        return ""
    if not headers:
        num_cols = len(data_rows[0]) if data_rows else 0
    else:
        num_cols = len(headers)
    if num_cols == 0:
        return ""

    def _norm(row: List[str]) -> List[str]:
        return (list(row) + [""] * num_cols)[:num_cols]

    norm_headers = _norm(headers)
    norm_data = [_norm(r) for r in data_rows]
    all_rows = [norm_headers] + norm_data

    natural_w = [max(_display_width(str(r[i]).strip()) for r in all_rows) for i in range(num_cols)]

    gap = "  " if num_cols >= 3 else "   "
    gap_w = _display_width(gap)

    if max_col_width is not None and max_col_width > 0:
        col_w = [max(min(nw, max_col_width), 1) for nw in natural_w]
    else:
        # Smart mobile-first budget (target total width <= 34 characters)
        if num_cols == 1:
            col_w = [min(natural_w[0], 32)]
        elif num_cols == 2:
            # 2 columns: target safe width <= 34
            nw0, nw1 = natural_w[0], natural_w[1]
            if nw0 + gap_w + nw1 <= 34:
                col_w = [max(nw0, 1), max(nw1, 1)]
            else:
                w0 = min(nw0, 12)
                rem = max(34 - gap_w - w0, 14)
                w1 = min(nw1, rem)
                col_w = [max(w0, 1), max(w1, 1)]
        elif num_cols == 3:
            # 3 columns: target safe width <= 34
            total_nat = sum(natural_w) + gap_w * 2
            if total_nat <= 34:
                col_w = [max(nw, 1) for nw in natural_w]
            else:
                col_w = [max(min(nw, 10), 1) for nw in natural_w]
        else:
            col_w = [max(min(nw, 8), 1) for nw in natural_w]

    max_table_w = 0

    def _render_row(cells: List[str]) -> Tuple[List[str], bool]:
        nonlocal max_table_w
        wrapped = [_wrap_cell(str(cells[i]).strip(), col_w[i]) for i in range(num_cols)]
        height = max(len(w) for w in wrapped)
        sublines = []
        for h in range(height):
            parts = []
            for i in range(num_cols):
                val = wrapped[i][h] if h < len(wrapped[i]) else ""
                if i < num_cols - 1:
                    parts.append(_pad_right(val, col_w[i]))
                else:
                    parts.append(val)
            while len(parts) > 1 and not parts[-1].strip():
                parts.pop()
            line = gap.join(parts).rstrip()
            sublines.append(line)
            dw = _display_width(line)
            if dw > max_table_w:
                max_table_w = dw
        return sublines, height > 1

    h_lines, _ = _render_row(norm_headers)
    rendered_data = [_render_row(r) for r in norm_data]

    sep = "─" * max(max_table_w, 1)

    lines = []
    lines.extend(h_lines)
    lines.append(sep)

    any_wrapped = any(is_w for _, is_w in rendered_data)
    for idx, (r_lines, _) in enumerate(rendered_data):
        if any_wrapped and idx > 0:
            lines.append(sep)
        lines.extend(r_lines)

    return "\n".join(lines)


def _parse_md_row(line: str) -> List[str]:
    """Parse a single markdown table row into cell values."""
    return [c.strip() for c in line.strip().strip('|').split('|')]


def _table_block_to_monospace(block: str) -> str:
    """Convert a single markdown table block to an open monospace code block.

    Reuses table_rows_to_preformatted_text for consistent cross-channel rendering.
    """
    lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
    if len(lines) < 3:
        return block

    headers = _parse_md_row(lines[0])
    data_rows = [_parse_md_row(l) for l in lines[2:]]
    rendered = table_rows_to_preformatted_text(headers, data_rows)
    if not rendered:
        return block
    return '\n```\n' + rendered + '\n```\n'


# Regex to extract complete markdown table blocks (header + separator + data rows)
_TABLE_BLOCK_RE = re.compile(
    r'((?:^|\n)[ \t]*\|[^\n]+\|[ \t]*\n'       # header row
    r'[ \t]*\|[-:| \t]+\|[ \t]*\n'              # separator row
    r'(?:[ \t]*\|[^\n]+\|[ \t]*\n?)+)',           # data rows (1+)
    re.MULTILINE,
)


def _find_token_file() -> Tuple[str, bool]:
    """Find existing token file or return preferred creation path."""
    custom_env = os.environ.get("TELEGRAPH_TOKEN_FILE")
    if custom_env:
        p = os.path.expanduser(custom_env)
        return p, os.path.exists(p)

    gc_path = os.path.expanduser("~/.config/groupconnect/telegraph_token.json")
    if os.path.exists(gc_path):
        return gc_path, True

    return gc_path, False


async def get_or_create_telegraph_token(author_name: str = "GroupConnect") -> str:
    """Retrieve existing Telegraph token or create a new free account."""
    env_token = os.environ.get("TELEGRAPH_ACCESS_TOKEN")
    if env_token:
        return env_token

    token_file, exists = _find_token_file()
    if exists:
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("access_token"):
                    return data["access_token"]
        except Exception as e:
            logger.warning(f"[Telegraph] Failed reading token file {token_file}: {e}")

    # Create new account via Telegraph API
    try:
        os.makedirs(os.path.dirname(token_file), exist_ok=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post("https://api.telegra.ph/createAccount", json={
                "short_name": "groupconnect",
                "author_name": author_name[:128]
            })
            data = res.json()
            if data.get("ok"):
                token = data["result"]["access_token"]
                with open(token_file, "w", encoding="utf-8") as f:
                    json.dump(data["result"], f, ensure_ascii=False, indent=2)
                logger.info(f"[Telegraph] Created new Telegraph account, token saved to {token_file}")
                return token
            else:
                raise RuntimeError(f"Telegraph createAccount error: {data}")
    except Exception as e:
        logger.error(f"[Telegraph] Failed creating Telegraph account: {e}")
        raise


def _tag_to_node(element: Any) -> Any:
    """Convert BeautifulSoup HTML element to Telegraph AST Node."""
    try:
        from bs4 import NavigableString, Tag
    except ImportError:
        return str(element)

    if isinstance(element, NavigableString):
        text = str(element)
        return text if text.strip() != "" else None

    if not isinstance(element, Tag):
        return None

    tag_name = element.name.lower()

    # Telegraph headings must be h3 or h4
    if tag_name in ['h1', 'h2']:
        tag_name = 'h3'
    elif tag_name in ['h3', 'h4', 'h5', 'h6']:
        tag_name = 'h4'
    elif tag_name in ['div', 'section', 'article', 'main']:
        tag_name = 'p'

    # Telegraph does not support <table> tags. Render tables as fullwidth-
    # aligned preformatted <pre> blocks: Telegram's Instant View shows them as
    # monospaced dark code cards, aligned identically on every device.
    if tag_name == 'table':
        rows = element.find_all('tr')
        if not rows:
            return None

        headers = []
        data_rows = []
        first_row = rows[0]
        ths = first_row.find_all('th')
        if ths:
            headers = [th.get_text().strip() for th in ths]
            data_row_elements = rows[1:]
        else:
            tds = first_row.find_all('td')
            headers = [td.get_text().strip() for td in tds]
            data_row_elements = rows[1:]

        for r in data_row_elements:
            cells = [c.get_text().strip() for c in r.find_all(['td', 'th'])]
            if any(cells):
                data_rows.append(cells)

        if not headers and data_rows:
            headers = [f"列{i+1}" for i in range(len(data_rows[0]))]

        pre_text = table_rows_to_preformatted_text(headers, data_rows)
        if not pre_text:
            return None
        return {"tag": "pre", "children": [pre_text]}

    if tag_name not in ALLOWED_TAGS:
        children = []
        for child in element.children:
            child_node = _tag_to_node(child)
            if child_node:
                if isinstance(child_node, list):
                    children.extend(child_node)
                else:
                    children.append(child_node)
        return children if children else None

    node: Dict[str, Any] = {'tag': tag_name}
    attrs = {}
    if tag_name == 'a' and element.get('href'):
        attrs['href'] = element['href']
    elif tag_name == 'img' and element.get('src'):
        attrs['src'] = element['src']
    if attrs:
        node['attrs'] = attrs

    children = []
    for child in element.children:
        child_node = _tag_to_node(child)
        if child_node:
            if isinstance(child_node, list):
                children.extend(child_node)
            else:
                children.append(child_node)
    if children:
        node['children'] = children

    return node


def markdown_to_nodes(md_text: str) -> List[Any]:
    """Convert Markdown text to Telegraph API compatible JSON node array."""
    try:
        import markdown
        from bs4 import BeautifulSoup

        # Pre-process task lists
        md_text = re.sub(r'^[ \t]*-[ \t]+\[ \][ \t]+', '- ⬜ ', md_text, flags=re.MULTILINE)
        md_text = re.sub(r'^[ \t]*-[ \t]+\[[xX]\][ \t]+', '- ✅ ', md_text, flags=re.MULTILINE)

        html = markdown.markdown(md_text, extensions=['tables', 'fenced_code', 'nl2br'])
        soup = BeautifulSoup(html, 'html.parser')
        root_nodes = []
        for child in soup.children:
            node = _tag_to_node(child)
            if node:
                if isinstance(node, list):
                    root_nodes.extend(node)
                else:
                    root_nodes.append(node)
        return root_nodes
    except Exception as e:
        logger.warning(f"[Telegraph] Rich HTML parsing error: {e}, falling back to paragraph split")
        # Graceful fallback without bs4/markdown
        paras = [p.strip() for p in md_text.split("\n\n") if p.strip()]
        return [{'tag': 'p', 'children': [p]} for p in paras]


async def publish_to_telegraph(
    content: str,
    title: Optional[str] = None,
    author_name: str = "GroupConnect"
) -> Optional[str]:
    """Publish content to Telegraph asynchronously and return the page URL."""
    if not content or not content.strip():
        return None

    try:
        token = await get_or_create_telegraph_token(author_name=author_name)
        page_title = (title or "详细报告")[:64]
        nodes = markdown_to_nodes(content)
        if not nodes:
            nodes = [{'tag': 'p', 'children': [content.strip()]}]

        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post("https://api.telegra.ph/createPage", json={
                "access_token": token,
                "title": page_title,
                "author_name": author_name[:128],
                "content": nodes,
                "return_content": False
            })
            data = res.json()
            if data.get("ok"):
                url = data["result"]["url"]
                logger.info(f"[Telegraph] Successfully published '{page_title}' -> {url}")
                return url
            else:
                logger.error(f"[Telegraph] API error creating page: {data}")
                return None
    except Exception as e:
        logger.error(f"[Telegraph] Request exception while publishing: {e}")
        return None


def has_markdown_table(text: str) -> bool:
    """Check if the text contains a Markdown table structure."""
    if not text or "|" not in text:
        return False
    return bool(re.search(r'\|[^\n]+\|\n\s*\|[-:\s|]+\|\n\s*\|[^\n]+\|', text))


def extract_title(text: str, default_author: str = "GroupConnect") -> str:
    """
    Extract a clean, concise title from Markdown text for Telegraph publishing and chat link.
    1. Check for Markdown headings (# or ##) in the first 3 lines.
    2. Check for bracketed title tags (e.g. 【...】 or [...]).
    3. Fallback to the first non-header sentence (truncated up to 30 chars).
    4. Default fallback: f"{default_author} 详细汇报".
    """
    lines = [line.strip() for line in (text or "").strip().split("\n") if line.strip()]
    if not lines:
        return f"{default_author} 详细汇报"

    # 1. Heading (# or ##) or bracketed header (【...】)
    for line in lines[:3]:
        m = re.match(r"^#+\s+(.+)$", line)
        if m:
            return m.group(1).strip()[:40]
        m2 = re.match(r"^[【\[](.+?)[】\]]$", line)
        if m2 and len(m2.group(1).strip()) <= 30:
            return m2.group(1).strip()

    # 2. First readable conversational sentence
    for line in lines:
        if line.startswith(("#", "|", "-", "*", "`", ">")):
            continue
        clauses = re.split(r"[，。！？；：\n]", line)
        for clause in clauses:
            c = clause.strip()
            if 4 <= len(c) <= 30 and "|" not in c:
                return c
        if len(line) <= 30:
            return line
        return line[:30].rstrip("，、；： ") + "…"

    return f"{default_author} 详细汇报"


def _clean_markdown_for_preview(text: str) -> str:
    """Clean rich markdown syntax from snippet so truncation never cuts entities in half."""
    if not text:
        return ""
    # Strip markdown images and links -> keep link anchor text only
    s = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    # Strip code fences and inline backticks
    s = re.sub(r"```[a-zA-Z0-9_-]*\n?(.*?)```", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    # Strip bold / italic markers
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"_([^_]+)_", r"\1", s)
    # Replace raw square brackets with fullwidth brackets to avoid broken markdown entities
    s = s.replace("[", "【").replace("]", "】")
    # Remove stray markdown symbols that could leave unclosed delimiters
    s = s.replace("*", "").replace("`", "")
    # Escape underscores so function names/variables don't trigger italic parsing in Telegram
    s = re.sub(r"(?<!\\)_", r"\\_", s)
    # Collapse multiple whitespaces
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def extract_first_paragraph(text: str, max_chars: int = 60) -> str:
    """Extract the first natural paragraph/snippet from text (up to max_chars) to place before Telegraph link."""
    if not text or not text.strip():
        return ""
    stripped = text.strip()
    # If text starts with structured content (table/code), do not extract as natural intro
    if stripped.startswith(("|", "```")):
        return ""

    # If text starts with markdown headings or bracketed headers, skip them to find body intro
    lines = stripped.split("\n")
    idx = 0
    while idx < len(lines) and (
        lines[idx].strip().startswith("#")
        or re.match(r"^[【\[].+?[】\]]$", lines[idx].strip())
        or not lines[idx].strip()
    ):
        idx += 1

    target = "\n".join(lines[idx:]).strip() if idx < len(lines) else ""
    if not target:
        target = stripped

    if not target or target.startswith(("|", "```")):
        return ""

    # Candidate selection: try \n\n first, then \n, else the whole target
    if "\n\n" in target:
        candidate = target.split("\n\n", 1)[0].strip()
    elif "\n" in target:
        candidate = target.split("\n", 1)[0].strip()
    else:
        candidate = target

    # If candidate itself has a single newline followed by structured items (lists/tables/code/quotes)
    if "\n" in candidate:
        first_line = candidate.split("\n", 1)[0].strip()
        rest = candidate.split("\n", 1)[1].strip()
        if rest.startswith(("- ", "* ", "1. ", "2. ", "|", "```", "> ")):
            candidate = first_line

    if not candidate or candidate.startswith(("|", "```")):
        return ""

    # Strip rich markdown syntax before length check and truncation
    candidate = _clean_markdown_for_preview(candidate)
    if not candidate:
        return ""

    if len(candidate) <= max_chars:
        return candidate
    return candidate[:max_chars].rstrip("，、；： \\") + "…"


# Fold replies longer than this many characters into a Telegraph page.
# Hard-coded (not config-exposed) to keep the config surface minimal;
# tests may pass an explicit threshold to exercise other boundaries.
AUTO_TELEGRAPH_THRESHOLD = 100


def _strip_blockquotes(text: str) -> str:
    """Remove Markdown blockquote lines (lines starting with '>') for threshold measurement."""
    if not text:
        return ""
    s = re.sub(r"(?m)^[ \t]*>.*$", "", text)
    # Collapse blank lines left behind by removed quote lines
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


async def process_outbound_text(
    reply_text: str,
    threshold: int = AUTO_TELEGRAPH_THRESHOLD,
    author_name: str = "GroupConnect"
) -> str:
    """
    Process outbound reply text:
    1. If threshold > 0 and len(text excluding blockquotes) > threshold, publish to Telegraph.
       The first paragraph is prepended before the link, keeping natural conversational context in chat.
       Tables within the body render as fullwidth-aligned preformatted code
       cards (Instant View "black code block" style, aligned on every device).
    2. Graceful fallback on any failure returns original text (tables fall
       back to the legacy inline monospace conversion).
    """
    if not reply_text:
        return reply_text

    # 1. Unified threshold: if text (excluding blockquotes) exceeds threshold,
    #    publish to Telegraph. Blockquotes don't count toward the length check.
    is_over_threshold = threshold > 0 and len(_strip_blockquotes(reply_text)) > threshold

    if is_over_threshold:
        title = extract_title(reply_text, default_author=author_name)
        safe_title = title.replace("[", "【").replace("]", "】").strip()
        url = await publish_to_telegraph(reply_text, title=safe_title, author_name=author_name)
        if url:
            safe_url = urllib.parse.quote(url, safe=":/%#?=@[]!$&'()*+,;")
            first_p = extract_first_paragraph(reply_text)
            if first_p:
                return f"{first_p}\n📄 [{safe_title}]({safe_url})"
            return f"📄 [{safe_title}]({safe_url})"
        else:
            logger.warning("[Telegraph] Auto-telegraph publish failed, falling back to expandable blockquote")
            if has_markdown_table(reply_text):
                text = _TABLE_BLOCK_RE.sub(lambda m: _table_block_to_monospace(m.group(1)), reply_text)
            else:
                text = reply_text
            text = re.sub(r'\n{3,}', '\n\n', text).strip()
            # HTML entity escape: blockquote is sent with parse_mode=HTML, so
            # raw < > & in the body would break entity parsing or leak tags.
            text = (
                text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            return f'<blockquote expandable>{text}</blockquote>'

    # 3. Under-threshold text stays in chat; tables within it are rendered as
    #    monospaced code blocks (Telegram has no native table support, raw
    #    Markdown pipes would render as broken pipes on mobile).
    if has_markdown_table(reply_text):
        return _TABLE_BLOCK_RE.sub(lambda m: _table_block_to_monospace(m.group(1)), reply_text)

    return reply_text
