FROM python:3.10-slim AS builder

# Install system dependencies (including those needed for Unstructured and OpenCV)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ musl-dev curl libffi-dev gfortran libopenblas-dev \
    tesseract-ocr libtesseract-dev libleptonica-dev pkg-config \
    poppler-utils libmagic1 \
    libgl1-mesa-glx libglib2.0-0 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir poetry

# Copy the entire project into the container
COPY . /app
WORKDIR /app/py

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --extras "core" --no-dev --no-root \
    && pip install --no-cache-dir gunicorn uvicorn

# Create the final image
FROM python:3.10-slim

# Install runtime dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    curl tesseract-ocr poppler-utils libmagic1 pandoc libreoffice \
    libgl1-mesa-glx libglib2.0-0 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the installed packages from the builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy the application and config
COPY core /app/core
COPY r2r /app/r2r
COPY r2r.toml /app/r2r.toml
COPY pyproject.toml /app/pyproject.toml

# Expose the port
ARG PORT=9311
ARG HOST=0.0.0.0
ENV PORT=$PORT HOST=$HOST
EXPOSE $PORT
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Run the application
CMD ["sh", "-c", "uvicorn core.main.app_entry:app --host $HOST --port $PORT"]