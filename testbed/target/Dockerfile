FROM python:3.12-slim

# Herramientas que usan los inyectores (stress-ng, tc) y la mitigación (iptables)
RUN apt-get update \
    && apt-get install -y --no-install-recommends iptables iproute2 stress-ng procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
