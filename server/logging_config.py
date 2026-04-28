"""日志配置模块 — 统一的日志设置"""

import logging
import sys
from pathlib import Path


def configure_logging(level=logging.DEBUG):
    """
    配置日志系统 — 同时输出到文件和控制台

    Args:
        level: 日志级别，默认 DEBUG
    """
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "videoscripts.log"

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 文件处理器 — 记录所有 DEBUG 级别的日志
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # 控制台处理器 — 只显示 INFO 级别及以上
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # 配置根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 移除已有的处理器（避免重复）
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 添加新处理器
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return log_file
