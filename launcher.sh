#!/bin/bash
# this script mainly created for overcaming the problem of activating conda environment in Heroku

source activate "$(head -1 ./environment.yml | cut -d' ' -f2)"
python3 launcher.py