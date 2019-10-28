from __future__ import unicode_literals

import os
import glob
import sys
import datetime
import logging
import subprocess
from . import eeUtil
import rasterio as rio
from affine import Affine
import numpy as np
from rasterio.crs import CRS
import requests
import time

LOG_LEVEL = logging.INFO
CLEAR_COLLECTION_FIRST = False
VERSION = '3.0'

# constants for bleaching alerts
SOURCE_URL = 'https://acdisc.gesdisc.eosdis.nasa.gov/data/Aqua_AIRS_Level3/AIRS3C2M.005/{year}/'
DATE_FORMAT = '%Y%m'
# Test how to download these files
# Have to set environmental variables

ASSET_NAME = 'cli_012_co2_concentrations_{date}'

# Read from data
NODATA_VALUE = -9999
DATA_TYPE = np.float32 # Byte/Int16/UInt16/UInt32/Int32/Float32/Float64/CInt16/CInt32/CFloat32/CFloat64

DATA_DIR = 'data'
GS_PREFIX = 'cli_012_co2_concentrations'
EE_COLLECTION = 'cli_012_co2_concentrations'

# Times two because of North / South parallels
MAX_YEARS = 5
MAX_DATES = MAX_YEARS*12
DATE_FORMAT = '%Y%m'
TIMESTEP = {'days': 30}

GCS_JSON = os.getenv('GCS_JSON') or os.getenv('GEE_JSON')

# environmental variables
with open('gcsPrivateKey.json','w') as f:
    f.write(GCS_JSON)

GEE_SERVICE_ACCOUNT = os.environ.get("GEE_SERVICE_ACCOUNT")
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS")
GEE_STAGING_BUCKET = os.environ.get("GEE_STAGING_BUCKET")
GCS_PROJECT = os.environ.get("CLOUDSDK_CORE_PROJECT")

NASA_USER = os.environ.get("EARTHDATA_USER")
NASA_PASS = os.environ.get("EARTHDATA_KEY")
DATASET_ID = '68455cb5-bfe3-4528-83a2-00fab1c52fb9'

def getLastUpdate(dataset):
    apiUrl = 'http://api.resourcewatch.org/v1/dataset/{}'.format(dataset)
    r = requests.get(apiUrl)
    lastUpdateString=r.json()['data']['attributes']['dataLastUpdated']
    nofrag, frag = lastUpdateString.split('.')
    nofrag_dt = datetime.datetime.strptime(nofrag, "%Y-%m-%dT%H:%M:%S")
    lastUpdateDT = nofrag_dt.replace(microsecond=int(frag[:-1])*1000)
    return lastUpdateDT

def getLayerIDs(dataset):
    apiUrl = 'http://api.resourcewatch.org/v1/dataset/{}?includes=layer'.format(dataset)
    r = requests.get(apiUrl)
    layers = r.json()['data']['attributes']['layer']
    layerIDs =[]
    for layer in layers:
        if layer['attributes']['application']==['rw']:
            layerIDs.append(layer['id'])
    return layerIDs

def flushTileCache(layer_id):
    """
    This function will delete the layer cache built for a GEE tiler layer.
     """
    apiUrl = 'http://api.resourcewatch.org/v1/layer/{}/expire-cache'.format(layer_id)
    headers = {
    'Content-Type': 'application/json',
    'Authorization': os.getenv('apiToken')
    }
    try_num=1
    tries=4
    while try_num<tries:
        try:
            r = requests.delete(url = apiUrl, headers = headers, timeout=1000)
            if r.ok or r.status_code==504:
                logging.info('[Cache tiles deleted] for {}: status code {}'.format(layer_id, r.status_code))
                return r.status_code
            else:
                if try_num < (tries-1):
                    logging.info('Cache failed to flush: status code {}'.format(r.status_code))
                    time.sleep(60)
                    logging.info('Trying again.')
                else:
                    logging.error('Cache failed to flush: status code {}'.format(r.status_code))
                    logging.error('Aborting.')
            try_num += 1
        except Exception as e:
            logging.error('Failed: {}'.format(e))

