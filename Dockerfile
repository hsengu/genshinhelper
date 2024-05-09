FROM python:3.12-alpine

RUN apk add --no-cache git build-base libxml2-dev libxslt-dev zlib-dev jpeg-dev freetype-dev
RUN pip install --upgrade pip
RUN mkdir /usr/src/genshinhelper
WORKDIR /usr/src/genshinhelper

COPY . .

RUN pip install --no-cache-dir -r requirements-docker.txt && pip uninstall -y pip
RUN apk --purge del git apk-tools

CMD ["python3", "./src/main.py"]
