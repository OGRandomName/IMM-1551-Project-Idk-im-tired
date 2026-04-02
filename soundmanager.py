# soundmanager.py

from direct.showbase import ShowBaseGlobal
from direct.task import Task
import random

class SoundManager:
    def __init__(self):
        self.sounds = {}
        self.sfx = {}              
        self.music_banks = {}
        self.current_track = None
        self.fade_task = None
        self.master_volume = 1.0
        self.music_volume = 0.7
        self.sfx_volume = 1.0

        loader = ShowBaseGlobal.base.loader  

        # Load boost SFX
        self.sfx["boost1"] = loader.loadSfx("Assets/sounds/boost.mp3")
        self.sfx["boost2"] = loader.loadSfx("Assets/sounds/boosted-rocket.mp3")



    def apply_volumes(self):
        # Apply master + music volumes to all music banks
        for bank in self.music_banks.values():
            for snd in bank:
                snd.setVolume(self.master_volume * self.music_volume)

        # Apply master + sfx volumes to all SFX
        for snd in self.sounds.values():
            snd.setVolume(self.master_volume * self.sfx_volume)


    def load(self, name, path, loop=False, volume=1.0):
        snd = ShowBaseGlobal.base.loader.loadSfx(path)
        snd.setLoop(loop)
        snd.setVolume(volume)
        self.sounds[name] = snd

    def play(self, name):
        if name in self.sounds:
            self.sounds[name].play()

    def stop(self, name):
        if name in self.sounds:
            self.sounds[name].stop()

    def load_bank(self, bank_name, file_list, loop=True, volume=1.0):
        self.music_banks[bank_name] = []
        for path in file_list:
            snd = ShowBaseGlobal.base.loader.loadSfx(path)
            snd.setLoop(loop)
            snd.setVolume(volume)
            self.music_banks[bank_name].append(snd)

    def play_random_from_bank(self, bank_name):
        if bank_name not in self.music_banks:
            return None

        # Stop previous track
        if self.current_track:
            self.current_track.stop()

        snd = random.choice(self.music_banks[bank_name])
        snd.play()
        self.current_track = snd
        return snd

    # ---------------------------------------------------------
    # CROSSFADE SYSTEM
    # ---------------------------------------------------------
    def crossfade(self, from_bank, to_bank, duration=2.0):
        base = ShowBaseGlobal.base

        # Stop any existing fade task
        if self.fade_task:
            base.taskMgr.remove(self.fade_task)

        # Pick new track
        new_track = random.choice(self.music_banks[to_bank])
        new_track.setVolume(0)
        new_track.play()

        old_track = self.current_track
        self.current_track = new_track

        # Fade task
        def fade_task(task):
            t = min(task.time / duration, 2.0)

            if old_track:
                old_track.setVolume(1.0 - t)
            new_track.setVolume(t)

            if t >= 1.0:
                if old_track:
                    old_track.stop()
                return Task.done

            return Task.cont

        self.fade_task = base.taskMgr.add(fade_task, "musicCrossfade")

    def play_random_boost(self):
        choice = random.choice(["boost1", "boost2"])
        s = self.sfx[choice]
        s.setVolume(self.sfx_volume * self.master_volume)
        s.play()
