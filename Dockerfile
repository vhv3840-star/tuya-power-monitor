FROM node:22-alpine AS frontend
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN npm install -g pnpm@11.25.0 && pnpm install --frozen-lockfile
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN pnpm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements-lock.txt /app/backend/requirements-lock.txt
RUN pip install --no-cache-dir -r backend/requirements-lock.txt
COPY backend ./backend
COPY scripts/serve.py ./scripts/serve.py
COPY --from=frontend /app/dist ./dist
RUN useradd --create-home monitor && mkdir /app/data && chown -R monitor:monitor /app
USER monitor
ENV BIND_HOST=0.0.0.0 PYTHONUNBUFFERED=1
EXPOSE 8000
VOLUME ["/app/data"]
CMD ["python", "scripts/serve.py"]
