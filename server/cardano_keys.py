"""Cardano address derivation from an account public key (watch-only), standard library only.

Implements BIP32-Ed25519 public (non-hardened) child derivation and CIP-1852 base addresses:
  account key (m/1852'/1815'/n')  ->  role 0 / index i  (receiving)  and  role 2 / index 0 (staking)
  address = bech32("addr", 0x01 | blake2b-224(payment key) | blake2b-224(stake key))   [mainnet base address]
No private keys are involved: the account public key can create addresses but can't spend.
"""
import hashlib
import hmac

# ---- bech32 ----
_CH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(v):
    g = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    c = 1
    for x in v:
        b = c >> 25
        c = (c & 0x1ffffff) << 5 ^ x
        for i in range(5):
            c ^= g[i] if (b >> i) & 1 else 0
    return c


def _hrp(h):
    return [ord(x) >> 5 for x in h] + [0] + [ord(x) & 31 for x in h]


def _bits(data, f, t, pad=True):
    acc = bits = 0
    out = []
    m = (1 << t) - 1
    for v in data:
        acc = (acc << f) | v
        bits += f
        while bits >= t:
            bits -= t
            out.append((acc >> bits) & m)
    if pad and bits:
        out.append((acc << (t - bits)) & m)
    elif not pad and (bits >= f or ((acc << (t - bits)) & m)):
        raise ValueError("bad padding")
    return out


def bech32_decode(s):
    s = s.strip().lower()
    hrp, _, rest = s.rpartition("1")
    d = [_CH.index(x) for x in rest]
    if _polymod(_hrp(hrp) + d) != 1:
        raise ValueError("bad checksum")
    return hrp, bytes(_bits(d[:-6], 5, 8, False))


def bech32_encode(hrp, data):
    d = _bits(data, 8, 5)
    c = _polymod(_hrp(hrp) + d + [0] * 6) ^ 1
    return hrp + "1" + "".join(_CH[x] for x in d + [(c >> 5 * (5 - i)) & 31 for i in range(6)])


# ---- ed25519 points (extended coordinates) ----
_P = 2 ** 255 - 19
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _inv(x):
    return pow(x, _P - 2, _P)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P:
        x = x * _I % _P
    if (x * x - xx) % _P:
        raise ValueError("not a curve point")
    return x


_BY = 4 * _inv(5) % _P
_BX = _xrecover(_BY)
if _BX & 1:
    _BX = _P - _BX
_B = (_BX, _BY, 1, _BX * _BY % _P)


def _add(p, q):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = t1 * 2 * _D * t2 % _P
    d = z1 * 2 * z2 % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s, p):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _decompress(b):
    y = int.from_bytes(b, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _xrecover(y)
    if x & 1 != sign:
        x = _P - x
    return (x, y, 1, x * y % _P)


def _compress(p):
    x, y, z, _ = p
    zi = _inv(z)
    x, y = x * zi % _P, y * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


# ---- BIP32-Ed25519 public derivation ----
def derive_public(xpub, index):
    """Non-hardened child of an extended public key (64 bytes: key | chain code)."""
    if index >= 2 ** 31:
        raise ValueError("public derivation can't do hardened indexes")
    a, c = xpub[:32], xpub[32:]
    i = index.to_bytes(4, "little")
    z = hmac.new(c, b"\x02" + a + i, hashlib.sha512).digest()
    zl = int.from_bytes(z[:28], "little")
    child = _compress(_add(_decompress(a), _mul(8 * zl, _B)))
    cc = hmac.new(c, b"\x03" + a + i, hashlib.sha512).digest()[32:]
    return child + cc


def parse_account_key(s):
    """Accepts bech32 'xpub1…' / 'acct_xvk1…' or 128 hex characters."""
    s = s.strip()
    if s.lower().startswith(("xpub1", "acct_xvk1")):
        hrp, raw = bech32_decode(s)
    else:
        raw = bytes.fromhex(s)
    if len(raw) != 64:
        raise ValueError("an account public key is 64 bytes, got %d" % len(raw))
    _decompress(raw[:32])  # must be a valid curve point
    return raw


def _h224(b):
    return hashlib.blake2b(b, digest_size=28).digest()


def base_address(account_xpub, index, role=0, network=1):
    pay = derive_public(derive_public(account_xpub, role), index)[:32]
    stake = derive_public(derive_public(account_xpub, 2), 0)[:32]
    return bech32_encode("addr" if network == 1 else "addr_test", bytes([network & 15]) + _h224(pay) + _h224(stake))
