from .soundfont_host import *
from .simple_rtmidi_wrapper import *
from abc import ABC, abstractmethod


class PlaybackImplementation(ABC):

    def __init__(self, host_instrument):
        # these get populated when the PlaybackImplementation is registered
        self.host_instrument = host_instrument
        # noinspection PyProtectedMember
        self.note_info_dict = host_instrument._note_info_by_id
        host_instrument.playback_implementations.append(self)
        # this is a fallback: if the instrument does not belong to an ensemble, it does not have
        # shared resources and so it will rely on its own privately held resources.
        self._resources = None

    """
    Methods for storing and accessing shared resources for the ensemble. For instance, SoundfontPlaybackImplementation
    uses this to store an instance of SoundfontHost. Only one instance of fluidsynth (and therefore SoundfontHost)
    needs to be running for all instruments in the ensemble, so this is a way of pooling that resource.
    """

    @property
    def resource_dictionary(self):
        if self.host_instrument.ensemble is None:
            # if this instrument is not part of an ensemble, it can't really have shared resources
            # instead, it creates a local resources dictionary and uses that
            if self._resources is None:
                self._resources = {}
            return self._resources
        else:
            # if this instrument is part of an ensemble, that ensemble holds the shared resources for all the
            # different playback implementations. Each playback implementation type has its own resource dictionary,
            # stored with its type as a key in the ensemble's shared resources dictionary. This way there can't be
            # name conflicts between different playback implementations
            if type(self) not in self.host_instrument.ensemble.shared_resources:
                self.host_instrument.ensemble.shared_resources[type(self)] = {}
            return self.host_instrument.ensemble.shared_resources[type(self)]

    def has_shared_resource(self, key):
        return key in self.resource_dictionary

    def get_shared_resource(self, key):
        return None if key not in self.resource_dictionary else self.resource_dictionary[key]

    def set_shared_resource(self, key, value):
        self.resource_dictionary[key] = value

    """
    Methods for storing and accessing shared resources for the ensemble. For instance, SoundfontPlaybackImplementation
    uses this to store an instance of SoundfontHost. Only one instance of fluidsynth (and therefore SoundfontHost)
    needs to be running for all instruments in the ensemble, so this is a way of pooling that resource.
    """

    @abstractmethod
    def start_note(self, note_id, pitch, volume, properties, other_parameter_values: dict = None):
        pass

    @abstractmethod
    def end_note(self, note_id):
        pass

    @abstractmethod
    def change_note_pitch(self, note_id, new_pitch):
        pass

    @abstractmethod
    def change_note_volume(self, note_id, new_volume):
        pass

    @abstractmethod
    def change_note_parameter(self, note_id, parameter_name, new_value):
        pass

    @abstractmethod
    def set_max_pitch_bend(self, semitones):
        # We include this because some playback implementations, namely ones that use the midi protocol, need a
        # way of changing the max pitch bend.
        pass


