FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
RUN useradd -m broker
USER broker
CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 60 main:app
