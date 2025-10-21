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