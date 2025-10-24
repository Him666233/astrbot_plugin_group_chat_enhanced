from typing import Dict, List, Optional, Any, AsyncGenerator
import sys
import os
import time
import json
import re
import asyncio
from collections import defaultdict
from pathlib import Path
from asyncio import Lock

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.provider import LLMResponse
from astrbot.core.provider.entities import ToolCallMessageSegment, ToolCallsResult, AssistantMessageSegment
from typing import Dict, List, Optional, Any, AsyncGenerator

# LLM指令常量定义 - 优化版本，直接输出自然文本
IMMERSIVE_SESSION_INSTRUCTION = (
    "你正在与一位用户进行沉浸式对话，需要根据对话历史和人格设定，判断是否要继续回复。"
    "【输出要求】"
    " - 如果你想继续对话，请直接给出你的自然回复内容，不要添加任何格式标记。"
    " - 如果你不想继续对话，请只回复：[DO_NOT_REPLY]"
    " - 不要使用JSON格式，直接输出自然语言。"
    "【判断场景】"
    " - **继续对话**: 当用户的话题有趣、与你相关、或你能提供价值时，直接给出回复。"
    " - **结束对话**: 当用户的话题无关、无聊、或你想结束对话时，回复[DO_NOT_REPLY]。"
    " - **情景感知**: 这是用户的追问，请结合'完整对话历史'理解前因后果，再做出决策。"
)

PROACTIVE_REPLY_INSTRUCTION = (
    "你需要根据对话历史和人格设定，判断是否要回复以及回复什么。"
    "【输出要求】"
    " - 如果你想主动插话，请直接给出你的自然回复内容，不要添加任何格式标记。"
    " - 如果你不想插话，请只回复：[DO_NOT_REPLY]"
    " - 不要使用JSON格式，直接输出自然语言。"
    "【判断场景】"
    " - **主动插话**: 当话题有趣、与你相关、或你能提供价值时，直接给出回复。"
    " - **保持沉默**: 当话题无关、无聊、或你想保持沉默时，回复[DO_NOT_REPLY]。"
    " - **情景感知**: 分析'最近群聊内容'判断当前讨论是否已结束或是一个新开端，结合'完整对话历史'理解前因后果，再做出决策。"
)

# 添加src目录到Python路径 - 使用更安全的方式
current_dir = Path(__file__).parent
src_dir = current_dir / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# 导入自定义模块
try:
    from active_chat_manager import ActiveChatManager
    from group_list_manager import GroupListManager
    from impression_manager import ImpressionManager
    from memory_integration import MemoryIntegration
    from interaction_manager import InteractionManager
    from response_engine import ResponseEngine
    from willingness_calculator import WillingnessCalculator
    from focus_chat_manager import FocusChatManager
    from fatigue_system import FatigueSystem
    from context_analyzer import ContextAnalyzer
    from state_manager import StateManager
    # 不再导入ImageProcessor，功能将整合到main.py中
except ImportError as e:
    logger.warning(f"无法导入部分模块，某些功能可能受限: {e}")

