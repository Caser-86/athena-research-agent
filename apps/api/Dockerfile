# Athena API 服务镜像
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 仅拷贝依赖清单先装，提升构建缓存命中率
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# 运行 API 网关（生产环境关闭 reload）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]