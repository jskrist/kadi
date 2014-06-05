from copy import deepcopy

from .. import events
from Chandra.Time import DateTime


def test_overlapping_intervals():
    """
    Intervals that overlap due to interval_pad get merged.
    """
    start = '2013:221:00:10:00.000'
    stop = '2013:221:00:20:00.000'
    fa_moves = deepcopy(events.fa_moves)
    fa_moves.interval_pad = 0.0
    assert fa_moves.intervals(start, stop) == [('2013:221:00:11:33.100', '2013:221:00:12:05.900'),
                                               ('2013:221:00:12:38.700', '2013:221:00:13:11.500')]
    fa_moves.interval_pad = 300.0
    assert fa_moves.intervals(start, stop) == [('2013:221:00:10:00.000', '2013:221:00:18:11.500')]


def test_interval_pads():
    """
    Intervals pads.
    """
    start = '2013:221:00:10:00.000'
    stop = '2013:221:00:20:00.000'
    intervals = [('2013:221:00:11:33.100', '2013:221:00:12:05.900'),
                 ('2013:221:00:12:38.700', '2013:221:00:13:11.500')]

    assert events.fa_moves.intervals(start, stop) == intervals

    fa_moves = events.fa_moves()
    assert fa_moves.intervals(start, stop) == intervals

    fa_moves = events.fa_moves(pad=0)
    assert fa_moves.intervals(start, stop) == intervals

    fa_moves = events.fa_moves(pad=(0, 0))
    assert fa_moves.intervals(start, stop) == intervals

    # 5 seconds earlier and 10 seconds later
    fa_moves = events.fa_moves(pad=(5, 10))
    assert fa_moves.intervals(start, stop) == [('2013:221:00:11:28.100', '2013:221:00:12:15.900'),
                                               ('2013:221:00:12:33.700', '2013:221:00:13:21.500')]

    fa_moves = events.fa_moves(pad=300)
    assert fa_moves.intervals(start, stop) == [('2013:221:00:10:00.000', '2013:221:00:18:11.500')]


def test_query_event_intervals():
    intervals = (events.manvrs & events.tsc_moves).intervals('2012:001', '2012:002')
    assert intervals == [('2012:001:18:21:31.715', '2012:001:18:22:04.515'),
                         ('2012:002:02:53:03.804', '2012:002:02:54:50.917')]


def test_basic_query():
    rad_zones = events.rad_zones.filter('2013:001', '2013:007')
    assert str(rad_zones).splitlines() == [
        '<RadZone: 1852 2013:003:16:19:36 2013:004:02:21:34 dur=36.1 ksec>',
        '<RadZone: 1853 2013:006:08:22:22 2013:006:17:58:48 dur=34.6 ksec>']
    assert rad_zones.table.pformat(max_width=-1) == [
        '        start                  stop             tstart        tstop          dur      orbit orbit_num        perigee       ',
        '--------------------- --------------------- ------------- ------------- ------------- ----- --------- ---------------------',
        '2013:003:16:19:36.289 2013:004:02:21:34.289 473617243.473 473653361.473 36118.0000001  1852      1852 2013:003:22:29:59.302',
        '2013:006:08:22:22.982 2013:006:17:58:48.982 473847810.166 473882396.166 34586.0000001  1853      1853 2013:006:13:58:21.389']


def test_zero_length_query():
    rad_zones = events.rad_zones.filter('2013:001', '2013:002')
    assert len(rad_zones) == 0
    assert len(rad_zones.table) == 0


def test_short_query():
    """
    Short duration queries that test that filter will return partially
    included intervals.
    """
    dwells = events.dwells.filter('2012:002:00:00:00', '2012:002:00:00:01')
    assert len(dwells) == 1
    dwells = events.dwells.filter('2012:001:18:40:00', '2012:001:18:42:00')
    assert len(dwells) == 1
    dwells = events.dwells.filter('2012:002:02:49:00', '2012:002:02:50:00')
    assert len(dwells) == 1


def test_get_obsid():
    """
    Test that the get_obsid() method gives the right obsid for all event models.
    """
    models = events.models.get_event_models()
    for model in models.values():
        if model.__name__ == 'SafeSun':
            continue  # Doesn't work for SafeSun because of bad OBC telem
        model_obj = model.objects.filter(start__gte='2002:010')[0]
        obsid = model_obj.get_obsid()
        obsid_obj = events.obsids.filter(obsid__exact=obsid)[0]
        model_obj_start = DateTime(getattr(model_obj, model_obj._get_obsid_start_attr)).date
        assert obsid_obj.start <= model_obj_start
        assert obsid_obj.stop > model_obj_start

        # Now test that searching for objects with the same obsid gets
        # some matching objects and that they all have the same obsid.
        if model_obj.model_name in ('major_event', 'safe_sun'):
            continue  # Doesn't work for these
        query = getattr(events, model_obj.model_name + 's')
        query_events = query.filter(obsid=obsid)
        assert len(query_events) >= 1
        for query_event in query_events:
            assert query_event.get_obsid() == obsid


def test_intervals_filter():
    """
    Test setting filter keywords in the EventQuery object itself.
    """
    ltt_bads = events.ltt_bads
    start, stop = '2011:295', '2011:305'

    assert (str(ltt_bads().filter('2011:298', '2011:305')).splitlines() ==
            ['<LttBad: start=2011:299:04:58:39.000 msid=1CBAT flag=M>',
             '<LttBad: start=2011:300:00:00:00.000 msid=AACCCDPT flag=A>',
             '<LttBad: start=2011:301:00:00:00.000 msid=AACCCDPT flag=A>',
             '<LttBad: start=2011:302:00:00:00.000 msid=AACCCDPT flag=A>'])

    # No filter
    assert (ltt_bads.intervals(start, stop) ==
            [('2011:299:04:58:39.000', '2011:303:00:00:00.000')])

    assert (ltt_bads(flag='M').intervals(start, stop) ==
            [('2011:299:04:58:39.000', '2011:300:04:58:39.000')])

    assert (ltt_bads(msid='AACCCDPT', flag='A').intervals(start, stop) ==
            [('2011:300:00:00:00.000', '2011:303:00:00:00.000')])

    assert (ltt_bads(msid='AACCCDPT', flag='A', start__gt='2011:301:12').intervals(start, stop) ==
            [('2011:302:00:00:00.000', '2011:303:00:00:00.000')])
