FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Brussels
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64 -o /usr/local/bin/tailwindcss \
    && chmod +x /usr/local/bin/tailwindcss

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN tailwindcss -i static/css/app.css -o static/css/tailwind.css --minify
RUN pybabel compile -d translations

EXPOSE 5000

CMD ["flask", "--app", "app.py", "run", "--host=0.0.0.0", "--port=5000"]
