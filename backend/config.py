"""Environment configuration. Never sent to the browser."""
import os
from pathlib import Path
from pydantic import BaseModel, Field, SecretStr, field_validator
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1]

class Settings(BaseModel):
    data_dir: Path = ROOT/'runtime'
    access_token: SecretStr = SecretStr('')
    api_key: SecretStr = SecretStr('')
    base_url: str = 'https://api.deepseek.com'
    model: str = 'deepseek-flash'
    llm_enabled: bool = False
    timeout_seconds: float = Field(default=60,gt=0,le=120)
    max_upload_bytes: int = 10*1024*1024
    max_ai_chars: int = 20000
    max_output_tokens: int = Field(default=3000,ge=256,le=8000)
    daily_token_budget: int = 100000
    retention_seconds: int = 86400
    cookie_secure: bool = True

    @field_validator('base_url')
    @classmethod
    def safe_base(cls,value):
        from urllib.parse import urlsplit
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError('API base URL must be administrator-configured HTTPS without credentials/query')
        return value.rstrip('/')

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT/'.env',override=False)
        return cls(data_dir=Path(os.getenv('DATA_DIR',str(ROOT/'runtime'))),access_token=os.getenv('DEMO_ACCESS_TOKEN',''),api_key=os.getenv('DEEPSEEK_API_KEY',''),base_url=os.getenv('DEEPSEEK_BASE_URL','https://api.deepseek.com'),model=os.getenv('DEEPSEEK_MODEL','deepseek-flash'),llm_enabled=os.getenv('LLM_ENABLED','false').lower()=='true',timeout_seconds=float(os.getenv('LLM_TIMEOUT_SECONDS','60')),daily_token_budget=int(os.getenv('DEMO_DAILY_TOKEN_BUDGET','100000')),cookie_secure=os.getenv('COOKIE_SECURE','true').lower()=='true')
