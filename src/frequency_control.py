"""
频率控制模块

负责管理群聊频率控制，包括消息频率分析、焦点值计算、历史数据管理等。

版本: 2.0.3
作者: Him666233
"""

__version__ = "2.0.3"
__author__ = "Him666233"
__description__ = "频率控制模块：负责管理群聊频率控制"

import time
from collections import deque
import random
from typing import Dict, List, Any, Optional
from pathlib import Path
import json

from astrbot.api import logger

class FrequencyControl:
    # 焦点值调整常量
    FOCUS_INCREASE_RATE = 0.1  # 焦点值增加速率
    FOCUS_DECREASE_RATE = 0.05  # 焦点值减少速率
    SMOOTHING_FACTOR = 0.1  # 平滑因子
    AT_MESSAGE_BOOST_DECAY = 0.95  # @消息增强衰减率
    AT_MESSAGE_BOOST_MIN = 0.01  # @消息增强最小值
    
    # 触发条件常量
    AT_MESSAGE_BOOST_THRESHOLD = 0.8  # @消息增强触发阈值
    MESSAGES_PER_MINUTE_THRESHOLD = 5  # 每分钟消息数触发阈值
    THRESHOLD_BUFFER_MULTIPLIER = 1.2  # 阈值缓冲倍数
    
    # 历史数据限制
    MAX_HISTORICAL_DAYS = 30  # 最大历史数据天数
    SAVE_INTERVAL_MESSAGES = 100  # 保存间隔消息数
    SAVE_INTERVAL_SECONDS = 600  # 保存间隔秒数（10分钟）
    
    # 智能默认值范围
    MORNING_PEAK_MSG_MIN = 25  # 早高峰消息数最小值
    MORNING_PEAK_MSG_MAX = 45  # 早高峰消息数最大值
    LUNCH_PEAK_MSG_MIN = 35  # 午间高峰消息数最小值
    LUNCH_PEAK_MSG_MAX = 55  # 午间高峰消息数最大值
    EVENING_PEAK_MSG_MIN = 40  # 晚高峰消息数最小值
    EVENING_PEAK_MSG_MAX = 65  # 晚高峰消息数最大值
    NIGHT_ACTIVE_MSG_MIN = 45  # 晚上活跃时间消息数最小值
    NIGHT_ACTIVE_MSG_MAX = 75  # 晚上活跃时间消息数最大值
    LATE_NIGHT_MSG_MIN = 10  # 深夜消息数最小值
    LATE_NIGHT_MSG_MAX = 25  # 深夜消息数最大值
    DAYTIME_MSG_MIN = 8  # 白天其他时间消息数最小值
    DAYTIME_MSG_MAX = 20  # 白天其他时间消息数最大值
    
    # 用户数比例范围
    USER_RATIO_MIN = 0.6  # 用户数相对于消息数的最小比例
    USER_RATIO_MAX = 0.8  # 用户数相对于消息数的最大比例

    def __init__(self, group_id: str, state_manager: Optional[Any] = None, config: Optional[Any] = None):
        self.group_id = group_id
        self.state_manager = state_manager
        self.config = config
        self.historical_hourly_avg_users = [0.0] * 24
        self.historical_hourly_avg_msgs = [0.0] * 24

        # 历史数据存储
        self.hourly_message_counts = {hour: [] for hour in range(24)}  # 每个小时的消息计数历史
        self.hourly_user_counts = {hour: [] for hour in range(24)}    # 每个小时的用户计数历史
        self.daily_stats = {}  # 按日期存储的统计数据

        self.load_historical_data()

        self.recent_messages: deque[float] = deque(maxlen=100)  # 存储最近的消息时间戳
        self.recent_users: set = set()  # 最近活跃的用户
        self.focus_value = 0.0
        self.last_update_time = time.time()
        self.at_message_boost = 0.0
        self.at_message_boost_decay = self.AT_MESSAGE_BOOST_DECAY
        self.smoothing_factor = self.SMOOTHING_FACTOR  # 用于平滑焦点值变化的因子
        # 从配置读取参数（如无配置则使用默认）
        self.at_boost_value = float(getattr(self.config, "at_boost_value", 0.5)) if self.config is not None else 0.5
        self.threshold = float(getattr(self.config, "heartbeat_threshold", 0.55)) if self.config is not None else 0.55  # 触发阈值（可运行期调整）

    def _is_detailed_logging(self) -> bool:
        """检查是否启用详细日志"""
        return getattr(self.config, "debug", False) if self.config else False

    def load_historical_data(self):
        """从历史数据加载或生成基础数据。"""
        # 详细日志：开始加载历史数据
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 开始加载历史数据 - 群组: {self.group_id}")
        
        if self.state_manager:
            # 尝试从状态管理器加载历史数据
            historical_data = self.state_manager.get(f"frequency_data_{self.group_id}", {})

            if historical_data and 'hourly_message_counts' in historical_data:
                # 从数据加载
                self.hourly_message_counts = historical_data.get('hourly_message_counts', self.hourly_message_counts)
                self.hourly_user_counts = historical_data.get('hourly_user_counts', self.hourly_user_counts)
                self.daily_stats = historical_data.get('daily_stats', {})
                
                # 修复：确保所有daily_stats中的hourly_breakdown都包含所有24小时键
                self._fix_daily_stats_hourly_breakdown()

                # 计算历史平均值
                self._calculate_historical_averages()
                
                # 详细日志：成功加载历史数据
                if self._is_detailed_logging():
                    logger.debug(f"[频率控制器] 成功加载历史数据 - 群组: {self.group_id}")
                logger.info(f"为群组 {self.group_id} 加载了历史数据。")
                return

        # 如果没有历史数据，使用智能默认值（基于群组类型和时间模式）
        self._generate_smart_defaults()
        
        # 详细日志：生成智能默认数据
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 生成智能默认历史数据 - 群组: {self.group_id}")
        logger.info(f"为群组 {self.group_id} 生成了智能默认的历史数据。")

    def _calculate_historical_averages(self):
        """根据收集的历史数据计算平均值。"""
        for hour in range(24):
            msg_counts = self.hourly_message_counts.get(hour, [])
            user_counts = self.hourly_user_counts.get(hour, [])

            if msg_counts:
                # 计算消息数的平均值
                self.historical_hourly_avg_msgs[hour] = sum(msg_counts) / len(msg_counts)
            else:
                # 如果没有数据，使用智能默认值
                self.historical_hourly_avg_msgs[hour] = self._get_smart_default_msgs(hour)

            if user_counts:
                # 计算用户数的平均值
                self.historical_hourly_avg_users[hour] = sum(user_counts) / len(user_counts)
            else:
                # 如果没有数据，使用智能默认值
                self.historical_hourly_avg_users[hour] = self._get_smart_default_users(hour)

    def _fix_daily_stats_hourly_breakdown(self):
        """修复daily_stats中的hourly_breakdown字典，确保包含所有24小时键。"""
        for date_str, stats in self.daily_stats.items():
            if 'hourly_breakdown' not in stats:
                stats['hourly_breakdown'] = {}
            
            # 确保所有24小时键都存在
            for hour in range(24):
                if hour not in stats['hourly_breakdown']:
                    stats['hourly_breakdown'][hour] = 0

    def _generate_smart_defaults(self):
        """生成基于时间模式的智能默认值。"""
        for hour in range(24):
            self.historical_hourly_avg_msgs[hour] = self._get_smart_default_msgs(hour)
            self.historical_hourly_avg_users[hour] = self._get_smart_default_users(hour)

    def _get_smart_default_msgs(self, hour: int) -> float:
        """根据小时获取智能默认消息数。"""
        # 基于真实群聊模式的默认值
        if 7 <= hour <= 9:  # 早高峰（上班、上学时间）
            return random.uniform(self.MORNING_PEAK_MSG_MIN, self.MORNING_PEAK_MSG_MAX)
        elif 11 <= hour <= 13:  # 午间高峰（午休时间）
            return random.uniform(self.LUNCH_PEAK_MSG_MIN, self.LUNCH_PEAK_MSG_MAX)
        elif 17 <= hour <= 19:  # 晚高峰（下班时间）
            return random.uniform(self.EVENING_PEAK_MSG_MIN, self.EVENING_PEAK_MSG_MAX)
        elif 20 <= hour <= 23:  # 晚上活跃时间
            return random.uniform(self.NIGHT_ACTIVE_MSG_MIN, self.NIGHT_ACTIVE_MSG_MAX)
        elif 0 <= hour <= 2:  # 深夜
            return random.uniform(self.LATE_NIGHT_MSG_MIN, self.LATE_NIGHT_MSG_MAX)
        else:  # 白天其他时间
            return random.uniform(self.DAYTIME_MSG_MIN, self.DAYTIME_MSG_MAX)

    def _get_smart_default_users(self, hour: int) -> float:
        """根据小时获取智能默认用户数。"""
        # 用户数通常是消息数的0.6-0.8倍
        msg_count = self._get_smart_default_msgs(hour)
        return msg_count * random.uniform(self.USER_RATIO_MIN, self.USER_RATIO_MAX)

    def update_message_rate(self, message_timestamp: float, user_id: str = None):
        """记录一条新消息并更新频率指标。"""
        # 详细日志：开始更新消息频率
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 开始更新消息频率 - 群组: {self.group_id}, 用户: {user_id}")
        
        self.recent_messages.append(message_timestamp)

        # 记录用户活跃度
        if user_id:
            self.recent_users.add(user_id)

        # 收集历史数据
        self._collect_historical_data(message_timestamp, user_id)

        self._update_focus()
        
        # 详细日志：消息频率更新完成
        if self._is_detailed_logging():
            current_focus = self.focus_value
            logger.debug(f"[频率控制器] 消息频率更新完成 - 群组: {self.group_id}, 当前焦点值: {current_focus:.3f}")

    def _collect_historical_data(self, timestamp: float, user_id: str = None):
        """收集历史数据用于分析。"""
        current_time = time.localtime(timestamp)
        hour = current_time.tm_hour
        date_str = time.strftime("%Y-%m-%d", current_time)

        # 更新小时统计
        if hour not in self.hourly_message_counts:
            self.hourly_message_counts[hour] = []

        # 限制每个小时最多保存30天的历史数据
        if len(self.hourly_message_counts[hour]) >= self.MAX_HISTORICAL_DAYS:
            self.hourly_message_counts[hour].pop(0)

        self.hourly_message_counts[hour].append(1)  # 每次调用代表一条消息

        # 更新用户统计
        if user_id and hour not in self.hourly_user_counts:
            self.hourly_user_counts[hour] = []

        if user_id:
            if len(self.hourly_user_counts[hour]) >= self.MAX_HISTORICAL_DAYS:
                self.hourly_user_counts[hour].pop(0)
            self.hourly_user_counts[hour].append(1)  # 每次调用代表一个活跃用户

        # 更新每日统计
        if date_str not in self.daily_stats:
            self.daily_stats[date_str] = {
                'total_messages': 0,
                'total_users': 0,
                'hourly_breakdown': {}
            }
            # 初始化所有24小时
            for h in range(24):
                self.daily_stats[date_str]['hourly_breakdown'][h] = 0

        self.daily_stats[date_str]['total_messages'] += 1
        self.daily_stats[date_str]['hourly_breakdown'][hour] += 1

        if user_id:
            self.daily_stats[date_str]['total_users'] += 1

        # 定期保存数据（每10分钟或100条消息保存一次）
        if len(self.recent_messages) % self.SAVE_INTERVAL_MESSAGES == 0 or time.time() - getattr(self, '_last_save_time', 0) > self.SAVE_INTERVAL_SECONDS:
            self._save_historical_data()

    def _save_historical_data(self):
        """保存历史数据到状态管理器。"""
        if not self.state_manager:
            return

        historical_data = {
            'hourly_message_counts': self.hourly_message_counts,
            'hourly_user_counts': self.hourly_user_counts,
            'daily_stats': self.daily_stats,
            'last_updated': time.time()
        }

        self.state_manager.set(f"frequency_data_{self.group_id}", historical_data)
        self._last_save_time = time.time()
        logger.info(f"为群组 {self.group_id} 保存了历史数据。")

    def _update_focus(self):
        """根据当前聊天活动与历史基线的对比，更新焦点值。"""
        # 详细日志：开始更新焦点值
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 开始更新焦点值 - 群组: {self.group_id}")
        
        current_time = time.time()
        delta_time = current_time - self.last_update_time
        self.last_update_time = current_time

        # 计算当前小时的活动
        current_hour = time.localtime(current_time).tm_hour
        messages_in_last_minute = len([t for t in self.recent_messages if current_time - t <= 60])

        # 与历史平均值进行比较
        historical_msgs = self.historical_hourly_avg_msgs[current_hour] / 60.0  # 每分钟
        
        # 详细日志：当前活动与历史基线对比
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 当前活动分析 - 当前小时: {current_hour}, 最近1分钟消息数: {messages_in_last_minute}, 历史基线: {historical_msgs:.2f}条/分钟")
        
        # 这是一个简化的调整逻辑；后续会进行改进
        target_focus = self.focus_value
        if messages_in_last_minute > historical_msgs * 1.5:
            target_focus += self.FOCUS_INCREASE_RATE * (delta_time / 60)  # 增加焦点
            # 详细日志：增加焦点值
            if self._is_detailed_logging():
                logger.debug(f"[频率控制器] 增加焦点值 - 当前消息数超过历史基线1.5倍, 目标焦点: {target_focus:.3f}")
        else:
            target_focus -= self.FOCUS_DECREASE_RATE * (delta_time / 60)  # 减少焦点
            # 详细日志：减少焦点值
            if self._is_detailed_logging():
                logger.debug(f"[频率控制器] 减少焦点值 - 当前消息数低于历史基线1.5倍, 目标焦点: {target_focus:.3f}")

        # 应用平滑处理
        old_focus = self.focus_value
        self.focus_value += (target_focus - self.focus_value) * self.smoothing_factor
        
        # 详细日志：平滑处理结果
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 平滑处理 - 旧焦点: {old_focus:.3f}, 新焦点: {self.focus_value:.3f}, 平滑因子: {self.smoothing_factor}")

        # 应用 @ 消息的衰减增强
        old_boost = self.at_message_boost
        self.at_message_boost *= self.at_message_boost_decay
        if self.at_message_boost < self.AT_MESSAGE_BOOST_MIN:
            self.at_message_boost = 0.0
        
        # 详细日志：@消息增强衰减
        if self._is_detailed_logging() and old_boost != self.at_message_boost:
            logger.debug(f"[频率控制器] @消息增强衰减 - 旧增强值: {old_boost:.3f}, 新增强值: {self.at_message_boost:.3f}")

        # 将焦点值限制在 0 和 1 之间
        old_focus_clamped = self.focus_value
        self.focus_value = max(0, min(1, self.focus_value))
        
        # 详细日志：焦点值限制
        if self._is_detailed_logging() and old_focus_clamped != self.focus_value:
            logger.debug(f"[频率控制器] 焦点值限制 - 原始值: {old_focus_clamped:.3f}, 限制后: {self.focus_value:.3f}")
        
        # 详细日志：焦点值更新完成
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 焦点值更新完成 - 最终焦点值: {self.focus_value:.3f}, @消息增强: {self.at_message_boost:.3f}")

    def boost_on_at(self):
        """当机器人被 @ 时，临时提高焦点值。"""
        # 详细日志：开始处理@消息增强
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 开始处理@消息增强 - 群组: {self.group_id}")
        
        old_boost = self.at_message_boost
        self.at_message_boost = float(self.at_boost_value)  # 使用配置的初始增强值
        
        # 详细日志：@消息增强设置
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] @消息增强设置 - 旧增强值: {old_boost:.3f}, 新增强值: {self.at_message_boost:.3f}, 配置值: {self.at_boost_value}")
        
        logger.info(f"机器人被 @，为群组 {self.group_id} 临时提高焦点。")

    def get_focus(self) -> float:
        """获取当前的焦点值。"""
        self._update_focus()
        return self.focus_value

    def get_messages_in_last_minute(self) -> int:
        """最近一分钟消息条数"""
        current_time = time.time()
        return len([t for t in self.recent_messages if current_time - t <= 60])

    def set_threshold(self, value: float):
        """设置触发阈值（0-1）"""
        try:
            v = float(value)
        except Exception:
            return
        self.threshold = max(0.0, min(1.0, v))

    def should_trigger_by_focus(self) -> bool:
        """根据焦点值决定是否触发回复。"""
        # 详细日志：开始检查是否触发回复
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 开始检查是否触发回复 - 群组: {self.group_id}")
        
        effective_focus = self.get_focus() + self.at_message_boost
        threshold = getattr(self, "threshold", 0.55)
        
        # 详细日志：当前焦点值和阈值
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 当前焦点值 - 基础焦点: {self.get_focus():.3f}, @增强: {self.at_message_boost:.3f}, 有效焦点: {effective_focus:.3f}, 阈值: {threshold:.3f}")
        
        # 只有当@消息增强值非常高时才快速触发
        if self.at_message_boost >= self.AT_MESSAGE_BOOST_THRESHOLD:  # 提高阈值，只有强烈@时才快速触发
            # 详细日志：@消息增强触发
            if self._is_detailed_logging():
                logger.debug(f"[频率控制器] @消息增强触发 - 增强值: {self.at_message_boost:.3f} >= {self.AT_MESSAGE_BOOST_THRESHOLD}, 触发回复")
            return True
            
        # 只有当消息非常活跃时才快速触发（提高消息数量要求）
        messages_in_last_minute = self.get_messages_in_last_minute()
        if messages_in_last_minute >= self.MESSAGES_PER_MINUTE_THRESHOLD:  # 从2条提高到5条
            # 详细日志：消息活跃度触发
            if self._is_detailed_logging():
                logger.debug(f"[频率控制器] 消息活跃度触发 - 最近1分钟消息数: {messages_in_last_minute} >= {self.MESSAGES_PER_MINUTE_THRESHOLD}, 触发回复")
            return True
            
        # 常规路径：比较阈值，但增加更严格的检查
        # 只有当焦点值显著超过阈值时才触发
        trigger_condition = effective_focus > threshold * self.THRESHOLD_BUFFER_MULTIPLIER  # 增加20%的缓冲
        
        # 详细日志：常规阈值检查结果
        if self._is_detailed_logging():
            logger.debug(f"[频率控制器] 常规阈值检查 - 有效焦点: {effective_focus:.3f} > 阈值*1.2: {threshold * 1.2:.3f} = {trigger_condition}")
        
        return trigger_condition