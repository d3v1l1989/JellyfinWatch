FROM python:3-alpine

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create defaults directory and copy default configs
RUN mkdir -p /app/defaults && \
    cp -r /app/data/* /app/defaults/ && \
    chmod +x /app/entrypoint.sh && \
    chmod -R 777 /app/defaults

# Create data and logs directories
RUN mkdir -p /app/data /app/logs && \
    chmod -R 777 /app/data /app/logs

# Set proper permissions
RUN chown -R 1000:1000 /app

USER 1000

ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]
CMD ["python", "main.py"]
