import time
import math
import re
from typing import Any, Dict

from astrbot.api import logger
from astrbot.api.star import Context
from state_manager import StateManager
from impression_manager import ImpressionManager

try:
    import jieba
    HAS_JIEBA = True
except ImportError:
    HAS_JIEBA = False
    logger.info("jieba 未安装，使用内置分词")

class WillingnessCalculator:
    """意愿计算器"""

    def __init__(self, context: Context, config: Any, impression_manager: ImpressionManager, state_manager: StateManager):
        self.context = context
        self.config = config
        self.impression_manager = impression_manager
        self.state_manager = state_manager
    
    def _is_detailed_logging(self) -> bool:
        """检查是否启用详细日志"""
        # 先检查顶层配置
        if hasattr(self.config, 'enable_detailed_logging') and self.config.enable_detailed_logging:
            return True
        # 再检查意愿计算器特定配置
        if hasattr(self.config, 'willingness_calculator') and hasattr(self.config.willingness_calculator, 'enable_detailed_logging'):
            return self.config.willingness_calculator.enable_detailed_logging
        return False
    
    async def calculate_response_willingness(self, event: Any, chat_context: Dict) -> Dict:
        """计算回复意愿，返回包含决策结果的字典"""
        user_id = event.get_sender_id()
        group_id = event.get_group_id()

        # 详细日志：开始计算意愿
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 开始计算回复意愿 - 用户: {user_id}, 群组: {group_id}")

        # 获取配置
        base_probability = getattr(self.config, 'base_probability', 0.3)
        willingness_threshold = getattr(self.config, 'willingness_threshold', 0.5)

        # 获取用户印象
        user_impression = await self.impression_manager.get_user_impression(user_id, group_id)
        impression_score = user_impression.get("score", 0.5)

        # 检查重复消息（防止重复回复同一问题）
        duplicate_penalty = self._check_duplicate_message(event, chat_context)

        # 计算各种因素
        group_activity = self._calculate_group_activity(chat_context)
        continuity_bonus = self._calculate_continuity_bonus(user_id, chat_context)
        fatigue_penalty = self._calculate_fatigue_penalty(user_id, chat_context)

        # 心流节奏融入：基于时间间隔动态调整阈值
        dynamic_threshold = self._calculate_dynamic_threshold(event, chat_context, willingness_threshold)

        # 详细日志：各因素计算结果
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 各因素计算结果 - 基础概率: {base_probability:.3f}, 印象分: {impression_score:.3f}, "
                       f"群活跃度: {group_activity:.3f}, 连续奖励: {continuity_bonus:.3f}, "
                       f"疲劳惩罚: {fatigue_penalty:.3f}, 重复惩罚: {duplicate_penalty:.3f}, "
                       f"动态阈值: {dynamic_threshold:.3f}")

        # 综合计算基础意愿值（应用重复消息惩罚）
        calculated_willingness = (
            base_probability * 0.3 +
            impression_score * 0.4 +
            group_activity * 0.2 +
            continuity_bonus * 0.1 -
            fatigue_penalty -
            duplicate_penalty
        )

        final_willingness = max(0.0, min(1.0, calculated_willingness))

        # 详细日志：最终意愿值
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 意愿计算结果 - 计算值: {calculated_willingness:.3f}, 最终值: {final_willingness:.3f}")

        # 如果启用读空气功能，让 LLM 做最终决策
        if getattr(self.config, 'air_reading_enabled', True):
            # 详细日志：读空气模式决策
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 读空气模式 - 意愿值: {final_willingness:.3f}, 动态阈值: {dynamic_threshold:.3f}, "
                           f"由LLM决定是否回复")
            
            result = {
                "should_respond": None,  # 由 LLM 决定
                "willingness_score": final_willingness,
                "requires_llm_decision": True,
                "decision_context": {
                    "base_willingness": final_willingness,
                    "impression_score": impression_score,
                    "group_activity": group_activity,
                    "fatigue_level": fatigue_penalty,
                    "interaction_mode": chat_context.get("current_mode", "normal"),
                    "dynamic_threshold": dynamic_threshold
                }
            }
        else:
            # 应用动态阈值（心流节奏）
            should_respond = final_willingness >= dynamic_threshold
            
            # 详细日志：直接阈值决策
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 直接阈值决策 - 意愿值: {final_willingness:.3f}, 动态阈值: {dynamic_threshold:.3f}, "
                           f"是否回复: {should_respond}")
            
            result = {
                "should_respond": should_respond,
                "willingness_score": final_willingness,
                "requires_llm_decision": False,
                "decision_context": {
                    "base_willingness": final_willingness,
                    "original_threshold": willingness_threshold,
                    "dynamic_threshold": dynamic_threshold
                }
            }
        
        # 详细日志：最终决策结果
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 决策完成 - 结果: {result}")
        
        return result
    
    def _calculate_group_activity(self, chat_context: Dict) -> float:
        """计算多维度群活跃度"""
        conversation_history = chat_context.get("conversation_history", [])
        if not conversation_history:
            return 0.0

        current_time = time.time()

        # 1. 时间窗口分析（多时间段）
        time_windows = [
            (60, 0.4),   # 最近1分钟，权重40%
            (300, 0.3),  # 最近5分钟，权重30%
            (1800, 0.2), # 最近30分钟，权重20%
            (3600, 0.1), # 最近1小时，权重10%
        ]

        activity_score = 0.0
        for window_seconds, weight in time_windows:
            recent_count = sum(1 for msg in conversation_history
                             if current_time - msg.get("timestamp", 0) < window_seconds)
            # 标准化到0-1范围（假设每分钟最大5条消息为活跃）
            normalized_count = min(1.0, recent_count / (window_seconds / 60 * 5))
            activity_score += normalized_count * weight

        # 2. 用户参与度分析
        recent_users = set()
        for msg in conversation_history:
            if current_time - msg.get("timestamp", 0) < 300:  # 最近5分钟
                recent_users.add(msg.get("user_id", ""))

        user_participation = min(1.0, len(recent_users) / 10.0)  # 假设10个活跃用户为满分

        # 3. 消息质量评估
        quality_score = self._assess_message_quality(conversation_history, current_time)

        # 4. 话题持续性分析
        topic_continuity = self._assess_topic_continuity(conversation_history, current_time)

        # 综合评分（活跃度40% + 用户参与30% + 质量20% + 持续性10%）
        final_activity = (
            activity_score * 0.4 +
            user_participation * 0.3 +
            quality_score * 0.2 +
            topic_continuity * 0.1
        )

        return min(1.0, max(0.0, final_activity))

    def _assess_message_quality(self, conversation_history: list, current_time: float) -> float:
        """评估消息质量"""
        recent_messages = [msg for msg in conversation_history
                          if current_time - msg.get("timestamp", 0) < 300]

        if not recent_messages:
            return 0.0

        quality_scores = []
        for msg in recent_messages:
            content = msg.get("content", "")
            score = 0.0

            # 长度评估（太短或太长都降低质量）
            content_length = len(content.strip())
            if 5 <= content_length <= 200:
                score += 0.3
            elif content_length > 200:
                score += 0.1  # 过长消息质量较低

            # 互动性评估（包含@、问号等）
            if "@" in content or "？" in content or "?" in content:
                score += 0.4

            # 情感表达评估（包含表情符号、感叹号等）
            if any(char in content for char in ["！", "!", "😊", "😂", "👍", "❤️"]):
                score += 0.3

            quality_scores.append(min(1.0, score))

        return sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

    def _assess_topic_continuity(self, conversation_history: list, current_time: float) -> float:
        """评估话题持续性"""
        recent_messages = [msg for msg in conversation_history
                          if current_time - msg.get("timestamp", 0) < 600]  # 最近10分钟

        if len(recent_messages) < 3:
            return 0.0

        # 简单的话题持续性：检查是否有重复的用户交互
        user_sequence = [msg.get("user_id", "") for msg in recent_messages[-10:]]
        continuity_score = 0.0

        # 检查连续对话模式
        for i in range(len(user_sequence) - 1):
            if user_sequence[i] == user_sequence[i + 1]:
                continuity_score += 0.2  # 连续发言加分

        # 检查回复模式（用户A -> 用户B -> 用户A）
        if len(user_sequence) >= 3:
            for i in range(len(user_sequence) - 2):
                if (user_sequence[i] == user_sequence[i + 2] and
                    user_sequence[i] != user_sequence[i + 1]):
                    continuity_score += 0.3  # 回复模式加分

        return min(1.0, continuity_score)
    
    def _calculate_continuity_bonus(self, user_id: str, chat_context: Dict) -> float:
        """计算连续对话奖励"""
        conversation_history = chat_context.get("conversation_history", [])
        group_id = chat_context.get("group_id", "default")

        bonus = 0.0

        # 1. 检查是否与同一用户连续对话（原有逻辑）
        if len(conversation_history) >= 2:
            last_two = conversation_history[-2:]
            if all(msg.get("user_id") == user_id for msg in last_two):
                bonus += 0.2  # 连续对话奖励

        # 2. 融入相似度计算：检查与最近机器人回复的相似度
        if len(conversation_history) >= 1:
            # 找到最近的机器人回复
            last_bot_reply = None
            for msg in reversed(conversation_history):
                if msg.get("role") == "assistant":
                    last_bot_reply = msg.get("content", "")
                    break

            if last_bot_reply:
                # 获取当前消息（假设是conversation_history的最后一个）
                current_msg = conversation_history[-1] if conversation_history else None
                if current_msg and current_msg.get("role") == "user":
                    current_content = current_msg.get("content", "")
                    # 计算相似度
                    similarity = self._hf_similarity(last_bot_reply, current_content, group_id)
                    # 相似度奖励：0.7以上给0.3，0.5-0.7给0.15
                    if similarity >= 0.7:
                        bonus += 0.3
                    elif similarity >= 0.5:
                        bonus += 0.15

        return min(0.5, bonus)  # 最高奖励0.5
    
    def _check_duplicate_message(self, event: Any, chat_context: Dict) -> float:
        """检查重复消息，返回惩罚值（0-1之间）"""
        conversation_history = chat_context.get("conversation_history", [])
        if not conversation_history:
            return 0.0
        
        current_message = event.message_str.strip()
        current_time = time.time()
        
        # 详细日志：开始检查重复消息
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 开始检查重复消息 - 当前消息: {current_message[:50]}...")
        
        # 检查最近3分钟内的消息（更短的时间窗口）
        recent_messages = [
            msg for msg in conversation_history 
            if current_time - msg.get("timestamp", 0) < 180  # 3分钟内
        ]
        
        if not recent_messages:
            # 详细日志：无最近消息
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 重复检查 - 无最近3分钟内的消息")
            return 0.0
        
        # 查找所有机器人回复
        bot_replies = []
        user_messages = []
        
        for msg in recent_messages:
            if msg.get("role") == "assistant":
                bot_replies.append(msg.get("content", "").strip())
            elif msg.get("role") == "user":
                user_messages.append({
                    "content": msg.get("content", "").strip(),
                    "timestamp": msg.get("timestamp", 0)
                })
        
        # 如果没有机器人回复，不需要检查重复
        if not bot_replies:
            # 详细日志：无机器人回复
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 重复检查 - 无机器人回复，无需检查")
            return 0.0
        
        # 检查当前消息是否与最近的用户消息相似（可能是用户重复发送）
        if user_messages:
            # 获取最近的非当前用户消息
            recent_user_messages = [msg for msg in user_messages if msg["content"] != current_message]
            if recent_user_messages:
                latest_user_msg = recent_user_messages[-1]["content"]
                similarity = self._hf_similarity(current_message, latest_user_msg, chat_context.get("group_id", "default"))
                
                # 详细日志：用户消息相似度检查
                if self._is_detailed_logging():
                    logger.debug(f"[意愿计算器] 重复检查 - 用户消息相似度: {similarity:.3f}")
                
                # 如果与最近用户消息高度相似，可能是重复问题
                if similarity > 0.8:
                    logger.info(f"检测到与最近用户消息重复，相似度: {similarity:.2f}，给予惩罚")
                    # 详细日志：高相似度惩罚
                    if self._is_detailed_logging():
                        logger.debug(f"[意愿计算器] 重复检查 - 高相似度惩罚: 0.6")
                    return 0.6  # 较高惩罚
        
        # 检查当前消息是否与机器人回复前的用户消息相似
        # 按时间顺序处理消息
        sorted_messages = sorted(recent_messages, key=lambda x: x.get("timestamp", 0))
        
        for i, msg in enumerate(sorted_messages):
            if msg.get("role") == "assistant":
                # 找到机器人回复，检查前面的用户消息
                if i > 0:
                    prev_msg = sorted_messages[i-1]
                    if prev_msg.get("role") == "user":
                        user_msg_content = prev_msg.get("content", "").strip()
                        similarity = self._hf_similarity(current_message, user_msg_content, chat_context.get("group_id", "default"))
                        
                        # 详细日志：机器人回复前消息相似度检查
                        if self._is_detailed_logging():
                            logger.debug(f"[意愿计算器] 重复检查 - 机器人回复前消息相似度: {similarity:.3f}")
                        
                        # 如果高度相似，认为是重复问题
                        if similarity > 0.7:
                            logger.info(f"检测到重复问题消息，相似度: {similarity:.2f}，给予惩罚")
                            # 详细日志：中等相似度惩罚
                            if self._is_detailed_logging():
                                logger.debug(f"[意愿计算器] 重复检查 - 中等相似度惩罚: 0.4")
                            return 0.4  # 中等惩罚
        
        # 详细日志：无重复消息
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 重复检查 - 无重复消息，惩罚: 0.0")
        
        return 0.0
    
    def _calculate_fatigue_penalty(self, user_id: str, chat_context: Dict) -> float:
        """计算疲劳度惩罚"""
        fatigue_data = self.state_manager.get_fatigue_data()
        user_fatigue = fatigue_data.get(user_id, 0)

        # 详细日志：疲劳度检查
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 疲劳度检查 - 用户: {user_id}, 疲劳值: {user_fatigue}")

        # 根据疲劳度计算惩罚
        fatigue_threshold = getattr(self.config, 'fatigue_threshold', 5)
        if user_fatigue >= fatigue_threshold:
            # 详细日志：高疲劳度惩罚
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 疲劳度检查 - 高疲劳度惩罚: 0.5")
            return 0.5  # 高疲劳度惩罚

        penalty = user_fatigue * 0.05  # 线性疲劳惩罚
        
        # 详细日志：线性疲劳惩罚
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 疲劳度检查 - 线性疲劳惩罚: {penalty:.3f}")
        
        return penalty

    def _calculate_dynamic_threshold(self, event: Any, chat_context: Dict, base_threshold: float) -> float:
        """计算动态阈值（心流节奏融入）"""
        group_id = event.get_group_id()
        if not group_id:
            # 详细日志：无群组ID，返回基础阈值
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 动态阈值计算 - 无群组ID，返回基础阈值: {base_threshold:.3f}")
            return base_threshold

        # 获取心流状态
        state = self._hf_get_state(group_id)
        current_time = time.time()
        conversation_history = chat_context.get("conversation_history", [])

        # 基础冷却时间（45秒）
        cooldown = 45.0

        # 根据活跃度调整冷却时间（活跃时适当缩短）
        recent_count = sum(1 for msg in conversation_history
                          if current_time - msg.get("timestamp", 0) < 60)
        activity_factor = min(1.0, recent_count / 5.0)  # 每分钟最多5条消息为基准
        cooldown = cooldown * (1.0 - 0.3 * activity_factor)

        # 详细日志：动态阈值计算参数
        if self._is_detailed_logging():
            dt = current_time - state.get("last_reply_ts", 0)
            streak = state.get("streak", 0)
            is_at_me = self._hf_is_at_me(event)
            logger.debug(f"[意愿计算器] 动态阈值计算 - 基础阈值: {base_threshold:.3f}, 冷却时间: {cooldown:.1f}s, "
                       f"时间间隔: {dt:.1f}s, 连续回复: {streak}, @提及: {is_at_me}")

        # 检查时间间隔
        dt = current_time - state.get("last_reply_ts", 0)
        if dt < cooldown:
            # 距离上次回复太近，提高阈值（减少回复概率）
            time_penalty = (cooldown - dt) / cooldown * 0.2
            result = min(0.9, base_threshold + time_penalty)
            # 详细日志：时间间隔惩罚
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 动态阈值计算 - 时间间隔惩罚: {result:.3f}")
            return result

        # @提及降低阈值
        if self._hf_is_at_me(event):
            result = max(0.1, base_threshold - 0.1)
            # 详细日志：@提及降低阈值
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 动态阈值计算 - @提及降低阈值: {result:.3f}")
            return result

        # 连续回复数提高阈值
        streak = state.get("streak", 0)
        if streak > 0:
            streak_penalty = min(0.2, streak * 0.05)
            result = min(0.9, base_threshold + streak_penalty)
            # 详细日志：连续回复惩罚
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 动态阈值计算 - 连续回复惩罚: {result:.3f}")
            return result

        # 详细日志：返回基础阈值
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 动态阈值计算 - 返回基础阈值: {base_threshold:.3f}")
        
        return base_threshold

    # 心流算法相关方法
    def _hf_get_state(self, group_id: str) -> Dict:
        """获取心流状态"""
        key = f"heartflow:{group_id}"
        state = self.state_manager.get(key, {})
        if not state:
            state = {
                "energy": 0.8,  # 初始能量
                "last_reply_ts": 0.0,
                "streak": 0
            }
            self.state_manager.set(key, state)
        return state

    def _hf_save_state(self, group_id: str, state: Dict):
        """保存心流状态"""
        key = f"heartflow:{group_id}"
        self.state_manager.set(key, state)

    def _hf_norm_count_last_seconds(self, conversation_history: list, seconds: int) -> float:
        """计算最近N秒内的消息数量并归一化"""
        current_time = time.time()
        recent_count = sum(1 for msg in conversation_history
                          if current_time - msg.get("timestamp", 0) < seconds)
        # 归一化：假设每分钟最多5条消息为活跃
        return min(1.0, recent_count / (seconds / 60 * 5))

    def _hf_is_at_me(self, event: Any) -> bool:
        """检查消息是否@机器人"""
        try:
            # 检查消息链中是否有At组件指向机器人
            if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'message'):
                for comp in event.message_obj.message:
                    if hasattr(comp, 'type') and comp.type == 'at':
                        if hasattr(comp, 'qq') and str(comp.qq) == str(event.get_self_id()):
                            return True
            # 回退：检查文本中是否包含@机器人昵称
            message_str = getattr(event, 'message_str', '')
            bot_nickname = getattr(event, 'get_self_nickname', lambda: '')()
            if bot_nickname and f"@{bot_nickname}" in message_str:
                return True
        except Exception:
            pass
        return False

    def _hf_similarity(self, a: str, b: str, group_id: str) -> float:
        """计算两段文本的相似度（学习Wakepro）"""
        if not a or not b:
            return 0.0

        # 分词处理
        if HAS_JIEBA:
            words_a = list(jieba.cut(a))
            words_b = list(jieba.cut(b))
        else:
            # 无jieba时使用简单正则分词
            words_a = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+|\d+', a)
            words_b = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+|\d+', b)

        # 过滤停用词和单字
        stop_words = {"的", "了", "在", "是", "和", "与", "或", "这", "那", "我", "你", "他", "她", "它"}
        words_a = [w for w in words_a if len(w) > 1 and w not in stop_words]
        words_b = [w for w in words_b if len(w) > 1 and w not in stop_words]

        if not words_a or not words_b:
            return 0.0

        # 计算词频向量
        from collections import Counter
        vec_a = Counter(words_a)
        vec_b = Counter(words_b)

        # 计算余弦相似度
        intersection = set(vec_a.keys()) & set(vec_b.keys())
        numerator = sum(vec_a[word] * vec_b[word] for word in intersection)

        norm_a = math.sqrt(sum(count ** 2 for count in vec_a.values()))
        norm_b = math.sqrt(sum(count ** 2 for count in vec_b.values()))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        cosine = numerator / (norm_a * norm_b)
        # 使用sigmoid函数将结果映射到更合理的范围
        return 1 / (1 + math.exp(-8 * (cosine - 0.6)))

    def _hf_on_user_msg(self, event: Any, chat_context: Dict):
        """用户消息到达时的心流状态更新"""
        group_id = event.get_group_id()
        if not group_id:
            # 详细日志：无群组ID，跳过心流状态更新
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 心流状态更新 - 无群组ID，跳过更新")
            return

        state = self._hf_get_state(group_id)
        conversation_history = chat_context.get("conversation_history", [])

        # 详细日志：心流状态更新开始
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 心流状态更新 - 群组: {group_id}, 当前能量: {state['energy']:.3f}")

        # 基础恢复
        old_energy = state["energy"]
        state["energy"] = min(1.0, state["energy"] + 0.01)
        
        # 详细日志：基础恢复
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 心流状态更新 - 基础恢复: {old_energy:.3f} -> {state['energy']:.3f}")

        # 活跃度加成
        mlm_norm = self._hf_norm_count_last_seconds(conversation_history, 60)
        old_energy = state["energy"]
        state["energy"] = min(1.0, state["energy"] + 0.06 * mlm_norm)
        
        # 详细日志：活跃度加成
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 心流状态更新 - 活跃度加成: {mlm_norm:.3f}, 能量: {old_energy:.3f} -> {state['energy']:.3f}")

        # @提及加成
        is_at_me = self._hf_is_at_me(event)
        if is_at_me:
            old_energy = state["energy"]
            state["energy"] = min(1.0, state["energy"] + 0.10)
            # 详细日志：@提及加成
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 心流状态更新 - @提及加成: 能量: {old_energy:.3f} -> {state['energy']:.3f}")

        # 连续性加成：与最近机器人回复的相似度
        last_bot_reply = None
        for msg in reversed(conversation_history):
            if msg.get("role") == "assistant":
                last_bot_reply = msg.get("content", "")
                break

        if last_bot_reply:
            continuity = self._hf_similarity(last_bot_reply, event.message_str, group_id)
            old_energy = state["energy"]
            state["energy"] = min(1.0, state["energy"] + 0.08 * continuity)
            # 详细日志：连续性加成
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 心流状态更新 - 连续性加成: {continuity:.3f}, 能量: {old_energy:.3f} -> {state['energy']:.3f}")

        # 确保能量不低于最小值
        state["energy"] = max(0.1, state["energy"])

        # 详细日志：最终能量值
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 心流状态更新 - 最终能量: {state['energy']:.3f}")

        self._hf_save_state(group_id, state)

    def _hf_can_pass_gate(self, event: Any, chat_context: Dict) -> bool:
        """检查是否可以通过心流门控"""
        group_id = event.get_group_id()
        
        # 详细日志：开始心流门控检查
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 心流门控检查 - 开始检查群组: {group_id}")
        
        if not group_id:
            # 详细日志：无群组ID，默认通过
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 心流门控检查 - 无群组ID，默认通过")
            return True  # 私聊或其他情况默认通过
        
        # 获取心流状态
        state = self._hf_get_state(group_id)
        energy = state.get("energy", 0.8)
        
        # 详细日志：当前心流能量
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 心流门控检查 - 群组: {group_id}, 当前能量: {energy:.3f}")
        
        # 检查能量阈值
        energy_threshold = 0.3  # 能量低于此值则拒绝
        if energy < energy_threshold:
            # 详细日志：能量不足，拒绝通过
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 心流门控检查 - 能量不足: {energy:.3f} < {energy_threshold}, 拒绝通过")
            return False
        
        # 检查冷却时间
        current_time = time.time()
        last_reply_ts = state.get("last_reply_ts", 0)
        cooldown = 5.0  # 5秒冷却时间
        
        if current_time - last_reply_ts < cooldown:
            # 详细日志：冷却时间未到，拒绝通过
            if self._is_detailed_logging():
                logger.debug(f"[意愿计算器] 心流门控检查 - 冷却时间未到: 距离上次回复 {current_time - last_reply_ts:.1f}s < {cooldown}s, 拒绝通过")
            return False
        
        # 详细日志：通过心流门控检查
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 心流门控检查 - 通过检查，群组: {group_id}, 能量: {energy:.3f}")
        
        return True

    async def on_bot_reply_update(self, event: Any, response_length: int):
        """机器人回复后的状态更新（心流算法）"""
        group_id = event.get_group_id()
        if not group_id:
            return

        # 获取心流状态
        state = self._hf_get_state(group_id)
        
        # 更新最后回复时间
        state["last_reply_ts"] = time.time()
        
        # 根据回复长度消耗能量
        # 回复越长，消耗能量越多
        energy_consumption = min(0.2, response_length / 500.0)  # 最多消耗20%能量
        state["energy"] = max(0.1, state["energy"] - energy_consumption)
        
        # 更新连续回复计数
        state["streak"] = state.get("streak", 0) + 1
        
        # 保存状态
        self._hf_save_state(group_id, state)
        
        # 详细日志：心流状态更新
        if self._is_detailed_logging():
            logger.debug(f"[意愿计算器] 心流状态更新 - 群组: {group_id}, 回复长度: {response_length}, "
                       f"能量消耗: {energy_consumption:.3f}, 当前能量: {state['energy']:.3f}, "
                       f"连续回复: {state['streak']}")