class SoundfontPlaybackImplementation(PlaybackImplementation):

    def __init__(self, host_instrument, bank_and_preset=(0, 0), soundfont="default",
                 num_channels=8, audio_driver="default", max_pitch_bend="default"):
        super().__init__(host_instrument)
        self.audio_driver = playback_settings.default_audio_driver if audio_driver == "default" else audio_driver
        self.soundfont = playback_settings.default_soundfont if soundfont == "default" else soundfont

        soundfont_host_resource_key = "{}_soundfont_host".format(self.audio_driver)
        if not self.has_shared_resource(soundfont_host_resource_key):
            self.set_shared_resource(soundfont_host_resource_key, SoundfontHost(self.soundfont, self.audio_driver))
        self.soundfont_host = self.get_shared_resource(soundfont_host_resource_key)

        if self.soundfont not in self.soundfont_host.soundfont_ids:
            self.soundfont_host.load_soundfont(self.soundfont)

        self.soundfont_instrument = self.soundfont_host.add_instrument(num_channels, bank_and_preset, self.soundfont)

        self.bank_and_preset = bank_and_preset
        self.num_channels = num_channels
        self.set_max_pitch_bend(playback_settings.default_max_midi_pitch_bend
                                if max_pitch_bend == "default" else max_pitch_bend)

    # -------------------------------- Main Playback Methods --------------------------------

    def start_note(self, note_id, pitch, volume, properties, other_parameter_values: dict = None):
        this_note_info = self.note_info_dict[note_id]
        this_note_fixed = "fixed" in this_note_info["flags"]
        int_pitch = int(round(pitch))

        # make a list of available channels to add this note to, ones that won't cause pitch bend / expression conflicts
        available_channels = list(range(self.soundfont_instrument.num_channels))
        oldest_note_id = None
        # go through all currently active notes
        for other_note_id, other_note_info in self.note_info_dict.items():
            # check to see that this other note has been handled by this playback implementation (for instance, a silent
            # note will be skipped, since it was never passed to the playback implementations). Also check that it
            # hasn't been prematurely ended.
            if self in other_note_info and not other_note_info[self]["prematurely_ended"]:
                other_note_channel = other_note_info[self]["channel"]
                other_note_fixed = "fixed" in other_note_info["flags"]
                other_note_pitch = other_note_info["parameter_values"]["pitch"]
                other_note_int_pitch = other_note_info[self]["midi_note"]
                # this new note only share a midi channel with the old note if:
                #   1) both notes are fixed (i.e. will not do a pitch or expression change, which is channel-wide)
                #   2) the notes don't have conflicting microtonality (i.e. one or both need a pitch bend, and it's
                # not the exact same pitch bend.)
                conflicting_microtonality = (pitch != int_pitch or other_note_pitch != other_note_int_pitch) and \
                                            (round(pitch - int_pitch, 5) !=  # round to fix float error
                                             round(other_note_pitch - other_note_int_pitch, 5))
                channel_compatible = this_note_fixed and other_note_fixed and not conflicting_microtonality
                if not channel_compatible:
                    available_channels.remove(other_note_channel)
                    # keep track of the oldest note that's holding onto a channel
                    if oldest_note_id is None or other_note_id < oldest_note_id:
                        oldest_note_id = other_note_id

        # pick the first free channel, or free one up if there are no free channels
        if len(available_channels) > 0:
            # if there's a free channel, return the lowest number available
            channel = available_channels[0]
        else:
            # otherwise, we'll have to kill an old note to find a free channel
            # get the info we stored on this note, related to this specific playback implementation
            # (see end of start_note method for explanation)
            oldest_note_info = self.note_info_dict[oldest_note_id][self]
            self.soundfont_instrument.note_off(oldest_note_info["channel"], oldest_note_info["midi_note"])
            # flag it as prematurely ended so that we send no further midi commands
            oldest_note_info["prematurely_ended"] = True
            # if every channel is playing this pitch, we will end the oldest note so we can
            channel = oldest_note_info["channel"]

        # start the note on that channel
        # note that we start it at the max volume that it wil lever reach, and use expression to get to the start volume
        self.soundfont_instrument.note_on(channel, int_pitch, this_note_info["max_volume"])
        if pitch != int_pitch:
            self.soundfont_instrument.pitch_bend(channel, pitch - int_pitch)
        self.soundfont_instrument.expression(channel, volume / this_note_info["max_volume"])
        # store the midi note that we pressed for this note, the channel we pressed it on, and make an entry (initially
        # false) for whether or not we ended this note prematurely (to free up a channel for a newer note).
        # Note that we're creating here a dictionary within the note_info dictionary, using this PlaybackImplementation
        # instance as the key. This way, there can never be conflict between data stored by this PlaybackImplementation
        # and data stored by other PlaybackImplementations
        this_note_info[self] = {
            "midi_note": int_pitch,
            "channel": channel,
            "prematurely_ended": False
        }

    def end_note(self, note_id):
        this_note_info = self.note_info_dict[note_id]
        assert self in this_note_info, "Note was never started by the SoundfontPlaybackImplementer; this is bad."
        this_note_implementation_info = this_note_info[self]
        if not this_note_implementation_info["prematurely_ended"]:
            self.soundfont_instrument.note_off(this_note_implementation_info["channel"],
                                               this_note_implementation_info["midi_note"])

    def change_note_pitch(self, note_id, new_pitch):
        this_note_info = self.note_info_dict[note_id]
        assert self in this_note_info, "Note was never started by the SoundfontPlaybackImplementer; this is bad."
        this_note_implementation_info = this_note_info[self]
        if not this_note_implementation_info["prematurely_ended"]:
            self.soundfont_instrument.pitch_bend(
                this_note_implementation_info["channel"],
                new_pitch - this_note_implementation_info["midi_note"]
            )

    def change_note_volume(self, note_id, new_volume):
        this_note_info = self.note_info_dict[note_id]
        assert self in this_note_info, "Note was never started by the SoundfontPlaybackImplementer; this is bad."
        this_note_implementation_info = this_note_info[self]
        if not this_note_implementation_info["prematurely_ended"]:
            self.soundfont_instrument.expression(this_note_implementation_info["channel"],
                                                 new_volume / this_note_info["max_volume"])

    def change_note_parameter(self, note_id, parameter_name, new_value):
        # parameter changes are not implemented for SoundfontPlaybackImplementer
        # perhaps they could be for some other uses, maybe program changes?
        pass

    # --------------------------------------- Other ---------------------------------------

    def set_max_pitch_bend(self, semitones):
        self.soundfont_instrument.set_max_pitch_bend(semitones)


class MIDIStreamPlaybackImplementation(PlaybackImplementation):

    def __init__(self, num_channels, midi_output_device=None, midi_output_name=None):
        super().__init__()
        self.num_channels = num_channels
        if midi_output_device is None:
            midi_output_device = playback_settings.default_midi_output_device

        # since rtmidi can only have 16 output channels, we need to create several output devices if we are using more
        if num_channels <= 16:
            self.rt_simple_outs = [SimpleRtMidiOut(midi_output_device, midi_output_name)]
        else:
            self.rt_simple_outs = [
                SimpleRtMidiOut(midi_output_device, midi_output_name + " chans {}-{}".format(chan, chan + 15))
                for chan in range(0, num_channels, 16)
            ]

    def on_register(self):
        self.set_max_pitch_bend(playback_settings.default_max_midi_pitch_bend)

    def start_note(self, note_id, pitch, volume, properties, other_parameter_values: dict = None):
        pass

    def end_note(self, note_id):
        pass

    def change_note_pitch(self, note_id, new_pitch):
        pass

    def change_note_volume(self, note_id, new_volume):
        pass

    def change_note_parameter(self, note_id, parameter_name, new_value):
        pass

    def set_max_pitch_bend(self, semitones):
        pass
