"""Configure parameters, and prepare metadata and dispersions."""
import logging.config
from os.path import basename, dirname, exists, join
import shutil
from sys import exit

import numpy as np

import pymodule as my


logger = logging.getLogger(__name__)


#
# Configurable constants
#
make_doc = True
PARAM = {}
STA2NET = {}
STNM2LOLA = {}
ALL_STATION = []
RECEIVER_STATION = []
RECEIVER_GROUP = None
SOURCE_STATION = []
PHPRPER = []
PHPRVEL = []
PRED_PV = None
DEF_SHD = None
SHD2KEY = {}
KEY2SHD = {}
USE_CW = False
USE_DW = False
CONV = False
CORR = False

#
# SAC headers
#
DEF_SHD = - 12345
SHD2KEY = {
    'kuser0': 'src_sta',
    'kuser1': 'net_rec',
    'kuser2': 'src_net',
    'user0': 'nsrc',
    'user1': 'nsided',
    'user2': 'snr',
    'user3': 'dr',
    'user4': 'theta',
    'user5': 'min_srdist',
    'user6': 'dir_src',
    'user7': 'nsrc_dir1',
    'user8': 'nsrc_dir2',
}
KEY2SHD = {v: k for k, v in SHD2KEY.items()}


#
# Configurable functions
#
def group_sta(lst, lnum):
    """
    Return 2 groups of stations.

    :param lst: list of stations
    :param lnum: list of group #
    """
    num = list(set(lnum))
    if len(num) != 2:
        raise ValueError('# of group != 2.')
    else:
        g0 = []
        g1 = []
        for k, st in enumerate(lst):
            if lnum[k] == num[0]:
                g0.append(st)
            else:
                g1.append(st)

        return g0, g1


def get_order(lst, st1, st2):
    """
    Sort two stations according to their orders in `lst`.
    """
    id1 = lst.index(st1)
    id2 = lst.index(st2)

    if id1 <= id2:
        return [st1, st2]
    else:
        return [st2, st1]


def get_pred_pv(n1, s1, n2, s2, pair=None, pair_r=None):
    """
    Get predicted phase velocity.
    """
    per = PHPRPER
    pv = PHPRVEL
    if PRED_PV:
        if pair is None:
            pair = '_'.join([n1, s1, n2, s2])
            pair_r = '_'.join([n2, s2, n1, s1])
        if pair in PRED_PV:
            pass
        elif pair_r in PRED_PV:
            pair = pair_r
        else:
            return per, pv

        per = PRED_PV[pair][0]
        pv = PRED_PV[pair][1]

    return np.asarray(per), np.asarray(pv)


def get_fnm(kind, sta1=None, sta2=None, sta3=None,
            lags=None, pre=None, I2=None):
    """
    Return names for various kinds of files.

    :param kind:
        - 'I2_PATH': paths to I2
        - 'SOURCE-STATION': common source-stations for receiver pairs
        - 'I2': raw two-station interferogram
        - 'I2_LAG_RAW': postive/negative lags of two-station interferogram
        - 'I2_LAG_PROC': processed two-station interferogram
        - 'C3': source-specific interferogram
        - 'I3': stacked three-station interferogram
        - 'I3_RAND': randomly stacked three-station interferogram
    """

    kind = kind.upper()

    if kind in ['I2_PATH']:
        return join(
            DIROUT,
            PARAM['dir']['meta'],
            PARAM['dir']['out'] + PARAM['sfx']['I2'],
        )
    if kind in ['SOURCE', 'SOURCE-STATION']:
        return join(
            DIROUT,
            PARAM['dir']['meta'],
            PARAM['dir']['out'] + PARAM['sfx']['source'],
        )

    if I2 is not None:
        sta2 = basename(dirname(I2))
        I2 = basename(I2)

    src, rec = get_order(ALL_STATION, sta1, sta2)

    if kind == 'I2':
        fnm = join(
            PARAM['dir']['project'],
            PARAM['dir']['I2'],
            src,
            f'COR_{src}_{rec}.SAC',
        )
    elif kind == 'I2_LAG_PROC':
        fnm = join(
            DIROUT,
            src,
            f'{pre}_COR_{src}_{rec}.SAC',
        )
    elif kind == 'C3':
        fnm = join(
            DIROUT,
            src,
            rec,
            f'{sta3}_{lags}_{src}_{rec}.SAC',
        )
    elif kind == 'I3':
        fnm = join(
            DIROUT,
            PARAM['dir']['I3'],
            src,
            f'I3_{src}_{rec}.SAC',
        )
    elif kind == 'I3_RAND':
        fnm = join(
            DIROUT,
            PARAM['dir']['I3_rand'],
            src,
            rec,
            f'I3_{src}_{rec}.SAC',
        )
    elif kind == 'I2_LAG_RAW':
        stadir = join(DIROUT, src)
        if PARAM['write']['lag']:
            my.sys_tool.mkdir(stadir)
        if PARAM['interferometry']['nlag'] == 2:
            plag = join(stadir, f'P_{I2}')
            nlag = join(stadir, f'N_{I2}')
            fnm = [plag, nlag]
        else:
            fnm = [join(stadir, f'S_{I2}')]
    else:
        raise ValueError(f'Unknow kind of file: {kind}.')

    return fnm


