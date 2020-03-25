
#!/opt/XXXXX/utils/XXXXX-python/python3/bin/python3

import json
import argparse
import pynetbox
import re
import os
import logging
from ipaddress import IPv4Network

#logging.basicConfig(filename='netbox_sync.log',level=logging.DEBUG)
logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)

parser = argparse.ArgumentParser()
parser = argparse.ArgumentParser(description='Tool that updates hosts on Netbox')
parser.add_argument("--hostname", help="Host to update", type=str, required=False)
parser.add_argument("--config", help="JSON Configuration file that contains Auth Token and Server URL values", type=str, required=True)
parser.add_argument("--factpath", help="Folder path containing output from netbox", required=True)
args = parser.parse_args()

ignore_interfaces = ['lo', 'usb.*', '.*tun.*']
regex_filter = "(" + ")|(".join(ignore_interfaces) + ")"


VMvaluemapping= {
    #Ansible Tree Key : #Netbox Key
    'ansible_processor_vcpus': 'vcpus',
    'ansible_memtotal_mb': 'memory',
    'ansible_processor_threads_per_core': { 'custom_fields': 'hyperthreading'},
    'ansible_processor_count': { 'custom_fields': 'cpusockets'},
    'ansible_kernel': { 'custom_fields': 'kernel'},
    'ansible_distribution_version': { 'custom_fields': 'linuxdistribution'},
    'ansible_dns' : { 'nameservers': {'custom_fields':'dnsservers'}, 'search': {'custom_fields' : 'dnssearch'}}
}

HDvaluemapping = {
    #Ansible Tree Key : #Netbox Key
    'ansible_processor_cores': { 'custom_fields': 'cores' },
    'ansible_memtotal_mb': { 'custom_fields': 'memory' },
    'ansible_processor_threads_per_core': { 'custom_fields': 'hyperthreading'},
    'ansible_processor_count': { 'custom_fields': 'cpusockets'},
    'ansible_product_serial': 'serial',
    'ansible_kernel': { 'custom_fields': 'kernel'},
    'ansible_distribution_version': { 'custom_fields': 'linuxdistribution'},
    'ansible_dns' : { 'nameservers': {'custom_fields':'dnsservers'}, 'search': {'custom_fields' : 'dnssearch'}}
}

local_valuemapping = {
    #file.fact name :{ netbox_field_name }
    'dnsalias' : 'custom_fields',
    'onload' : 'custom_fields'
}

with open(f'{args.config}') as config_file:
    config = json.load(config_file)

nb = pynetbox.api(config['api_endpoint'], token=f'{config["token"]}')


def parse_json(filepath):
    logging.debug(f'Parsing: {filepath}')
    hostinfo = ''
    try:
        with open(f'{args.factpath}/{filepath}') as f:
            hostinfo = json.load(f)
    except Exception as e:
        logging.critical(f'{filepath} WAS UNABLE TO BE LOADED')
        
    return hostinfo




