FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /tinman
COPY . /tinman/
RUN python -m pip install --no-cache-dir .

ENTRYPOINT ["tinman"]