@register("astrbot_plugin_group_chat_enhanced", "Him666233", "增强版群聊插件：融合了沉浸式对话和主动插话功能，提供更智能的群聊交互体验。", "V2.0.4", "https://github.com/qa296/astrbot_plugin_group_chat")
class GroupChatPluginEnhanced(Star):
    _instance = None
    
    def __init__(self, context: Context, config: Any):
        super().__init__(context)
        self.config = config
        # 记录实例用于静态包装器访问
        GroupChatPluginEnhanced._instance = self
        
        # 初始化直接回复插件的功能组件
        self.immersive_lock = Lock()
        self.proactive_lock = Lock()
        self.immersive_sessions = {}  # key: (group_id, user_id)
        self.active_proactive_timers = {}
        self.group_chat_buffer = defaultdict(list)
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 插件初始化开始，配置类型: {type(config).__name__}")
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 配置内容摘要: {self._summarize_config(config)}")
        
        # 初始化群聊插件的功能组件
        try:
            self.state_manager = StateManager(context, config)
            self.group_list_manager = GroupListManager(config)
            self.impression_manager = ImpressionManager(context, config)
            self.memory_integration = MemoryIntegration(context, config)
            self.interaction_manager = InteractionManager(context, config, self.state_manager)
            # 不再创建ImageProcessor实例，功能将整合到main.py中
            self.response_engine = ResponseEngine(context, config, None)
            self.willingness_calculator = WillingnessCalculator(context, config, self.impression_manager, self.state_manager)
            self.focus_chat_manager = FocusChatManager(context, config, self.state_manager)
            self.fatigue_system = FatigueSystem(config, self.state_manager)
            self.context_analyzer = ContextAnalyzer(context, config, self.state_manager, self.impression_manager, self.memory_integration)
            
            self.active_chat_manager = ActiveChatManager(
                context,
                self.state_manager,
                response_engine=self.response_engine,
                context_analyzer=self.context_analyzer,
                willingness_calculator=self.willingness_calculator,
                plugin_config=self.config
            )
        except Exception as e:
            logger.error(f"初始化群聊插件组件时出错: {e}")
            # 设置默认值，防止后续代码访问未初始化的属性时出错
            self.state_manager = None
            self.group_list_manager = None
            self.impression_manager = None
            self.memory_integration = None
            self.interaction_manager = None
            self.response_engine = None
            self.willingness_calculator = None
            self.focus_chat_manager = None
            self.fatigue_system = None
            self.context_analyzer = None
            self.active_chat_manager = None
        
        # 初始化图片拦截状态字典
        self.image_interception_states = {}
        
        # 初始化主动回复互斥标记，防止主动插话和读空气主动对话同时触发
        self._proactive_reply_in_progress = {}  # 群组ID -> 是否正在进行主动插话
        self._air_reading_in_progress = {}     # 群组ID -> 是否正在进行读空气主动对话
        
        logger.info("增强版群聊插件初始化完成 - 已融合沉浸式对话和主动插话功能")
        
        # 初始化图片处理相关缓存
        self.caption_cache = {}
        
        # 初始化工具识别相关缓存
        self.tool_cache = {}
        self.last_tool_update = 0
        self.tool_cache_ttl = 300  # 5分钟缓存时间
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            components = [self.state_manager, self.group_list_manager, self.impression_manager, self.memory_integration, self.interaction_manager, self.response_engine, self.willingness_calculator, self.focus_chat_manager, self.fatigue_system, self.context_analyzer, self.active_chat_manager]
            initialized_count = len([comp for comp in components if comp is not None])
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 插件初始化完成，组件数量: {initialized_count}/{len(components)}")
    
    def _is_detailed_logging(self) -> bool:
        """检查是否启用详细日志输出。"""
        try:
            # 检查配置中的enable_detailed_logging开关
            if isinstance(self.config, dict):
                return self.config.get("enable_detailed_logging", False)
            return False
        except Exception:
            return False
    
    def _summarize_config(self, config: Any) -> str:
        """摘要化配置信息，用于详细日志输出。"""
        try:
            if isinstance(config, dict):
                summary = {
                    "enable_plugin": config.get("enable_plugin", True),
                    "enable_immersive_chat": config.get("enable_immersive_chat", True),
                    "enable_proactive_reply": config.get("enable_proactive_reply", True),
                    "enable_detailed_logging": config.get("enable_detailed_logging", False),
                    "image_processing_enabled": config.get("image_processing", {}).get("enabled", False) if isinstance(config.get("image_processing"), dict) else False
                }
                return str(summary)
            return "配置类型非字典"
        except Exception:
            return "无法摘要配置"
    
    async def _get_available_tools(self) -> Dict[str, Any]:
        """获取AstrBot平台可用的工具列表"""
        current_time = time.time()
        
        # 检查缓存是否有效
        if (current_time - self.last_tool_update < self.tool_cache_ttl and 
            self.tool_cache):
            logger.debug("[工具识别] 使用缓存中的工具列表")
            return self.tool_cache
        
        try:
            # 获取LLM工具管理器
            tool_manager = self.context.get_llm_tool_manager()
            if not tool_manager:
                logger.warning("[工具识别] 无法获取LLM工具管理器")
                return {}
            
            # 获取平台搜索配置信息
            platform_search_config = {}
            try:
                # 尝试获取当前会话的配置
                cfg = self.context.get_config()
                if cfg:
                    prov_settings = cfg.get("provider_settings", {})
                    websearch_enable = prov_settings.get("web_search", False)
                    provider = prov_settings.get("websearch_provider", "default")
                    
                    platform_search_config = {
                        "websearch_enable": websearch_enable,
                        "websearch_provider": provider,
                        "has_search_config": True
                    }
                    logger.info(f"[搜索适配] 平台搜索配置: 启用={websearch_enable}, 提供商={provider}")
                else:
                    platform_search_config = {
                        "websearch_enable": False,
                        "websearch_provider": "default",
                        "has_search_config": False
                    }
                    logger.info("[搜索适配] 无法获取平台配置，使用默认配置")
            except Exception as config_error:
                logger.warning(f"[搜索适配] 获取平台搜索配置失败: {config_error}")
                platform_search_config = {
                    "websearch_enable": False,
                    "websearch_provider": "default",
                    "has_search_config": False
                }
            
            # 获取所有已激活的工具
            active_tools = []
            for tool in tool_manager.func_list:
                if tool.active:
                    tool_info = {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                        "origin": tool.origin or "official"
                    }
                    active_tools.append(tool_info)
            
            # 按来源分类工具
            official_tools = [tool for tool in active_tools if tool["origin"] == "official"]
            plugin_tools = [tool for tool in active_tools if tool["origin"] != "official"]
            
            # 构建工具信息结构
            tools_info = {
                "official_tools": official_tools,
                "plugin_tools": plugin_tools,
                "total_count": len(active_tools),
                "official_count": len(official_tools),
                "plugin_count": len(plugin_tools),
                "last_updated": current_time,
                "platform_search_config": platform_search_config
            }
            
            # 更新缓存
            self.tool_cache = tools_info
            self.last_tool_update = current_time
            
            logger.info(f"[工具识别] 成功获取工具列表: 官方工具{len(official_tools)}个, 插件工具{len(plugin_tools)}个")
            return tools_info
            
        except Exception as e:
            logger.error(f"[工具识别] 获取工具列表时出错: {e}")
            return {}
    
    def _format_tools_prompt(self, tools_info: Dict[str, Any]) -> str:
        """格式化工具信息为AI可理解的提示词"""
        # 使用新的搜索适配版本
        return self._format_tools_prompt_with_search_adapter(tools_info)
    
    async def _should_include_tools_prompt(self, event: AstrMessageEvent) -> bool:
        """判断是否应该在当前消息中包含工具提示
        
        配置示例（在config.json中添加）：
        {
            "tool_prompt": {
                "enable_tool_prompt": true,           // 是否启用工具提示功能
                "enable_auto_mention": true,          // 是否启用自动提及（首次交互/定时提及）
                "enable_keyword_trigger": true,        // 是否启用关键词触发
                "mention_interval": 3600              // 自动提及间隔（秒），默认1小时
            }
        }
        """
        try:
            # 检查配置是否启用工具提示
            if isinstance(self.config, dict):
                tool_prompt_config = self.config.get("tool_prompt", {})
                enable_tool_prompt = tool_prompt_config.get("enable_tool_prompt", True)
                if not enable_tool_prompt:
                    return False
                
                # 获取配置参数
                mention_interval = tool_prompt_config.get("mention_interval", 3600)  # 默认1小时
                enable_auto_mention = tool_prompt_config.get("enable_auto_mention", True)
                enable_keyword_trigger = tool_prompt_config.get("enable_keyword_trigger", True)
            else:
                # 默认配置
                mention_interval = 3600
                enable_auto_mention = True
                enable_keyword_trigger = True
            
            # 关键词触发
            if enable_keyword_trigger:
                message_text = event.message_str.lower()
                tool_keywords = ["工具", "功能", "能做什么", "能力", "function", "tool", "capability", "help", "帮助"]
                
                # 如果消息明确询问工具相关的内容
                if any(keyword in message_text for keyword in tool_keywords):
                    logger.info(f"[工具识别] 检测到工具相关关键词，触发工具提示")
                    return True
            
            # 自动提及机制
            if enable_auto_mention:
                # 检查是否是首次交互或长时间未使用工具
                session_key = (event.get_group_id(), event.get_sender_id())
                last_tool_mention = getattr(self, '_last_tool_mention', {})
                
                current_time = time.time()
                if session_key not in last_tool_mention:
                    last_tool_mention[session_key] = current_time
                    self._last_tool_mention = last_tool_mention
                    logger.info(f"[工具识别] 首次交互，触发工具提示")
                    return True
                
                # 如果超过配置时间未提及工具，再次提及
                if current_time - last_tool_mention[session_key] > mention_interval:
                    last_tool_mention[session_key] = current_time
                    self._last_tool_mention = last_tool_mention
                    logger.info(f"[工具识别] 超过{mention_interval}秒未提及工具，触发工具提示")
                    return True
            
            return False
            
        except Exception as e:
            logger.warning(f"[工具识别] 判断是否包含工具提示时出错: {e}")
            return False

    def _extract_images(self, message_event) -> List[str]:
        """提取消息中的图片"""
        images = []
        
        try:
            # ✅ 方法1：优先从原始消息文本中提取CQ码图片
            raw_message_text = ""
            
            # 尝试多种方式获取原始消息
            try:
                raw_message_text = str(message_event.message_obj.raw_message.get("raw_message", "")).strip()
            except Exception:
                pass
            
            if not raw_message_text:
                try:
                    # 尝试从message_obj直接获取
                    if hasattr(message_event, 'message_obj') and hasattr(message_event.message_obj, '__str__'):
                        raw_message_text = str(message_event.message_obj).strip()
                except Exception:
                    pass
            
            if not raw_message_text:
                raw_message_text = getattr(message_event, 'message_str', '').strip()
            
            logger.debug(f"[图片提取] 原始消息文本: {raw_message_text[:200] if raw_message_text else '无'}")
            
            # ✅ 改进的CQ码图片正则表达式 - 使用非贪婪匹配
            if raw_message_text and '[CQ:image' in raw_message_text:
                
                # 方法1：提取完整的CQ码图片（包括所有参数）
                # 使用 .*? 进行非贪婪匹配，确保不会跨越多个CQ码
                cq_pattern = r'\[CQ:image,([^\]]+)\]'
                cq_matches = re.findall(cq_pattern, raw_message_text)
                
                logger.info(f"[图片提取] 找到 {len(cq_matches)} 个CQ:image标识")
                
                for idx, cq_params in enumerate(cq_matches):
                    logger.debug(f"[图片提取] CQ码参数 {idx+1}: {cq_params[:100]}...")
                    
                    # 提取URL参数（可能在任意位置）
                    url_match = re.search(r'url=([^,\]]+)', cq_params)
                    if url_match:
                        url = url_match.group(1).strip()
                        if url:
                            # 修复HTML转义字符
                            url = url.replace('&amp;', '&')
                            
                            # 检查URL格式，确保是有效的HTTP/HTTPS链接
                            if url.startswith('http://') or url.startswith('https://'):
                                images.append(url)
                                logger.info(f"[图片提取] 从URL参数提取到有效图片 {idx+1}: {url[:80]}...")
                            else:
                                # 如果不是HTTP/HTTPS链接，可能需要转换格式
                                logger.warning(f"[图片提取] 提取到非标准URL格式: {url}")
                                # 尝试转换为有效URL
                                if url.startswith('base64://'):
                                    # base64格式的图片，需要特殊处理
                                    logger.warning(f"[图片提取] 跳过base64格式图片: {url[:50]}...")
                                else:
                                    # 尝试添加http前缀
                                    http_url = f"http://{url}" if not url.startswith('//') else f"http:{url}"
                                    images.append(http_url)
                                    logger.info(f"[图片提取] 转换URL格式为: {http_url[:80]}...")
                            continue
                    
                    # 如果URL提取失败，提取file参数作为备选
                    file_match = re.search(r'file=([^,\]]+)', cq_params)
                    if file_match:
                        file_name = file_match.group(1).strip()
                        if file_name:
                            # file参数通常是本地文件路径，需要转换为可访问的URL
                            logger.warning(f"[图片提取] 提取到file参数: {file_name}")
                            # 对于本地文件路径，LLM无法直接访问，跳过处理
                            logger.warning(f"[图片提取] 跳过本地文件路径图片: {file_name}")
            
            # ✅ 方法2：从消息链中提取图片组件（作为备选）
            if not images:
                try:
                    message_chain = None
                    if hasattr(message_event, 'get_message_chain'):
                        message_chain = message_event.get_message_chain()
                    elif hasattr(message_event, 'message_chain'):
                        message_chain = message_event.message_chain
                    
                    if message_chain:
                        for component in message_chain:
                            if hasattr(component, 'type') and component.type == 'image':
                                if hasattr(component, 'url') and component.url:
                                    url = component.url
                                    # 检查URL格式，确保是有效的HTTP/HTTPS链接
                                    if url.startswith('http://') or url.startswith('https://'):
                                        images.append(url)
                                        logger.info(f"[图片提取] 从消息链提取到有效URL: {url[:80]}...")
                                    else:
                                        logger.warning(f"[图片提取] 从消息链提取到非标准URL格式: {url}")
                                        # 尝试转换为有效URL
                                        if not url.startswith('base64://'):
                                            http_url = f"http://{url}" if not url.startswith('//') else f"http:{url}"
                                            images.append(http_url)
                                            logger.info(f"[图片提取] 转换消息链URL为: {http_url[:80]}...")
                                elif hasattr(component, 'file') and component.file:
                                    # file参数通常是本地文件路径，LLM无法直接访问
                                    logger.warning(f"[图片提取] 从消息链提取到file参数: {component.file}")
                                    logger.warning(f"[图片提取] 跳过本地文件路径图片: {component.file}")
                                elif hasattr(component, 'data') and component.data:
                                    # data参数通常是base64数据，需要特殊处理
                                    logger.warning(f"[图片提取] 从消息链提取到data参数: {component.data[:50]}...")
                                    logger.warning(f"[图片提取] 跳过base64格式图片")
                except Exception as e:
                    logger.debug(f"[图片提取] 从消息链提取失败: {e}")
            
            # 记录最终结果
            if images:
                logger.info(f"[图片提取] 总共提取到 {len(images)} 张图片")
            else:
                logger.debug(f"[图片提取] 未提取到任何图片")
                
        except Exception as e:
            logger.error(f"[图片提取] 提取图片时发生错误: {e}", exc_info=True)
        
        return images

    def _is_at_message(self, message_text: str, message_event) -> bool:
        """检查消息是否为@消息（严格检测，确保真的@了机器人）"""
        
        # 获取配置中的机器人QQ号
        bot_qq_number = self.config.get("bot_qq_number", "").strip()
        if not bot_qq_number:
            logger.warning("[严格@检测] 未配置机器人QQ号，@消息检测功能可能无法正常工作")
            return False
        
        # 方法1：检查事件对象中的@信息（最可靠）
        try:
            if hasattr(message_event, 'get_at_users'):
                at_users = message_event.get_at_users()
                if at_users and len(at_users) > 0:
                    # 检查@用户列表中是否包含机器人QQ号
                    if bot_qq_number in at_users:
                        logger.debug(f"[严格@检测] 检测到@机器人QQ号: {bot_qq_number}")
                        return True
                    else:
                        logger.debug(f"[严格@检测] @用户列表不包含机器人QQ号: {at_users}，机器人QQ号: {bot_qq_number}")
                        return False
        except Exception as e:
            logger.debug(f"[严格@检测] get_at_users检测失败: {e}")
        
        # 方法2：检查消息文本中的@标识（需要更严格的验证）
        if message_text:
            # 首先检查是否配置了机器人名字，如果配置了则进行名字检测
            bot_name = self.config.get("bot_name", "").strip()
            if bot_name:
                # 检测@符号后紧挨着机器人名字的情况（支持括号等特殊字符）
                at_name_pattern1 = r'@' + re.escape(bot_name) + r'(?=\s|$|[^\w\u4e00-\u9fa5])'  # @后紧挨着名字，后面是空格、结束符或非字母数字中文
                # 检测@符号后隔一个空格跟着机器人名字的情况
                at_name_pattern2 = r'@\s+' + re.escape(bot_name) + r'(?=\s|$|[^\w\u4e00-\u9fa5])'
                
                if re.search(at_name_pattern1, message_text) or re.search(at_name_pattern2, message_text):
                    logger.debug(f"[严格@检测] 检测到@机器人名字: {bot_name}")
                    return True
            
            # 检查CQ码格式的@消息
            if "[CQ:at" in message_text:
                # 检查CQ码中是否包含机器人QQ号
                cq_at_pattern = r'\[CQ:at,qq=(\d+)\]'
                matches = re.findall(cq_at_pattern, message_text)
                if matches:
                    if bot_qq_number in matches:
                        logger.debug(f"[严格@检测] 检测到CQ码格式@机器人QQ号: {bot_qq_number}")
                        return True
                    else:
                        logger.debug(f"[严格@检测] CQ码@用户不包含机器人QQ号: {matches}，机器人QQ号: {bot_qq_number}")
                        return False
                else:
                    # 如果没有明确的QQ号，默认认为是有效的@消息
                    logger.debug("[严格@检测] 检测到CQ码格式@消息，但无法解析QQ号")
                    return True
            
            # 检查[At:格式的@消息
            if "[At:" in message_text:
                # 检查[At:格式中是否包含机器人QQ号
                at_pattern = r'\[At:(\d+)\]'
                matches = re.findall(at_pattern, message_text)
                if matches:
                    if bot_qq_number in matches:
                        logger.debug(f"[严格@检测] 检测到[At:格式@机器人QQ号: {bot_qq_number}")
                        return True
                    else:
                        logger.debug(f"[严格@检测] [At:格式@用户不包含机器人QQ号: {matches}，机器人QQ号: {bot_qq_number}")
                        return False
                else:
                    # 如果没有明确的QQ号，默认认为是有效的@消息
                    logger.debug("[严格@检测] 检测到[At:格式@消息，但无法解析QQ号")
                    return True
            
            # 对于普通的@符号，需要更严格的验证
            # 避免误判包含@符号但不@机器人的消息
            if "@" in message_text:
                # 检查@符号后面是否跟着机器人QQ号
                # 匹配@后跟数字（QQ号）的模式
                at_qq_pattern = r'@(\d+)'
                matches = re.findall(at_qq_pattern, message_text)
                if matches:
                    if bot_qq_number in matches:
                        logger.debug(f"[严格@检测] 检测到普通@格式@机器人QQ号: {bot_qq_number}")
                        return True
                    else:
                        logger.debug(f"[严格@检测] 普通@格式@用户不包含机器人QQ号: {matches}，机器人QQ号: {bot_qq_number}")
                        return False
                else:
                    # 检查@符号后面是否跟着有效的内容（不是空格或标点）
                    # 修复：使用Python re模块支持的语法，替换\p{P}为具体的标点符号
                    at_pattern = r'@[^\s\d\.,!?;:\-"\'\[\](){}<>]'  # @后面跟着非空格、非数字、非常见标点的字符
                    if re.search(at_pattern, message_text):
                        logger.debug("[严格@检测] 检测到有效的@消息格式，但无法确定是否@机器人")
                        # 对于无法确定QQ号的@消息，默认返回False，避免误判
                        return False
                    else:
                        logger.debug("[严格@检测] @符号后无有效内容，可能是误判")
        
        logger.debug("[严格@检测] 未检测到有效的@机器人消息")
        return False

    def _get_message_text(self, message_event) -> str:
        """获取消息文本"""
        try:
            if hasattr(message_event, 'message_str'):
                return message_event.message_str
            elif hasattr(message_event, 'get_message_text'):
                return message_event.get_message_text()
            else:
                return str(message_event)
        except Exception:
            return ""

    async def _detect_and_caption_at_images(self, message_event) -> Optional[Dict[str, Any]]:
        """
        @消息图片检测并转文字描述函数
        
        Args:
            message_event: 消息事件对象
            
        Returns:
            如果符合@消息图片条件并处理成功，返回处理结果；否则返回None
        """
        try:
            # 获取@消息图片转文字配置
            logger.info(f"[_detect_and_caption_at_images] 开始执行，self.config类型: {type(self.config)}")
            logger.info(f"[_detect_and_caption_at_images] self.config内容: {self.config}")
            
            # 检查self.config是否为None或空
            if not self.config:
                logger.warning("[_detect_and_caption_at_images] self.config为空或None")
                return None
            
            # 检查self.config是否为字典类型
            if not isinstance(self.config, dict):
                logger.warning(f"[_detect_and_caption_at_images] self.config不是字典类型: {type(self.config)}")
                return None
            
            # 检查image_processing配置是否存在
            if "image_processing" not in self.config:
                logger.warning("[_detect_and_caption_at_images] 配置中缺少image_processing字段")
                return None
        
            image_config = self.config.get("image_processing", {})
            enable_at_image_caption = image_config.get("enable_at_image_caption", False)
            
            logger.info(f"[_detect_and_caption_at_images] 配置检查 - image_config: {image_config}")
            logger.info(f"[_detect_and_caption_at_images] 配置检查 - enable_at_image_caption: {enable_at_image_caption}")
            
            # 如果不启用@消息图片转文字功能，直接返回None
            if not enable_at_image_caption:
                logger.info("[_detect_and_caption_at_images] @消息图片转文字功能未启用")
                return None
        
            # 检查消息是否包含@ - 使用原始消息而不是处理后的消息
            message_text = self._get_message_text(message_event)
            
            # 尝试获取原始消息
            raw_message_text = ""
            try:
                raw_message_text = str(message_event.message_obj.raw_message.get("raw_message", "")).strip()
            except Exception:
                pass
            
            if not raw_message_text:
                try:
                    raw_message_text = str(message_event.message_obj).strip()
                except Exception:
                    pass
            
            if not raw_message_text:
                raw_message_text = getattr(message_event, 'message_str', '').strip()
            
            logger.info(f"[_detect_and_caption_at_images] 原始消息文本: '{raw_message_text[:100] if raw_message_text else '无'}'")
            logger.info(f"[_detect_and_caption_at_images] 处理后消息文本: '{message_text[:100] if message_text else '无'}'")
            
            # 使用原始消息进行@检测
            is_at = self._is_at_message(raw_message_text, message_event)
            logger.info(f"[_detect_and_caption_at_images] @消息检测结果: {is_at}")
            
            if not is_at:
                return None
            
            # 提取消息中的图片
            images = self._extract_images(message_event)
            logger.info(f"[_detect_and_caption_at_images] 提取到的图片数量: {len(images)}")
            logger.info(f"[_detect_and_caption_at_images] 图片列表: {images}")
            
            if not images:
                return None
            
            if self._is_detailed_logging():
                logger.debug(f"检测到@消息包含图片，开始图片转文字处理，图片数量: {len(images)}")
            
            # 获取服务提供商和提示词
            provider_id = image_config.get("at_image_caption_provider_id", "")
            prompt = image_config.get("at_image_caption_prompt", "")
            
            # 获取服务提供商
            if provider_id:
                provider = self.context.get_provider_by_id(provider_id)
            else:
                provider = self.context.get_using_provider()
            
            if not provider:
                logger.warning("无法找到@消息图片转文字服务提供商")
                return None
            
            # 为每张图片生成描述
            captions = []
            for image in images:
                caption = await self._generate_image_caption(image, provider, prompt)
                if caption:
                    captions.append(caption)
            
            if not captions:
                return None
            
            # 合并图片描述和原消息
            combined_message = self._combine_captions_with_message(message_text, captions)
            
            if self._is_detailed_logging():
                logger.debug(f"@消息图片转文字完成，原消息: {message_text[:100]}...，合并后消息: {combined_message[:100]}...")
            
            return {
                "images": [],
                "captions": captions,
                "has_images": True,
                "filtered_message": combined_message
            }
        except Exception as e:
            logger.error(f"[_detect_and_caption_at_images] 方法执行过程中发生异常: {e}", exc_info=True)
            return None

    def _combine_captions_with_message(self, message_text: str, captions: List[str]) -> str:
        """合并图片描述和原消息"""
        if not captions:
            return message_text
        
        caption_text = "，".join(captions)
        return f"{message_text}\n图片内容：{caption_text}"

    async def _generate_image_caption(self, image: str, provider, prompt: str) -> Optional[str]:
        """生成图片描述（增强版）"""
        try:
            # 检查缓存
            if image in self.caption_cache:
                return self.caption_cache[image]
            
            # 使用provider生成图片描述
            if hasattr(provider, 'generate_image_caption'):
                caption = await provider.generate_image_caption(image, prompt)
            else:
                # 如果provider没有generate_image_caption方法，使用默认方式
                caption = await self._generate_image_caption_default(image, provider, prompt)
            
            # 缓存结果
            if caption:
                self.caption_cache[image] = caption
            
            return caption
        except Exception as e:
            logger.error(f"生成图片描述时出错: {e}")
            return None

    async def _generate_image_caption_default(self, image: str, provider, prompt: str) -> Optional[str]:
        """默认的图片描述生成方法"""
        try:
            # 使用provider的text_chat方法来生成图片描述
            # 这是正确的调用方式，参考astrbot_plugin_context_enhancer-main的实现
            logger.info(f"[图片转文字] 开始调用LLM进行图片描述，图片URL: {image[:100]}...")
            logger.info(f"[图片转文字] 使用提示词: {prompt}")
            
            # 正确的调用方式：直接传递prompt和image_urls
            llm_response = await provider.text_chat(prompt=prompt, image_urls=[image])
            
            caption = llm_response.completion_text
            
            logger.info(f"[图片转文字] LLM返回结果: {caption}")
            
            return caption
        except Exception as e:
            logger.error(f"默认图片描述生成失败: {e}", exc_info=True)
            return None

    async def caption_images(self, images: List[str]) -> Optional[str]:
        """手动识别图片方法"""
        try:
            if not images:
                return None
            
            # 获取图片处理配置
            image_config = self.config.get("image_processing", {})
            provider_id = image_config.get("at_image_caption_provider_id", "")
            prompt = image_config.get("at_image_caption_prompt", "")
            
            # 获取服务提供商
            if provider_id:
                provider = self.context.get_provider_by_id(provider_id)
            else:
                provider = self.context.get_using_provider()
            
            if not provider:
                logger.warning("无法找到图片识别服务提供商")
                return None
            
            # 为每张图片生成描述
            captions = []
            for image in images:
                caption = await self._generate_image_caption(image, provider, prompt)
                if caption:
                    captions.append(caption)
            
            if not captions:
                return None
            
            # 合并所有图片描述
            return "，".join(captions)
        except Exception as e:
            logger.error(f"手动识别图片时出错: {e}", exc_info=True)
            return None

    async def _handle_response_fallback(self, completion_text: str, unified_msg_origin: str, context: str):
        """
        优化版本：简化响应处理，提升性能
        
        Args:
            completion_text: LLM的原始回复文本
            unified_msg_origin: 消息来源标识
            context: 上下文描述（用于日志）
        """
        logger.warning(f"[{context}] 处理LLM回复失败，尝试备用方案。原始回复: {completion_text}")
        
        # 简化处理：直接检查是否包含有效回复内容
        if completion_text and completion_text.strip():
            trimmed_text = completion_text.strip()
            
            # 快速检查：如果是纯JSON格式，尝试简单提取
            if trimmed_text.startswith('{') and trimmed_text.endswith('}'):
                try:
                    json_data = json.loads(trimmed_text)
                    if 'content' in json_data and json_data['content']:
                        reply_content = str(json_data['content']).strip()
                        if reply_content:
                            logger.info(f"[{context}] 从JSON中提取到回复内容: {reply_content[:100]}...")
                            message_chain = MessageChain().message(reply_content)
                            await self.context.send_message(unified_msg_origin, message_chain)
                            return
                except:
                    pass
            
            # 如果不是JSON格式或提取失败，直接使用原始内容
            # 过滤掉明显的错误标记
            if not any(keyword in trimmed_text.lower() for keyword in ['json', 'format', 'error', 'invalid', 'should_reply']):
                logger.info(f"[{context}] 使用原始回复内容: {trimmed_text[:100]}...")
                message_chain = MessageChain().message(trimmed_text)
                await self.context.send_message(unified_msg_origin, message_chain)
                return
        
        logger.warning(f"[{context}] LLM回复为空或无效，跳过发送")

    def _extract_json_from_text(self, text: str) -> str:
        """从文本中提取JSON内容（增强版，支持多种格式）"""
        if not text or not text.strip():
            return ""
        
        trimmed_text = text.strip()
        
        # 策略0：检查整个文本是否是有效的JSON（针对纯JSON格式）
        if trimmed_text.startswith('{') and trimmed_text.endswith('}'):
            try:
                json.loads(trimmed_text)
                return trimmed_text
            except:
                pass
        
        # 策略1：寻找被 ```json ... ``` 包裹的代码块
        json_block_pattern = r'```json\s*(\{.*?\})\s*```'
        match = re.search(json_block_pattern, text, re.DOTALL)
        if match:
            json_content = match.group(1).strip()
            try:
                json.loads(json_content)
                return json_content
            except:
                pass

        # 策略2：寻找被 ``` ... ``` 包裹的代码块（不指定语言）
        generic_block_pattern = r'```\s*(\{.*?\})\s*```'
        match = re.search(generic_block_pattern, text, re.DOTALL)
        if match:
            json_content = match.group(1).strip()
            try:
                json.loads(json_content)
                return json_content
            except:
                pass

        # 策略3：寻找被 ```json 和 ``` 包裹的多行代码块（支持换行和缩进）
        multiline_json_pattern = r'```json\s*([\s\S]*?)\s*```'
        match = re.search(multiline_json_pattern, text, re.DOTALL)
        if match:
            json_content = match.group(1).strip()
            try:
                json.loads(json_content)
                return json_content
            except:
                # 尝试清理JSON内容
                json_content = re.sub(r'\s+', ' ', json_content)  # 合并多余空格
                try:
                    json.loads(json_content)
                    return json_content
                except:
                    pass

        # 策略4：寻找被 ``` 和 ``` 包裹的多行代码块（不指定语言，支持换行和缩进）
        multiline_generic_pattern = r'```\s*([\s\S]*?)\s*```'
        match = re.search(multiline_generic_pattern, text, re.DOTALL)
        if match:
            json_content = match.group(1).strip()
            if json_content.startswith('{') and json_content.endswith('}'):
                try:
                    json.loads(json_content)
                    return json_content
                except:
                    # 尝试清理JSON内容
                    json_content = re.sub(r'\s+', ' ', json_content)
                    try:
                        json.loads(json_content)
                        return json_content
                    except:
                        pass

        # 策略5：寻找第一个 { 和最后一个 } 之间的所有内容（增强版）
        start = text.find("{")
        if start != -1:
            brace_count = 0
            json_start = -1
            
            for i in range(start, len(text)):
                if text[i] == '{':
                    if brace_count == 0:
                        json_start = i
                    brace_count += 1
                elif text[i] == '}':
                    brace_count -= 1
                    if brace_count == 0 and json_start != -1:
                        json_content = text[json_start:i+1].strip()
                        try:
                            json.loads(json_content)
                            return json_content
                        except:
                            pass
        
        # 策略6：使用更灵活的正则表达式匹配JSON对象
        json_patterns = [
            r'\{\s*"should_reply"\s*:\s*(?:true|false)\s*,\s*"content"\s*:\s*"[^"]*"\s*\}',  # 标准格式
            r'\{\s*"content"\s*:\s*"[^"]*"\s*,\s*"should_reply"\s*:\s*(?:true|false)\s*\}',  # 字段顺序不同
            r'\{\s*"should_reply"\s*:\s*(?:true|false)\s*\}',  # 只有should_reply
            r'\{\s*"content"\s*:\s*"[^"]*"\s*\}'  # 只有content
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                json_content = match.group(0).strip()
                try:
                    json.loads(json_content)
                    return json_content
                except:
                    pass
        
        # 策略7：如果所有策略都失败，尝试直接解析整个文本
        try:
            json.loads(trimmed_text)
            return trimmed_text
        except:
            pass
            
        return ""

    async def _extract_and_filter_json(self, text: str, event: AstrMessageEvent) -> str:
        """从文本中提取JSON并过滤，返回纯文本内容（用于非沉浸式对话模式）"""
        if not text or not text.strip():
            return text
        
        # 提取JSON内容
        json_string = self._extract_json_from_text(text)
        
        if json_string:
            logger.info(f"[非沉浸式对话] JSON提取成功，内容预览: {json_string[:100]}")
            
            try:
                # 解析JSON
                decision_data = json.loads(json_string)
                content = decision_data.get("content", "")
                
                if content:
                    # 检查是否启用详细日志
                    if self._is_detailed_logging():
                        logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 非沉浸式对话JSON解析成功，content长度={len(content)}")
                    
                    # 过滤掉JSON结构，只保留content内容
                    # 需要移除整个JSON结构，包括可能的代码块标记
                    filtered_text = text
                    
                    # 策略1：如果JSON被代码块包裹，移除整个代码块
                    if "```json" in text and "```" in text:
                        # 使用正则表达式匹配整个代码块
                        code_block_pattern = r'```json\s*\{[\s\S]*?\}\s*```'
                        filtered_text = re.sub(code_block_pattern, "", text, flags=re.DOTALL).strip()
                    else:
                        # 策略2：直接移除JSON内容
                        filtered_text = text.replace(json_string, "").strip()
                    
                    # 如果过滤后还有内容，可能是自然语言部分，需要合并
                    if filtered_text:
                        # 检查content是否已经在过滤后的文本中，避免重复
                        if content not in filtered_text:
                            final_content = content + "\n" + filtered_text
                        else:
                            final_content = filtered_text
                    else:
                        final_content = content
                    
                    logger.info(f"[非沉浸式对话] JSON过滤完成，最终内容长度: {len(final_content)}")
                    return final_content
                else:
                    logger.warning("[非沉浸式对话] JSON中content字段为空")
                    return text
                    
            except Exception as e:
                logger.error(f"[非沉浸式对话] JSON解析失败: {e}")
                # JSON解析失败，返回原始文本
                return text
        else:
            # 没有检测到JSON，返回原始文本
            logger.debug("[非沉浸式对话] 未检测到JSON结构，使用原始回复")
            return text

    async def _arm_immersive_session(self, event: AstrMessageEvent):
        """当机器人回复后，为目标用户启动一个限时的沉浸式会话。"""
        if not self.config.get("enable_immersive_chat", True):
            return

        group_id = event.get_group_id()
        user_id = event.get_sender_id()

        if not group_id or not user_id:
            return

        session_key = (group_id, user_id)
        
        async with self.immersive_lock:
            if session_key in self.immersive_sessions:
                self.immersive_sessions[session_key]['timer'].cancel()

            # 获取完整的对话历史记录，包括平台保存的历史
            context = await self._get_complete_conversation_history(event)

            timeout = self.config.get("immersive_chat_timeout", 120)
            timer = asyncio.get_running_loop().call_later(
                timeout, self._clear_immersive_session, session_key
            )
            
            self.immersive_sessions[session_key] = {
                'context': context,
                'timer': timer
            }
            logger.info(f"[沉浸式对话] 已为群 {group_id} 的用户 {user_id} 开启了 {timeout}s 的沉浸式会话，上下文长度: {len(context)}")

    def _clear_immersive_session(self, session_key):
        """超时后清理沉浸式会话的回调函数"""
        if session_key in self.immersive_sessions:
            self.immersive_sessions.pop(session_key, None)
            logger.debug(f"[沉浸式对话] 会话 {session_key} 已超时并清理。")

    def _get_raw_message_text(self, event) -> str:
        """获取原始消息文本"""
        raw_message_text = ""
        
        # 方式1：从raw_message获取
        try:
            raw_message_text = str(event.message_obj.raw_message.get("raw_message", "")).strip()
        except Exception:
            pass
        
        # 方式2：如果方式1失败，尝试直接从message_obj获取
        if not raw_message_text:
            try:
                raw_message_text = str(event.message_obj).strip()
            except Exception:
                pass
        
        # 方式3：如果都失败，使用message_str
        if not raw_message_text:
            raw_message_text = getattr(event, 'message_str', '').strip()
        
        return raw_message_text

    def _check_at_message_in_text(self, message_text: str, bot_qq_number: str) -> bool:
        """检查消息文本中是否包含@机器人的内容"""
        if not message_text:
            return False
        
        # 首先检查是否配置了机器人名字，如果配置了则进行名字检测
        bot_name = self.config.get("bot_name", "").strip()
        if bot_name:
            # 检测@符号后紧挨着机器人名字的情况（支持括号等特殊字符）
            at_name_pattern1 = r'@' + re.escape(bot_name) + r'(?=\s|$|[^\w\u4e00-\u9fa5])'  # @后紧挨着名字，后面是空格、结束符或非字母数字中文
            # 检测@符号后隔一个空格跟着机器人名字的情况
            at_name_pattern2 = r'@\s+' + re.escape(bot_name) + r'(?=\s|$|[^\w\u4e00-\u9fa5])'
            
            if re.search(at_name_pattern1, message_text) or re.search(at_name_pattern2, message_text):
                logger.info(f"[图片检测] 检测到@机器人名字: {bot_name}")
                return True
        
        # 检查CQ码格式的@消息
        if "[CQ:at" in message_text:
            cq_at_pattern = r'\[CQ:at,qq=(\d+)\]'
            matches = re.findall(cq_at_pattern, message_text)
            if matches:
                if bot_qq_number in matches:
                    logger.info(f"[图片检测] 检测到CQ码格式@机器人QQ号: {bot_qq_number}")
                    return True
                else:
                    logger.debug(f"[图片检测] CQ码@用户不包含机器人QQ号: {matches}，机器人QQ号: {bot_qq_number}")
            else:
                # 如果没有明确的QQ号，默认认为是有效的@消息
                logger.info("[图片检测] 检测到CQ码格式@消息，但无法解析QQ号")
                return True
        
        # 检查[At:格式的@消息
        elif "[At:" in message_text:
            at_pattern = r'\[At:(\d+)\]'
            matches = re.findall(at_pattern, message_text)
            if matches:
                if bot_qq_number in matches:
                    logger.info(f"[图片检测] 检测到[At:格式@机器人QQ号: {bot_qq_number}")
                    return True
                else:
                    logger.debug(f"[图片检测] [At:格式@用户不包含机器人QQ号: {matches}，机器人QQ号: {bot_qq_number}")
            else:
                # 如果没有明确的QQ号，默认认为是有效的@消息
                logger.info("[图片检测] 检测到[At:格式@消息，但无法解析QQ号")
                return True
        
        # 对于普通的@符号，需要更严格的验证
        elif "@" in message_text:
            at_qq_pattern = r'@(\d+)'
            matches = re.findall(at_qq_pattern, message_text)
            if matches:
                if bot_qq_number in matches:
                    logger.info(f"[图片检测] 检测到普通@格式@机器人QQ号: {bot_qq_number}")
                    return True
                else:
                    logger.debug(f"[图片检测] 普通@格式@用户不包含机器人QQ号: {matches}，机器人QQ号: {bot_qq_number}")
            else:
                # 检查@符号后面是否跟着有效的内容（不是空格或标点）
                at_pattern = r'@[^\s\d\.,!?;:\-"\'\[\](){}<>]'  # @后面跟着非空格、非数字、非常见标点的字符
                if re.search(at_pattern, message_text):
                    logger.debug("[图片检测] 检测到有效的@消息格式，但无法确定是否@机器人")
                    # 对于无法确定QQ号的@消息，默认返回False，避免误判
                else:
                    logger.debug(f"[图片检测] 检测到@符号但无有效内容: {message_text[:50]}")
        
        return False

    def _check_at_message_in_event(self, event, bot_qq_number: str) -> bool:
        """检查事件对象中的@信息"""
        try:
            if hasattr(event, 'get_at_users'):
                at_users = event.get_at_users()
                if at_users and len(at_users) > 0:
                    # 检查@用户列表中是否包含机器人QQ号
                    if bot_qq_number in at_users:
                        logger.info(f"[图片检测] 通过get_at_users检测到@机器人QQ号: {bot_qq_number}")
                        return True
                    else:
                        logger.debug(f"[图片检测] @用户列表不包含机器人QQ号: {at_users}，机器人QQ号: {bot_qq_number}")
        except Exception as e:
            logger.debug(f"[图片检测] get_at_users检测失败: {e}")
        
        # 检查消息文本中是否包含@机器人名字
        bot_name = self.config.get("bot_name", "").strip()
        if bot_name:
            # 获取消息文本
            message_text = getattr(event, 'message_str', '')
            if not message_text:
                message_text = self._get_raw_message_text(event)
            
            # 检测@符号后紧挨着机器人名字的情况（支持括号等特殊字符）
            at_name_pattern1 = r'@' + re.escape(bot_name) + r'(?=\s|$|[^\w\u4e00-\u9fa5])'  # @后紧挨着名字，后面是空格、结束符或非字母数字中文
            # 检测@符号后隔一个空格跟着机器人名字的情况
            at_name_pattern2 = r'@\s+' + re.escape(bot_name) + r'(?=\s|$|[^\w\u4e00-\u9fa5])'
            
            if re.search(at_name_pattern1, message_text) or re.search(at_name_pattern2, message_text):
                logger.info(f"[图片检测] 通过事件检测到@机器人名字: {bot_name}")
                return True
        
        return False

    def _detect_images_in_message(self, event, raw_message_text: str, message_text: str) -> bool:
        """检测消息中是否包含图片"""
        has_images = False
        
        # 方法1：使用image_processor提取图片（最可靠）
        if hasattr(self, 'image_processor'):
            try:
                images = self.image_processor._extract_images(event)
                has_images = len(images) > 0
                if has_images:
                    logger.info(f"[图片检测] 通过image_processor检测到 {len(images)} 张图片")
            except Exception as e:
                logger.warning(f"[图片检测] image_processor检测失败: {e}")
        
        # 方法2：如果方法1失败，检查原始消息中的图片标识
        if not has_images:
            for msg in [raw_message_text, message_text]:
                if msg and (
                    "[图片]" in msg or
                    "[CQ:image" in msg or
                    any(ext in msg for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']) or
                    "动画表情" in msg or
                    "image" in msg.lower()
                ):
                    has_images = True
                    logger.info(f"[图片检测] 在消息中检测到图片标识")
                    break
        
        return has_images

    async def _process_at_image_caption(self, event, message_text: str) -> tuple[bool, str]:
        """处理@消息图片转文字"""
        try:
            logger.info(f"[图片检测] 开始调用_detect_and_caption_at_images")
            
            processed_result = await self._detect_and_caption_at_images(event)
            
            logger.info(f"[图片检测] _detect_and_caption_at_images返回结果类型: {type(processed_result)}")
            logger.info(f"[图片检测] _detect_and_caption_at_images返回结果内容: {processed_result}")
            
            if processed_result:
                filtered_message = processed_result.get("filtered_message", message_text)
                logger.info(f"[图片检测] @消息图片转文字完成，过滤后消息: '{filtered_message[:100]}...'")
                return True, filtered_message
            else:
                # 当返回None时，尝试手动识别图片
                logger.warning(f"[图片检测] @消息图片转文字处理返回空结果，尝试手动识别图片")
                
                try:
                    # 提取图片
                    images = self._extract_images(event)
                    logger.info(f"[图片检测] 手动提取到 {len(images)} 张图片")
                    
                    if images:
                        # 调用图片识别
                        caption_result = await self.caption_images(images)
                        logger.info(f"[图片检测] 手动识别结果: {caption_result}")
                        
                        if caption_result:
                            # 将识别结果添加到消息中
                            filtered_message = f"{message_text}\n图片内容：{caption_result}"
                            logger.info(f"[图片检测] 手动识别成功，更新消息为: {filtered_message[:100]}...")
                            return True, filtered_message
                        else:
                            logger.warning(f"[图片检测] 手动识别失败，返回原始消息")
                            return True, message_text
                    else:
                        logger.warning(f"[图片检测] 未能提取到图片，返回原始消息")
                        return True, message_text
                        
                except Exception as e:
                    logger.error(f"[图片检测] 手动识别图片时出错: {e}", exc_info=True)
                    return True, message_text
                
        except Exception as e:
            logger.error(f"[图片检测] @消息图片转文字处理出错: {e}", exc_info=True)
            return True, message_text

    async def _detect_at_images(self, event) -> tuple[bool, str, bool]:
        """
        @消息图片检测函数
        返回: (should_process_message, filtered_message, is_at_image)
        """
        # 获取图片处理配置
        image_config = self.config.get("image_processing", {})
        
        # 获取原始消息和处理后的消息文本
        raw_message_text = self._get_raw_message_text(event)
        message_text = getattr(event, 'message_str', '').strip()
        if not message_text:
            message_text = raw_message_text
        
        logger.info(f"[图片检测] 原始消息: '{raw_message_text[:100] if raw_message_text else '无'}'")
        logger.info(f"[图片检测] 处理后消息: '{message_text[:100] if message_text else '无'}'")
        
        # 检查是否启用@消息图片转文字功能
        enable_at_image_caption = image_config.get("enable_at_image_caption", False)
        
        if not enable_at_image_caption:
            logger.debug("[图片检测] @消息图片转文字功能未启用")
            return True, message_text, False
        
        # 获取配置中的机器人QQ号
        bot_qq_number = self.config.get("bot_qq_number", "").strip()
        if not bot_qq_number:
            logger.warning("[图片检测] 未配置机器人QQ号，@消息检测功能可能无法正常工作")
            return True, message_text, False
        
        # 检查是否为@消息
        is_at_message = False
        
        # 检查原始消息和处理后消息
        for msg in [raw_message_text, message_text]:
            if self._check_at_message_in_text(msg, bot_qq_number):
                is_at_message = True
                break
        
        # 检查事件对象中的@信息
        if not is_at_message:
            is_at_message = self._check_at_message_in_event(event, bot_qq_number)
        
        if not is_at_message:
            logger.debug("[图片检测] 未检测到@消息")
            return True, message_text, False
        
        # 检测是否包含图片
        has_images = self._detect_images_in_message(event, raw_message_text, message_text)
        
        if not has_images:
            logger.info(f"[图片检测] 检测到@消息但未包含图片，跳过图片转文字处理")
            return True, message_text, True
        
        logger.info(f"[图片检测] 检测到@消息且包含图片，开始处理图片转文字")
        
        # 处理@消息图片转文字
        should_process, filtered_message = await self._process_at_image_caption(event, message_text)
        return should_process, filtered_message, True
        
    async def _intercept_other_images(self, event, message_text: str) -> tuple[bool, str]:
        """
        其他消息图片拦截函数
        
        Args:
            event: 消息事件对象
            message_text: 消息文本
            
        Returns:
            (should_process_message, filtered_message)
        """
        # 获取图片处理配置
        image_config = self.config.get("image_processing", {})
        enable_image_processing = image_config.get("enable_image_processing", False)
        image_mode = image_config.get("image_mode", "ignore")
        
        logger.info(f"[图片检测] 配置检查 - enable_image_processing: {enable_image_processing}, image_mode: {image_mode}")
        
        # 如果未开启图片处理，直接返回正常处理
        if not enable_image_processing:
            return True, message_text
        
        # 如果是ignore模式，直接拦截图片消息
        if image_mode == "ignore":
            # 检测消息是否包含图片标识（支持多种格式）
            is_image_message = (
                "[图片]" in message_text or
                "[CQ:image" in message_text or
                any(ext in message_text for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']) or
                "动画表情" in message_text or
                "image" in message_text.lower()
            )
            
            if is_image_message:
                logger.info(f"[图片检测] ignore模式检测到图片消息，拦截处理")
                # 设置标记，让after_bot_message_sent知道这是图片消息拦截
                event._is_image_message = True
                return False, message_text  # 拦截消息
            else:
                return True, message_text  # 非图片消息正常处理
        
        # 检测消息是否包含图片标识（支持多种格式）
        is_image_message = (
            "[图片]" in message_text or
            "[CQ:image" in message_text or
            any(ext in message_text for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']) or
            "动画表情" in message_text or
            "image" in message_text.lower()
        )
        
        if not is_image_message:
            return True, message_text
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 检测到[图片]标识")
        
        # 检测纯图片消息（支持多种图片格式）
        stripped_message = message_text.strip()
        is_pure_image = False
        
        # 如果是CQ码图片消息，直接判定为纯图片
        if "[CQ:image" in stripped_message:
            is_pure_image = True
            logger.info(f"[图片检测] 检测到CQ码图片消息，判定为纯图片")
        # 如果是标准[图片]标识
        elif stripped_message == "[图片]" or (stripped_message.startswith("[图片]") and len(stripped_message.replace("[图片]", "").strip()) == 0):
            is_pure_image = True
        # 如果是包含常见图片格式的文件名
        elif any(ext in stripped_message for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']):
            # 检查是否只包含图片相关标识
            temp_text = stripped_message.lower()
            # 移除图片格式后检查是否还有有效内容
            for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                temp_text = temp_text.replace(ext, '')
            # 如果移除图片格式后只剩下空白或常见图片标识，判定为纯图片
            temp_text = temp_text.strip()
            if len(temp_text) == 0 or all(keyword in temp_text for keyword in ['cq:', 'image', 'file', 'url']):
                is_pure_image = True
                logger.info(f"[图片检测] 检测到图片文件消息，判定为纯图片")
        # 如果是动画表情
        elif "动画表情" in stripped_message:
            is_pure_image = True
            logger.info(f"[图片检测] 检测到动画表情，判定为纯图片")
        
        if is_pure_image:
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 消息仅包含[图片]标识，忽略消息")
            
            logger.info(f"[图片检测] 检测到纯图片消息: '{message_text}'，拦截但不清理沉浸式会话")
            
            # 检查是否存在沉浸式会话
            session_key = (event.get_group_id(), event.get_sender_id())
            async with self.immersive_lock:
                if session_key in self.immersive_sessions:
                    logger.info(f"[图片检测] 沉浸式会话存在: {session_key}，保持会话继续运行")
                    # 重置定时器，让沉浸式对话继续有效
                    session_data = self.immersive_sessions[session_key]
                    if session_data.get('timer'):
                        session_data['timer'].cancel()
                        logger.info(f"[图片检测] 已取消当前定时器: {session_key}")
                    
                    # 使用配置中的沉浸式对话超时秒数
                    timeout_seconds = self.config.get("immersive_chat_timeout", 120)
                    
                    # 重新启动定时器，保持沉浸式对话有效
                    session_data['timer'] = asyncio.get_running_loop().call_later(
                        timeout_seconds, 
                        self._clear_immersive_session, 
                        session_key
                    )
                    logger.info(f"[图片检测] 已重新启动{timeout_seconds}秒定时器: {session_key}")
                else:
                    logger.info(f"[图片检测] 未找到沉浸式会话: {session_key}")
            
            # 如果image_mode为direct，直接传递图片给AI
            if image_mode == "direct":
                logger.info(f"[图片检测] 直接传递图片模式，开始处理图片")
                
                # 提取图片
                images = self._extract_images(event)
                logger.info(f"[图片检测] 提取到 {len(images)} 张图片")
                
                if images:
                    # 在direct模式下，将图片信息传递给后续处理
                    # 设置图片信息到event对象中，让后续流程能够使用
                    event._images = images
                    event._is_image_message = True
                    
                    # 返回True让消息继续处理，图片信息会通过event传递给LLM
                    logger.info(f"[图片检测] 直接传递图片模式处理完成，图片数量: {len(images)}")
                    return True, message_text
                else:
                    logger.warning(f"[图片检测] 直接传递图片模式但未提取到图片")
            
            # 如果image_mode为caption，调用图片转文字功能
            elif image_mode == "caption":
                logger.info(f"[图片检测] 图片转文字模式，开始处理图片转文字")
                
                # 提取图片
                images = self._extract_images(event)
                logger.info(f"[图片检测] 提取到 {len(images)} 张图片")
                
                if images:
                    # 调用图片转文字功能
                    caption_result = await self.caption_images(images)
                    if caption_result:
                        logger.info(f"[图片检测] 图片转文字成功，结果: {caption_result}")
                        # 设置event.message_str为图片描述，让后续处理使用
                        event.message_str = caption_result
                        # 设置标记，让after_bot_message_sent知道这是图片消息拦截
                        event._is_image_message = True
                        
                        # 返回True表示需要处理消息，但消息内容已替换为图片描述
                        return True, caption_result
                    else:
                        logger.warning(f"[图片检测] 图片转文字失败")
            
            logger.info(f"[图片检测] 纯图片消息已拦截，沉浸式会话保持运行")
            # 设置标记，让after_bot_message_sent知道这是图片消息拦截
            event._is_image_message = True
            
            return False, message_text  # 不处理消息
        else:
            # 如果消息包含[图片]标识和其他文字，过滤标识后继续处理
            filtered_message = message_text.replace("[图片]", "").strip()
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 消息包含[图片]标识和其他文字，过滤后消息: '{filtered_message}'")
            
            logger.info(f"[图片检测] 检测到包含[图片]标识的消息，已移除标识，过滤后消息: '{filtered_message[:50]}...'")
            
            return True, filtered_message

    async def _handle_immersive_session(self, event: AstrMessageEvent, session_key: tuple, session_data: dict) -> bool:
        """
        处理沉浸式会话逻辑
        
        Args:
            event: 消息事件对象（event.message_str已经是图片转文字后的内容）
            session_key: 会话键 (group_id, user_id)
            session_data: 会话数据
            
        Returns:
            bool: 是否已处理沉浸式会话（True表示已处理，False表示未处理）
        """
        logger.info(f"[沉浸式对话] 捕获到用户 {event.get_sender_id()} 的连续消息，开始判断是否回复。")
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 沉浸式对话会话存在，会话键: {session_key}")
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 会话数据: 上下文长度={len(session_data.get('context', []))}")
        
        # 因为要进行沉浸式回复，所以取消可能存在的、针对全群的主动插话任务
        group_id = event.get_group_id()
        async with self.proactive_lock:
            if group_id in self.active_proactive_timers:
                self.active_proactive_timers[group_id].cancel()
                logger.debug(f"[沉浸式对话] 已取消群 {group_id} 的主动插话任务。")
                
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 已取消群 {group_id} 的主动插话任务")
    
        # 阻止事件继续传播，避免触发默认的LLM回复
        event.stop_event()
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 已阻止事件传播，开始沉浸式对话处理")
    
        found_persona = await self._get_persona_info_str(event.unified_msg_origin)
        
        # ✅ 关键修改：先保存用户消息到平台历史记录
        try:
            await self._save_user_message_to_conversation(event, event.message_str)
        except Exception as e:
            logger.warning(f"[沉浸式对话] 保存用户消息到平台历史失败: {e}")
        
        # ✅ 关键修改：每次处理沉浸式会话时都重新获取完整上下文
        # 这样可以确保包含最新的图片信息和对话历史
        saved_context = await self._get_complete_conversation_history(event)
        
        # ✅ 关键修改：支持direct模式下的图片传递
        user_prompt = event.message_str
        
        # 检查是否是direct模式的图片消息
        if hasattr(event, '_images') and event._images:
            logger.info(f"[沉浸式对话] 检测到direct模式图片消息，图片数量: {len(event._images)}")
            # 在direct模式下，我们需要将图片信息传递给LLM
            # 这里可以添加图片URL或路径到提示中，或者使用支持多模态的API
            user_prompt = f"[图片消息] 用户发送了 {len(event._images)} 张图片"
            # 在实际实现中，这里应该调用支持多模态的LLM API
        
        # 添加日志确认使用的消息内容
        logger.info(f"[沉浸式对话] 使用的用户提示内容（前100字符）: {user_prompt[:100]}...")
        
        instruction = IMMERSIVE_SESSION_INSTRUCTION
    
        provider = self.context.get_using_provider()
        if not provider:
            logger.warning("[沉浸式对话] 未找到可用的大语言模型提供商。")
            return True
    
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 开始调用LLM进行沉浸式对话决策")
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 用户提示长度: {len(user_prompt)}")
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 上下文数量: {len(saved_context)}")
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 系统提示长度: {len(instruction)}")
    
        # 检查是否是direct模式的图片消息，需要特殊处理
        if hasattr(event, '_images') and event._images:
            # 在实际的多模态实现中，这里应该调用支持图片的API
            # 目前先使用文本模式处理
            logger.info(f"[沉浸式对话] direct模式图片消息，使用文本模式处理")
        
        # 获取工具调用能力
        func_tool = None
        try:
            # 使用AstrBot v4.0.0的工具管理器获取工具
            tool_manager = self.context.get_llm_tool_manager()
            if tool_manager:
                # 获取当前会话的可用工具集 - 使用正确的get_full_tool_set方法
                tool_set = tool_manager.get_full_tool_set()
                if tool_set and hasattr(tool_set, 'tools') and tool_set.tools:
                    func_tool = tool_set
                    logger.info(f"[沉浸式对话] 获取到工具调用能力，工具数量: {len(tool_set.tools)}")
                    
                    # 关键改进：检查当前平台配置的搜索提供商，确保插件使用平台配置的搜索方法
                    try:
                        cfg = self.context.get_config()
                        prov_settings = cfg.get("provider_settings", {})
                        websearch_enable = prov_settings.get("web_search", False)
                        websearch_provider = prov_settings.get("websearch_provider", "default")
                        
                        logger.info(f"[搜索适配] 平台搜索配置: 启用={websearch_enable}, 提供商={websearch_provider}")
                        
                        # 如果平台启用了搜索功能，记录可用的搜索工具
                        if websearch_enable:
                            available_search_tools = []
                            for tool in tool_set.tools:
                                if tool.name in ["web_search", "web_search_tavily", "AIsearch"]:
                                    available_search_tools.append(tool.name)
                            
                            if available_search_tools:
                                logger.info(f"[搜索适配] 可用搜索工具: {', '.join(available_search_tools)}")
                            else:
                                logger.info("[搜索适配] 未找到搜索工具，将使用平台默认配置")
                        
                    except Exception as config_error:
                        logger.warning(f"[搜索适配] 获取平台搜索配置失败: {config_error}")
                else:
                    logger.info("[沉浸式对话] 当前会话没有可用的工具")
        except Exception as e:
            logger.warning(f"[沉浸式对话] 获取工具调用能力失败: {e}")
        
        # 关键修复：在沉浸式对话中，我们需要使用AstrBot v4.0.0的Agent系统来处理LLM请求
        # 这样工具调用能力才能正确传递给LLM并自动处理工具调用循环
        
        # 导入必要的类
        from astrbot.core.provider.entities import ProviderRequest
        from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
        from astrbot.core.agent.run_context import ContextWrapper
        from astrbot.core.agent.hooks import BaseAgentRunHooks
        from astrbot.core.agent.tool_executor import BaseFunctionToolExecutor
        from astrbot.core.astr_agent_context import AstrAgentContext
        
        # 每次AI回复前重新获取上下文，确保包含最新的对话历史
        try:
            # 重新获取完整的对话历史，应用配置中的上下文限制
            refreshed_context = await self._get_complete_conversation_history(event)
            
            # 合并重新获取的上下文和当前保存的上下文（通过内容去重避免重复）
            if refreshed_context and isinstance(refreshed_context, list):
                # 创建内容集合用于去重
                existing_contents = set()
                if saved_context and isinstance(saved_context, list):
                    for msg in saved_context:
                        if isinstance(msg, dict) and 'content' in msg:
                            existing_contents.add(msg['content'])
                
                # 添加不重复的消息
                for msg in refreshed_context:
                    if isinstance(msg, dict) and 'content' in msg:
                        if msg['content'] not in existing_contents:
                            saved_context.append(msg)
                            existing_contents.add(msg['content'])
                
                logger.info(f"[沉浸式对话] 重新获取上下文后，总消息数: {len(saved_context)}条")
            else:
                logger.info("[沉浸式对话] 重新获取上下文为空，使用原始上下文")
        except Exception as e:
            logger.warning(f"[沉浸式对话] 重新获取上下文失败: {e}")
        # 应用上下文数量限制
        max_context_messages = self.config.get('max_context_messages', -1)
        if max_context_messages != -1:  # -1表示不限制
            if max_context_messages == 0:  # 0表示不使用上下文
                logger.info(f"[上下文限制] 配置为0，不使用上下文，清空历史记录")
                saved_context = []
            elif max_context_messages > 0 and len(saved_context) > max_context_messages:
                # 保留最近的消息，去掉最前面的消息
                original_length = len(saved_context)
                saved_context = saved_context[-max_context_messages:]
                logger.info(f"[上下文限制] 上下文数量({original_length})超过限制({max_context_messages})，保留最近{len(saved_context)}条消息")
        
        logger.info(f"[沉浸式对话] 应用上下文限制后，总长度: {len(saved_context)}")
        # 创建ProviderRequest - 确保上下文格式正确
        # 标准AstrBot使用json.loads(conversation.history)格式的上下文
        if isinstance(saved_context, str):
            try:
                saved_context = json.loads(saved_context)
            except json.JSONDecodeError:
                logger.warning("[沉浸式对话] 上下文格式异常，使用空列表")
                saved_context = []
        elif not isinstance(saved_context, list):
            saved_context = []
            
        req = ProviderRequest(
            prompt=user_prompt,
            contexts=saved_context,
            system_prompt=instruction,
            func_tool=func_tool
        )
        
        # 初始化AgentRunner
        AgentRunner = ToolLoopAgentRunner[AstrAgentContext]
        agent_runner = AgentRunner()
        
        # 创建Agent上下文
        astr_agent_ctx = AstrAgentContext(
            provider=provider,
            first_provider_request=req,
            curr_provider_request=req,
            streaming=False,  # 非流式响应
            tool_call_timeout=60  # 工具调用超时时间
        )
        
        # 创建自定义的ToolExecutor
        class ImmersiveToolExecutor(BaseFunctionToolExecutor[AstrAgentContext]):
            @classmethod
            def execute(cls, tool, run_context, **tool_args):
                # 这里可以添加自定义的工具执行逻辑
                # 对于沉浸式对话，我们使用AstrBot中实际的FunctionToolExecutor
                from astrbot.core.pipeline.process_stage.method.llm_request import FunctionToolExecutor
                # 正确返回异步生成器方法本身，而不是调用结果
                return FunctionToolExecutor.execute(tool, run_context, **tool_args)
        
        # 创建自定义的AgentHooks
        class ImmersiveAgentHooks(BaseAgentRunHooks[AstrAgentContext]):
            async def on_agent_done(self, run_context, llm_response):
                # 在Agent完成时记录日志
                logger.info(f"[沉浸式对话] Agent处理完成，响应长度: {len(llm_response.completion_text)}")
        
        # 重置并配置AgentRunner
        await agent_runner.reset(
            provider=provider,
            request=req,
            run_context=ContextWrapper(context=astr_agent_ctx, event=event),
            tool_executor=ImmersiveToolExecutor(),
            agent_hooks=ImmersiveAgentHooks(),
            streaming=False
        )
        
        # 执行Agent步骤，处理工具调用循环
        max_steps = 30  # 最大步骤数
        step_count = 0
        
        while step_count < max_steps and not agent_runner.done():
            step_count += 1
            async for _ in agent_runner.step():
                # 处理Agent步骤中的各种响应
                pass
            
            # 检查是否完成
            if agent_runner.done():
                break

        # 获取最终的LLM响应
        llm_response = agent_runner.get_final_llm_resp()
        
        # 如果AgentRunner没有返回响应，使用后备方案
        if not llm_response:
            logger.warning("[沉浸式对话] AgentRunner未返回响应，使用后备方案")
            llm_response = await provider.text_chat(
                prompt=user_prompt,
                contexts=saved_context,
                system_prompt=instruction,
                func_tool=func_tool
            )
        
        # 关键修复：保存对话历史到平台，确保上下文连续性
        # 模仿标准AstrBot的_save_to_history方法逻辑
        if llm_response and llm_response.role == "assistant":
            try:
                # 获取Agent执行后的完整上下文（包括Agent可能添加的工具调用结果）
                # 通过run_context获取Agent修改后的上下文
                if hasattr(agent_runner, 'run_context') and agent_runner.run_context:
                    run_context = agent_runner.run_context
                    if hasattr(run_context, 'context') and hasattr(run_context.context, 'curr_provider_request'):
                        # 使用Agent修改后的上下文
                        agent_request = run_context.context.curr_provider_request
                        if agent_request and agent_request.contexts:
                            messages = agent_request.contexts.copy()
                            logger.info(f"[沉浸式对话] 使用Agent修改后的上下文，长度: {len(messages)}")
                        else:
                            # 使用原始上下文
                            messages = saved_context.copy() if saved_context else []
                            logger.info(f"[沉浸式对话] 使用原始上下文，长度: {len(messages)}")
                    else:
                        # 使用原始上下文
                        messages = saved_context.copy() if saved_context else []
                        logger.info(f"[沉浸式对话] 使用原始上下文，长度: {len(messages)}")
                else:
                    # 使用原始上下文
                    messages = saved_context.copy() if saved_context else []
                    logger.info(f"[沉浸式对话] 使用原始上下文，长度: {len(messages)}")
                
                # 确保包含当前轮次的完整对话
                # 检查是否已经包含了当前用户输入和LLM响应
                has_current_user_input = any(msg.get('content') == user_prompt for msg in messages if isinstance(msg, dict))
                has_current_llm_response = any(msg.get('content') == llm_response.completion_text for msg in messages if isinstance(msg, dict))
                
                if not has_current_user_input:
                    messages.append({"role": "user", "content": user_prompt})
                if not has_current_llm_response:
                    messages.append({"role": "assistant", "content": llm_response.completion_text})
                
                # 保存到平台对话历史
                await self._save_conversation_history(event.unified_msg_origin, messages)
                logger.info(f"[沉浸式对话] 对话历史已保存，总消息数: {len(messages)}条")
            except Exception as e:
                logger.warning(f"[沉浸式对话] 保存对话历史失败: {e}")
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - LLM调用完成，响应长度: {len(llm_response.completion_text)}")
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 工具调用信息: names={llm_response.tools_call_name}, args={llm_response.tools_call_args}")
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - LLM响应文本预览: {llm_response.completion_text[:200]}")
        
        # 在AstrBot v4.0.0中，工具调用由ToolLoopAgentRunner自动处理
        # 如果响应包含工具调用信息，说明AstrBot已经处理了工具调用循环
        # 我们只需要检查最终的响应内容
        if llm_response.tools_call_name and len(llm_response.tools_call_name) > 0:
            logger.info(f"[沉浸式对话] 检测到工具调用，但AstrBot已自动处理工具调用循环")
            # 工具调用已由AstrBot自动处理，我们继续处理最终的响应内容
        
        # 优化版本：直接处理LLM响应，不再使用JSON格式
        response_text = llm_response.completion_text.strip()
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - LLM响应处理开始，响应长度: {len(response_text)}")
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 响应内容预览: {response_text[:200]}")
        
        # 检查是否是不回复标记
        if "[DO_NOT_REPLY]" in response_text:
            logger.info("[沉浸式对话] LLM判断不需要回复，结束沉浸式对话状态")
            # 清理会话
            if session_key in self.immersive_sessions:
                del self.immersive_sessions[session_key]
            return True
        
        # 直接使用LLM的回复内容
        if response_text:
            logger.info(f"[沉浸式对话] LLM决定回复，内容: {response_text[:50]}...")
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 沉浸式对话决定回复，内容预览: {response_text[:100]}")
            
            # 发送回复
            message_chain = MessageChain().message(response_text)
            await self.context.send_message(event.session, message_chain)
            
            # 保存回复到平台历史记录
            try:
                await self._save_bot_reply_to_conversation(event, response_text)
                await asyncio.sleep(0.1)  # 等待保存完成
                # 回复后重新启动沉浸式会话
                await self._arm_immersive_session(event)
            except Exception as e:
                logger.warning(f"[沉浸式对话] 保存回复到平台历史失败: {e}")
                # 即使保存失败，也重新启动沉浸式会话
                await self._arm_immersive_session(event)
                
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 沉浸式回复已发送，会话已重新启动")
            else:
                logger.info("[沉浸式对话] LLM响应为空")

        # 关键修复：只有当沉浸式对话真正处理了用户消息（发送了回复）时才返回True
        # 其他情况（如工具调用后AI准备回复）都应该返回False，让事件继续传播
        return True


    async def _start_proactive_check(self, group_id: str, unified_msg_origin: str, should_process_message: bool = True):
        """启动或重置一个群组的主动插话检查任务。"""
        # 存储图片拦截状态
        self.image_interception_states[group_id] = should_process_message
        
        async with self.proactive_lock:
            if group_id in self.active_proactive_timers:
                self.active_proactive_timers[group_id].cancel()
                logger.debug(f"[主动插话] 取消了群 {group_id} 的旧计时器。")

            self.group_chat_buffer[group_id].clear()
            task = asyncio.create_task(
                self._proactive_check_task(group_id, unified_msg_origin)
            )
            self.active_proactive_timers[group_id] = task
        logger.debug(f"[主动插话] 已为群 {group_id} 启动/重置了延时检查任务。")

    async def _get_persona_info_str(self, unified_msg_origin: str) -> str:
        """获取当前会话的人格信息并格式化为字符串。"""
        try:
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(unified_msg_origin)
            if not curr_cid:
                return ""
            conversation = await self.context.conversation_manager.get_conversation(unified_msg_origin, curr_cid)
            if not conversation:
                return ""

            persona_id = conversation.persona_id
            if persona_id == "[%None]":
                return ""
            if not persona_id:
                persona_id = self.context.provider_manager.selected_default_persona.get("name")
            
            if not persona_id:
                return ""

            all_personas = self.context.provider_manager.personas
            found_persona = next((p for p in all_personas if p.get('name') == persona_id), None)

            if found_persona:
                persona_details = (
                    f"--- 当前人格信息 ---\n"
                    f"名称: {found_persona.get('name', '未知')}\n"
                    f"设定: {found_persona.get('prompt', '无')}\n"
                    f"--- 人格信息结束 ---"
                )
                return persona_details
            
            return ""
        except Exception as e:
            logger.error(f"[人格获取] 获取人格信息时出错: {e}", exc_info=True)
            return ""

    async def _get_conversation_history(self, unified_msg_origin: str) -> list:
        """获取指定会话的完整对话历史记录。"""
        try:
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(unified_msg_origin)
            if not curr_cid:
                return []
            conversation = await self.context.conversation_manager.get_conversation(unified_msg_origin, curr_cid)
            if conversation and conversation.history:
                try:
                    history_data = json.loads(conversation.history)
                    # 确保返回的是列表
                    if isinstance(history_data, list):
                        return history_data
                    else:
                        logger.warning(f"[历史记录获取] 历史数据格式错误，期望list，实际{type(history_data)}")
                        return []
                except json.JSONDecodeError as e:
                    logger.warning(f"[历史记录获取] JSON解析失败: {e}")
                    return []
            return []
        except Exception as e:
            logger.error(f"[历史记录获取] 获取对话历史时出错: {e}", exc_info=True)
            return []

    async def _get_complete_conversation_history(self, event: AstrMessageEvent) -> list:
        """获取完整的对话历史记录，包括平台保存的历史和插件上下文"""
        try:
            # 1. 获取平台保存的对话历史
            platform_history = await self._get_conversation_history(event.unified_msg_origin)
            
            # 2. 获取插件上下文分析器提供的上下文
            plugin_context = []
            if self.context_analyzer:
                try:
                    chat_context = await self.context_analyzer.analyze_chat_context(event)
                    plugin_context = chat_context.get('conversation_history', [])
                    # 确保是列表格式
                    if not isinstance(plugin_context, list):
                        logger.warning(f"[沉浸式对话] 插件上下文格式错误，期望list，实际{type(plugin_context)}")
                        plugin_context = []
                except Exception as e:
                    logger.warning(f"[沉浸式对话] 获取插件上下文失败: {e}")
            
            # 3. 合并上下文，优先使用平台历史，插件上下文作为补充
            complete_context = platform_history.copy()
            
            # 如果平台历史为空或很少，使用插件上下文
            if len(complete_context) < 5 and plugin_context:
                logger.info(f"[沉浸式对话] 平台历史较少({len(complete_context)}条)，使用插件上下文({len(plugin_context)}条)")
                complete_context = plugin_context
            elif plugin_context:
                # 合并上下文，避免重复但保留重要上下文信息
                logger.info(f"[沉浸式对话] 合并平台历史({len(complete_context)}条)和插件上下文({len(plugin_context)}条)")
                
                # 改进的去重逻辑：基于时间戳和内容进行智能合并
                platform_messages = {}
                for msg in complete_context:
                    if isinstance(msg, dict):
                        content = msg.get('content', '')
                        timestamp = msg.get('timestamp', 0)
                        # 使用内容和时间戳作为唯一标识
                        key = f"{content}_{timestamp}"
                        platform_messages[key] = msg
                
                # 添加插件上下文中的新消息
                for msg in plugin_context:
                    if isinstance(msg, dict):
                        content = msg.get('content', '')
                        timestamp = msg.get('timestamp', 0)
                        key = f"{content}_{timestamp}"
                        
                        # 如果平台历史中没有该消息，则添加
                        if key not in platform_messages:
                            complete_context.append(msg)
                            logger.debug(f"[沉浸式对话] 添加插件上下文消息: {content[:50]}...")
                
                # 按时间戳排序，确保对话顺序正确
                complete_context.sort(key=lambda x: x.get('timestamp', 0) if isinstance(x, dict) else 0)
            
            # 4. 应用上下文数量限制
            max_context_messages = self.config.get('max_context_messages', -1)
            if max_context_messages != -1:  # -1表示不限制
                if max_context_messages == 0:  # 0表示不使用上下文
                    logger.info(f"[上下文限制] 配置为0，不使用上下文，清空历史记录")
                    complete_context = []
                elif max_context_messages > 0 and len(complete_context) > max_context_messages:
                    # 保留最近的消息，去掉最前面的消息
                    original_length = len(complete_context)
                    complete_context = complete_context[-max_context_messages:]
                    logger.info(f"[上下文限制] 上下文数量({original_length})超过限制({max_context_messages})，保留最近{len(complete_context)}条消息")
            
            logger.info(f"[沉浸式对话] 完整上下文获取完成，总长度: {len(complete_context)}")
            return complete_context
            
        except Exception as e:
            logger.error(f"[沉浸式对话] 获取完整对话历史时出错: {e}", exc_info=True)
            logger.info(f"[沉浸式对话] 异常情况下返回空上下文，总长度: 0")
            return []

    async def _save_bot_reply_to_conversation(self, event: AstrMessageEvent, reply_content: str):
        """将机器人的回复保存到平台的对话历史记录中，支持图片附件信息"""
        try:
            uid = event.unified_msg_origin
            if self._is_detailed_logging():
                logger.debug(f"[历史保存][bot] 开始保存机器人回复，UMO={uid}, 内容长度={len(reply_content) if reply_content else 0}")
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(uid)
            if self._is_detailed_logging():
                logger.debug(f"[历史保存][bot] 当前对话ID: {curr_cid}")
            
            if not curr_cid:
                # 如果没有当前对话ID，创建一个新的对话
                curr_cid = await self.context.conversation_manager.create_conversation(uid)
                logger.info(f"[历史保存][bot] 创建新对话ID: {curr_cid}")
            
            if curr_cid:
                # 获取当前对话
                conversation = await self.context.conversation_manager.get_conversation(uid, curr_cid)
                if conversation:
                    if self._is_detailed_logging():
                        logger.debug(f"[历史保存][bot] 获取对话成功，对话ID={curr_cid}, 对话类型={type(conversation).__name__}")
                    # 获取现有历史记录
                    existing_history = []
                    if conversation.history:
                        try:
                            existing_history = json.loads(conversation.history)
                        except (json.JSONDecodeError, TypeError):
                            existing_history = []
                    
                    # 构建新的回复记录
                    new_message = {
                        "role": "assistant",
                        "content": reply_content,
                        "timestamp": time.time()
                    }
                    
                    # 检查并添加图片附件信息（如果AI回复包含图片）
                    attachments = await self._get_bot_reply_attachments(reply_content)
                    if attachments:
                        new_message["attachments"] = attachments
                        logger.info(f"[历史保存][bot] AI回复包含 {len(attachments)} 个附件")
                    
                    existing_history.append(new_message)

                    if self._is_detailed_logging():
                        logger.debug(f"[历史保存][bot] 追加后历史长度={len(existing_history)}，准备持久化")

                    # 保存更新后的历史记录（带多重回退与详细日志）
                    await self._persist_conversation_history(uid, curr_cid, existing_history)
                    logger.debug(f"[历史保存][bot] 回复已持久化到平台历史，对话ID={curr_cid}")
                else:
                    logger.warning(f"[历史保存][bot] 无法获取对话对象，对话ID={curr_cid}")
            else:
                logger.warning(f"[历史保存][bot] 无法创建或获取对话ID")
                
        except Exception as e:
            logger.error(f"[历史保存][bot] 保存回复到平台历史记录时出错: {e}", exc_info=True)

    def _calculate_attachment_stats(self, history_list: list) -> Dict:
        """计算历史记录中的附件统计信息"""
        stats = {
            "total_attachments": 0,
            "image_attachments": 0,
            "messages_with_attachments": 0,
            "attachment_types": {}
        }
        
        try:
            for message in history_list:
                if isinstance(message, dict) and "attachments" in message:
                    attachments = message.get("attachments", [])
                    if attachments:
                        stats["messages_with_attachments"] += 1
                        stats["total_attachments"] += len(attachments)
                        
                        for attachment in attachments:
                            attachment_type = attachment.get("type", "unknown")
                            if attachment_type == "image":
                                stats["image_attachments"] += 1
                            
                            # 统计各类型数量
                            if attachment_type not in stats["attachment_types"]:
                                stats["attachment_types"][attachment_type] = 0
                            stats["attachment_types"][attachment_type] += 1
            
            if self._is_detailed_logging() and stats["total_attachments"] > 0:
                logger.debug(f"[附件统计] 历史记录包含 {stats['total_attachments']} 个附件，其中 {stats['image_attachments']} 个图片")
                
        except Exception as e:
            logger.warning(f"[附件统计] 计算附件统计信息时出错: {e}")
        
        return stats

    async def _get_bot_reply_attachments(self, reply_content: str) -> List[Dict]:
        """获取AI回复中的附件信息（主要是图片）"""
        attachments = []
        try:
            # 从回复内容中提取图片CQ码
            if reply_content:
                image_urls = self._extract_images(reply_content)
                for url in image_urls:
                    attachment = {
                        "type": "image",
                        "url": url,
                        "timestamp": time.time()
                    }
                    attachments.append(attachment)
                        
            if attachments and self._is_detailed_logging():
                logger.debug(f"[附件处理] AI回复中提取到 {len(attachments)} 个附件")
                
        except Exception as e:
            logger.error(f"[附件处理] 获取AI回复附件信息时出错: {e}", exc_info=True)
            
        return attachments

    async def _get_message_attachments(self, event: AstrMessageEvent) -> List[Dict]:
        """获取消息中的附件信息（主要是图片）"""
        attachments = []
        try:
            # 检查事件中是否有图片信息
            if hasattr(event, '_images') and event._images:
                for image_info in event._images:
                    attachment = {
                        "type": "image",
                        "url": image_info.get('url', ''),
                        "file": image_info.get('file', ''),
                        "timestamp": time.time()
                    }
                    attachments.append(attachment)
                    
            # 从消息文本中提取图片CQ码
            if event.message_str:
                image_urls = self._extract_images(event.message_str)
                for url in image_urls:
                    if url not in [att.get('url', '') for att in attachments]:
                        attachment = {
                            "type": "image",
                            "url": url,
                            "timestamp": time.time()
                        }
                        attachments.append(attachment)
                        
            if attachments and self._is_detailed_logging():
                logger.debug(f"[附件处理] 提取到 {len(attachments)} 个附件")
                
        except Exception as e:
            logger.error(f"[附件处理] 获取消息附件信息时出错: {e}", exc_info=True)
            
        return attachments

    async def _save_user_message_to_conversation(self, event: AstrMessageEvent, message_content: str):
        """将用户的消息保存到平台的对话历史记录中，支持图片附件信息"""
        try:
            uid = event.unified_msg_origin
            if self._is_detailed_logging():
                logger.debug(f"[历史保存][user] 开始保存用户消息，UMO={uid}, 内容长度={len(message_content) if message_content else 0}")
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(uid)
            if self._is_detailed_logging():
                logger.debug(f"[历史保存][user] 当前对话ID: {curr_cid}")
            
            if not curr_cid:
                # 如果没有当前对话ID，创建一个新的对话
                curr_cid = await self.context.conversation_manager.create_conversation(uid)
                logger.info(f"[历史保存][user] 创建新对话ID: {curr_cid}")
            
            if curr_cid:
                # 获取当前对话
                conversation = await self.context.conversation_manager.get_conversation(uid, curr_cid)
                if conversation:
                    if self._is_detailed_logging():
                        logger.debug(f"[历史保存][user] 获取对话成功，对话ID={curr_cid}, 对话类型={type(conversation).__name__}")
                    # 获取现有历史记录
                    existing_history = []
                    if conversation.history:
                        try:
                            existing_history = json.loads(conversation.history)
                        except (json.JSONDecodeError, TypeError):
                            existing_history = []
                    
                    # 构建新的用户消息记录
                    new_message = {
                        "role": "user",
                        "content": message_content,
                        "timestamp": time.time(),
                        "sender_id": event.get_sender_id(),
                        "sender_name": event.get_sender_name()
                    }
                    
                    # 检查并添加图片附件信息
                    attachments = await self._get_message_attachments(event)
                    if attachments:
                        new_message["attachments"] = attachments
                        logger.info(f"[历史保存][user] 消息包含 {len(attachments)} 个附件")
                    
                    existing_history.append(new_message)

                    if self._is_detailed_logging():
                        logger.debug(f"[历史保存][user] 追加后历史长度={len(existing_history)}，准备持久化")

                    # 保存更新后的历史记录（带多重回退与详细日志）
                    await self._persist_conversation_history(uid, curr_cid, existing_history)
                    logger.debug(f"[历史保存][user] 用户消息已持久化到平台历史，对话ID={curr_cid}")
                else:
                    logger.warning(f"[历史保存][user] 无法获取对话对象，对话ID={curr_cid}")
            else:
                logger.warning(f"[历史保存][user] 无法创建或获取对话ID")
                
        except Exception as e:
            logger.error(f"[历史保存][user] 保存用户消息到平台历史记录时出错: {e}", exc_info=True)

    # 在AstrBot v4.0.0中，工具调用由ToolLoopAgentRunner自动处理
    # 不再需要手动处理工具调用，因此删除_handle_tool_calls方法

    async def _fallback_save_to_filesystem(self, unified_msg_origin: str, conversation_id: str, history_list: list):
        """临时文件保存方法，当官方方法失败时使用。"""
        try:
            import os
            import json
            
            # 创建保存目录
            save_dir = os.path.join(os.path.dirname(__file__), "conversation_backups")
            os.makedirs(save_dir, exist_ok=True)
            
            # 生成文件名
            safe_umo = unified_msg_origin.replace(":", "_").replace("/", "_")
            filename = f"{safe_umo}_{conversation_id}.json"
            filepath = os.path.join(save_dir, filename)
            
            # 检查文件大小，避免保存过大的历史记录
            history_size = len(json.dumps(history_list, ensure_ascii=False))
            max_size = 10 * 1024 * 1024  # 10MB限制
            
            if history_size > max_size:
                logger.warning(f"[临时文件] 历史记录过大({history_size}字节)，进行截断")
                # 保留最近的50条消息
                history_list = history_list[-50:]
                history_size = len(json.dumps(history_list, ensure_ascii=False))
                logger.info(f"[临时文件] 截断后大小: {history_size}字节")
            
            # 计算图片附件统计信息
            attachment_stats = self._calculate_attachment_stats(history_list)
            
            # 保存到文件
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({
                    "unified_msg_origin": unified_msg_origin,
                    "conversation_id": conversation_id,
                    "history": history_list,
                    "timestamp": time.time(),
                    "saved_by": "temporary_filesystem",
                    "history_size": history_size,
                    "message_count": len(history_list),
                    "attachment_stats": attachment_stats,
                    "format_version": "1.1"  # 新增格式版本标识
                }, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[临时文件] 对话历史已保存到临时文件: {filepath} (大小: {history_size}字节, 消息数: {len(history_list)})")
            
            # 清理旧文件（保留最近100个文件）
            await self._cleanup_old_backup_files(save_dir)
            
            return True
            
        except Exception as e:
            logger.error(f"[临时文件] 文件系统保存失败: {e}")
            return False

    async def _cleanup_old_backup_files(self, backup_dir: str):
        """清理旧的临时文件，保留最近100个文件。"""
        try:
            import os
            import glob
            
            # 获取所有备份文件
            backup_files = glob.glob(os.path.join(backup_dir, "*.json"))
            
            if len(backup_files) > 100:
                # 按修改时间排序，删除最旧的文件
                backup_files.sort(key=os.path.getmtime)
                files_to_delete = backup_files[:-100]  # 保留最新的100个
                
                for file_path in files_to_delete:
                    try:
                        os.remove(file_path)
                        logger.debug(f"[临时文件][清理] 删除旧临时文件: {file_path}")
                    except Exception as e:
                        logger.warning(f"[临时文件][清理] 删除文件失败 {file_path}: {e}")
                
                logger.info(f"[临时文件][清理] 清理完成，删除了 {len(files_to_delete)} 个旧临时文件")
                
        except Exception as e:
            logger.warning(f"[临时文件][清理] 清理临时文件时出错: {e}")

    async def _restore_from_filesystem_backup(self, unified_msg_origin: str, conversation_id: str):
        """从临时文件中恢复对话历史。"""
        try:
            import os
            import json
            import glob
            
            # 查找匹配的临时文件
            save_dir = os.path.join(os.path.dirname(__file__), "conversation_backups")
            safe_umo = unified_msg_origin.replace(":", "_").replace("/", "_")
            pattern = os.path.join(save_dir, f"{safe_umo}_{conversation_id}.json")
            
            backup_files = glob.glob(pattern)
            if not backup_files:
                logger.info(f"[临时文件][恢复] 未找到临时文件: {pattern}")
                return None
            
            # 使用最新的临时文件
            latest_backup = max(backup_files, key=os.path.getmtime)
            
            with open(latest_backup, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            
            history_list = backup_data.get("history", [])
            logger.info(f"[临时文件][恢复] 从临时文件恢复对话历史: {latest_backup} (消息数: {len(history_list)})")
            
            return history_list
            
        except Exception as e:
            logger.error(f"[临时文件][恢复] 从临时文件恢复失败: {e}")
            return None

    async def _persist_conversation_history(self, unified_msg_origin: str, conversation_id: str, history_list: list):
        """智能对话历史保存：优先使用官方方法，失败时使用临时文件，支持自动迁移。"""
        try:
            cm = self.context.conversation_manager
            
            # 1. 首先检查是否有临时历史记录需要迁移
            await self._migrate_temp_history_to_official(unified_msg_origin, conversation_id)
            
            # 2. 检查并执行消息清理（如果启用）
            history_list = await self._cleanup_history_if_needed(unified_msg_origin, conversation_id, history_list)
            
            # 3. 尝试使用官方方法保存
            official_success = await self._try_official_persistence(unified_msg_origin, conversation_id, history_list)
            
            if official_success:
                # 官方方法成功，检查并清理对应的临时文件
                await self._cleanup_temp_history_file(unified_msg_origin, conversation_id)
                logger.info(f"[智能保存] 官方方法保存成功，对话ID={conversation_id}")
                return
            
            # 4. 官方方法失败，使用临时文件保存
            logger.warning(f"[智能保存] 官方方法失败，使用临时文件保存，对话ID={conversation_id}")
            await self._fallback_save_to_filesystem(unified_msg_origin, conversation_id, history_list)
            
        except Exception as e:
            logger.error(f"[智能保存] 持久化历史时发生异常: {e}", exc_info=True)

    async def _save_conversation_history(self, unified_msg_origin: str, history_list: list):
        """保存完整的对话历史记录到平台，确保上下文连续性。"""
        try:
            # 获取当前对话ID
            curr_cid = await self.context.conversation_manager.get_curr_conversation_id(unified_msg_origin)
            if not curr_cid:
                # 如果没有当前对话ID，创建一个新的对话
                curr_cid = await self.context.conversation_manager.create_conversation(unified_msg_origin)
                logger.info(f"[历史保存] 创建新对话ID: {curr_cid}")
            
            if curr_cid:
                # 使用智能持久化方法保存历史记录
                await self._persist_conversation_history(unified_msg_origin, curr_cid, history_list)
                logger.info(f"[历史保存] 对话历史已保存，对话ID={curr_cid}，消息数量={len(history_list)}")
            else:
                logger.warning(f"[历史保存] 无法创建或获取对话ID")
                
        except Exception as e:
            logger.error(f"[历史保存] 保存对话历史时出错: {e}", exc_info=True)

    async def _cleanup_history_if_needed(self, unified_msg_origin: str, conversation_id: str, history_list: list) -> list:
        """检查配置并执行消息清理（如果启用）。"""
        try:
            # 获取消息清理配置
            cleanup_config = self.config.get("message_cleanup", {})
            enable_cleanup = cleanup_config.get("enable_cleanup", False)
            
            # 详细日志：消息清理功能状态
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 消息清理功能状态: 启用={enable_cleanup}")
            
            if not enable_cleanup:
                # 详细日志：消息清理功能未启用
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 消息清理功能未启用，跳过清理")
                return history_list
            
            # 获取目标群组列表
            target_groups = cleanup_config.get("target_groups", [])
            max_messages = cleanup_config.get("max_messages", 1000)
            
            # 详细日志：消息清理配置信息
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 消息清理配置: 目标群组数量={len(target_groups)}，最大消息数={max_messages}")
                if target_groups:
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 目标群组列表: {target_groups}")
            
            # 检查是否需要对当前群组进行清理
            group_id = self._extract_group_id_from_umo(unified_msg_origin)
            
            # 详细日志：群组ID提取结果
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 从UMO提取群组ID: {group_id}")
            
            if not group_id:
                # 详细日志：无法提取群组ID
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 无法提取群组ID，跳过清理")
                return history_list
            
            # 检查群组是否在目标列表中（如果目标列表为空，则对所有群组生效）
            if target_groups and group_id not in target_groups:
                # 详细日志：群组不在目标列表中
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 群组 {group_id} 不在目标列表中，跳过清理")
                return history_list
            
            # 检查当前历史记录是否超出限制
            current_count = len(history_list)
            
            # 详细日志：当前历史记录数量
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 群组 {group_id} 当前历史记录数量: {current_count}")
            
            if current_count <= max_messages:
                # 详细日志：历史记录未超出限制
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 历史记录未超出限制 ({current_count} <= {max_messages})，无需清理")
                return history_list
            
            # 执行清理：删除最旧的消息，保留最新的max_messages条
            messages_to_remove = current_count - max_messages
            cleaned_history = history_list[messages_to_remove:]
            
            # 详细日志：清理操作详情
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 执行消息清理: 删除最旧的 {messages_to_remove} 条消息")
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 清理前消息数量: {current_count}，清理后消息数量: {len(cleaned_history)}")
            
            logger.info(f"[消息清理] 群组 {group_id} 历史记录超出限制 ({current_count} > {max_messages})，删除最旧的 {messages_to_remove} 条消息")
            
            return cleaned_history
            
        except Exception as e:
            logger.error(f"[消息清理] 执行消息清理时发生异常: {e}")
            return history_list

    def _extract_group_id_from_umo(self, unified_msg_origin: str) -> str:
        """从统一消息来源中提取群组ID。"""
        try:
            # UMO格式通常为 "platform:group_id" 或 "platform:user_id@group_id"
            if ":" in unified_msg_origin:
                parts = unified_msg_origin.split(":")
                if len(parts) >= 2:
                    # 提取群组ID部分
                    group_part = parts[1]
                    # 如果包含@符号，取@后面的部分
                    if "@" in group_part:
                        group_part = group_part.split("@")[1]
                    return group_part
            return ""
        except Exception as e:
            logger.warning(f"[消息清理] 提取群组ID失败: {e}")
            return ""

    async def _try_official_persistence(self, unified_msg_origin: str, conversation_id: str, history_list: list) -> bool:
        """尝试使用官方对话管理器进行持久化。"""
        try:
            cm = self.context.conversation_manager
            methods = [
                "update_conversation",  # 这是正确的主要保存方法
                "update_conversation_history",
                "set_conversation_history",
                "save_conversation_history",
                "save_history",
                # 追加式候选
                "append_conversation_history",
                "append_history",
                "add_conversation_history",
                "add_history",
                # 单条消息候选（后续逐条尝试）
                "append_message",
                "add_message",
                "add_conversation_message",
                "push_message",
                # 新增更多可能的API方法
                "update_history",
                "set_history",
                "store_conversation_history",
                "store_history",
                "record_conversation_history",
                "record_history",
            ]

            # 记录可用方法
            try:
                cm_type = type(cm).__name__
                available = [m for m in methods if hasattr(cm, m)]
                logger.info(f"[官方保存] CM类型={cm_type}, 对话ID={conversation_id}")
                logger.info(f"[官方保存] 可用方法: {available}")
            except Exception as e:
                logger.warning(f"[官方保存] 记录CM信息失败: {e}")

            # 优先尝试以列表直接保存
            for m in methods:
                if hasattr(cm, m):
                    try:
                        if self._is_detailed_logging():
                            logger.debug(f"[官方保存] 尝试 {m} 使用列表参数，历史长度={len(history_list)}")
                        await getattr(cm, m)(unified_msg_origin, conversation_id, history_list)
                        if self._is_detailed_logging():
                            logger.debug(f"[官方保存] {m} 成功（列表）")
                        return True
                    except TypeError as te:
                        # 尝试字符串格式
                        if self._is_detailed_logging():
                            logger.debug(f"[官方保存] {m} 列表参数类型不匹配，尝试字符串; 错误: {te}")
                    except Exception as e:
                        logger.debug(f"[官方保存] {m}（列表）失败: {e}")

                    try:
                        history_str = json.dumps(history_list, ensure_ascii=False)
                        if self._is_detailed_logging():
                            logger.debug(f"[官方保存] 尝试 {m} 使用字符串参数，长度={len(history_str)}")
                        await getattr(cm, m)(unified_msg_origin, conversation_id, history_str)
                        if self._is_detailed_logging():
                            logger.debug(f"[官方保存] {m} 成功（字符串）")
                        return True
                    except Exception as e2:
                        logger.debug(f"[官方保存] {m}（字符串）失败: {e2}")

            # 逐条消息尝试追加类API
            single_msg_methods = [m for m in methods if m in ("append_message", "add_message", "add_conversation_message", "push_message") and hasattr(cm, m)]
            if single_msg_methods:
                if self._is_detailed_logging():
                    logger.debug(f"[官方保存] 尝试使用逐条追加API: {single_msg_methods}")
                for msg in history_list:
                    role = (msg.get("role") if isinstance(msg, dict) else None) or "assistant"
                    content = (msg.get("content") if isinstance(msg, dict) else str(msg))
                    appended = False
                    for m in single_msg_methods:
                        try:
                            # 形态1: cm.m(umo, cid, role, content)
                            await getattr(cm, m)(unified_msg_origin, conversation_id, role, content)
                            appended = True
                            break
                        except TypeError:
                            pass
                        except Exception as e:
                            logger.debug(f"[官方保存] {m}(umo,cid,role,content) 失败: {e}")

                        try:
                            # 形态2: cm.m(umo, cid, {role, content})
                            await getattr(cm, m)(unified_msg_origin, conversation_id, {"role": role, "content": content})
                            appended = True
                            break
                        except Exception as e:
                            logger.debug(f"[官方保存] {m}(umo,cid,obj) 失败: {e}")

                    if not appended:
                        logger.debug(f"[官方保存] 逐条追加失败: role={role}, len={len(content)}")

                # 验证是否保存成功
                try:
                    conversation = await cm.get_conversation(unified_msg_origin, conversation_id)
                    if conversation and getattr(conversation, "history", None):
                        if self._is_detailed_logging():
                            logger.debug("[官方保存] 逐条追加后对话存在历史，认为保存成功")
                        return True
                except Exception as e:
                    logger.debug(f"[官方保存] 逐条追加后读取验证失败: {e}")

            # 最后尝试直接更新对话对象
            try:
                conversation = await cm.get_conversation(unified_msg_origin, conversation_id)
                if conversation is not None:
                    history_str = json.dumps(history_list, ensure_ascii=False)
                    if hasattr(conversation, "history"):
                        conversation.history = history_str
                        if hasattr(cm, "save_conversation"):
                            if self._is_detailed_logging():
                                logger.debug(f"[官方保存] 使用 save_conversation 进行最终回退保存")
                            await cm.save_conversation(unified_msg_origin, conversation_id, conversation)
                            return True
            except Exception as e:
                logger.debug(f"[官方保存] 直接保存回退失败: {e}")

            return False
            
        except Exception as e:
            logger.error(f"[官方保存] 尝试官方持久化时发生异常: {e}")
            return False

    async def _migrate_temp_history_to_official(self, unified_msg_origin: str, conversation_id: str):
        """将临时文件中的历史记录迁移到官方对话管理器。"""
        try:
            # 检查是否存在对应的临时文件
            temp_history = await self._load_temp_history_file(unified_msg_origin, conversation_id)
            if not temp_history:
                return
            
            logger.info(f"[迁移历史] 发现临时历史记录，对话ID={conversation_id}，消息数={len(temp_history)}")
            
            # 尝试使用官方方法保存临时历史
            migration_success = await self._try_official_persistence(unified_msg_origin, conversation_id, temp_history)
            
            if migration_success:
                # 迁移成功，删除临时文件
                await self._delete_temp_history_file(unified_msg_origin, conversation_id)
                logger.info(f"[迁移历史] 临时历史记录迁移成功，对话ID={conversation_id}")
            else:
                logger.warning(f"[迁移历史] 临时历史记录迁移失败，对话ID={conversation_id}")
                
        except Exception as e:
            logger.error(f"[迁移历史] 迁移临时历史记录时发生异常: {e}")

    async def _load_temp_history_file(self, unified_msg_origin: str, conversation_id: str) -> list:
        """加载临时历史记录文件。"""
        try:
            import os
            import json
            
            # 构建文件路径
            safe_umo = unified_msg_origin.replace(":", "_").replace("/", "_")
            filename = f"{safe_umo}_{conversation_id}.json"
            filepath = os.path.join(os.path.dirname(__file__), "conversation_backups", filename)
            
            if not os.path.exists(filepath):
                return []
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("history", [])
                
        except Exception as e:
            logger.error(f"[临时文件] 加载临时历史记录失败: {e}")
            return []

    async def _delete_temp_history_file(self, unified_msg_origin: str, conversation_id: str):
        """删除临时历史记录文件。"""
        try:
            import os
            
            safe_umo = unified_msg_origin.replace(":", "_").replace("/", "_")
            filename = f"{safe_umo}_{conversation_id}.json"
            filepath = os.path.join(os.path.dirname(__file__), "conversation_backups", filename)
            
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"[临时文件] 删除临时历史记录文件: {filename}")
                
        except Exception as e:
            logger.error(f"[临时文件] 删除临时历史记录文件失败: {e}")

    async def _cleanup_temp_history_file(self, unified_msg_origin: str, conversation_id: str):
        """清理临时历史记录文件（官方方法成功时调用）。"""
        await self._delete_temp_history_file(unified_msg_origin, conversation_id)

    async def _proactive_check_task(self, group_id: str, unified_msg_origin: str):
        """延时任务，在指定时间后检查一次是否需要主动插话。"""
        try:
            # 检查点3：在主动插话逻辑前检查图片拦截标记
            should_process_message = self.image_interception_states.get(group_id, True)
            if not should_process_message:
                logger.info(f"[主动插话检查] 检测到图片消息拦截标记，跳过主动插话逻辑，群组ID: {group_id}")
                # 重置标记为True，避免影响后续处理
                self.image_interception_states[group_id] = True
                return
            
            # 新增检查点：检查是否有强制回复正在进行，防止重复发送消息
            # 注意：这里需要检查全局的强制回复标记，因为主动插话任务无法访问原始event对象
            if hasattr(self, '_force_reply_in_progress') and self._force_reply_in_progress:
                logger.info(f"[主动插话检查] 检测到强制回复正在进行，跳过主动插话逻辑，群组ID: {group_id}")
                return
            
            # 新增检查点：检查是否正在进行读空气主动对话，防止冲突
            if self._air_reading_in_progress.get(group_id, False):
                logger.info(f"[主动插话检查] 检测到读空气主动对话正在进行，跳过主动插话逻辑，群组ID: {group_id}")
                return
            
            delay = self.config.get("proactive_reply_delay", 8)
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话任务开始，群组ID: {group_id}, 延迟时间: {delay}秒")
            
            await asyncio.sleep(delay)

            chat_history = []
            async with self.proactive_lock:
                if self.active_proactive_timers.get(group_id) is not asyncio.current_task():
                    # 检查是否启用详细日志
                    if self._is_detailed_logging():
                        logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话任务已取消或替换，群组ID: {group_id}")
                    return
                if group_id in self.group_chat_buffer:
                    chat_history = self.group_chat_buffer.pop(group_id, [])

            if not chat_history:
                logger.debug(f"[主动插话] 群 {group_id} 在 {delay}s 内无新消息，任务结束。")
                
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话无新消息，任务结束，群组ID: {group_id}")
                return

            logger.debug(f"[主动插话] 群 {group_id} 计时结束，收集到 {len(chat_history)} 条消息，请求LLM判断。")
            
            # 设置主动插话互斥标记，防止读空气主动对话同时触发
            self._proactive_reply_in_progress[group_id] = True
            logger.debug(f"[主动插话] 设置主动插话互斥标记，群组ID: {group_id}")
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话收集到消息，数量: {len(chat_history)}")
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 消息预览: {chat_history[:3] if len(chat_history) > 3 else chat_history}")

            # ✅ 关键修改：获取完整对话历史，包括平台保存的历史和插件上下文
            # 首先定义formatted_history变量
            formatted_history = "\n".join(chat_history)
            
            # 创建一个模拟的event对象来获取完整上下文
            from types import SimpleNamespace
            mock_event = SimpleNamespace()
            mock_event.unified_msg_origin = unified_msg_origin
            mock_event.get_group_id = lambda: group_id
            mock_event.get_sender_id = lambda: "system"
            mock_event.message_str = formatted_history
            
            history = await self._get_complete_conversation_history(mock_event)
            found_persona = await self._get_persona_info_str(unified_msg_origin)
            user_prompt = f"--- 最近的群聊内容 ---\n{formatted_history}\n--- 群聊内容结束 ---"
            
            instruction = PROACTIVE_REPLY_INSTRUCTION
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话准备调用LLM，群组ID: {group_id}")
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 用户提示长度: {len(user_prompt)}")
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 历史上下文数量: {len(history)}")
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 系统提示长度: {len(instruction)}")

            provider = self.context.get_using_provider()
            if not provider:
                logger.warning("[主动插话] 未找到可用的大语言模型提供商。")
                
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话未找到可用LLM提供商")
                return

            llm_response = await provider.text_chat(
                prompt=user_prompt, 
                contexts=history, 
                system_prompt=instruction
            )
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话LLM调用完成，响应长度: {len(llm_response.completion_text)}")
            
            # 优化版本：直接处理LLM响应，不再使用JSON格式
            response_text = llm_response.completion_text.strip()
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话LLM响应处理开始，响应长度: {len(response_text)}")
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 响应内容预览: {response_text[:200]}")
            
            # 检查是否是不回复标记
            if "[DO_NOT_REPLY]" in response_text:
                logger.info("[主动插话] LLM判断不需要插话，保持沉默")
                return
            
            # 直接使用LLM的回复内容
            if response_text:
                logger.info(f"[主动插话] LLM决定插话，内容: {response_text[:50]}...")
                
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话决定回复，内容预览: {response_text[:100]}")
                
                # 发送回复
                message_chain = MessageChain().message(response_text)
                await self.context.send_message(unified_msg_origin, message_chain)
                
                # 保存回复到平台历史记录
                try:
                    from types import SimpleNamespace
                    mock_event = SimpleNamespace()
                    mock_event.unified_msg_origin = unified_msg_origin
                    await self._save_bot_reply_to_conversation(mock_event, response_text)
                except Exception as e:
                    logger.warning(f"[主动插话] 保存回复到平台历史失败: {e}")
                
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话回复已发送")
            else:
                logger.info("[主动插话] LLM响应为空，保持沉默")

        except asyncio.CancelledError:
            logger.debug(f"[主动插话] 群 {group_id} 的检查任务被取消。")
        except Exception as e:
            logger.error(f"[主动插话] 群 {group_id} 的检查任务出现未知异常: {e}", exc_info=True)
        finally:
            # 清除主动插话互斥标记
            if group_id in self._proactive_reply_in_progress:
                self._proactive_reply_in_progress.pop(group_id, None)
                logger.debug(f"[主动插话] 清除主动插话互斥标记，群组ID: {group_id}")
            
            async with self.proactive_lock:
                if self.active_proactive_timers.get(group_id) is asyncio.current_task():
                    self.active_proactive_timers.pop(group_id, None)

    @filter.after_message_sent()
    async def after_bot_message_sent(self, event: AstrMessageEvent):
        """机器人发送消息后，同时启动主动插话和沉浸式对话的计时器。"""
        if not self.config.get("enable_plugin", True):
            return
        if event.is_private_chat():
            return

        group_id = event.get_group_id()
        sender_id = event.get_sender_id()
        
        if not group_id or sender_id == event.get_self_id():
            return

        # 检查点4：在启动沉浸式会话前检查图片拦截标记
        if not getattr(event, '_should_process_message', True):
            logger.info(f"[沉浸式会话检查] 检测到图片消息拦截标记，跳过沉浸式会话开启")
            # 重置标记为True，避免影响后续处理
            event._should_process_message = True
            return

        # 1. 启动/重置主动插话任务 (针对整个群聊)
        if self.config.get("enable_proactive_reply", True):
            # 传递图片拦截状态，默认为True（处理消息）
            should_process_message = getattr(event, '_should_process_message', True)
            await self._start_proactive_check(event.get_group_id(), event.unified_msg_origin, should_process_message)
        
        # 2. 启动/重置沉浸式对话任务 (针对被回复的那个用户)
        # 只有在不是图片消息拦截的情况下才开启沉浸式会话
        if not hasattr(event, '_is_image_message') or not event._is_image_message:
            await self._arm_immersive_session(event)
        else:
            logger.info(f"[图片检测] 检测到图片消息拦截，跳过沉浸式会话开启")

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """处理群聊消息的主入口 - 融合两种处理逻辑"""
        try:
            # ✅ 修复：确保event对象具有所有必需的属性
            if not hasattr(event, 'platform_meta') and hasattr(event, 'platform'):
                event.platform_meta = event.platform
            
            # ✅ 修复：确保session对象正确初始化
            if hasattr(event, 'session') and event.session:
                # 确保session有platform_id属性
                if not hasattr(event.session, 'platform_id') and hasattr(event.session, 'platform_name'):
                    event.session.platform_id = event.session.platform_name
        except Exception as e:
            logger.warning(f"[兼容性修复] 事件对象属性检查失败: {e}")
        
        group_id = event.get_group_id()
        
        # ✅ 第一步：在消息处理的最开始添加发送者信息
        sender_id = event.get_sender_id()
        sender_name = event.get_sender_name()
        sender_info = f"[User ID: {sender_id}, Nickname: {sender_name}]"
        
        # ✅ 第二步：添加时间戳功能
        timestamp_info = ""
        timestamp_config = self.config.get("timestamp_display", {})
        enable_timestamp = timestamp_config.get("enable_timestamp", False)
        
        if enable_timestamp:
            current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            timestamp_info = f"[Time: {current_time}]"
            
            # 详细日志：时间戳功能状态
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 时间戳显示功能已启用，当前时间: {current_time}")
        else:
            # 详细日志：时间戳功能状态
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 时间戳显示功能未启用")
        
        # 如果消息内容不为空，在消息前面添加发送者信息和时间戳
        if hasattr(event, 'message_str') and event.message_str:
            original_length = len(event.message_str)
            if timestamp_info:
                event.message_str = f"{sender_info} {timestamp_info} {event.message_str}"
            else:
                event.message_str = f"{sender_info} {event.message_str}"
            
            # 详细日志：消息内容修改
            if self._is_detailed_logging():
                new_length = len(event.message_str)
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 消息内容已修改，原始长度: {original_length}，新长度: {new_length}")
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 修改后消息预览: {event.message_str[:100]}...")
        
        # 初始化消息处理标志
        event._should_process_message = True
        
        # 1. 群组权限检查
        if not self.group_list_manager or not self.group_list_manager.check_group_permission(group_id):
            return
        
        # ✅ 2. 图片检测逻辑（在所有其他逻辑之前，包括沉浸式会话检查之前）
        # 第一步：检测@消息图片
        should_process_message, filtered_message, is_at_image = await self._detect_at_images(event)
        
        # 如果@消息图片转文字成功，更新消息内容
        if should_process_message and filtered_message is not None:
            logger.info(f"[图片检测] @消息图片处理完成，更新消息为: {filtered_message[:100]}...")
            event.message_str = filtered_message
        
        # 第二步：处理其他消息图片拦截（只在非@消息图片的情况下）
        if not is_at_image:
            should_process_message, filtered_message = await self._intercept_other_images(event, event.message_str)
            
            # 如果其他图片拦截返回False，直接返回
            if not should_process_message:
                return
            
            # 更新过滤后的消息
            if filtered_message is not None:
                event.message_str = filtered_message

        # 获取原始消息（保留前缀）
        raw_message = ""
        try:
            raw_message = str(event.message_obj.raw_message.get("raw_message", "")).lstrip()
        except Exception:
            raw_message = event.message_str.lstrip()
        
        astrbot_config = self.context.get_config()
        command_prefixes = astrbot_config.get('wake_prefix', ['/'])

        # 判断是否以任一指令前缀开头
        if any(raw_message.startswith(prefix) for prefix in command_prefixes):
            logger.debug("[调试] 命中指令前缀，清理并跳过沉浸式")
            session_key = (event.get_group_id(), event.get_sender_id())
            async with self.immersive_lock:
                if session_key in self.immersive_sessions:
                    self.immersive_sessions[session_key]['timer'].cancel()
                    self.immersive_sessions.pop(session_key, None)
            return

        # ✅ 3. 检查是否触发了沉浸式对话（移到图片检测之后）
        session_key = (event.get_group_id(), event.get_sender_id())
        async with self.immersive_lock:
            session_data = self.immersive_sessions.get(session_key)
        
        if session_data:
            # 此时 event.message_str 已经是图片转文字后的内容
            logger.info(f"[沉浸式对话] 检测到沉浸式会话，消息内容: {event.message_str[:100]}...")
            
            # 使用新抽取的独立方法处理沉浸式会话
            result = await self._handle_immersive_session(event, session_key, session_data)
            
            # 关键修复：只有当沉浸式会话真正处理了用户消息时才终止事件传播
            # 如果result为True，表示沉浸式会话已经处理了用户消息并可能发送了回复
            # 如果result为False，表示沉浸式会话没有处理用户消息（比如工具调用后的AI回复）
            if result:
                logger.info("[沉浸式对话] 沉浸式会话处理完成，完全终止事件传播")
                # 确保事件传播被完全终止，防止后续处理
                event.stop_event()
                # 关键修复：直接返回，不再执行后续的群聊处理逻辑
                return
            else:
                logger.info("[沉浸式对话] 沉浸式会话未处理消息，继续正常群聊处理")
                # 如果沉浸式会话没有处理消息，继续正常群聊处理

        # ✅ 4. 处理群聊插件的原有逻辑
        # 关键修改：确保@消息图片也能进入群聊处理流程
        logger.info(f"[群聊处理] 开始处理消息，is_at_image={is_at_image}, message_str长度={len(event.message_str)}")
        
        # ✅ 关键修改：先保存用户消息到平台历史记录
        try:
            await self._save_user_message_to_conversation(event, event.message_str)
        except Exception as e:
            logger.warning(f"[群聊处理] 保存用户消息到平台历史失败: {e}")
        
        # 记录会话标识并确保该群心跳存在
        if self.state_manager:
            self.state_manager.set_group_umo(group_id, event.unified_msg_origin)
        if self.active_chat_manager:
            self.active_chat_manager.ensure_flow(group_id)
            
            # 将消息传递给 ActiveChatManager 以进行频率分析
            if group_id in self.active_chat_manager.group_flows:
                self.active_chat_manager.group_flows[group_id].on_message(event)
        
        # ✅ 关键修改：确保@消息图片也能进入群聊处理流程
        # 处理消息
        async for result in self._process_group_message(event):
            yield result

        # ✅ 5. 收集消息用于主动插话
        if self.config.get("enable_proactive_reply", True):
            async with self.proactive_lock:
                if group_id in self.active_proactive_timers:
                    # 只收集非指令消息
                    if not any(raw_message.startswith(prefix) for prefix in command_prefixes):
                        self.group_chat_buffer[group_id].append(f"{event.get_sender_name()}: {event.message_str}")
    
    async def _process_group_message(self, event: AstrMessageEvent):
        """处理群聊消息的核心逻辑（群聊插件原有功能）"""
        group_id = event.get_group_id()
        user_id = event.get_sender_id()
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 开始处理群聊消息，群组ID: {group_id}, 用户ID: {user_id}")
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 消息内容: {event.message_str[:100] if event.message_str else '空消息'}")
        
        # ✅ 新增：检查是否是@消息或唤醒消息（强制触发回复）
        # 使用更严格的@检测逻辑，确保只有在真正@机器人的情况下才触发强制回复
        is_wake = getattr(event, 'is_wake', False)
        is_at_or_wake_command = getattr(event, 'is_at_or_wake_command', False)
        
        # 双重验证：除了框架标记外，还需要通过自定义@检测逻辑
        # 同时考虑普通@消息和带图片的@消息
        is_at_message = self._is_at_message(event.message_str, event)
        
        # 只有当框架标记为True且自定义@检测为True时，才认为是真正的@消息
        # 注意：is_at_image变量在on_group_message函数中定义，这里无法访问
        # 因此我们只使用is_at_message进行检测
        is_force_reply = (is_wake or is_at_or_wake_command) and is_at_message
        
        if is_force_reply:
            logger.info(f"[强制回复] 检测到@消息或唤醒消息，跳过意愿计算，直接调用LLM回复")
            logger.debug(f"[强制回复] 详细检测结果 - is_wake: {is_wake}, is_at_or_wake_command: {is_at_or_wake_command}, is_at_message: {is_at_message}")
            
            # ✅ 关键：临时屏蔽主动插话，防止同一条消息发两次
            # 设置一个全局临时标记，在本次消息处理期间屏蔽主动插话
            self._force_reply_in_progress = True
            
            # 直接生成回复，不进行意愿计算
            provider = self.context.get_using_provider()
            if not provider:
                logger.warning("[强制回复] 未找到可用的大语言模型提供商")
                # 清除临时标记
                self._force_reply_in_progress = False
                return
            
            # 获取人设信息
            found_persona = await self._get_persona_info_str(event.unified_msg_origin)
            
            # 获取聊天上下文
            if not self.context_analyzer:
                logger.warning("[强制回复] context_analyzer未初始化，无法获取聊天上下文")
                self._force_reply_in_progress = False
                return
            
            # ✅ 关键修改：获取完整对话历史，包括平台保存的历史和插件上下文
            contexts = await self._get_complete_conversation_history(event)
            
            # 调用LLM
            try:
                # 构建系统提示词，包含自定义提示词
                system_prompt = found_persona if found_persona else ""
                
                # 添加自定义系统提示词
                if isinstance(self.config, dict):
                    system_prompt_config = self.config.get("system_prompt", {})
                    enable_system_prompt = system_prompt_config.get("enable_system_prompt", False)
                    custom_prompt = system_prompt_config.get("custom_prompt", "").strip()
                    
                    # 详细日志：系统提示词功能状态
                    if self._is_detailed_logging():
                        logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 系统提示词功能状态: 启用={enable_system_prompt}")
                        if enable_system_prompt:
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 自定义提示词长度: {len(custom_prompt)} 字符")
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 自定义提示词预览: {custom_prompt[:100]}...")
                    
                    if enable_system_prompt and custom_prompt:
                        if system_prompt:
                            system_prompt += f"\n\n【自定义系统提示词】\n{custom_prompt}"
                            # 详细日志：系统提示词已合并
                            if self._is_detailed_logging():
                                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 已合并人格提示词和自定义系统提示词")
                        else:
                            system_prompt = f"【自定义系统提示词】\n{custom_prompt}"
                            # 详细日志：系统提示词已应用
                            if self._is_detailed_logging():
                                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 已应用自定义系统提示词")
                    else:
                        # 详细日志：系统提示词未应用
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 未应用自定义系统提示词")
                
                # ✅ 新增：添加工具识别功能
                if self._should_include_tools_prompt(event):
                    try:
                        available_tools = await self._get_available_tools()
                        if available_tools:
                            tools_prompt = self._format_tools_prompt(available_tools)
                            if system_prompt:
                                system_prompt += f"\n\n{tools_prompt}"
                            else:
                                system_prompt = tools_prompt
                            
                            logger.info(f"[工具识别] 已向AI提供{len(available_tools)}个可用工具信息")
                            if self._is_detailed_logging():
                                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 工具提示词预览: {tools_prompt[:200]}...")
                        else:
                            logger.debug("[工具识别] 未找到可用工具")
                    except Exception as e:
                        logger.warning(f"[工具识别] 获取工具信息失败: {e}")
                
                # 确保contexts是列表格式
                if not isinstance(contexts, list):
                    logger.warning(f"[强制回复] contexts格式错误，期望list，实际{type(contexts)}，使用空列表")
                    contexts = []
                
                llm_response = await provider.text_chat(
                    prompt=event.message_str,
                    contexts=contexts,
                    system_prompt=system_prompt if system_prompt else None
                )
                
                response_content = llm_response.completion_text.strip()
                
                if response_content:
                    logger.info(f"[强制回复] LLM回复成功，内容长度: {len(response_content)}")
                    
                    yield event.plain_result(response_content)
                    
                    # ✅ 关键修改：确保强制回复也保存到平台历史记录
                    try:
                        await self._save_bot_reply_to_conversation(event, response_content)
                    except Exception as e:
                        logger.warning(f"[强制回复] 保存回复到平台历史失败: {e}")
                    
                    # 更新连续回复计数
                    if self.state_manager:
                        self.state_manager.increment_consecutive_response(group_id)
                    
                    # 心流算法：回复成功后更新状态
                    if self.willingness_calculator:
                        await self.willingness_calculator.on_bot_reply_update(event, len(response_content))
                    
                    # ✅ 关键：@消息回复后，启动沉浸式对话
                    await self._arm_immersive_session(event)
                    logger.info(f"[强制回复] 已启动沉浸式对话会话")
                    
                    # 清除临时标记
                    self._force_reply_in_progress = False
                    
                    return
                else:
                    logger.warning("[强制回复] LLM返回了空内容")
                    # 清除临时标记
                    self._force_reply_in_progress = False
                    return
            except Exception as e:
                logger.error(f"[强制回复] LLM调用失败: {e}")
                # 清除临时标记
                self._force_reply_in_progress = False
                return
        
        # 获取聊天上下文
        if not self.context_analyzer:
            logger.warning("[群聊处理] context_analyzer未初始化，跳过处理")
            return
        
        # ✅ 关键修改：获取完整对话历史，包括平台保存的历史和插件上下文
        chat_context = await self.context_analyzer.analyze_chat_context(event)
        # 同时获取完整的历史记录作为补充
        complete_history = await self._get_complete_conversation_history(event)
        if complete_history:
            # 将完整历史记录添加到聊天上下文中
            if 'messages' not in chat_context:
                chat_context['messages'] = []
            # 合并上下文，避免重复
            existing_texts = set()
            for msg in chat_context['messages']:
                if isinstance(msg, dict):
                    content = msg.get('content', '')
                    # 如果content是列表，转换为字符串；如果是字符串，直接使用
                    if isinstance(content, list):
                        content_str = ' '.join(str(item) for item in content)
                    else:
                        content_str = str(content)
                    existing_texts.add(content_str)
            
            for msg in complete_history:
                if isinstance(msg, dict):
                    content = msg.get('content', '')
                    # 如果content是列表，转换为字符串；如果是字符串，直接使用
                    if isinstance(content, list):
                        content_str = ' '.join(str(item) for item in content)
                    else:
                        content_str = str(content)
                    
                    if content_str not in existing_texts:
                        chat_context['messages'].append(msg)
                        # 添加到existing_texts避免重复添加
                        existing_texts.add(content_str)
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 聊天上下文分析完成，消息数量: {len(chat_context.get('messages', []))}")
        
        # 判断交互模式
        if not self.interaction_manager:
            logger.warning("[群聊处理] interaction_manager未初始化，跳过处理")
            return
        interaction_mode = self.interaction_manager.determine_interaction_mode(chat_context)
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 交互模式判断结果: {interaction_mode}")
        
        # 观察模式不回复
        if interaction_mode == "observation":
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 当前为观察模式，跳过回复处理")
            return
        
        # 计算回复意愿
        if not self.willingness_calculator:
            logger.warning("[群聊处理] willingness_calculator未初始化，跳过处理")
            return
        willingness_result = await self.willingness_calculator.calculate_response_willingness(event, chat_context)
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 意愿计算结果: {willingness_result}")
        
        # 如果不需要 LLM 决策且意愿不足，直接跳过
        if not willingness_result.get("requires_llm_decision") and not willingness_result.get("should_respond"):
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 不需要LLM决策且意愿不足，跳过回复")
            return
        
        # 检查连续回复限制
        max_consecutive = getattr(self.config, 'max_consecutive_responses', 3)
        consecutive_count = 0
        if self.state_manager:
            consecutive_count = self.state_manager.get_consecutive_responses().get(group_id, 0)
        if consecutive_count >= max_consecutive:
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 连续回复限制已达上限 ({consecutive_count}/{max_consecutive})，跳过回复")
            return
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 当前连续回复计数: {consecutive_count}/{max_consecutive}")
        
        # 检查主动插话是否正在进行，如果是则跳过读空气功能
        if self._proactive_reply_in_progress.get(group_id, False):
            logger.debug(f"[读空气] 检测到主动插话正在进行，群组ID: {group_id}，跳过读空气功能")
            return
        
        # 设置读空气主动对话互斥标记，防止主动插话同时触发
        self._air_reading_in_progress[group_id] = True
        logger.debug(f"[读空气] 设置读空气互斥标记，群组ID: {group_id}")
        
        # 生成回复（包含读空气功能）
        if not self.response_engine:
            logger.warning("[群聊处理] response_engine未初始化，跳过处理")
            # 清除读空气互斥标记
            if group_id in self._air_reading_in_progress:
                self._air_reading_in_progress.pop(group_id, None)
                logger.debug(f"[读空气] 清除读空气互斥标记，群组ID: {group_id}")
            return
        response_result = await self.response_engine.generate_response(event, chat_context, willingness_result)
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 回复生成结果: {response_result}")
        
        # 根据结果决定是否回复
        if response_result.get("should_reply"):
            response_content = response_result.get("content")
            if response_content:
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 决定回复，内容长度: {len(response_content)}，内容预览: {response_content[:100]}")
                
                yield event.plain_result(response_content)

                # ✅ 关键修改：确保普通群聊回复也保存到平台历史记录
                try:
                    await self._save_bot_reply_to_conversation(event, response_content)
                except Exception as e:
                    logger.warning(f"[群聊处理] 保存回复到平台历史失败: {e}")

                # 更新连续回复计数
                if self.state_manager:
                    self.state_manager.increment_consecutive_response(group_id)

                # 心流算法：回复成功后更新状态
                if self.willingness_calculator:
                    await self.willingness_calculator.on_bot_reply_update(event, len(response_content))

                # 记录决策信息（用于调试）
                decision_method = response_result.get("decision_method")
                willingness_score = response_result.get("willingness_score")
                logger.debug(f"群组 {group_id} 回复 - 方法: {decision_method}, 意愿分: {willingness_score:.2f}")
                
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 回复已发送，连续回复计数已更新")
        else:
            # 记录跳过回复的原因
            decision_method = response_result.get("decision_method")
            skip_reason = response_result.get("skip_reason", "意愿不足")
            willingness_score = response_result.get("willingness_score")
            logger.debug(f"群组 {group_id} 跳过回复 - 方法: {decision_method}, 原因: {skip_reason}, 意愿分: {willingness_score:.2f}")
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 跳过回复，原因: {skip_reason}")
        
        # 更新交互状态
        if self.interaction_manager:
            await self.interaction_manager.update_interaction_state(event, chat_context, response_result)
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 交互状态已更新，消息处理完成")
        
        # 清除读空气主动对话互斥标记
        if group_id in self._air_reading_in_progress:
            self._air_reading_in_progress.pop(group_id, None)
            logger.debug(f"[读空气] 清除读空气互斥标记，群组ID: {group_id}")

    # 读空气功能：处理LLM回复，进行文本过滤
    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        """处理大模型回复，进行文本过滤"""
        try:
            if resp.role != "assistant":
                return
        except Exception as e:
            logger.error(f"处理LLM回复时发生错误: {e}")

    # 读空气功能：在消息发送前检查是否包含<NO_RESPONSE>标记
    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        """在消息发送前处理读空气功能"""
        try:
            result = event.get_result()
            if result is None or not result.chain:
                return

            # 检查是否为LLM结果且包含<NO_RESPONSE>标记
            if result.is_llm_result():
                # 获取消息文本内容
                message_text = ""
                for comp in result.chain:
                    if hasattr(comp, 'text'):
                        message_text += comp.text

                # 如果包含<NO_RESPONSE>标记，清空事件结果以阻止消息发送
                if "<NO_RESPONSE>" in message_text:
                    logger.debug("检测到读空气标记<NO_RESPONSE>，阻止消息发送")
                    event.clear_result()
                    logger.debug("已清空事件结果，消息发送被阻止")

        except Exception as e:
            logger.error(f"处理消息发送前事件时发生错误: {e}")
    
    @filter.command("群聊主动状态")
    async def gcstatus(self, event: AstrMessageEvent):
        """显示当前群的主动对话状态"""
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("请在群聊中使用此命令。")
            return

        # 确保会话映射与心跳存在
        if not self.state_manager or not self.active_chat_manager:
            yield event.plain_result("插件组件未正确初始化，无法显示状态。")
            return
            
        self.state_manager.set_group_umo(group_id, event.unified_msg_origin)
        self.active_chat_manager.ensure_flow(group_id)

        stats = self.active_chat_manager.get_stats(group_id)

        has_flow = "✅" if stats.get("has_flow") else "❌"
        has_umo = "✅" if stats.get("has_umo") else "❌"
        focus = float(stats.get("focus", 0.0) or 0.0)
        at_boost = float(stats.get("at_boost", 0.0) or 0.0)
        effective = float(stats.get("effective", 0.0) or 0.0)
        mlm = int(stats.get("messages_last_minute", 0) or 0)
        cd = float(stats.get("cooldown_remaining", 0.0) or 0.0)
        last_ts = float(stats.get("last_trigger_ts", 0.0) or 0.0)
        elapsed = (time.time() - last_ts) if last_ts > 0 else 0.0

        # 配置值
        hb_thr = float(getattr(self.config, "heartbeat_threshold", 0.55) or 0.55)
        wil_thr = float(getattr(self.config, "willingness_threshold", 0.5) or 0.5)
        obs_thr = float(getattr(self.config, "observation_mode_threshold", 0.2) or 0.2)
        min_interest = float(getattr(self.config, "min_interest_score", 0.6) or 0.6)
        at_boost_cfg = float(getattr(self.config, "at_boost_value", 0.5) or 0.5)

        # 计算意愿分与群活跃度
        if not self.context_analyzer or not self.willingness_calculator:
            yield event.plain_result("插件组件未正确初始化，无法计算状态。")
            return
        chat_context = await self.context_analyzer.analyze_chat_context(event)
        will_res = await self.willingness_calculator.calculate_response_willingness(event, chat_context)
        willingness_score = float(will_res.get("willingness_score", 0.0) or 0.0)
        decision_ctx = will_res.get("decision_context", {}) or {}
        group_activity = float(decision_ctx.get("group_activity", 0.0) or 0.0)

        # 评估专注兴趣度
        try:
            if self.focus_chat_manager:
                interest = float(await self.focus_chat_manager.evaluate_focus_interest(event, chat_context))
            else:
                interest = 0.0
        except Exception:
            interest = 0.0

        # 从 flow 读取心跳/冷却常量（回退到默认）
        flow = self.active_chat_manager.group_flows.get(group_id)
        hb_int = getattr(flow, "HEARTBEAT_INTERVAL", 15) if flow else 15
        cd_total = getattr(flow, "COOLDOWN_SECONDS", 120) if flow else 120

        msg = (
            "主动对话状态\n"
            f"心跳: {has_flow}    UMO: {has_umo}\n"
            f"最近1分钟消息: {mlm}\n"
            f"焦点: {focus:.2f}\n"
            f"@增强(当前/设定): {at_boost:.2f} / {at_boost_cfg:.2f}\n"
            f"心跳: ({effective:.2f}/{hb_thr:.2f})\n"
            f"意愿: ({willingness_score:.2f}/{wil_thr:.2f})\n"
            f"观察: ({group_activity:.2f}/{obs_thr:.2f})\n"
            f"专注: ({interest:.2f}/{min_interest:.2f})\n"
            f"冷却剩余: {cd:.1f}s  上次触发: {elapsed:.1f}s\n"
            f"心跳/冷却: {hb_int}s / {cd_total}s"
        )
        yield event.plain_result(msg)

    async def process_images(self, message_event) -> Dict[str, Any]:
        """
        处理消息中的图片
        
        Args:
            message_event: 消息事件对象
            
        Returns:
            Dict包含处理结果:
            - images: 直接传递的图片列表
            - captions: 图片转文字的描述列表
            - has_images: 是否包含图片
            - filtered_message: 过滤掉图片标识符后的消息文本
        """
        
        # 第一步：先调用@消息图片检测函数，确保@消息的图片不会被拦截
        at_image_result = await self._detect_and_caption_at_images(message_event)
        if at_image_result:
            return at_image_result
        
        # 第二步：再调用消息图片拦截函数，处理其他消息的图片
        return await self._intercept_other_images(message_event)

    async def terminate(self):
        """插件终止时的清理工作"""
        logger.info("增强版群聊插件正在终止...")
        # 停止主动聊天管理器
        if self.active_chat_manager:
            self.active_chat_manager.stop_all_flows()
        # 清理沉浸式对话和主动插话的计时器
        async with self.immersive_lock:
            for session_key, session_data in self.immersive_sessions.items():
                if 'timer' in session_data:
                    session_data['timer'].cancel()
            self.immersive_sessions.clear()
        
        async with self.proactive_lock:
            for group_id, timer in self.active_proactive_timers.items():
                if timer:
                    timer.cancel()
            self.active_proactive_timers.clear()
            self.group_chat_buffer.clear()
        
        # 使用状态管理器清理所有持久化状态
        if self.state_manager:
            self.state_manager.clear_all_state()
        logger.info("增强版群聊插件已终止")

    # 搜索适配机制：工具错误处理
    async def _handle_tool_call_error(self, tool_name: str, error: Exception, event: AstrMessageEvent = None) -> str:
        """处理工具调用错误，适配平台搜索配置
        
        Args:
            tool_name: 工具名称
            error: 错误对象
            event: 消息事件对象（可选）
            
        Returns:
            友好的错误提示信息
        """
        error_msg = str(error)
        logger.error(f"[工具错误] 工具调用失败: {tool_name} - {error_msg}")
        
        # 关键改进：动态适配平台搜索配置
        # 检查是否是搜索相关的错误
        if "Tavily" in error_msg or "API key" in error_msg.lower() or "websearch" in error_msg.lower():
            # 获取平台配置的搜索提供商信息
            try:
                cfg = self.context.get_config()
                prov_settings = cfg.get("provider_settings", {})
                websearch_enable = prov_settings.get("web_search", False)
                provider = prov_settings.get("websearch_provider", "default")
                
                # 根据平台配置提供相应的错误提示
                if not websearch_enable:
                    return "搜索功能未在AstrBot平台中启用。请在平台设置中启用搜索功能。"
                elif provider == "tavily" and "API key" in error_msg.lower():
                    return "Tavily搜索需要配置API密钥。请在AstrBot平台设置中配置websearch_tavily_key。"
                elif provider == "baidu_ai_search" and "API key" in error_msg.lower():
                    return "百度AI搜索需要配置API密钥。请在AstrBot平台设置中配置websearch_baidu_app_builder_key。"
                else:
                    return f"搜索工具执行失败: {error_msg}"
            except Exception as config_error:
                logger.warning(f"[搜索适配] 获取平台配置失败: {config_error}")
                return f"搜索工具执行失败: {error_msg}"
        
        # 其他类型的错误
        return f"工具执行失败: {error_msg}"

    # 搜索适配机制：格式化工具提示时添加搜索适配说明
    def _format_tools_prompt_with_search_adapter(self, tools_info: Dict[str, Any]) -> str:
        """格式化工具信息为AI可理解的提示词，包含搜索适配说明"""
        if not tools_info or tools_info.get("total_count", 0) == 0:
            return ""
        
        prompt_parts = ["\n\n=== AstrBot平台可用工具 ==="]
        
        # 添加搜索适配说明
        search_config = tools_info.get("platform_search_config", {})
        if search_config.get("has_search_config", False):
            websearch_enable = search_config.get("websearch_enable", False)
            provider = search_config.get("websearch_provider", "default")
            
            if websearch_enable:
                provider_names = {
                    "default": "默认搜索引擎",
                    "tavily": "Tavily搜索引擎",
                    "baidu_ai_search": "百度AI搜索"
                }
                provider_name = provider_names.get(provider, provider)
                prompt_parts.append(f"🔍 搜索功能: 已启用 ({provider_name})")
            else:
                prompt_parts.append("🔍 搜索功能: 未启用")
        else:
            prompt_parts.append("🔍 搜索功能: 平台配置未知")
        
        prompt_parts.append("")
        
        # 官方工具
        official_tools = tools_info.get("official_tools", [])
        if official_tools:
            prompt_parts.append("📋 官方工具:")
            for tool in official_tools:
                prompt_parts.append(f"🔧 {tool['name']}: {tool['description']}")
                if tool.get('parameters') and tool['parameters'].get('properties'):
                    params = tool['parameters']['properties']
                    if params:
                        param_desc = ", ".join([f"{name}({param.get('type', 'unknown')})" for name, param in params.items()])
                        prompt_parts.append(f"   参数: {param_desc}")
        
        # 插件工具
        plugin_tools = tools_info.get("plugin_tools", [])
        if plugin_tools:
            prompt_parts.append("\n🔌 插件工具:")
            for tool in plugin_tools:
                prompt_parts.append(f"⚡ {tool['name']}: {tool['description']}")
                if tool.get('parameters') and tool['parameters'].get('properties'):
                    params = tool['parameters']['properties']
                    if params:
                        param_desc = ", ".join([f"{name}({param.get('type', 'unknown')})" for name, param in params.items()])
                        prompt_parts.append(f"   参数: {param_desc}")
        
        # 使用说明
        prompt_parts.append("\n💡 使用说明:")
        prompt_parts.append("- 你可以直接调用这些工具来完成任务")
        prompt_parts.append("- 工具调用会自动执行，无需手动操作")
        prompt_parts.append("- 优先使用官方工具，插件工具可能有额外依赖")
        
        # 搜索适配说明
        prompt_parts.append("\n🔍 搜索适配说明:")
        prompt_parts.append("- 搜索功能会自动适配AstrBot平台的配置")
        prompt_parts.append("- 如果部分搜索工具失败，系统会尝试其他可用工具")
        prompt_parts.append("- 当搜索工具部分成功时，请明确告知用户确实搜到了一些内容")
        prompt_parts.append("- 即使某个搜索方法失败，也不代表完全没有搜索结果")
        prompt_parts.append("- 优先使用可用的搜索工具，失败的工具会自动跳过")
        
        return "\n".join(prompt_parts)