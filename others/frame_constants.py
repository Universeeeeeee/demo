class FrameConstants:
    # 帧格式定义
    FRAME_HEAD = b'\x5A\x5A\x5A\x5A'  # 帧头 4字节
    FRAME_TAIL = b'\xA5\xA5\xA5\xA5'  # 帧尾 4字节
    
    # 帧基本信息
    # 使用 2 字节长度字段 (little-endian)
    MIN_FRAME_LENGTH = 12  # 最小帧长度 (帧头4B + 类型1B + 长度2B + 数据0B + CRC1B + 帧尾4B)
    MAX_DATA_LENGTH = 65535  # 数据段最大长度
    
    # 帧位置索引
    HEAD_LEN = 4          # 帧头长度
    TAIL_LEN = 4          # 帧尾长度
    CTRL_INDEX = 4        # 控制字位置（帧头后）
    LENGTH_INDEX = 5      # 数据长度起始位置（2 字节，小端）
    DATA_START = 7        # 数据开始位置（帧头4 + ctrl1 + len2 = 7）