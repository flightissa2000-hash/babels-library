"""Web Push: notifications for the iPhone app (a web app on the Home Screen can't run in the background; Apple's push
service wakes it). The computer has its own key pair (VAPID, kept in the settings); each iPhone hands over a
subscription (an address at Apple's push service plus its keys), and a message is encrypted for that phone alone
(RFC 8291, aes128gcm) and signed (RFC 8292) before it's sent. Nothing but the encrypted message goes to Apple."""
import base64
import json
import ssl
import urllib.error
import os
import struct
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor_py"))
from cryptography.hazmat.primitives import hashes, serialization                      # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec                             # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature     # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM                       # noqa: E402
from cryptography.hazmat.primitives.kdf.hkdf import HKDF                             # noqa: E402
import certifi                                                                       # noqa: E402

import store

SUBJECT = "https://flightissa2000-hash.github.io/babels-library-web/"


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    s = str(s)
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _raw_public(key):
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


_key = None


def _vapid():
    """The computer's signing key, made once and kept in its own file (not in the settings the app's pages can read)."""
    global _key
    if _key:
        return _key
    p = os.path.join(store.DATA_DIR, "push_vapid.der")
    if os.path.exists(p):
        with open(p, "rb") as f:
            _key = serialization.load_der_private_key(f.read(), None)
        return _key
    _key = ec.generate_private_key(ec.SECP256R1())
    with open(p + ".tmp", "wb") as f:
        f.write(_key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    os.replace(p + ".tmp", p)
    return _key


def public_key():
    """What the iPhone needs to subscribe (its applicationServerKey)."""
    return _b64(_raw_public(_vapid()))


def _hkdf(salt, ikm, info, n):
    return HKDF(hashes.SHA256(), n, salt, info).derive(ikm)


def encrypt(sub, payload):
    """RFC 8291: only the phone that subscribed can read it."""
    ua_pub = _unb64(sub["keys"]["p256dh"])
    auth = _unb64(sub["keys"]["auth"])
    eph = ec.generate_private_key(ec.SECP256R1())
    eph_pub = _raw_public(eph)
    shared = eph.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + ua_pub + eph_pub, 32)
    salt = os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack(">IB", 4096, len(eph_pub)) + eph_pub + body


def _jwt(audience):
    """RFC 8292: proves the message comes from this computer (the key the phone subscribed with)."""
    head = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = _b64(json.dumps({"aud": audience, "exp": int(time.time()) + 12 * 3600, "sub": SUBJECT}).encode())
    r, s = decode_dss_signature(_vapid().sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"{head}.{claims}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def send(sub, message):
    """Returns the push service's answer: 201 sent · 404/410 the phone unsubscribed (forget it)."""
    u = urllib.parse.urlparse(sub["endpoint"])
    req = urllib.request.Request(sub["endpoint"], data=encrypt(sub, json.dumps(message).encode()), method="POST", headers={
        "TTL": str(24 * 3600), "Urgency": "normal", "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
        "Authorization": f"vapid t={_jwt(f'{u.scheme}://{u.netloc}')}, k={public_key()}"})
    try:
        # (Python on Windows doesn't fetch roots it hasn't seen, and Apple's push service uses one: a bundle of them)
        with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context(cafile=certifi.where())) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
