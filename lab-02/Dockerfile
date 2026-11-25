FROM python:3.12-alpine AS build

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-alpine

RUN adduser -D -u 10001 app \
 && mkdir -p /data && chown app:app /data

WORKDIR /app

COPY --from=build /install /usr/local
COPY app.py .

ENV PORT=8080
USER app

EXPOSE 8080

CMD ["python", "app.py"]
