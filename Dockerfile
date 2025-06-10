# Dockerfile

# 1. Use a modern, lightweight Python base image
FROM python:3.11-slim

# 2. Set environment variables for logging and port binding
ENV PYTHONUNBUFFERED True
ENV PORT 8080

# 3. Set the working directory inside the container
WORKDIR /app

# 4. Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy your application code
COPY . .

# 6. Define the command to run the synchronous Gunicorn server
#    This matches the approach in the guide.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--worker-class", "uvicorn.workers.UvicornWorker", "--timeout", "120", "bot:app"]
