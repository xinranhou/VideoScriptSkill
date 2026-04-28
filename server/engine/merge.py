"""结果合并模块：将 ASR 结果合并为带时间定位的 Markdown"""

from dataclasses import dataclass


@dataclass
class Segment:
    """带时间戳的文本片段"""
    start_sec: float
    end_sec: float
    text: str


def fmt_timestamp(seconds: float) -> str:
    """秒 → MM:SS 格式"""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"


def merge_to_markdown(
    chunks: list,
    results: dict[int, str | None],
    engine_name: str = "腾讯云 ASR",
    duration_sec: float | None = None,
    translation: bool = False,
) -> str:
    """
    将切片结果合并为 Markdown 格式。

    结构：
    # 视频转文字脚本

    ## [00:00] - [00:45]
    第一段识别文本...

    ## [00:45] - [01:30]
    第二段识别文本...
    """
    lines = ["# 视频转文字脚本\n"]

    success_count = 0
    fail_count = 0

    for chunk in sorted(chunks, key=lambda c: c.index):
        result = results.get(chunk.index)
        start_ts = fmt_timestamp(chunk.start_sec)
        end_ts = fmt_timestamp(chunk.end_sec)

        if result and result.strip():
            lines.append(f"## [{start_ts}] - [{end_ts}]")
            lines.append(result.strip())
            lines.append("")
            success_count += 1
        else:
            lines.append(f"## [{start_ts}] - [{end_ts}]")
            lines.append("*（此片段识别失败）*")
            lines.append("")
            fail_count += 1

    lines.append("---")
    meta_parts = [f"共 {len(chunks)} 个切片，成功 {success_count}，失败 {fail_count}"]
    meta_parts.append(f"引擎：{engine_name}")
    if translation:
        meta_parts.append("翻译：是")
    if duration_sec is not None:
        meta_parts.append(f"耗时：{duration_sec:.1f} 秒")
    lines.append(f"* {' | '.join(meta_parts)} *")

    return "\n".join(lines)
