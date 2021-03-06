# -*- coding: iso-8859-1 -*-
# -----------------------------------------------------------------------------
# mp4.py - mp4/mov file parser
# -----------------------------------------------------------------------------
# $Id$
#
# -----------------------------------------------------------------------------
# kaa-Metadata - Media Metadata for Python
# Copyright (C) 2003-2007 Thomas Schueppel, Dirk Meyer
#
# First Edition: Thomas Schueppel <stain@acm.org>
# Maintainer:    Dirk Meyer <dischi@freevo.org>
#
# Please see the file AUTHORS for a complete list of authors.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MER-
# CHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
#
# -----------------------------------------------------------------------------

__all__ = ['Parser']

# python imports
import zlib
import logging
import io
import struct

# import kaa.metadata.video core
from . import core

# get logging object
log = logging.getLogger('metadata')


# http://developer.apple.com/documentation/QuickTime/QTFF/index.html
# http://developer.apple.com/documentation/QuickTime/QTFF/QTFFChap4/\
#     chapter_5_section_2.html#//apple_ref/doc/uid/TP40000939-CH206-BBCBIICE
# Note: May need to define custom log level to work like ATOM_DEBUG did here

QTUDTA = {
    b'nam': 'title',
    b'aut': 'artist',
    b'cpy': 'copyright'
}

QTLANGUAGES = {
    0 : "en",
    1 : "fr",
    2 : "de",
    3 : "it",
    4 : "nl",
    5 : "sv",
    6 : "es",
    7 : "da",
    8 : "pt",
    9 : "no",
    10 : "he",
    11 : "ja",
    12 : "ar",
    13 : "fi",
    14 : "el",
    15 : "is",
    16 : "mt",
    17 : "tr",
    18 : "hr",
    19 : "Traditional Chinese",
    20 : "ur",
    21 : "hi",
    22 : "th",
    23 : "ko",
    24 : "lt",
    25 : "pl",
    26 : "hu",
    27 : "et",
    28 : "lv",
    29 : "Lappish",
    30 : "fo",
    31 : "Farsi",
    32 : "ru",
    33 : "Simplified Chinese",
    34 : "Flemish",
    35 : "ga",
    36 : "sq",
    37 : "ro",
    38 : "cs",
    39 : "sk",
    40 : "sl",
    41 : "yi",
    42 : "sr",
    43 : "mk",
    44 : "bg",
    45 : "uk",
    46 : "be",
    47 : "uz",
    48 : "kk",
    49 : "az",
    50 : "AzerbaijanAr",
    51 : "hy",
    52 : "ka",
    53 : "mo",
    54 : "ky",
    55 : "tg",
    56 : "tk",
    57 : "mn",
    58 : "MongolianCyr",
    59 : "ps",
    60 : "ku",
    61 : "ks",
    62 : "sd",
    63 : "bo",
    64 : "ne",
    65 : "sa",
    66 : "mr",
    67 : "bn",
    68 : "as",
    69 : "gu",
    70 : "pa",
    71 : "or",
    72 : "ml",
    73 : "kn",
    74 : "ta",
    75 : "te",
    76 : "si",
    77 : "my",
    78 : "Khmer",
    79 : "lo",
    80 : "vi",
    81 : "id",
    82 : "tl",
    83 : "MalayRoman",
    84 : "MalayArabic",
    85 : "am",
    86 : "ti",
    87 : "om",
    88 : "so",
    89 : "sw",
    90 : "Ruanda",
    91 : "Rundi",
    92 : "Chewa",
    93 : "mg",
    94 : "eo",
    128 : "cy",
    129 : "eu",
    130 : "ca",
    131 : "la",
    132 : "qu",
    133 : "gn",
    134 : "ay",
    135 : "tt",
    136 : "ug",
    137 : "Dzongkha",
    138 : "JavaneseRom",
}

