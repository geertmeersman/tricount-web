FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Brussels
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN pybabel compile -d translations

EXPOSE 5000

CMD ["flask", "--app", "app.py", "run", "--host=0.0.0.0", "--port=5000"]
