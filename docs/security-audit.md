# Athena Research Agent 安全审计报告

审计日期：2026-09-17
范围：Python/FastAPI/LangGraph 后端、原生 JavaScript 前端、MCP 工具、Docker/部署配置、管理员脚本及测试。

## 执行摘要

本轮对工作树和可见配置的扫描未发现真实 API Key、Token 或私钥内容；但初始版本存在前端持久化 XSS、MCP 输入边界不足、任务级观测串账，以及管理员脚本硬编码本地数据库密码等问题。本轮已修复这些可在不改变公开 API 的前提下安全修复的问题，并新增回归测试。

当前仍需部署侧处理的主要风险是：生产环境已禁用演示级 Python 沙箱，但若未来重新启用，仍必须替换为真正的 OS/容器隔离；直接暴露 API 端口时还需要外部网关提供统一的限流、配额和审计。

验证证据：初始审计后续复核为后端 `81 passed`；`ruff check app tests scripts` 通过；前端脚本解析通过；`docker compose config`（主编排、生产覆盖与观测编排注入哑变量）通过；`compileall` 通过；`git diff --check` 通过；API 镜像按锁文件重建并完成容器级冒烟检查。报告中的行号以本轮工作树为准。

## P1 高风险

### SEC-001：前端与 API Key 鉴权不匹配（Compose 同源部署已修复）

- 位置：`apps/web/index.html:325`；`apps/api/app/main.py:29-41`；`apps/api/app/auth.py:34-49`
- 证据：前端已移除 `URLSearchParams(...).get("api")` 和浏览器 Key 读取；Web 镜像启动时由 Nginx 服务端注入 `X-API-Key`，Compose 将 Key 仅传入 Web 容器。
- 影响：标准 Docker 同源部署已形成鉴权闭环；绕过 Web 网关直接访问 API 的客户端仍需自行携带请求头。
- 建议：生产保持 API 端口不对公网暴露，统一通过反向代理或专用会话层访问。

### SEC-002：MCP Python 沙箱仍不是安全隔离边界（生产已禁用，残余风险）

- 位置：`apps/api/app/mcp/server.py:120-165`
- 证据：当前代码已做 AST 白名单、`-I` 隔离启动、超时和最小环境限制，但仍在应用宿主机上调用 `subprocess.run`。
- 影响：开发环境中 AST 校验和超时不能替代操作系统级 CPU、内存、网络、进程和文件系统隔离；生产环境现在会直接拒绝该工具调用，因此不会把演示实现当作生产安全边界。
- 建议：生产环境改为一次性容器或专用沙箱服务，配置只读文件系统、非 root 用户、网络禁用、CPU/内存/PID 限额和更短超时；当前实现只适合演示和受信输入。

### SEC-003：文档解析器的本地路径读取范围未收敛（已修复）

- 位置：`apps/api/app/mcp/server.py:209-216`
- 证据：本地分支默认拒绝读取；配置 `ATHENA_DOC_ROOT` 后，使用 `resolve()` 和 `relative_to()` 校验来源必须位于允许根目录内。
- 影响：默认不会因为 MCP 调用而读取任意本地文件；部署者仍应在容器中以最小权限运行。
- 建议：生产继续优先传递上传文件 ID，而不是原始路径。

## P2 中风险

### SEC-004：OpenAPI 文档默认公开（生产模式已修复）

- 位置：`apps/api/app/main.py:20-26`
- 证据：`ATHENA_ENVIRONMENT=production` 时显式关闭 `/docs`、`/redoc`、`/openapi.json`；开发环境仍保持可用。
- 影响：生产模式不会默认公开接口结构；开发模式的公开文档属于明确的本地便利行为。
- 建议：若生产确实需要文档，放在受认证的内部网络或单独文档服务。

### SEC-005：未配置 CORS 时默认允许任意来源（生产模式已修复）

- 位置：`apps/api/app/main.py:29-36`
- 证据：开发模式仍可使用 `allow_origins=["*"]`；生产模式缺少 `ATHENA_CORS_ALLOWED_ORIGINS` 时启动失败，并将允许方法/请求头收窄。
- 影响：生产不会在忘记配置时静默进入全开放 CORS。
- 建议：生产只填写实际前端来源，并避免使用通配符。

### SEC-014：Host 头未收敛（已修复）

- 位置：`apps/api/app/main.py`；`apps/api/app/config.py`；`docker-compose.yml`
- 证据：生产环境现在要求配置 `ATHENA_ALLOWED_HOSTS`，并由 `TrustedHostMiddleware` 拒绝不在白名单中的 Host；Compose 从根目录 `.env` 传入该配置。
- 影响：降低 Host 头注入、错误路由到非预期主机和 DNS rebinding 类风险；开发环境保留通配以兼容本地测试。
- 验证：回归测试覆盖生产缺失配置 fail-fast 和恶意 Host 返回 400。
- 建议：生产填写精确域名，必要时使用 `*.example.com` 等明确受控模式，并确保外部代理也校验 Host。

