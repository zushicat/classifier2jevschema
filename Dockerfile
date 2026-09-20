FROM python:3.13

WORKDIR /app

RUN python -m pip install --upgrade pip setuptools wheel

COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt -r requirements-dev.txt

COPY . .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=TRUE \
    PYTHONPATH=/app/src \
    DATA_DIR=/app/data

EXPOSE 80