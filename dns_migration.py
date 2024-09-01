import json
import logging
import boto3
from godaddypy import Client, Account
from godaddypy.client import BadResponse
import uuid
import argparse
import pandas as pd
from time import sleep
from datetime import timedelta, datetime
import requests
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),             # Log to console
        logging.FileHandler('dns_migration.log')  # Log to a file
    ]
)
logger = logging.getLogger('DNSMigration')
logger.setLevel(logging.DEBUG)

# argparse configuration
argparser = argparse.ArgumentParser(description='Check DNS records for a domain')
argparser.add_argument('--domain-list', '-d', default='domains.txt', required=False, help='File containing the list of domains')
argparser.add_argument('--output', '-o', default='output.csv', required=False, help='Output file for the results')

try:
    opts = argparser.parse_args()
except Exception as e:
    logger.error(f"Error parsing arguments: {str(e)}")
    argparser.print_help()


DOMAIN_LIST_FILE = opts.domain_list
OUTPUT_FILE = opts.output

# Read GoDaddy API credentials from environment variables
GD_API_KEY = os.environ['GD_API_KEY']
GD_API_SECRET = os.environ['GD_API_SECRET']


class GoDaddyClient:
    wait_time = timedelta(milliseconds=1000) #1 second
    def __init__(self, client):
        self.client = client
        self.last_call_time = datetime.now()
    
    def _wait_until(self):
        time_since_last_call = datetime.now() - self.last_call_time
        if time_since_last_call < self.wait_time:
            time_to_wait = self.wait_time - time_since_last_call
            logger.debug(f"Waiting for {time_to_wait} seconds to avoid GoDaddy API limit")
            sleep(time_to_wait.total_seconds())
            self.last_call_time = datetime.now()

    def get_records(self, domain):
        self._wait_until()
        return self.client.get_records(domain)
    
    def update_domain(self, domain, **kwargs):
        self._wait_until()
        return self.client.update_domain(domain, **kwargs)

# Initialize the GoDaddy client
gd_account = Account(api_key=GD_API_KEY, api_secret=GD_API_SECRET)
gd_client = GoDaddyClient(Client(gd_account))
logger.info(f"GoDaddy API initialized")

r53_client = boto3.client('route53')
logger.info(f"Route 53 client initialized")


