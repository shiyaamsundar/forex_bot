# Base Python image
FROM python:3.10-slim

# Environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV DISPLAY=:99

# Install system dependencies for Chrome + ChromeDriver
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    gnupg \
    chromium \
    chromium-driver \
    fonts-liberation \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libgbm1 \
    libxss1 \
    libasound2 \
    libxshmfence1 \
    --no-install-recommends && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy all files
COPY . .

# Install Python dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Make .env available (optional for debugging)
RUN touch .env

# Expose port for Flask app
EXPOSE 10000

# Start the app
CMD ["python", "forexnews.py"]
