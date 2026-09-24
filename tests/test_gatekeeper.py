import unittest
from groupconnect.core.gatekeeper import Gatekeeper


class TestGatekeeper(unittest.TestCase):
    def test_secure_by_default_lockdown(self):
        # 1. Empty allowlist with allow_open_access=False -> Locked down
        gk = Gatekeeper(allow_open_access=False)
        self.assertFalse(gk.is_whitelist_active())

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Private message rejected
        auth, reason = loop.run_until_complete(
            gk.verify_sender(12345, "private", {"id": 99999, "username": "stranger"})
        )
        self.assertFalse(auth)
        self.assertEqual(reason, "empty_whitelist_lockdown")

        # 2. Empty allowlist with allow_open_access=True -> Explicitly allowed
        gk_open = Gatekeeper(allow_open_access=True)
        auth_open, reason_open = loop.run_until_complete(
            gk_open.verify_sender(12345, "private", {"id": 99999, "username": "stranger"})
        )
        self.assertTrue(auth_open)
        self.assertEqual(reason_open, "open_access_explicitly_allowed")

        loop.close()

    def test_group_authorization(self):
        gk = Gatekeeper(allowed_chat_ids={-100111222})
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        auth_ok, _ = loop.run_until_complete(
            gk.verify_sender(-100111222, "supergroup", {"id": 123, "username": "alice"})
        )
        self.assertTrue(auth_ok)

        auth_deny, reason = loop.run_until_complete(
            gk.verify_sender(-100999999, "supergroup", {"id": 123, "username": "alice"})
        )
        self.assertFalse(auth_deny)
        self.assertEqual(reason, "unauthorized_group")

        loop.close()

    def test_dynamic_group_members_dm_toggle(self):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def mock_checker(group_id: int, user_id: int) -> bool:
            return user_id == 555  # 555 is member of group

        # Case A: allow_group_members_dm = True (default) -> Allowed via dynamic membership
        gk_enabled = Gatekeeper(allowed_chat_ids={-100123}, allow_group_members_dm=True)
        auth_a, reason_a = loop.run_until_complete(
            gk_enabled.verify_sender(555, "private", {"id": 555, "username": "member_bob"}, dynamic_checker=mock_checker)
        )
        self.assertTrue(auth_a)
        self.assertEqual(reason_a, "dynamic_member_verified")

        # Case B: allow_group_members_dm = False -> Rejected even if in group
        gk_disabled = Gatekeeper(allowed_chat_ids={-100123}, allow_group_members_dm=False)
        auth_b, reason_b = loop.run_until_complete(
            gk_disabled.verify_sender(555, "private", {"id": 555, "username": "member_bob"}, dynamic_checker=mock_checker)
        )
        self.assertFalse(auth_b)
        self.assertEqual(reason_b, "unauthorized_user")

        loop.close()

    def test_string_ids_support(self):
        """String IDs used by Feishu, Slack, and WeCom are properly supported without type errors."""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        gk = Gatekeeper(
            allowed_chat_ids={"oc_feishu_group_123"},
            allowed_user_ids={"ou_feishu_user_456"}
        )
        self.assertTrue(gk.is_whitelist_active())

        # 1. Authorized group chat with string chat_id
        auth_group, _ = loop.run_until_complete(
            gk.verify_sender("oc_feishu_group_123", "group", {"id": "ou_someone", "username": "someone"})
        )
        self.assertTrue(auth_group)

        # 2. Unauthorized group chat
        auth_unauth, reason = loop.run_until_complete(
            gk.verify_sender("oc_other_group", "group", {"id": "ou_someone", "username": "someone"})
        )
        self.assertFalse(auth_unauth)
        self.assertEqual(reason, "unauthorized_group")

        # 3. Authorized private DM with string user_id
        auth_dm, _ = loop.run_until_complete(
            gk.verify_sender("ou_feishu_user_456", "private", {"id": "ou_feishu_user_456", "username": "user"})
        )
        self.assertTrue(auth_dm)

        loop.close()


if __name__ == "__main__":
    unittest.main()
