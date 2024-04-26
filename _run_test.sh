#!/bin/bash
module=${1}
version=${2}
shift 2

(
set -x
./builder2ibek.support.py /dls_sw/prod/R3.14.12.7/support/${module}/${version} \
    ./examples/${module}.ibek.support.yaml "${@}"
)
