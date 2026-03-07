# Docker Expert Production Template (Skill: docker-expert)
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8080

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Create builds directory
RUN mkdir -p builds

# Expose port
EXPOSE 8080

# Run with Gunicorn for Flask + B2B Prospecting Setup (Bind to $PORT)
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "--workers", "4", "main:app"]
