# Dockerfile

# 1. Use a modern, lightweight Python base image
FROM python:3.11-slim

# 2. Set environment variables
ENV PYTHONUNBUFFERED True

# 3. Set the working directory inside the container
WORKDIR /app

# 4. Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy your application code
COPY . .

# 6. Define the command to run the Uvicorn server with the FastAPI app
CMD ["uvicorn", "bot:app", "--host", "0.0.0.0", "--port", "8080"]
