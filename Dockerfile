FROM python:3.9

RUN mkdir /usr/src/genshinhelper
WORKDIR /usr/src/genshinhelper

COPY . .

RUN pip install -r requirements.txt

CMD ["python3", "./src/main.py"]
