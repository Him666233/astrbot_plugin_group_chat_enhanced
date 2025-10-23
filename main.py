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

# LLM指令常量定义
IMMERSIVE_SESSION_INSTRUCTION = (
    "你正在与一位用户进行沉浸式对话，需要根据对话历史和人格设定，判断是否要继续回复。"
    "【1. 输出格式】必须严格返回```json{\"should_reply\": 布尔值, \"content\": \"字符串\"}```的格式，否则无效。"
    "【2. 字段解释】"
    " - `should_reply` (布尔值): 决定你是否想主动发起或继续对话。true表示想，false表示不想。"
    " - `content` (字符串): 你的回复内容。即使不想继续对话(false)，也可以通过提供内容来发表简短、非引导性的评论。"
    "【3. 判断场景】"
    " - **想继续对话 (should_reply: true)**: 当用户的话题有趣、与你相关、或你能提供价值时使用。此时`content`应为具体回复。"
    " - **不想继续对话 (should_reply: false)**: 当用户的话题无关、无聊、或你想结束对话时使用。此时`content`可为空字符串(不回复)，或一句简短的结束语。"
    " - **情景感知**: 这是用户的追问，请结合'完整对话历史'理解前因后果，再做出决策。"
)

PROACTIVE_REPLY_INSTRUCTION = (
    "你需要根据对话历史和人格设定，判断是否要回复以及回复什么。"
    "【1. 输出格式】必须严格返回```json{\"should_reply\": 布尔值, \"content\": \"字符串\"}```的格式，否则无效。"
    "【2. 字段解释】"
    " - `should_reply` (布尔值): 决定你是否想主动发起或继续对话。true表示想，false表示不想。"
    " - `content` (字符串): 你的回复内容。即使不想继续对话(false)，也可以通过提供内容来发表简短、非引导性的评论。"
    "【3. 判断场景】"
    " - **想继续对话 (should_reply: true)**: 当话题有趣、与你相关、或你能提供价值时使用。此时`content`应为具体回复。"
    " - **不想继续对话 (should_reply: false)**: 当话题无关、无聊、或你想结束对话时使用。此时`content`可为空字符串（不回复），或一句简短的结束语/吐槽。"
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

@register("astrbot_plugin_group_chat_enhanced", "qa296", "增强版群聊插件：融合了沉浸式对话和主动插话功能，提供更智能的群聊交互体验。", "2.0.0", "https://github.com/qa296/astrbot_plugin_group_chat")
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
        
        logger.info("增强版群聊插件初始化完成 - 已融合沉浸式对话和主动插话功能")
        
        # 初始化图片处理相关缓存
        self.caption_cache = {}
        
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

    async def _handle_json_extraction_failure(self, completion_text: str, unified_msg_origin: str, context: str):
        """
        统一处理JSON提取失败的情况
        
        Args:
            completion_text: LLM的原始回复文本
            unified_msg_origin: 消息来源标识
            context: 上下文描述（用于日志）
        """
        logger.warning(f"[{context}] 从LLM回复中未能提取出JSON。原始回复: {completion_text}")
        
        # 检查是否有有效的回复内容
        if completion_text and completion_text.strip():
            # 检查是否包含有意义的内容（不是纯JSON格式错误信息）
            if not any(keyword in completion_text.lower() for keyword in ['json', 'format', 'error', 'invalid']):
                logger.info(f"[{context}] 使用原始回复内容: {completion_text[:100]}...")
                message_chain = MessageChain().message(completion_text)
                await self.context.send_message(unified_msg_origin, message_chain)
            else:
                logger.warning(f"[{context}] LLM回复包含格式错误信息，跳过发送")
        else:
            logger.warning(f"[{context}] LLM回复为空，跳过发送")

    def _extract_json_from_text(self, text: str) -> str:
        """从文本中提取JSON内容（来自直接回复插件）"""
        # 策略1：寻找被 ```json ... ``` 包裹的代码块
        json_block_pattern = r'```json\s*(\{.*?\})\s*```'
        match = re.search(json_block_pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 策略2：寻找被 ``` ... ``` 包裹的代码块（不指定语言）
        generic_block_pattern = r'```\s*(\{.*?\})\s*```'
        match = re.search(generic_block_pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 策略3：寻找被 ```json 和 ``` 包裹的多行代码块
        multiline_json_pattern = r'```json\s*([\s\S]*?)\s*```'
        match = re.search(multiline_json_pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 策略4：寻找被 ``` 和 ``` 包裹的多行代码块（不指定语言）
        multiline_generic_pattern = r'```\s*([\s\S]*?)\s*```'
        match = re.search(multiline_generic_pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 策略5：寻找第一个 { 和最后一个 } 之间的所有内容
        start = text.find("{")
        if start != -1:
            brace_count = 0
            for i in range(start, len(text)):
                if text[i] == '{':
                    brace_count += 1
                elif text[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        return text[start:i+1].strip()
        
        # 策略6：如果所有策略都失败，尝试直接解析整个文本
        try:
            json.loads(text.strip())
            return text.strip()
        except:
            pass
            
        return ""

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
            # 检测@符号后紧挨着机器人名字的情况
            at_name_pattern1 = r'@' + re.escape(bot_name) + r'(?![\w\u4e00-\u9fa5])'  # @后紧挨着名字，后面不是字母、数字、中文
            # 检测@符号后隔一个空格跟着机器人名字的情况
            at_name_pattern2 = r'@\s+' + re.escape(bot_name) + r'(?![\w\u4e00-\u9fa5])'
            
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
            
            # 检测@符号后紧挨着机器人名字的情况
            at_name_pattern1 = r'@' + re.escape(bot_name) + r'(?![\w\u4e00-\u9fa5])'  # @后紧挨着名字，后面不是字母、数字、中文
            # 检测@符号后隔一个空格跟着机器人名字的情况
            at_name_pattern2 = r'@\s+' + re.escape(bot_name) + r'(?![\w\u4e00-\u9fa5])'
            
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
        
        llm_response = await provider.text_chat(
            prompt=user_prompt,
            contexts=saved_context,
            system_prompt=instruction
        )
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - LLM调用完成，响应长度: {len(llm_response.completion_text)}")
        
        json_string = self._extract_json_from_text(llm_response.completion_text)
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - JSON提取结果: {'成功' if json_string else '失败'}")
            if json_string:
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 提取的JSON长度: {len(json_string)}")
        
        if not json_string:
            # 统一处理JSON提取失败的情况
            await self._handle_json_extraction_failure(llm_response.completion_text, event.unified_msg_origin, "沉浸式对话")
            return True
        
        try:
            decision_data = json.loads(json_string)
            should_reply = decision_data.get("should_reply")
            content = decision_data.get("content", "")
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - JSON解析成功，should_reply={should_reply}, content长度={len(content)}")
        
            if should_reply is True:
                if content:
                    logger.info(f"[沉浸式对话] LLM判断需要回复，内容: {content[:50]}...")
                    
                    # 检查是否启用详细日志
                    if self._is_detailed_logging():
                        logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 沉浸式对话决定回复，内容预览: {content[:100]}")
                    
                    message_chain = MessageChain().message(content)
                    await self.context.send_message(event.unified_msg_origin, message_chain)
                    
                    # ✅ 关键修改：确保沉浸式对话的回复也保存到平台历史记录
                    try:
                        # 通过平台的对话管理器保存回复
                        await self._save_bot_reply_to_conversation(event, content)
                    except Exception as e:
                        logger.warning(f"[沉浸式对话] 保存回复到平台历史失败: {e}")
                    
                    # 回复后重新启动沉浸式会话
                    await self._arm_immersive_session(event)
                    
                    # 检查是否启用详细日志
                    if self._is_detailed_logging():
                        logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 沉浸式回复已发送，会话已重新启动")
                else:
                    logger.info("[沉浸式对话] LLM判断为 true 但内容为空，跳过回复。")
                    
                    # 检查是否启用详细日志
                    if self._is_detailed_logging():
                        logger.debug(f"GroupChatPluginEnhanced: 详细日志 - LLM判断为true但内容为空，跳过回复")
            elif should_reply is False:
                if content:
                    logger.info(f"[沉浸式对话] LLM判断为 false 但仍回复，内容: {content[:50]}...")
                    
                    # 检查是否启用详细日志
                    if self._is_detailed_logging():
                        logger.debug(f"GroupChatPluginEnhanced: 详细日志 - LLM判断为false但仍回复，内容预览: {content[:100]}")
                    
                    message_chain = MessageChain().message(content)
                    await self.context.send_message(event.unified_msg_origin, message_chain)
                else:
                    logger.info("[沉浸式对话] LLM判断为 false 且无内容，跳过回复与计时。")
                    
                    # 检查是否启用详细日志
                    if self._is_detailed_logging():
                        logger.debug(f"GroupChatPluginEnhanced: 详细日志 - LLM判断为false且无内容，跳过回复")
                # 结束沉浸式对话
                async with self.immersive_lock:
                    if session_key in self.immersive_sessions:
                        self.immersive_sessions[session_key]['timer'].cancel()
                        self.immersive_sessions.pop(session_key, None)
                    
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 沉浸式对话会话已结束，会话键: {session_key}")
            else:
                logger.warning("[沉浸式对话] LLM返回格式异常，跳过处理。")
                
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - LLM返回格式异常，should_reply值: {should_reply}")
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            logger.error(f"[沉浸式对话] 解析LLM的JSON回复失败: {e}\n清理后文本: '{json_string}'")
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - JSON解析异常: {e}")
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 原始JSON字符串: {json_string}")

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
                return json.loads(conversation.history)
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
                    plugin_context = chat_context.get('messages', [])
                except Exception as e:
                    logger.warning(f"[沉浸式对话] 获取插件上下文失败: {e}")
            
            # 3. 合并上下文，优先使用平台历史，插件上下文作为补充
            complete_context = platform_history.copy()
            
            # 如果平台历史为空或很少，使用插件上下文
            if len(complete_context) < 5 and plugin_context:
                logger.info(f"[沉浸式对话] 平台历史较少({len(complete_context)}条)，使用插件上下文({len(plugin_context)}条)")
                complete_context = plugin_context
            elif plugin_context:
                # 合并上下文，避免重复
                logger.info(f"[沉浸式对话] 合并平台历史({len(complete_context)}条)和插件上下文({len(plugin_context)}条)")
                # 简单的去重逻辑：如果插件上下文中有平台历史没有的消息，则添加
                platform_texts = {msg.get('content', '') for msg in complete_context if isinstance(msg, dict)}
                for msg in plugin_context:
                    if isinstance(msg, dict) and msg.get('content', '') not in platform_texts:
                        complete_context.append(msg)
            
            logger.info(f"[沉浸式对话] 完整上下文获取完成，总长度: {len(complete_context)}")
            return complete_context
            
        except Exception as e:
            logger.error(f"[沉浸式对话] 获取完整对话历史时出错: {e}", exc_info=True)
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
            
            # 2. 尝试使用官方方法保存
            official_success = await self._try_official_persistence(unified_msg_origin, conversation_id, history_list)
            
            if official_success:
                # 官方方法成功，检查并清理对应的临时文件
                await self._cleanup_temp_history_file(unified_msg_origin, conversation_id)
                logger.info(f"[智能保存] 官方方法保存成功，对话ID={conversation_id}")
                return
            
            # 3. 官方方法失败，使用临时文件保存
            logger.warning(f"[智能保存] 官方方法失败，使用临时文件保存，对话ID={conversation_id}")
            await self._fallback_save_to_filesystem(unified_msg_origin, conversation_id, history_list)
            
        except Exception as e:
            logger.error(f"[智能保存] 持久化历史时发生异常: {e}", exc_info=True)

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
            
            json_string = self._extract_json_from_text(llm_response.completion_text)
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话JSON提取结果: {'成功' if json_string else '失败'}")
                if json_string:
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 提取的JSON长度: {len(json_string)}")
            
            if not json_string:
                # 统一处理JSON提取失败的情况
                await self._handle_json_extraction_failure(llm_response.completion_text, unified_msg_origin, "主动插话")
                return
            
            try:
                decision_data = json.loads(json_string)
                should_reply = decision_data.get("should_reply")
                content = decision_data.get("content", "")
                
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话JSON解析成功，should_reply={should_reply}, content长度={len(content)}")
            
                if should_reply is True:
                    if content:
                        logger.info(f"[主动插话] LLM判断需要回复，内容: {content[:50]}...")
                        
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话决定回复，内容预览: {content[:100]}")
                        
                        message_chain = MessageChain().message(content)
                        await self.context.send_message(unified_msg_origin, message_chain)
                        
                        # ✅ 关键修改：确保主动插话的回复也保存到平台历史记录
                        try:
                            # 创建一个模拟的event对象来保存回复
                            from types import SimpleNamespace
                            mock_event = SimpleNamespace()
                            mock_event.unified_msg_origin = unified_msg_origin
                            await self._save_bot_reply_to_conversation(mock_event, content)
                        except Exception as e:
                            logger.warning(f"[主动插话] 保存回复到平台历史失败: {e}")
                        
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话回复已发送")
                    else:
                        logger.info("[主动插话] LLM判断为 true 但内容为空，跳过回复，继续计时。")
                        
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话判断为true但内容为空，继续计时")
                        
                        # 重新启动主动插话任务，传递默认的图片拦截状态（True）
                        await self._start_proactive_check(group_id, unified_msg_origin, True)
                elif should_reply is False:
                    if content:
                        logger.info(f"[主动插话] LLM判断为 false 但仍回复，内容: {content[:50]}...")
                        
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话判断为false但仍回复，内容预览: {content[:100]}")
                        
                        message_chain = MessageChain().message(content)
                        await self.context.send_message(unified_msg_origin, message_chain)
                        
                        # ✅ 关键修改：确保主动插话的回复也保存到平台历史记录
                        try:
                            # 创建一个模拟的event对象来保存回复
                            from types import SimpleNamespace
                            mock_event = SimpleNamespace()
                            mock_event.unified_msg_origin = unified_msg_origin
                            await self._save_bot_reply_to_conversation(mock_event, content)
                        except Exception as e:
                            logger.warning(f"[主动插话] 保存回复到平台历史失败: {e}")
                        
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话回复已发送")
                    else:
                        logger.info("[主动插话] LLM判断为 false 且无内容，跳过回复与计时。")
                        
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话判断为false且无内容，跳过回复")
                else:
                    logger.warning("[主动插话] LLM返回格式异常，跳过处理。")
                    
                    # 检查是否启用详细日志
                    if self._is_detailed_logging():
                        logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话LLM返回格式异常，should_reply值: {should_reply}")
            except (json.JSONDecodeError, TypeError, AttributeError) as e:
                logger.error(f"[主动插话] 解析LLM的JSON回复失败: {e}\n清理后文本: '{json_string}'")
                
                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话JSON解析异常: {e}")
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 原始JSON字符串: {json_string}")

        except asyncio.CancelledError:
            logger.debug(f"[主动插话] 群 {group_id} 的检查任务被取消。")
        except Exception as e:
            logger.error(f"[主动插话] 群 {group_id} 的检查任务出现未知异常: {e}", exc_info=True)
        finally:
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
        group_id = event.get_group_id()
        
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
            await self._handle_immersive_session(event, session_key, session_data)
            return

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
                llm_response = await provider.text_chat(
                    prompt=event.message_str,
                    contexts=contexts,
                    system_prompt=found_persona if found_persona else None
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
            existing_texts = {msg.get('content', '') for msg in chat_context['messages'] if isinstance(msg, dict)}
            for msg in complete_history:
                if isinstance(msg, dict) and msg.get('content', '') not in existing_texts:
                    chat_context['messages'].append(msg)
        
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
        
        # 生成回复（包含读空气功能）
        if not self.response_engine:
            logger.warning("[群聊处理] response_engine未初始化，跳过处理")
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