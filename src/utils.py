"""
工具函数模块

提供各种工具函数，包括消息清理、随机选择、时间格式化、字符串截断等。

版本: V2.0.4
作者: Him666233
"""

__version__ = "V2.0.4"
__author__ = "Him666233"
__description__ = "工具函数模块：提供各种工具函数"

import random
import re
from typing import Any, Dict, List

def clean_message(message: str) -> str:
    """
    清理消息文本，移除特殊字符和规范化空白。
    这是一个纯文本处理工具，不涉及任何智能分析。
    
    Args:
        message: 原始消息字符串。
        
    Returns:
        清理后的消息字符串。
    """
    # 移除多余的空格和换行符
    message = re.sub(r'\s+', ' ', message).strip()
    # 移除特殊字符，保留中文、英文、数字和基本标点
    message = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s\.,!?;:()（）。，！？；：]', '', message)
    return message

def get_random_reply_from_list(replies: List[str]) -> str:
    """
    从一个字符串列表中随机选择一个元素。
    这是一个纯粹的随机选择工具，常用于从多个预设回复中选择一个。
    
    Args:
        replies: 字符串列表。
        
    Returns:
        随机选择的字符串，如果列表为空则返回空字符串。
    """
    if not replies:
        return ""
    return random.choice(replies)

def format_time_ago(seconds: int) -> str:
    """
    将一个时间差（秒数）格式化为人类可读的"X时间前"的字符串。
    这是一个纯粹的时间格式化工具。
    
    Args:
        seconds: 距离现在的秒数。
        
    Returns:
        格式化后的时间字符串，如"5分钟前"、"2小时前"。
    """
    if seconds < 60:
        return "刚刚"
    elif seconds < 3600:
        return f"{seconds // 60}分钟前"
    elif seconds < 86400:
        return f"{seconds // 3600}小时前"
    else:
        return f"{seconds // 86400}天前"

def truncate_string(text: str, max_length: int = 100) -> str:
    """
    将字符串截断到指定长度，并在末尾添加省略号。
    这是一个纯粹的字符串处理工具，用于显示长文本的摘要。
    
    Args:
        text: 原始字符串。
        max_length: 最大长度。
        
    Returns:
        截断后的字符串。
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."

def safe_get(data: Dict, keys: List[str], default: Any = None) -> Any:
    """
    安全地从嵌套字典中获取值，避免因键不存在而抛出异常。
    这是一个纯粹的数据安全访问工具。
    
    Args:
        data: 要访问的字典。
        keys: 一个键的列表，表示访问路径，例如 ['a', 'b', 'c']。
        default: 如果键路径不存在，返回的默认值。
        
    Returns:
        找到的值，或者默认值。
    """
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data