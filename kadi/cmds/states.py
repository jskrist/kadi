"""
This module provides the core functions for creating, manipulating and updating
the Chandra commanded states database.
"""

import collections
import itertools

import numpy as np
import six
from six.moves import range

from astropy.table import Table, Column

from . import cmds as commands

from Chandra.cmd_states import decode_power
from Chandra.Time import DateTime
import Chandra.Maneuver
from Quaternion import Quat
import Ska.Sun

REV_PARS_DICT = commands.rev_pars_dict

# Registry of Transition classes with state transition name as key.  A state transition
# may be generated by several different transition classes, hence the dict value is a list
TRANSITIONS = collections.defaultdict(list)

# Set of all Transition classes
TRANSITION_CLASSES = set()

# Ordered list of all state keys
STATE_KEYS = []

# Quaternion componenent names
QCS = ['q1', 'q2', 'q3', 'q4']

# State keys that are required to handle maneuvers.  If any of these keys are requested
# then all of these must be included in state processing.
MANVR_STATE_KEYS = QCS + ['targ_' + qc for qc in QCS] + ['auto_npnt', 'pcad_mode', 'pitch']


class TransitionMeta(type):
    """
    Metaclass that adds the class to the TRANSITIONS registry.
    """
    def __new__(mcls, name, bases, members):
        cls = super(TransitionMeta, mcls).__new__(mcls, name, bases, members)

        # Register transition classes that have a `transition_name`.
        if 'transition_name' in members:
            if 'state_keys' not in members:
                cls.state_keys = [cls.transition_name]

            for state_key in cls.state_keys:
                if state_key not in STATE_KEYS:
                    STATE_KEYS.append(state_key)
                TRANSITIONS[state_key].append(cls)

            TRANSITION_CLASSES.add(cls)

        return cls


@six.add_metaclass(TransitionMeta)
class BaseTransition(object):
    @classmethod
    def get_state_changing_commands(cls, cmds):
        """
        Get commands that match the required attributes for state changing commands.
        """
        ok = np.ones(len(cmds), dtype=bool)
        for attr, val in cls.command_attributes.items():
            ok = ok & (cmds[attr] == val)
        return cmds[ok]


class SingleFixedTransition(BaseTransition):
    @classmethod
    def set_transitions(cls, transitions, cmds):
        """
        Set transitions for a Table of commands ``cmds``.  This is the simplest
        case where there is a single fixed attribute that gets set to a fixed
        value, e.g. pcad_mode='NMAN' for NMM.
        """
        state_cmds = cls.get_state_changing_commands(cmds)
        val = cls.transition_val
        attr = cls.transition_name

        for cmd in state_cmds:
            transitions[cmd['date']][attr] = val


class NMM_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AONMMODE'}
    transition_name = 'pcad_mode'
    transition_val = 'NMAN'
    state_keys = MANVR_STATE_KEYS


class NPM_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AONPMODE'}
    transition_name = 'pcad_mode'
    transition_val = 'NPNT'
    state_keys = MANVR_STATE_KEYS


# class ACISTransition(BaseTransition):
#     command_attributes = {'type': 'ACISPKT'}
#     transition_name = 'acis'

#     @classmethod
#     def set_transitions(cls, transitions, cmds):
#         state_cmds = cls.get_state_changing_commands(cmds)
#         for cmd in state_cmds:
#             tlmsid = cmd['tlmsid']
#             date = cmd['date']

# class NPM_AutoEnableTransition(BaseTransition):
#     command_attributes = {'type': 'COMMAND_SW',
#                           'tlmsid': 'AONM2NPE'}
#     transition_name = 'pcad_mode'

#     @classmethod
#     def set_transitions(cls, transitions, cmds):
#         state_cmds = cls.get_state_changing_commands(cmds)
#         for cmd in state_cmds:
#             date = cmd['date']
#             transitions[date].update({'auto_npnt': True})


class HETG_INSR_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': '4OHETGIN'}
    transition_name = 'hetg'
    transition_val = 'INSR'


class HETG_RETR_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': '4OHETGRE'}
    transition_name = 'hetg'
    transition_val = 'RETR'


