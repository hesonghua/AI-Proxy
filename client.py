"""供应商客户端模块"""
import asyncio
import httpx
import json
import logging
from typing import List, Dict, Any, Optional
from config import Provider

# 获取logger
logger = logging.getLogger(__name__)


class ProviderClient:
    """供应商客户端"""
    
    def __init__(self, provider: Provider):
        self.provider = provider
        # 检查URL是否已经包含完整的API路径
        if provider.url.endswith('/chat/completions'):
            # 如果URL已经包含完整路径，直接使用
            base_url = provider.url.rstrip('/')
            self.chat_endpoint = ""
        else:
            # 标准OpenAI兼容API
            base_url = provider.url.rstrip('/')
            self.chat_endpoint = "/chat/completions"
            
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )
        logger.info(f"初始化供应商客户端: {provider.name}, base_url: {base_url}, chat_endpoint: {self.chat_endpoint}")
    
    async def get_models(self) -> List[Dict[str, Any]]:
        """获取供应商支持的模型列表"""
        try:
            logger.info(f"开始获取供应商 {self.provider.name} 的模型列表")
            response = await self.client.get("/models")
            response.raise_for_status()
            data = response.json()
            
            # 标准化模型数据格式
            models = []
            if "data" in data:
                for model in data["data"]:
                    # 添加供应商前缀到模型ID
                    model_id = f"{self.provider.name}/{model.get('id', model.get('model', ''))}"
                    models.append({
                        "id": model_id,
                        "object": model.get("object", "model"),
                        "created": model.get("created"),
                        "owned_by": self.provider.name
                    })
            
            logger.info(f"成功获取供应商 {self.provider.name} 的 {len(models)} 个模型")
            return models
            
        except Exception as e:
            logger.error(f"获取供应商 {self.provider.name} 模型失败: {e}")
            return []
    
    async def chat_completion(self, model: str, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """发送聊天完成请求"""
        try:
            # 解析模型名称，提取实际的模型ID
            if "/" in model:
                _, actual_model = model.split("/", 1)
            else:
                actual_model = model
            
            logger.info(f"向供应商 {self.provider.name} 发送聊天请求，模型: {actual_model}, 消息数: {len(messages)}")
            
            # 构建请求数据
            data = {
                "model": actual_model,
                "messages": messages,
                **kwargs
            }
            
            logger.debug(f"请求数据: {data}")
            
            response = await self.client.post(self.chat_endpoint, json=data)
            response.raise_for_status()
            
            # 检查响应类型，处理流式和非流式响应
            content_type = response.headers.get('content-type', '')
            
            if 'text/event-stream' in content_type:
                # 处理流式响应 (Server-Sent Events)
                logger.info(f"供应商 {self.provider.name} 返回流式响应")
                
                # 返回原始流式数据供API层处理
                result = {
                    "stream_response": response.text
                }
            else:
                # 处理非流式响应
                result = response.json()
                
                # 在响应中返回完整的模型名称
                if "model" in result:
                    result["model"] = model
            
            logger.info(f"供应商 {self.provider.name} 响应成功")
            return result
            
        except httpx.HTTPStatusError as e:
            logger.error(f"供应商 {self.provider.name} HTTP错误: {e.response.status_code} - {e.response.text}")
            return {
                "error": {
                    "message": f"供应商 {self.provider.name} 请求失败: HTTP {e.response.status_code}",
                    "type": "provider_error",
                    "code": "provider_request_failed"
                }
            }
        except Exception as e:
            logger.error(f"供应商 {self.provider.name} 请求异常: {str(e)}")
            return {
                "error": {
                    "message": f"请求供应商 {self.provider.name} 失败: {str(e)}",
                    "type": "provider_error",
                    "code": "provider_request_failed"
                }
            }
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            logger.debug(f"检查供应商 {self.provider.name} 健康状态")
            response = await self.client.get("/models")
            is_healthy = response.status_code == 200
            logger.debug(f"供应商 {self.provider.name} 健康状态: {'健康' if is_healthy else '异常'}")
            return is_healthy
        except Exception as e:
            logger.warning(f"供应商 {self.provider.name} 健康检查失败: {e}")
            return False
    
    async def close(self):
        """关闭客户端连接"""
        logger.info(f"关闭供应商 {self.provider.name} 客户端连接")
        await self.client.aclose()


class ModelManager:
    """模型管理器"""
    
    def __init__(self, providers: List[Provider]):
        self.providers = providers
        self.clients = {p.name: ProviderClient(p) for p in providers}
        self._models_cache: Optional[List[Dict[str, Any]]] = None
        logger.info(f"初始化模型管理器，供应商数量: {len(providers)}")
    
    async def get_all_models(self) -> List[Dict[str, Any]]:
        """获取所有供应商的模型列表"""
        if self._models_cache is not None:
            logger.debug("使用缓存的模型列表")
            return self._models_cache
        
        logger.info("开始获取所有供应商的模型列表")
        all_models = []
        tasks = []
        
        for client in self.clients.values():
            tasks.append(client.get_models())
        
        # 并发获取所有供应商的模型
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, list):
                all_models.extend(result)
                logger.debug(f"供应商 {list(self.clients.keys())[i]} 返回 {len(result)} 个模型")
            else:
                logger.warning(f"供应商 {list(self.clients.keys())[i]} 获取模型失败: {result}")
        
        self._models_cache = all_models
        logger.info(f"成功获取 {len(all_models)} 个模型")
        return all_models
    
    def get_provider_client(self, model: str) -> Optional[ProviderClient]:
        """根据模型名称获取对应的供应商客户端"""
        if "/" in model:
            provider_name, actual_model = model.split("/", 1)
            client = self.clients.get(provider_name)
            if client:
                logger.debug(f"找到模型 {model} 对应的供应商: {provider_name}")
            else:
                logger.warning(f"未找到模型 {model} 对应的供应商: {provider_name}")
            return client
        else:
            logger.warning(f"模型名称格式错误，缺少供应商前缀: {model}")
        return None
    
    async def chat_completion(self, model: str, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """发送聊天完成请求"""
        logger.info(f"处理聊天完成请求，模型: {model}, 消息数: {len(messages)}")
        
        client = self.get_provider_client(model)
        if not client:
            logger.error(f"未找到模型 {model} 对应的供应商")
            return {
                "error": {
                    "message": f"未找到模型 {model} 对应的供应商",
                    "type": "model_not_found",
                    "code": "model_not_found"
                }
            }
        
        result = await client.chat_completion(model, messages, **kwargs)
        
        if "error" in result:
            logger.error(f"聊天完成请求失败: {result['error']['message']}")
        else:
            logger.info(f"聊天完成请求成功")
            
        return result
    
    async def health_check(self) -> Dict[str, bool]:
        """检查所有供应商的健康状态"""
        logger.info("开始健康检查")
        health_status = {}
        tasks = []
        
        for name, client in self.clients.items():
            tasks.append((name, client.health_check()))
        
        for name, task in tasks:
            try:
                health_status[name] = await task
            except Exception as e:
                logger.error(f"供应商 {name} 健康检查异常: {e}")
                health_status[name] = False
        
        healthy_count = sum(1 for status in health_status.values() if status)
        logger.info(f"健康检查完成，健康供应商: {healthy_count}/{len(health_status)}")
        return health_status
    
    def clear_cache(self):
        """清除模型缓存"""
        logger.info("清除模型缓存")
        self._models_cache = None
    
    async def close_all(self):
        """关闭所有客户端连接"""
        logger.info("关闭所有供应商客户端连接")
        for client in self.clients.values():
            await client.close()
