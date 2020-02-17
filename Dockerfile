#FROM continuumio/miniconda3:latest
##FROM heroku/miniconda:3
#
#ADD ./environment.yml /tmp/environment.yml
#ARG conda_env=disc
#ENV conda_env=$conda_env
#RUN conda update conda \
#    && conda env create -f /tmp/environment.yml \
#    && rm -rf /opt/conda/pkgs/*
#
#RUN echo "source /opt/conda/etc/profile.d/conda.sh"
#RUN echo "conda activate ${conda_env}" >> ~/.bashrc
#RUN cat ~/.bashrc
#ENV PATH $CONDA_DIR/envs/${conda_env}/bin:$PATH
#RUN echo $PATH
#ENV CONDA_DEFAULT_ENV ${conda_env}
#RUN echo $CONDA_DEFAULT_ENV
#
#
### Add the user that will run the app (no need to run as root)
##RUN groupadd -r myuser && useradd -r -g myuser myuser
#
## create  working dir
#WORKDIR /home/qutils
#
### Install myapp requirements
##COPY environment.yml /home/qutils/environment.yml
#
### update conda
##RUN conda update conda
##
##RUN conda config --add channels conda-forge \
##    && conda env create -f environment.yml \
##    && rm -rf /opt/conda/pkgs/*
#
## copy files
#COPY . /home/qutils/
##RUN chown -R myuser:myuser /home/qutils/*
#
##RUN echo "source activate disc" >> ~/.bashrc
##ENV PATH /opt/conda/envs/disc/bin:$PATH
##RUN /bin/bash -c "source activate disc"
#
#
#
#
### create conda environment
##RUN conda env create -f ./environment.yml
##
### Pull the environment name out of the environment.yml
##RUN echo "source activate disc" >> ~/.bashrc
##ENV PATH /opt/conda/envs/disc/bin:$PATH
#
## run the app
##CMD ["/bin/bash", "-c", "python launcher.py"]
##ENTRYPOINT ["python", "launcher.py" ]
##ENTRYPOINT "conda run -n $conda_env python3 launcher.py"
##ENTRYPOINT ["/bin/bash", "-c", "conda run -n $conda_env python3 launcher.py"]

FROM continuumio/miniconda3:latest
ARG CONDA_DIR="/opt/conda"
ARG conda_env=disc
ENV conda_env=$conda_env


ADD environment.yml /tmp/environment.yml
RUN conda update conda && conda env create -f /tmp/environment.yml && \
    conda clean --all --force-pkgs-dirs --yes && \
    find "$CONDA_DIR" -follow -type f \( -iname '*.a' -o -iname '*.pyc' -o -iname '*.js.map' \) -delete

# create  working dir
WORKDIR /home/qutils

COPY entrypoint /opt/docker/bin/entrypoint
COPY . /home/qutils/

RUN source /opt/conda/etc/profile.d/conda.sh && \
    conda activate "$conda_env"

CMD ["/opt/conda/bin/tini", \
     "--", \
     "/opt/docker/bin/entrypoint", \
     "python", \
     "launcher.py"
    ]