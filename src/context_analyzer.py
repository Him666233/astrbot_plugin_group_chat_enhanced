"""
上下文分析器模块

负责分析聊天上下文，包括对话历史、用户印象、相关记忆等信息。

版本: V2.0.4
作者: Him666233
"""

__version__ = "V2.0.4"
__author__ = "Him666233"
__description__ = "上下文分析器模块：负责分析聊天上下文"

import json
from typing import TYPE_CHECKING, Any, Dict

from astrbot.api import logger
from astrbot.api.star import Context

if TYPE_CHECKING:
    from state_manager import StateManager
    from impression_manager import ImpressionManager
    from memory_integration import MemoryIntegration

class ContextAnalyzer:
    """上下文分析器"""

    def __init__(self, context: Context, config: Any,
                 state_manager: "StateManager",
                 impression_manager: "ImpressionManager",
                 memory_integration: "MemoryIntegration"):
        self.context = context
        self.config = config
        self.state_manager = state_manager
        self.impression_manager = impression_manager
        self.memory_integration = memory_integration

    def _is_detailed_logging(self) -> bool:
        """检查是否启用详细日志"""
        try:
            # 检查配置中的enable_detailed_logging开关
            if isinstance(self.config, dict):
                return self.config.get("enable_detailed_logging", False)
            return getattr(self.config, "enable_detailed_logging", False) if self.config else False
        except Exception:
            return False

    async def analyze_chat_context(self, event: Any) -> Dict:
        """分析聊天上下文"""
        try:
            # 详细日志：开始分析聊天上下文
            if self._is_detailed_logging():
                logger.debug(f"[上下文分析器] 开始分析聊天上下文 - 群组: {event.get_group_id()}, 用户: {event.get_sender_id()}")
            
            group_id = event.get_group_id()
            user_id = event.get_sender_id()

            # 详细日志：获取对话历史
            if self._is_detailed_logging():
                logger.debug(f"[上下文分析器] 获取对话历史 - 群组: {group_id}, 用户: {user_id}")
            
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(event.unified_msg_origin)
            conversation_history = []
            if curr_cid:
                conversation = await self.context.conversation_manager.get_conversation(event.unified_msg_origin, curr_cid)
                if conversation and conversation.history:
                    try:
                        conversation_history = json.loads(conversation.history)
                        # 确保是列表格式
                        if not isinstance(conversation_history, list):
                            logger.warning(f"[上下文分析器] 对话历史格式错误，期望list，实际{type(conversation_history)}")
                            conversation_history = []
                    except json.JSONDecodeError as e:
                        logger.warning(f"[上下文分析器] JSON解析失败: {e}")
                        conversation_history = []
                    # 详细日志：对话历史获取成功
                    if self._is_detailed_logging():
                        logger.debug(f"[上下文分析器] 对话历史获取成功 - 群组: {group_id}, 历史记录数: {len(conversation_history)}")
            else:
                # 详细日志：无当前对话ID
                if self._is_detailed_logging():
                    logger.debug(f"[上下文分析器] 无当前对话ID - 群组: {group_id}")

            # 详细日志：获取用户印象
            if self._is_detailed_logging():
                logger.debug(f"[上下文分析器] 获取用户印象 - 群组: {group_id}, 用户: {user_id}")
            
            user_impression = await self.impression_manager.get_user_impression(user_id, group_id)
            
            # 详细日志：用户印象获取完成
            if self._is_detailed_logging():
                logger.debug(f"[上下文分析器] 用户印象获取完成 - 群组: {group_id}, 用户: {user_id}")

            # 详细日志：获取相关记忆
            if self._is_detailed_logging():
                logger.debug(f"[上下文分析器] 获取相关记忆 - 群组: {group_id}, 消息内容长度: {len(event.message_str)}")
            
            # 获取相关记忆（不使用关键词，基于内容语义）
            relevant_memories = await self.memory_integration.recall_memories(
                message_content=event.message_str,
                group_id=group_id
            )
            
            # 详细日志：相关记忆获取完成
            if self._is_detailed_logging():
                logger.debug(f"[上下文分析器] 相关记忆获取完成 - 群组: {group_id}, 记忆数量: {len(relevant_memories)}")

            # 详细日志：获取对话统计
            if self._is_detailed_logging():
                logger.debug(f"[上下文分析器] 获取对话统计 - 群组: {group_id}")
            
            conversation_counts = self.state_manager.get_conversation_counts()
            group_counts = conversation_counts.get(group_id, {})

            # 详细日志：构建上下文结果
            if self._is_detailed_logging():
                logger.debug(f"[上下文分析器] 构建上下文结果 - 群组: {group_id}, 用户: {user_id}")
            
            result = {
                "group_id": group_id,
                "user_id": user_id,
                "conversation_history": conversation_history,
                "user_impression": user_impression,
                "relevant_memories": relevant_memories,
                "current_mode": self.state_manager.get_interaction_modes().get(group_id, "normal"),
                "focus_target": self.state_manager.get_focus_targets().get(group_id),
                "fatigue_count": self.state_manager.get_fatigue_data().get(user_id, 0),
                "conversation_count": group_counts.get(user_id, 0)
            }
            
            # 详细日志：上下文分析完成
            if self._is_detailed_logging():
                logger.debug(f"[上下文分析器] 上下文分析完成 - 群组: {group_id}, 用户: {user_id}")
            
            return result
            
        except Exception as e:
            # 错误日志：上下文分析失败
            logger.error(f"[上下文分析器] 分析聊天上下文时发生错误 - 群组: {event.get_group_id()}, 用户: {event.get_sender_id()}, 错误: {e}", exc_info=True)
            
            # 返回默认的上下文结果，确保功能不中断
            return {
                "group_id": event.get_group_id(),
                "user_id": event.get_sender_id(),
                "conversation_history": [],
                "user_impression": {},
                "relevant_memories": [],
                "current_mode": "normal",
                "focus_target": None,
                "fatigue_count": 0,
                "conversation_count": 0
            }