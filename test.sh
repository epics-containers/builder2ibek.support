#!/bin/bash

THIS=$(dirname $0)
cd ${THIS}

set -e

if [[ ! -f /dls_sw/prod/tools/RHEL7-x86_64/Python/2-7-13/prefix/bin/python2.7 ]] ; then
    echo "ERROR: this script must be run at DLS with access to dls-python2.7"
    echo "It also requires access to the /dls_sw/prod folder"
    exit 1
fi

# test each of the interesting support module conversions
./_run_test.sh quadEM 9-4dls1 -o 21:2,25:100
./_run_test.sh motor 7-0dls9-1
./_run_test.sh pmac 2-5-23beta1 -o 14:A+B,474:A+B,801:1,805:1.0,804:1.0
./_run_test.sh zebra 2-9-2
./_run_test.sh ADCore 3-12-1dls3 -o 193:10,178:10
./_run_test.sh ADAravis 2-2-1dls16
./_run_test.sh asyn 4-41dls2
./_run_test.sh calc 3-7-3
./_run_test.sh busy 1-7-2dls6
./_run_test.sh devIocStats 3-1-14dls3-3
./_run_test.sh lakeshore340 2-6
./_run_test.sh ipac 2-8dls4-8-1

# now verify that there have been no changes since last results were committed
CHANGES=$(git diff examples)
if [[ -n ${CHANGES} ]] ; then
    echo "FAILURE: use git to check differences in the examples folder"
    echo "if you are happy with the changes then commit and push them"
else
    echo "SUCCESS: no changes detected"
fi
