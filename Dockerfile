FROM continuumio/miniconda3:latest
ARG CONDA_DIR="/opt/conda"
ARG conda_env=disc
ENV conda_env=$conda_env

# Add the user that will run the app (no need to run as root)
RUN groupadd -r myuser && useradd -r -g myuser myuser
RUN apt-get install -y libc-dev

ADD environment.yml /tmp/environment.yml
RUN conda update conda && conda env create nomkl -f /tmp/environment.yml && \
    conda clean --all --force-pkgs-dirs --yes && \
    find "$CONDA_DIR" -follow -type f \( -iname '*.a' -o -iname '*.pyc' -o -iname '*.js.map' \) -delete

# create  working dir
USER myuser
WORKDIR /home/qutils
COPY --chown=myuser:myuser . /home/qutils/

COPY --chown=myuser:myuser entrypoint /opt/docker/bin/entrypoint

RUN . /opt/conda/etc/profile.d/conda.sh && \
    conda activate "$conda_env" && \
    chmod +x /opt/docker/bin/entrypoint


ENTRYPOINT ["/opt/docker/bin/entrypoint"]