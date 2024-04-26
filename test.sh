#!/bin/bash

THIS=$(dirname $0)
cd ${THIS}


if [[ ! -f /dls_sw/prod/tools/RHEL7-x86_64/Python/2-7-13/prefix/bin/python2.7 ]] ; then
    echo "ERROR: this script must be run at DLS with access to dls-python2.7"
    echo "It also requires access to the /dls_sw/prod folder"
    exit 1
fi

function test () {
    module=${1}
    version=${2}
    shift 2

    echo > /tmp/builder2ibek.support.log

    # add in the overrides with convoluted bash escaping
    if [[ -n ${1} ]] ; then
      override='-o'
      args="$@"
    fi

    (
    set -x
    ./builder2ibek.support.py /dls_sw/prod/R3.14.12.7/support/${module}/${version} \
      ./examples/${module}.ibek.support.yaml ${override} "${args}" \
      >> /tmp/builder2ibek.support.log
    )
}

# test each of the interesting support module conversions
test quadEM 9-4dls1 21:2 25:100
test pmac 2-5-23beta1 14:A+B 474:A+B 801:1 805:1.0 804:1.0


# now verify that there have been no changes since last results were committed
if ! git diff examples --no-pager >> /tmp/builder2ibek.support.log; then
    echo "FAILURE: use git to check differences in the examples folder"
    echo "if you are happy with the changes then commit and push them"
else
    echo "SUCCESS: no changes detected"
fi
