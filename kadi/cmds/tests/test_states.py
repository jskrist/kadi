import numpy as np

from ... import cmds as commands
from ...cmds import states
import pytest

import Chandra.cmd_states as cmd_states
from Chandra.Time import DateTime
from Ska.engarchive import fetch


def get_states(start, stop, state_keys, state0=None):
    """
    Helper for getting states from kadi and cmd_states
    """
    start = DateTime(start)
    stop = DateTime(stop)

    cstates = cmd_states.fetch_states(start, stop)
    rcstates = states.reduce_states(cstates, state_keys)
    lenr = len(rcstates)

    cmds = commands.filter(start - 7, stop)
    kstates = states.get_states_for_cmds(cmds, state_keys, state0=state0)
    rkstates = states.reduce_states(kstates, state_keys)[-lenr:]

    return rcstates, rkstates


def compare_states(start, stop, state_keys, compare_state_keys=None, state0=None):
    """
    Helper for comparing states from kadi and cmd_states
    """
    rcstates, rkstates = get_states(start, stop, state_keys, state0=state0)

    if compare_state_keys is None:
        compare_state_keys = state_keys

    for colname in compare_state_keys:
        assert np.all(rkstates[colname] == rcstates[colname])

    return rcstates, rkstates


def test_acis():
    """
    Test all ACIS states include vid_board for late-2017
    """
    state_keys = ['clocking', 'power_cmd',  'fep_count', 'si_mode',  'ccd_count', 'vid_board']
    compare_states('2017:280', '2017:360', state_keys, state_keys + ['datestart'])


def test_quick():
    """
    Test for a few days in 2017.  Sanity check for refactoring etc.
    """
    state_keys = (['obsid', 'clocking', 'power_cmd',  'fep_count', 'vid_board',
                   'si_mode',  'ccd_count'] +
                  ['q1', 'q2', 'q3', 'q4', 'pcad_mode', 'dither', 'ra', 'dec', 'roll'] +
                  ['letg', 'hetg'] +
                  ['simpos', 'simfa_pos'])
    state0 = {'letg': 'RETR', 'hetg': 'RETR'}  # Not necessarily set within 7 days
    rc, rk = compare_states('2017:300', '2017:310', state_keys, state0=state0)
    assert np.all(rc['datestart'] == rk['datestart'])


def test_states_2017():
    """
    Test for 200 days in 2017.  Includes 2017:066, 068, 090 anomalies and
    2017:250-254 SCS107 + 251 CTI.

    Skip 'vid_board' because https://github.com/sot/cmd_states/pull/31 was put
    in place around 2017:276 and so the behavior of this changed then. (Tested later).

    Skip 'pitch' because Chandra.cmd_states only avoids pitch breaks within actual
    maneuver commanding (so the NMAN period before maneuver starts is OK) while kadi
    will insert pitch breaks only in NPNT.  (Tested later).
    """
    state_keys = (['obsid', 'clocking', 'power_cmd',  'fep_count',
                   'si_mode',  'ccd_count'] +
                  ['q1', 'q2', 'q3', 'q4', 'pcad_mode', 'dither', 'ra', 'dec', 'roll'] +
                  ['letg', 'hetg'] +
                  ['simpos', 'simfa_pos'])
    state0 = {'letg': 'RETR', 'hetg': 'RETR'}  # Not necessarily set within 7 days
    rcstates, rkstates = compare_states('2017:060', '2017:260', state_keys, state0=state0)

    # Check state datestart.  There are 4 known discrepancies of 0.001 sec
    # due to a slight difference in the start time for NSUN maneuvers.  Cmd_states
    # uses the exact floating point time to start while kadi uses the string time
    # rounded to the nearest msec.  The float command time is not stored in kadi.
    bad = np.flatnonzero(rkstates['datestart'] != rcstates['datestart'])
    assert len(bad) == 4
    tk = DateTime(rkstates['datestart'][bad]).secs
    tc = DateTime(rcstates['datestart'][bad]).secs
    assert np.all(np.abs(tk - tc) < 0.0015)


def test_pitch_2017():
    """
    Test pitch for 100 days in 2017.  Includes 2017:066, 068, 090 anomalies.  This is done
    by interpolating states (at 200 second intervals) because the pitch generation differs
    slightly between kadi and Chandra.cmd_states.  (See test_states_2017 note).

    Make sure that pitch matches to within 0.5 deg in all samples, and 0.05 deg during
    NPNT.
    """
    rcstates, rkstates = get_states('2017:060', '2017:160', ['pcad_mode', 'pitch'])

    rcstates['tstop'] = DateTime(rcstates['datestop']).secs
    rkstates['tstop'] = DateTime(rkstates['datestop']).secs

    times = np.arange(rcstates['tstop'][0], rcstates['tstop'][-2], 200.0)
    rci = cmd_states.interpolate_states(rcstates, times)
    rki = cmd_states.interpolate_states(rkstates, times)

    dp = np.abs(rci['pitch'] - rki['pitch'])
    assert np.all(dp < 0.5)
    assert np.all(rci['pcad_mode'] == rki['pcad_mode'])
    ok = rci['pcad_mode'] == 'NPNT'
    assert np.all(dp[ok] < 0.05)


