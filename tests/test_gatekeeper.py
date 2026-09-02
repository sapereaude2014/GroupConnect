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


if __name__ == "__main__":
    unittest.main()
