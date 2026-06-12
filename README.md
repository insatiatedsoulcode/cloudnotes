# CloudNotes — Cloud Engineering POC

A full-stack notes app built to practice cloud engineering concepts progressively.

**Stack:** React (Vite) + FastAPI + PostgreSQL

---

## Quick Start (Phase 0 — No Docker)

### 1. Start PostgreSQL
```bash
# macOS
brew install postgresql@16 && brew services start postgresql@16
createdb cloudnotes

# Or use Docker just for the DB:
docker run -d --name pg -e POSTGRES_DB=cloudnotes -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16-alpine
```

### 2. Run the Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/cloudnotes"
uvicorn app.main:app --reload --port 8000
# API docs at http://localhost:8000/docs
```

### 3. Run the Frontend
```bash
cd frontend
npm install
npm run dev
# App at http://localhost:3000
```

---

## Phase 1 — Docker (Full Stack)

```bash
# From project root:
docker compose up --build

# App at http://localhost
# API at http://localhost:8000/docs
# Postgres exposed at localhost:5432

# Tear down (keeps DB data in the named volume):
docker compose down

# Tear down AND delete all data:
docker compose down -v
```

### Useful Docker Commands to Practice

```bash
# List running containers
docker ps

# Inspect logs of a service
docker compose logs -f backend

# Shell into a running container
docker exec -it cloudnotes_backend bash

# Inspect the Docker network
docker network inspect cloudnotes_default

# See image sizes (notice multi-stage build kept it lean)
docker images | grep cloudnotes

# Check what's in a named volume
docker volume inspect cloudnotes_postgres_data
```

---

## Phase 2 — AWS EC2 (Manual Deploy)

### Prerequisites
- AWS account with IAM user (AdministratorAccess for learning)
- AWS CLI configured: `aws configure`
- Billing alert set at $20

### Step-by-step

#### 1. Create ECR Repositories
```bash
aws ecr create-repository --repository-name cloudnotes-backend --region ap-south-1
aws ecr create-repository --repository-name cloudnotes-frontend --region ap-south-1
```

#### 2. Push Images to ECR
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=ap-south-1
ECR="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

# Authenticate Docker to ECR
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR

# Build and push
docker build -t $ECR/cloudnotes-backend:latest ./backend
docker push $ECR/cloudnotes-backend:latest

docker build --build-arg APP_ENV=production -t $ECR/cloudnotes-frontend:latest -f frontend/Dockerfile .
docker push $ECR/cloudnotes-frontend:latest
```

#### 3. Launch EC2 Instance
```bash
# Use the AWS Console or CLI:
aws ec2 run-instances \
  --image-id ami-0f58b397bc5c1f2e8 \   # Amazon Linux 2023 ap-south-1
  --instance-type t3.micro \
  --key-name your-key-pair \
  --security-group-ids sg-XXXX \
  --iam-instance-profile Name=EC2ECRReadRole \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=cloudnotes}]'
```

#### 4. Security Group Rules
Open these ports in the EC2 security group:
| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP | SSH |
| 80 | TCP | 0.0.0.0/0 | HTTP (frontend) |
| 8000 | TCP | 0.0.0.0/0 | API (optional, for testing) |

#### 5. Install Docker on EC2 and Run
```bash
ssh -i your-key.pem ec2-user@<PUBLIC_IP>

# Install Docker
sudo yum update -y
sudo yum install -y docker
sudo systemctl start docker && sudo systemctl enable docker
sudo usermod -aG docker ec2-user

# Install compose plugin
sudo curl -L https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Authenticate to ECR (EC2 uses instance profile, no keys needed)
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin $ECR

# Run the stack (create a compose file pointing to ECR images)
# Then:
docker compose up -d
```

---

## Phase 3 — AWS ECS (Fargate)

See the full ECS setup guide at https://ecsworkshop.com

Key resources to create (in order):
1. VPC with public/private subnets (or use default VPC to start)
2. ECR repos (already done above)
3. ECS Cluster (Fargate)
4. RDS PostgreSQL instance (move DB off containers)
5. AWS Secrets Manager secret for DB credentials
6. ECS Task Definitions (backend + frontend)
7. ECS Services
8. Application Load Balancer + target groups

---

## Phase 4 — CI/CD (GitHub Actions)

### Required GitHub Secrets
| Secret | Value |
|--------|-------|
| `AWS_ACCOUNT_ID` | Your 12-digit AWS account ID |
| `AWS_DEPLOY_ROLE_ARN` | ARN of IAM role GitHub can assume via OIDC |

### Set up OIDC trust (one-time)
```bash
# Create the OIDC provider in IAM (only needed once per AWS account)
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# Create an IAM role that GitHub Actions can assume
# Trust policy: allow token.actions.githubusercontent.com for your repo
# Permission policy: ECR push + ECS deploy
```

Once set, every `git push` to `main` triggers the full pipeline.

---

## Project Structure

```
cloudnotes/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, CORS, health check
│   │   ├── config.py        # pydantic-settings (env vars)
│   │   ├── database.py      # SQLAlchemy engine + session
│   │   ├── models/note.py   # ORM model
│   │   ├── schemas/note.py  # Pydantic request/response schemas
│   │   └── routers/notes.py # CRUD endpoints
│   ├── Dockerfile           # Multi-stage, non-root user
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api/notes.js     # API client (no hardcoded hostnames)
│   │   └── components/
│   ├── Dockerfile           # Build → Nginx serve
│   └── vite.config.js       # Dev proxy to backend
├── nginx/
│   └── nginx.conf           # Reverse proxy: serves SPA + proxies /api
├── docker-compose.yml       # Local dev orchestration
└── .github/workflows/
    └── deploy.yml           # CI/CD: test → build → push → ECS deploy
```
