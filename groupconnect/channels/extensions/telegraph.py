"""
Telegraph Publishing and Outbound Auto-Formatting Utilities for GroupConnect.
Provides seamless publishing to Telegraph for long messages and Markdown tables.
"""

import json
import logging
import os
import re
import sys
import unicodedata
from typing import Any, Dict, List, Optional, Tuple, Union

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
    """Map ASCII to fullwidth forms and spaces to U+3000 so every glyph is 1em."""
    out = []
    for ch in s:
        o = ord(ch)
        if ch == ' ':
            out.append('\u3000')
        elif 0x21 <= o <= 0x7E:
            out.append(chr(o + 0xFEE0))
        elif ch == '\u00B7':
            out.append('\u30FB')  # katakana middle dot is unambiguous 1em
        else:
            out.append(ch)
    return ''.join(out)


def _wrap_fullwidth_cell(text: str, width: int) -> List[str]:
    """Wrap fullwidth cell text into chunks of at most `width` characters."""
    if not text:
        return [""]
    if width <= 0:
        return [text]
    lines = []
    for part in text.split("\n"):
        part = part.strip()
        if not part:
            lines.append("")
            continue
        while len(part) > width:
            lines.append(part[:width])
            part = part[width:].lstrip("\u3000 ")
        if part:
            lines.append(part)
    return lines if lines else [""]


def table_rows_to_preformatted_text(
    headers: List[str],
    data_rows: List[List[str]],
    max_col_width: int = 14,
) -> str:
    """Render a table as fullwidth-aligned text for a Telegraph <pre> block.

    Supports automatic cell wrapping when cell content exceeds max_col_width,
    keeping columns strictly aligned and preserving mobile screen readability.
    """
    if not data_rows:
        return ""
    num_cols = max([len(headers)] + [len(r) for r in data_rows])
    if num_cols == 0:
        return ""

    def _norm(row: List[str]) -> List[str]:
        row = (list(row) + [""] * num_cols)[:num_cols]
        return [_to_fullwidth(str(c).strip()) for c in row]

    norm_headers = _norm(headers)
    norm_data = [_norm(r) for r in data_rows]
    all_rows = [norm_headers] + norm_data

    widths = []
    for i in range(num_cols):
        natural_w = max(len(r[i]) for r in all_rows)
        w = natural_w
        if max_col_width and max_col_width > 0:
            w = min(natural_w, max_col_width)
        widths.append(max(w, 1))

    def _render_row(cells: List[str]) -> Tuple[List[str], bool]:
        wrapped = [_wrap_fullwidth_cell(cells[i], widths[i]) for i in range(num_cols)]
        height = max(len(w) for w in wrapped)
        sublines = []
        for h in range(height):
            line_parts = [wrapped[i][h] if h < len(wrapped[i]) else "" for i in range(num_cols)]
            sublines.append(
                "\uff5c".join(
                    c + "\u3000" * (widths[i] - len(c)) for i, c in enumerate(line_parts)
                )
            )
        return sublines, height > 1

    separator = "\uff0b".join("\uff0d" * w for w in widths)
    lines = []

    h_lines, h_wrapped = _render_row(norm_headers)
    lines.extend(h_lines)
    lines.append(separator)

    rendered_data = [_render_row(r) for r in norm_data]
    any_wrapped = h_wrapped or any(is_w for _, is_w in rendered_data)

    for idx, (r_lines, _) in enumerate(rendered_data):
        if any_wrapped and idx > 0:
            lines.append(separator)
        lines.extend(r_lines)

    return "\n".join(lines)


def _display_width(s: str) -> int:
    """Display width of a string (CJK characters = 2, others = 1)."""
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ('W', 'F'):
            w += 2
        else:
            w += 1
    return w


def _pad_right(s: str, target_width: int) -> str:
    """Pad string to target display width with trailing spaces."""
    return s + ' ' * max(0, target_width - _display_width(s))


def _parse_md_row(line: str) -> List[str]:
    """Parse a single markdown table row into cell values."""
    return [c.strip() for c in line.strip().strip('|').split('|')]


def _table_block_to_monospace(block: str) -> str:
    """Convert a single markdown table block to a monospace code block.

    Uses Unicode box-drawing characters for clean borders and spaces for
    CJK-aware column alignment.  Output is wrapped in triple backticks so
    Telegram renders it with a monospaced font.
    """
    lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
    if len(lines) < 3:
        return block

    headers = _parse_md_row(lines[0])
    data_rows = [_parse_md_row(l) for l in lines[2:]]
    num_cols = len(headers)

    # Column widths based on display width (CJK = 2)
    col_w = [0] * num_cols
    for i, h in enumerate(headers):
        col_w[i] = max(col_w[i], _display_width(h))
    for row in data_rows:
        for i, v in enumerate(row):
            if i < num_cols:
                col_w[i] = max(col_w[i], _display_width(v))

    def _fmt_row(cells: List[str]) -> str:
        parts = []
        for i in range(num_cols):
            v = cells[i] if i < len(cells) else ''
            parts.append(_pad_right(v, col_w[i]))
        return '\u2502 ' + ' \u2502 '.join(parts) + ' \u2502'

    def _sep() -> str:
        parts = ['\u2500' * w for w in col_w]
        return '\u251c\u2500' + '\u2500\u253c\u2500'.join(parts) + '\u2500\u2524'

    out = [_fmt_row(headers), _sep()]
    for row in data_rows:
        out.append(_fmt_row(row))

    return '\n```\n' + '\n'.join(out) + '\n```\n'


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


async def process_outbound_text(
    reply_text: str,
    threshold: int = 60,
    author_name: str = "GroupConnect"
) -> str:
    """
    Process outbound reply text:
    1. If threshold > 0 and len(reply_text) > threshold, publish to Telegraph.
       Tables within the body render as fullwidth-aligned preformatted code
       cards (Instant View "black code block" style, aligned on every device).
    2. Graceful fallback on any failure returns original text (tables fall
       back to the legacy inline monospace conversion).
    """
    if not reply_text:
        return reply_text

    # 1. Unified threshold: if text exceeds threshold, publish to Telegraph.
    #    Tables are just a format within the body, not a separate scenario.
    #    If publishing fails, fall back to expandable blockquote.
    is_over_threshold = threshold > 0 and len(reply_text.strip()) > threshold

    if is_over_threshold:
        title = extract_title(reply_text, default_author=author_name)
        url = await publish_to_telegraph(reply_text, title=title, author_name=author_name)
        if url:
            return f"📄 [{title}]({url})"
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
