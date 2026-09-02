"""
Chat History Search Utility for GroupConnect Team Ops Assistant.
Searches historical monthly JSONL chat logs beyond the 30-message sliding window.
"""

import argparse
import datetime
import glob
import json
import os
import sys


def search_logs(query: str = None, sender: str = None, days: int = None, logs_dir: str = "inbox/chat_logs", limit: int = 20):
    if not os.path.exists(logs_dir):
        print(f"Log directory '{logs_dir}' not found. No history recorded yet.")
        return []

    log_files = sorted(glob.glob(os.path.join(logs_dir, "*.jsonl")), reverse=True)
    if not log_files:
        print(f"No .jsonl log files found in '{logs_dir}'.")
        return []

    cutoff_time = None
    if days:
        cutoff_time = datetime.datetime.now() - datetime.timedelta(days=days)

    matched = []
    query_lower = query.lower() if query else None
    sender_lower = sender.lower() if sender else None

    for fpath in log_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Time filter
                    ts_str = entry.get("timestamp")
                    if cutoff_time and ts_str:
                        try:
                            dt = datetime.datetime.fromisoformat(ts_str)
                            if dt < cutoff_time:
                                continue
                        except ValueError:
                            pass

                    # Sender filter
                    entry_sender = (entry.get("sender") or "").lower()
                    if sender_lower and sender_lower not in entry_sender:
                        continue

                    # Query text filter
                    entry_text = (entry.get("text") or "").lower()
                    if query_lower and query_lower not in entry_text:
                        continue

                    matched.append(entry)
                    if len(matched) >= limit:
                        break
        except Exception as e:
            print(f"Error reading {fpath}: {e}", file=sys.stderr)

        if len(matched) >= limit:
            break

    return matched


def main():
    parser = argparse.ArgumentParser(description="Search historical chat logs in GroupConnect")
    parser.add_argument("-q", "--query", help="Text keyword to search in chat history")
    parser.add_argument("-s", "--sender", help="Filter messages by sender name/username")
    parser.add_argument("-d", "--days", type=int, help="Search only within the last N days")
    parser.add_argument("-n", "--limit", type=int, default=20, help="Maximum matching messages to return")
    parser.add_argument("--logs-dir", default="inbox/chat_logs", help="Path to chat logs directory")
    args = parser.parse_args()

    results = search_logs(
        query=args.query,
        sender=args.sender,
        days=args.days,
        logs_dir=args.logs_dir,
        limit=args.limit
    )

    if not results:
        print("No matching chat history found.")
        return

    print(f"🔍 Found {len(results)} matching message(s):\n")
    for r in results:
        ts = r.get("timestamp", "N/A")
        sender = r.get("sender", "Unknown")
        text = r.get("text", "")
        att = r.get("attachments", [])
        att_str = f" [Attached: {', '.join(a.get('name', a.get('type', 'file')) for a in att)}]" if att else ""
        print(f"[{ts}] {sender}:{att_str}\n  {text}\n")


if __name__ == "__main__":
    main()
