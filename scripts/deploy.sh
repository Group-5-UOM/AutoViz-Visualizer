#!/bin/bash
cd /home/ec2-user/autoviz

REGION=eu-north-1
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin 965002174455.dkr.ecr.$REGION.amazonaws.com

# Bring up (or leave running) Postgres — never recreated, so pgdata volume persists
/usr/local/bin/docker-compose up -d db

# Pull and recreate only the API container
/usr/local/bin/docker-compose pull api
/usr/local/bin/docker-compose up -d --no-deps api

# Run migrations against whatever schema state currently exists
/usr/local/bin/docker-compose exec -T api uv run alembic upgrade head

# Deploy the freshly built frontend static files
sudo rm -rf /usr/share/nginx/html/*
sudo cp -r /home/ec2-user/autoviz/frontend-dist/* /usr/share/nginx/html/
