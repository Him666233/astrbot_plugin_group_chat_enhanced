"""
疲劳系统模块

负责管理用户疲劳度，包括疲劳度更新、衰减、惩罚计算等功能。

版本: 2.0.3
作者: Him666233
"""

__version__ = "2.0.3"
__author__ = "Him666233"
__description__ = "疲劳系统模块：负责管理用户疲劳度"

import time
from typing import TYPE_CHECKING, Any

from astrbot.api import logger

if TYPE_CHECKING:
    from state_manager import StateManager

class FatigueSystem:
    """疲劳系统"""

    def __init__(self, config: Any, state_manager: "StateManager"):
        self.config = config
        self.state_manager = state_manager

    def update_fatigue(self, user_id: str, increment: int = 1):
        """更新用户疲劳度"""
        if not getattr(self.config, 'fatigue_enabled', True):
            return

        self._apply_fatigue_decay()

        fatigue_data = self.state_manager.get_fatigue_data()
        current_fatigue = fatigue_data.get(user_id, 0)
        self.state_manager.update_fatigue(user_id, current_fatigue + increment)

    def _apply_fatigue_decay(self):
        """应用疲劳衰减"""
        current_time = time.time()
        last_decay_time = self.state_manager.get("last_fatigue_decay_time", current_time)
        hours_passed = (current_time - last_decay_time) / 3600

        if hours_passed >= 1:
            decay_rate = getattr(self.config, 'fatigue_decay_rate', 0.5)
            fatigue_data = self.state_manager.get_fatigue_data()
            
            for user_id in list(fatigue_data.keys()):
                fatigue_data[user_id] *= (1 - decay_rate)

            fatigue_data = {k: v for k, v in fatigue_data.items() if v > 0.1}
            
            self.state_manager.set("fatigue_data", fatigue_data)
            self.state_manager.set("last_fatigue_decay_time", current_time)

    def get_fatigue_penalty(self, user_id: str) -> float:
        """获取疲劳度惩罚"""
        if not getattr(self.config, 'fatigue_enabled', True):
            return 0.0

        fatigue_count = self.get_fatigue_level(user_id)
        threshold = getattr(self.config, 'fatigue_threshold', 5)

        if fatigue_count >= threshold:
            return 0.5

        return fatigue_count * 0.05

    def reset_fatigue(self, user_id: str):
        """重置用户疲劳度"""
        fatigue_data = self.state_manager.get_fatigue_data()
        if user_id in fatigue_data:
            del fatigue_data[user_id]
            self.state_manager.set("fatigue_data", fatigue_data)

    def get_fatigue_level(self, user_id: str) -> float:
        """获取用户疲劳度等级"""
        return self.state_manager.get_fatigue_data().get(user_id, 0.0)

    def cleanup_expired_fatigue(self):
        """清理过期的疲劳数据"""
        current_time = time.time()
        last_decay_time = self.state_manager.get("last_fatigue_decay_time", current_time)
        reset_interval = getattr(self.config, 'fatigue_reset_interval', 6) * 3600

        if current_time - last_decay_time > reset_interval:
            self.state_manager.set("fatigue_data", {})
            self.state_manager.set("last_fatigue_decay_time", current_time)
            logger.info("已清理所有疲劳数据")