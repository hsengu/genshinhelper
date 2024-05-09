FROM python:3.12-alpine as base

FROM base as build

RUN apk add --no-cache git build-base libxml2-dev libxslt-dev zlib-dev jpeg-dev freetype-dev
RUN pip install --upgrade pip
RUN mkdir /install
WORKDIR /install

COPY ./requirements-docker.txt requirements.txt
COPY ./app.json .
COPY ./setup* .
COPY ./.env .

RUN pip install -r requirements.txt

FROM base

COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /install /app
COPY ./src /app/src

WORKDIR /app

RUN pip uninstall -y pip && apk --purge del apk-tools

CMD ["python3", "./src/main.py"]