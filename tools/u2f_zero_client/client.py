#!/usr/bin/env python
#
# Copyright (c) 2016, Conor Patrick
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

#
#
#
# Client application for U2F Zero that can be used
# for configuring new builds or accessing custom functionality.
#
#
from __future__ import print_function
import time, os, sys, array, binascii, signal, random, hashlib

try:
    import hid
except:
    print('python hidapi module is required')
    print('try running: ')
    print('     apt-get install libusb-1.0-0-dev libudev-dev')
    print('     pip install hidapi')
    sys.exit(1)

try:
    import ecdsa
except:
    print('python ecdsa module is required')
    print('try running: ')
    print('     pip install ecdsa')
    sys.exit(1)



cmd_prefix = [0, 0xff,0xff,0xff,0xff]

class commands:
    U2F_CONFIG_GET_SERIAL_NUM = 0x80
    U2F_CONFIG_IS_BUILD = 0x81
    U2F_CONFIG_IS_CONFIGURED = 0x82
    U2F_CONFIG_LOCK = 0x83
    U2F_CONFIG_GENKEY = 0x84
    U2F_CONFIG_LOAD_TRANS_KEY = 0x85
    U2F_CONFIG_LOAD_WRITE_KEY = 0x86
    U2F_CONFIG_LOAD_ATTEST_KEY = 0x87
    U2F_CONFIG_BOOTLOADER = 0x88
    U2F_CONFIG_BOOTLOADER_DESTROY = 0x89

    U2F_CUSTOM_RNG = 0x21
    U2F_CUSTOM_SEED = 0x22
    U2F_CUSTOM_WIPE = 0x23
    U2F_CUSTOM_WINK = 0x24


if len(sys.argv) < 2:
    print('usage: %s <action> [<arguments>] [-s serial-number]' % sys.argv[0])
    print('actions: ')
    print("""   configure <ecc-private-key> <output-file>: setup the device configuration.  Specify ECC P-256 private
                                                           key for token attestation.  Specify temporary output file for
                                                           generated keys.""")
    print('     rng: Continuously dump random numbers from the devices hardware RNG.')
    print('     seed: update the hardware RNG seed with input from stdin')
    print('     wipe: wipe all registered keys on U2F Zero.  Must also press button 5 times.  Not reversible.')
    print('     list: list all connected U2F Zero tokens.')
    print('     wink: blink the LED')
    print('     bootloader: put device in bootloader mode')
    print('     bootloader-destroy: permanently disable the bootloader')
    sys.exit(1)

def open_u2f(SN=None):
    h = hid.device()
    try:
        h.open(0x10c4,0x8acf,SN if SN is None else unicode(SN))
        print('opened ', SN)
    except IOError as ex:
        print( ex)
        if SN is None: print( 'U2F Zero not found')
        else: print ('U2F Zero %s not found' % SN)
        sys.exit(1)
    return h


def do_list():
    for d in hid.enumerate(0x10c4, 0x8acf):
        keys = list(d.keys())
        keys.sort()
        for key in keys:
            print("%s : %s" % (key, d[key]))
    print('')


def die(msg):
    print( msg)
    sys.exit(1)


def feed_crc(crc, b):
    crc ^= b
    crc = (crc >> 1) ^ 0xa001 if crc & 1 else crc >> 1
    crc = (crc >> 1) ^ 0xa001 if crc & 1 else crc >> 1
    crc = (crc >> 1) ^ 0xa001 if crc & 1 else crc >> 1
    crc = (crc >> 1) ^ 0xa001 if crc & 1 else crc >> 1
    crc = (crc >> 1) ^ 0xa001 if crc & 1 else crc >> 1
    crc = (crc >> 1) ^ 0xa001 if crc & 1 else crc >> 1
    crc = (crc >> 1) ^ 0xa001 if crc & 1 else crc >> 1
    crc = (crc >> 1) ^ 0xa001 if crc & 1 else crc >> 1
    return crc

def reverse_bits(crc):
    crc = (((crc & 0xaaaa) >> 1) | ((crc & 0x5555) << 1))
    crc = (((crc & 0xcccc) >> 2) | ((crc & 0x3333) << 2))
    crc = (((crc & 0xf0f0) >> 4) | ((crc & 0x0f0f) << 4))
    return (((crc & 0xff00) >> 8) | ((crc & 0x00ff) << 8))

def get_crc(data):
    crc = 0
    for i in data:
        crc = feed_crc(crc,ord(i))
    crc = reverse_bits(crc)
    crc2 = crc & 0xff;
    crc1 = (crc>>8) & 0xff;
    return [crc1,crc2]

