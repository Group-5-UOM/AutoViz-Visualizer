#!/bin/bash
# Fail the deploy on the first failed step. Without this a failed image pull
# (e.g. a full disk) still reported success while the old API kept running.
set -euo pipefail
cd /home/ec2-user/autoviz

REGION=eu-north-1
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin 965002174455.dkr.ecr.$REGION.amazonaws.com

# Each deploy leaves the previous API image behind untagged (~660 MB). Clear any
# a failed run left over before pulling, so the pull has room.
docker image prune -f

# Bring up (or leave running) Postgres — never recreated, so pgdata volume persists
/usr/local/bin/docker-compose up -d db

# Pull and recreate only the API container
/usr/local/bin/docker-compose pull api
/usr/local/bin/docker-compose up -d --no-deps api

# The container's entrypoint runs `alembic upgrade head` before starting uvicorn,
# so a healthy API means migrations applied. A failed migration exits the
# entrypoint and this times out, failing the deploy.
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8000/health > /dev/null 2>&1; then
    echo "API healthy"
    break
  fi
  sleep 2
done
curl -fsS http://localhost:8000/health > /dev/null

# The image the API just stopped using is now untagged.
docker image prune -f

# Deploy the freshly built frontend static files
sudo rm -rf /usr/share/nginx/html/*
sudo cp -r /home/ec2-user/autoviz/frontend-dist/* /usr/share/nginx/html/
