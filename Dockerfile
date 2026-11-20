FROM node:22-slim AS client
WORKDIR /app/client
COPY client/package.json client/package-lock.json ./
RUN npm ci
COPY client/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ server/
COPY --from=client /app/client/dist client/dist
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn server.app:app --host 0.0.0.0 --port ${PORT}"]
