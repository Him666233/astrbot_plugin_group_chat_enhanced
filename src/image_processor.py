#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片处理模块
处理消息中的图片内容，支持直接传递和转文字两种模式

版本: 2.0.3
作者: Him666233
"""

__version__ = "2.0.3"
__author__ = "Him666233"
__description__ = "图片处理模块：处理消息中的图片内容"

import asyncio
import re
from typing import List, Optional, Dict, Any

from astrbot.api import logger


class ImageProcessor:
    """图片处理器"""
    
    def __init__(self, context, config):
        self.context = context
        self.config = config
        self.caption_cache = {}
    
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
    
    def _extract_images(self, message_event) -> List[str]:
        """提取消息中的图片"""
        images = []
        
        try:
            # 获取消息链
            message_chain = message_event.get_message_chain()
            if message_chain:
                # 遍历消息组件，查找图片组件
                for component in message_chain:
                    if hasattr(component, 'type') and component.type == 'image':
                        # 获取图片URL或base64数据
                        if hasattr(component, 'url'):
                            images.append(component.url)
                        elif hasattr(component, 'data'):
                            images.append(component.data)
            
            # 如果从消息链中没有提取到图片，尝试从消息文本中提取CQ码图片
            if not images:
                # 直接获取原始消息文本，而不是使用过滤后的文本
                try:
                    # 尝试获取原始消息字符串 - 优先使用可能存在的原始消息属性
                    message_text = None
                    
                    # 方法1：尝试获取原始消息属性
                    if hasattr(message_event, 'original_message_str'):
                        message_text = message_event.original_message_str
                    elif hasattr(message_event, 'raw_message_str'):
                        message_text = message_event.raw_message_str
                    elif hasattr(message_event, 'get_original_message'):
                        message_text = message_event.get_original_message()
                    
                    # 方法2：如果无法获取原始消息，尝试从消息链重建原始消息
                    if not message_text:
                        message_chain = message_event.get_message_chain()
                        if message_chain:
                            # 重建包含所有组件的原始消息
                            message_parts = []
                            for component in message_chain:
                                if hasattr(component, 'type'):
                                    if component.type == 'text' and hasattr(component, 'text'):
                                        message_parts.append(component.text)
                                    elif component.type == 'image':
                                        # 重建CQ码图片格式
                                        cq_image = '[CQ:image'
                                        if hasattr(component, 'url'):
                                            cq_image += f',url={component.url}'
                                        if hasattr(component, 'file'):
                                            cq_image += f',file={component.file}'
                                        cq_image += ']'
                                        message_parts.append(cq_image)
                                    elif component.type == 'at' and hasattr(component, 'target'):
                                        message_parts.append(f'[CQ:at,qq={component.target}]')
                            
                            if message_parts:
                                message_text = ''.join(message_parts)
                    
                    # 方法3：如果都失败，直接使用message_str（可能包含CQ码）
                    if not message_text:
                        if hasattr(message_event, 'message_str'):
                            message_text = message_event.message_str
                        else:
                            message_text = self._get_message_text(message_event)
                    
                    if message_text and '[CQ:image' in message_text:
                        # 使用正则表达式提取CQ码图片的URL
                        import re
                        
                        # 记录原始消息文本用于调试
                        logger.debug(f"CQ码图片提取 - 原始消息文本: {message_text}")
                        
                        # 方法1：匹配完整的CQ码图片格式
                        cq_pattern = r'\[CQ:image,([^\]]+)\]'
                        cq_matches = re.findall(cq_pattern, message_text)
                        
                        for cq_params in cq_matches:
                            # 从CQ码参数中提取URL
                            url_match = re.search(r'url=([^,\]]+)', cq_params)
                            if url_match:
                                url = url_match.group(1).strip()
                                if url and not url.endswith('...'):  # 避免截断的URL
                                    images.append(url)
                                    logger.debug(f"从完整CQ码提取到URL: {url}")
                            
                            # 如果URL提取失败，提取file参数
                            if not images:
                                file_match = re.search(r'file=([^,\]]+)', cq_params)
                                if file_match:
                                    file_name = file_match.group(1).strip()
                                    if file_name:
                                        # 构建可能的图片URL
                                        images.append(f"file://{file_name}")
                                        logger.debug(f"从完整CQ码提取到file: {file_name}")
                        
                        # 方法2：如果方法1失败，尝试直接匹配URL和file参数（处理截断情况）
                        if not images:
                            # 匹配CQ码图片的URL（处理截断情况）
                            url_pattern = r'url=([^,\]]+)'
                            matches = re.findall(url_pattern, message_text)
                            for url in matches:
                                if url and url.strip() and not url.endswith('...'):
                                    images.append(url.strip())
                                    logger.debug(f"直接提取到URL: {url}")
                            
                            # 如果没有提取到URL，尝试提取file参数
                            if not images:
                                file_pattern = r'file=([^,\]]+)'
                                file_matches = re.findall(file_pattern, message_text)
                                for file_name in file_matches:
                                    if file_name and file_name.strip():
                                        # 构建可能的图片URL
                                        images.append(f"file://{file_name.strip()}")
                                        logger.debug(f"直接提取到file: {file_name}")
                        
                        # 方法3：如果仍然失败，尝试从消息链中提取图片组件
                        if not images:
                            try:
                                message_chain = message_event.get_message_chain()
                                if message_chain:
                                    for component in message_chain:
                                        if hasattr(component, 'type') and component.type == 'image':
                                            if hasattr(component, 'url') and component.url:
                                                images.append(component.url)
                                                logger.debug(f"从消息链组件提取到URL: {component.url}")
                                            elif hasattr(component, 'file') and component.file:
                                                images.append(f"file://{component.file}")
                                                logger.debug(f"从消息链组件提取到file: {component.file}")
                            except Exception as e:
                                logger.debug(f"从消息链提取图片组件失败: {e}")
                except Exception as e:
                    logger.error(f"获取原始消息文本时出错: {e}", exc_info=True)
            
            # 记录调试信息
            if images:
                logger.info(f"提取到 {len(images)} 张图片: {images}")
            else:
                logger.debug("未提取到任何图片")
                
        except Exception as e:
            logger.error(f"提取图片时发生错误: {e}", exc_info=True)
        
        return images
    
    async def _process_direct_mode(self, images: List[str], message_event) -> Dict[str, Any]:
        """直接传递图片模式"""
        if self._is_detailed_logging():
            logger.debug("使用直接传递图片模式")
        
        return {
            "images": images,
            "captions": [],
            "has_images": True,
            "filtered_message": self._get_message_text(message_event)
        }
    
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
        
            # 检查消息是否包含@
            message_text = self._get_message_text(message_event)
            logger.info(f"[_detect_and_caption_at_images] 检查消息文本: '{message_text}'")
            
            is_at = self._is_at_message(message_text, message_event)
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
            
            # 为每张图片生成描述，参考astrbot_plugin_context_enhancer-main的实现
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
    
    async def _intercept_other_images(self, message_event) -> Dict[str, Any]:
        """
        其他消息图片拦截函数
        
        Args:
            message_event: 消息事件对象
            
        Returns:
            处理结果字典，包含图片处理信息
        """
        # 获取图片处理配置
        image_config = self.config.get("image_processing", {})
        enable_image_processing = image_config.get("enable_image_processing", False)
        image_mode = image_config.get("image_mode", "ignore")
        
        # 如果不启用图片处理，直接返回空结果
        if not enable_image_processing or image_mode == "ignore":
            return {
                "images": [],
                "captions": [],
                "has_images": False,
                "filtered_message": self._get_message_text(message_event)
            }
        
        # 提取消息中的图片
        images = self._extract_images(message_event)
        
        if not images:
            return {
                "images": [],
                "captions": [],
                "has_images": False,
                "filtered_message": self._get_message_text(message_event)
            }
        
        # 根据模式处理图片
        if image_mode == "direct":
            # 直接传递图片模式
            return await self._process_direct_mode(images, message_event)
        elif image_mode == "caption":
            # 图片转文字模式
            return await self._process_caption_mode(images, message_event)
        else:
            # 忽略模式
            return {
                "images": [],
                "captions": [],
                "has_images": False,
                "filtered_message": self._get_message_text(message_event)
            }
    
    async def _process_caption_mode(self, images: List[str], message_event) -> Dict[str, Any]:
        """图片转文字模式"""
        if self._is_detailed_logging():
            logger.debug("使用图片转文字模式")
        
        captions = []
        
        # 获取图片转文字配置
        image_config = self.config.get("image_processing", {})
        provider_id = image_config.get("image_caption_provider_id", "")
        prompt = image_config.get("image_caption_prompt", "请直接简短描述这张图片")
        
        # 获取服务提供商
        if provider_id:
            provider = self.context.get_provider_by_id(provider_id)
        else:
            provider = self.context.get_using_provider()
        
        if not provider:
            logger.warning("无法找到图片转文字服务提供商")
            return {
                "images": [],
                "captions": [],
                "has_images": False,
                "filtered_message": self._get_message_text(message_event)
            }
        
        # 为每张图片生成描述
        for image in images:
            caption = await self._generate_image_caption(image, provider, prompt)
            if caption:
                captions.append(caption)
        
        return {
            "images": [],
            "captions": captions,
            "has_images": len(captions) > 0,
            "filtered_message": self._get_message_text(message_event)
        }
    
    async def caption_images(self, images: List[str]) -> Optional[str]:
        """
        手动识别图片内容
        
        Args:
            images: 图片URL或base64数据列表
            
        Returns:
            图片描述文本，失败时返回None
        """
        if not images:
            logger.warning("[手动识别] 图片列表为空")
            return None
        
        try:
            # 获取图片转文字配置
            image_config = self.config.get("image_processing", {})
            provider_id = image_config.get("image_caption_provider_id", "")
            prompt = image_config.get("image_caption_prompt", "请直接简短描述这张图片")
            
            # 获取服务提供商
            if provider_id:
                provider = self.context.get_provider_by_id(provider_id)
            else:
                provider = self.context.get_using_provider()
            
            if not provider:
                logger.warning("[手动识别] 无法找到图片转文字服务提供商")
                return None
            
            logger.info(f"[手动识别] 开始处理 {len(images)} 张图片")
            
            # 为每张图片生成描述
            captions = []
            for i, image in enumerate(images):
                logger.info(f"[手动识别] 处理第 {i+1} 张图片")
                caption = await self._generate_image_caption(image, provider, prompt)
                if caption:
                    captions.append(caption)
                else:
                    logger.warning(f"[手动识别] 第 {i+1} 张图片识别失败")
            
            if not captions:
                logger.warning("[手动识别] 所有图片识别失败")
                return None
            
            # 合并所有图片描述
            result = "，".join(captions)
            logger.info(f"[手动识别] 识别成功，结果: {result}")
            return result
            
        except Exception as e:
            logger.error(f"[手动识别] 图片识别过程中出错: {e}", exc_info=True)
            return None
    
    
    async def _generate_image_caption(self, image: str, provider, prompt: str, timeout: int = 30) -> Optional[str]:
        """
        图片转文字描述函数，参考astrbot_plugin_context_enhancer-main实现
        
        Args:
            image: 图片URL或base64数据
            provider: LLM服务提供商
            prompt: 提示词
            timeout: 超时时间
            
        Returns:
            图片描述文本，失败时返回None
        """
        # 检查缓存
        if image in self.caption_cache:
            if self._is_detailed_logging():
                logger.debug(f"命中图片描述缓存: {image[:50]}...")
            return self.caption_cache[image]
        
        try:
            # ✅ 关键修复：参考astrbot_plugin_context_enhancer-main的正确实现
            # 使用正确的参数格式，避免参数错误
            logger.info(f"[图片转文字] 开始调用LLM进行图片描述，图片URL: {image[:100]}...")
            logger.info(f"[图片转文字] 使用提示词: {prompt}")
            
            # 正确的调用方式：直接传递prompt和image_urls，不需要其他参数
            llm_response = await asyncio.wait_for(
                provider.text_chat(prompt=prompt, image_urls=[image]),
                timeout=timeout
            )
            
            caption = llm_response.completion_text
            
            logger.info(f"[图片转文字] LLM返回结果: {caption}")
            
            # 缓存结果
            if caption:
                self.caption_cache[image] = caption
                if self._is_detailed_logging():
                    logger.debug(f"缓存图片描述: {image[:50]}... -> {caption}")
            
            return caption
            
        except asyncio.TimeoutError:
            logger.warning(f"图片转述超时，超过了{timeout}秒")
            return None
        except Exception as e:
            logger.error(f"图片转述失败: {e}", exc_info=True)
            return None
    
    def _get_message_text(self, message_event) -> str:
        """获取消息文本，过滤掉图片标识符"""
        try:
            # 获取消息概要（通常已经过滤了图片等非文本内容）
            message_outline = message_event.get_message_outline()
            if message_outline:
                return message_outline.strip()
            
            # 如果无法获取消息概要，尝试从消息链中提取文本
            message_chain = message_event.get_message_chain()
            if not message_chain:
                return ""
            
            # 提取文本内容，过滤掉图片
            text_parts = []
            for component in message_chain:
                if hasattr(component, 'type') and component.type == 'text':
                    if hasattr(component, 'text'):
                        text_parts.append(component.text)
            
            return "".join(text_parts).strip()
            
        except Exception as e:
            logger.error(f"获取消息文本时发生错误: {e}")
            return ""
    
    def _is_at_message(self, message_text: str, message_event) -> bool:
        """
        检查消息是否为@消息（严格检测，确保真的@了机器人）
        
        Args:
            message_text: 消息文本
            message_event: 消息事件对象
            
        Returns:
            如果消息包含@机器人QQ号，返回True；否则返回False
        """
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
            elif "[At:" in message_text:
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
                    at_pattern = r'@[^\s\p{P}\d]'  # @后面跟着非空格、非标点、非数字的字符
                    if re.search(at_pattern, message_text):
                        logger.debug("[严格@检测] 检测到有效的@消息格式，但无法确定是否@机器人")
                        # 对于无法确定QQ号的@消息，默认返回False，避免误判
                        return False
                    else:
                        logger.debug("[严格@检测] @符号后无有效内容，可能是误判")
        
        logger.debug("[严格@检测] 未检测到有效的@机器人消息")
        return False
    
    def _combine_captions_with_message(self, message_text: str, captions: List[str]) -> str:
        """
        合并图片描述和原消息
        
        Args:
            message_text: 原消息文本
            captions: 图片描述列表
            
        Returns:
            合并后的消息文本
        """
        if not captions:
            return message_text
        
        # 构建图片描述文本
        caption_text = "图片描述："
        for i, caption in enumerate(captions):
            caption_text += f"\n第{i+1}张图片：{caption}"
        
        # 合并原消息和图片描述
        if message_text.strip():
            return f"{message_text}\n\n{caption_text}"
        else:
            return caption_text
    
    def _is_detailed_logging(self) -> bool:
        """检查是否启用详细日志"""
        # 首先检查顶层的enable_detailed_logging开关
        if self.config.get("enable_detailed_logging", False):
            return True
        # 然后检查图片处理配置中的开关
        image_config = self.config.get("image_processing", {})
        return image_config.get("enable_detailed_logging", False)
    
    def clear_cache(self):
        """清空图片描述缓存"""
        self.caption_cache.clear()
        if self._is_detailed_logging():
            logger.debug("已清空图片描述缓存")