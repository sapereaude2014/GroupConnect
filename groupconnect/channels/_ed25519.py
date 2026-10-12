"""Minimal self-contained RFC 8032 Ed25519 implementation (sign + verify).

Used by the Discord webhook channel to verify X-Signature-Ed25519 headers.
Kept dependency-free on purpose: some supported runtimes ship crypto libraries
without Ed25519 support (e.g. trimmed pycryptodome builds). Correctness is
pinned against the RFC 8032 test vectors in tests/test_webhook_security.py.
"""

import hashlib

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _xx_from_y(y: int) -> int:
    if (_D * y * y + 1) % _P == 0:
        raise ValueError("point not on curve")
    return (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P


def _sqrt_or_none(xx: int):
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if (x * x - xx) % _P != 0:
        return None
    return x


def _edwards_add(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * pow(1 + _D * x1 * x2 * y1 * y2, _P - 2, _P) % _P
    y3 = (y1 * y2 + x1 * x2) * pow(1 - _D * x1 * x2 * y1 * y2, _P - 2, _P) % _P
    return (x3, y3)


def _scalarmult(P, e: int):
    Q = (0, 1)
    while e > 0:
        if e & 1:
            Q = _edwards_add(Q, P)
        P = _edwards_add(P, P)
        e >>= 1
    return Q


def _point_encode(P) -> bytes:
    x, y = P
    return int(y | ((x & 1) << 255)).to_bytes(32, "little")


def _point_decode(b: bytes):
    if len(b) != 32:
        raise ValueError("bad point length")
    v = int.from_bytes(b, "little")
    sign = (v >> 255) & 1
    y = v & ((1 << 255) - 1)
    if y >= _P:
        raise ValueError("non-canonical y")
    x = _sqrt_or_none(_xx_from_y(y))
    if x is None:
        raise ValueError("point not on curve")
    if x % 2 != sign:
        x = (_P - x) % _P
    return (x, y)


def _clamp(h: bytes) -> int:
    return 2 ** 254 + sum(2 ** i * ((h[i // 8] >> (i % 8)) & 1) for i in range(3, 254))


# Base point (x even, y = 4/5)
_GY = (4 * pow(5, _P - 2, _P)) % _P
_GX = _sqrt_or_none(_xx_from_y(_GY))
if _GX % 2 != 0:
    _GX = _P - _GX
_G = (_GX, _GY)


def publickey(seed: bytes) -> bytes:
    """Derives the 32-byte Ed25519 public key from a 32-byte seed."""
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    return _point_encode(_scalarmult(_G, _clamp(_sha512(seed))))


def sign(seed: bytes, message: bytes) -> bytes:
    """Signs a message with a 32-byte seed; returns the 64-byte signature.

    Exported for tests / local tooling; production channels only verify.
    """
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    h = _sha512(seed)
    a = _clamp(h)
    pub = _point_encode(_scalarmult(_G, a))
    r = int.from_bytes(_sha512(h[32:64] + message), "little")
    R = _point_encode(_scalarmult(_G, r))
    k = int.from_bytes(_sha512(R + pub + message), "little")
    S = (r + k * a) % _L
    return R + S.to_bytes(32, "little")


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verifies an Ed25519 signature (RFC 8032, canonical-S enforced)."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        A = _point_decode(public_key)
        R = _point_decode(signature[:32])
    except ValueError:
        return False
    S = int.from_bytes(signature[32:], "little")
    if S >= _L:
        return False
    k = int.from_bytes(_sha512(signature[:32] + public_key + message), "little")
    # Verify [S]G == R + [k]A
    left = _scalarmult(_G, S)
    right = _edwards_add(R, _scalarmult(A, k))
    return left == right