def lastUpdateDate(dataset, date):
   apiUrl = 'http://api.resourcewatch.org/v1/dataset/{0}'.format(dataset)
   headers = {
   'Content-Type': 'application/json',
   'Authorization': os.getenv('apiToken')
   }
   body = {
       "dataLastUpdated": date.isoformat()
   }
   try:
       r = requests.patch(url = apiUrl, json = body, headers = headers)
       logging.info('[lastUpdated]: SUCCESS, '+ date.isoformat() +' status code '+str(r.status_code))
       return 0
   except Exception as e:
       logging.error('[lastUpdated]: '+str(e))

DATASET_ID = '68455cb5-bfe3-4528-83a2-00fab1c52fb9'

def lastUpdateDate(dataset, date):
    apiUrl = 'http://api.resourcewatch.org/v1/dataset/{0}'.format(dataset)
    headers = {
    'Content-Type': 'application/json',
    'Authorization': os.getenv('apiToken')
    }
    body = {
        "dataLastUpdated": date.isoformat()
    }
    try:
        r = requests.patch(url = apiUrl, json = body, headers = headers)
        logging.info('[lastUpdated]: SUCCESS, '+ date.isoformat() +' status code '+str(r.status_code))
        return 0
    except Exception as e:
        logging.error('[lastUpdated]: '+str(e))

def getAssetName(tif):
    '''get asset name from tif name, extract datetime and location'''
    date = getDate(tif)
    return os.path.join(EE_COLLECTION, ASSET_NAME.format(date=date))

def getDate(filename):
    '''get last 8 chrs of filename'''
    return os.path.splitext(os.path.basename(filename))[0][-6:]

def getNewTargetDates(exclude_dates):
    '''Get new dates excluding existing'''
    new_dates = []
    date = datetime.date.today()
    date.replace(day=15)
    for i in range(MAX_YEARS*12):
        date -= datetime.timedelta(**TIMESTEP)
        date.replace(day=15)
        datestr = date.strftime(DATE_FORMAT)
        if datestr not in exclude_dates:
            new_dates.append(datestr)
    return new_dates

def fetch(year):
    cmd = ' '.join(['wget','--user',NASA_USER,'--password',NASA_PASS,
                    '-r','-c','-nH','-nd','-np',
                    '-A','hdf,hdf.map.gz,hdf.xml',
                    SOURCE_URL.format(year=year)])

    subprocess.call(cmd, shell=True)
    logging.info('call to server: {}'.format(cmd))


def getDateFromSource(filename):
    dateinfo = filename.split('.')
    year = dateinfo[1]
    month = dateinfo[2]
    return('{year}{month}'.format(year=year,month=month))

def convert(filename, date):
    # https://gis.stackexchange.com/questions/58688/convert-from-hdf-to-geotiff
    '''Convert from hdf to GTIFF format, delete hdf file on hand'''
    new_filename = ASSET_NAME.format(date=date)
    data_filename = new_filename+'_data.tif'
    georef_filename = new_filename+'.tif'

    cmd = ' '.join(['gdal_translate','-of', 'GTIFF',
                    '\'HDF4_EOS:EOS_GRID:"{file}":CO2:mole_fraction_of_carbon_dioxide_in_free_troposphere\''.format(file=filename),
                    data_filename])
    subprocess.call(cmd, shell=True)

    with rio.open(data_filename, 'r') as src:
        data = src.read(indexes=1)
        # lats: -89.5, 88 to 60, in increments of 2
        # lons: -180 to 177.5, in increments of 2.5
        row_width=2.5
        column_height=-2
        row_rotation=0
        column_rotation=0
        upper_right_x=-180
        upper_right_y=90

        transform = Affine(row_width,row_rotation,upper_right_x,
                            column_rotation, column_height, upper_right_y)
        profile = {
            'driver': 'GTiff',
            'dtype': np.float32,
            'nodata': -9999,
            'width': data.shape[1],
            'height': data.shape[0],
            'count': 1,
            'crs': CRS({'init': 'EPSG:4326'}),
            'transform':transform,
            'tiled': True,
            'compress': 'lzw',
            'interleave': 'band'
        }
        with rio.open(georef_filename, "w", **profile) as dst:
            dst.write(data, indexes=1)

    return georef_filename

