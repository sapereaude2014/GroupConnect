"""
Telegraph Publishing Utility for GroupConnect.
Converts Markdown text / files into instant Telegraph pages with zero authentication needed.
"""

import argparse
import json
import re
import sys
import httpx

TELEGRAPH_API = "https://api.telegra.ph"


def create_account(short_name: str = "Assistant", author_name: str = "Assistant") -> str:
    """Creates a temporary Telegraph account and returns the access_token."""
    url = f"{TELEGRAPH_API}/createAccount"
    resp = httpx.post(url, json={"short_name": short_name, "author_name": author_name}, timeout=15)
    data = resp.json()
    if data.get("ok"):
        return data["result"]["access_token"]
    raise RuntimeError(f"Failed to create Telegraph account: {data}")


def markdown_to_nodes(md_text: str) -> list:
    """Converts a subset of Markdown to Telegraph DOM node representation."""
    lines = md_text.split("\n")
    nodes = []

    in_code_block = False
    code_buffer = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code_block:
                nodes.append({"tag": "pre", "children": ["\n".join(code_buffer)]})
                code_buffer = []
                in_code_block = False
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_buffer.append(line)
            continue

        if not stripped:
            continue

        # Headers
        if stripped.startswith("### "):
            nodes.append({"tag": "h4", "children": [stripped[4:]]})
        elif stripped.startswith("## "):
            nodes.append({"tag": "h3", "children": [stripped[3:]]})
        elif stripped.startswith("# "):
            nodes.append({"tag": "h3", "children": [stripped[2:]]})
        # Blockquotes
        elif stripped.startswith("> "):
            nodes.append({"tag": "blockquote", "children": [stripped[2:]]})
        # Unordered Lists
        elif stripped.startswith("- ") or stripped.startswith("* "):
            nodes.append({"tag": "p", "children": ["• " + stripped[2:]]})
        else:
            nodes.append({"tag": "p", "children": [line]})

    if in_code_block and code_buffer:
        nodes.append({"tag": "pre", "children": ["\n".join(code_buffer)]})

    return nodes


def publish_page(title: str, content_nodes: list, access_token: str, author_name: str = "Assistant") -> str:
    """Publishes a Telegraph page and returns its URL."""
    url = f"{TELEGRAPH_API}/createPage"
    payload = {
        "access_token": access_token,
        "title": title[:250],
        "author_name": author_name,
        "content": json.dumps(content_nodes),
        "return_content": False
    }
    resp = httpx.post(url, data=payload, timeout=20)
    data = resp.json()
    if data.get("ok"):
        return data["result"]["url"]
    raise RuntimeError(f"Failed to publish Telegraph page: {data}")


def main():
    parser = argparse.ArgumentParser(description="Publish Markdown to Telegraph Instant View")
    parser.add_argument("--title", required=True, help="Page title")
    parser.add_argument("--input", help="Input Markdown file path")
    parser.add_argument("--text", help="Raw Markdown text")
    parser.add_argument("--author", default="Family Assistant", help="Author name")
    args = parser.parse_args()

    md_content = ""
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            md_content = f.read()
    elif args.text:
        md_content = args.text
    else:
        md_content = sys.stdin.read()

    if not md_content.strip():
        print("Error: Empty content.", file=sys.stderr)
        sys.exit(1)

    try:
        token = create_account(short_name=args.author[:32], author_name=args.author)
        nodes = markdown_to_nodes(md_content)
        page_url = publish_page(title=args.title, content_nodes=nodes, access_token=token, author_name=args.author)
        print(f"PAGE_URL: {page_url}")
    except Exception as e:
        print(f"Error publishing: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
