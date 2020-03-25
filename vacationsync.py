#!/opt/XXXXXX/utils/XXXXXX-python/python3/bin/python3


#https://github.com/O365/python-o365#usage
import O365
import json
import datetime as dt
from dateutil.relativedelta import relativedelta
import csv
import ssl
import warnings
import contextlib
import logging



#The destructive flag is bugged at the moment and will leave only 1 entry per day. 
destructive = True
config_path = 'o365.json'


#Log level for submodules. Change this to see messages from O365 module
logging.root.setLevel(logging.WARNING)
logging.basicConfig(format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)
#Log level for my logs.
logger.setLevel(logging.INFO)

import requests
from urllib3.exceptions import InsecureRequestWarning
old_merge_environment_settings = requests.Session.merge_environment_settings

@contextlib.contextmanager
def no_ssl_verification():
    opened_adapters = set()

    def merge_environment_settings(self, url, proxies, stream, verify, cert):
        # Verification happens only once per connection so we need to close
        # all the opened adapters once we're done. Otherwise, the effects of
        # verify=False persist beyond the end of this context manager.
        opened_adapters.add(self.get_adapter(url))

        settings = old_merge_environment_settings(self, url, proxies, stream, verify, cert)
        settings['verify'] = False

        return settings

    requests.Session.merge_environment_settings = merge_environment_settings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', InsecureRequestWarning)
            yield
    finally:
        requests.Session.merge_environment_settings = old_merge_environment_settings

        for adapter in opened_adapters:
            try:
                adapter.close()
            except:
                pass

with open(f'{config_path}') as config_file:
    config = json.load(config_file)


csv_path = config['csv_path']
credentials = (config['application_client_id'], config['application_client_secret'])

account = O365.Account(credentials, auth_flow_type='credentials', tenant_id=config['application_tenant_id'] )
if account.authenticate():
   logger.info('Authenticated!')

def query_specific_date(calendar, startdate, enddate):
    logger.debug(f'Querying Calendar for date: {startdate} - {enddate}')
    query = calendar.new_query('start').greater_equal(startdate)
    query.chain('and').on_attribute('end').less_equal(enddate)
    return calendar.get_events(query=query)

def manipulate_vacationdata(csvdata):
    vacation_dictionary = {}
    count = 1
    for row in csvdata:
        startdate = dt.datetime.strptime(row["StartDate"], '%m/%d/%Y %I:%M:%S %p')
        enddate = dt.datetime.strptime(row["EndDate"], '%m/%d/%Y %I:%M:%S %p')
        vacation_dictionary[f'{count}'] = { 
                                            'subject': f'{row["FirstName"]} {row["LastName"]}',
                                            'startdate' : startdate,
                                            'enddate' : enddate,
                                            'length' : row["Quantity"]
                                            }
        count+=1
    return vacation_dictionary


def main():
    with open(f'{csv_path}') as vacation_file:
        vacationcsv = csv.DictReader(vacation_file)
        vacations = manipulate_vacationdata(vacationcsv)
    #Bypass the man in the middle 
    with no_ssl_verification():
        schedule = account.schedule(resource='Calendar@XXXX.com')
        calendar = schedule.get_default_calendar()
        #Cleanup.
        if destructive:
            daterangestart = vacations['1']['startdate']
            daterangeend_key = list(vacations.keys())[-1]
            daterangeend = vacations[f"{daterangeend_key}"]['startdate']
            totalrange = (daterangeend - daterangestart).days + 1
            logger.warning(f'Destructive flag set. Deleting events from {daterangestart} - {daterangeend}')
            for day_number in range(totalrange):
                scheduled_events = query_specific_date(calendar, (daterangestart + dt.timedelta(days = day_number)).date(), (daterangestart + dt.timedelta(days = (day_number + 1) )).date())
                for event in scheduled_events:
                    event.delete()
                    logger.debug('Event Deleted')

        for key, vacation in vacations.items():
            if float(vacation['length']) == 0.5:
                subject = f'{vacation["subject"]} / Half Day'
            else:
                subject = vacation['subject']
            logger.info(f'\n\nEvent Creation: {subject}\nStart: {vacation["startdate"]}\nEnd: {vacation["enddate"]}\nLength: {vacation["length"]}')
            new_event = calendar.new_event()
            new_event.subject = subject
            new_event.start = vacation['startdate']
            new_event.end = vacation['enddate']
            new_event.save()

        
if __name__ == '__main__':
    main()
