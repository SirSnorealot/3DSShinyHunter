from __future__ import annotations

import struct


BLOCK_SIZE = 56

BLOCK_POSITION = [
    [0,0,0,0,0,0,1,1,2,3,2,3,1,1,2,3,2,3,1,1,2,3,2,3],
    [1,1,2,3,2,3,0,0,0,0,0,0,2,3,1,1,3,2,2,3,1,1,3,2],
    [2,3,1,1,3,2,2,3,1,1,3,2,0,0,0,0,0,0,3,2,3,2,1,1],
    [3,2,3,2,1,1,3,2,3,2,1,1,3,2,3,2,1,1,0,0,0,0,0,0],
]


def _crypt(data: bytes, seed: int, start: int, end: int) -> bytes:
    result = bytearray()
    temp = seed
    for i in range(start, end, 2):
        temp = (temp * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        result.append(data[i] ^ ((temp >> 16) & 0xFF))
        result.append(data[i + 1] ^ ((temp >> 24) & 0xFF))
    return bytes(result)


def _unshuffle(blocks: bytes, sv: int) -> bytes:
    result = bytearray()
    for block in range(4):
        start = BLOCK_SIZE * BLOCK_POSITION[block][sv]
        result.extend(blocks[start:start + BLOCK_SIZE])
    return bytes(result)


def decrypt_pk67(encrypted: bytes) -> bytes:
    if len(encrypted) < 232:
        raise ValueError("PK6/PK7 core requires at least 232 bytes")

    ec = struct.unpack_from("<I", encrypted, 0)[0]
    sv = ((ec >> 13) & 0x1F) % 24
    blocks = _crypt(encrypted, ec, 8, 232)
    return encrypted[:8] + _unshuffle(blocks, sv)


def parse_pk7(encrypted: bytes) -> dict:
    d = decrypt_pk67(encrypted)
    species = struct.unpack_from("<H", d, 0x08)[0]
    tid = struct.unpack_from("<H", d, 0x0C)[0]
    sid = struct.unpack_from("<H", d, 0x0E)[0]
    pid = struct.unpack_from("<I", d, 0x18)[0]
    shiny_xor = tid ^ sid ^ (pid & 0xFFFF) ^ (pid >> 16)

    return {
        "species": species,
        "tid": tid,
        "sid": sid,
        "pid": pid,
        "shiny_xor": shiny_xor,
        "shiny": shiny_xor < 16,
    }