def test_sun_vec_versus_telemetry():
    """
    Test sun vector values `pitch` and `off_nominal_roll` versus flight telem.  Include
    Load maneuver at 2017:349:20:52:37.719 in DEC1117 with large pitch and
    off_nominal_roll change (from around zero to -17 deg).

    State values are within 1.5 degrees of telemetry.
    """

    state_keys = ['pitch', 'off_nom_roll']
    start, stop = '2017:349:10:00:00', '2017:350:10:00:00'
    cmds = commands.filter(start, stop)
    kstates = states.get_states_for_cmds(cmds, state_keys)[-20:-1]
    rk = states.reduce_states(kstates, state_keys)

    tstart = DateTime(rk['datestart']).secs
    tstop = DateTime(rk['datestop']).secs
    tmid = (tstart + tstop) / 2

    # Pitch from telemetry
    dat = fetch.Msid('pitch', tstart[0] - 100, tstop[-1] + 100)
    dat.interpolate(times=tmid)
    delta = np.abs(dat.vals - rk['pitch'])
    assert np.max(rk['pitch']) - np.min(rk['pitch']) > 75  # Big maneuver
    assert np.all(delta < 1.5)

    # Off nominal roll (not roll from ra,dec,roll) from telemetry
    dat = fetch.Msid('roll', tstart[0] - 100, tstop[-1] + 100)
    dat.interpolate(times=tmid)
    delta = np.abs(dat.vals - rk['off_nom_roll'])
    assert np.max(rk['off_nom_roll']) - np.min(rk['off_nom_roll']) > 20  # Large range
    assert np.all(delta < 1.5)


def test_dither():
    """Values look reasonable given load commands"""
    cs = commands.filter('2017:340:00:00:00', '2017:350:00:00:00')
    rk = states.get_states_for_cmds(cs, ['dither_phase_pitch', 'dither_phase_yaw',
                                         'dither_ampl_pitch', 'dither_ampl_yaw',
                                         'dither_period_pitch', 'dither_period_yaw'])

    assert np.all(rk['datestart'] == ['2017:341:21:40:05.265',
                                      '2017:342:08:26:34.023',
                                      '2017:345:02:45:50.318',
                                      '2017:345:09:02:21.704',
                                      '2017:345:17:18:08.893',
                                      '2017:346:04:35:44.546',
                                      '2017:349:21:28:42.426'])
    assert np.all(rk['dither_phase_pitch'] == 0.0)
    assert np.all(rk['dither_phase_yaw'] == 0.0)
    ampls = [20.00149628163879,
             7.9989482580707696,
             20.00149628163879,
             7.9989482580707696,
             20.00149628163879,
             7.9989482580707696,
             20.00149628163879]
    assert np.allclose(rk['dither_ampl_pitch'], ampls, atol=1e-6, rtol=0)
    assert np.allclose(rk['dither_ampl_yaw'], ampls, atol=1e-6, rtol=0)
    assert np.allclose(rk['dither_period_pitch'], [768.5740994184024,
                                                   707.13038356352104,
                                                   768.5740994184024,
                                                   707.13038356352104,
                                                   768.5740994184024,
                                                   707.13038356352104,
                                                   768.5740994184024], atol=1e-6, rtol=0)

    assert np.allclose(rk['dither_period_yaw'], [1086.9567572759399,
                                                 999.99938521341483,
                                                 1086.9567572759399,
                                                 999.99938521341483,
                                                 1086.9567572759399,
                                                 999.99938521341483,
                                                 1086.9567572759399], atol=1e-6, rtol=0)


def test_get_state0_regress():
    """Regression test against values produced by get_state0 during development.
    Correctness not validated
    """
    expected = {'auto_npnt': 'ENAB',
                'ccd_count': 4,
                'clocking': 1,
                'dec': 1.5846264168595519,
                'dither': 'ENAB',
                'dither_ampl_pitch': 7.9989482580707696,
                'dither_ampl_yaw': 7.9989482580707696,
                'dither_period_pitch': 707.13038356352104,
                'dither_period_yaw': 999.99938521341483,
                'dither_phase_pitch': 0.0,
                'dither_phase_yaw': 0.0,
                'fep_count': 4,
                'hetg': 'RETR',
                'letg': 'RETR',
                'obsid': 18926,
                'off_nom_roll': 0.29420229587100266,
                'pcad_mode': 'NPNT',
                'pitch': 140.65601594364458,
                'power_cmd': 'XTZ0000005',
                'q1': -0.35509348299999999,
                'q2': -0.32069040199999999,
                'q3': 0.56677623399999999,
                'q4': 0.67069440499999999,
                'ra': 81.262785800648018,
                'roll': 302.84307361651355,
                'si_mode': 'TE_006C8',
                'simfa_pos': -468,
                'simpos': 75624,
                'targ_q1': -0.355093483,
                'targ_q2': -0.320690402,
                'targ_q3': 0.566776234,
                'targ_q4': 0.670694405,
                'vid_board': 1}

    state0 = states.get_state0('2017:014')

    for key, val in expected.items():
        if isinstance(val, (int, str)):
            assert state0[key] == val
        else:
            assert np.isclose(state0[key], val, rtol=0, atol=1e-7)


def test_get_state0_vs_states():
    """
    Functional test: state0 for a certain date should be the same as the last states
    when fed in cmds up through that date.
    """
    date0 = '2017:014'
    # Get last state up through `date0`.  Hardwire the lookback here to 21 days.
    cmds = commands.filter('2016:360', date0)
    sts = states.get_states_for_cmds(cmds)
    sts0 = sts[-1]

    state0 = states.get_state0(date0)

    for key, val in state0.items():
        if isinstance(val, (int, str)):
            assert sts0[key] == val
        else:
            assert np.isclose(sts0[key], val, rtol=0, atol=1e-7)


def test_get_state0_fail():
    with pytest.raises(ValueError) as err:
        states.get_state0('2017:014', ['letg'], lookbacks=[3])
    assert 'did not find transitions' in str(err)


def test_transition_error():
    """Raise exception if there are no state transitions within supplied commands"""
    cmds = commands.filter('2016:360', '2016:361')
    with pytest.raises(states.NoTransitionsError):
        states.get_states_for_cmds(cmds, ['letg'])


# TODO: test reduce_states.
