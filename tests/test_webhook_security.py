"""Security regression tests for inbound webhook channels (issue #1).

Covers the identity-spoofing class of bugs reported against the Discord/WeCom
webhook listeners — now extended to Slack which shared the same flaw:
- requests without a valid platform signature must be rejected (401/403)
- channels without verification keys configured must fail CLOSED
- validly signed/encrypted requests must still be dispatched
- webhook servers must bind 127.0.0.1 by default
- the pure-Python Ed25519 verifier must match the RFC 8032 test vectors
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import socket
import struct
import time
import unittest
import urllib.parse

import httpx

from groupconnect.channels._ed25519 import publickey as ed25519_publickey
from groupconnect.channels._ed25519 import sign as ed25519_sign
from groupconnect.channels._ed25519 import verify as ed25519_verify
from groupconnect.channels.discord import DiscordChannel
from groupconnect.channels.slack import SlackChannel
from groupconnect.channels.wecom import WeComChannel, _wecom_signature
from groupconnect.core.config import GatewayConfig


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Capture:
    def __init__(self):
        self.messages = []

    async def __call__(self, msg):
        self.messages.append(msg)


def _serve_requests(channel, port, requests):
    """Drives a channel's raw HTTP handler with real requests.

    requests: list of {"method": "GET"|"POST", "url": str, "content"?: bytes, "headers"?: dict}
    Returns the list of httpx.Response objects.
    """
    async def run():
        server = await asyncio.start_server(channel._handle_http_client, "127.0.0.1", port)
        responses = []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for req in requests:
                    if req.get("method") == "GET":
                        r = await client.get(req["url"])
                    else:
                        r = await client.post(
                            req["url"], content=req.get("content"), headers=req.get("headers") or {}
                        )
                    responses.append(r)
            await asyncio.sleep(0.1)  # let async dispatch tasks settle
        finally:
            server.close()
            await server.wait_closed()
        return responses

    return asyncio.run(run())


class TestEd25519KnownAnswers(unittest.TestCase):
    """RFC 8032 §7.1 TEST 1 — pins the pure-Python Ed25519 implementation."""

    def test_rfc8032_test_vector_1(self):
        seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        pub_expected = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        sig_expected = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        )
        self.assertEqual(ed25519_publickey(seed), pub_expected)
        sig = ed25519_sign(seed, b"")
        self.assertEqual(sig, sig_expected)
        self.assertTrue(ed25519_verify(pub_expected, b"", sig))
        # Tampered message / signature must fail
        self.assertFalse(ed25519_verify(pub_expected, b"tampered", sig))
        bad = bytearray(sig)
        bad[10] ^= 0xFF
        self.assertFalse(ed25519_verify(pub_expected, b"", bytes(bad)))
        # Non-canonical S (S + group order) must fail
        L = 2 ** 252 + 27742317777372353535851937790883648493
        noncanon = sig[:32] + (int.from_bytes(sig[32:], "little") + L).to_bytes(32, "little")
        self.assertFalse(ed25519_verify(pub_expected, b"", noncanon))


class TestDiscordWebhookSecurity(unittest.TestCase):
    def _make_channel(self, port, public_key_hex=""):
        cfg = GatewayConfig({
            "platform": "discord",
            "discord_bot_token": "t",
            "discord_public_key": public_key_hex,
            "webhook_port": port,
        })
        cap = _Capture()
        return DiscordChannel(cfg, cap), cap

    def test_default_bind_is_loopback(self):
        ch, _ = self._make_channel(_free_port())
        self.assertEqual(ch.bind_host, "127.0.0.1")

    def test_fail_closed_without_public_key(self):
        port = _free_port()
        ch, cap = self._make_channel(port)  # no discord_public_key configured
        body = json.dumps({
            "message": {"id": "1", "channel_id": 111, "author": {"id": "a", "username": "victim_alice"}, "content": "hi"}
        }).encode()
        ts = str(int(time.time()))
        responses = _serve_requests(ch, port, [
            {"method": "POST", "url": f"http://127.0.0.1:{port}/webhook", "content": body},
            {"method": "POST", "url": f"http://127.0.0.1:{port}/webhook", "content": body,
             "headers": {"X-Signature-Ed25519": "00" * 64, "X-Signature-Timestamp": ts}},
        ])
        self.assertEqual([r.status_code for r in responses], [401, 401])
        self.assertEqual(cap.messages, [])

    def test_rejects_forged_and_accepts_signed(self):
        port = _free_port()
        seed = os.urandom(32)
        pub = ed25519_publickey(seed)
        ch, cap = self._make_channel(port, public_key_hex=pub.hex())
        body = json.dumps({
            "message": {"id": "1", "channel_id": 111, "author": {"id": "attacker", "username": "victim_alice"}, "content": "hello"}
        }).encode()
        ts = str(int(time.time()))
        good_sig = ed25519_sign(seed, ts.encode() + body).hex()
        stale_ts = str(int(time.time()) - 4000)
        stale_sig = ed25519_sign(seed, stale_ts.encode() + body).hex()
        url = f"http://127.0.0.1:{port}/webhook"
        responses = _serve_requests(ch, port, [
            {"method": "POST", "url": url, "content": body},  # unsigned
            {"method": "POST", "url": url, "content": body,
             "headers": {"X-Signature-Ed25519": "ab" * 64, "X-Signature-Timestamp": ts}},  # wrong sig
            {"method": "POST", "url": url, "content": body,
             "headers": {"X-Signature-Ed25519": "zz" * 64, "X-Signature-Timestamp": ts}},  # not hex
            {"method": "POST", "url": url, "content": body,
             "headers": {"X-Signature-Ed25519": stale_sig, "X-Signature-Timestamp": stale_ts}},  # replay
            {"method": "POST", "url": url, "content": body,
             "headers": {"X-Signature-Ed25519": good_sig, "X-Signature-Timestamp": ts}},  # valid
        ])
        self.assertEqual([r.status_code for r in responses], [401, 401, 401, 401, 200])
        self.assertEqual(len(cap.messages), 1)
        self.assertEqual(cap.messages[0].text, "hello")
        self.assertEqual(cap.messages[0].chat_id, 111)


class TestSlackWebhookSecurity(unittest.TestCase):
    def _make_channel(self, port, signing_secret=""):
        cfg = GatewayConfig({
            "platform": "slack",
            "slack_bot_token": "xoxb-t",
            "slack_signing_secret": signing_secret,
            "webhook_port": port,
        })
        cap = _Capture()
        return SlackChannel(cfg, cap), cap

    def _sign(self, secret, ts, body):
        basestring = f"v0:{ts}:".encode() + body
        return "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()

    def test_default_bind_is_loopback(self):
        ch, _ = self._make_channel(_free_port())
        self.assertEqual(ch.bind_host, "127.0.0.1")

    def test_fail_closed_without_signing_secret(self):
        port = _free_port()
        ch, cap = self._make_channel(port)
        body = json.dumps({"type": "url_verification", "challenge": "abc"}).encode()
        responses = _serve_requests(ch, port, [
            {"method": "POST", "url": f"http://127.0.0.1:{port}/events", "content": body},
        ])
        self.assertEqual([r.status_code for r in responses], [401])
        self.assertEqual(cap.messages, [])

    def test_rejects_forged_and_accepts_signed(self):
        port = _free_port()
        secret = "test-signing-secret"
        ch, cap = self._make_channel(port, signing_secret=secret)
        event = json.dumps({
            "type": "event_callback",
            "event": {"type": "message", "channel": "C1", "channel_type": "im", "user": "U9", "text": "hi bot", "ts": "1.2"},
        }).encode()
        ts = str(int(time.time()))
        stale_ts = str(int(time.time()) - 4000)
        url = f"http://127.0.0.1:{port}/events"
        responses = _serve_requests(ch, port, [
            {"method": "POST", "url": url, "content": event},  # unsigned
            {"method": "POST", "url": url, "content": event,
             "headers": {"X-Slack-Signature": "v0=" + "0" * 64, "X-Slack-Request-Timestamp": ts}},  # wrong sig
            {"method": "POST", "url": url, "content": event,
             "headers": {"X-Slack-Signature": self._sign(secret, stale_ts, event), "X-Slack-Request-Timestamp": stale_ts}},  # replay
            {"method": "POST", "url": url, "content": event,
             "headers": {"X-Slack-Signature": self._sign(secret, ts, event), "X-Slack-Request-Timestamp": ts}},  # valid
        ])
        self.assertEqual([r.status_code for r in responses], [401, 401, 401, 200])
        self.assertEqual(len(cap.messages), 1)
        self.assertEqual(cap.messages[0].text, "hi bot")
        self.assertEqual(cap.messages[0].chat_id, "C1")

    def test_signed_url_verification_echoes_challenge(self):
        port = _free_port()
        secret = "test-signing-secret"
        ch, cap = self._make_channel(port, signing_secret=secret)
        body = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()
        ts = str(int(time.time()))
        responses = _serve_requests(ch, port, [
            {"method": "POST", "url": f"http://127.0.0.1:{port}/events", "content": body,
             "headers": {"X-Slack-Signature": self._sign(secret, ts, body), "X-Slack-Request-Timestamp": ts}},
        ])
        self.assertEqual(responses[0].status_code, 200)
        self.assertEqual(responses[0].json()["challenge"], "abc123")
        self.assertEqual(cap.messages, [])


class TestWeComWebhookSecurity(unittest.TestCase):
    CORP = "ww_test_corp"

    def _make_channel(self, port, token="", aes_key="", corp_id=CORP):
        cfg = GatewayConfig({
            "platform": "wecom",
            "wecom_corp_id": corp_id,
            "wecom_corp_secret": "s",
            "wecom_callback_token": token,
            "wecom_encoding_aes_key": aes_key,
            "webhook_port": port,
        })
        cap = _Capture()
        return WeComChannel(cfg, cap), cap

    def _aes_key(self):
        return base64.b64encode(os.urandom(32)).decode()[:43]

    def _encrypt(self, plain, aes_key, corp_id=CORP):
        from Crypto.Cipher import AES
        key = base64.b64decode(aes_key + "=")
        msg = plain.encode("utf-8")
        raw = os.urandom(16) + struct.pack(">I", len(msg)) + msg + corp_id.encode("utf-8")
        pad = 32 - len(raw) % 32
        raw += bytes([pad]) * pad
        return base64.b64encode(AES.new(key, AES.MODE_CBC, key[:16]).encrypt(raw)).decode()

    def _signed_url(self, port, token, ts, nonce, enc, sig=None, include_echostr=False):
        if sig is None:
            sig = _wecom_signature(token, ts, nonce, enc)
        params = {"msg_signature": sig, "timestamp": ts, "nonce": nonce}
        if include_echostr:
            params["echostr"] = enc
        return f"http://127.0.0.1:{port}/callback?{urllib.parse.urlencode(params)}"

    def test_default_bind_is_loopback(self):
        ch, _ = self._make_channel(_free_port())
        self.assertEqual(ch.bind_host, "127.0.0.1")

    def test_fail_closed_without_keys(self):
        port = _free_port()
        ch, cap = self._make_channel(port)  # no token / AES key configured
        forged_plain = "<xml><FromUserName><![CDATA[attacker]]></FromUserName><Content><![CDATA[/backup]]></Content></xml>"
        responses = _serve_requests(ch, port, [
            {"method": "POST", "url": f"http://127.0.0.1:{port}/callback", "content": forged_plain.encode()},
            {"method": "GET", "url": f"http://127.0.0.1:{port}/callback?echostr=whatever"},
        ])
        self.assertEqual([r.status_code for r in responses], [403, 403])
        self.assertEqual(cap.messages, [])

    def test_rejects_forged_and_accepts_signed(self):
        port = _free_port()
        token = "callback-token"
        aes_key = self._aes_key()
        ch, cap = self._make_channel(port, token=token, aes_key=aes_key)
        xml_plain = ("<xml><FromUserName><![CDATA[alice]]></FromUserName>"
                     "<Content><![CDATA[你好]]></Content><MsgType><![CDATA[text]]></MsgType>"
                     "<ChatId><![CDATA[wrk123]]></ChatId></xml>")
        enc = self._encrypt(xml_plain, aes_key)
        ts = str(int(time.time()))
        nonce = "n1"
        body = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>".encode()

        # Old-style forged plaintext XML (what the vulnerable code used to accept)
        forged = "<xml><FromUserName><![CDATA[attacker]]></FromUserName><Content><![CDATA[/backup]]></Content></xml>".encode()
        responses = _serve_requests(ch, port, [
            {"method": "POST", "url": self._signed_url(port, token, ts, nonce, enc, sig="deadbeef"), "content": body},
            {"method": "POST", "url": f"http://127.0.0.1:{port}/callback", "content": forged},
            {"method": "POST", "url": self._signed_url(port, token, ts, nonce, enc), "content": body},
        ])
        self.assertEqual([r.status_code for r in responses], [403, 403, 200])
        self.assertEqual(len(cap.messages), 1)
        self.assertEqual(cap.messages[0].text, "你好")
        self.assertEqual(cap.messages[0].sender_name, "alice")
        self.assertEqual(cap.messages[0].chat_id, "wrk123")

    def test_corp_id_mismatch_rejected(self):
        port = _free_port()
        token = "callback-token"
        aes_key = self._aes_key()
        ch, cap = self._make_channel(port, token=token, aes_key=aes_key)
        # Correctly signed payload encrypted for a DIFFERENT corp id
        enc = self._encrypt("<xml><Content><![CDATA[x]]></Content></xml>", aes_key, corp_id="ww_evil_corp")
        ts = str(int(time.time()))
        body = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>".encode()
        responses = _serve_requests(ch, port, [
            {"method": "POST", "url": self._signed_url(port, token, ts, "n1", enc), "content": body},
        ])
        self.assertEqual(responses[0].status_code, 403)
        self.assertEqual(cap.messages, [])

    def test_get_echo_verification(self):
        port = _free_port()
        token = "callback-token"
        aes_key = self._aes_key()
        ch, _ = self._make_channel(port, token=token, aes_key=aes_key)
        enc = self._encrypt("echo-plain-123", aes_key)
        ts = str(int(time.time()))
        responses = _serve_requests(ch, port, [
            {"method": "GET", "url": self._signed_url(port, token, ts, "n1", enc, sig="bad", include_echostr=True)},
            {"method": "GET", "url": self._signed_url(port, token, ts, "n1", enc, include_echostr=True)},
        ])
        self.assertEqual(responses[0].status_code, 403)
        self.assertEqual(responses[1].status_code, 200)
        self.assertEqual(responses[1].text, "echo-plain-123")


if __name__ == "__main__":
    unittest.main()
