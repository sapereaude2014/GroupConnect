"""
Security Gatekeeper for GroupConnect.
Enforces default-deny access control, group isolation, and optional dynamic membership verification.
"""

import logging
from typing import Any, Callable, Coroutine, Dict, Optional, Set, Tuple

logger = logging.getLogger("groupconnect.gatekeeper")


class Gatekeeper:
    """Evaluates whether incoming messages and events come from authorized sources."""

    def __init__(
        self,
        allowed_chat_ids: Optional[Set[int]] = None,
        allowed_user_ids: Optional[Set[int]] = None,
        allowed_usernames: Optional[Set[str]] = None,
        allow_open_access: bool = False,
        allow_group_members_dm: bool = True
    ):
        self.allowed_chat_ids: Set[int] = set(allowed_chat_ids or [])
        self.allowed_user_ids: Set[int] = set(allowed_user_ids or [])
        self.allowed_usernames: Set[str] = set(
            u.lower().lstrip("@") for u in (allowed_usernames or [])
        )
        self.allow_open_access: bool = allow_open_access
        self.allow_group_members_dm: bool = allow_group_members_dm

    def is_whitelist_active(self) -> bool:
        return bool(self.allowed_chat_ids or self.allowed_user_ids or self.allowed_usernames)

    async def verify_sender(
        self,
        chat_id: int,
        chat_type: str,
        from_user: Dict[str, Any],
        dynamic_checker: Optional[Callable[[int, int], Coroutine[Any, Any, bool]]] = None
    ) -> Tuple[bool, str]:
        """
        Verifies if an incoming message is authorized under secure-by-default rules.

        Returns:
          (is_authorized, reason_code)
        """
        # If no allowlist configured and open access is NOT explicitly enabled, lock down by default
        if not self.is_whitelist_active():
            if self.allow_open_access:
                return True, "open_access_explicitly_allowed"
            return False, "empty_whitelist_lockdown"

        user_id = from_user.get("id")
        username = (from_user.get("username") or "").lower().lstrip("@")
        is_group = chat_type in ("group", "supergroup", "channel")

        # 1. Group Chat Evaluation
        if is_group:
            if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
                return False, "unauthorized_group"

            # In authorized group, cache sender ID if username matches
            if username and username in self.allowed_usernames and user_id:
                self.allowed_user_ids.add(user_id)

            return True, "authorized_group"

        # 2. Private Chat Evaluation
        if user_id and user_id in self.allowed_user_ids:
            return True, "user_id_matched"

        if username and username in self.allowed_usernames:
            if user_id:
                self.allowed_user_ids.add(user_id)
            return True, "username_matched"

        # 3. Dynamic Group Membership Check (if enabled by config)
        if self.allow_group_members_dm and user_id and self.allowed_chat_ids and dynamic_checker:
            for gid in self.allowed_chat_ids:
                try:
                    is_member = await dynamic_checker(gid, user_id)
                    if is_member:
                        self.allowed_user_ids.add(user_id)
                        logger.info(f"[SECURITY] Dynamically verified user {user_id} via group {gid}.")
                        return True, "dynamic_member_verified"
                except Exception as e:
                    logger.warning(f"[SECURITY] Error running dynamic membership check: {e}")

        return False, "unauthorized_user"
