# The pinned environment of MoukhlijMatExtract: the exact package versions of requirements.lock, Tesseract, and the
# command that makes every table and figure of the article again (scripts/reproduce_paper.py).
#
#   docker build --build-arg MME_COMMIT=$(git rev-parse HEAD) -t moukhlijmatextract .
#   docker run --rm -v "$HOME/MoukhlijMatExtract:/data/MoukhlijMatExtract" moukhlijmatextract
#
# (or: make paper-docker). The project folder is mounted at /data/MoukhlijMatExtract: the results land in its paper/.
# Another command of the program: docker run --rm -v … moukhlijmatextract mme-rank --top 20
FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr git make \
 && apt-get clean

WORKDIR /mme
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN pip install --no-cache-dir --no-deps -e .

ARG MME_COMMIT=""
ENV MME_COMMIT=${MME_COMMIT} \
    HOME=/data \
    MPLBACKEND=Agg \
    PYTHONHASHSEED=0
VOLUME /data

CMD ["python", "scripts/reproduce_paper.py"]
