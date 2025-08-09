# Base Python image
FROM python:3.10-slim

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99
# Tell Selenium where Chromium is (handy if you want to read it from env in code)
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Install Chromium + ChromeDriver + deps
RUN apt-get update && apt-get install -y \
    wget curl unzip gnupg \
    chromium chromium-driver \
    fonts-liberation libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libdrm2 libgbm1 libxss1 libasound2 libxshmfence1 \
    --no-install-recommends && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

EXPOSE 10000

# Unbuffered python so Render logs show immediately
CMD ["python", "-u", "forexnews.py"]