### SEC-006：SSE 错误向客户端透传原始异常文本（已修复）

- 位置：`apps/api/app/api/routes.py:150-152`
- 证据：服务端通过 `logger.exception()` 记录带任务 ID 的异常，SSE 只返回固定错误消息和任务 ID。
- 影响：客户端不再直接获得内部路径、上游 URL、数据库信息或实现细节。
- 建议：生产日志系统仍需限制访问权限，并避免把完整异常同步到外部日志服务。

### SEC-007：MCP SQL 工具仍接受调用者提供的数据库路径（生产已禁用，残余风险）

- 位置：`apps/api/app/mcp/server.py:70-98`
- 证据：当前已限制单条 `SELECT/WITH`、长度、只读 URI 和返回行数，但 `db_path` 仍由调用者决定。
- 影响：开发环境中只读不等于安全；生产环境现在拒绝按调用者提供的路径查询，避免把该演示接口暴露为任意文件读取能力。
- 建议：将数据库映射为服务端注册的逻辑名称，路径由配置解析；使用独立只读账号/容器和允许表白名单。

### SEC-008：部署配置含固定开发凭据与外部镜像可变风险（已增加生产覆盖）

- 位置：`docker-compose.yml:18-23`；`deploy/docker-compose.observability.yml`
- 证据：主 Compose 明确是本地一键演示配置，仍有 `athena_dev` 开发密码；API/Web 基础镜像与主 Compose 的 pgvector 镜像已固定 digest；`deploy/docker-compose.production.yml` 已要求数据库/模型/网关凭据与白名单，并移除数据库宿主机端口映射；可选 Langfuse Compose 已改为必填环境变量/镜像引用，不再含占位密钥、`latest` 或全网卡数据库端口。
- 影响：生产不应单独使用主 Compose；叠加生产覆盖后会在缺少关键变量时由 Compose fail-fast，但 Secret 注入、外部数据库和 TLS 仍属于部署侧职责。
- 建议：生产固定使用生产覆盖文件和 Secret 管理，并按运维流程迁移已有数据卷凭据。

### SEC-009：缺少请求体、速率和资源上限（部分修复，仍需外部配额）

- 位置：`apps/api/app/main.py:13-41` 及各业务 router
- 证据：请求模型和 Nginx 已限制输入体积；Nginx 现在对 `/api/research/run`、`/api/research/stream` 增加按来源地址的基础速率限制，应用队列状态也会在获得槽位后才标记 running。
- 影响：标准 Web 网关部署可降低重复提交冲击；直接访问 API、跨多实例的全局配额、用户级计费上限和 SSE 生命周期预算仍未统一实现。
- 建议：生产在统一 API Gateway/WAF 增加分布式限流、用户配额、超时预算和成本告警，避免仅依赖单实例 Nginx 内存状态。

### SEC-010：前端严格 CSP 配置不足（已修复）

- 位置：`apps/web/index.html` 内嵌 script/style；`apps/web/nginx.conf` 响应头
- 证据：前端已固定同源 API（仅保留可选的部署时 `window.ATHENA_API_BASE`），不再读取 URL 覆盖；inline 事件、inline `style` 属性和 JS `.style` 写入已移除；Nginx 对静态 script/style 使用 SHA-256 hash，且不再包含 `unsafe-inline`。
- 影响：恶意 `?api=` 导流路径、HTML inline 事件注入面和宽泛 inline 样式/脚本执行面已移除，同时保留单文件前端结构。
- 建议：以后修改内嵌 script/style 必须重新计算 CSP hash，并由 `test_web_security_contract.py` 一起更新验证。

### SEC-011：pgvector 启动时自动创建数据库扩展（已修复）

- 位置：`apps/api/app/rag/pg_store.py:70-78`
- 证据：开发环境仍可自动启用扩展；`ATHENA_ENVIRONMENT=production` 时跳过 `CREATE EXTENSION`，由迁移/运维账号预先安装。
- 影响：生产应用账号不再需要该扩展 DDL 权限；若扩展未预置，启动会明确失败，需要先完成数据库准备。
- 建议：把扩展与表结构纳入版本化 migration，并让应用账号只保留所需 DML 权限。

## P3 低风险与维护项

### SEC-012：API Key 比较未使用常量时间函数（已修复）

- 位置：`apps/api/app/auth.py:18-31`
- 证据：`auth.py:29` 使用 `secrets.compare_digest` 比较用户输入和配置值。
- 影响：降低认证比较的时序侧信道风险。
- 建议：继续为失败请求增加审计，但避免记录 Key。

### SEC-013：LangGraph 配置类型触发运行时警告（已修复）

