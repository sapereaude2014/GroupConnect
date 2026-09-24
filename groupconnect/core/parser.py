"""
Strict Slash Command Parser for GroupConnect.
Prevents false triggers from body text, punctuation, or similar English vocabulary (e.g. /stopwords).
"""

import re
from typing import Optional, Tuple


def parse_bot_command(text: str, current_bot_username: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Parses a strict slash command from user input.

    Rules:
    - Must start with '/' at index 0.
    - Matches command name (letters, numbers, underscores).
    - Optionally matches target bot username ('@bot_name').
    - If target bot is specified and does NOT match current_bot_username, command is ignored.
    - Trailing content after whitespace is treated as arguments.

    Returns:
      (command_name_lowercase, target_bot_or_none, arguments_string)
    """
    raw = (text or "").strip()
    match = re.match(r"^/([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9_]+))?(?:\s+(.*))?$", raw, re.DOTALL)
    if not match:
        return None, None, ""

    cmd = match.group(1).lower()
    target_bot = match.group(2)
    args = match.group(3) or ""

    if target_bot and target_bot.lower() != current_bot_username.lower():
        return None, None, ""

    return cmd, (target_bot.lower() if target_bot else None), args
