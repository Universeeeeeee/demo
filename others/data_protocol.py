import struct
from typing import Dict, Any

# === 类型定义(type 字段) ===
E_CMD = 0x00            # 下行命令
E_ACK = 0x80            # 上行应答/错误位图
E_STATUS_REPORT = 0x81  # 上行状态上报（键值对）
E_DATA_REPORT = 0x82    # 上行数据上报（业务数据）


# === CRC-8 (poly=0x07, init=0x00, refin=False, refout=False, xorout=0x00) ===
def crc8_msb(data: bytes, poly=0x07, init=0x00, xorout=0x00) -> int:
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:  # MSB-first，符合 refin=False
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc ^ xorout


# === 构造帧 ===
def build_frame(ptype: int, payload: bytes) -> bytes:
    """按协议构造一帧。
    帧结构: HEAD(4) + TYPE(1) + LEN(2 little-endian) + PAYLOAD(N) + CRC(1) + TAIL(4)
    CRC 覆盖: TYPE + LEN(LE) + PAYLOAD
    """
    header = b'\x5A\x5A\x5A\x5A'   # 帧头
    tail = b'\xA5\xA5\xA5\xA5'     # 帧尾
    length = len(payload)              # 载荷长度

    # 小端长度
    len_le = struct.pack('<H', length)
    crc = crc8_msb(struct.pack('B', ptype) + len_le + payload)
    crc_b = struct.pack('B', crc)

    return header + struct.pack('B', ptype) + len_le + payload + crc_b + tail


def _parse_payload(ptype: int, payload: bytes) -> Dict[str, Any]:
    """根据类型解析载荷，返回结构化字段。保持尽可能健壮：长度不足则返回空结构。"""
    info: Dict[str, Any] = {}
    if ptype == E_CMD:
        if len(payload) >= 1:
            info['cmd'] = payload[0]
    elif ptype == E_ACK:
        if len(payload) >= 1:
            info['ack_bitmap'] = payload[0]
    elif ptype == E_STATUS_REPORT:
        # [type: uint8][value: uint8]
        if len(payload) >= 2:
            info['status_type'] = payload[0]
            info['value'] = payload[1]  # 注意：第二字节应赋给 value
    elif ptype == E_DATA_REPORT:
        # DATA_INFO(6): [frameIdx(4,BE)][packNum(1)][packIdx(1)] + data
        if len(payload) >= 6:
            frame_idx_be = payload[0:4]
            frame_idx = int.from_bytes(frame_idx_be, 'big')
            pack_num = payload[4]
            pack_idx = payload[5]
            data = payload[6:]
            info.update({
                'frameIdx': frame_idx,
                'packNum': pack_num,
                'packIdx': pack_idx,
                'data_part': data,
            })
            # 从 data 前12字节提取 96 个 LED 位（LSB→MSB），越界保护
            led_bits = []
            led_bytes = data[:12]
            for i, b in enumerate(led_bytes):
                for bit in range(8):
                    if len(led_bits) >= 96:
                        break
                    led_bits.append((b >> bit) & 0x1)
                if len(led_bits) >= 96:
                    break
            info['led_bits'] = led_bits  # 长度<=96
            info['led_count'] = 96
    return info


# === 解析帧 ===
def parse_frame(frame: bytes) -> Dict[str, Any]:
    if len(frame) < 12:
        raise ValueError('frame too short')
    if frame[:4] != b'\x5A\x5A\x5A\x5A' or frame[-4:] != b'\xA5\xA5\xA5\xA5':
        raise ValueError('Invalid frame: wrong header or tail')

    ptype = frame[4]
    length = struct.unpack('<H', frame[5:7])[0]  # 小端
    payload = frame[7:7 + length]
    if len(payload) != length:
        raise ValueError('Invalid frame: length mismatch')
    recv_crc = frame[7 + length]

    # CRC 覆盖 TYPE + LEN(LE) + PAYLOAD
    calc_crc = crc8_msb(struct.pack('B', ptype) + struct.pack('<H', length) + payload)
    if recv_crc != calc_crc:
        raise ValueError('CRC check failed')

    parsed_payload = _parse_payload(ptype, payload)
    # 兼容旧调用：保留 'data' 键指向 payload，以便 UI 继续展示 hex
    return {
        'type': ptype,
        'length': length,
        'payload': payload,
        'data': payload,
        'fields': parsed_payload,
    }


# === 示例测试 ===
if __name__ == '__main__':
    # 构造一个 E_DATA_REPORT 的示例：DATA_INFO(6) + 3字节数据
    frame_idx = 1
    pack_num = 1
    pack_idx = 1
    data_part = b'\x01\x02\x03'
    data_info = frame_idx.to_bytes(4, 'big') + bytes([pack_num, pack_idx])
    payload = data_info + data_part
    frame = build_frame(E_DATA_REPORT, payload)
    print('构造帧:', frame.hex(' '))

    parsed = parse_frame(frame)
    print('解析结果:', parsed)