def update_host(hostname, values):
    logging.info(f'Starting to gather update values for {hostname}')
    try:
        logging.debug(values['ansible_product_name'])
    except:
        logging.critical(f'Couldnt grab ansible_product_name from {hostname}, skipping')
        return
    updatedict = {}
    valuemapping = {}

    if 'VMware' in values['ansible_product_name'] or 'Virtual' in values['ansible_product_name']:
        valuemapping = VMvaluemapping
        nbhost = nb.virtualization.virtual_machines.get(name=hostname)
    else:
        valuemapping = HDvaluemapping
        nbhost = nb.dcim.devices.get(name=hostname)
    
    try:
        nbdict = dict(nbhost)
        #logging.debug(nbdict)
    except:
        logging.critical(f'Error getting {hostname} from netbox - NOT UPDATING.')
        badhosts.append(hostname)
        return
    for v in values:
        #Ansible local values have special recursion
        if 'ansible_local' in v:
            local_values = values[v]
            logging.debug(f'Local Values: {local_values}')
            for local_fact in local_values:
                if local_fact in local_valuemapping:
                    logging.debug(f'Found local fact {local_fact}, value {local_values[local_fact]["main"]}')
                    #strip this stupid big dictionary down to something manageable 
                    for fact_key, fact_value in local_values[local_fact]['main'].items():
                        logging.debug(f'{fact_key} {fact_value}')
                        mapping_key = local_valuemapping[local_fact]
                        if mapping_key not in updatedict:
                            updatedict[mapping_key] = nbdict[key]
                            logging.debug(f'Copied current {mapping_key} to updatedict for modification: {updatedict[mapping_key]}')
                        nbvalue = nbdict[mapping_key][fact_key]
                        logging.debug(f'Current netbox value was {nbvalue}')
                        if fact_value != nbvalue:
                            logging.info(f'Values Differ, Updating dictionary')
                            updatedict[mapping_key].update({ fact_key : fact_value })
            continue
        if v in valuemapping:
            if type(valuemapping[v]) == dict and len(valuemapping[v]) == 1:
                    #We need to submit the FULL dictionary back to netbox, or any manually entered stuff will be deleted when we update
                    for key, value in valuemapping[v].items():
                        logging.debug(f'Working with key: {key}')
                        if key not in updatedict:
                            updatedict[key] = nbdict[key]
                            logging.debug(f'Copying current {key} to updatedict for modification: {updatedict[key]}')
                        logging.debug(value)
                        nbvalue = nbdict[key][value]    
            elif type(valuemapping[v]) == dict and len(valuemapping[v]) > 1:
                logging.debug('Working with an ansible key that has children.')
                child_values = values[v]
                logging.debug(f'{child_values}')
                for dictionarykey, dictionaryvalue in valuemapping[v].items():
                    #nameservers: {custom_fields, dns servers}
                    if not dictionarykey in child_values:
                        logging.debug(f'Did not find {dictionarykey} in child_values: {child_values}')
                        continue
                    for childkey, childvalue in valuemapping[v][dictionarykey].items():
                        #custom_fields, dnsservers
                        if childkey not in updatedict:
                            updatedic[childkey] = nbdict[childkey]
                        nbvalue = nbdict[childkey][childvalue]
                        
                        logging.debug(f'ChildKey: {childkey} ChildValue: {childvalue} AnsibleValue: {child_values[dictionarykey]} NetboxValue: {nbvalue}')
                        if nbvalue != child_values[dictionarykey]:
                            updatedict[childkey].update({ childvalue : child_values[dictionarykey] })
                continue
            else:
                nbvalue = nbdict[valuemapping[v]]
            

            logging.debug(f'Found Value {v} mapping to {valuemapping[v]}\nCurrent Netbox Value (to be overwritten): {nbvalue}')
            if values[v] != nbvalue:
                if type(valuemapping[v]) == dict:
                    for key, value in valuemapping[v].items():
                        if key in updatedict:
                            updatedict[key].update({ value : values[v]})
                        else:
                            updatedict[key] = { value : values[v]}
                else:
                    updatedict[valuemapping[v]] = values[v]
    logging.info(f'Updating {hostname}')
    logging.debug(f'{updatedict}')
    nbhost.update(updatedict)
    
