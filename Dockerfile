FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY infractl/pyproject.toml ./
RUN pip install --upgrade pip && pip install fastapi uvicorn python-dotenv kubernetes ansible ansible-runner

# Copy project files
COPY infractl/ ./infractl/
WORKDIR /app/infractl

# Expose FastAPI port
EXPOSE 8000

# Run API
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
