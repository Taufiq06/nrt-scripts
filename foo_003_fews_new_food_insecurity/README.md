## Current and Projected Food Insecurity Dataset Near Real-time Script
This file describes the near real-time script that retrieves and processes the [Famine Early Warning Systems Network (FEWS NET) Food Security Classification dataset](http://www.fews.net/fews-data/333) for [display on Resource Watch](https://resourcewatch.org/data/explore/foo003nrt-Food-Insecurity_replacement).

{Describe how the original data came from the source.}

{Describe the steps used to process the data, e.g., "convert variable X from the original netcdf file to a tif to upload to Google Earth Engine."}

Please see the [Python script](https://github.com/resource-watch/nrt-scripts/blob/master/foo_003_fews_new_food_insecurity/contents/src/__init__.py) for more details on this processing.

**Schedule**

This script is run daily. The exact time that the script is run to update the dataset can be found in the the `time.cron` file. This time is in Coordinated Universal Time (UTC), expressed in cron format.

###### Note: This script was originally written by [Nathan Suberi](mailto:nathan.suberi@wri.org), and is currently maintained by [Amelia Snyder](https://www.wri.org/profile/amelia-snyder).
