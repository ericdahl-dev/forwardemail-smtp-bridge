FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge ./bridge

# Unprivileged: the bridge listens on 2525, so it needs no capability to bind a low port.
RUN useradd --system --uid 10001 bridge
USER bridge

EXPOSE 2525
CMD ["python", "-m", "bridge"]
