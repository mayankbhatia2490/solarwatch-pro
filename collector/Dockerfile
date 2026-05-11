FROM python:3.11-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY solar_collector.py .
COPY ai_analyst.py .
COPY backfill.py .

CMD ["python", "-u", "solar_collector.py"]
