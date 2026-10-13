# FilingLens EDA: dataset exploration (deliverable 1)
# A container with Python and every EDA library already installed.
# By default it opens Jupyter to view the notebook; the scripts run on demand.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt eda/requirements.txt
RUN pip install --no-cache-dir -r eda/requirements.txt

# The EDA code goes in eda/, as in the repo, so the paths are the same.
# The .env with the keys NEVER enters the image (.dockerignore blocks it).
COPY . eda/

# data/ is mounted from your machine by docker compose, never baked into the image
ENV PYTHONUNBUFFERED=1

EXPOSE 8888

# Jupyter without a password: only safe because compose publishes it on 127.0.0.1
CMD ["jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", \
     "--ServerApp.token=", "--ServerApp.password=", "--ServerApp.root_dir=/app"]
