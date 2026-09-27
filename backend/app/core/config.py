# @Author: RebeccaZhou
# @Description: Application settings: Neo4j / LLM / Foundry injected via environment variables
#              应用配置：Neo4j / LLM / Foundry 全部通过环境变量注入。
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 固定定位到 backend/ 目录，不随启动时的工作目录变化
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "purifier123"
    neo4j_host: str = "localhost"

    # LLM provider
    llm_provider: Literal["qwen", "deepseek", "azure_openai"] = "qwen"

    # Qwen
    qwen_endpoint: str = ""
    qwen_api_key: str = ""
    qwen_model: str = "qwen-plus"

    # DeepSeek
    deepseek_endpoint: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"

    # Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o-mini"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    seed_on_startup: bool = True

    # 模型可选项（前端模型下拉用）
    @property
    def available_models(self) -> list[dict]:
        return [
            {"id": "qwen", "name": "Qwen-Plus", "provider": "qwen"},
            {"id": "deepseek", "name": "DeepSeek-Chat", "provider": "deepseek"},
            {"id": "azure_openai", "name": "Azure GPT-4o-mini", "provider": "azure_openai"},
        ]

    # 根据 provider 取连接信息
    def llm_endpoint(self) -> str:
        return {
            "qwen": self.qwen_endpoint,
            "deepseek": self.deepseek_endpoint,
            "azure_openai": self.azure_openai_endpoint,
        }[self.llm_provider]

    def llm_api_key(self) -> str:
        return {
            "qwen": self.qwen_api_key,
            "deepseek": self.deepseek_api_key,
            "azure_openai": self.azure_openai_api_key,
        }[self.llm_provider]

    def llm_model(self) -> str:
        return {
            "qwen": self.qwen_model,
            "deepseek": self.deepseek_model,
            "azure_openai": self.azure_openai_deployment,
        }[self.llm_provider]

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