def read_n_tries(dev,tries,num,wait):
    data = None
    for i in range(0,tries-1):
        try:
            return dev.read(num,wait)
        except:
            time.sleep(.1)
            pass
    return dev.read(num,wait)

def get_write_mask(key):
    m = hashlib.new('sha256')
    m.update(key + '\x15\x02\x01\x00\xee\x01\x23' + ('\x00'*57))
    h1 = m.hexdigest()
    m = hashlib.new('sha256')
    m.update(binascii.unhexlify(h1))
    h2 = m.hexdigest()

    return h1 + h2[:8]



def do_configure(h, pemkey, output, wkey, rkey):
    config = "\x01\x23\x6d\x10\x00\x00\x50\x00\xd7\x2c\xa5\x71\xee\xc0\x85\x00\xc0\x00\x55\x00\x83\x71\x81\x01\x83\x71\xC1\x01\x83\x71\x83\x71\x83\x71\xC1\x71\x01\x01\x83\x71\x83\x71\xC1\x71\x83\x71\x83\x71\x83\x71\x83\x71\xff\xff\xff\xff\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x55\x55\xff\xff\x00\x00\x00\x00\x00\x00\x13\x00\x3C\x00\x13\x00\x3C\x00\x13\x00\x3C\x00\x13\x00\x3C\x00\x3c\x00\x3C\x00\x13\x00\x3C\x00\x13\x00\x3C\x00\x13\x00\x33\x00"


    h.write([0,commands.U2F_CONFIG_IS_BUILD])
    data = h.read(64,1000)
    if data[1] == 1:
        print( 'Device is configured.')
    else:
        die('Device not configured')

    time.sleep(0.250)

    h.write([0,commands.U2F_CONFIG_GET_SERIAL_NUM])
    while True:
        data = read_n_tries(h,5,64,1000)
        l = data[1]
        print( 'read %i bytes' % l)
        if data[0] == commands.U2F_CONFIG_GET_SERIAL_NUM:
            break
    print( data)
    config = array.array('B',data[2:2+l]).tostring() + config[l:]
    print( 'conf: ', binascii.hexlify(config))
    time.sleep(0.250)


    crc = get_crc(config)
    print( 'crc is ', [hex(x) for x in crc])
    h.write([0,commands.U2F_CONFIG_LOCK] + crc)
    data = read_n_tries(h,5,64,1000)

    if data[1] == 1:
        print( 'locked eeprom with crc ',crc)
    else:
        die('not locked')

    time.sleep(0.250)

    #h.write([0,commands.U2F_CONFIG_GENKEY])
    #data = read_n_tries(h,5,64,1000)
    #data = array.array('B',data).tostring()
    #pubkey = binascii.hexlify(data)

    if wkey is None:
        print('generating a new random wkey')
        # TODO: use urandom for that
        wkey = [random.randint(0,255)&0xff for x in range(0,32)]
    else:
        print('using provided wkey instead of generating one')

    if rkey is None:
        print('generating a new random rkey')
        # TODO: use urandom for that
        rkey = [random.randint(0,255)&0xff for x in range(0,32)]
    else:
        print('using provided rkey instead of generating one')

    h.write([0,commands.U2F_CONFIG_LOAD_TRANS_KEY]+wkey)
    data = read_n_tries(h,5,64,1000)
    if data[1] != 1:
        die('failed writing master key')


    wkey = get_write_mask(''.join([chr(x) for x in wkey]))
    print('wkey',wkey)
    rkey = get_write_mask(''.join([chr(x) for x in rkey]))


    h.write([0,commands.U2F_CONFIG_LOAD_WRITE_KEY]+[ord(x) for x in binascii.unhexlify(wkey)])
    data = read_n_tries(h,5,64,1000)
    if data[1] != 1:
        die('failed loading write key')

    attestkey = ecdsa.SigningKey.from_pem(open(pemkey).read())
    if len(attestkey.to_string()) != 32:
        die('Incorrect key type.  Must be prime256v1 ECC private key in PEM format.')


    h.write([0,commands.U2F_CONFIG_LOAD_ATTEST_KEY] + [ord(x) for x in attestkey.to_string()])
    data = read_n_tries(h,5,64,1000)
    if data[1] != 1:
        die('failed loading attestation key')


    print('writing keys to ', output)
    open(output,'w+').write(wkey + '\n' + rkey)

    print( 'Done.  Putting device in bootloader mode.')
    h.write([0,commands.U2F_CONFIG_BOOTLOADER])
    data = read_n_tries(h,5,64,1000)
    if data[1] != 1:
        die('failed to put device in bootloader mode.')

