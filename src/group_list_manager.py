"""
群组名单管理器模块

负责管理群组权限，包括白名单和黑名单模式。

版本: V2.0.4
作者: Him666233
"""

__version__ = "V2.0.4"
__author__ = "Him666233"
__description__ = "群组名单管理器模块：负责管理群组权限"

from typing import Any

class GroupListManager:
    """群组名单管理器"""
    
    def __init__(self, config: Any):
        self.config = config
    
    def check_group_permission(self, group_id: str) -> bool:
        """检查群组权限"""
        if not hasattr(self.config, 'list_mode'):
            return True
        
        if self.config.list_mode == "whitelist":
            return group_id in getattr(self.config, 'groups', [])
        else:
            return group_id not in getattr(self.config, 'groups', [])