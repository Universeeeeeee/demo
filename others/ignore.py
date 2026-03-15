"""
一维 LED 阵列遮挡/恢复事件识别（忽略特定编号）
------------------------------------------------

功能概述：
- 输入为随时间变化的 LED 状态帧序列（每帧为按字节先后顺序排列的位序列）。
- LED 编号以“位索引（从 1 开始）”为准。
- 在所有分析步骤中，完全忽略编号为 1、58、61 的 LED：
  - 不参与遮挡/恢复判断；不计入连续遮挡段长度；不作为事件边界。
- 仅依赖有效 LED 的顺序关系（不做物理位置重排或插值）。

返回：
- segments_by_frame：每帧的遮挡连续段列表（基于过滤后的序列计算，起止均不包含被忽略编号）。
- events：跨帧比较得到的事件（start/continue/recover），输出不包含被忽略编号。

使用说明：
- 默认认为 bit=0 表示“遮挡”，bit=1 表示“恢复/未遮挡”。
- 若设备协议使用不同定义，可通过 blocked_value 参数调整。
- 位顺序默认按“LSB→MSB”（bit_order='lsb'）；如需 MSB→LSB，请设置 bit_order='msb'。
"""

from __future__ import annotations

from typing import Iterable, List, Tuple, Dict, Any, Sequence, Optional, Set


IGNORED_DEFAULT: Set[int] = {1, 58, 61}


def _bytes_to_bits(frame: Sequence[int] | bytes | bytearray, bit_order: str = "lsb") -> List[int]:
	"""将一帧（按字节排列）转换为位列表（每位为 0/1）。

	参数：
	  - frame: bytes/bytearray 或 整数列表（0..255）。
	  - bit_order: 'lsb' 表示每字节从低位到高位；'msb' 则相反。
	返回：长度为 8*len(frame) 的 0/1 列表。
	"""
	bits: List[int] = []
	# 统一为整数字节序列
	if isinstance(frame, (bytes, bytearray)):
		byte_vals = list(frame)
	else:
		byte_vals = list(frame)

	for b in byte_vals:
		if not (0 <= b <= 255):
			raise ValueError("字节值必须在 0..255 范围内")
		if bit_order == "lsb":
			# 低位在前：bit0, bit1, ..., bit7
			bits.extend([(b >> i) & 1 for i in range(8)])
		elif bit_order == "msb":
			# 高位在前：bit7, bit6, ..., bit0
			bits.extend([(b >> i) & 1 for i in reversed(range(8))])
		else:
			raise ValueError("bit_order 仅支持 'lsb' 或 'msb'")
	return bits


def _filter_ignored(bits: List[int], ignored: Set[int]) -> List[Tuple[int, int]]:
	"""过滤被忽略编号，返回 (原始编号, 位值) 列表。

	- 原始编号按位顺序从 1 开始递增。
	- 被忽略编号（如 1/58/61）完全移除，相当于在序列中不存在。
	"""
	out: List[Tuple[int, int]] = []
	for idx_1b, val in enumerate(bits, start=1):
		if idx_1b in ignored:
			continue
		out.append((idx_1b, val))
	return out


def _segments_from_filtered(filtered: List[Tuple[int, int]], blocked_value: int) -> List[Tuple[int, int, int]]:
	"""在过滤后的序列上识别遮挡连续段。

	返回列表中每个元素为 (start_idx, end_idx, length)，其中：
	  - start_idx / end_idx 为原始 LED 编号（不包含被忽略编号）。
	  - length 为过滤后的连续段内 LED 数量（被忽略编号不计入）。
	"""
	segments: List[Tuple[int, int, int]] = []
	n = len(filtered)
	i = 0
	while i < n:
		orig_idx, val = filtered[i]
		if val == blocked_value:
			# 起一个新的遮挡段
			start_idx = orig_idx
			length = 1
			j = i + 1
			while j < n and filtered[j][1] == blocked_value:
				length += 1
				j += 1
			end_idx = filtered[j - 1][0]
			segments.append((start_idx, end_idx, length))
			i = j
		else:
			i += 1
	return segments


