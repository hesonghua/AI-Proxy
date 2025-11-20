"""配置管理模块"""
import os
import logging
from typing import List, Tuple, Dict
from dataclasses import dataclass

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ai_proxy.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


@dataclass
class Provider:
    """供应商配置"""
    name: str
    url: str
    api_key: str
    
    @classmethod
    def from_line(cls, line: str) -> 'Provider | None':
        """从配置行创建Provider实例"""
        line = line.strip()
        if not line or line.startswith('#'):
            return None
            
        parts = line.split('|')
        if len(parts) != 3:
            raise ValueError(f"配置格式错误: {line}，正确格式：供应商名称|URL|API_KEY")
        
        name, url, api_key = parts
        
        return cls(name=name.strip(), url=url.rstrip('/'), api_key=api_key)


class Config:
    """配置管理器"""
    
    def __init__(self, providers_file: str = "providers.txt", tokens_file: str = "tokens.txt"):
        self.providers_file = providers_file
        self.tokens_file = tokens_file
        self.providers: List[Provider] = []
        self.valid_tokens: Dict[str, str] = {}
        logger.info(f"初始化配置管理器，供应商文件: {providers_file}, token文件: {tokens_file}")
        self.load_providers()
        self.load_tokens()
    
    def load_providers(self):
        """加载供应商配置"""
        if not os.path.exists(self.providers_file):
            logger.warning(f"供应商配置文件不存在: {self.providers_file}，创建示例配置")
            self._create_sample_config()
            return
            
        self.providers = []
        with open(self.providers_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                provider = Provider.from_line(line)
                if provider:
                    self.providers.append(provider)
                    logger.debug(f"加载供应商: {provider.name} (第{line_num}行)")
        
        logger.info(f"成功加载 {len(self.providers)} 个供应商配置")
    
    def _create_sample_config(self):
        """创建示例配置文件"""
        logger.info("创建示例供应商配置文件")
        sample_config = """# AI供应商配置文件
# 格式：供应商名称|URL|API_KEY
# 每行一个供应商配置

# OpenAI示例
# openai|https://api.openai.com/v1|sk-your-openai-key-here

# 智谱AI示例
# zhipu|https://open.bigmodel.cn/api/paas/v4|your-zhipu-key-here

# Azure OpenAI示例  
# azure|https://your-resource.openai.azure.com|your-azure-key-here

# 其他兼容OpenAI API的供应商
# other|https://api.other-provider.com/v1|sk-your-key-here
"""
        with open(self.providers_file, 'w', encoding='utf-8') as f:
            f.write(sample_config)
    
    def get_provider_by_name(self, name: str) -> Provider | None:
        """根据名称获取供应商"""
        provider = next((p for p in self.providers if p.name == name), None)
        if provider:
            logger.debug(f"找到供应商: {name}")
        else:
            logger.warning(f"未找到供应商: {name}")
        return provider
    
    def load_tokens(self):
        """加载token白名单"""
        if not os.path.exists(self.tokens_file):
            logger.warning(f"token文件不存在: {self.tokens_file}，创建示例token文件")
            self._create_sample_tokens()
            return
            
        self.valid_tokens = {}
        with open(self.tokens_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split('|')
                    if len(parts) == 2:
                        description, token = parts
                        self.valid_tokens[description.strip()] = token.strip()
                        logger.debug(f"加载token: {description} (第{line_num}行)")
        
        logger.info(f"成功加载 {len(self.valid_tokens)} 个token")
    
    def _create_sample_tokens(self):
        """创建示例token文件"""
        logger.info("创建示例token文件")
        sample_tokens = """# API Token白名单
# 每行一个token，用于API访问验证
# 格式：token描述|token值

# 示例tokens（请根据需要添加实际token）
test_token|sk-test-123456
admin_token|sk-admin-789012
readonly_token|sk-readonly-345678
"""
        with open(self.tokens_file, 'w', encoding='utf-8') as f:
            f.write(sample_tokens)
    
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
    
    def reload(self):
        """重新加载配置"""
        logger.info("重新加载配置")
        self.load_providers()
        self.load_tokens()
