"""(Copied from gmcat-drop/cose.py, 2026-11-16, plus verify_owner() for TinyADA's "Verified owner" badge.)
Verify Cardano wallet sign-in signatures (CIP-30 signData / CIP-8 COSE_Sign1) with the standard library only.

verify(signature_hex, key_hex, expected_message) -> stake key hash (hex) of the signing wallet, or raises ValueError.
The wallet must sign with its reward (stake) address; the COSE key's public key must hash to that address's stake
credential, and the Ed25519 signature must be valid over the COSE Sig_structure.
"""
import hashlib

import cardano_keys as ck

_L = 2 ** 252 + 27742317777372353535851937790883648493


# ---- minimal CBOR -------------------------------------------------------------
def _decode(b, i=0):
    ib = b[i]
    major, info = ib >> 5, ib & 31
    i += 1
    if info < 24:
        val = info
    elif info in (24, 25, 26, 27):
        n = 1 << (info - 24)
        val = int.from_bytes(b[i:i + n], "big")
        i += n
    elif info == 31 and major in (2, 3, 4, 5):
        val = None  # indefinite length
    else:
        raise ValueError("unsupported CBOR")
    if major == 0:
        return val, i
    if major == 1:
        return -1 - val, i
    if major in (2, 3):
        if val is None:
            parts = b""
            while b[i] != 0xFF:
                p, i = _decode(b, i)
                parts += p if isinstance(p, bytes) else p.encode()
            return (parts if major == 2 else parts.decode()), i + 1
        raw = b[i:i + val]
        return (raw if major == 2 else raw.decode()), i + val
    if major == 4:
        out = []
        while (val is None and b[i] != 0xFF) or (val is not None and len(out) < val):
            x, i = _decode(b, i)
            out.append(x)
        return out, (i + 1 if val is None else i)
    if major == 5:
        out = {}
        n = 0
        while (val is None and b[i] != 0xFF) or (val is not None and n < val):
            k, i = _decode(b, i)
            v, i = _decode(b, i)
            out[k] = v
            n += 1
        return out, (i + 1 if val is None else i)
    if major == 6:
        return _decode(b, i)  # tag: ignore, return content
    if major == 7:
        return {20: False, 21: True, 22: None}.get(val, val), i
    raise ValueError("bad CBOR")


def cbor_loads(b):
    v, i = _decode(b, 0)
    return v


def _head(major, n):
    if n < 24:
        return bytes([major << 5 | n])
    for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if n < 1 << (8 * size):
            return bytes([major << 5 | info]) + n.to_bytes(size, "big")


def _enc_bytes(x):
    return _head(2, len(x)) + x


def _enc_text(s):
    s = s.encode()
    return _head(3, len(s)) + s


# ---- Ed25519 verify (RFC 8032, cofactored) --------------------------------------
def ed25519_verify(pub, msg, sig):
    if len(pub) != 32 or len(sig) != 64:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    try:
        a = ck._decompress(pub)
        r = ck._decompress(sig[:32])
    except ValueError:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + pub + msg).digest(), "little") % _L
    left = ck._mul(8 * s, ck._B)
    right = ck._mul(8, ck._add(r, ck._mul(h, a)))
    return ck._compress(left) == ck._compress(right)


# ---- COSE_Sign1 -----------------------------------------------------------------
def verify(signature_hex, key_hex, expected_message):
    try:
        sign1 = cbor_loads(bytes.fromhex(signature_hex))
        key = cbor_loads(bytes.fromhex(key_hex))
    except Exception:
        raise ValueError("unreadable signature")
    if not (isinstance(sign1, list) and len(sign1) == 4):
        raise ValueError("not a COSE_Sign1 signature")
    protected_raw, unprotected, payload, sig = sign1
    protected = cbor_loads(protected_raw) if protected_raw else {}
    address = protected.get("address")
    pub = key.get(-2) if isinstance(key, dict) else None
    if not isinstance(address, bytes) or not isinstance(pub, bytes) or protected.get(1) not in (-8, None):
        raise ValueError("signature is missing the address or key")
    # must be a mainnet reward (stake) address: header 0xe1 = key-hash stake credential on mainnet
    if len(address) != 29 or address[0] != 0xE1:
        raise ValueError("please sign with your wallet's stake (reward) address")
    stake_hash = address[1:]
    if hashlib.blake2b(pub, digest_size=28).digest() != stake_hash:
        raise ValueError("the key doesn't belong to that address")
    msg = expected_message.encode()
    hashed = isinstance(unprotected, dict) and unprotected.get("hashed") is True
    want = hashlib.blake2b(msg, digest_size=28).digest() if hashed else msg
    if payload is None:          # "detached" payload: the wallet signed our message without embedding it
        payload = want
    if payload != want:
        raise ValueError("the signed message doesn't match")
    to_sign = bytes([0x84]) + _enc_text("Signature1") + _enc_bytes(protected_raw) + _enc_bytes(b"") + _enc_bytes(payload)
    if not ed25519_verify(pub, to_sign, sig):
        raise ValueError("invalid signature")
    return stake_hash.hex()


def stake_address(stake_hash_hex):
    return ck.bech32_encode("stake", bytes([0xE1]) + bytes.fromhex(stake_hash_hex))


def verify_owner(signature_hex, key_hex, expected_message, address_bytes):
    """TinyADA: did the holder of this receiving address sign our message? CIP-30 signData with a payment address signs
    with that address's payment key, so the COSE "address" header must be exactly this address and the public key must
    hash to its payment credential (bytes 1-28). Script addresses can't sign. Returns True or raises ValueError."""
    try:
        sign1 = cbor_loads(bytes.fromhex(signature_hex))
        key = cbor_loads(bytes.fromhex(key_hex))
    except Exception:
        raise ValueError("unreadable signature")
    if not (isinstance(sign1, list) and len(sign1) == 4):
        raise ValueError("not a COSE_Sign1 signature")
    protected_raw, unprotected, payload, sig = sign1
    protected = cbor_loads(protected_raw) if protected_raw else {}
    pub = key.get(-2) if isinstance(key, dict) else None
    if not isinstance(pub, bytes) or protected.get(1) not in (-8, None):
        raise ValueError("signature is missing the key")
    if address_bytes[0] >> 4 not in (0, 2, 4, 6) or len(address_bytes) < 29:
        raise ValueError("this kind of address can't sign messages")
    if protected.get("address") != address_bytes:
        raise ValueError("the wallet signed with a different address")
    if hashlib.blake2b(pub, digest_size=28).digest() != address_bytes[1:29]:
        raise ValueError("the key doesn't belong to that address")
    msg = expected_message.encode()
    hashed = isinstance(unprotected, dict) and unprotected.get("hashed") is True
    want = hashlib.blake2b(msg, digest_size=28).digest() if hashed else msg
    if payload is None:
        payload = want
    if payload != want:
        raise ValueError("the signed message doesn't match")
    to_sign = bytes([0x84]) + _enc_text("Signature1") + _enc_bytes(protected_raw) + _enc_bytes(b"") + _enc_bytes(payload)
    if not ed25519_verify(pub, to_sign, sig):
        raise ValueError("invalid signature")
    return True
