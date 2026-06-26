# Use Python 3.12 slim image as base
FROM python:3.12-slim

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

#
# System packages
#
RUN apt-get update && apt-get install -y \
    apt-file \
    curl \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxshmfence1 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

#
# Initialize apt-file database
#
RUN apt-file update

#
# Install Node.js 22
#
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get update \
    && apt-get install -y nodejs

#
# Install Mermaid CLI globally
#
RUN npm install -g @mermaid-js/mermaid-cli

# Set working directory
WORKDIR /app

# Install system dependencies for file handling (tar, gz, tgz support)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tar \
    gzip \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy enviroment file
COPY .env .env

# Copy application code
COPY app ./app

# Copy externalized prompts
COPY prompts ./prompts

# Create uploads directory
RUN mkdir -p uploads

# Expose port 8080
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health')" || exit 1

# Run the application with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
