#!/usr/bin/env python3
#-------------------------------------------------------------------
# RadCalNet api client
#-------------------------------------------------------------------
# Copyright (C) 2022 Magellium <admin-radcalnet@magellium.fr>
# Valentin Samir <valentin.samir@magellium.fr>
# All rights reserved.
# 2024-02-06 :
# add format argument (ascii/nc) to choose RadCalNet format of files to be downloaded.

import os
import sys
import datetime
import requests
import argparse
from getpass import getpass


def parse_name(filename):
    site_instrument, year, doy, version = filename.split('_')
    return (site_instrument, int(year), int(doy), version)


class RadcalnetApi(object):
    url_base = "https://www.radcalnet.org/api/json/"

    def __init__(self, username, password):
        self.session = requests.session()
        self.session.auth = (username, password)
        # Fetch list of available sites
        r = self.session.get(self.url_base)
        r.raise_for_status()
        self.sites = [filename['name'] for filename in r.json()]

    def download_file(self, url, dest):
        """Download the file at URL into dest using class credentials for basic auth"""
        with self.session.get(url, stream=True) as r:
            r.raise_for_status()
            with open(dest + '.new', 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            os.rename(dest + '.new', dest)

    def get_files_list(self, site, date1, date2, fmt):
        if site not in self.sites:
            raise ValueError(
                "site {} unknown. Valid sites are {}".format(site, ", ".join(self.sites))
            )
        if date1 > date2:
            return []
        #ASCII or NetCDF
        if fmt.lower() not in ('ascii', 'nc'):
            return []
        subdir={'ascii': '/data/', 'nc': '/datanc/'}
        url = self.url_base + site + subdir[fmt.lower()]
        # get the list of all files for the site
        r = self.session.get(url)
        r.raise_for_status()
        filelist = [file['name'] for file in r.json()]
        #print(filelist)
        wanted_files = []
        doy1 = (date1 - datetime.datetime(date1.year, 1, 1, 0, 0)).days + 1
        doy2 = (date2 - datetime.datetime(date2.year, 1, 1, 0, 0)).days + 1

        for filename in filelist:
            try: # in NetCDF case parse_name fails for archive file, ex GONA01_archive_v04.09.nc
                site_instrument, year, doy, version = parse_name(filename)
                if date1.year == date2.year:
                    if year == date1.year and doy1 <= doy <= doy2:
                        wanted_files.append(filename)
                elif date1.year == year and doy1 <= doy:
                    wanted_files.append(filename)
                elif date2.year == year and doy <= doy2:
                    wanted_files.append(filename)
                elif date1.year < year < date2.year:
                    wanted_files.append(filename)
            except:
                unexpected = 1
        return {'url_base': url, 'filtered_files': wanted_files}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', '-u', required=True)
    parser.add_argument(
        '--password', '-p',
        help="Password can be provided using the RADCALNET_PASSWORD environnement variable"
    )
    parser.add_argument('--output-dir', '-o', required=True)
    parser.add_argument('--site', '-s', required=True)
    parser.add_argument(
        '--start-date',
        type=lambda s: datetime.datetime.strptime(s, '%Y-%m-%d'),
        required=True,
        help="Date format YYYY-MM-DD"
    )
    parser.add_argument(
        '--stop-date',
        type=lambda s: datetime.datetime.strptime(s, '%Y-%m-%d'),
        help="Date format YYYY-MM-DD"
    )
    parser.add_argument('--fmt', '-f', required=True,
                        help="format (ascii or nc)"
    )

    args = parser.parse_args()

    if not os.path.isdir(args.output_dir):
        print("Directory {!r} does not exists".format(args.output_dir))
        sys.exit(1)
    if args.fmt.lower() not in ('ascii', 'nc'):
        print("format must be ascii or nc")
        sys.exit(1)

    if args.password:
        password = args.password
    elif os.environ.get('RADCALNET_PASSWORD'):
        password = os.environ['RADCALNET_PASSWORD']
    else:
        password = getpass()
    try:
        api = RadcalnetApi(args.username, password)
    except requests.exceptions.HTTPError as error:
        print(error)
        sys.exit(1)
    try:
        liste = api.get_files_list(args.site, args.start_date, args.stop_date or datetime.datetime.now(), args.fmt)
    except ValueError as error:
        print(error)
        sys.exit(1)
    for filename in liste['filtered_files']:
        dest = os.path.join(args.output_dir, filename)
        if not os.path.isfile(dest):
            print(filename)
            api.download_file(liste['url_base'] + filename, dest)


if __name__ == "__main__":
    main()
