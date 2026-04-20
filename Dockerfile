FROM cadquery/cadquery:latest

WORKDIR /app

COPY . .

# Install deps
RUN pip install --no-cache-dir flask pillow numpy opencv-python-headless gunicorn

# FIX PATH
ENV PATH="/home/cq/.local/bin:$PATH"

ENV PORT=10000

CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]
