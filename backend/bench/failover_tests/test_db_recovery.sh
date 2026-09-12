#!/bin/bash
set -e

API_URL="http://localhost/api/health"
COMPOSE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/docker-compose.local.yml"

echo "=== Failover & Recovery Test: Database Crash ==="

# 1. Verify initial state
echo "[1] Checking initial health..."
STATUS=$(curl --max-time 2 -s -o /dev/null -w "%{http_code}" $API_URL)
if [ "$STATUS" -eq 200 ]; then
    echo "✅ API is healthy ($STATUS)."
else
    echo "❌ API is not healthy ($STATUS). Aborting test."
    exit 1
fi

# 2. Simulate DB crash
echo "[2] Simulating database crash (stopping db container)..."
docker compose -f $COMPOSE_FILE stop db

# 3. Verify API fails gracefully
echo "[3] Checking API response while DB is down..."
STATUS=$(curl --max-time 2 -s -o /dev/null -w "%{http_code}" $API_URL)
if [[ "$STATUS" == 5* ]]; then
    echo "✅ API correctly returns a 5xx error ($STATUS) when DB is unreachable."
else
    echo "❌ Expected 5xx error, but got $STATUS."
    # We might continue anyway to bring DB back up
fi

# 4. Bring DB back up
echo "[4] Restarting database container..."
docker compose -f $COMPOSE_FILE start db
echo "Waiting 5 seconds for database to initialize..."
sleep 5

# 5. Verify API recovery
echo "[5] Checking if API recovers automatically..."
MAX_RETRIES=10
RECOVERED=false
for i in $(seq 1 $MAX_RETRIES); do
    STATUS=$(curl --max-time 2 -s -o /dev/null -w "%{http_code}" $API_URL)
    if [ "$STATUS" -eq 200 ]; then
        echo "✅ API successfully recovered ($STATUS)!"
        RECOVERED=true
        break
    else
        echo "Still waiting... ($STATUS)"
        sleep 2
    fi
done

if [ "$RECOVERED" = false ]; then
    echo "❌ API failed to recover after DB restart."
    exit 1
fi

echo "=== Test Completed Successfully ==="
