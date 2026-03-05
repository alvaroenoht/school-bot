FROM python:3.12-slim

# System deps (for psycopg2, reportlab)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY app/ ./app/

# Create directories for runtime use
RUN mkdir -p /tmp/reports

# Non-root user for security
RUN useradd -m -u 1000 schoolbot && chown -R schoolbot:schoolbot /app /tmp/reports
USER schoolbot

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
