from typing import Any, Dict
import logging

from astrbot.api import logger

class ImpressionManager:
    """印象管理器 - 只读"""
    
    def __init__(self, context: Any, config: Any):
        self.context = context
        self.config = config
        self.memora_plugin = self._init_memora_plugin()
    
    def _init_memora_plugin(self) -> Any:
        """初始化 MemoraConnectPlugin 连接"""
        try:
            memora_plugin_meta = self.context.get_registered_star("astrbot_plugin_memora_connect")
            if memora_plugin_meta:
                return memora_plugin_meta.star_cls
            else:
                logger.warning("未找到 MemoraConnectPlugin，印象功能将不可用")
                return None
        except Exception as e:
            logger.error(f"初始化 MemoraConnectPlugin 失败: {e}")
            return None
    
    async def get_user_impression(self, user_id: str, group_id: str = None) -> Dict:
        """获取用户印象摘要"""
        if not getattr(self.config, 'impression_enabled', True) or not self.memora_plugin:
            return {"score": 0.5, "summary": "印象系统不可用"}
        
        try:
            return await self.memora_plugin.get_impression_summary_api(
                person_name=user_id,
                group_id=group_id
            )
        except Exception as e:
            logger.error(f"获取用户印象失败: {e}")
            return {"score": 0.5, "summary": "获取印象失败"}