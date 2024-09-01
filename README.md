
# DNS Migration Script

This script automates the migration of DNS records from GoDaddy to AWS Route 53. It processes a list of domains, checks if they have DNS records in GoDaddy, and, if necessary, migrates those records to Route 53. The script also updates the nameservers in GoDaddy to point to the new Route 53 hosted zone.

## Features

- **Check GoDaddy DNS Records**: Verifies if a domain has existing DNS records in GoDaddy.
- **Route 53 Zone Management**: Creates a hosted zone in Route 53 if one doesn't already exist for the domain.
- **DNS Record Migration**: Migrates DNS records from GoDaddy to Route 53.
- **Nameserver Update**: Updates the nameservers in GoDaddy to reflect the new Route 53 nameservers.
- **MX Record Detection**: Checks if the domain supports email by identifying MX records.
- **Logging**: Provides detailed logging of the migration process.

## Prerequisites

### Libraries
- Python 3.10+
- Required Python packages listed in requirements.txt

You can install the required packages using pip:

```bash
pip3 install -r requirements
```

### GoDaddy and AWS Credentials

The script requires GoDaddy API credentials obtained from https://developer.godaddy.com .  These credentials must be provided to the script using environment variables.

You can set these in your shell:
```bash
export GD_API_KEY='your_godaddy_api_key'
export GD_API_SECRET='your_godaddy_api_secret'
```

Your AWS credentials can be either environment variables or a preconfigured AWS CLI profile.

Using AWS Access Keys, export the following environment variables
```bash
export AWS_ACCESS_KEY_ID="your_aws_access_key_id"
export AWS_SECRET_ACCESS_KEY="your_aws_secret_access_key"
```

Alternatively, you can use your existing AWS CLI profile
```bash
export AWS_PROFILE="your_aws_profile_name"
```

Optionally, ensure that your AWS credentials are functional using the AWS CLI
```bash
aws sts get-caller-identity
```


## Usage

The script can be run from the command line with the following arguments:

```bash
python dns_migration.py --domain-list domains.txt --output output.csv
```

### Command-Line Arguments

- `--domain-list` or `-d`: Path to the file containing the list of domains (default: `domains.txt`).
- `--output` or `-o`: Path to the output CSV file where the results will be saved (default: `output.csv`).

### Example Domain List File

The domain list file should be a CSV file containing a column named `Name` with the domains you want to process:

```
Name
example1.com
example2.com
example3.com
```

## Logging

The script logs its activities to both the console and a log file named `dns_migration.log`. The log file provides detailed information, which is useful for debugging and auditing purposes.

## Script Execution Flow

1. **Initialize Clients**: The script initializes the GoDaddy and Route 53 clients using the provided API credentials.
2. **Process Domains**: It reads the domains from the specified file and processes each domain.
3. **Check GoDaddy DNS**: For each domain, the script checks if DNS records exist in GoDaddy.
4. **Determine Migration Eligibility**: If the domain is eligible for migration (e.g., it has non-parked A records), it proceeds with the migration.
5. **Create Route 53 Hosted Zone**: If a hosted zone doesn't already exist in Route 53, it is created.
6. **Migrate DNS Records**: DNS records are migrated from GoDaddy to Route 53.
7. **Update GoDaddy Nameservers**: The nameservers in GoDaddy are updated to point to Route 53.
8. **Save Results**: The results of the migration process are saved to the specified output CSV file.

## Contributing

Please create a pull request with your changes and provide a clear description of why the change is needed.

## License

This code is licensed under the LGPL v3 license.