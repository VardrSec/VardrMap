FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home map
COPY . .
RUN sed -i 's/\r$//' start.sh
USER 10001:10001
EXPOSE 8000
CMD ["bash", "start.sh"]
