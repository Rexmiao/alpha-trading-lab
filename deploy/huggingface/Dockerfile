FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_MAX_UPLOAD_SIZE=3 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

RUN useradd --create-home --uid 1000 user
USER user
WORKDIR /home/user/app

COPY --chown=user:user requirements.txt ./requirements.txt
RUN python -m pip install --user --no-cache-dir -r requirements.txt

COPY --chown=user:user hf_space/ ./hf_space/
COPY --chown=user:user research/ ./research/
COPY --chown=user:user LICENSE ./LICENSE

EXPOSE 7860
CMD ["python", "-m", "streamlit", "run", "hf_space/streamlit_app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]
