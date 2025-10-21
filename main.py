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
    from image_processor import ImageProcessor
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
            self.image_processor = ImageProcessor(context, config)
            self.response_engine = ResponseEngine(context, config, self.image_processor)
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
        
        logger.info("增强版群聊插件初始化完成 - 已融合沉浸式对话和主动插话功能")
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 插件初始化完成，组件数量: {len([comp for comp in [self.state_manager, self.group_list_manager, self.impression_manager, self.memory_integration, self.interaction_manager, self.image_processor, self.response_engine, self.willingness_calculator, self.focus_chat_manager, self.fatigue_system, self.context_analyzer, self.active_chat_manager] if comp is not None])}")
    
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

            context = []
            try:
                uid = event.unified_msg_origin
                curr_cid = await self.context.conversation_manager.get_curr_conversation_id(uid)
                if curr_cid:
                    conversation = await self.context.conversation_manager.get_conversation(uid, curr_cid)
                    if conversation and conversation.history:
                        context = json.loads(conversation.history)
            except Exception as e:
                logger.error(f"[沉浸式对话] 准备上下文时出错: {e}", exc_info=True)

            timeout = self.config.get("immersive_chat_timeout", 120)
            timer = asyncio.get_running_loop().call_later(
                timeout, self._clear_immersive_session, session_key
            )
            
            self.immersive_sessions[session_key] = {
                'context': context,
                'timer': timer
            }
            logger.info(f"[沉浸式对话] 已为群 {group_id} 的用户 {user_id} 开启了 {timeout}s 的沉浸式会话。")

    def _clear_immersive_session(self, session_key):
        """超时后清理沉浸式会话的回调函数"""
        if session_key in self.immersive_sessions:
            self.immersive_sessions.pop(session_key, None)
            logger.debug(f"[沉浸式对话] 会话 {session_key} 已超时并清理。")

    async def _start_proactive_check(self, group_id: str, unified_msg_origin: str):
        """启动或重置一个群组的主动插话检查任务。"""
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

    async def _proactive_check_task(self, group_id: str, unified_msg_origin: str):
        """延时任务，在指定时间后检查一次是否需要主动插话。"""
        try:
            # 检查点3：在主动插话逻辑前检查图片拦截标记
            if hasattr(self, 'current_event') and self.current_event and hasattr(self.current_event, '_should_process_message'):
                if not self.current_event._should_process_message:
                    logger.info(f"[主动插话检查] 检测到图片消息拦截标记，跳过主动插话逻辑，群组ID: {group_id}")
                    # 重置标记为True，避免影响后续处理
                    self.current_event._should_process_message = True
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

            history = await self._get_conversation_history(unified_msg_origin)
            found_persona = await self._get_persona_info_str(unified_msg_origin)

            formatted_history = "\n".join(chat_history)
            user_prompt = f"--- 最近的群聊内容 ---\n{formatted_history}\n--- 群聊内容结束 ---"
            
            instruction = (
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
                logger.warning(f"[主动插话] 从LLM回复中未能提取出JSON。原始回复: {llm_response.completion_text}")
                if llm_response.completion_text and llm_response.completion_text.strip():
                    logger.info(f"[主动插话] 使用原始回复内容: {llm_response.completion_text[:100]}...")
                    message_chain = MessageChain().message(llm_response.completion_text)
                    await self.context.send_message(unified_msg_origin, message_chain)
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
                        
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话回复已发送")
                    else:
                        logger.info("[主动插话] LLM判断为 true 但内容为空，跳过回复，继续计时。")
                        
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话判断为true但内容为空，继续计时")
                        
                        await self._start_proactive_check(group_id, unified_msg_origin)
                elif should_reply is False:
                    if content:
                        logger.info(f"[主动插话] LLM判断为 false 但仍回复，内容: {content[:50]}...")
                        
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 主动插话判断为false但仍回复，内容预览: {content[:100]}")
                        
                        message_chain = MessageChain().message(content)
                        await self.context.send_message(unified_msg_origin, message_chain)
                        
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
            await self._start_proactive_check(event.get_group_id(), event.unified_msg_origin)
        
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
        
        # 关键检查点1：在群组权限检查前检查图片拦截标记
        if not getattr(event, '_should_process_message', True):
            logger.info(f"[入口检查] 检测到图片消息拦截标记，跳过所有后续处理")
            # 重置标记为True，以便后续消息能正常处理
            event._should_process_message = True
            return
        
        # 1. 群组权限检查
        if not self.group_list_manager.check_group_permission(group_id):
            return
        
        # 2. 图片检测逻辑（在所有其他逻辑之前）
        # 获取图片处理配置
        image_config = self.config.get("image_processing", {})
        enable_image_processing = image_config.get("enable_image_processing", False)
        image_mode = image_config.get("image_mode", "ignore")
        
        # 添加详细的配置检查日志
        logger.info(f"[图片检测] 配置检查 - enable_image_processing: {enable_image_processing}, image_mode: {image_mode}")
        
        # 如果开启了忽略图片功能，检测消息中的图片标识
        if enable_image_processing and image_mode == "ignore":
            # 获取消息文本 - 使用增强的消息获取方法
            message_text = getattr(event, 'message_str', '').strip()
            if not message_text:
                # 尝试从其他属性获取消息
                try:
                    message_text = str(event.message_obj.raw_message.get("raw_message", "")).strip()
                except Exception:
                    message_text = ""
            
            # 如果仍然为空，尝试从消息对象直接获取
            if not message_text:
                try:
                    message_text = str(event.message_obj).strip()
                except Exception:
                    message_text = ""
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 图片检测逻辑开始，消息内容: '{message_text}'")
            
            # 首先检查是否是@消息，如果是@消息且启用了@消息图片转文字功能，则跳过图片拦截
            image_config = self.config.get("image_processing", {})
            enable_at_image_caption = image_config.get("enable_at_image_caption", False)
            
            # 检查消息是否包含@
            is_at_message = False
            if enable_at_image_caption:
                # 检查消息文本中是否包含@符号
                if "@" in message_text:
                    is_at_message = True
                # 检查消息事件中是否有@信息
                try:
                    if hasattr(event, 'get_at_users'):
                        at_users = event.get_at_users()
                        if at_users and len(at_users) > 0:
                            is_at_message = True
                except Exception:
                    pass
            
            if is_at_message and enable_at_image_caption:
                logger.info(f"[图片检测] 检测到@消息且启用了@消息图片转文字功能，跳过图片拦截")
                # 不进行图片拦截，让消息继续正常流程，由图片处理器处理
            else:
                # 检测消息是否包含图片标识（支持多种格式）
                is_image_message = (
                    "[图片]" in message_text or
                    "[CQ:image" in message_text or
                    any(ext in message_text for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']) or
                    "动画表情" in message_text or
                    "image" in message_text.lower()
                )
                
                if is_image_message:
                    # 检查是否启用详细日志
                    if self._is_detailed_logging():
                        logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 检测到[图片]标识")
                    
                    # 获取图片处理配置（支持嵌套配置结构）
                    image_config = self.config.get("image_processing", {})
                    enable_image_processing = image_config.get("enable_image_processing", False)
                    image_mode = image_config.get("image_mode", "ignore")
                    
                    logger.info(f"[图片检测] 图片处理配置 - 启用: {enable_image_processing}, 模式: {image_mode}")
                
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
                    
                    # 根据配置模式处理纯图片消息
                    if enable_image_processing and image_mode == "ignore":
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
                        
                        logger.info(f"[图片检测] 纯图片消息已拦截，沉浸式会话保持运行")
                        # 设置标记，让after_bot_message_sent知道这是图片消息拦截
                        event._is_image_message = True
                        # 设置消息处理标志为False，防止后续逻辑执行
                        event._should_process_message = False
                        
                        # 关键修复：完全阻止事件传播，确保AI不会被启动
                        event.stop_event()
                        return  # 直接忽略消息，不进行后续处理
                    else:
                        # 如果配置为direct或caption模式，或者图片处理未启用，则正常处理
                        logger.info(f"[图片检测] 配置模式为{image_mode}，纯图片消息将正常处理")
                        # 不进行拦截，让消息继续正常流程
            else:
                    # 如果消息包含[图片]标识和其他文字，根据配置模式处理
                    if enable_image_processing and image_mode == "ignore":
                        # 混合消息，过滤标识后继续处理
                        filtered_message = message_text.replace("[图片]", "").strip()
                        
                        # 检查是否启用详细日志
                        if self._is_detailed_logging():
                            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 消息包含[图片]标识和其他文字，过滤后消息: '{filtered_message}'")
                        
                        # 更新事件的消息文本为过滤后的内容
                        event.message_str = filtered_message
                        logger.info(f"[图片检测] 检测到包含[图片]标识的消息，已移除标识，过滤后消息: '{filtered_message[:50]}...'")
                    else:
                        # direct或caption模式，或者图片处理未启用，保持原消息不变
                        logger.info(f"[图片检测] 配置模式为{image_mode}，混合消息将正常处理")
        
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

        # --- 逻辑1: 检查是否触发了沉浸式对话 ---
        # 首先检查消息处理标志，如果为False则跳过沉浸式对话逻辑
        if not getattr(event, '_should_process_message', True):
            logger.info(f"[消息处理] 检测到图片消息拦截，跳过沉浸式对话逻辑，直接进入群聊处理")
            # 重置标志为True，以便后续消息能正常处理
            event._should_process_message = True
            return  # 关键：直接返回，不进入任何后续逻辑
        
        # 统一使用元组格式的会话键
        session_key = (event.get_group_id(), event.get_sender_id())
        async with self.immersive_lock:
            session_data = self.immersive_sessions.get(session_key)
        
        if session_data:
            logger.info(f"[沉浸式对话] 捕获到用户 {event.get_sender_id()} 的连续消息，开始判断是否回复。")
            
            # 检查是否启用详细日志
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 沉浸式对话会话存在，会话键: {session_key}")
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 会话数据: 上下文长度={len(session_data.get('context', []))}")
            
            # --- 强制图片拦截检查（在沉浸式对话判定中）---
            # 修复消息获取逻辑，确保能正确获取消息内容
            message_text = getattr(event, 'message_str', '').strip()
            if not message_text:
                # 尝试从其他属性获取消息
                try:
                    message_text = str(event.message_obj.raw_message.get("raw_message", "")).strip()
                except Exception:
                    message_text = ""
            
            # 如果仍然为空，尝试从消息对象直接获取
            if not message_text:
                try:
                    message_text = str(event.message_obj).strip()
                except Exception:
                    message_text = ""
            
            logger.info(f"[强制图片拦截] 开始检查消息: '{message_text}'")
            
            # 首先检查是否已经设置了图片拦截标记
            if getattr(event, '_should_process_message', True) is False:
                logger.info(f"[强制图片拦截] 检测到图片消息拦截标记，跳过沉浸式对话")
                # 重置标记为True，以便后续消息能正常处理
                event._should_process_message = True
                return
            
            # 首先检查是否是@消息，如果是@消息且启用了@消息图片转文字功能，则跳过图片拦截
            image_config = self.config.get("image_processing", {})
            enable_at_image_caption = image_config.get("enable_at_image_caption", False)
            
            # 检查消息是否包含@
            is_at_message = False
            if enable_at_image_caption:
                # 检查消息文本中是否包含@符号
                if "@" in message_text:
                    is_at_message = True
                # 检查消息事件中是否有@信息
                try:
                    if hasattr(event, 'get_at_users'):
                        at_users = event.get_at_users()
                        if at_users and len(at_users) > 0:
                            is_at_message = True
                except Exception:
                    pass
            
            if is_at_message and enable_at_image_caption:
                logger.info(f"[强制图片拦截] 检测到@消息且启用了@消息图片转文字功能，跳过图片拦截")
                # 不进行图片拦截，让消息继续正常流程，由图片处理器处理
            else:
                # 检测消息是否包含图片标识（支持多种格式）
                is_image_message = (
                    "[图片]" in message_text or
                    "[CQ:image" in message_text or
                    any(ext in message_text for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']) or
                    "动画表情" in message_text or
                    "image" in message_text.lower()
                )
                
                if is_image_message:
                    # 获取图片处理配置（支持嵌套配置结构）
                    image_config = self.config.get("image_processing", {})
                    enable_image_processing = image_config.get("enable_image_processing", False)
                    image_mode = image_config.get("image_mode", "ignore")
                    
                    logger.info(f"[强制图片拦截] 图片处理配置 - 启用: {enable_image_processing}, 模式: {image_mode}")
                    logger.info(f"[强制图片拦截] 完整配置检查: image_config={image_config}")
                    logger.info(f"[强制图片拦截] 拦截条件: enable_image_processing={enable_image_processing}, image_mode={image_mode}, 条件结果={enable_image_processing and image_mode == 'ignore'}")
                    
                    stripped_message = message_text.strip()
                    
                    # 检测纯图片消息（支持多种图片格式）
                    # 纯图片消息的判断标准：消息只包含图片标识，没有其他有效文本内容
                    is_pure_image = False
                    
                    # 如果是CQ码图片消息，直接判定为纯图片
                    if "[CQ:image" in stripped_message:
                        is_pure_image = True
                        logger.info(f"[强制图片拦截] 检测到CQ码图片消息，判定为纯图片")
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
                            logger.info(f"[强制图片拦截] 检测到图片文件消息，判定为纯图片")
                    # 如果是动画表情
                    elif "动画表情" in stripped_message:
                        is_pure_image = True
                        logger.info(f"[强制图片拦截] 检测到动画表情，判定为纯图片")
                    
                    logger.info(f"[强制图片拦截] 消息检测: stripped_message='{stripped_message}', is_pure_image={is_pure_image}")
                    logger.info(f"[强制图片拦截] 检测条件1: stripped_message == '[图片]' = {stripped_message == '[图片]'}")
                    logger.info(f"[强制图片拦截] 检测条件2: starts_with_and_empty_after = {stripped_message.startswith('[图片]') and len(stripped_message.replace('[图片]', '').strip()) == 0}")
                    
                    if is_pure_image:
                        # 只有在ignore模式下才拦截纯图片消息
                        if enable_image_processing and image_mode == "ignore":
                            logger.info(f"[强制图片拦截] 检测到纯图片消息: '{message_text}'，强制判定为不回复")
                            
                            # 重置定时器，保持沉浸式对话继续有效
                            async with self.immersive_lock:
                                if session_key in self.immersive_sessions:
                                    session_data = self.immersive_sessions[session_key]
                                    if session_data.get('timer'):
                                        session_data['timer'].cancel()
                                        logger.info(f"[强制图片拦截] 已取消当前定时器: {session_key}")
                                    
                                    # 使用配置中的沉浸式对话超时秒数
                                    timeout_seconds = self.config.get("immersive_chat_timeout", 120)
                                    
                                    # 重新启动定时器，保持沉浸式对话有效
                                    session_data['timer'] = asyncio.get_running_loop().call_later(
                                        timeout_seconds, 
                                        self._clear_immersive_session, 
                                        session_key
                                    )
                                    logger.info(f"[强制图片拦截] 已重新启动{timeout_seconds}秒定时器: {session_key}")
                            
                            logger.info(f"[强制图片拦截] 纯图片消息已强制拦截，沉浸式会话保持运行，AI不会回复")
                            return  # 直接返回，不进行LLM判定
                        else:
                            # direct或caption模式，或者图片处理未启用，则正常处理
                            logger.info(f"[强制图片拦截] 配置模式为{image_mode}，纯图片消息将正常处理")
                    else:
                        # 混合消息，根据配置模式处理
                        if enable_image_processing and image_mode == "ignore":
                            # 混合消息，过滤标识后继续处理
                            filtered_message = message_text.replace("[图片]", "").strip()
                            event.message_str = filtered_message
                            logger.info(f"[强制图片拦截] 混合消息，过滤后: '{filtered_message}'，继续沉浸式对话判定")
                        else:
                            # direct或caption模式，或者图片处理未启用，保持原消息不变
                            logger.info(f"[强制图片拦截] 配置模式为{image_mode}，混合消息将正常处理")
            
            # 因为要进行沉浸式回复，所以取消可能存在的、针对全群的主动插话任务
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
                
                saved_context = session_data.get('context', [])
                user_prompt = event.message_str
                instruction = (
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
        
                provider = self.context.get_using_provider()
                if not provider:
                    logger.warning("[沉浸式对话] 未找到可用的大语言模型提供商。")
                    return

                # 检查是否启用详细日志
                if self._is_detailed_logging():
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 开始调用LLM进行沉浸式对话决策")
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 用户提示长度: {len(user_prompt)}")
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 上下文数量: {len(saved_context)}")
                    logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 系统提示长度: {len(instruction)}")

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
                    logger.warning(f"[沉浸式对话] 从LLM回复中未能提取出JSON。原始回复: {llm_response.completion_text}")
                    if llm_response.completion_text and llm_response.completion_text.strip():
                        logger.info(f"[沉浸式对话] 使用原始回复内容: {llm_response.completion_text[:100]}...")
                        message_chain = MessageChain().message(llm_response.completion_text)
                        await self.context.send_message(event.unified_msg_origin, message_chain)
                    return
                
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

                return

        # --- 逻辑2: 处理群聊插件的原有逻辑 ---
        # 关键检查点2：在群聊处理逻辑前检查图片拦截标记
        if not getattr(event, '_should_process_message', True):
            logger.info(f"[群聊检查] 检测到图片消息拦截标记，跳过群聊处理逻辑")
            # 重置标记为True，以便后续消息能正常处理
            event._should_process_message = True
            return
        
        # 记录会话标识并确保该群心跳存在
        self.state_manager.set_group_umo(group_id, event.unified_msg_origin)
        self.active_chat_manager.ensure_flow(group_id)
        # 将消息传递给 ActiveChatManager 以进行频率分析
        if group_id in self.active_chat_manager.group_flows:
            self.active_chat_manager.group_flows[group_id].on_message(event)
        
        # 处理消息
        async for result in self._process_group_message(event):
            yield result

        # --- 逻辑3: 收集消息用于主动插话 ---
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
        
        # 获取聊天上下文
        chat_context = await self.context_analyzer.analyze_chat_context(event)
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 聊天上下文分析完成，消息数量: {len(chat_context.get('messages', []))}")
        
        # 判断交互模式
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
        consecutive_count = self.state_manager.get_consecutive_responses().get(group_id, 0)
        if consecutive_count >= max_consecutive:
            if self._is_detailed_logging():
                logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 连续回复限制已达上限 ({consecutive_count}/{max_consecutive})，跳过回复")
            return
        
        # 检查是否启用详细日志
        if self._is_detailed_logging():
            logger.debug(f"GroupChatPluginEnhanced: 详细日志 - 当前连续回复计数: {consecutive_count}/{max_consecutive}")
        
        # 生成回复（包含读空气功能）
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

                # 更新连续回复计数
                self.state_manager.increment_consecutive_response(group_id)

                # 心流算法：回复成功后更新状态
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
        chat_context = await self.context_analyzer.analyze_chat_context(event)
        will_res = await self.willingness_calculator.calculate_response_willingness(event, chat_context)
        willingness_score = float(will_res.get("willingness_score", 0.0) or 0.0)
        decision_ctx = will_res.get("decision_context", {}) or {}
        group_activity = float(decision_ctx.get("group_activity", 0.0) or 0.0)

        # 评估专注兴趣度
        try:
            interest = float(await self.focus_chat_manager.evaluate_focus_interest(event, chat_context))
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

    async def terminate(self):
        """插件终止时的清理工作"""
        logger.info("增强版群聊插件正在终止...")
        # 停止主动聊天管理器
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
        self.state_manager.clear_all_state()
        logger.info("增强版群聊插件已终止")