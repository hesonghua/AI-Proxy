"""供应商客户端模块"""
import asyncio
import httpx
import json
import logging
import time
from typing import List, Dict, Any, Optional
from config import Provider

# 获取logger
logger = logging.getLogger(__name__)


class ProviderClient:
    """供应商客户端"""
    
    @staticmethod
    def parse_model_name(model: str) -> tuple:
        """解析模型名称，返回(供应商名称, 实际模型名)
        
        Args:
            model: 模型名称，格式为 "供应商/模型" 或 "模型"
            
        Returns:
            (供应商名称, 实际模型名) 元组
        """
        if "/" in model:
            parts = model.split("/", 1)
            return parts[0], parts[1]
        return "", model
    
    def _create_error_response(self, message: str, error_type: str = "provider_error") -> dict:
        """创建统一的错误响应
        
        Args:
            message: 错误消息
            error_type: 错误类型
            
        Returns:
            标准错误响应字典
        """
        return {
            "error": {
                "message": f"供应商 {self.provider.name}: {message}",
                "type": error_type,
                "code": "provider_request_failed"
            }
        }
    
    def __init__(self, provider: Provider, config=None):
        self.provider = provider
        self.config = config
        self._models_cache: Optional[List[Dict[str, Any]]] = None  # 模型缓存
        self._last_fetch_time: Optional[float] = None  # 上次获取时间
        self._fetch_failed: bool = False  # 是否获取失败
        
        # 检查URL是否已经包含完整的API路径
        if provider.url.endswith('/chat/completions'):
            # 如果URL已经包含完整路径，直接使用
            base_url = provider.url.rstrip('/')
            self.chat_endpoint = ""
        else:
            # 标准OpenAI兼容API
            base_url = provider.url.rstrip('/')
            self.chat_endpoint = "/chat/completions"
        
        # 从配置获取超时和连接池参数
        stream_timeout = config.stream_timeout if config else 300.0
        non_stream_timeout = config.non_stream_timeout if config else 30.0
        max_connections = config.max_connections if config else 100
        max_keepalive = config.max_keepalive_connections if config else 20
        keepalive_expiry = config.keepalive_expiry if config else 30.0
        
        # 为流式请求使用更长的超时时间
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json"
            },
            timeout=httpx.Timeout(
                connect=10.0,  # 连接超时
                read=stream_timeout,  # 读取超时（从配置读取）
                write=10.0,    # 写入超时
                pool=10.0      # 连接池超时
            ),
            limits=httpx.Limits(
                max_keepalive_connections=max_keepalive,  # 从配置读取
                max_connections=max_connections,           # 从配置读取
                keepalive_expiry=keepalive_expiry          # 从配置读取
            )
        )
        logger.info(f"初始化供应商客户端: {provider.name}, base_url: {base_url}, "
                   f"chat_endpoint: {self.chat_endpoint}, "
                   f"stream_timeout: {stream_timeout}s, non_stream_timeout: {non_stream_timeout}s")
    
    async def get_models(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """获取供应商支持的模型列表
        
        Args:
            force_refresh: 是否强制刷新，默认False
            
        Returns:
            模型列表
        """
        import time
        current_time = time.time()
        
        # 如果有缓存且不强制刷新
        if not force_refresh and self._models_cache is not None:
            # 如果之前获取失败，且距离上次尝试超过10秒，重新尝试
            if self._fetch_failed and self._last_fetch_time:
                time_since_last = current_time - self._last_fetch_time
                if time_since_last > 10:
                    logger.info(f"供应商 {self.provider.name} 上次获取失败，10秒后重试...")
                    # 继续执行获取逻辑
                else:
                    # 返回缓存（可能为空）
                    logger.debug(f"供应商 {self.provider.name} 使用缓存 (失败状态，等待重试)")
                    return self._models_cache
            else:
                # 成功状态，直接返回缓存
                logger.debug(f"供应商 {self.provider.name} 使用缓存的模型列表")
                return self._models_cache
        
        # 执行获取逻辑（带重试）
        models = await self._fetch_models_with_retry()
        
        # 更新缓存和状态
        self._models_cache = models
        self._last_fetch_time = current_time
        self._fetch_failed = (len(models) == 0)
        
        return models
    
    async def _fetch_models_with_retry(self, max_retries: int = 3) -> List[Dict[str, Any]]:
        """从供应商获取模型列表（带重试）
        
        Args:
            max_retries: 最大重试次数
            
        Returns:
            模型列表，失败返回空列表
        """
        for attempt in range(max_retries):
            response = None
            try:
                if attempt > 0:
                    # 重试前等待，使用指数退避
                    wait_time = min(2 ** attempt, 10)
                    logger.info(f"供应商 {self.provider.name} 第 {attempt + 1}/{max_retries} 次重试，等待 {wait_time} 秒...")
                    await asyncio.sleep(wait_time)
                
                logger.info(f"开始获取供应商 {self.provider.name} 的模型列表 (尝试 {attempt + 1}/{max_retries})")
                
                # 使用较短的超时时间获取模型列表
                response = await self.client.get("/models", timeout=15.0)
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
                
            except httpx.TimeoutException as e:
                logger.warning(f"获取供应商 {self.provider.name} 模型超时 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    logger.error(f"获取供应商 {self.provider.name} 模型失败：超过最大重试次数")
            except httpx.NetworkError as e:
                logger.warning(f"获取供应商 {self.provider.name} 模型网络错误 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    logger.error(f"获取供应商 {self.provider.name} 模型失败：网络错误")
            except Exception as e:
                logger.warning(f"获取供应商 {self.provider.name} 模型失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    logger.error(f"获取供应商 {self.provider.name} 模型失败：{e}")
            finally:
                # 确保响应被关闭
                if response:
                    try:
                        await response.aclose()
                    except:
                        pass
        
        # 所有重试都失败，返回空列表
        return []
    
    async def chat_completion(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """发送聊天完成请求 - 接受完整的请求体字典"""
        response = None
        start_time = time.time()
        is_stream_response = False  # 标记是否为流式响应
        
        try:
            model = body.get("model")
            messages = body.get("messages")
            
            if not model or not messages:
                return {
                    "error": {
                        "message": "缺少必需参数: model 或 messages",
                        "type": "invalid_request",
                        "code": "invalid_request"
                    }
                }
            
            # 解析模型名称，提取实际的模型ID
            _, actual_model = self.parse_model_name(model)
            
            logger.info(f"向供应商 {self.provider.name} 发送聊天请求，模型: {actual_model}, 消息数: {len(messages)}")
            
            # 构造要发送给上游的请求体：原样保留所有参数，仅替换 model 字段
            data = dict(body)
            data["model"] = actual_model
            
            logger.debug(f"请求数据: {json.dumps(data, ensure_ascii=False)}")
            
            # 检查是否为流式请求
            is_stream = body.get('stream', False)
            
            # 根据是否流式选择不同的请求方式
            if is_stream:
                # 流式请求：使用stream=True
                request = self.client.build_request('POST', self.chat_endpoint, json=data)
                response = await self.client.send(request, stream=True)
            else:
                # 非流式请求：直接发送，不使用stream模式
                response = await self.client.post(self.chat_endpoint, json=data)
            
            response.raise_for_status()
            
            # 检查响应类型，处理流式和非流式响应
            content_type = response.headers.get('content-type', '')
            
            if 'text/event-stream' in content_type or is_stream:
                # 处理流式响应 (Server-Sent Events)
                logger.info(f"供应商 {self.provider.name} 返回流式响应")
                is_stream_response = True  # 标记为流式响应
                
                # 创建真正的流式生成器
                async def stream_generator():
                    """流式生成器，确保资源正确释放"""
                    try:
                        async for chunk in response.aiter_text():
                            yield chunk
                    except asyncio.CancelledError:
                        logger.warning(f"供应商 {self.provider.name} 流式请求被取消")
                        raise
                    except Exception as e:
                        logger.error(f"供应商 {self.provider.name} 流式响应错误: {str(e)}")
                        raise
                    finally:
                        # 确保响应被正确关闭
                        try:
                            await response.aclose()
                            logger.debug(f"供应商 {self.provider.name} 流式响应连接已关闭")
                        except Exception as e:
                            logger.error(f"关闭流式响应连接时出错: {str(e)}")
                
                # 返回流式生成器供API层处理
                # 注意：连接关闭由stream_generator的finally块管理
                result = {
                    "stream_response": stream_generator()
                }
            else:
                # 处理非流式响应
                try:
                    # 从配置获取响应大小限制
                    max_size = self.config.max_response_size if self.config else (10 * 1024 * 1024)
                    
                    # 检查响应大小
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > max_size:
                        raise ValueError(f"响应大小 ({content_length} bytes) 超过限制 ({max_size} bytes)")
                    
                    # 读取响应内容
                    if is_stream:
                        # 如果使用了stream模式，需要用aread
                        content = await response.aread()
                    else:
                        # 否则直接获取内容
                        content = response.content
                    
                    # 检查实际读取的大小
                    if len(content) > max_size:
                        raise ValueError(f"实际响应大小 ({len(content)} bytes) 超过限制 ({max_size} bytes)")
                    
                    result = json.loads(content)
                    
                    # 在响应中返回完整的模型名称
                    if "model" in result:
                        result["model"] = model
                    
                    # 记录响应时间
                    elapsed_time = time.time() - start_time
                    logger.info(f"供应商 {self.provider.name} 非流式响应成功，耗时: {elapsed_time:.2f}秒，响应大小: {len(content)} bytes")
                    
                except json.JSONDecodeError as e:
                    logger.error(f"JSON解析失败: {str(e)}, 内容: {content[:200] if content else 'empty'}")
                    raise
                except ValueError as e:
                    logger.error(f"响应大小验证失败: {str(e)}")
                    raise
            
            return result
            
        except httpx.HTTPStatusError as e:
            logger.error(f"供应商 {self.provider.name} HTTP错误: {e.response.status_code} - {e.response.text}")
            return self._create_error_response(f"请求失败: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"供应商 {self.provider.name} 请求异常: {str(e)}")
            return self._create_error_response(f"请求失败: {str(e)}")
        finally:
            # 只有非流式响应才在这里关闭连接
            # 流式响应的连接由stream_generator的finally块管理
            if response and not is_stream_response:
                try:
                    await response.aclose()
                    logger.debug(f"供应商 {self.provider.name} 非流式响应连接已关闭")
                except Exception as e:
                    logger.error(f"关闭非流式响应连接失败: {str(e)}")
    
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
    
    def __init__(self, providers: List[Provider], config=None):
        self.providers = providers
        self.clients = {p.name: ProviderClient(p, config) for p in providers}
        self.config = config
        logger.info(f"初始化模型管理器，供应商数量: {len(providers)}")
    
    async def get_all_models(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """获取所有供应商的模型列表
        
        Args:
            force_refresh: 是否强制刷新缓存，默认False
            
        Returns:
            模型列表
        """
        logger.info("开始获取所有供应商的模型列表")
        all_models = []
        tasks = []
        
        # 并发调用所有供应商的get_models
        # 每个ProviderClient会自己管理缓存和重试
        for client in self.clients.values():
            tasks.append(client.get_models(force_refresh=force_refresh))
        
        # 并发获取所有供应商的模型
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = 0
        for i, result in enumerate(results):
            provider_name = list(self.clients.keys())[i]
            if isinstance(result, list):
                if result:
                    all_models.extend(result)
                    success_count += 1
                    logger.debug(f"供应商 {provider_name} 返回 {len(result)} 个模型")
                else:
                    logger.debug(f"供应商 {provider_name} 返回空模型列表")
            else:
                logger.warning(f"供应商 {provider_name} 获取模型异常: {result}")
        
        # 如果有config，则过滤模型列表
        if self.config:
            all_models = self.config.filter_models(all_models)
        
        logger.info(f"获取到 {len(all_models)} 个模型 (成功供应商: {success_count}/{len(self.clients)})")
        
        return all_models
    
    def get_provider_client(self, model: str) -> Optional[ProviderClient]:
        """根据模型名称获取对应的供应商客户端"""
        provider_name, _ = ProviderClient.parse_model_name(model)
        
        if not provider_name:
            logger.warning(f"模型名称格式错误，缺少供应商前缀: {model}")
            return None
        
        client = self.clients.get(provider_name)
        if client:
            logger.debug(f"找到模型 {model} 对应的供应商: {provider_name}")
        else:
            logger.warning(f"未找到模型 {model} 对应的供应商: {provider_name}")
        return client
    
    async def chat_completion(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """发送聊天完成请求 - 接受完整的请求体字典"""
        model = body.get("model")
        messages = body.get("messages")
        
        if not model or not messages:
            return {
                "error": {
                    "message": "缺少必需参数: model 或 messages",
                    "type": "invalid_request",
                    "code": "invalid_request"
                }
            }
        
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
        
        # 直接将完整 body 传递给 ProviderClient
        result = await client.chat_completion(body)
        
        if "error" in result:
            logger.error(f"聊天完成请求失败: {result['error']['message']}")
        else:
            logger.info(f"聊天完成请求成功")
            
        return result
    
    async def health_check(self) -> Dict[str, bool]:
        """检查所有供应商的健康状态"""
        logger.info("开始健康检查")
        health_status = {}
        
        # 使用asyncio.gather并发执行健康检查
        tasks = [client.health_check() for client in self.clients.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, (name, result) in enumerate(zip(self.clients.keys(), results)):
            if isinstance(result, bool):
                health_status[name] = result
            elif isinstance(result, Exception):
                logger.error(f"供应商 {name} 健康检查异常: {result}")
                health_status[name] = False
            else:
                health_status[name] = False
        
        healthy_count = sum(1 for status in health_status.values() if status)
        logger.info(f"健康检查完成，健康供应商: {healthy_count}/{len(health_status)}")
        return health_status
    
    def clear_cache(self):
        """清除所有供应商的模型缓存"""
        logger.info("清除所有供应商的模型缓存")
        for client in self.clients.values():
            client._models_cache = None
            client._fetch_failed = False
            client._last_fetch_time = None
    
    async def close_all(self):
        """关闭所有客户端连接"""
        logger.info("关闭所有供应商客户端连接")
        for client in self.clients.values():
            await client.close()
