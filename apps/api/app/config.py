"""环境配置：统一从 .env / 环境变量读取，前缀 ATHENA_。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATHENA_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 模型（OpenAI 兼容接口）
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    # Embedding（未配置时 RAG 使用确定性演示向量）
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""

    # 测试 / CI 强制演示模式：即使 .env 配置了真实 Key 也走内置应答，保证测试快且可复现
    mock_force: bool = False

    # 编排护栏
    max_iterations: int = 3          # Critic 打回的最大轮数
    critic_pass_score: float = 7.0    # Critic 通过阈值（0-10）

    # 检索
    tavily_api_key: str = ""          # 留空时 Researcher 使用内置演示数据源

    # 超时
    request_timeout_seconds: float = 120.0

    # 输出上限：约束 thinking 模型的推理与输出长度，显著降低真实调用时延与成本
    llm_max_output_tokens: int = 2048

    # 单价（元/百万 token），用于可观测性成本核算；0 或未配置时用 obs.py 内置示例价
    llm_price_per_1m_input: float = 2.0
    llm_price_per_1m_output: float = 8.0

    # 存储后端 DSN：空 = 内存实现；填 sqlite:///athena.db 或 postgresql://... 走 SQL 持久化
    pg_dsn: str = ""

    # 向量检索后端：memory（进程内，默认）| postgres（PostgreSQL + pgvector，需 pg_dsn 指向
    # 已启用 vector 扩展的库，且安装 pgvector 依赖）。留空 = memory。
    vector_store: str = "memory"

    # API 鉴权：平台自身 API Key。留空 = 开放（本地演示）；生产务必设置，
    # 客户端请求头携带 `Authorization: Bearer <key>` 或 `X-API-Key: <key>`。
    api_key: str = ""

    # CORS 允许的来源（逗号分隔）。留空且非生产 = 允许全部（本地开发）；
    # 设置后仅放行列表内来源，收敛跨域风险。
    cors_allowed_origins: str = ""

    @property
    def mock_mode(self) -> bool:
        """未配置 API Key 或强制演示模式时，进入演示模式：LLM 返回内置应答，开箱即可跑通编排回路。"""
        return self.mock_force or not self.llm_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
