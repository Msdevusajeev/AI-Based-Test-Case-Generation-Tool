# Deployment Guide

## Overview

This document describes how to deploy and run the AI-Based Test Case Generation Tool in both local (on-prem) and Docker environments.

---

## System Requirements

### Software Prerequisites

| Software | Version |
|-----------|----------|
| Python | 3.11 |
| Node.js | 18+ |
| Git | Latest |
| Docker Desktop (Optional) | Latest |

Verify installations:

```bash
python --version
node --version
npm --version
```

---

## Clone Repository

```bash
git clone <repository-url>
cd sas_poc_26a14
```

---

## Environment Configuration

Copy the sample environment file:

```bash
copy .env.example backend\.env
```

Update values if required.

---

# On-Prem Deployment

## Backend Setup

Navigate to backend folder:

```bash
cd backend
```

### Create Virtual Environment

```bash
python -m venv venv
```

### Activate Virtual Environment

Windows:

```bash
venv\Scripts\activate
```

Linux/macOS:

```bash
source venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Install spaCy Language Model

```bash
python -m spacy download en_core_web_sm
```

### Backend URL

```text
http://localhost:8000
```

---

## Frontend Setup

Open a new terminal:

```bash
cd frontend
```

Install dependencies:

```bash
npm install
```

Build frontend:

```bash
npm run build
```

### Generate Application Executable

After installing all dependencies and the spaCy language model, execute the build script to generate the application executable:

```bash
build_exe.bat
```

### Frontend URL

```text
http://localhost:5173
```

---

# Docker Deployment

## Build Docker Image

Navigate to the project root directory:

```bash
docker build -t testcase-generator .
```

Expected output:

```text
Successfully tagged testcase-generator:latest
```

---

## Run Docker Container

```bash
docker run -p 8000:8000 testcase-generator
```

Expected output:

```text
INFO: Uvicorn running on http://0.0.0.0:8000
```

---

## Validate Deployment

Open:

```text
http://localhost:8000
```

### Health Check

```text
http://localhost:8000/api/health
```

Expected Response:

```json
{
  "status": "healthy"
}
```

---

# Troubleshooting

## Python Dependency Issues

Reinstall dependencies:

```bash
pip install -r requirements.txt
```

---

## Frontend Build Issues

```bash
npm install
npm run build
```

---

## Docker Issues

Verify Docker is running:

```bash
docker ps
```

Rebuild image:

```bash
docker build --no-cache -t testcase-generator .
```

---

# Verification Checklist

## On-Prem Deployment

- [ ] Python installed
- [ ] Node.js installed
- [ ] Backend dependencies installed
- [ ] Frontend dependencies installed
- [ ] Backend started successfully
- [ ] Frontend started successfully
- [ ] Application accessible

## Docker Deployment

- [ ] Docker Desktop installed
- [ ] Docker Engine running
- [ ] Docker image built successfully
- [ ] Container started successfully
- [ ] Application accessible

---

# Application Usage

1. Open the application.
2. Upload the SRS document (PDF, DOCX, XLSX).
3. Generate test cases.
4. Review generated results.
5. Export results as:
   - DOCX
   - XLSX

---

# Support

For deployment issues, contact the project team and provide:

- Deployment type (On-Prem or Docker)
- Error screenshot/logs
- Operating System details
- Application version