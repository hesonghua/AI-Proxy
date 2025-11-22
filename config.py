"""配置管理模块"""
import os
import json
import re
import logging
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

# 日志级别映射
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'WARN': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}

def setup_logging(log_level: str = 'WARNING'):
    """配置日志系统
    
    Args:
        log_level: 日志级别，可选值: DEBUG, INFO, WARNING, ERROR, CRITICAL
                  默认为 WARNING
    """
    level = LOG_LEVEL_MAP.get(log_level.upper(), logging.WARNING)
    
    # 清除现有的handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 重新配置日志
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('ai_proxy.log', encoding='utf-8'),
            logging.StreamHandler()
        ],
        force=True  # 强制重新配置
    )
    
    return logging.getLogger(__name__)

# 初始化logger（使用默认级别）
logger = setup_logging()


@dataclass
class Provider:
    """供应商配置"""
    name: str
    url: str
    api_key: str
    model_list: List[str]
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Provider':
        """从字典创建Provider实例
        
        Args:
            data: 包含provider配置的字典，格式：
                  {
                      "provider": "供应商名称",
                      "baseurl": "API URL",
                      "token": "API密钥",
                      "model_list": ["model1", "model2"] (可选)
                  }
        
        Returns:
            Provider实例
        """
        return cls(
            name=data['provider'].strip(),
            url=data['baseurl'].rstrip('/'),
            api_key=data['token'].strip(),
            model_list=data.get('model_list', [])
        )
    
    @classmethod
    def from_line(cls, line: str) -> 'Provider | None':
        """从配置行创建Provider实例（兼容旧格式）
        
        Args:
            line: 格式为 "供应商名称|URL|API_KEY" 的字符串
        
        Returns:
            Provider实例或None
        """
        line = line.strip()
        if not line or line.startswith('#'):
            return None
            
        parts = line.split('|')
        if len(parts) != 3:
            raise ValueError(f"配置格式错误: {line}，正确格式：供应商名称|URL|API_KEY")
        
        name, url, api_key = parts
        
        return cls(
            name=name.strip(),
            url=url.rstrip('/'),
            api_key=api_key.strip(),
            model_list=[]
        )


