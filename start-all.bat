@echo off
REM 一键启动 sport-agent-fullstack 三服务（各自独立窗口）
REM 前提：backend\target\sport-agent-backend-0.1.0.jar 已构建（见 README 的 mvn clean package）
set BASE=C:\Users\24162\Documents\sport-agent-fullstack
set JAVA_HOME=C:\Users\24162\tools\jdk17\jdk-17.0.20+8
set PY=C:\Users\24162\.workbuddy\binaries\python\versions\3.13.12\python.exe
set NPM=C:\Users\24162\.workbuddy\binaries\node\versions\22.22.2-2\npm.cmd

REM 关键：清掉本机代理变量。本机代理（如 127.0.0.1 端口的透明代理）会让
REM Python 到 api.deepseek.com 的 TLS 握手被掐断（SSL: UNEXPECTED_EOF_WHILE_READING），
REM 表现为 /chat 一律返回「LLM 暂时不可用，已降级」。DeepSeek 是国内服务，直连即可。
set HTTP_PROXY=
set HTTPS_PROXY=
set http_proxy=
set https_proxy=

start "agent-service(8001)" cmd /k "cd /d %BASE%\agent-service && %PY% -m uvicorn app:app --port 8001 --host 127.0.0.1"
start "backend(8080)" cmd /k "cd /d %BASE%\backend && %JAVA_HOME%\bin\java -jar target\sport-agent-backend-0.1.0.jar --server.port=8080"
start "frontend(5173)" cmd /k "cd /d %BASE%\frontend && %NPM% run dev"

echo 三服务已在独立窗口启动。浏览器打开 http://localhost:5173
echo （若 backend 窗口报找不到 jar，请先按 README 执行 mvn clean package -DskipTests）
pause
