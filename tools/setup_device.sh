#!/bin/bash

# The keys (rkey and wkey) could be given using the -w and -r flags as follows:
#   ./setup_device.sh -w 01020304..... -r f1f2f3f4.....
# where 01020304..... is a hex-encoded 32-byte data. For example, this is how
# one could generate random keys, store into an environment variables, and
# then pass them to setup_device.sh on Linux:
#
# $ MY_WKEY=$(dd if=/dev/urandom bs=1 count=32 | od -t x1 -An | tr -d '\n ')
# $ MY_RKEY=$(dd if=/dev/urandom bs=1 count=32 | od -t x1 -An | tr -d '\n ')
# $ ./setup_device.sh -w ${MY_WKEY} -r ${MY_RKEY} gencert/ca/key.pem gencert/ca/cert.der


SETUP_HEX=../firmware/SETUP.hex
FINAL_HEX=../firmware/release/u2f-firmware.hex
FLASH_TOOLS=0
WKEY_ARG=''
RKEY_ARG=''
SN=
SN_build=
SN_setup=

# Parse keys
while [[ $# -gt 0 ]]; do
  case $1 in
    -w|--wkey)
      shift
      if [[ $# < 1 ]]; then
        echo "expected wkey hex after -w"
        exit 1
      fi

      WKEY_ARG="-w $1"
      shift
      ;;

    -r|--rkey)
      shift
      if [[ $# < 1 ]]; then
        echo "expected rkey hex after -r"
        exit 1
      fi

      RKEY_ARG="-r $1"
      shift
      ;;

    *)
      break
      ;;
  esac
done

if [[ $# != "2" ]] && [[ $# != "6" ]]
then

    echo "usage: $0 <attestation-private-key> <attestation-public-key.der> [debugger-SN new-SN-for-U2F-token setup-hex-file setup-SN]"
    exit 1

fi

attest_priv=$1
attest_pub=$2

if [[ $# != "2" ]] ; then
    FLASH_TOOLS=1
    SN=$3
    SN_build=$4
    SETUP_HEX=$5
    SN_setup=$6
fi

export PATH=$PATH:gencert:u2f_zero_client:flashing

if [[ $FLASH_TOOLS = 1 ]] 
then

    # setup atecc
    #echo "erasing..."
    #erase.sh $SN

    echo "programming setup..."
    program.sh $SETUP_HEX $SN
    
    while [[ "$?" -ne "0" ]] ; do
        echo "$SN is retrying program... "
        sleep 0.2
        program.sh $SETUP_HEX $SN
    done

fi

echo "configuring..."

while true; do
    if [[ -n $SN_setup ]] ; then
        client.py configure $attest_priv pubkey.hex -s $SN_setup ${WKEY_ARG} ${RKEY_ARG}
    else
        client.py configure $attest_priv pubkey.hex ${WKEY_ARG} ${RKEY_ARG}
    fi

    if [[ "$?" -eq "0" ]]; then
        break
    else
        sleep 0.2
    fi
done


echo "generate attestation certificate..."
echo "for file $attest_pub"
cbytes.py $attest_pub > ../firmware/src/cert.c

[[ "$?" -ne "0" ]] && exit 1

wkey=$(cbytes.py "$(cat pubkey.hex|head -n 1)" -s)
[[ "$?" -ne "0" ]] && exit 1

rkey=$(cbytes.py "$(cat pubkey.hex|tail -n 1)" -s)
[[ "$?" -ne "0" ]] && exit 1


echo "" >> ../firmware/src/cert.c
echo "code uint8_t WMASK[] = $wkey;" >> ../firmware/src/cert.c
echo "code uint8_t RMASK[] = $rkey;" >> ../firmware/src/cert.c


if [[ -n $SN_build ]] ; then
    echo "setting SN to $SN_build"
    sed -i "/#define SER_STRING.*/c\#define SER_STRING \"$SN_build\""  ../firmware/src/descriptors.c
    rm ../firmware/release/u2f-firmware.omf
fi

echo "done."
echo "building..."

if [[ $FLASH_TOOLS != 1 ]] 
then

    echo "Open Simplicity Studio and rebuild final program."
    echo "Then you can erase and reprogram U2F Token."
    exit 1

fi

PATH1=$PATH
cur=`pwd`
cd ../firmware/release && make all && cd $cur

[[ "$?" -ne "0" ]] && exit 1

export PATH=$PATH1

echo "programming final build..."
cp $FINAL_HEX prog.hex
program.sh prog.hex $SN

while [[ "$?" -ne "0" ]] ; do
    sleep .2
    program.sh prog.hex $SN
done

[[ "$?" -ne "0" ]] && exit 1

echo "waiting to unplug"
sleep 0.2

while [[ "$?" -eq 0 ]] ; do

    sleep 0.5
    client.py wink -s "$SN_build"

done

echo "done."
