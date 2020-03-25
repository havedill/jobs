#!/opt/XXXXX/utils/XXXXX-python/python2.7/bin/python
import socket
import struct
import argparse
import csv
import select
import IN
import os
import sys
sys.path.append(os.path.dirname(os.path.realpath(__file__)) + '/../modules')
import locate_prodconfigs as loc
import XXXXX_parser
import re

parser = argparse.ArgumentParser()
parser = argparse.ArgumentParser(description='TCP/Multicast Data Bulk Testing Tool')
parser.add_argument("-csvpath", help="csv file path (Header of IP, Port)", type=str)
parser.add_argument("-tcp", help="Listen for TCP Data", action='store_true')
parser.add_argument("-udp", help="Listen for Multicast Data (Default)", action='store_true')
parser.add_argument("-i", help="Interface NAME to bind to (eth0)", type=str)
parser.add_argument("-cboec1", help="AUTO: Fully test CBOE C1 configurations on this box", action='store_true')
parser.add_argument("-cboec1dr", help="AUTO: Disaster Recovery testing for CBOE C1", action='store_true')
parser.add_argument("-quiet", help="Only print out FAILURE messages", action='store_true')
args = parser.parse_args()

if os.getuid() != 0:
    print '\nThis script must be run as root to open TCP sockets / scrape home dirs\n'
    exit()


def multicast_listen(mgroup, mport, interface):
    #Translate the interface name supplied into an IP
    if re.match('[0-9.]+', interface) is None:
        f = os.popen('ifconfig {0} | grep "inet\ addr" | cut -d: -f2 | cut -d" " -f1'.format(interface))
        interface=f.read().rstrip()
        
    #Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    #Allow mulitple sockets to use the same port #
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Windows workaround
    try:
        sock.bind((mgroup, mport))
    except socket.error:
        sock.bind(('', mport))

    #bind to the interface specified
    sock.setsockopt(socket.SOL_IP,socket.IP_ADD_MEMBERSHIP, socket.inet_aton(mgroup)+socket.inet_aton(interface))
    
    try:
        #5 second timeout
        ready = select.select([sock], [], [], 3)
        if ready[0]:
            #Attempt to pull some data in. This value is very small in case we are only getting heartbeats
            data = sock.recvfrom(8)
            if not args.quiet:
                print 'SUCCESS: {0}:{1}'.format(mgroup, mport)
        else:
            print 'FAILED: {0}:{1}'.format(mgroup, mport)
    except Exception as e:
        print 'Exeception on {0}:{1} {2}'.format(mgroup, mport, str(e))


def tcp_listen(tgroup, tport, interface):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, IN.SO_BINDTODEVICE, interface)
    sock.settimeout(5)

    try:
        sock.connect((tgroup, tport))
        if not args.quiet:
            print 'SUCCESS: {0}:{1}'.format(tgroup, tport)
    except:
        print 'FAILED: {0}:{1}'.format(tgroup, tport)


def looper(pairings):
    for pair in pairings:
        if args.tcp:
            tcp_listen(pair[0], int(pair[1]), args.i)
        else:
            multicast_listen(pair[0], int(pair[1]), args.i)


def auto_looper(pairings, interface='', tcp=False):
    #This function attempts to discover the proper interface with each loop for tcp connections
    for pair in pairings:
        if tcp:
            i_name = XXXXX_parser.discover_tcproute(pair[0])
            tcp_listen(pair[0], int(pair[1]), i_name)
        else:
            multicast_listen(pair[0], int(pair[1]), interface)


def create_testlist(filepaths):
    hostport = []
    for file in filepaths:
            #parser returns a list of lists.
        if '.yml' in file:
            hostport = hostport + (XXXXX_parser.parse_yml(file))
        else:
            hostport = hostport + (XXXXX_parser.parse_ini(file))
    return hostport


def dedupe_listobject(list):
    newlist = []
    for value in list:
        if value not in newlist:
            newlist.append(value)
    return newlist

  
if(args.csvpath and args.i):
    csvname = args.csvpath
    pairings = []
    with open(csvname, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            #print '{row}')
            pairings.append([row['IP'], row['Port']])
        print 'CSV File loaded the following IP/Port pairings: {0}'.format(pairings)
    looper(sorted(pairings))
        
elif args.cboec1 or args.cboec1dr:
    #Default Config File Names based on location
    if args.cboec1:
        config_filename_containing_mcast_interface = 'C1prod.cfg'
        tcp_connection_configs = ['CboeBatsSessions.cfg', 'C1_prod_spins.yml', 'C1_prod_spins_redundant.yml']
        mcast_connection_configs = ['C1_prod_distribution.yml']

    if args.cboec1dr:
        config_filename_containing_mcast_interface = 'C1prod_disaster_recovery.cfg'
        tcp_connection_configs = ['CboeBatsSessions_disaster_recovery.cfg', 'C1_prod_spins_disaster_recovery.yml']
        mcast_connection_configs = ['C1_prod_distribution_disaster_recovery.yml']

    binding_info = loc.locate_configs(name=config_filename_containing_mcast_interface)
    if not binding_info:
        raise Exception('Cannot find any {0}, which defines what interface to listen to multicast on'.format(config_filename_containing_mcast_interface))
    mcast_interface = XXXXX_parser.parse_multicastinterface(binding_info[0])

    for config in mcast_connection_configs:
        found_configs = loc.locate_configs(name=config)
        if not found_configs:
            print '\n\n WARNING: Unable to locate any configs with name {0}'.format(config)
        hostport = create_testlist(found_configs)
        testlist = sorted(dedupe_listobject(hostport))
        if testlist:
            print '\n\n=================== Multicast: {0} Interface: {1} ======================='.format(config, mcast_interface)
            auto_looper(testlist, interface=mcast_interface)

    for config in tcp_connection_configs:
        found_configs = loc.locate_configs(name=config)
        if not found_configs:
            print '\n\n WARNING: Unable to locate any configs with name {0}'.format(config)
        hostport = create_testlist(found_configs)
        testlist = sorted(dedupe_listobject(hostport))
        if testlist:
            print '\n\n=================== TCP: {0} ======================='.format(config)
            auto_looper(testlist, tcp=True)
            
else:
    parser.print_help()
    print 'You must specify the -csvpath and -i interface, or specify the -cboec1 flag for the current location'
