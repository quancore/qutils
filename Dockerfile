FROM heroku/miniconda:3

ADD environment.yml /tmp/environment.yml
RUN conda update conda \
    && conda env create -f /tmp/environment.yml \
    && rm -rf /opt/conda/pkgs/*

RUN echo "conda activate $(head -1 /tmp/environment.yml | cut -d' ' -f2)" >> ~/.bashrc
ENV PATH /opt/conda/envs/$(head -1 /tmp/environment.yml | cut -d' ' -f2)/bin:$PATH
ENV CONDA_DEFAULT_ENV $(head -1 /tmp/environment.yml | cut -d' ' -f2)


## Add the user that will run the app (no need to run as root)
#RUN groupadd -r myuser && useradd -r -g myuser myuser

# create  working dir
WORKDIR /home/qutils

## Install myapp requirements
#COPY environment.yml /home/qutils/environment.yml

## update conda
#RUN conda update conda
#
#RUN conda config --add channels conda-forge \
#    && conda env create -f environment.yml \
#    && rm -rf /opt/conda/pkgs/*

# copy files
COPY . /home/qutils/
#RUN chown -R myuser:myuser /home/qutils/*

#RUN echo "source activate disc" >> ~/.bashrc
#ENV PATH /opt/conda/envs/disc/bin:$PATH
#RUN /bin/bash -c "source activate disc"




## create conda environment
#RUN conda env create -f ./environment.yml
#
## Pull the environment name out of the environment.yml
#RUN echo "source activate disc" >> ~/.bashrc
#ENV PATH /opt/conda/envs/disc/bin:$PATH

RUN conda env list | grep -v "^$\|#" |awk '{print $1;}'|xargs -I{} -d "\n" sh -c 'printf "Env: {}\t"; conda list -n {} |grep "^python\s";'
RUN which python

# run the app
CMD [ "python", "./launcher.py" ]