class LETG_INSR_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': '4OLETGIN'}
    transition_name = 'letg'
    transition_val = 'INSR'


class LETG_RETR_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': '4OLETGRE'}
    transition_name = 'letg'
    transition_val = 'RETR'


class DitherEnableTransition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AOENDITH'}
    transition_name = 'dither'
    transition_val = 'ENAB'


class DitherDisableTransition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AODSDITH'}
    transition_name = 'dither'
    transition_val = 'DISA'


class ParamTransition(BaseTransition):
    @classmethod
    def set_transitions(cls, transitions, cmds):
        """
        Set transitions for a Table of commands ``cmds``.  This is the simplest
        case where there is an attribute that gets set to a specified
        value in the command, e.g. MP_OBSID or SIMTRANS
        """
        state_cmds = cls.get_state_changing_commands(cmds)
        param_key = cls.transition_param_key
        name = cls.transition_name

        for cmd in state_cmds:
            val = dict(REV_PARS_DICT[cmd['idx']])[param_key]
            transitions[cmd['date']][name] = val


class ObsidTransition(ParamTransition):
    command_attributes = {'type': 'MP_OBSID'}
    transition_name = 'obsid'
    transition_param_key = 'id'


class SimTscTransition(ParamTransition):
    command_attributes = {'type': 'SIMTRANS'}
    transition_param_key = 'pos'
    transition_name = 'simpos'


class SimFocusTransition(ParamTransition):
    command_attributes = {'type': 'SIMFOCUS'}
    transition_param_key = 'pos'
    transition_name = 'simfa_pos'


class AutoNPMEnableTransition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AONM2NPE'}
    transition_name = 'auto_npnt'
    transition_val = 'ENAB'
    state_keys = MANVR_STATE_KEYS


class AutoNPMDisableTransition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AONM2NPD'}
    transition_name = 'auto_npnt'
    transition_val = 'DISA'
    state_keys = MANVR_STATE_KEYS


class TargQuatTransition(BaseTransition):
    command_attributes = {'type': 'MP_TARGQUAT'}
    transition_name = 'targ_quat'
    state_keys = MANVR_STATE_KEYS

    @classmethod
    def set_transitions(cls, transitions, cmds):
        state_cmds = cls.get_state_changing_commands(cmds)

        for cmd in state_cmds:
            transition = transitions[cmd['date']]
            for qc in ('q1', 'q2', 'q3', 'q4'):
                transition['targ_' + qc] = cmd[qc]


