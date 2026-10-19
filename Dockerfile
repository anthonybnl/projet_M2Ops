FROM python:3.12-trixie

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-deps .

COPY sources.csv ./
ENV SOURCES_FILE=/app/sources.csv DATA_DIR=/data

CMD ["python", "-m", "la_gazette_des_sorciers.main"]