#
# Check input parameters & extract meta
#
def _check():
    """
    Ensure input parameters are consistent with each other.
    """
    p = PARAM

    if USE_CW:
        if CONV:
            raise ValueError('NO convolution of coda')
        if p['interferometry']['spz']:
            logger.warning('Using stationary phase zone for coda')

    elif USE_DW:
        if p['interferometry']['Welch']:
            raise ValueError("NOT use Welch's method for direct-wave")

    if (p['interferometry']['nlag'] == 4) and (not p['interferometry']['flip_nlag']):
        raise NotImplementedError('4 lags MUST use the symmetric component')

    return


def _meta(name, col_net=0, col_sta=1, col_lon=2, col_lat=3):
    """
    Extract network, station name, longitude, and latitude.
    Overwrite `STA2NET, STNM2LOLA, RECEIVER_STATION, RECEIVER_GROUP, SOURCE_STATION,
    ALL_STATION`.
    """
    global STA2NET
    global STNM2LOLA
    global RECEIVER_STATION
    global RECEIVER_GROUP
    global SOURCE_STATION
    global ALL_STATION

    with open(join(PARAM['dir']['project'], name), 'r') as f:
        for line in f:
            lst = line.split()
            # key = f'{lst[col_net]}.{lst[col_sta]}'
            key = lst[col_sta]
            STNM2LOLA[key] = [float(lst[col_lon]), float(lst[col_lat])]
            STA2NET[key] = lst[col_net]
            ALL_STATION.append(key)

    f_rec_st = join(PARAM['dir']['project'], PARAM['fstation']['receiver']['name'])
    RECEIVER_STATION = my.fio.rcol(f_rec_st, 0)[0]
    if PARAM['fstation']['receiver']['group']:
        RECEIVER_GROUP = my.fio.rcol(f_rec_st, 1)[0]
    else:
        RECEIVER_GROUP = None

    _f = join(PARAM['dir']['project'], PARAM['fstation']['source'])
    SOURCE_STATION = my.fio.rcol(_f, 0)[0]

    return


def _cp_fparam():
    """
    Copy parameter file for reference later.
    """
    dir_meta = join(
        DIROUT,
        PARAM['dir']['meta'],
    )
    my.sys_tool.mkdir(dir_meta)

    n = 0
    while True:
        fout = join(dir_meta, f'{basename(fparam)}_{n}')
        if exists(fout):
            n += 1
        else:
            shutil.copy(fparam, fout)
            break

    return


if not make_doc:
    fparam = './param.yml'
    PARAM = my.fio.ryml(fparam)
    DIROUT = join(PARAM['dir']['project'], PARAM['dir']['out'])

    # Use direct-wave or coda
    if PARAM['misc']['wavetype'].lower() in ['cw', 'coda', 'coda wave', 'coda-wave']:
        USE_CW = True
        USE_DW = False
    elif PARAM['misc']['wavetype'].lower() in ['dw', 'direct wave', 'direct-wave']:
        USE_CW = False
        USE_DW = True
    else:
        raise ValueError(f"Unknown type of signal {PARAM['misc']['wavetype']}")

    # Use correlation or convolution
    if PARAM['interferometry']['operator'].lower() in ['conv', 'convolution']:
        CONV = True
        CORR = False
    elif PARAM['interferometry']['operator'].lower() in ['corr', 'correlation']:
        CORR = True
        CONV = False
    else:
        raise ValueError(f"Unknown operator {PARAM['interferometry']['type']}")

    # Prior phase velocity
    logger.debug('Load predicted prediction')
    _fpv_1d = PARAM['interferometry'].get('pred_pv_1d')
    if _fpv_1d is not None:
        PHPRPER, PHPRVEL = np.loadtxt(_fpv_1d, unpack=True)
    _fpv_2d = PARAM['interferometry'].get('pred_pv_2d')
    if _fpv_2d is not None:
        PRED_PV = my.fio.rpk(_fpv_2d)

    _check()
    _meta(**PARAM['fstation']['all'])
    _cp_fparam()
