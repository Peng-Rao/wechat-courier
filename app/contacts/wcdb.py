"""Verified 4.1.13.65 x64 WCDB cipher configuration layout, not master keys.

Adapted from wechatauto-replica, commit
4ec0273a4d1b2f0eac6cb5fe99c5695a56514d17, under Apache-2.0.
Source: https://github.com/fanyuantaier/wechatauto-replica/blob/
4ec0273a4d1b2f0eac6cb5fe99c5695a56514d17/wechatauto/db.py
Changes: strict known layout, selected-salt association, bounded buffers,
mutable key lifetime; no persistence, page decryption, or account guessing.
See licenses/wechatauto-replica-LICENSE.txt and licenses/README.txt.
"""

import re
import struct


CONFIG_NAME = b"com.Tencent.WCDB.Config.Cipher"
XOR_MASK = bytes.fromhex("d2c7442458020000004889442450488b450048844c2448488944254048584c24")
KEY_LITERAL = re.compile(rb"[xX]'([0-9a-fA-F]{64}(?:[0-9a-fA-F]{32})?)'")
MAX_ANCHORS = 32
MAX_STRUCTURES = 128


def config_pointer(node, anchors):
    if len(node) != 0x50:
        return None
    address, length = struct.unpack_from("<QQ", node, 0x10)
    if address not in anchors or length != len(CONFIG_NAME):
        return None
    return struct.unpack_from("<Q", node, 0x28)[0]


def buffer_location(obj):
    if len(obj) != 0x28:
        return None
    address, size = struct.unpack_from("<QQ", obj, 0x8)
    return (address, size) if 0 < size <= 1024 else None


def decoded_keys(blob, salt):
    decoded = bytearray(v ^ XOR_MASK[i % len(XOR_MASK)] for i, v in enumerate(blob))
    try:
        for match in KEY_LITERAL.finditer(decoded):
            material = bytearray.fromhex(match.group(1).decode("ascii"))
            key = None
            try:
                if len(material) == 48 and material[32:] != salt:
                    continue
                key = material[:32]
                yield key
            finally:
                material[:] = b"\0" * len(material)
                if key is not None:
                    key[:] = b"\0" * len(key)
    finally:
        decoded[:] = b"\0" * len(decoded)
