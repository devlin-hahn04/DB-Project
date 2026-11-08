FROM python:3.12-slim

WORKDIR /app

# Install dependencies from the shared root requirements file
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy the FastAPI backend
COPY backend/ ./backend/

EXPOSE 8000

# Start FastAPI on the port Render provides in $PORT (8000 when run locally)
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]