def clearDir():
    files = glob.glob('*')
    for file in files:
        os.remove(file)

def processNewData(existing_dates):
    '''fetch, process, upload, and clean new data'''
    # 1. Determine which years to read from the file
    target_dates = getNewTargetDates(existing_dates) or []
    logging.debug('Target dates: {}'.format(target_dates))
    # 2. Fetch datafiles
    logging.info('Fetching files')
    years = []
    for date in target_dates:
        years.append(date[0:4])
    years = set(years)
    logging.info(years)

    new_assets = []
    for year in years:
        clearDir()
        fetch(year)
        # 3. Convert files
        files = glob.glob('*.hdf')
        tifs = []
        for _file in files:
            date = getDateFromSource(_file)
            logging.info(date)
            logging.info(existing_dates)
            if date not in existing_dates:
                logging.info('Converting file: {}'.format(_file))
                tifs.append(convert(_file, date))

        # 3. Upload new files
        logging.info('Uploading files')
        dates = [getDate(tif) for tif in tifs]
        assets = [getAssetName(tif) for tif in tifs]
        eeUtil.uploadAssets(tifs, assets, GS_PREFIX, dates, dateformat=DATE_FORMAT, public=True, timeout=3000)
        new_assets.extend(assets)

    clearDir()
    return new_assets

def checkCreateCollection(collection):
    '''List assests in collection else create new collection'''
    if eeUtil.exists(collection):
        return eeUtil.ls(collection)
    else:
        logging.info('{} does not exist, creating'.format(collection))
        eeUtil.createFolder(collection, imageCollection=True, public=True)
        return []

def deleteExcessAssets(dates, max_assets):
    '''Delete assets if too many'''
    # oldest first
    dates.sort()
    if len(dates) > max_assets:
        for date in dates[:-max_assets]:
            eeUtil.removeAsset(getAssetName(date))

def get_most_recent_date(collection):
    existing_assets = checkCreateCollection(collection)  # make image collection if doesn't have one
    existing_dates = [getDate(a) for a in existing_assets]
    existing_dates.sort()
    most_recent_date = datetime.datetime.strptime(existing_dates[-1], DATE_FORMAT)
    return most_recent_date

def main():
    '''Ingest new data into EE and delete old data'''
    logging.basicConfig(stream=sys.stderr, level=LOG_LEVEL)
    logging.info('STARTING')

    # Initialize eeUtil
    eeUtil.init(GEE_SERVICE_ACCOUNT, GOOGLE_APPLICATION_CREDENTIALS,
                GCS_PROJECT, GEE_STAGING_BUCKET)

    if CLEAR_COLLECTION_FIRST:
        eeUtil.removeAsset(EE_COLLECTION, recursive=True)

    # 1. Check if collection exists and create
    existing_ids = checkCreateCollection(EE_COLLECTION)
    exclude_dates = [getDate(asset) for asset in existing_ids]
    logging.debug(exclude_dates)

    # 2. Process, stage, ingest, clean
    os.chdir('data')
    new_assets = processNewData(exclude_dates)

    # 3. Delete old assets

    logging.info('Existing assets: {}, new: {}, max: {}'.format(
        len(existing_ids), len(new_assets), MAX_DATES))
    deleteExcessAssets(existing_ids+new_assets,MAX_DATES)

    # Get most recent update date
    most_recent_date = get_most_recent_date(EE_COLLECTION)
    current_date = getLastUpdate(DATASET_ID)

    if current_date != most_recent_date:
        logging.info('Updating last update date and flushing cache.')
        # Update data set's last update date on Resource Watch
        lastUpdateDate(DATASET_ID, most_recent_date)
        # get layer ids and flush tile cache for each
        layer_ids = getLayerIDs(DATASET_ID)
        for layer_id in layer_ids:
            flushTileCache(layer_id)

    logging.info('SUCCESS')
