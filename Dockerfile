# python:3.13-slim 3.13.18-slim
FROM python:3.13-slim@sha256:168d3a5d10f2152f8e8d77b6843ac82c22a846cfefeef7afdf9aa630404e82a7

ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Brussels
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64 -o /usr/local/bin/tailwindcss \
    && chmod +x /usr/local/bin/tailwindcss

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG VERSION=dev

COPY . .

RUN echo "$VERSION" > VERSION

RUN tailwindcss -i static/css/app.css -o static/css/tailwind.css --minify
RUN pybabel compile -d translations

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "120", "app:app"]
