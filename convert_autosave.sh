#!/bin/bash

# WARNING: this is for example only
# WARNING: instead use `builder2ibek autosave`
# from epics-containers/builder2ibek project

# script to extract autosave comments from DLS db templates and
# convert them to a format suitable for use with the autosave
# in epics-containers

# where possible the resulting files should be placed in the module in
# xxxAp/Db
#
# if not then they can be placed in ibek-support/xxx and will be used
# as overrides at runtime

# usage convert_autosave.sh <path to db folder> <path to output folder>

set -e

db_templates="$1/*.template"
output_folder=$2

mkdir -p $output_folder
for db_template in $db_templates; do
    echo "Processing $db_template"
    base=$output_folder/$(basename $db_template .template)
    if grep autosave $db_template; then
    (
        set -x
        epicsparser.py -s as $db_template ${base}
    )
    fi
    if [[ -f ${base}_2.req ]]; then
        cat ${base}_1.req ${base}_2.req > ${base}.req
        rm -f ${base}_2.req
        mv ${base}.req ${base}_1.req
    fi

    # remove empty files
    for i in $(seq 0 2); do
        if [[ ! -s ${base}_$i.req ]]; then
            rm -f ${base}_$i.req
        fi
    done
done