- 位置：`apps/api/app/graph/builder.py:43,45`
- 证据：移除 HITL 节点的延迟注解后，完整 `pytest -q` 为 `81 passed` 且不再出现该警告。
- 影响：当前依赖版本下配置注入契约与框架识别一致。
- 建议：依赖升级时继续保留全量测试与警告检查。

### SEC-015：测试依赖混入生产镜像（已修复）

- 位置：`apps/api/requirements.txt`；`apps/api/requirements-dev.txt`；`apps/api/requirements.lock.txt`；`apps/api/requirements-dev.lock.txt`；`apps/api/Dockerfile`；`.github/workflows/ci.yml`
- 证据：运行时 requirements 已移除 `pytest` 与 `pytest-asyncio`；测试依赖集中到 `requirements-dev.txt`；运行时和开发依赖分别锁定，Dockerfile 安装运行时锁文件，CI 安装开发锁文件。
- 影响：生产镜像不再默认携带测试运行器及其额外依赖，降低镜像体积和攻击面；开发/CI 测试能力保持不变。
- 验证：requirements 契约测试确认两类依赖边界，全量测试通过。
- 建议：后续引入锁文件或哈希约束时，分别为生产与开发依赖生成锁定集合。

## 本轮已修复的安全相关项

- `apps/web/index.html`：对进入 `innerHTML` 的报告、分析、Trace、工具结果和历史任务内容进行转义；历史任务改为 DOM 节点与事件监听器，避免把任务 ID 拼接进 inline JavaScript。
- `apps/web/index.html`、`apps/web/nginx.conf`：移除 inline style 和 JS 动态样式写入，改用 CSS class/hash CSP，收紧到无 `unsafe-inline` 的静态策略。
- `apps/api/app/mcp/server.py`：限制搜索数量、SQL 语句形式/长度/行数；对 Python 演示执行增加 AST 校验、隔离解释器、超时和最小环境；HTTP 文档解析增加公网地址校验、禁止重定向和响应大小上限，并改为异步流式读取。
- `apps/api/app/main.py`、`apps/api/app/config.py`：生产环境关闭调试文档、要求 CORS/Host 白名单，并收窄预检允许的方法和请求头。
- `apps/api/app/main.py`：生产环境缺少 `ATHENA_API_KEY` 时 fail-fast，避免部署后意外开放业务 API。
- `apps/web/nginx.conf`：增加反向代理请求体大小上限，配合 API schema 限制降低异常大请求风险。
- `apps/web/Dockerfile`、`apps/web/docker-entrypoint.sh`、`apps/web/nginx.conf`：由服务端 Nginx 注入 API Key，移除前端 URL API 覆盖，并对研究入口增加网关限流。
- `apps/api/app/mcp/server.py`：生产环境禁用演示级 Python 沙箱与任意路径 SQLite 查询；数据库异常改为通用错误。
- `apps/api/app/api/routes.py`：修复队列状态过早标记 running 和 SSE 异常路径注册表残留。
- `apps/api/app/rag/pg_store.py`：生产环境不再自动执行 `CREATE EXTENSION`。
- `deploy/docker-compose.observability.yml`：移除固定凭据、占位密钥和浮动 `latest` 标签，改为必填部署变量。
- `apps/api/requirements.txt`、`apps/api/requirements-dev.txt`、两份 lock 文件、`.github/workflows/ci.yml`：将测试依赖从生产安装集合拆出，锁定安装集合，并将 Ruff、Python 编译检查和主/生产 Compose 配置校验纳入 CI。
- `.env.example`、`apps/api/.env.example`、`docker-compose.yml`：统一 `ATHENA_` 配置前缀，并让根目录生产模式/CORS/Host 设置真正传入 API 容器。
- `apps/api/app/eval/__init__.py`：评测 CLI 改为惰性导出，消除 `python -m app.eval.harness` 的重复导入警告。
- `apps/api/app/obs.py`、`apps/api/app/api/routes.py`：使用 `ContextVar` 绑定任务 ID，避免并发任务汇总彼此的 LLM token 和成本。
- `scripts/_pg_test.py`：移除版本库中的 PostgreSQL DSN 硬编码，改为强制读取 `ATHENA_PG_DSN`。
- `scripts/install_pgvector_admin.ps1`、`scripts/install_pgvector_admin.bat`：移除版本库中的管理员密码硬编码，改为读取 `ATHENA_PG_ADMIN_PASSWORD`。

## 清理与文件保留结论

### 已删除文件/目录

以下项目均为明确的 A 级生成物、缓存或空日志；删除前已检查 Git 状态和全局引用，且没有 tracked 删除：

