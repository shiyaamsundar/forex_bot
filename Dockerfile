FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget unzip curl gnupg2 \
    libglib2.0-0 libnss3 libgconf-2-4 libfontconfig1 libxss1 \
    libappindicator3-1 libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcups2 libdbus-1-3 libgdk-pixbuf2.0-0 libnspr4 libx11-xcb1 \
    libxcomposite1 libxdamage1 libxrandr2 xdg-utils

# Install Chrome (fixed version)
RUN wget https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_114.0.5735.90-1_amd64.deb && \
    apt install -y ./google-chrome-stable_114.0.5735.90-1_amd64.deb

# Install matching ChromeDriver (v114)
RUN wget https://chromedriver.storage.googleapis.com/114.0.5735.90/chromedriver_linux64.zip && \
    unzip chromedriver_linux64.zip && \
    mv chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver

# Set working directory
WORKDIR /app

# Copy code and install Python deps
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt

# Expose Flask port and run
EXPOSE 10000
CMD ["python", "main.py"]
