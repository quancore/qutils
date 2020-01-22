# file for migrating the old files to the new SQL format
# precondition: tables created already
# function must be migrate_cog_name

import json
import datetime
import csv
import io


def _load_json(fp):
    with open(fp, 'r', encoding='utf-8') as f:
        return json.load(f)