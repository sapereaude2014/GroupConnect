#!/usr/bin/env python3
import json
import os
import re
import sys
import markdown
import requests
from bs4 import BeautifulSoup, NavigableString, Tag

TOKEN_FILE = os.path.expanduser("~/.config/mama-family-bot/telegraph_token.json")
ALLOWED_TAGS = {
    'a', 'aside', 'b', 'blockquote', 'br', 'code', 'em', 
    'figcaption', 'figure', 'h3', 'h4', 'hr', 'i', 'iframe', 
    'img', 'li', 'ol', 'p', 'pre', 's', 'strong', 'u', 'ul', 'video'
}

def get_or_create_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "access_token" in data:
                    return data["access_token"]
        except Exception:
            pass
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    res = requests.post("https://api.telegra.ph/createAccount", json={
        "short_name": "family_bot",
        "author_name": "家庭管家"
    }).json()
    if res.get("ok"):
        token = res["result"]["access_token"]
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(res["result"], f)
        return token
    raise RuntimeError(f"Failed to create Telegraph account: {res}")

def tag_to_node(element):
    if isinstance(element, NavigableString):
        text = str(element)
        if text.strip() == "":
            return None
        return text

    if not isinstance(element, Tag):
        return None

    tag_name = element.name.lower()

    # Map headings to h3 / h4 (Telegraph only allows h3 and h4 for titles)
    if tag_name in ['h1', 'h2']:
        tag_name = 'h3'
    elif tag_name in ['h3', 'h4', 'h5', 'h6']:
        tag_name = 'h4'
    elif tag_name in ['div', 'section', 'article', 'main']:
        tag_name = 'p'

    # Special handling for tables: Telegraph does not support table tags,
    # so we convert <table> into clean <p> / <ul> items!
    if tag_name == 'table':
        nodes = []
        rows = element.find_all('tr')
        headers = []
        for r_idx, row in enumerate(rows):
            ths = row.find_all('th')
            tds = row.find_all('td')
            if ths and not headers:
                headers = [th.get_text().strip() for th in ths]
                continue
            cells = tds if tds else ths
            if not cells:
                continue
            cell_texts = [c.get_text().strip() for c in cells]
            if headers and len(headers) == len(cell_texts):
                parts = [f"【{h}】{v}" for h, v in zip(headers, cell_texts) if v]
                line = " • " + " ｜ ".join(parts)
            else:
                line = " • " + " ｜ ".join([v for v in cell_texts if v])
            nodes.append({'tag': 'p', 'children': [line]})
        return nodes

    # If tag is not in allowed tags, unpack its children
    if tag_name not in ALLOWED_TAGS:
        children = []
        for child in element.children:
            child_node = tag_to_node(child)
            if child_node:
                if isinstance(child_node, list):
                    children.extend(child_node)
                else:
                    children.append(child_node)
        return children if children else None

    # Normal allowed tag
    node = {'tag': tag_name}
    attrs = {}
    if tag_name == 'a' and element.get('href'):
        attrs['href'] = element['href']
    elif tag_name == 'img' and element.get('src'):
        attrs['src'] = element['src']
    if attrs:
        node['attrs'] = attrs

    children = []
    for child in element.children:
        child_node = tag_to_node(child)
        if child_node:
            if isinstance(child_node, list):
                children.extend(child_node)
            else:
                children.append(child_node)
    if children:
        node['children'] = children

    return node

def markdown_to_nodes(md_text):
    # Pre-process task lists: - [ ] -> ⬜ , - [x] -> ✅
    md_text = re.sub(r'^[ \t]*-[ \t]+\[ \][ \t]+', '- ⬜ ', md_text, flags=re.MULTILINE)
    md_text = re.sub(r'^[ \t]*-[ \t]+\[[xX]\][ \t]+', '- ✅ ', md_text, flags=re.MULTILINE)

    html = markdown.markdown(md_text, extensions=['tables', 'fenced_code', 'nl2br'])
    soup = BeautifulSoup(html, 'html.parser')
    root_nodes = []
    for child in soup.children:
        node = tag_to_node(child)
        if node:
            if isinstance(node, list):
                root_nodes.extend(node)
            else:
                root_nodes.append(node)
    return root_nodes

def publish_file(file_path, title=None):
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    if not title:
        first_line = content.split("\n")[0].strip()
        if first_line.startswith("# "):
            title = first_line[2:].strip()
        else:
            title = os.path.splitext(os.path.basename(file_path))[0]
    token = get_or_create_token()
    nodes = markdown_to_nodes(content)
    res = requests.post("https://api.telegra.ph/createPage", json={
        "access_token": token,
        "title": title[:64],
        "author_name": "家庭管家",
        "content": nodes,
        "return_content": False
    }).json()
    if res.get("ok"):
        return res["result"]["url"]
    else:
        print("Telegraph Error:", res)
    return None

if __name__ == "__main__":
    if len(sys.argv) > 1:
        url = publish_file(sys.argv[1])
        print("TELEGRAPH_URL:", url)
