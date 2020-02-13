FROM heroku/miniconda:3

# create  working dir
WORKDIR /home/qutils

# copy files
COPY . ./

# update caonda
RUN conda update conda

# create conda environment
RUN conda env create -f ./environment.yml

# Pull the environment name out of the environment.yml
RUN echo "source activate $(head -1 ./environment.yml | cut -d' ' -f2)" >> ~/.bashrc
ENV PATH /opt/conda/envs/$(head -1 ./environment.yml | cut -d' ' -f2)/bin:$PATH

RUN conda env list | grep -v "^$\|#" |awk '{print $1;}'|xargs -I{} -d "\n" sh -c 'printf "Env: {}\t"; conda list -n {} |grep "^python\s";'


# run the app
CMD [ "python3", "launcher.py" ]