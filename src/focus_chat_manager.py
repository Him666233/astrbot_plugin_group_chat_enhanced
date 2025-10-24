"""
专注聊天管理器模块

负责管理专注聊天模式，包括兴趣度评估、结构化特征分析、上下文一致性分析等。

版本: V2.0.4
作者: Him666233
"""

__version__ = "V2.0.4"
__author__ = "Him666233"
__description__ = "专注聊天管理器模块：负责管理专注聊天模式"

import time
from typing import TYPE_CHECKING, Any, Dict

from astrbot.api import logger

if TYPE_CHECKING:
    from state_manager import StateManager

class FocusChatManager:
    """专注聊天管理器"""
    
    # 权重常量定义
    AT_MESSAGE_WEIGHT = 0.4  # @消息权重
    MESSAGE_RELEVANCE_WEIGHT = 0.3  # 消息相关性权重
    USER_IMPRESSION_WEIGHT = 0.3  # 用户印象权重
    
    # 结构化特征分析权重
    STRUCTURAL_WEIGHT = 0.25  # 结构特征权重
    CONTEXT_WEIGHT = 0.30  # 上下文一致性权重
    BEHAVIOR_WEIGHT = 0.20  # 用户行为权重
    FLOW_WEIGHT = 0.15  # 对话流权重
    TEMPORAL_WEIGHT = 0.10  # 时间相关性权重
    
    # 长度特征评分
    OPTIMAL_LENGTH_SCORE = 0.3  # 适中长度评分
    SHORT_LENGTH_SCORE = 0.1  # 短消息评分
    LONG_LENGTH_SCORE = 0.2  # 长消息评分
    
    # 标点符号密度评分
    OPTIMAL_PUNCTUATION_SCORE = 0.3  # 适中标点密度评分
    HIGH_PUNCTUATION_SCORE = 0.2  # 高标点密度评分
    
    # 特殊符号评分
    AT_SYMBOL_SCORE = 0.4  # @符号评分
    QUESTION_SCORE = 0.3  # 疑问句评分
    EMOTION_SCORE = 0.2  # 情感表达评分
    
    # 上下文一致性评分
    CONTINUOUS_DIALOGUE_SCORE = 0.3  # 连续对话评分
    REPLY_PATTERN_SCORE = 0.2  # 回复模式评分
    LENGTH_PATTERN_SCORE = 0.2  # 长度模式评分
    TIME_INTERVAL_5MIN_SCORE = 0.3  # 5分钟内时间间隔评分
    TIME_INTERVAL_30MIN_SCORE = 0.2  # 30分钟内时间间隔评分
    
    # 用户行为模式评分
    HIGH_FREQUENCY_SCORE = 0.3  # 高频互动用户评分
    RECENT_ACTIVITY_SCORE = 0.3  # 近期活跃用户评分
    QUALITY_MESSAGE_SCORE = 0.2  # 消息质量模式评分
    HIGH_RESPONSE_RATE_SCORE = 0.2  # 高响应率评分
    
    # 对话流分析评分
    CONVERSATION_RHYTHM_SCORE = 0.3  # 对话节奏评分
    TOPIC_COHERENCE_SCORE = 0.4  # 话题连贯性评分
    
    # 时间相关性评分
    HIGH_TEMPORAL_RELEVANCE_SCORE = 0.8  # 高时间相关性评分
    MEDIUM_TEMPORAL_RELEVANCE_SCORE = 0.6  # 中等时间相关性评分
    LOW_TEMPORAL_RELEVANCE_SCORE = 0.3  # 低时间相关性评分

    def __init__(self, context: Any, config: Any, state_manager: "StateManager"):
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

    async def evaluate_focus_interest(self, event: Any, chat_context: Dict) -> float:
        """评估专注聊天兴趣度"""
        user_id = event.get_sender_id()
        message_content = event.message_str

        # 详细日志：开始评估专注聊天兴趣度
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 开始评估专注聊天兴趣度 - 用户: {user_id}, 消息: {message_content[:50]}...")

        # 计算兴趣度分数
        interest_score = 0.0

        # 1. 检查是否@机器人
        if event.is_at_or_wake_command:
            interest_score += self.AT_MESSAGE_WEIGHT
            # 详细日志：@机器人加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] @机器人加分 - 当前分数: {interest_score:.3f}")

        # 2. 检查消息相关性
        if self._is_message_relevant(message_content, chat_context):
            interest_score += self.MESSAGE_RELEVANCE_WEIGHT
            # 详细日志：消息相关性加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 消息相关性加分 - 当前分数: {interest_score:.3f}")

        # 3. 检查用户印象
        user_impression = self.state_manager.get_user_impression(user_id)
        impression_score = user_impression.get("score", 0.5)
        interest_score += impression_score * self.USER_IMPRESSION_WEIGHT
        # 详细日志：用户印象加分
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 用户印象加分 - 印象分数: {impression_score:.3f}, 当前分数: {interest_score:.3f}")

        final_score = min(1.0, interest_score)
        
        # 详细日志：兴趣度评估完成
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 兴趣度评估完成 - 最终分数: {final_score:.3f}")

        return final_score
    
    def _is_message_relevant(self, message_content: str, chat_context: Dict) -> bool:
        """智能相关性检测（不使用关键词）"""
        # 详细日志：开始检查消息相关性
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 开始检查消息相关性 - 消息: {message_content[:50]}...")
        
        # 1. 结构化特征分析
        structural_score = self._analyze_structural_features(message_content)

        # 2. 上下文一致性分析
        context_score = self._analyze_context_consistency(message_content, chat_context)

        # 3. 用户行为模式分析
        behavior_score = self._analyze_user_behavior_pattern(chat_context)

        # 4. 对话流分析
        flow_score = self._analyze_conversation_flow(chat_context)

        # 5. 时间相关性分析
        time_score = self._analyze_temporal_relevance(chat_context)

        # 综合评分（各维度权重可调整）
        total_score = (
            structural_score * self.STRUCTURAL_WEIGHT +
            context_score * self.CONTEXT_WEIGHT +
            behavior_score * self.BEHAVIOR_WEIGHT +
            flow_score * self.FLOW_WEIGHT +
            time_score * self.TEMPORAL_WEIGHT
        )

        relevance_threshold = getattr(self.context, 'relevance_threshold', 0.6)
        result = total_score >= relevance_threshold
        
        # 详细日志：相关性检查完成
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 相关性检查完成 - 总分: {total_score:.3f}, 阈值: {relevance_threshold:.3f}, 结果: {'相关' if result else '不相关'}")
        
        return result

    def _analyze_structural_features(self, message_content: str) -> float:
        """分析消息的结构化特征"""
        # 详细日志：开始分析结构化特征
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 开始分析结构化特征 - 消息: {message_content[:50]}...")
        
        if not message_content or not message_content.strip():
            # 详细日志：空消息
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 空消息，结构化特征分数: 0.0")
            return 0.0

        score = 0.0
        content = message_content.strip()

        # 长度特征（适中长度更可能需要回复）
        length = len(content)
        if 10 <= length <= 150:
            score += self.OPTIMAL_LENGTH_SCORE  # 适中长度
            # 详细日志：长度特征加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 长度特征加分 - 长度: {length}, 当前分数: {score:.3f}")
        elif length < 10:
            score += self.SHORT_LENGTH_SCORE  # 太短
            # 详细日志：长度特征加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 长度特征加分 - 长度: {length}, 当前分数: {score:.3f}")
        else:
            score += self.LONG_LENGTH_SCORE  # 较长但仍可能重要
            # 详细日志：长度特征加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 长度特征加分 - 长度: {length}, 当前分数: {score:.3f}")

        # 标点符号密度（丰富的标点可能表示更正式或更需要回复的内容）
        punctuation_count = sum(1 for char in content if char in "，。！？；：""''（）【】")
        punctuation_ratio = punctuation_count / length if length > 0 else 0
        if 0.05 <= punctuation_ratio <= 0.25:
            score += self.OPTIMAL_PUNCTUATION_SCORE
            # 详细日志：标点符号密度加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 标点符号密度加分 - 密度: {punctuation_ratio:.3f}, 当前分数: {score:.3f}")
        elif punctuation_ratio > 0.25:
            score += self.HIGH_PUNCTUATION_SCORE
            # 详细日志：标点符号密度加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 标点符号密度加分 - 密度: {punctuation_ratio:.3f}, 当前分数: {score:.3f}")

        # 特殊符号分析
        if "@" in content:
            score += self.AT_SYMBOL_SCORE  # @机器人直接相关
            # 详细日志：特殊符号加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 特殊符号加分 - 包含@符号, 当前分数: {score:.3f}")

        # 疑问句特征
        question_indicators = ["吗", "呢", "啊", "吧", "?", "？", "怎么", "什么", "为什么", "怎么"]
        if any(indicator in content for indicator in question_indicators):
            score += self.QUESTION_SCORE
            # 详细日志：疑问句特征加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 疑问句特征加分 - 包含疑问词, 当前分数: {score:.3f}")

        # 情感表达特征
        emotion_indicators = ["!", "！", "😊", "😂", "👍", "❤️", "😭", "😤", "🤔"]
        if any(indicator in content for indicator in emotion_indicators):
            score += self.EMOTION_SCORE
            # 详细日志：情感表达特征加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 情感表达特征加分 - 包含情感符号, 当前分数: {score:.3f}")

        final_score = min(1.0, score)
        # 详细日志：结构化特征分析完成
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 结构化特征分析完成 - 最终分数: {final_score:.3f}")

        return final_score

    def _analyze_context_consistency(self, message_content: str, chat_context: Dict) -> float:
        """分析与上下文的一致性"""
        # 详细日志：开始分析上下文一致性
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 开始分析上下文一致性 - 消息: {message_content[:50]}...")
        
        conversation_history = chat_context.get("conversation_history", [])
        if not conversation_history:
            # 详细日志：无对话历史，返回中等分数
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 无对话历史，上下文一致性分数: 0.5")
            return 0.5  # 没有历史上下文，给中等分数

        # 分析最近几条消息的模式
        recent_messages = conversation_history[-5:]  # 最近5条消息
        if not recent_messages:
            # 详细日志：无最近消息，返回中等分数
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 无最近消息，上下文一致性分数: 0.5")
            return 0.5

        consistency_score = 0.0

        # 详细日志：对话历史信息
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 对话历史长度: {len(conversation_history)}, 最近消息数: {len(recent_messages)}")

        # 1. 用户交互模式分析
        current_user = chat_context.get("user_id", "")
        recent_users = [msg.get("user_id", "") for msg in recent_messages]

        # 检查是否是连续对话
        if recent_users.count(current_user) >= 2:
            consistency_score += self.CONTINUOUS_DIALOGUE_SCORE
            # 详细日志：连续对话加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 连续对话加分 - 当前用户: {current_user}, 当前分数: {consistency_score:.3f}")

        # 检查是否是回复模式
        if len(recent_users) >= 2:
            if recent_users[-2] != current_user:  # 上一条消息不是当前用户发的
                consistency_score += self.REPLY_PATTERN_SCORE
                # 详细日志：回复模式加分
                if self._is_detailed_logging():
                    logger.debug(f"[专注聊天管理器] 回复模式加分 - 当前分数: {consistency_score:.3f}")

        # 2. 消息长度模式分析
        current_length = len(message_content.strip())
        recent_lengths = [len(msg.get("content", "").strip()) for msg in recent_messages]

        if recent_lengths:
            avg_length = sum(recent_lengths) / len(recent_lengths)
            length_diff = abs(current_length - avg_length) / max(avg_length, 1)
            if length_diff < 0.5:  # 长度差异不大
                consistency_score += self.LENGTH_PATTERN_SCORE
                # 详细日志：长度模式加分
                if self._is_detailed_logging():
                    logger.debug(f"[专注聊天管理器] 长度模式加分 - 当前长度: {current_length}, 平均长度: {avg_length:.1f}, 当前分数: {consistency_score:.3f}")

        # 3. 时间间隔分析
        if len(recent_messages) >= 2:
            current_time = chat_context.get("timestamp", time.time())
            last_msg_time = recent_messages[-1].get("timestamp", 0)
            time_diff = current_time - last_msg_time

            if time_diff < 300:  # 5分钟内
                consistency_score += self.TIME_INTERVAL_5MIN_SCORE
                # 详细日志：时间间隔加分（5分钟内）
                if self._is_detailed_logging():
                    logger.debug(f"[专注聊天管理器] 时间间隔加分（5分钟内）- 间隔: {time_diff:.1f}秒, 当前分数: {consistency_score:.3f}")
            elif time_diff < 1800:  # 30分钟内
                consistency_score += self.TIME_INTERVAL_30MIN_SCORE
                # 详细日志：时间间隔加分（30分钟内）
                if self._is_detailed_logging():
                    logger.debug(f"[专注聊天管理器] 时间间隔加分（30分钟内）- 间隔: {time_diff:.1f}秒, 当前分数: {consistency_score:.3f}")

        final_score = min(1.0, consistency_score)
        # 详细日志：上下文一致性分析完成
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 上下文一致性分析完成 - 最终分数: {final_score:.3f}")

        return final_score

    def _analyze_user_behavior_pattern(self, chat_context: Dict) -> float:
        """分析用户行为模式"""
        # 详细日志：开始分析用户行为模式
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 开始分析用户行为模式")
        
        user_id = chat_context.get("user_id", "")
        if not user_id:
            # 详细日志：无用户ID，返回中等分数
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 无用户ID，用户行为模式分数: 0.5")
            return 0.5

        # 详细日志：用户ID
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 分析用户行为模式 - 用户ID: {user_id}")

        # 从状态管理器获取用户的历史行为数据
        if hasattr(self.state_manager, 'get_user_interaction_pattern'):
            pattern_data = self.state_manager.get_user_interaction_pattern(user_id)
            # 详细日志：使用状态管理器获取行为数据
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 使用状态管理器获取用户行为数据")
        else:
            # 回退方案：基于当前上下文估算
            conversation_history = chat_context.get("conversation_history", [])
            user_messages = [msg for msg in conversation_history if msg.get("user_id") == user_id]

            pattern_data = {
                "total_messages": len(user_messages),
                "avg_response_time": 0,  # 简化处理
                "interaction_frequency": len(user_messages) / max(1, (time.time() - chat_context.get("timestamp", time.time())) / 3600)  # 每小时消息数
            }
            # 详细日志：使用回退方案获取行为数据
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 使用回退方案获取用户行为数据 - 用户消息数: {len(user_messages)}")

        # 详细日志：用户行为数据
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 用户行为数据 - 总消息数: {pattern_data.get('total_messages', 0)}, 互动频率: {pattern_data.get('interaction_frequency', 0):.3f}")

        # 基于行为模式计算相关性分数
        score = 0.0

        # 高频互动用户
        if pattern_data.get("interaction_frequency", 0) > 2:  # 每小时超过2条消息
            score += 0.3
            # 详细日志：高频互动用户加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 高频互动用户加分 - 互动频率: {pattern_data.get('interaction_frequency', 0):.3f}, 当前分数: {score:.3f}")

        # 近期活跃用户
        last_activity = pattern_data.get("last_activity", 0)
        if time.time() - last_activity < 3600:  # 1小时内活跃
            score += 0.3
            # 详细日志：近期活跃用户加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 近期活跃用户加分 - 最后活跃: {last_activity}, 当前分数: {score:.3f}")

        # 消息质量模式
        avg_length = pattern_data.get("avg_message_length", 50)
        if 20 <= avg_length <= 200:  # 适中长度的消息
            score += 0.2
            # 详细日志：消息质量模式加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 消息质量模式加分 - 平均长度: {avg_length:.1f}, 当前分数: {score:.3f}")

        # 互动响应模式
        response_rate = pattern_data.get("response_rate", 0.5)
        if response_rate > 0.7:  # 高响应率
            score += 0.2
            # 详细日志：互动响应模式加分
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 互动响应模式加分 - 响应率: {response_rate:.3f}, 当前分数: {score:.3f}")

        final_score = min(1.0, score)
        # 详细日志：用户行为模式分析完成
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 用户行为模式分析完成 - 最终分数: {final_score:.3f}")

        return final_score

    def _analyze_conversation_flow(self, chat_context: Dict) -> float:
        """分析对话流"""
        # 详细日志：开始分析对话流
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 开始分析对话流")
        
        conversation_history = chat_context.get("conversation_history", [])
        if len(conversation_history) < 2:
            # 详细日志：对话历史不足，返回中等分数
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 对话历史不足（{len(conversation_history)}条），对话流分数: 0.5")
            return 0.5

        flow_score = 0.0

        # 详细日志：对话历史信息
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 对话历史长度: {len(conversation_history)}")

        # 1. 对话节奏分析
        recent_messages = conversation_history[-10:]
        if len(recent_messages) >= 3:
            # 计算消息间隔
            intervals = []
            for i in range(1, len(recent_messages)):
                interval = recent_messages[i].get("timestamp", 0) - recent_messages[i-1].get("timestamp", 0)
                intervals.append(interval)

            if intervals:
                avg_interval = sum(intervals) / len(intervals)
                current_interval = chat_context.get("timestamp", time.time()) - recent_messages[-1].get("timestamp", 0)

                # 如果当前间隔接近平均间隔，说明对话节奏正常
                if abs(current_interval - avg_interval) / max(avg_interval, 1) < 0.5:
                    flow_score += 0.3
                    # 详细日志：对话节奏加分
                    if self._is_detailed_logging():
                        logger.debug(f"[专注聊天管理器] 对话节奏加分 - 平均间隔: {avg_interval:.1f}秒, 当前间隔: {current_interval:.1f}秒, 当前分数: {flow_score:.3f}")
        else:
            # 详细日志：对话节奏分析条件不足
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 对话节奏分析条件不足 - 最近消息数: {len(recent_messages)}")

        # 2. 话题连贯性分析
        # 简单分析：检查是否有重复的用户交互模式
        user_sequence = [msg.get("user_id", "") for msg in recent_messages]
        transitions = []
        for i in range(len(user_sequence) - 1):
            transitions.append((user_sequence[i], user_sequence[i + 1]))

        # 分析转换模式
        if transitions:
            # 检查是否有重复的交互模式
            unique_transitions = set(transitions)
            if len(unique_transitions) < len(transitions) * 0.7:  # 如果有很多重复的交互模式
                flow_score += 0.4
                # 详细日志：话题连贯性加分
                if self._is_detailed_logging():
                    logger.debug(f"[专注聊天管理器] 话题连贯性加分 - 当前分数: {flow_score:.3f}")

        final_score = min(1.0, flow_score)
        # 详细日志：对话流分析完成
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 对话流分析完成 - 最终分数: {final_score:.3f}")

        return final_score

    def _analyze_temporal_relevance(self, chat_context: Dict) -> float:
        """分析时间相关性"""
        # 详细日志：开始分析时间相关性
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 开始分析时间相关性")
        
        current_time = time.time()
        conversation_history = chat_context.get("conversation_history", [])

        if not conversation_history:
            # 详细日志：无对话历史，返回中等分数
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 无对话历史，时间相关性分数: 0.5")
            return 0.5

        # 分析消息的时间分布
        recent_messages = conversation_history[-20:]  # 最近20条消息
        if len(recent_messages) < 3:
            # 详细日志：消息数量不足，返回中等分数
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 消息数量不足（{len(recent_messages)}条），时间相关性分数: 0.5")
            return 0.5

        # 详细日志：对话历史信息
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 对话历史长度: {len(conversation_history)}, 最近消息数: {len(recent_messages)}")

        # 计算消息的时间间隔
        intervals = []
        for i in range(1, len(recent_messages)):
            interval = recent_messages[i].get("timestamp", 0) - recent_messages[i-1].get("timestamp", 0)
            if interval > 0:
                intervals.append(interval)

        if not intervals:
            # 详细日志：无有效时间间隔，返回中等分数
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 无有效时间间隔，时间相关性分数: 0.5")
            return 0.5

        # 分析时间模式
        avg_interval = sum(intervals) / len(intervals)
        std_dev = (sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)) ** 0.5

        # 详细日志：时间模式分析结果
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 时间模式分析 - 平均间隔: {avg_interval:.1f}秒, 标准差: {std_dev:.1f}秒")

        # 计算当前消息的时间相关性
        last_msg_time = recent_messages[-1].get("timestamp", 0)
        current_interval = current_time - last_msg_time

        # 详细日志：当前时间间隔
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 当前时间间隔: {current_interval:.1f}秒")

        # 如果当前间隔接近平均间隔，说明时间相关性高
        if abs(current_interval - avg_interval) <= std_dev:
            # 详细日志：时间相关性高
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 时间相关性高 - 分数: 0.8")
            return 0.8
        elif abs(current_interval - avg_interval) <= std_dev * 2:
            # 详细日志：时间相关性中等
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 时间相关性中等 - 分数: 0.6")
            return 0.6
        else:
            # 详细日志：时间相关性低
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 时间相关性低 - 分数: 0.3")
            return 0.3
    
    async def enter_focus_mode(self, group_id: str, target_user_id: str):
        """进入专注聊天模式"""
        # 详细日志：开始进入专注模式
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 开始进入专注模式 - 群组: {group_id}, 目标用户: {target_user_id}")
        
        if not getattr(self.config, 'focus_chat_enabled', True):
            # 详细日志：专注模式未启用
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 专注模式未启用，跳过进入专注模式")
            return

        self.state_manager.set_interaction_mode(group_id, "focus")
        self.state_manager.set_focus_target(group_id, target_user_id)

        # 详细日志：专注模式设置完成
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 专注模式设置完成 - 群组: {group_id}, 目标用户: {target_user_id}")

        logger.info(f"群组 {group_id} 进入专注聊天模式，目标用户：{target_user_id}")

    async def should_exit_focus_mode(self, group_id: str, target_user_id: str) -> bool:
        """检查是否应该退出专注模式"""
        # 详细日志：开始检查是否应该退出专注模式
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 开始检查是否应该退出专注模式 - 群组: {group_id}, 目标用户: {target_user_id}")
        
        current_target = self.state_manager.get_focus_target(group_id)
        if current_target != target_user_id:
            # 详细日志：目标用户不匹配
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 目标用户不匹配 - 当前目标: {current_target}, 期望目标: {target_user_id}, 应该退出")
            return True

        # 检查超时
        last_activity = self.state_manager.get_last_activity(target_user_id)
        timeout = getattr(self.config, 'focus_timeout_seconds', 300)
        current_time = time.time()
        time_diff = current_time - last_activity
        
        if time_diff > timeout:
            # 详细日志：超时退出
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 超时退出 - 时间差: {time_diff:.1f}秒, 超时阈值: {timeout}秒, 应该退出")
            return True

        # 检查回复次数限制
        response_count = self.state_manager.get_focus_response_count(group_id)
        max_responses = getattr(self.config, 'focus_max_responses', 10)
        if response_count >= max_responses:
            # 详细日志：回复次数达到限制
            if self._is_detailed_logging():
                logger.debug(f"[专注聊天管理器] 回复次数达到限制 - 当前回复数: {response_count}, 最大回复数: {max_responses}, 应该退出")
            return True

        # 详细日志：无需退出专注模式
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 无需退出专注模式 - 目标用户匹配, 未超时, 回复次数未达限制")
        
        return False

    async def exit_focus_mode(self, group_id: str):
        """退出专注聊天模式"""
        # 详细日志：开始退出专注模式
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 开始退出专注模式 - 群组: {group_id}")
        
        self.state_manager.set_interaction_mode(group_id, "normal")
        self.state_manager.clear_focus_target(group_id)
        self.state_manager.clear_focus_response_count(group_id)

        # 详细日志：专注模式已退出
        if self._is_detailed_logging():
            logger.debug(f"[专注聊天管理器] 专注模式已退出 - 群组: {group_id}")

        logger.info(f"群组 {group_id} 退出专注聊天模式")

    def increment_focus_response_count(self, group_id: str):
        """增加专注模式回复计数"""
        # 详细日志：开始增加专注模式回复计数
        if self._is_detailed_logging():
            current_count = self.state_manager.get_focus_response_count(group_id)
            logger.debug(f"[专注聊天管理器] 开始增加专注模式回复计数 - 群组: {group_id}, 当前计数: {current_count}")
        
        self.state_manager.increment_focus_response_count(group_id)
        
        # 详细日志：专注模式回复计数已增加
        if self._is_detailed_logging():
            new_count = self.state_manager.get_focus_response_count(group_id)
            logger.debug(f"[专注聊天管理器] 专注模式回复计数已增加 - 群组: {group_id}, 新计数: {new_count}")