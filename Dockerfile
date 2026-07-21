FROM apache/airflow:2.9.3-python3.11

USER root

# ffmpeg はレンダリングに必須
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

ENV PYTHONPATH=/opt/airflow/src:/opt/airflow/config
