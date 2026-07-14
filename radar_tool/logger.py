"""
日志模块 - Logging utility

自动在项目根目录创建 `日志/` 目录，按日期生成日志文件。
提供统一的日志记录接口，支持文件和控制台输出。
"""

import os
import logging
from datetime import datetime


# 项目根目录 (tool/)
_TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 日志目录
LOG_DIR = os.path.join(_TOOL_DIR, '日志')

# 日志文件路径 (按日期)
LOG_FILE = os.path.join(LOG_DIR, f"运行日志_{datetime.now().strftime('%Y%m%d')}.log")

# 日志格式
_LOG_FORMAT = '%(asctime)s | %(levelname)-7s | %(name)-15s | %(message)s'
_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 缓存已创建的 logger
_loggers = {}


def _ensure_log_dir():
    """确保日志目录存在"""
    if not os.path.isdir(LOG_DIR):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
        except Exception as e:
            print(f"[日志] 无法创建日志目录 '{LOG_DIR}': {e}")


def _setup_root_logger():
    """初始化根 logger（仅执行一次）"""
    if logging.getLogger('radar_tool').handlers:
        return

    _ensure_log_dir()

    # 根 logger
    root_logger = logging.getLogger('radar_tool')
    root_logger.setLevel(logging.DEBUG)

    # 格式器
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # ——— 文件 Handler (记录全部 DEBUG+) ———
    try:
        fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        root_logger.addHandler(fh)
    except Exception as e:
        print(f"[日志] 无法创建日志文件 '{LOG_FILE}': {e}")

    # ——— 控制台 Handler (只显示 INFO+) ———
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    root_logger.addHandler(ch)

    root_logger.info('═══ 日志系统初始化完成 ═══')
    root_logger.info(f'日志目录: {LOG_DIR}')
    root_logger.info(f'日志文件: {LOG_FILE}')


def get_logger(name: str = 'radar_tool') -> logging.Logger:
    """
    获取指定名称的 logger。

    Args:
        name: Logger 名称，默认为 'radar_tool'

    Returns:
        配置好的 Logger 实例
    """
    if name not in _loggers:
        _setup_root_logger()
        logger = logging.getLogger(name)
        _loggers[name] = logger
    return _loggers[name]