- `runner.log`：空的未跟踪运行日志；无代码、脚本或文档引用。
- `.playwright-cli/`：浏览器自动化工具缓存；不属于应用运行时或发布资源。
- `apps/api/.pytest_cache/`：pytest 缓存。
- `apps/api/.ruff_cache/`：Ruff 缓存。
- `apps/api/app/**/__pycache__/`、`apps/api/tests/__pycache__/`：Python 字节码缓存；共清理 8 个包/测试缓存目录。

未删除源码、入口、配置、数据库、迁移、资源、CI、许可证或用户未提交文件；当前工作树 `git ls-files --deleted` 无输出。

### 保留的疑似无用文件

- `scripts/_pg_test.py`：无自动调用引用、名称像临时脚本，但内容是需要显式 `ATHENA_PG_DSN` 的 PostgreSQL/pgvector 手工验证工具；保留以支持运维自检。若要删除，需要确认团队已不再使用该手工流程，并把其验证步骤迁入正式脚本或文档。
- `scripts/install_pgvector_admin.ps1`、`scripts/install_pgvector_admin.bat`：无应用内调用，但承担 Windows 本地 pgvector 安装/验证职责；保留。后续可在文档中明确适用环境，避免误用于生产。
- `deploy/docker-compose.observability.yml`、`deploy/.env.example`：主应用默认不依赖，但属于可选 Langfuse 部署配置；保留，并已改为必填部署参数。
- `.env.example`、`apps/api/.env.example`、`apps/api/app/eval/golden_set.py`、`docs/PRD.md`、`docs/architecture.svg`：配置、评测数据或正式文档/资源，属于 C 级或高风险文件，不能因缺少直接 Python 引用删除。

## 未完成与后续风险分级

### P0 严重

- 当前未发现已验证的 P0 问题。

### P1 高风险

- Python 演示沙箱仍不是 OS/容器安全边界。生产模式已直接禁用，但若未来重新开放，必须迁移到独立沙箱服务，并施加非 root、禁网、只读文件系统、CPU/内存/PID 限额。

### P2 中风险

- 主 Compose 的 `athena_dev` 账号密码明确属于本地演示配置，不能直接作为公网生产编排；已提供 `deploy/docker-compose.production.yml`，生产仍应使用 Secret/外部数据库并按覆盖文件启动。
- Nginx 限流是单实例、按 IP 的基础护栏；多实例用户配额、SSE 生命周期预算、成本上限和统一审计仍需 API Gateway/WAF 或专用会话层。
- `PostgresSaver`/版本化 migration 尚未落地；当前任务持久化与 pgvector 依赖生产侧预置和部署流程。

### P3 低风险

- 依赖仍使用范围版本而非锁定/哈希集合；已拆分生产与开发依赖，后续应生成分别可复现的锁文件。

## 最终验证记录

- `python -m pytest -q`：`81 passed`。
- `ruff check app tests ..\\..\\scripts`：通过。
- `python -m compileall -q app tests`：通过。
- 前端内嵌 JavaScript：Node 语法解析通过。
- 严格 CSP：静态 script/style hash 与页面内容匹配，且页面无 inline `style` 属性、JS `.style` 写入或 `unsafe-inline`。
- 主 `docker compose config --quiet`：通过。
- 观测 `docker compose -f deploy/docker-compose.observability.yml config --quiet`：在哑变量下通过。
- `docker compose build web api`：两个镜像构建成功，目标为 Linux `amd64`。
- `docker compose up -d --no-build`：`athena-db` healthy，`athena-api`/`athena-web` running；Web `/health`、`/api/obs/summary` 和首页均返回 HTTP 200，响应包含严格 CSP。
- `docker compose -f docker-compose.yml -f deploy/docker-compose.production.yml config --quiet`：生产覆盖在注入哑变量后通过；缺少必需生产变量时按设计 fail-fast。
- 主运行时镜像引用（Python、Nginx、pgvector）已固定为本轮 Docker 构建解析出的 digest，并由配置契约测试守护。
- CI 工作流已包含 Ruff、compileall、主 Compose 与生产覆盖配置校验；本地对应命令均已通过。
- 容器依赖检查：API 运行时镜像未携带 pytest。
- 离线评测：`overall=0.895`，`threshold=0.5`，PASS；本次强制 mock 配置运行未发起上游模型请求。
- 本轮测试/编译后生成的 Python 缓存目录仍被 `.gitignore` 忽略；本机删除策略拒绝递归删除命令，因此未绕过策略清理，也未产生跟踪文件或删除 Git 文件。
- `git diff --check`：通过（仅有 Git 的 LF/CRLF 提示）。
- tracked 文件敏感模式扫描：未发现常见 API Key、Token、私钥模式。

审计过程中曾有一次未覆盖本地忽略 `.env` 的评测命令读取到真实模型配置并观察到上游请求，随后已立即中止；没有在输出中打印密钥。之后所有评测均使用强制 mock/空 Key 配置，未发起上游请求；如需确认供应商侧是否产生计费，仍应检查对应账户用量记录。
