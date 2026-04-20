FROM cadquery/cadquery:latest

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir flask pillow numpy opencv-python-headless gunicorn

ENV PORT=10000

CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]
