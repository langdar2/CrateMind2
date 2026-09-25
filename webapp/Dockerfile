FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY webapp/frontend/package.json webapp/frontend/package-lock.json* ./
RUN npm install
COPY webapp/frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY webapp/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY webapp/backend/ .
COPY --from=frontend-build /app/frontend/dist ./static

ENV DB_PATH=/data/library.db
ENV VUIO_BASE_URL=http://192.168.0.54:8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
