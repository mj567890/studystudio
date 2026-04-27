#!/usr/bin/env bash
# StudyStudio 开发辅助工具
# 用法：source ~/studystudio/dev_tools.sh
#   然后可直接调用：wait_api / get_token / api_get / api_post

# 重建 api 并等待健康就绪（替代 restart + sleep）
rebuild_api() {
    echo "正在重建 api 容器..."
    docker-compose up -d --no-deps --build api
    wait_api
}

# 等待 API 健康就绪（最多等 60 秒）
wait_api() {
    echo -n "等待 API 就绪"
    for i in $(seq 1 20); do
        status=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health)
        if [ "$status" = "200" ]; then
            echo " ✓ (${i}次检查后就绪)"
            return 0
        fi
        echo -n "."
        sleep 3
    done
    echo " ✗ 超时，请检查 api 日志"
    return 1
}

# 获取 token（自动保存到 TOKEN 变量）
get_token() {
    local email="${1:-zhulimin@163.net}"
    local password="${2:-Admin@1234}"
    TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${email}\",\"password\":\"${password}\"}" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")
    if [ -n "$TOKEN" ]; then
        echo "✓ Token 已获取（${#TOKEN} 字符）"
    else
        echo "✗ Token 获取失败，请检查 API 是否就绪"
    fi
}

# GET 请求（自动处理中文参数编码）
# 用法：api_get /api/blueprints/网络安全/status
api_get() {
    local path="$1"
    # 对路径进行 URL 编码（Python 处理中文）
    local encoded_path
    encoded_path=$(python3 -c "
import urllib.parse, sys
path = sys.argv[1]
parts = path.split('?')
encoded = urllib.parse.quote(parts[0], safe='/:-_.')
if len(parts) > 1:
    params = urllib.parse.urlencode(
        dict(p.split('=',1) for p in parts[1].split('&') if '=' in p)
    )
    encoded = encoded + '?' + params
print(encoded)
" "$path")
    curl -s "http://127.0.0.1:8000${encoded_path}" \
        -H "Authorization: Bearer $TOKEN" \
        | python3 -m json.tool
}

# POST 请求
# 用法：api_post /api/blueprints/网络安全/generate '{}'
api_post() {
    local path="$1"
    local data="${2:-{}}"
    local encoded_path
    encoded_path=$(python3 -c "
import urllib.parse, sys
print(urllib.parse.quote(sys.argv[1], safe='/:-_.?=&'))
" "$path")
    curl -s -X POST "http://127.0.0.1:8000${encoded_path}" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "$data" \
        | python3 -m json.tool
}


export SPACE_ID="41756491-6d33-4f44-8046-885dda995da5"  # 全局领域 space_id
echo "✓ dev_tools.sh 已加载。可用命令：rebuild_api / wait_api / get_token / api_get / api_post"
