FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg snapraid ca-certificates && rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home photosync
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server
COPY client ./client
COPY shared ./shared
COPY VERSION ./VERSION
RUN mkdir /data /media && chown photosync:photosync /data
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8080
ENTRYPOINT ["python", "-B", "-m", "server.app"]
CMD ["--host", "0.0.0.0", "--port", "8080", "--data", "/data", "--library-base", "/media"]
