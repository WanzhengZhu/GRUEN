FROM python:3.12

ARG UID=1000
ARG GID=1000

RUN groupadd -g ${GID} gruen && \ 
    useradd -m -u ${UID} -g ${GID} -s /bin/bash gruen

 

RUN pip install editdistance numpy \
    spacy torch nltk transformers  \
    git+https://github.com/src-d/wmd-relax


COPY . /home/gruen/GRUEN
RUN chown -R gruen:gruen /home/gruen/GRUEN

WORKDIR /home/gruen/GRUEN
RUN apt-get update && apt-get install -y unzip && pip install gdown && bash install.sh
USER gruen

ENTRYPOINT ["python", "run_gruen.py"]

