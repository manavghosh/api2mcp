FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ".[http]"

# Copy source
COPY src/ ./src/

# Default: stdio transport (override via CMD or entrypoint)
ENTRYPOINT ["api2mcp"]
CMD ["--help"]

EXPOSE 8000