def bootloader(h):
    h.write([0,commands.U2F_CONFIG_BOOTLOADER])
    h.write([0,0xff,0xff,0xff,0xff,commands.U2F_CONFIG_BOOTLOADER])
    print('If this device has an enabled bootloader, the LED should be turned off.')


def bootloader_destroy(h):
    h.write([0,commands.U2F_CONFIG_BOOTLOADER_DESTROY])
    h.write([0,0xff,0xff,0xff,0xff,commands.U2F_CONFIG_BOOTLOADER_DESTROY])
    print('Device bootloader mode removed.  Please double check by running bootloader command.')





def do_rng(h):
    cmd = [0,0xff,0xff,0xff,0xff, commands.U2F_CUSTOM_RNG, 0,0]
    # typically runs around 700 bytes/s
    while True:
        h.write(cmd)
        rng = h.read(64,1000)
        if not rng or rng[4] != commands.U2F_CUSTOM_RNG:
            sys.stderr.write('error: device error\n')
        else:
            if rng[6] != 32:
                sys.stderr.write('error: device error\n')
            else:
                data = array.array('B',rng[6+1:6+1+32]).tostring()
                sys.stdout.write(data)
                sys.stdout.flush()

def do_seed(h):
    cmd = cmd_prefix + [ commands.U2F_CUSTOM_SEED, 0,20]
    num = 0
    # typically runs around 414 bytes/s
    def signal_handler(signal, frame):
        print('seeded %i bytes' % num)
        sys.exit(0)
    signal.signal(signal.SIGINT, signal_handler)
    while True:
        # must be 20 bytes or less at a time
        c = sys.stdin.read(20)
        if not c:
            break
        buf = [ord(x) for x in c]
        h.write(cmd + buf)
        res = h.read(64, 1000)
        if not res or res[7] != 1:
            sys.stderr.write('error: device error\n')
        else:
            num += len(c)

    h.close()

def do_wipe(h):
    cmd = cmd_prefix + [ commands.U2F_CUSTOM_WIPE, 0,0]
    h.write(cmd)
    print( 'Press U2F button repeatedly until the LED is no longer red.')
    res = None
    while not res:
        res = h.read(64, 10000)
    if res[7] != 1:
        print( 'Wipe failed')
    else:
        print( 'Wipe succeeded')


    h.close()

def hexcode2bytes(color):
    h = [ord(x) for x in color.replace('#','').decode('hex')]
    return h

def do_wink(h):
    cmd = cmd_prefix + [ commands.U2F_CUSTOM_WINK, 0,0]
    h.write(cmd)




if __name__ == '__main__':
    action = sys.argv[1].lower()
    h = None
    SN = None
    wkey = None
    rkey = None
    if '-s' in sys.argv:
        if sys.argv.index('-s') + 1 > len(sys.argv):
            print('need serial number')
            sys.exit(1)
        SN = sys.argv[sys.argv.index('-s') + 1]

    if '-w' in sys.argv:
        if sys.argv.index('-w') + 1 > len(sys.argv):
            print('need wkey after -w')
            sys.exit(1)
        wkey_hex = sys.argv[sys.argv.index('-w') + 1]
        wkey = [ord(x) for x in binascii.unhexlify(wkey_hex)]

    if '-r' in sys.argv:
        if sys.argv.index('-r') + 1 > len(sys.argv):
            print('need rkey after -r')
            sys.exit(1)
        rkey_hex = sys.argv[sys.argv.index('-r') + 1]
        rkey = [ord(x) for x in binascii.unhexlify(rkey_hex)]

    if action == 'configure':
        h = open_u2f(SN)
        if len(sys.argv) < 4:
            print( 'error: need ecc private key and an output file')
            h.close()
            sys.exit(1)
        do_configure(h, sys.argv[2], sys.argv[3], wkey, rkey)
    elif action == 'rng':
        h = open_u2f(SN)
        do_rng(h)
    elif action == 'seed':
        h = open_u2f(SN)
        do_seed(h)
    elif action == 'wipe':
        h = open_u2f(SN)
        do_wipe(h)
    elif action == 'list':
        do_list()
    elif action == 'wink':
        h = open_u2f(SN)
        do_wink(h)
    elif action == 'bootloader':
        h = open_u2f(SN)
        bootloader(h)
    elif action == 'bootloader-destroy':
        h = open_u2f(SN)
        bootloader_destroy(h)
    else:
        print( 'error: invalid action: ', action)
        sys.exit(1)

    if h is not None: h.close()




