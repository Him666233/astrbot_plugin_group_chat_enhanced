"""
状态管理器模块

负责插件状态的持久化存储，包括交互模式、专注目标、疲劳度等状态信息。

版本: V2.0.4
作者: Him666233
"""

__version__ = "V2.0.4"
__author__ = "Him666233"
__description__ = "状态管理器模块：负责插件状态的持久化存储"

import json
import os
import time
from typing import Dict, Any, Optional
from pathlib import Path

from astrbot.api import logger
from astrbot.api.star import Context

class StateManager:
    """状态管理器 - 负责插件状态的持久化存储"""
    
    def __init__(self, context: Context, config: Any):
        self.context = context
        self.config = config
        
        # 使用AstrBot标准的数据目录获取方式
        try:
            # 尝试使用StarTools.get_data_dir()方法
            from astrbot.api.star import StarTools
            if hasattr(StarTools, 'get_data_dir') and callable(getattr(StarTools, 'get_data_dir')):
                self.data_dir = Path(StarTools.get_data_dir())
            else:
                raise AttributeError("StarTools.get_data_dir method not available")
        except (ImportError, AttributeError, Exception) as e:
            # 回退方案：使用配置中的数据目录
            logger.debug(f"使用标准数据目录获取方式失败，使用回退方案: {e}")
            try:
                data_dir_config = context.get_config().get("data_dir", "data")
                if os.path.isabs(data_dir_config):
                    self.data_dir = Path(data_dir_config)
                else:
                    # 如果是相对路径，相对于插件根目录
                    plugin_root = Path(__file__).parent.parent
                    self.data_dir = plugin_root / data_dir_config
            except Exception as config_error:
                # 最终回退方案：使用默认数据目录
                logger.debug(f"配置数据目录获取失败，使用默认目录: {config_error}")
                plugin_root = Path(__file__).parent.parent
                self.data_dir = plugin_root / "data"
        
        self.plugin_data_dir = self.data_dir / "astrbot_plugin_group_chat"
        
        # 确保数据目录存在
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)
        
        # 状态文件路径
        self.state_file = self.plugin_data_dir / "state.json"
        
        # 内存中的状态
        self._state_cache: Dict[str, Any] = {}
        
        # 加载已有状态
        self._load_state()
        
        logger.info(f"状态管理器初始化完成，数据目录: {self.plugin_data_dir}")
    
    def _is_detailed_logging(self) -> bool:
        """检查是否启用详细日志"""
        try:
            # 检查配置中的enable_detailed_logging开关
            if isinstance(self.config, dict):
                return self.config.get("enable_detailed_logging", False)
            return getattr(self.config, "enable_detailed_logging", False) if self.config else False
        except Exception:
            return False
    
    def _load_state(self):
        """从文件加载状态"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    self._state_cache = json.load(f)
                # 详细日志：状态加载成功
                if self._is_detailed_logging():
                    logger.debug(f"[状态管理器] 状态加载成功 - 文件: {self.state_file}, 状态键数量: {len(self._state_cache)}")
                logger.info(f"已从 {self.state_file} 加载状态数据")
            except Exception as e:
                logger.error(f"加载状态文件失败: {e}")
                self._state_cache = {}
        else:
            # 详细日志：状态文件不存在
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 状态文件不存在 - 文件: {self.state_file}, 使用空状态")
            logger.info("状态文件不存在，使用空状态")
            self._state_cache = {}
    
    def _save_state(self):
        """保存状态到文件"""
        try:
            # 详细日志：开始保存状态
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 开始保存状态 - 文件: {self.state_file}, 状态键数量: {len(self._state_cache)}")
            
            # 创建备份
            if self.state_file.exists():
                backup_file = self.state_file.with_suffix('.json.backup')
                backup_file.write_text(self.state_file.read_text(encoding='utf-8'), encoding='utf-8')
                # 详细日志：备份创建成功
                if self._is_detailed_logging():
                    logger.debug(f"[状态管理器] 备份创建成功 - 备份文件: {backup_file}")
            
            # 保存新状态
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self._state_cache, f, ensure_ascii=False, indent=2)
            
            # 详细日志：状态保存成功
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 状态保存成功 - 文件: {self.state_file}")
            
            logger.debug(f"状态已保存到 {self.state_file}")
        except Exception as e:
            logger.error(f"保存状态文件失败: {e}")
            # 详细日志：状态保存失败
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 状态保存失败 - 错误: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取状态值"""
        value = self._state_cache.get(key, default)
        # 详细日志：获取状态值
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 获取状态 - 键: {key}, 值: {value}, 默认值: {default}")
        return value
    
    def set(self, key: str, value: Any):
        """设置状态值"""
        # 详细日志：设置状态值
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 设置状态 - 键: {key}, 值: {value}")
        self._state_cache[key] = value
        self._save_state()
    
    def update(self, key: str, value: Any, save: bool = True):
        """更新状态值（可选择是否立即保存）"""
        # 详细日志：更新状态值
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 更新状态 - 键: {key}, 值: {value}, 立即保存: {save}")
        self._state_cache[key] = value
        if save:
            self._save_state()
    
    def delete(self, key: str):
        """删除状态值"""
        if key in self._state_cache:
            # 详细日志：删除状态值
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 删除状态 - 键: {key}")
            del self._state_cache[key]
            self._save_state()
    
    def get_interaction_modes(self) -> Dict[str, str]:
        """获取交互模式状态"""
        return self.get("interaction_modes", {})
    
    def set_interaction_mode(self, group_id: str, mode: str):
        """设置交互模式"""
        # 详细日志：设置交互模式
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 设置交互模式 - 群组: {group_id}, 模式: {mode}")
        modes = self.get_interaction_modes()
        modes[group_id] = mode
        self.set("interaction_modes", modes)
    
    def get_focus_targets(self) -> Dict[str, str]:
        """获取专注聊天目标"""
        return self.get("focus_targets", {})
    
    def set_focus_target(self, group_id: str, user_id: str):
        """设置专注聊天目标"""
        # 详细日志：设置专注聊天目标
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 设置专注聊天目标 - 群组: {group_id}, 用户: {user_id}")
        targets = self.get_focus_targets()
        targets[group_id] = user_id
        self.set("focus_targets", targets)
    
    def remove_focus_target(self, group_id: str):
        """移除专注聊天目标"""
        targets = self.get_focus_targets()
        if group_id in targets:
            # 详细日志：移除专注聊天目标
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 移除专注聊天目标 - 群组: {group_id}")
            del targets[group_id]
            self.set("focus_targets", targets)

    def get_group_umo_map(self) -> Dict[str, str]:
        """获取群组会话标识映射（unified_msg_origin 映射）"""
        return self.get("group_umo_map", {})

    def set_group_umo(self, group_id: str, umo: str):
        """记录群组的 unified_msg_origin，供主动消息发送使用"""
        # 详细日志：设置群组UMO
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 设置群组UMO - 群组: {group_id}, UMO: {umo}")
        mapping = self.get_group_umo_map()
        mapping[group_id] = umo
        self.set("group_umo_map", mapping)

    def get_group_umo(self, group_id: str) -> Optional[str]:
        """获取群组的 unified_msg_origin"""
        return self.get_group_umo_map().get(group_id)
    
    def get_fatigue_data(self) -> Dict[str, float]:
        """获取疲劳度数据"""
        return self.get("fatigue_data", {})
    
    def update_fatigue(self, user_id: str, fatigue_value: float):
        """更新疲劳度"""
        # 详细日志：更新疲劳度
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 更新疲劳度 - 用户: {user_id}, 疲劳值: {fatigue_value:.3f}")
        fatigue_data = self.get_fatigue_data()
        fatigue_data[user_id] = fatigue_value
        self.set("fatigue_data", fatigue_data)
    
    def get_conversation_counts(self) -> Dict[str, Dict[str, int]]:
        """获取对话计数"""
        return self.get("conversation_counts", {})
    
    def increment_conversation_count(self, group_id: str, user_id: str):
        """增加对话计数"""
        # 详细日志：增加对话计数
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 增加对话计数 - 群组: {group_id}, 用户: {user_id}")
        counts = self.get_conversation_counts()
        if group_id not in counts:
            counts[group_id] = {}
        counts[group_id][user_id] = counts[group_id].get(user_id, 0) + 1
        self.set("conversation_counts", counts)
    
    def get_last_activity(self, key: str) -> float:
        """获取指定键的最后活动时间"""
        value = self.get("last_activity", {}).get(key, 0.0)
        # 详细日志：获取最后活动时间
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 获取最后活动时间 - 键: {key}, 值: {value}")
        return value

    def update_last_activity(self, key: str, timestamp: float = None):
        """更新最后活动时间"""
        if timestamp is None:
            timestamp = time.time()
        # 详细日志：更新最后活动时间
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 更新最后活动时间 - 键: {key}, 时间戳: {timestamp}")
        activity = self.get("last_activity", {})
        activity[key] = timestamp
        self.set("last_activity", activity)

    def get_user_impression(self, user_id: str) -> Dict[str, Any]:
        """获取用户印象"""
        impression = self.get("user_impressions", {}).get(user_id, {})
        # 详细日志：获取用户印象
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 获取用户印象 - 用户: {user_id}, 印象数据: {len(impression)} 个字段")
        return impression

    def get_focus_target(self, group_id: str) -> Optional[str]:
        """获取专注聊天目标"""
        target = self.get_focus_targets().get(group_id)
        # 详细日志：获取专注聊天目标
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 获取专注聊天目标 - 群组: {group_id}, 目标: {target}")
        return target

    def clear_focus_target(self, group_id: str):
        """清除专注聊天目标"""
        targets = self.get_focus_targets()
        if group_id in targets:
            # 详细日志：清除专注聊天目标
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 清除专注聊天目标 - 群组: {group_id}")
            del targets[group_id]
            self.set("focus_targets", targets)

    def get_focus_response_count(self, group_id: str) -> int:
        """获取专注聊天回复计数"""
        count = self.get("focus_response_counts", {}).get(group_id, 0)
        # 详细日志：获取专注聊天回复计数
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 获取专注聊天回复计数 - 群组: {group_id}, 计数: {count}")
        return count

    def increment_focus_response_count(self, group_id: str):
        """增加专注聊天回复计数"""
        # 详细日志：增加专注聊天回复计数
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 增加专注聊天回复计数 - 群组: {group_id}")
        counts = self.get("focus_response_counts", {})
        counts[group_id] = counts.get(group_id, 0) + 1
        self.set("focus_response_counts", counts)

    def clear_focus_response_count(self, group_id: str):
        """清除专注聊天回复计数"""
        counts = self.get("focus_response_counts", {})
        if group_id in counts:
            # 详细日志：清除专注聊天回复计数
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 清除专注聊天回复计数 - 群组: {group_id}")
            del counts[group_id]
            self.set("focus_response_counts", counts)
    
    def get_consecutive_responses(self) -> Dict[str, int]:
        """获取连续回复计数"""
        return self.get("consecutive_responses", {})
    
    def increment_consecutive_response(self, group_id: str):
        """增加连续回复计数"""
        # 详细日志：增加连续回复计数
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 增加连续回复计数 - 群组: {group_id}")
        responses = self.get_consecutive_responses()
        responses[group_id] = responses.get(group_id, 0) + 1
        self.set("consecutive_responses", responses)
    
    def reset_consecutive_response(self, group_id: str):
        """重置连续回复计数"""
        responses = self.get_consecutive_responses()
        if group_id in responses:
            # 详细日志：重置连续回复计数
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 重置连续回复计数 - 群组: {group_id}")
            responses[group_id] = 0
            self.set("consecutive_responses", responses)
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "interaction_modes_count": len(self.get_interaction_modes()),
            "focus_targets_count": len(self.get_focus_targets()),
            "fatigue_users_count": len(self.get_fatigue_data()),
            "conversation_groups_count": len(self.get_conversation_counts()),
            "last_activity_count": len(self.get("last_activity", {})),
            "consecutive_responses_count": len(self.get_consecutive_responses()),
            "state_file": str(self.state_file),
            "state_file_exists": self.state_file.exists(),
            "state_file_size": self.state_file.stat().st_size if self.state_file.exists() else 0
        }
    
    def clear_all_state(self):
        """清空所有状态"""
        # 详细日志：开始清空所有状态
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 开始清空所有状态 - 当前状态键数量: {len(self._state_cache)}")
        
        self._state_cache.clear()
        self._save_state()
        
        # 详细日志：所有状态已清空
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 所有状态已清空")
        
        logger.info("所有状态已清空")
    
    def backup_state(self, backup_name: str = None) -> str:
        """备份状态到指定文件"""
        if backup_name is None:
            backup_name = f"state_backup_{int(time.time())}.json"
        
        backup_file = self.plugin_data_dir / backup_name
        
        # 详细日志：开始备份状态
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 开始备份状态 - 备份文件: {backup_file}, 状态键数量: {len(self._state_cache)}")
        
        try:
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(self._state_cache, f, ensure_ascii=False, indent=2)
            
            # 详细日志：状态备份成功
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 状态备份成功 - 备份文件: {backup_file}")
            
            logger.info(f"状态已备份到 {backup_file}")
            return str(backup_file)
        except Exception as e:
            logger.error(f"备份状态失败: {e}")
            # 详细日志：状态备份失败
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 状态备份失败 - 错误: {e}")
            raise
    
    def restore_state(self, backup_file_path: str):
        """从备份文件恢复状态"""
        backup_file = Path(backup_file_path)
        
        # 详细日志：开始恢复状态
        if self._is_detailed_logging():
            logger.debug(f"[状态管理器] 开始恢复状态 - 备份文件: {backup_file}")
        
        if not backup_file.exists():
            raise FileNotFoundError(f"备份文件不存在: {backup_file}")
        
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                backup_state = json.load(f)
            
            # 详细日志：备份文件加载成功
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 备份文件加载成功 - 备份状态键数量: {len(backup_state)}")
            
            # 验证备份文件格式
            if not isinstance(backup_state, dict):
                raise ValueError("备份文件格式错误")
            
            # 恢复状态
            self._state_cache = backup_state
            self._save_state()
            
            # 详细日志：状态恢复成功
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 状态恢复成功 - 恢复后状态键数量: {len(self._state_cache)}")
            
            logger.info(f"状态已从 {backup_file} 恢复")
        except Exception as e:
            logger.error(f"恢复状态失败: {e}")
            # 详细日志：状态恢复失败
            if self._is_detailed_logging():
                logger.debug(f"[状态管理器] 状态恢复失败 - 错误: {e}")
            raise