def detect_led_occlusion_events(
	frames: Iterable[Sequence[int] | bytes | bytearray],
	*,
	blocked_value: int = 0,
	bit_order: str = "lsb",
	ignored_indices: Optional[Set[int]] = None,
) -> Dict[str, Any]:
	"""
	识别一维 LED 阵列的遮挡与恢复事件（跨帧）。

	参数：
	  - frames: 时间序列帧，帧类型可为 bytes/bytearray 或 0..255 的整数列表；
				 每帧转换为位序列后，按位索引从 1 开始编号。
	  - blocked_value: 指示“遮挡”的位值，默认 0 表示位为 0 时认为遮挡。
	  - bit_order: 位顺序，'lsb'（低位在前）或 'msb'（高位在前）。
	  - ignored_indices: 被忽略的 LED 编号集合，默认 {1,58,61}。

	返回：
	  {
		'segments_by_frame': List[List[{'start': int, 'end': int, 'length': int}]],
		'events': List[{'t': int, 'type': str, 'start': int, 'end': int, 'length': int}],
	  }

	事件类型：
	  - 'start': 本帧出现了新的遮挡段（与上一帧的任何遮挡段都不重叠）。
	  - 'continue': 本帧遮挡段与上一帧存在重叠，视为持续。
	  - 'recover': 上一帧的遮挡段在本帧中不再出现（不与任何本帧段重叠）。

	注意：
	  - 所有判断均在“过滤后的序列”上完成，输出索引不包含被忽略编号。
	  - 不做物理位置重排或插值，仅依据有效 LED 的顺序关系识别连续段。
	"""
	ignored = set(ignored_indices or IGNORED_DEFAULT)

	# 逐帧生成遮挡连续段
	segments_by_frame: List[List[Dict[str, int]]] = []
	for frame in frames:
		bits = _bytes_to_bits(frame, bit_order=bit_order)
		filtered = _filter_ignored(bits, ignored)
		segments = _segments_from_filtered(filtered, blocked_value)
		segments_by_frame.append([
			{"start": s, "end": e, "length": L} for (s, e, L) in segments
		])

	# 跨帧事件识别（基于重叠关系）
	events: List[Dict[str, int | str]] = []
	prev: List[Tuple[int, int, int]] = []  # (start, end, length)
	for t, segs_dict in enumerate(segments_by_frame):
		curr: List[Tuple[int, int, int]] = [(d["start"], d["end"], d["length"]) for d in segs_dict]

		# 标记每个当前段是否与上帧段重叠
		used_prev = [False] * len(prev)
		used_curr = [False] * len(curr)

		# 按区间重叠进行匹配
		for i_prev, (ps, pe, pl) in enumerate(prev):
			overlapped = False
			for i_curr, (cs, ce, cl) in enumerate(curr):
				if ce < ps or cs > pe:
					continue  # 无重叠
				overlapped = True
				used_prev[i_prev] = True
				if not used_curr[i_curr]:
					used_curr[i_curr] = True
					events.append({
						"t": t,
						"type": "continue",
						"start": cs,
						"end": ce,
						"length": cl,
					})
			if not overlapped:
				# 上一帧的段在本帧中无重叠，视为恢复
				events.append({
					"t": t,
					"type": "recover",
					"start": ps,
					"end": pe,
					"length": pl,
				})

		# 对本帧中未匹配（与上帧不重叠）的段，视为新开始
		for i_curr, (cs, ce, cl) in enumerate(curr):
			if not used_curr[i_curr]:
				events.append({
					"t": t,
					"type": "start",
					"start": cs,
					"end": ce,
					"length": cl,
				})

		prev = curr

	return {
		"segments_by_frame": segments_by_frame,
		"events": events,
	}


__all__ = [
	"detect_led_occlusion_events",
]

