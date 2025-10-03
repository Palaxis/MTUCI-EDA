## MTUCI-EDA Backend Monorepo

Backend for a food delivery platform built with FastAPI microservices and containerized infrastructure for local development and k8s deployment.

### Services
- Auth Service (FastAPI)
- User Service (FastAPI)
- Order Service (FastAPI)
- Restaurant Service (FastAPI)
- Notification Service (FastAPI)

### Local Development (Docker Compose)
1. Copy environment template and adjust if needed:
   - `Copy-Item env/.env.example .env`
2. Build and start stack (loads variables from `.env` and compose from `infra/`):
   - `docker compose --env-file .env -f infra/docker-compose.yml up --build`
3. Services will be available at:
   - Auth: http://localhost:8001
   - User: http://localhost:8002
   - Order: http://localhost:8003
   - Restaurant: http://localhost:8004
   - Notification: http://localhost:8005
4. Infra components:
   - Postgres: localhost:5432
   - Redis: localhost:6379
   - Kafka: internal `kafka:9092` (exposed 9094)
   - RabbitMQ: AMQP `localhost:5672`, UI `http://localhost:15672` (guest/guest)

### Tech Stack
- Python 3.12
- FastAPI, Uvicorn
- PostgreSQL, Redis
- Kafka (orders), RabbitMQ (notifications)
- Docker, Docker Compose
- Kubernetes (manifests to be added under `k8s/`)

### Structure
```
services/
  auth/
    app/
      main.py
    requirements.txt
    Dockerfile
  user/
  order/
  restaurant/
  notification/
infra/
  docker-compose.yml
.env.example
```

### Environment
See `.env.example` for variables used by docker-compose and services.

### Notes
- This is the initial skeleton: health/ready endpoints are available. Business logic, DB migrations, and message flows will be added incrementally.


