FROM python:3.11-slim

# Install ONLY the essential system libraries
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# Install requirements but DO NOT install chromium here
RUN pip install --no-cache-dir -r requirements.txt

# This command runs when the app STARTS, bypassing the build limit
CMD playwright install chromium && gunicorn -b 0.0.0.0:8000 app:app