class MPEG4(core.AVContainer):
    """
    Parser for the MP4 container format. This format is mostly
    identical to Apple Quicktime and 3GP files. It maps to mp4, mov,
    qt and some other extensions.
    """
    table_mapping = { 'QTUDTA': QTUDTA }

    def __init__(self,file):
        core.AVContainer.__init__(self)
        self._references = []

        self.mime = 'video/quicktime'
        self.type = 'Quicktime Video'
        h = file.read(8)
        try:
            (size,type) = struct.unpack('>I4s',h)
        except struct.error:
            # EOF.
            raise core.ParseError()

        if type == b'ftyp':
            # file type information
            if size >= 12:
                # this should always happen
                if file.read(4) != b'qt  ':
                    # not a quicktime movie, it is a mpeg4 container
                    self.mime = 'video/mp4'
                    self.type = 'MPEG-4 Video'
                size -= 4
            file.seek(size-8, 1)
            h = file.read(8)
            (size,type) = struct.unpack('>I4s',h)

        while type in (b'mdat', b'skip', b'pnot', b'PICT') and size > 0:
            # movie data at the beginning, skip
            file.seek(size-8, 1)
            h = file.read(8)
            (size,type) = struct.unpack('>I4s',h)

        if not type in (b'moov', b'wide', b'free'):
            log.debug('invalid header: %r' % type)
            raise core.ParseError()

        # Extended size
        if size == 1:
            size = struct.unpack('>Q', file.read(8))

        # Back over the atom header we just read, since _readatom expects the
        # file position to be at the start of an atom.
        file.seek(-8, 1)
        while self._readatom(file):
            pass

        if self._references:
            self._set('references', self._references)


    def _readatom(self, file):
        s = file.read(8)
        if len(s) < 8:
            return 0

        atomsize,atomtype = struct.unpack('>I4s', s)
        if not atomtype.isalnum():
            # stop at nonsense data
            return 0

        log.debug('%s [%X]' % (atomtype,atomsize))

        if atomtype == b'udta':
            # Userdata (Metadata)
            pos = 0
            tabl = {}
            i18ntabl = {}
            atomdata = file.read(atomsize-8)
            while pos < atomsize-12:
                (datasize, datatype) = struct.unpack('>I4s', atomdata[pos:pos+8])
                if datatype[0] == 169:
                    # i18n Metadata...
                    mypos = 8+pos
                    while mypos + 4 < datasize+pos:
                        # first 4 Bytes are i18n header
                        (tlen, lang) = struct.unpack('>HH', atomdata[mypos:mypos+4])
                        i18ntabl[lang] = i18ntabl.get(lang, {})
                        l = atomdata[mypos+4:mypos+tlen+4]
                        i18ntabl[lang][datatype[1:]] = l
                        mypos += tlen+4
                elif datatype == b'WLOC':
                    # Drop Window Location
                    pass
                else:
                    if atomdata[pos+8:pos+datasize][0] > 1:
                        tabl[datatype] = atomdata[pos+8:pos+datasize]
                pos += datasize
            if len(list(i18ntabl.keys())) > 0:
                for k in list(i18ntabl.keys()):
                    if k in QTLANGUAGES and QTLANGUAGES[k] == 'en':
                        self._appendtable('QTUDTA', i18ntabl[k])
                        self._appendtable('QTUDTA', tabl)
            else:
                log.debug('NO i18')
                self._appendtable('QTUDTA', tabl)

        elif atomtype == b'trak':
            atomdata = file.read(atomsize-8)
            pos = 0
            trackinfo = {}
            tracktype = None
            while pos < atomsize-8:
                (datasize, datatype) = struct.unpack('>I4s', atomdata[pos:pos+8])

                if datatype == b'tkhd':
                    tkhd = struct.unpack('>6I8x4H36xII', atomdata[pos+8:pos+datasize])
                    trackinfo['width'] = tkhd[10] >> 16
                    trackinfo['height'] = tkhd[11] >> 16
                    trackinfo['id'] = tkhd[3]

                    try:
                        # XXX Timestamp of Seconds is since January 1st 1904!
                        # XXX 2082844800 is the difference between Unix and
                        # XXX Apple time. FIXME to work on Apple, too
                        self.timestamp = int(tkhd[1]) - 2082844800
                    except Exception as e:
                        log.exception('There was trouble extracting timestamp')

                elif datatype == b'mdia':
                    pos      += 8
                    datasize -= 8
                    log.debug('--> mdia information')

                    while datasize:
                        mdia = struct.unpack('>I4s', atomdata[pos:pos+8])
                        if mdia[1] == b'mdhd':
                            # Parse based on version of mdhd header.  See
                            # http://wiki.multimedia.cx/index.php?title=QuickTime_container#mdhd
                            ver = atomdata[pos + 8]
                            if ver == 0:
                                mdhd = struct.unpack('>IIIIIhh', atomdata[pos+8:pos+8+24])
                            elif ver == 1:
                                mdhd = struct.unpack('>IQQIQhh', atomdata[pos+8:pos+8+36])
                            else:
                                mdhd = None

                            if mdhd:
                                # duration / time scale
                                trackinfo['length'] = mdhd[4] / mdhd[3]
                                if mdhd[5] in QTLANGUAGES:
                                    trackinfo['language'] = QTLANGUAGES[mdhd[5]]
                                # mdhd[6] == quality
                                self.length = max(self.length, mdhd[4] / mdhd[3])
                        elif mdia[1] == b'minf':
                            # minf has only atoms inside
                            pos -=      (mdia[0] - 8)
                            datasize += (mdia[0] - 8)
                        elif mdia[1] == b'stbl':
                            # stbl has only atoms inside
                            pos -=      (mdia[0] - 8)
                            datasize += (mdia[0] - 8)
                        elif mdia[1] == b'hdlr':
                            hdlr = struct.unpack('>I4s4s', atomdata[pos+8:pos+8+12])
                            if hdlr[1] == b'mhlr':
                                if hdlr[2] == b'vide':
                                    tracktype = 'video'
                                if hdlr[2] == b'soun':
                                    tracktype = 'audio'
                        elif mdia[1] == b'stsd':
                            stsd = struct.unpack('>2I', atomdata[pos+8:pos+8+8])
                            if stsd[1] > 0:
                                codec = atomdata[pos+16:pos+16+8]
                                codec = struct.unpack('>I4s', codec)
                                trackinfo['codec'] = codec[1].decode()
                                if codec[1] == b'jpeg':
                                    tracktype = 'image'
                        elif mdia[1] == b'dinf':
                            dref = struct.unpack('>I4s', atomdata[pos+8:pos+8+8])
                            log.debug('  --> %s, %s (useless)' % mdia)
                            if dref[1] == b'dref':
                                num = struct.unpack('>I', atomdata[pos+20:pos+20+4])[0]
                                rpos = pos+20+4
                                for ref in range(num):
                                    # FIXME: do somthing if this references
                                    ref = struct.unpack('>I3s', atomdata[rpos:rpos+7])
                                    data = atomdata[rpos+7:rpos+ref[0]]
                                    rpos += ref[0]
                        else:
                            if mdia[1].startswith(b'st'):
                                log.debug('  --> %s, %s (sample)' % mdia)
                            elif mdia[1] in (b'vmhd',) and not tracktype:
                                # indicates that this track is video
                                tracktype = 'video'
                            elif mdia[1] in (b'vmhd', b'smhd') and not tracktype:
                                # indicates that this track is audio
                                tracktype = 'audio'
                            else:
                                log.debug('  --> %s, %s (unknown)' % mdia)

                        pos      += mdia[0]
                        datasize -= mdia[0]

                elif datatype == b'udta':
                    log.debug(struct.unpack('>I4s', atomdata[:8]))
                else:
                    if datatype == b'edts':
                        log.debug('--> %s [%d] (edit list)' % \
                                  (datatype, datasize))
                    else:
                        log.debug('--> %s [%d] (unknown)' % \
                                  (datatype, datasize))
                pos += datasize

            info = None
            if tracktype == 'video':
                info = core.VideoStream()
                self.video.append(info)
            if tracktype == 'audio':
                info = core.AudioStream()
                self.audio.append(info)
            if info:
                for key, value in list(trackinfo.items()):
                    setattr(info, key, value)

        elif atomtype == b'mvhd':
            # movie header
            mvhd = struct.unpack('>6I2h', file.read(28))
            self.length = max(self.length or 0, mvhd[4] / mvhd[3])
            self.volume = mvhd[6]
            file.seek(atomsize-8-28,1)


        elif atomtype == b'cmov':
            # compressed movie
            datasize, atomtype = struct.unpack('>I4s', file.read(8))
            if not atomtype == b'dcom':
                return atomsize

            method = struct.unpack('>4s', file.read(datasize-8))[0]

            datasize, atomtype = struct.unpack('>I4s', file.read(8))
            if not atomtype == b'cmvd':
                return atomsize

            if method == b'zlib':
                data = file.read(datasize-8)
                try:
                    decompressed = zlib.decompress(data)
                except Exception as e:
                    try:
                        decompressed = zlib.decompress(data[4:])
                    except Exception as e:
                        log.exception('There was a proble decompressiong atom')
                        return atomsize

                decompressedIO = io.StringIO(decompressed)
                while self._readatom(decompressedIO):
                    pass

            else:
                log.info('unknown compression %s' % method)
                # unknown compression method
                file.seek(datasize-8,1)

        elif atomtype == b'moov':
            # decompressed movie info
            while self._readatom(file):
                pass

        elif atomtype == b'mdat':
            pos = file.tell() + atomsize - 8
            # maybe there is data inside the mdat
            log.info('parsing mdat')
            while self._readatom(file):
                pass
            log.info('end of mdat')
            file.seek(pos, 0)


        elif atomtype == b'rmra':
            # reference list
            while self._readatom(file):
                pass

        elif atomtype == b'rmda':
            # reference
            atomdata = file.read(atomsize-8)
            pos   = 0
            url = ''
            quality = 0
            datarate = 0
            while pos < atomsize-8:
                (datasize, datatype) = struct.unpack('>I4s', atomdata[pos:pos+8])
                if datatype == b'rdrf':
                    rflags, rtype, rlen = struct.unpack('>I4sI', atomdata[pos+8:pos+20])
                    if rtype == b'url ':
                        url = atomdata[pos+20:pos+20+rlen]
                        if url.find('\0') > 0:
                            url = url[:url.find('\0')]
                elif datatype == b'rmqu':
                    quality = struct.unpack('>I', atomdata[pos+8:pos+12])[0]

                elif datatype == b'rmdr':
                    datarate = struct.unpack('>I', atomdata[pos+12:pos+16])[0]

                pos += datasize
            if url:
                self._references.append((url, quality, datarate))

        else:
            if not atomtype in (b'wide', b'free'):
                log.info('unhandled base atom %s' % atomtype)

            # Skip unknown atoms
            try:
                file.seek(atomsize-8,1)
            except IOError:
                return 0

        return atomsize


Parser = MPEG4
