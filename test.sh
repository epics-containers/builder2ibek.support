#!/bin/bash

THIS=$(dirname $0)
cd ${THIS}


if [[ ! -f /dls_sw/prod/tools/RHEL7-x86_64/Python/2-7-13/prefix/bin/python2.7 ]] ; then
    echo "ERROR: this script must be run at DLS with access to dls-python2.7"
    exit 1
fi

function test () {
    module=${1}
    version=${2}
    overrides=${3}

    if [[ -e ${overrides} ]] ; then
      args="-o\'$overrides\'"
    else
      args=
    fi

    set -x
    ./builder2ibek.support.py /dls_sw/prod/R3.14.12.7/support/${module}/${version} \
      ./examples/${module}.ibek.support.yaml  ${args}
    set +x
}

test quadEM 9-4dls1 '21:2 25:100'

