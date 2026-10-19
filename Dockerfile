FROM python:3.12-trixie

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-deps .

CMD ["python", "-m", "la_gazette_des_sorciers.main"]
