import logging
import urllib
import hashlib
import zipfile
import time
import os
import asyncio

from .base import ProviderBase, ProviderSearchResultBase, ProviderError, parse_xml
from ..toolbox import db
from ..toolbox.net import download
from ..toolbox.utils import tempfile, tostr
from ..config import config

__all__ = ['Provider']

log = logging.getLogger('stagehand.providers.thetvdb')

class ProviderSearchResult(ProviderSearchResultBase):
    @property
    def pid(self):
        return self._attrs.get('seriesid')

    @property
    def name(self):
        return self._attrs.get('SeriesName')

    @property
    def names(self):
        yield self.name

    @property
    def overview(self):
        return self._attrs.get('Overview')

    @property
    def imdb(self):
        return self._attrs.get('IMDB_ID')

    @property
    def year(self):
        started = self.started
        if started and len(started.split('-')) == 3:
            return started.split('-')[0]
        else:
            return started

    @property
    def started(self):
        return self._attrs.get('FirstAired')


    @property
    def banner(self):
        if 'banner' in self._attrs:
            return self.provider.hostname + '/banners/' + self._attrs['banner']



class Provider(ProviderBase):
    NAME = 'thetvdb'
    NAME_PRINTABLE = 'TheTVDB'
    IDATTR = 'thetvdbid'
    CACHEATTR = 'thetvdbcache'

    def __init__(self, db):
        super().__init__(db)
        self.hostname = 'http://www.thetvdb.com'
        self._apikey = '1E9534A23E6D7DC0'
        self._apiurl = '%s/api/%s/' % (self.hostname, self._apikey)

        db.register_object_type_attrs('series',
            thetvdbid = (str, db.ATTR_SEARCHABLE | db.ATTR_INDEXED),
            thetvdbcache = (dict, db.ATTR_SIMPLE)
        )

        db.register_object_type_attrs('episode',
            thetvdbid = (str, db.ATTR_SEARCHABLE),
        )



    @asyncio.coroutine
    def search(self, name):
        results = []
        name = urllib.parse.quote(name.replace('.', ' ').replace('-', ' ').replace('_', ' '))
        url = self.hostname + '/api/GetSeries.php?seriesname=%s' % name
        log.info('fetching %s', url)
        for tag, attrs, data in (yield from parse_xml(url)):
            if tag == 'Series':
                results.append(ProviderSearchResult(self, data))
        return results


    @asyncio.coroutine
    def _get_api_zipfile(self, url):
        STAY_LOCAL = os.getenv('STAY_LOCAL', 0)
        tmpname = tempfile('stagehand', 'thetvdb-', '.zip')
        url = self._apiurl + url

        if STAY_LOCAL and os.path.exists(tmpname):
            status = 200
        else:
            # Try 3 times before giving up, unless it's a permanent error
            log.debug('fetching zip file %s', url)
            status, curl = yield from download(url, tmpname, retry=3, resume=False)
        if status != 200:
            if os.path.exists(tmpname):
                os.unlink(tmpname)
            raise ProviderError('thetvdb gave status %d for %s' % (status, url))

        try:
            z = zipfile.ZipFile(tmpname)
        except zipfile.BadZipfile:
            os.unlink(tmpname)
            raise ProviderError('invalid zip file from thetvdb at %s' % url)

        return z


    @asyncio.coroutine
    def get_series(self, id):
        STAY_LOCAL = os.getenv('STAY_LOCAL', 0)
        log.debug('retrieving series data for %s', id)
        if not self.get_last_updated():
            # DB doesn't know about server time.  Set to current time so that
            # subsequent calls to get_changed_series_ids() have a reference
            # point.
            self.db.set_metadata('thetvdb::servertime', int(time.time()))

        series = {'episodes': []}
        # TODO: if language doesn't exist, retry english.  Or (probaby better)
        # fetch and cache languages.xml and make sure the user choice is there.
        z = yield from self._get_api_zipfile('series/%s/all/%s.zip' % (id, config.misc.language.lower()))

        # Find the highest rated banner for the given language.
        banner = (-1, None)  # (rating, url)
        for tag, attrs, data in (yield from parse_xml(z.open('banners.xml'))):
            if tag != 'Banner' or data.get('BannerType') != 'series' or \
               data.get('Language', '').lower() != config.misc.language.lower():
                continue
            try:
                rating = float(data.get('Rating', 0))
            except ValueError:
                rating = 0.0

            if rating > banner[0] and 'BannerPath' in data:
                banner = rating, data['BannerPath']

        # Get series and episode data.
        for tag, attrs, data in (yield from parse_xml(z.open('%s.xml' % config.misc.language.lower()))):
            if tag == 'Series':
                try:
                    series['runtime'] = int(data['Runtime'])
                except (ValueError, KeyError):
                    pass
                try:
                    # XXX: is Airs_Time guaranteed to be well formatted?
                    # Should we be more robust?
                    timetuple = time.strptime(data.get('Airs_Time', ''), '%I:%M %p')
                    series['airtime'] = tostr(time.strftime('%H:%M', timetuple))
                except ValueError:
                    pass

                # Get any existing series and see if we need to fetch banner data.
                existing = self.db.get_series_by_id('thetvdb:' + data['id'])
                missing = not existing or not existing.banner_data
                if not STAY_LOCAL and banner[1] and (missing or not existing.banner.endswith(banner[1])):
                    # Need to fetch banner, either because it changed (different banner with
                    # a higher rating?) or because we never had one.
                    url = self.hostname + '/banners/' + banner[1]
                    log.debug('refresh series banner %s', url)
                    status, banner_data = yield from download(url, retry=3)
                    if status == 200:
                        series['banner_data'] = banner_data
                    else:
                        log.error('banner download failed for series %s', data.get('SeriesName', data['id']))

                from ..tvdb import Series
                status_str = data.get('Status', '').lower()
                if status_str.startswith('cont'):  # continuing
                    status = Series.STATUS_RUNNING
                elif status_str.startswith('on'):  # on hiaitus
                    status = Series.STATUS_SUSPENDED
                elif status_str.startswith('end'):  # ended
                    status = Series.STATUS_ENDED
                else:
                    status = Series.STATUS_UNKNOWN

                series.update({
                    'id': data['id'],
                    'name': data.get('SeriesName'),
                    'poster': self.hostname + '/banners/' + data['poster'] if data.get('poster') else None,
                    'banner': self.hostname + '/banners/' + tostr(banner[1]) if banner[1] else None,
                    'overview': data.get('Overview'),
                    'genres': [g.strip().lower() for g in data.get('Genre', '').split('|') if g],
                    # TODO: do a sanity check on FirstAired format.
                    'started': data.get('FirstAired'),
                    # TODO: use constants for status
                    'status': status,
                    'imdbid': data.get('IMDB_ID')
                })
            elif tag == 'Episode':
                series['episodes'].append({
                    'id': data['id'],
                    'name': data.get('EpisodeName'),
                    'season': int(data['SeasonNumber']),
                    'episode': int(data['EpisodeNumber']),
                    # TODO: do a sanity check on FirstAired format.
                    'airdate': data.get('FirstAired'),
                    'overview': data.get('Overview')
                })
            else:
                log.error('unknown element: %s', name)

        z.close()
        if not STAY_LOCAL:
            os.unlink(z.filename)
        return series


    @asyncio.coroutine
    def get_changed_series_ids(self):
        servertime = self.get_last_updated()
        if not servertime:
            # No servertime stored, so there must not be any series in db.
            return
        ids = []
        now = int(time.time())

        # Grab all series ids currently in the DB.
        series = set([o[self.IDATTR] for o in self.db.query(type='series', attrs=[self.IDATTR])])
        if now - servertime < 60*60*24:
            update_file = 'updates_day'
        elif now - servertime < 60*60*24*7:
            update_file = 'updates_week'
        elif now - servertime < 60*60*24*28:
            update_file = 'updates_month'
        else:
            # Haven't updated in over a month, so refresh all series.
            self.db.set_metadata('thetvdb::servertime', now)
            return list(series)

        # Fetch updates
        z = yield from self._get_api_zipfile('updates/%s.zip' % update_file)
        for tag, attrs, data in (yield from parse_xml(z.open('%s.xml' % update_file), nest=['Data'])):
            if tag == 'Series' and data['id'] in series:
                if 'time' not in data or int(data['time']) >= servertime:
                    ids.append(data['id'])
        self.db.set_metadata('thetvdb::servertime', now)
        log.debug('set servertime %s', now)
        z.close()
        os.unlink(z.filename)
        return ids


    def get_last_updated(self):
        return int(self.db.get_metadata('thetvdb::servertime', 0))