class Domain:
    def __init__(self, name: str):
        '''
        Initialize the Domain object with the given name.
        :param name: The name of the domain.
        '''
        self.name = name.lower().strip()
        self._r53_zone_id = None
        self.index = None
        self._records = None

    @property
    def records(self):
        try:
            if not self._records:
                self._records = gd_client.get_records(self.name)
        except BadResponse as e:
            self._records = []
        return self._records
    
    @property
    def r53_zone_id(self):
        '''
        Get the Route 53 hosted zone id for the domain.
        :return: The hosted zone id
        '''
        if self._r53_zone_id:
            return self._r53_zone_id

        try:
            hosted_zones = r53_client.list_hosted_zones_by_name(DNSName=self.name)
            for zone in hosted_zones['HostedZones']:
                if zone['Name'] == self.name + '.':
                    self._r53_zone_id = zone['Id']
                    break

        except r53_client.exceptions.InvalidInput or r53_client.exceptions.InvalidDomainName:
            logger.error(f"Zone {self.name} is not valid")

        return self._r53_zone_id

    @r53_zone_id.setter
    def r53_zone_id(self, value: str):
        self._r53_zone_id = value

    def gd_dns_exists(self):
        '''
        Check if the domain has DNS records in GoDaddy
        :return: True if the domain has DNS records in GoDaddy, False otherwise.
        '''
        if len(self.records) > 0:
            logger.info(f"Domain {self.name} has DNS records in GoDaddy")
            return True

        logger.info(f"Domain {self.name} does not have DNS records in GoDaddy")
        return False
       
        
    def requires_zone_migration(self):
        '''
        Check if the domain is eligible for migration to Route 53
        :return: True if the domain is eligible, False otherwise.
        '''
        if not self.gd_dns_exists():
            return False
        
        domain_parked = False

        for record in self.records:
            if record['name'] == '@' and record['type'] == 'A' and record['data'] == 'Parked':
                domain_parked = True
        
        if not domain_parked:
            logger.info(f"Domain {self.name} requires zone migration: apex record is not parked")
            return True

        if len(self.records) <= 6:
            logger.info(f"Domain {self.name} requires zone migration: more than the default 5 records found")
            return True
    
        return False

    def gd_update_nameservers(self, nameservers: list[str]):
        '''
        Update the NS records for the domain in GoDaddy
        :return: True on success, False otherwise
        '''
        try:
            gd_client.update_domain(self.name, nameServers = nameservers )
            logger.info(f"Updated NS records for {self.name} in GoDaddy to {nameservers}")
        except Exception as e:
            logger.error(f"Error updating NS records for {self.name} in GoDaddy: {str(e)}")
            return False
        
        return True

    def r53_zone_exists(self):
        '''
        Check if the domain zone exists in Route 53.
        :return: True if the zone exists, False otherwise.
        '''
        if self.r53_zone_id:
            logger.debug(f"Route 53 hosted zone for {self.name} already exists")
            return True

        logger.debug(f"Route 53 hosted zone for {self.name} does not exist")
        return False

    def r53_get_nameservers(self):
        '''
        Get the nameservers for the domain from Route 53.
        :return: A list of nameservers
        '''
        nameservers = []
        try:
            response = r53_client.get_hosted_zone(Id=self.r53_zone_id)
            nameservers = response['DelegationSet']['NameServers']
        except Exception as e:
            logger.error(f"Error getting nameservers for {self.name} from Route 53: {str(e)}")

        return nameservers

    def r53_create_zone(self):
        '''
        Create a new Route 53 hosted zone for the domain.
        :return: The hosted zone id
        '''
        logger.debug(f"Creating Route 53 hosted zone for {self.name}")
        try:
            response = r53_client.create_hosted_zone(
                Name=self.name,
                CallerReference=str(uuid.uuid4())
            )
            logger.info(f"Created Route 53 hosted zone for {self.name} with id {response['HostedZone']['Id']}")
            self.r53_zone_id = response['HostedZone']['Id']

        except r53_client.exceptions.HostedZoneAlreadyExists:
            logger.info(f"Route 53 hosted zone for {self.name} already exists")
        except Exception as e:
            logger.error(f"Error creating Route 53 hosted zone for {self.name}: {str(e)}")
    
        logger.debug(f"Route 53 hosted zone for {self.name} is {self.r53_zone_id}")
        return self.r53_zone_id
    
    def has_mx_records(self):
        for record in self.records:
            if record['type'] == 'MX':
                return True
        
        return False

    def r53_create_records(self):
        '''
        Create DNS records in Route 53 for the domain.
        :return: True on success, False otherwise
        '''

        # Dictionary to aggregate records by name and type
        aggregated_records = {}

        for record in self.records:
            if record['type'] in ['SOA', 'NS']:
                continue

            if record['type'] == 'A' and record['data'] == 'Parked':
                continue

            if record['type'] == 'CNAME' and record['name'] == '_domainconnect':
                continue

            if record['type'] == 'CNAME' and record['data'] == '@':
                record['data'] = self.name

            if record['type'] == 'A' and record['data'] == 'WebsiteBuilder Site':
                record['data'] = '76.223.105.230'

            # AWS does not support the @ symbol to represent the apex
            if record['name'] == '@':
                record['name'] = self.name
            else:
                # All records must contain the FQDN
                record['name'] = record['name'] + '.' + self.name

            if record['type'] == 'MX':
                record['data'] =  f"{record['priority']} {record['data']}"

            # Enclose TXT record values in double quotes
            if record['type'] == 'TXT':
                record['data'] = f'"{record["data"]}"'

            # Ensure SRV records are correctly formatted
            if record['type'] == 'SRV':
                if len(record['data'].split()) != 4:
                    logger.error(f"Invalid SRV record data for {record['name']}: {record['data']}")
                    continue

            # Aggregate records by name and type
            key = (record['name'], record['type'])
            if key not in aggregated_records:
                aggregated_records[key] = {
                    'Name': record['name'],
                    'Type': record['type'],
                    'TTL': record['ttl'],
                    'ResourceRecords': []
                }
            
            # Add the data to the aggregated records
            aggregated_records[key]['ResourceRecords'].append({'Value': record['data']})

        # Prepare the changes list for the ChangeResourceRecordSets API
        changes = [
            {
                'Action': 'UPSERT',
                'ResourceRecordSet': aggregated_record
            }
            for aggregated_record in aggregated_records.values()
        ]

        logger.debug(f"Creating DNS records for {self.name} in Route 53: {changes}")

        # Perform the batch update (create or update records)
        response = r53_client.change_resource_record_sets(
            HostedZoneId=self.r53_zone_id,
            ChangeBatch={
                'Changes': changes
            }
        )

        return response

# Read domains from file and process them
def get_domains_list(file_path):
    '''
    Read domains from a file and return a list of domains.
    :param file_path: The path to the file with the list of domains.
    :return: A list of domains.
    '''
    try:
        with open(file_path, 'r') as file:
            domains = [line.strip() for line in file.readlines()]
        
        return domains
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
    except Exception as e:
        logger.error(f"An error occurred while processing domains: {str(e)}")
    
    return []

if __name__ == "__main__":
    #domains = get_domains_list(DOMAIN_LIST_FILE)
    domains = []
    domains_data = pd.read_csv(DOMAIN_LIST_FILE)
    
    # iterate over domains and print each name
    for index, row in domains_data.iterrows():
        domain = Domain(row['Name'])
        domain.index = index
        domains.append(domain)

    for domain in domains:
        logger.info(f"Processing domain: {domain.name}")
        domains_data.at[domain.index, 'Has GoDaddy DNS'] = "Yes" if domain.gd_dns_exists() else "No"
        if domain.requires_zone_migration():
            domains_data.at[domain.index, 'Requires DNS Migration'] = 'Yes'
            
            if not domain.r53_zone_exists():
                domain.r53_create_zone()
            
            domains_data.at[domain.index, 'AWS Zone ID'] = domain.r53_zone_id
            domain.r53_create_records()
            domains_data.at[domain.index, 'AWS DNS Records Created'] = 'Yes'

            nameservers = domain.r53_get_nameservers()
            if nameservers:
                domain.gd_update_nameservers(nameservers)
        else:
            domains_data.at[domain.index, 'Requires DNS Migration'] = 'No'
            domains_data.at[domain.index, 'AWS DNS Records Created'] = 'No'
        
        domains_data.at[domain.index, 'Supports Email'] = "Yes" if domain.has_mx_records() else "No"
    
    domains_data.to_csv(OUTPUT_FILE, index=False)
    logger.info(f"Domains processed: {os.linesep} {domains_data}")
    logger.info("Script execution completed.")
