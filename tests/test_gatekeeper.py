import asyncio
import unittest
from groupagent.core.gatekeeper import Gatekeeper


class TestGatekeeper(unittest.TestCase):
    def test_gatekeeper_rules(self):
        gk = Gatekeeper(
            allowed_chat_ids={-100123},
            allowed_user_ids={8888},
            allowed_usernames={"authorized_user"}
        )

        async def run_suite():
            # 1. Authorized group
            auth, reason = await gk.verify_sender(-100123, "supergroup", {"id": 1111, "username": "anyone"})
            self.assertTrue(auth)
            self.assertEqual(reason, "authorized_group")

            # 2. Unauthorized group
            auth, reason = await gk.verify_sender(-100999, "supergroup", {"id": 1111, "username": "anyone"})
            self.assertFalse(auth)
            self.assertEqual(reason, "unauthorized_group")

            # 3. Authorized private user (by ID)
            auth, reason = await gk.verify_sender(8888, "private", {"id": 8888, "username": "other"})
            self.assertTrue(auth)
            self.assertEqual(reason, "user_id_matched")

            # 4. Authorized private user (by Username)
            auth, reason = await gk.verify_sender(7777, "private", {"id": 7777, "username": "authorized_user"})
            self.assertTrue(auth)
            self.assertEqual(reason, "username_matched")

            # 5. Unauthorized private user
            auth, reason = await gk.verify_sender(6666, "private", {"id": 6666, "username": "stranger"})
            self.assertFalse(auth)
            self.assertEqual(reason, "unauthorized_user")

        asyncio.run(run_suite())


if __name__ == "__main__":
    unittest.main()
