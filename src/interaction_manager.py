"""
交互管理器模块

负责管理交互模式，包括观察模式、正常模式、专注模式的判断和状态更新。

版本: V2.0.4
作者: Him666233
"""

__version__ = "V2.0.4"
__author__ = "Him666233"
__description__ = "交互管理器模块：负责管理交互模式"

import time
from typing import Any, Dict

from astrbot.api import logger
from astrbot.api.star import Context
from state_manager import StateManager

class InteractionManager:
    """交互管理器"""
    
    def __init__(self, context: Context, config: Any, state_manager: StateManager):
        self.context = context
        self.config = config
        self.state_manager = state_manager
    
    def _is_detailed_logging(self) -> bool:
        """检查是否启用详细日志"""
        try:
            # 检查配置中的enable_detailed_logging开关
            if isinstance(self.config, dict):
                return self.config.get("enable_detailed_logging", False)
            return getattr(self.config, "enable_detailed_logging", False) if self.config else False
        except Exception:
            return False
    
    def determine_interaction_mode(self, chat_context: Dict) -> str:
        """判断交互模式"""
        group_activity = self._calculate_group_activity(chat_context)
        observation_threshold = getattr(self.config, 'observation_mode_threshold', 0.2)
        
        # 详细日志：计算群活跃度
        if self._is_detailed_logging():
            logger.debug(f"[交互管理器] 计算群活跃度 - 活跃度: {group_activity:.3f}, 观察阈值: {observation_threshold}")
        
        if group_activity < observation_threshold:
            # 详细日志：进入观察模式
            if self._is_detailed_logging():
                logger.debug(f"[交互管理器] 进入观察模式 - 活跃度低于阈值")
            return "observation"  # 观察模式
        
        # 检查是否在专注聊天中
        current_mode = chat_context.get("current_mode", "normal")
        if current_mode == "focus":
            # 详细日志：保持专注模式
            if self._is_detailed_logging():
                logger.debug(f"[交互管理器] 保持专注模式")
            return "focus"
        
        # 详细日志：进入正常模式
        if self._is_detailed_logging():
            logger.debug(f"[交互管理器] 进入正常模式")
        return "normal"
    
    def _calculate_group_activity(self, chat_context: Dict) -> float:
        """计算群活跃度"""
        conversation_history = chat_context.get("conversation_history", [])
        if not conversation_history:
            # 详细日志：无对话历史
            if self._is_detailed_logging():
                logger.debug(f"[交互管理器] 计算群活跃度 - 无对话历史，返回0.0")
            return 0.0
        
        # 简单的活跃度计算：最近5分钟内的消息数量
        current_time = time.time()
        recent_count = sum(1 for msg in conversation_history if current_time - msg.get("timestamp", 0) < 300)
        
        activity = min(1.0, recent_count / 10.0)  # 假设10条消息为最大活跃度
        
        # 详细日志：活跃度计算结果
        if self._is_detailed_logging():
            logger.debug(f"[交互管理器] 计算群活跃度 - 总消息数: {len(conversation_history)}, 最近5分钟消息数: {recent_count}, 活跃度: {activity:.3f}")
        
        return activity
    
    async def update_interaction_state(self, event: Any, chat_context: Dict, response_result: Dict):
        """更新交互状态"""
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        current_time = time.time()
        
        # 详细日志：开始更新交互状态
        if self._is_detailed_logging():
            logger.debug(f"[交互管理器] 开始更新交互状态 - 群组: {group_id}, 用户: {user_id}, 当前模式: {chat_context.get('current_mode', 'normal')}")
        
        # 更新最后活动时间
        self.state_manager.update_last_activity(group_id, current_time)
        self.state_manager.update_last_activity(user_id, current_time)
        
        # 更新对话计数
        self.state_manager.increment_conversation_count(group_id, user_id)
        
        # 如果未回复，重置连续回复计数器
        if not response_result.get("should_reply"):
            # 详细日志：重置连续回复计数
            if self._is_detailed_logging():
                logger.debug(f"[交互管理器] 重置连续回复计数 - 群组: {group_id}")
            self.state_manager.reset_consecutive_response(group_id)
        
        # 检查专注模式退出条件
        if chat_context.get("current_mode") == "focus":
            # 详细日志：检查专注模式退出条件
            if self._is_detailed_logging():
                logger.debug(f"[交互管理器] 检查专注模式退出条件 - 群组: {group_id}")
            await self._check_focus_mode_exit(group_id, user_id, current_time, response_result)
        
        # 记录读空气决策统计
        if response_result.get("decision_method") == "air_reading":
            # 详细日志：记录读空气决策统计
            if self._is_detailed_logging():
                logger.debug(f"[交互管理器] 记录读空气决策统计 - 群组: {group_id}")
            await self._update_air_reading_stats(group_id, response_result)
        
        # 详细日志：交互状态更新完成
        if self._is_detailed_logging():
            logger.debug(f"[交互管理器] 交互状态更新完成 - 群组: {group_id}")
    
    async def _check_focus_mode_exit(self, group_id: str, user_id: str, current_time: float, response_result: Dict):
        """检查是否需要退出专注模式"""
        focus_targets = self.state_manager.get_focus_targets()
        focus_target = focus_targets.get(group_id)

        # 详细日志：检查专注模式退出条件
        if self._is_detailed_logging():
            logger.debug(f"[交互管理器] 检查专注模式退出条件 - 群组: {group_id}, 当前用户: {user_id}, 专注目标: {focus_target}")

        if focus_target and focus_target != user_id:
            last_target_activity = self.state_manager.get_last_activity(focus_target)
            focus_timeout = getattr(self.config, 'focus_timeout_seconds', 300)
            
            # 详细日志：检查专注目标活动时间
            if self._is_detailed_logging():
                logger.debug(f"[交互管理器] 专注目标活动检查 - 目标: {focus_target}, 最后活动: {last_target_activity}, 超时时间: {focus_timeout}秒")

            if current_time - last_target_activity > focus_timeout:
                # 详细日志：专注模式超时退出
                if self._is_detailed_logging():
                    logger.debug(f"[交互管理器] 专注模式超时退出 - 群组: {group_id}, 目标: {focus_target}, 超时时间: {current_time - last_target_activity:.1f}秒")
                
                self.state_manager.set_interaction_mode(group_id, "normal")
                self.state_manager.remove_focus_target(group_id)
                logger.info(f"群组 {group_id} 因超时退出专注聊天模式")
            else:
                # 详细日志：专注模式继续
                if self._is_detailed_logging():
                    logger.debug(f"[交互管理器] 专注模式继续 - 群组: {group_id}, 目标: {focus_target}, 剩余时间: {focus_timeout - (current_time - last_target_activity):.1f}秒")
        else:
            # 详细日志：无需检查专注模式退出
            if self._is_detailed_logging():
                logger.debug(f"[交互管理器] 无需检查专注模式退出 - 群组: {group_id}, 无专注目标或当前用户是目标")
    
    async def _update_air_reading_stats(self, group_id: str, response_result: Dict):
        """更新读空气统计信息"""
        # 详细日志：更新读空气统计信息
        if self._is_detailed_logging():
            logger.debug(f"[交互管理器] 更新读空气统计信息 - 群组: {group_id}, 决策结果: {response_result}")
        
        # 这里可以添加读空气决策的统计逻辑
        # 比如记录 LLM 跳过回复的频率，用于优化系统
        pass