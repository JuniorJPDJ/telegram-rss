FROM python:3-alpine

WORKDIR /usr/src/telegram-rss
VOLUME ["/usr/src/telegram-rss/data"]


COPY . .
RUN apk add gcc python3-dev build-base libffi-dev libressl-dev
RUN pip install --no-cache-dir -r requirements.txt

CMD [ "python", "./main.py" ]