FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Create entrypoint script that handles PORT variable
RUN echo '#!/bin/bash' > /app/entrypoint.sh && \
    echo 'PORT=${PORT:-8000}' >> /app/entrypoint.sh && \
    echo 'exec uvicorn main:app --host 0.0.0.0 --port $PORT' >> /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