def update_ip(hostname, values):
    vm = False
    if 'VMware' in values['ansible_product_name'] or 'Virtual' in values['ansible_product_name']:
        nbhost = nb.virtualization.virtual_machines.get(name=hostname)
        vm = True
    else:
        nbhost = nb.dcim.devices.get(name=hostname)


    for interface in values['ansible_interfaces']:
        if not re.match(regex_filter, interface):
            logging.debug(f'Tring {interface}')
            key = 'ansible_' + interface
            if key in values:
                logging.debug(f'Found ansible interface {key}')

                if 'ipv4' not in values[key]:
                    logging.debug(f'{key} doesnt have an IP address. We dont care about it')
                    continue

                ###################### INTERFACE CREATION / UPDATING
                interfacedic = {
                    'name': f'{interface}',
                    'enabled': f'{values[key]["active"]}',
                    'mtu': f'{values[key]["mtu"]}',
                    'mac_address': f'{values[key]["macaddress"]}'
                }
                if vm:
                    interfacedic['virtual_machine'] = { 'id' : nbhost.id }

                    if not nb.virtualization.interfaces.get(virtual_machine_id=f'{nbhost.id}',name=f'{interface}'):
                        logging.info(f'Creating a virutal interface with {interfacedic}')
                        nb.virtualization.interfaces.create(interfacedic)
                    nbiface = nb.virtualization.interfaces.get(virtual_machine_id=f'{nbhost.id}',name=f'{interface}')

                else:
                    interfacedic['device'] = { 'id' : nbhost.id }
                    if not nb.dcim.interfaces.get(device_id=f'{nbhost.id}',name=f'{interface}'):
                        logging.info(f'Creating a physical interface with {interfacedic}')
                        nb.dcim.interfaces.create(interfacedic)
                    nbiface = nb.dcim.interfaces.get(device_id=f'{nbhost.id}',name=f'{interface}')
                logging.debug(f'Interface Info: {dict(nbiface)}')


                ############# IP ADDRESS CREATION 
                networkinfo = {}
                index = 0
                networkinfo = { 'network100' : {'ip': values[key]['ipv4']['address'], 'mask' : convert_tocidr(values[key]['ipv4']['netmask'])} }

                if 'ipv4_secondaries' in values[key]:
                    logging.debug(f'{key} has multiple addresses assigned to it')
                    for secondary in values[key]['ipv4_secondaries']:
                        networkinfo[f'network{index}'] = { 'ip' : values[key]['ipv4_secondaries'][index]['address'], 'mask' : convert_tocidr(values[key]['ipv4_secondaries'][index]['netmask']) }
                        index+=1

                logging.debug(networkinfo)
                for k, v in networkinfo.items():
                    ipdic = {
                        'address' : f'{networkinfo[k]["ip"]}/{networkinfo[k]["mask"]}',
                        'interface' : { 'id' : nbiface.id }
                     }
                    try:
                        nbip = nb.ipam.ip_addresses.get(address=networkinfo[k]["ip"])
                    except ValueError:
                        logging.critical(f'DUPLICATE IP DETECTED {networkinfo[k]["ip"]}')
                        continue
                    
                    if not nbip:
                        logging.info(f'{hostname}: Adding {networkinfo[k]["ip"]}/{networkinfo[k]["mask"]} to netbox')
                        nb.ipam.ip_addresses.create(ipdic)
                    elif ('interface' in nbip) and (nbip.interface.id != nbiface.id):
                        logging.warning(f'{hostname}: IP Detected, but interfaces differ. Found: {nbip.interface.id} Interface: {nbiface.id}')
                        nbip.interface.id = nbiface.id
                        nbip.save()
                    else:
                        nbip.save()


            
def convert_tocidr(mask):
    return IPv4Network(f'0.0.0.0/{mask}').prefixlen

def work_onhost(hostname):
    hostvalues = parse_json(hostname)
    if 'ansible_facts' not in hostvalues:
        logging.critical(f'{hostname} ANSIBLE dump is invalid')        
        badhosts.append(hostname)
        return
    #trim the dict down a little to make it easier to work with
    hostvalues = hostvalues['ansible_facts']
    update_host(hostname, hostvalues)
    update_ip(hostname, hostvalues)

badhosts = []
def main():
    if args.hostname:
        work_onhost(args.hostname)
    else:
        files = os.listdir(args.factpath)
        for f in files:
            work_onhost(f)
    if len(badhosts) > 0:
        logging.critical('HOSTS WITH PROBLEMS:\n{}'.format(*badhosts, sep="\n"))


if __name__ == '__main__':
    main()
