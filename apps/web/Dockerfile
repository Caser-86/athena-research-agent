# Athena Web 前端镜像：Nginx 托管静态页 + 反代 API
FROM nginx:1.27-alpine

# 静态页
COPY index.html /usr/share/nginx/html/index.html
# Nginx 反代配置（/api 与 /health -> api:8000，SSE 需关闭缓冲）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80