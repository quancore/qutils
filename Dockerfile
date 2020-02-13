FROM heroku/miniconda:3

# Install extra packages if required
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

# Add the user that will run the app (no need to run as root)
RUN groupadd -r myuser && useradd -r -g myuser myuser

# create  working dir
WORKDIR /home/qutils

# Install myapp requirements
COPY environment.yml /home/qutils/environment.yml

# update conda
RUN conda update conda

RUN conda config --add channels conda-forge \
    && conda env create -n disc -f environment.yml \
    && rm -rf /opt/conda/pkgs/*

# copy files
COPY . /home/qutils/
RUN chown -R myuser:myuser /home/qutils/*

ENV PATH /opt/conda/envs/disc/bin:$PATH

## create conda environment
#RUN conda env create -f ./environment.yml
#
## Pull the environment name out of the environment.yml
#RUN echo "source activate disc" >> ~/.bashrc
#ENV PATH /opt/conda/envs/disc/bin:$PATH

RUN conda env list | grep -v "^$\|#" |awk '{print $1;}'|xargs -I{} -d "\n" sh -c 'printf "Env: {}\t"; conda list -n {} |grep "^python\s";'


# run the app
CMD [ "python3", "launcher.py" ]