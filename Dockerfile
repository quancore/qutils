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
RUN echo "source activate disc" >> ~/.bashrc
ENV PATH /opt/conda/envs/disc/bin:$PATH

RUN conda env list | grep -v "^$\|#" |awk '{print $1;}'|xargs -I{} -d "\n" sh -c 'printf "Env: {}\t"; conda list -n {} |grep "^python\s";'


# run the app
CMD [ "python3", "launcher.py" ]