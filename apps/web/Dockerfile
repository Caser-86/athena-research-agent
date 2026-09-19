# Athena Web 前端镜像：Nginx 托管静态页 + 反代 API
FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

# 静态页
COPY index.html /usr/share/nginx/html/index.html
# Nginx 反代模板；启动时只替换 ATHENA_API_KEY，其余 Nginx 变量保持不变。
COPY nginx.conf /etc/nginx/athena.conf.template
COPY docker-entrypoint.sh /usr/local/bin/athena-entrypoint.sh
RUN chmod +x /usr/local/bin/athena-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/athena-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]

EXPOSE 80
