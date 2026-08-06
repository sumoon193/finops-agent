FROM public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
RUN pip install --no-cache-dir . uvicorn
EXPOSE 8000
CMD ["uvicorn", "app.finops.api:app", "--host", "0.0.0.0", "--port", "8000"]
