# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install build tools
RUN apt-get update && apt-get install -y \
    git \
    gcc \
    build-essential \
    libssl-dev \
    libffi-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install python packages
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
RUN pip install uwsgi uwsgitop  # Ensure uwsgi and uwsgitop are installed

COPY . .

CMD ["uwsgi", "--ini", "uwsgi.ini","--protocol","http"]
