#!/usr/bin/env bash

set -e  # Stop on error

echo ">>> Updating system packages..."
apt-get update && apt-get install -y \
  wget \
  unzip \
  curl \
  gnupg \
  software-properties-common \
  apt-transport-https \
  ca-certificates \
  fonts-liberation \
  libappindicator3-1 \
  libasound2 \
  libatk-bridge2.0-0 \
  libatk1.0-0 \
  libcups2 \
  libdbus-1-3 \
  libgdk-pixbuf2.0-0 \
  libnspr4 \
  libnss3 \
  libx11-xcb1 \
  libxcomposite1 \
  libxdamage1 \
  libxrandr2 \
  xdg-utils

echo ">>> Installing Google Chrome..."
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt install -y ./google-chrome-stable_current_amd64.deb

echo ">>> Detecting Chrome version..."
CHROME_VERSION=$(google-chrome --version | awk '{print $3}' | cut -d '.' -f 1)

if [ -z "$CHROME_VERSION" ]; then
  echo "❌ Failed to detect Chrome version. Exiting."
  exit 1
fi

echo ">>> Installing matching ChromeDriver version: $CHROME_VERSION"
CHROMEDRIVER_VERSION=$(curl -sS "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_$CHROME_VERSION")

wget -N "https://chromedriver.storage.googleapis.com/${CHROMEDRIVER_VERSION}/chromedriver_linux64.zip"
unzip -o chromedriver_linux64.zip
mv chromedriver /usr/local/bin/
chmod +x /usr/local/bin/chromedriver

echo "✅ Chrome and ChromeDriver installed successfully."
