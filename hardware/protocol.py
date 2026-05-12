"""
Python translation of MFCOptojumpLedStatus protocol parser.
- Mirrors protocol.h/protocol.cpp behavior with fixes for a few obvious offsets.
- datalength denotes only the payload length (not including type/length fields).
- Uses struct for binary layout parsing.

API
----
- protocol_parser(buf: bytearray) -> (ret: int, frame_type: int|None, ack: AckData|None, subpack: UploadDataSubPack|None, status: StatusData|None)
  On success (ret == 0), returns the parsed structure for the detected frame and removes the consumed bytes from buf.
  On partial/incomplete or invalid frames, consumes data as needed to resync and returns -1 if nothing complete is parsed this round.

Notes
-----
- Header: 4 bytes magic + 1 byte type + 2 bytes datalength, little-endian for the 16-bit length.
- CRC: CRC-8 polynomial 0x07, init 0x00, no reflection, xorout 0x00; computed over (type + length + payload).
- Tail: 4 bytes magic (0xA5A5A5A5).
- DATA_REPORT payload layout: DATA_INFO (frameIdx: uint32 big-endian, packNum: u8, packIdx: u8) + raw bytes.
- STATUS_REPORT payload layout: type: u8, value: u8 (fixing the apparent bug in C++ code that overwrote type twice).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import struct

# =====================
# Protocol constants
# =====================
FRAME_HEADER_FLAG = 0x5A5A5A5A
FRAME_TAIL_FLAG = 0xA5A5A5A5

FRAME_HEADER_LEN = 4  # only the 4-byte magic
FRAME_TYPE_LEN = 1
FRAME_LENGTH_LEN = 2
FRAME_CRC_LEN = 1
FRAME_TAIL_LEN = 4

# minimal frame: header(4) + type(1) + len(2) + crc(1) + tail(4)
MIN_PACKET_LENGTH = FRAME_HEADER_LEN + FRAME_TYPE_LEN + FRAME_LENGTH_LEN + FRAME_CRC_LEN + FRAME_TAIL_LEN

# Types
E_ACK = 0x80
E_STATUS_REPORT = 0x81
E_DATA_REPORT = 0x82
E_CMD = 0x00
E_UNKNOWN_TYPE = 0xFF


# =====================
# Data structures
# =====================
@dataclass
class AckData:
    ACK: int = 0


@dataclass
class StatusData:
    type: int = 0
    value: int = 0


@dataclass
class UploadDataSubPack:
    bufferLen: int = 0
    frameIdx: int = 0
    packNum: int = 0
    packIdx: int = 0
    buffer: bytes = b""


# =====================
# CRC-8 (poly 0x07, init 0x00, no-reflect, xorout 0x00)
# =====================
def crc8_poly_07(data: bytes) -> int:
    crc = 0x00
    poly = 0x07
    for b in data:
        crc ^= b
        for _ in range(8):
            if (crc & 0x80) != 0:
                crc = ((crc << 1) & 0xFF) ^ poly
            else:
                crc = (crc << 1) & 0xFF
    return crc & 0xFF


# =====================
# Parser
# =====================
def _find_header(buf: bytes, start: int = 0) -> int:
    magic = struct.pack('<I', FRAME_HEADER_FLAG)
    idx = buf.find(magic, start)
    return idx


def protocol_parser(buf: bytearray) -> Tuple[int, Optional[int], Optional[AckData], Optional[UploadDataSubPack], Optional[StatusData]]:
    """Parse one frame from the buffer if available.
    - Mutates buf in place to drop consumed bytes (either a full frame or junk up to next viable position).
    - Returns (ret, type, ack, subpack, status). ret==0 on success, -1 if no full valid frame found.
    """
    idx = 0
    bHaveParsed = False

    while idx <= len(buf) - MIN_PACKET_LENGTH:
        # Seek header
        idx = _find_header(buf, idx)
        if idx < 0:
            break

        # Ensure we have at least minimal header/type/length to read
        if len(buf) - idx < MIN_PACKET_LENGTH:
            break  # wait for more data

        # Read header magic, type, datalength (little-endian)
        try:
            # header magic already matched, but read fields
            # After 4-byte magic, next 1 byte type, 2 bytes length
            frame_type = buf[idx + 4]
            datalength = struct.unpack_from('<H', buf, idx + 5)[0]
        except struct.error:
            break

        packlen = FRAME_TYPE_LEN + FRAME_LENGTH_LEN + datalength  # bytes covered by CRC
        total_len = FRAME_HEADER_LEN + packlen + FRAME_CRC_LEN + FRAME_TAIL_LEN

        # If not enough bytes for this frame, wait for more
        if len(buf) - idx < total_len:
            break

        # Compute and verify CRC (over type+length+data)
        crc_region = bytes(buf[idx + FRAME_HEADER_LEN : idx + FRAME_HEADER_LEN + packlen])
        calc = crc8_poly_07(crc_region)
        recv_crc = buf[idx + FRAME_HEADER_LEN + packlen]

        # Read and verify tail
        tail_off = idx + FRAME_HEADER_LEN + packlen + FRAME_CRC_LEN
        frametail = struct.unpack_from('<I', buf, tail_off)[0]

        if calc != recv_crc or frametail != FRAME_TAIL_FLAG:
            # Drop this frame and continue searching
            del buf[: idx + total_len]
            idx = 0
            continue

        # Valid frame; parse by type
        payload_off = idx + FRAME_HEADER_LEN + FRAME_TYPE_LEN + FRAME_LENGTH_LEN
        payload = bytes(buf[payload_off : payload_off + datalength])

        ack: Optional[AckData] = None
        subpack: Optional[UploadDataSubPack] = None
        status: Optional[StatusData] = None

        if frame_type == E_ACK:
            ack_val = payload[0] if len(payload) >= 1 else 0
            ack = AckData(ACK=ack_val)
        elif frame_type == E_STATUS_REPORT:
            t = payload[0] if len(payload) >= 1 else 0
            v = payload[1] if len(payload) >= 2 else 0
            status = StatusData(type=t, value=v)
        elif frame_type == E_DATA_REPORT:
            if len(payload) >= 6:
                frameIdx = struct.unpack('!I', payload[0:4])[0]  # network (big-endian)
                packNum = payload[4]
                packIdx = payload[5]
                body = payload[6:]
                subpack = UploadDataSubPack(
                    bufferLen=len(body),
                    frameIdx=frameIdx,
                    packNum=packNum,
                    packIdx=packIdx,
                    buffer=body,
                )
            else:
                # payload too short; treat as invalid and drop
                del buf[: idx + total_len]
                idx = 0
                continue
        else:
            # Unknown type; report as unknown and still consume
            frame_type = E_UNKNOWN_TYPE

        # Consume the frame from buffer
        del buf[: idx + total_len]
        return 0, frame_type, ack, subpack, status

    # No full valid frame parsed this round; optionally drop junk before first header to mimic C++ resync
    first = _find_header(buf, 0)
    if first > 0:
        del buf[:first]
    return -1, None, None, None, None


# Convenience class wrapper (optional)
class ProtocolParser:
    def __init__(self):
        pass

    def parse(self, buf: bytearray):
        return protocol_parser(buf)
