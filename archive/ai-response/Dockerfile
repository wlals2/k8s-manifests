# Why: 멀티스테이지 빌드로 최종 이미지 크기 최소화
# Stage 1: Build dependencies
FROM python:3.11-slim as builder

WORKDIR /build

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime image
FROM python:3.11-slim

# Why: Non-root 사용자로 실행 (보안)
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY app/ ./app/

# Why: PATH에 사용자 pip 패키지 경로 추가
ENV PATH=/home/appuser/.local/bin:$PATH

# Change ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Why: Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=5.0)" || exit 1

# Expose port
EXPOSE 8000

# Run application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
