FROM python:3.9-alpine

RUN apk add git build-base zlib-dev jpeg-dev freetype-dev
RUN pip install --upgrade pip
RUN mkdir /usr/src/genshinhelper
WORKDIR /usr/src/genshinhelper

COPY . .

RUN pip install -r requirements.txt
RUN apk --purge del git py-pip && rm -rf /root/.cache/pip && apk --purge del apk-tools

CMD ["python3", "./src/main.py"]
