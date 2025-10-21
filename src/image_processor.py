#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片处理模块
处理消息中的图片内容，支持直接传递和转文字两种模式
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


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
        
        # 首先检查是否启用@消息图片转文字功能，这个功能在所有图片检测和拦截前完成
        at_image_result = await self._process_at_image_caption(message_event)
        if at_image_result:
            return at_image_result
        
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
    
    def _extract_images(self, message_event) -> List[str]:
        """提取消息中的图片"""
        images = []
        
        try:
            # 获取消息链
            message_chain = message_event.get_message_chain()
            if not message_chain:
                return images
            
            # 遍历消息组件，查找图片
            for component in message_chain:
                if hasattr(component, 'type') and component.type == 'image':
                    # 获取图片URL或base64数据
                    if hasattr(component, 'url'):
                        images.append(component.url)
                    elif hasattr(component, 'data'):
                        images.append(component.data)
            
            # 记录调试信息
            if images and self._is_detailed_logging():
                logger.debug(f"提取到 {len(images)} 张图片")
                
        except Exception as e:
            logger.error(f"提取图片时发生错误: {e}")
        
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
    
    async def _process_at_image_caption(self, message_event) -> Optional[Dict[str, Any]]:
        """
        处理@消息图片转文字功能
        
        Args:
            message_event: 消息事件对象
            
        Returns:
            如果符合条件并处理成功，返回处理结果；否则返回None
        """
        # 获取@消息图片转文字配置
        image_config = self.config.get("image_processing", {})
        enable_at_image_caption = image_config.get("enable_at_image_caption", False)
        
        # 如果不启用@消息图片转文字功能，直接返回None
        if not enable_at_image_caption:
            return None
        
        # 检查消息是否包含@
        message_text = self._get_message_text(message_event)
        if not self._is_at_message(message_text, message_event):
            return None
        
        # 提取消息中的图片
        images = self._extract_images(message_event)
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
    
    async def _generate_image_caption(self, image: str, provider, prompt: str, timeout: int = 30) -> Optional[str]:
        """为单张图片生成文字描述"""
        
        # 检查缓存
        if image in self.caption_cache:
            if self._is_detailed_logging():
                logger.debug(f"命中图片描述缓存: {image[:50]}...")
            return self.caption_cache[image]
        
        try:
            # 带超时控制的调用大模型进行图片转述
            async def call_llm():
                return await provider.text_chat(
                    prompt=prompt,
                    contexts=[], 
                    image_urls=[image],
                    func_tool=None,
                    system_prompt=""
                )
            
            # 使用asyncio.wait_for添加超时控制
            llm_response = await asyncio.wait_for(call_llm(), timeout=timeout)
            caption = llm_response.completion_text
            
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
            logger.error(f"图片转述失败: {e}")
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
        检查消息是否包含@
        
        Args:
            message_text: 消息文本
            message_event: 消息事件对象
            
        Returns:
            如果消息包含@，返回True；否则返回False
        """
        # 检查消息文本中是否包含@符号
        if "@" in message_text:
            return True
        
        # 检查消息事件中是否有@信息
        try:
            # 检查是否有被@的用户列表
            if hasattr(message_event, 'get_at_users'):
                at_users = message_event.get_at_users()
                if at_users and len(at_users) > 0:
                    return True
            
            # 检查消息链中是否有@组件
            message_chain = message_event.get_message_chain()
            if message_chain:
                for component in message_chain:
                    if hasattr(component, 'type') and component.type == 'at':
                        return True
        except Exception as e:
            logger.debug(f"检查@信息时发生错误: {e}")
        
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