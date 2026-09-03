"""pytest 全局配置：强制演示模式，避免 .env 中的真实 API Key 拖慢/打断测试。

环境变量优先级高于 .env（pydantic-settings 的 source 顺序），因此在此设置
即可让整个测试进程（get_settings 的 lru_cache 首次求值前）稳定使用内置应答。
"""

import os

# 测试隔离存储：强制置空 DSN 走进程内内存实现，避免测试依赖本地数据库驱动（psycopg）
# 与外部服务；存储层本身有专门的 SQL 实现单元测试覆盖（test_storage.py）。
# 直接赋值而非 setdefault：环境变量优先级高于 .env，确保覆盖 .env 里配置的 PG DSN。
os.environ["ATHENA_PG_DSN"] = ""
os.environ["ATHENA_MOCK_FORCE"] = "true"
os.environ["ATHENA_API_KEY"] = ""  # 预留：确保不误用任何 Key
# 测试进程一律使用进程内向量后端（memory），避免读到 .env 的
# vector_store=postgres 而本地库/驱动缺失导致 researcher 崩溃（PG 后端由 pgvector 专项覆盖）
os.environ["ATHENA_VECTOR_STORE"] = "memory"