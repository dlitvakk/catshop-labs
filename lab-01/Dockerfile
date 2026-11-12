FROM python:3.12-alpine

RUN adduser -D -u 10001 app \
 && mkdir -p /data && chown app:app /data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV PORT=8080
USER app

EXPOSE 8080

CMD ["python", "app.py"]
