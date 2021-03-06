#!/usr/bin/python

"""NED.py: NED (National Elevation Dataset) preprocessing for TopOSM."""

import numpy
from os import path, system
from math import floor, ceil

from env import *
from common import *

from mapnik import Box2d


__author__      = "Lars Ahlzen"
__copyright__   = "(c) Lars Ahlzen 2008-2011"
__license__     = "GPLv2"

# Size (side length, in degrees) of NED tiles that are cut up into
# more manageable chunks.
STEP = 0.5

def getTilepath(basename):
    return os.path.join(
        NED13DIR, basename + '.tif')

def getTiles(envLL):
    """Gets the (basename, Box2d) of all (existing) 1/3 NED tiles
    to cover the specified Box2d"""
    fromx = int(floor(envLL.minx))
    tox = int(floor(envLL.maxx))
    fromy = int(ceil(envLL.miny))
    toy = int(ceil(envLL.maxy))
    tiles = []
    for y in range(fromy, toy+1):
        for x in range(fromx, tox+1):
            basename = 'n%02dw%03d' % (y, -x)
            tilepath = getTilepath(basename)
            print tilepath
            if path.isfile(tilepath):
                tiles.append((basename, Box2d(x, y-1, x+1, y)))
    return tiles

def getSlice(prefix, x, y, suffix = '.tif'):
    filename = prefix + '_%.1f_%.1f%s' % (float(x), float(y), suffix)
    return path.join(TEMPDIR, filename)

def getSlices(prefix, envLL, suffix = '.tif'):
    fromx = floor(envLL.minx/STEP)*STEP
    fromy = floor(envLL.miny/STEP)*STEP
    tox = ceil(envLL.maxx/STEP)*STEP
    toy = ceil(envLL.maxy/STEP)*STEP
    slices = []
    for y in numpy.arange(fromy, toy, STEP):
        for x in numpy.arange(fromx, tox, STEP):
            slicefile = getSlice(prefix, x, y, suffix)
            if path.isfile(slicefile):
                slices.append(slicefile)
    return slices

def getTilecoords(lat, lon, step = 1):
    return (int(ceil(lat/float(step)))*float(step), \
        int(floor(lon/float(step)))*float(step))

def getTilename(lat, lon, step = 1):
    (y, x) = get_ned13_tilecoords(lat, lon, step)
    if step == 1:
        return 'n%02dw%03d' % (y, -x)
    return 'n%02.2fw%03.2f' % (y, -x) 

def convertContourElevationsToFt():
    
    templ = 'UPDATE %s SET height_ft = CAST(height * 3.28085 AS INT)' + \
        ' WHERE height_ft IS NULL'
    sql = templ % (CONTOURS_TABLE)
    runSql(sql)

# NOTE: This removes a LOT of artifacts around shorelines. Unfortunately,
# it also removes any legitimate 0ft contours (which may exist around
# areas below sea-level).
# TODO: Find a better workaround.
def removeSeaLevelContours():
    sql = 'DELETE FROM %s WHERE height_ft = 0;' % (CONTOURS_TABLE)
    runSql(sql)

def simplifyContours(level = 1.0):
    sql = 'UPDATE %s SET way = ST_Simplify(way, %f);' % (CONTOURS_TABLE, level)
    runSql(sql)

def clusterContoursOnGeoColumn():
    sql = 'CLUSTER %s_way_gist ON %s;' % (CONTOURS_TABLE, CONTOURS_TABLE)
    runSql(sql)

def analyzeContoursTable():
    sql = 'ANALYZE %s;' % (CONTOURS_TABLE)
    runSql(sql)

def prepDataFile(basename, env):
    geotiff = getTilepath(basename)

    # split the GeoTIFF, since it's often too large otherwise
    for y in numpy.arange(env.miny, env.maxy, STEP):
        for x in numpy.arange(env.minx, env.maxx, STEP):       
            nedslice = getSlice('ned', x, y)
            if not path.isfile(nedslice):
                print '  Cutting geotiff slice...'
                cmd = 'gdalwarp -q -te %f %f %f %f "%s" "%s"' % \
                    (x, y, x+STEP, y+STEP, geotiff, nedslice)
                os.system(cmd)
            
            contourbasefile = path.join(TEMPDIR, 'contours_' + str(x) + '_' + str(y))
            contourfile = contourbasefile + '.shp'
            contourfileproj = contourbasefile + '_900913.shp'
            if not path.isfile(contourfile):
                print '  Generating contour lines...'
                cmd = 'gdal_contour -i %f -snodata 32767 -a height "%s" "%s"' % \
                    (CONTOUR_INTERVAL, nedslice, contourfile)
                os.system(cmd)

                print '  Reprojecting contour lines...'
                # NOTE: The s_srs is not required with most GDAL/OGR versions
                cmd = 'ogr2ogr -s_srs "%s" -t_srs "%s" -f "ESRI Shapefile" "%s" "%s"' % \
                    (NAD83_PROJECTION_DEF, MERCATOR_PROJECTION_DEF, \
                    contourfileproj, contourfile)
                os.system(cmd)

                print '  Importing contour lines...'
                # NOTE: this assumes that the table is already set up
                cmd = 'shp2pgsql -a -g way "%s" "%s" | psql -q "%s"' % \
                    (contourfileproj, CONTOURS_TABLE, DATABASE)
                os.system(cmd)
                
                # Clear contents (but keep file to prevent us from importing
                # these contours again).
                writeEmpty(contourfile)
                tryRemove(contourfileproj)
                tryRemove(contourbasefile + ".shx")
                tryRemove(contourbasefile + ".dbf")

            writeEmpty(nedslice) # don't need the raw slice anymore.
 
