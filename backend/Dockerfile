FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y sqlite3 curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create directory for SQLite database
RUN mkdir -p /data

# Set environment variables
ENV ENABLE_IP_WHITELIST=false
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Healthcheck to ensure the proxy is running
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# Start the application with Hypercorn (ASGI server)
CMD ["hypercorn", "--bind", "0.0.0.0:8080", "app:app"]