class Config:
    """配置管理器"""
    
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.providers: List[Provider] = []
        self.valid_tokens: Dict[str, str] = {}
        self.supported_models: List[str] = []
        self.host: str = "localhost"
        self.port: int = 8080
        self.log_level: str = "WARNING"  # 默认日志级别
        
        # 连接池配置
        self.max_connections: int = 100  # 最大连接数
        self.max_keepalive_connections: int = 20  # 最大保持连接数
        self.keepalive_expiry: float = 30.0  # 连接过期时间（秒）
        
        # 超时配置
        self.stream_timeout: float = 300.0  # 流式超时（秒）
        self.non_stream_timeout: float = 30.0  # 非流式超时（秒）
        
        # 响应大小限制
        self.max_response_size: int = 10 * 1024 * 1024  # 10MB
        
        logger.info(f"初始化配置管理器，配置文件: {config_file}")
        self.load_config()
    
    def load_config(self):
        """从JSON文件加载配置"""
        if not os.path.exists(self.config_file):
            logger.warning(f"配置文件不存在: {self.config_file}")
            return
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            self.host = config_data.get('host', 'localhost')
            self.port = config_data.get('port', 8080)
            
            # 加载日志级别配置
            new_log_level = config_data.get('log_level', 'WARNING').upper()
            if new_log_level != self.log_level:
                self.log_level = new_log_level
                # 重新配置日志级别
                setup_logging(self.log_level)
                logging.getLogger(__name__).info(f"日志级别已设置为: {self.log_level}")
            
            # 加载连接池配置
            self.max_connections = config_data.get('max_connections', 100)
            self.max_keepalive_connections = config_data.get('max_keepalive_connections', 20)
            self.keepalive_expiry = config_data.get('keepalive_expiry', 30.0)
            
            # 加载超时配置
            self.stream_timeout = config_data.get('stream_timeout', 300.0)
            self.non_stream_timeout = config_data.get('non_stream_timeout', 30.0)
            
            # 加载响应大小限制
            self.max_response_size = config_data.get('max_response_size', 10 * 1024 * 1024)
            
            logger.info(f"连接池配置 - 最大连接数: {self.max_connections}, "
                       f"保持连接数: {self.max_keepalive_connections}, "
                       f"过期时间: {self.keepalive_expiry}秒")
            logger.info(f"超时配置 - 流式: {self.stream_timeout}秒, 非流式: {self.non_stream_timeout}秒")
            logger.info(f"响应大小限制: {self.max_response_size / 1024 / 1024:.1f}MB")

            # 加载供应商配置
            self.providers = []
            providers_data = config_data.get('providers', [])
            
            for item in providers_data:
                try:
                    if isinstance(item, dict):
                        # 新格式：字典对象
                        provider = Provider.from_dict(item)
                    elif isinstance(item, str):
                        # 旧格式：字符串 "name|url|key"
                        provider = Provider.from_line(item)
                    else:
                        logger.warning(f"未知的供应商配置格式: {item}")
                        continue
                    
                    if provider:
                        self.providers.append(provider)
                        model_count = len(provider.model_list) if provider.model_list else "自动获取"
                        logger.debug(f"加载供应商: {provider.name}, 模型列表: {model_count}")
                except Exception as e:
                    logger.error(f"加载供应商配置失败: {item}, 错误: {e}")
                    continue
            
            logger.info(f"成功加载 {len(self.providers)} 个供应商配置")
            
            # 加载token配置
            self.valid_tokens = {}
            tokens_data = config_data.get('tokens', [])
            for line in tokens_data:
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split('|')
                    if len(parts) == 2:
                        description, token = parts
                        self.valid_tokens[description.strip()] = token.strip()
                        logger.debug(f"加载token: {description}")
            
            logger.info(f"成功加载 {len(self.valid_tokens)} 个token")
            
            # 加载支持的模型列表
            self.supported_models = config_data.get('supported_models', [])
            logger.info(f"成功加载 {len(self.supported_models)} 个支持的模型模式")
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析错误: {e}")
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")

    def get_provider_by_name(self, name: str) -> Provider | None:
        """根据名称获取供应商"""
        provider = next((p for p in self.providers if p.name == name), None)
        if provider:
            logger.debug(f"找到供应商: {name}")
        else:
            logger.warning(f"未找到供应商: {name}")
        return provider
    
    
    def validate_token(self, token: str) -> bool:
        """验证token是否在白名单中"""
        is_valid = token in self.valid_tokens.values()
        if is_valid:
            token_info = self.get_token_info(token)
            logger.info(f"token验证成功: {token_info}")
        else:
            logger.warning(f"token验证失败: {token}")
        return is_valid
    
    def get_token_info(self, token: str) -> str | None:
        """获取token描述信息"""
        for description, valid_token in self.valid_tokens.items():
            if token == valid_token:
                return description
        return None
    
    def is_model_supported(self, model_id: str) -> bool:
        """检查模型是否在支持列表中（使用正则表达式匹配，不区分大小写）"""
        if not self.supported_models:
            # 如果没有配置支持的模型列表，则允许所有模型
            return True
        
        # 使用正则表达式匹配，不区分大小写
        for pattern in self.supported_models:
            try:
                if re.search(pattern, model_id, re.IGNORECASE):
                    logger.debug(f"模型 {model_id} 匹配模式 {pattern}")
                    return True
            except re.error as e:
                logger.warning(f"正则表达式模式错误 '{pattern}': {e}")
                continue
        
        logger.debug(f"模型 {model_id} 不匹配任何支持的模式")
        return False
    
    def filter_models(self, models: List[Dict]) -> List[Dict]:
        """过滤模型列表，只保留支持的模型"""
        if not self.supported_models:
            # 如果没有配置支持的模型列表，则返回所有模型
            return models
        
        filtered_models = [
            model for model in models
            if self.is_model_supported(model.get('id', ''))
        ]
        
        logger.info(f"模型过滤: {len(models)} -> {len(filtered_models)}")
        return filtered_models
    
    def reload(self):
        """重新加载配置"""
        logger.info("重新加载配置")
        self.load_config()