class ManeuverTransition(BaseTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AOMANUVR'}
    transition_name = 'maneuver'
    state_keys = MANVR_STATE_KEYS

    @classmethod
    def set_transitions(cls, transitions, cmds):
        state_cmds = cls.get_state_changing_commands(cmds)

        for cmd in state_cmds:
            # Note that the transition key 'maneuver' doesn't really matter here
            # as long as it is different from the other state keys.
            transitions[cmd['date']]['maneuver'] = {'func': cls.add_transitions,
                                                    'cmd': cmd}

    @classmethod
    def add_transitions(cls, date, transitions, state, idx, cmd):
        end_manvr_date = cls.add_manvr_transitions(date, transitions, state, idx, cmd)

        # If auto-transition to NPM after manvr is enabled (this is
        # normally the case) then back to NPNT at end of maneuver
        if state['auto_npnt'] == 'ENAB':
            transition = {'date': end_manvr_date, 'pcad_mode': 'NPNT'}
            add_transition(transitions, idx, transition)

    @classmethod
    def add_manvr_transitions(cls, date, transitions, state, idx, cmd):
        targ_att = [state['targ_' + qc] for qc in QCS]
        if state['q1'] is None:
            for qc in QCS:
                state[qc] = state['targ_' + qc]
        curr_att = [state[qc] for qc in QCS]

        # add pitch/attitude commands
        atts = Chandra.Maneuver.attitudes(curr_att, targ_att,
                                          tstart=DateTime(cmd['date']).secs)

        pitches = np.hstack([(atts[:-1].pitch + atts[1:].pitch) / 2,
                             atts[-1].pitch])
        for att, pitch in zip(atts, pitches):
            # q_att = Quat([att[x] for x in QCS])
            date = DateTime(att.time).date
            transition = {'date': date}
            for qc in QCS:
                transition[qc] = att[qc]
            transition['pitch'] = pitch
            add_transition(transitions, idx, transition)

            # TODO: ra, dec, roll

        return date  # date of end of maneuver


class NormalSunTransition(ManeuverTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AONSMSAF'}
    transition_name = 'normal_sun'
    state_keys = MANVR_STATE_KEYS

    @classmethod
    def add_transitions(cls, date, transitions, state, idx, cmd):
        # Transition to NSUN
        state['pcad_mode'] = 'NSUN'

        # Setup for maneuver to sun-pointed attitude from current att
        curr_att = [state[qc] for qc in QCS]
        targ_att = Chandra.Maneuver.NSM_attitude(curr_att, cmd['date'])
        for qc, targ_q in zip(QCS, targ_att.q):
            state['targ_' + qc] = targ_q

        # Do the maneuver
        cls.add_manvr_transitions(date, transitions, state, idx, cmd)


class ACISTransition(BaseTransition):
    command_attributes = {'type': 'ACISPKT'}
    transition_name = 'acis'
    state_keys = ['clocking', 'power_cmd', 'vid_board', 'fep_count', 'si_mode', 'ccd_count']

    @classmethod
    def set_transitions(cls, transitions, cmds):
        state_cmds = cls.get_state_changing_commands(cmds)
        for cmd in state_cmds:
            tlmsid = cmd['tlmsid']
            date = cmd['date']

            # TODO: fix bug in ACIS commanding: https://github.com/sot/cmd_states/pull/31/files

            if tlmsid.startswith('WSPOW'):
                pwr = decode_power(tlmsid)
                transitions[date].update(fep_count=pwr['fep_count'],
                                         ccd_count=pwr['ccd_count'],
                                         vid_board=pwr['vid_board'],
                                         clocking=pwr['clocking'],
                                         power_cmd=tlmsid)

            elif tlmsid in ('XCZ0000005', 'XTZ0000005'):
                transitions[date].update(clocking=1, power_cmd=tlmsid)

            elif tlmsid == 'WSVIDALLDN':
                transitions[date].update(vid_board=0, power_cmd=tlmsid)

            elif tlmsid == 'AA00000000':
                transitions[date].update(clocking=0, power_cmd=tlmsid)

            elif tlmsid == 'WSFEPALLUP':
                transitions[date].update(fep_count=6, power_cmd=tlmsid)

            elif tlmsid.startswith('WC'):
                transitions[date].update(si_mode='CC_' + tlmsid[2:7])

            elif tlmsid.startswith('WT'):
                transitions[date].update(si_mode='TE_' + tlmsid[2:7])


def get_transition_classes(state_keys=None):
    """
    Get all BaseTransition subclasses in this module corresponding to
    state keys ``state_keys``.
    """
    if isinstance(state_keys, six.string_types):
        state_keys = [state_keys]

    if state_keys is None:
        # itertools.chain => concat list of lists
        trans_classes = set(itertools.chain.from_iterable(TRANSITIONS.values()))
    else:
        trans_classes = set(itertools.chain.from_iterable(
                classes for state_key, classes in TRANSITIONS.items()
                if state_key in state_keys))
    return trans_classes


def get_transitions_list(cmds, state_keys=None):
    transitions = collections.defaultdict(dict)

    for transition_class in get_transition_classes(state_keys):
        transition_class.set_transitions(transitions, cmds)

    transitions_list = []
    for date in sorted(transitions):
        transition = transitions[date]
        transition['date'] = date
        transitions_list.append(transition)

    return transitions_list


def update_pitch_state(date, transitions, state, idx):
    """
    This function gets called during state processing to potentially update the
    `pitch` state if pcad_mode is NPNT.
    """
    if state['pcad_mode'] == 'NPNT':
        q_att = Quat([state[qc] for qc in QCS])
        pitch = Ska.Sun.pitch(q_att.ra, q_att.dec, date)
        state['pitch'] = pitch


def add_pitch_transitions(start, stop, transitions):
    """
    Add transitions between start/stop every 10ksec to sample the pitch during NPNT.
    These are function transitions which check to see that pcad_mode == 'NPNT'
    before changing the pitch.

    This function gets called after assembling the initial list of transitions
    that are generated from Transition classes.
    """
    # np.floor is used here to get 'times' at even increments of "sample_time"
    # so that the commands will be at the same times in an interval even
    # if a different time range is being updated.
    sample_time = 10000
    tstart = np.floor(DateTime(start).secs / sample_time) * sample_time
    tstop = DateTime(stop).secs
    times = np.arange(tstart, tstop, sample_time)
    dates = DateTime(times).date

    # Now with the dates, finally make all the transition dicts which will
    # call `update_pitch_state` during state processing.
    pitch_transitions = [{'date': date,
                          'update_pitch': {'func': update_pitch_state}}
                         for date in dates]

    # Add to the transitions list and sort by date
    transitions.extend(pitch_transitions)
    transitions.sort(key=lambda x: x['date'])


def add_transition(transitions, idx, transition):
    # Prevent adding command before current command since the command
    # interpreter is a one-pass process.
    date = transition['date']
    if date < transitions[idx]['date']:
        raise ValueError('cannot insert transition prior to current command')

    # Insert transition at first place where new transition date is strictly
    # less than existing transition date.  This implementation is linear, and
    # could be improved, though in practice transitions are often inserted
    # close to the original.
    for ii in range(idx + 1, len(transitions)):
        if date < transitions[ii]['date']:
            transitions.insert(ii, transition)
            break
    else:
        transitions.append(transition)


def get_states_for_cmds(cmds, state_keys=None):
    # Define complete list of column names for output table corresponding to
    # each state key.  Maintain original order and uniqueness of keys.
    if state_keys is None:
        state_keys = STATE_KEYS
        orig_state_keys = state_keys
    else:
        # Go through each transition class which impacts desired state keys and accumulate
        # all the state keys that the classes touch.  For instance if user requests
        # state_keys=['q1'] then we actually need to process all the MANVR_STATE_KEYS
        # and then at the end reduce down to the requested keys.
        orig_state_keys = state_keys
        state_keys = []
        for state_key in orig_state_keys:
            for cls in TRANSITION_CLASSES:
                if state_key in cls.state_keys:
                    state_keys.extend(cls.state_keys)
        state_keys = unique(state_keys)

    # Get transitions, which is a list of dict (state key
    # and new state value at that date).  This goes through each active
    # transition class and accumulates transitions.
    transitions = get_transitions_list(cmds, state_keys)

    add_pitch_transitions(cmds[0]['date'], cmds[-1]['date'], transitions)

    # List of dict to hold state values
    states = [{key: None for key in state_keys}]
    datestarts = [transitions[0]['date']]
    state = states[0]

    for idx, transition in enumerate(transitions):
        date = transition['date']

        if date != datestarts[-1]:
            state = state.copy()
            states.append(state)
            datestarts.append(date)

        for key, value in transition.items():
            if isinstance(value, dict):
                func = value.pop('func')
                func(date, transitions, state, idx, **value)
            elif key != 'date':
                state[key] = value

    # Make into an astropy Table and set up datestart/stop columns
    states = Table(rows=states, names=state_keys)
    states.add_column(Column(datestarts, name='datestart'), 0)
    datestop = states['datestart'].copy()
    datestop[:-1] = states['datestart'][1:]
    datestop[-1] = '2099:365:00:00:00.000'
    states.add_column(Column(datestop, name='datestop'), 1)

    return states


def reduce_states(states, state_keys):
    if not isinstance(states, Table):
        states = Table(states)

    different = np.zeros(len(states), dtype=bool)
    for key in state_keys:
        col = states[key]
        different[1:] |= (col[:-1] != col[1:])

    out = states[['datestart', 'datestop'] + state_keys][different]
    out['datestop'][:-1] = out['datestart'][1:]

    return out


def unique(seq):
    """Return unique elements of seq in order"""
    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]
