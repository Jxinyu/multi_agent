import yaml
from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMKeySetting(BaseModel):
    """大模型的key"""
    deepseek: str = SecretStr
    xiaoAi: str = SecretStr
    qwen: str = SecretStr
    llamaParse: str = SecretStr
    postgressql: str = SecretStr
    redis: str = SecretStr


class LlamaParseSetting(BaseModel):
    """llamaParse的配置"""
    invalidate_cache: bool = True  # 是否失效缓存


class MilvusSetting(BaseModel):
    """milvus的配置"""
    uri: str = '127.0.0.1'
    dims: int = 19530


class AppSettings(BaseSettings):
    """app配置"""
    llm_key: LLMKeySetting = LLMKeySetting()
    llama_parser: LlamaParseSetting = LlamaParseSetting()
    milvus: MilvusSetting = MilvusSetting()


def load_setting(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        config_data = yaml.safe_load(f)
    return AppSettings().model_validate(config_data)


if __name__ == '__main__':
    setting = load_setting('config.yaml')
    print(setting.llm_key.xiaoAi)
