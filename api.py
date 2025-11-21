"""API兼容层 - FastAPI应用"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
import json
import asyncio

from config import Config
from client import ModelManager

# 获取logger
logger = logging.getLogger(__name__)

# 全局配置和模型管理器
config = Config()
model_manager = ModelManager(config.providers, config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时的初始化
    logger.info("AI聚合代理服务启动中...")
    logger.info(f"已加载 {len(config.providers)} 个供应商配置")
    
    yield
    
    # 关闭时的清理
    logger.info("正在关闭AI聚合代理服务...")
    await model_manager.close_all()

# 创建安全方案
security = HTTPBearer(auto_error=False)

def get_current_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """获取当前token"""
    if credentials is None:
        logger.debug("未提供token")
        return None
    logger.debug(f"收到token: {credentials.credentials}")
    return credentials.credentials


# 请求/响应模型
class Message(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]  # 支持字符串或数组


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = Field(default=1.0, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    stream: Optional[bool] = Field(default=False)
    top_p: Optional[float] = Field(default=1.0, ge=0, le=1)
    frequency_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: Optional[int] = None
    owned_by: str


class ModelsResponse(BaseModel):
    object: str = "list"
    data: List[ModelInfo]


# 创建FastAPI应用
app = FastAPI(
    title="AI聚合代理",
    description="兼容OpenAI API的AI模型聚合代理服务",
    version="1.0.0",
    lifespan=lifespan  # 使用现代化的生命周期管理
)


def normalize_message_content(content):
    """标准化消息内容格式"""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # 处理数组格式的内容
        if all(isinstance(item, dict) and 'text' in item for item in content):
            return ' '.join(item['text'] for item in content)
        elif all(isinstance(item, dict) and 'type' in item and 'text' in item for item in content):
            # 处理 kilo 插件格式: [{'type': 'text', 'text': '...'}]
            return ' '.join(item['text'] for item in content if item.get('type') == 'text')
        elif all(isinstance(item, str) for item in content):
            return ' '.join(content)
        else:
            # 其他情况，尝试转换为字符串
            try:
                return ' '.join(str(item) for item in content)
            except:
                return str(content)
    else:
        return str(content)


@app.get("/health")
async def health_check():
    """健康检查端点"""
    logger.info("收到健康检查请求")
    health_status = await model_manager.health_check()
    healthy_providers = sum(1 for status in health_status.values() if status)
    total_providers = len(health_status)
    
    logger.info(f"健康检查结果: {healthy_providers}/{total_providers} 个供应商健康")
    return {
        "status": "healthy" if healthy_providers > 0 else "unhealthy",
        "providers": health_status,
        "healthy_providers": healthy_providers,
        "total_providers": total_providers
    }


@app.get("/v1/models", response_model=ModelsResponse)
async def list_models():
    """获取所有可用模型列表"""
    try:
        logger.info("收到获取模型列表请求")
        models_data = await model_manager.get_all_models()
        models = [ModelInfo(**model) for model in models_data]
        logger.info(f"返回 {len(models)} 个模型")
        return ModelsResponse(data=models)
    except Exception as e:
        logger.error(f"获取模型列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}")


@app.post("/v1/chat/completions")
async def create_chat_completion(request: ChatCompletionRequest, 
                                 token: Optional[str] = Depends(get_current_token)):
    """创建聊天完成"""
    try:
        logger.info(f"收到聊天完成请求，模型: {request.model}, 消息数: {len(request.messages)}")
        
        # 验证token - token是强制性的
        if not token:
            logger.warning("未提供API token")
            raise HTTPException(
                status_code=401, 
                detail="未提供API token"
            )
        
        if not config.validate_token(token):
            logger.warning(f"无效的API token: {token}")
            raise HTTPException(
                status_code=401, 
                detail="无效的API token"
            )
        
        logger.info(f"token验证通过，使用token: {config.get_token_info(token)}")
        
        # 标准化消息格式 - 处理各种content格式
        normalized_messages = []
        for msg in request.messages:
            normalized_content = normalize_message_content(msg.content)
            normalized_messages.append({
                "role": msg.role,
                "content": normalized_content
            })
        
        # 记录请求参数
        logger.debug(f"请求参数 - temperature: {request.temperature}, max_tokens: {request.max_tokens}, stream: {request.stream}")
        
        # 调用模型管理器
        result = await model_manager.chat_completion(
            model=request.model,
            messages=normalized_messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=request.stream,
            top_p=request.top_p,
            frequency_penalty=request.frequency_penalty,
            presence_penalty=request.presence_penalty
        )
        
        # 检查是否有错误
        if "error" in result:
            logger.error(f"聊天完成请求返回错误: {result['error']['message']}")
            raise HTTPException(
                status_code=500, 
                detail=result["error"]["message"]
            )
        
        # 处理流式响应
        if request.stream and "stream_response" in result:
            logger.info("返回流式响应")
            return StreamingResponse(
                result["stream_response"],
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*"
                }
            )
        
        logger.info("聊天完成请求成功")
        return JSONResponse(content=result)
        
    except HTTPException as e:
        logger.warning(f"HTTP异常: {e.status_code} - {e.detail}")
        raise
    except Exception as e:
        logger.error(f"聊天完成请求失败: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"聊天完成请求失败: {str(e)}"
        )


@app.post("/v1/reload")
async def reload_config():
    """重新加载配置"""
    global model_manager
    try:
        logger.info("收到重新加载配置请求")
        
        # 关闭现有客户端
        await model_manager.close_all()
        
        # 重新加载配置
        config.reload()
        
        # 重新创建模型管理器
        model_manager = ModelManager(config.providers, config)
        
        # 清除模型缓存
        model_manager.clear_cache()
        
        logger.info(f"配置重新加载成功，当前供应商数量: {len(config.providers)}")
        return {"message": "配置重新加载成功", "providers_count": len(config.providers)}
        
    except Exception as e:
        logger.error(f"重新加载配置失败: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"重新加载配置失败: {str(e)}"
        )


@app.get("/")
async def root():
    """根路径信息"""
    logger.debug("收到根路径请求")
    return {
        "service": "AI聚合代理",
        "version": "1.0.0",
        "endpoints": {
            "models": "/v1/models",
            "chat": "/v1/chat/completions",
            "health": "/health",
            "reload": "/v1/reload"
        },
        "providers_count": len(config.providers)
    }


# 错误处理
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP异常处理"""
    logger.warning(f"HTTP异常处理: {exc.status_code} - {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.detail,
                "type": "http_error",
                "code": exc.status_code
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """通用异常处理"""
    logger.error(f"通用异常处理: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": f"内部服务器错误: {str(exc)}",
                "type": "internal_error",
                "code": "internal_error"
            }
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    详细的验证错误处理器
    """
    # 记录详细的错误信息
    logger.error(f"请求验证错误: {exc.errors()}")
    
    # 尝试获取原始请求体
    try:
        body = await request.body()
        body_str = body.decode()
        logger.error(f"接收到的原始请求体: {body_str}")
        
        # 尝试解析JSON以便更好地格式化
        try:
            body_json = json.loads(body_str)
            logger.error(f"解析后的JSON: {json.dumps(body_json, indent=2, ensure_ascii=False)}")
        except json.JSONDecodeError:
            logger.error("请求体不是有效的JSON格式")
    except Exception as e:
        logger.error(f"读取请求体失败: {e}")

    # 返回更友好的错误信息
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "message": "请求参数验证失败",
                "type": "validation_error",
                "code": 422,
                "details": exc.errors()
            }
        }
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level="info",
        access_log=False
    )
