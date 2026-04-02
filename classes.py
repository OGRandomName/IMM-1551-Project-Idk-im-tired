# classes.py
import random
from unittest import loader
from direct.showbase import ShowBaseGlobal
from panda3d.core import (
    Texture, ClockObject, Vec3, TextureStage, LODNode,
    CollisionNode, CollisionSphere, TransparencyAttrib
)
from direct.gui.OnscreenImage import OnscreenImage
from panda3d.core import CardMaker

# Collider metadata
from collisions import SphereCollideObj, BoxCollideObj, MultiBoxCollideObj

DEBUG_COLLIDERS = True


# ============================================================
# Base Class: SpaceObject (visual only)
# ============================================================
class SpaceObject:
    def __init__(self, name, model_path, scale, position,
                 collider_type="sphere", health=100, texture_path=None):

        self.name = name
        self.model_path = model_path
        self.scale = scale
        self.position = position
        self.collider_type = collider_type
        self.health = health
        self.texture_path = texture_path

        # ROOT NODE (no scale!)
        self.node = ShowBaseGlobal.base.render.attachNewNode(self.name + "_ROOT")
        self.node.setPos(*self.position)

        # Load model under the root
        self.model = ShowBaseGlobal.base.loader.loadModel(self.model_path)
        self.model.reparentTo(self.node)

        # Apply scale to MODEL, not root
        self.model.setScale(self.scale)

        # Tag
        self.model.setTag("objectType", self.name)

        # Texture override
        if self.texture_path:
            tex = ShowBaseGlobal.base.loader.loadTexture(self.texture_path)
            if tex:
                self.model.setTexture(tex, 1)

    def set_position(self, pos):
        self.position = pos
        self.node.setPos(*pos)


# ============================================================
# Universe (no collisions)
# ============================================================
class Universe:
    def __init__(self, model_path, scale=15000, position=(0, 0, 0), texture_path=None):
        self.name = "Universe"
        self.model_path = model_path
        self.scale = scale
        self.position = position
        self.texture_path = texture_path

        self.collider_type = None
        self.debug_mode = False

        self.model = ShowBaseGlobal.base.loader.loadModel(self.model_path)
        self.model.reparentTo(ShowBaseGlobal.base.camera)
        self.model.setCompass()

        self.model.setPos(*self.position)
        self.model.setScale(self.scale)

        self.model.setTag("objectType", "Universe")

        if self.texture_path:
            tex = ShowBaseGlobal.base.loader.loadTexture(self.texture_path)
            if tex:
                self.model.setTexture(tex, 1)

        self.model.setTwoSided(True)


# ============================================================
# Planet (Sphere collider)
# ============================================================
import math

class Planet(SpaceObject, SphereCollideObj):
    def __init__(
        self,
        name,
        model_path,
        scale,
        position,
        texture_path=None,
        enable_collisions=True,
        health=100
    ):
        SpaceObject.__init__(
            self,
            name=name,
            model_path=model_path,
            scale=scale,
            position=position,
            collider_type="sphere",
            health=health
        )

        self.enable_collisions = enable_collisions

        if enable_collisions:
            SphereCollideObj.__init__(self, radius=scale)
            self.debug_mode = False
        else:
            self.collider_type = "none"
            self.debug_mode = False

        if texture_path:
            tex = ShowBaseGlobal.base.loader.loadTexture(texture_path)
            self.model.setTexture(tex, 1)

        self.model.flattenStrong()
        self.model.setTwoSided(False)

        ShowBaseGlobal.base.taskMgr.add(self._distance_cull, f"planetCull_{name}")

    def _distance_cull(self, task):
        cam = ShowBaseGlobal.base.camera
        planet_pos = self.node.getPos(ShowBaseGlobal.base.render)
        cam_pos = cam.getPos(ShowBaseGlobal.base.render)

        dx = planet_pos.x - cam_pos.x
        dy = planet_pos.y - cam_pos.y
        dz = planet_pos.z - cam_pos.z
        dist_sq = dx*dx + dy*dy + dz*dz

    def update_spin(self, dt, player_pos):
        planet_pos = self.node.getPos(ShowBaseGlobal.base.render)
        dist = (planet_pos - player_pos).length()

        if dist < 12000:
            self.model.setH(self.model.getH() + 10 * dt)


# ============================================================
# Space Station (Multi‑box collider)
# ============================================================
class SpaceStation(SpaceObject, MultiBoxCollideObj):
    def __init__(self, name, model_path, scale, position, box_list, health=100):
        SpaceObject.__init__(
            self,
            name=name,
            model_path=model_path,
            scale=scale,
            position=position,
            collider_type="multi_box",
            health=health
        )

        MultiBoxCollideObj.__init__(self, box_list)
        self.debug_mode = DEBUG_COLLIDERS


# ============================================================
# Missile Class (must appear BEFORE Player)
# ============================================================
class Missile(SphereCollideObj):
    missileCount = 0
    Models = {}
    Colliders = {}
    Intervals = {}

    def __init__(self, name, model_path, scale, position):
        Missile.missileCount += 1

        self.name = name
        self.model_path = model_path
        self.scale = scale
        self.position = position

        self.node = ShowBaseGlobal.base.render.attachNewNode(name + "_ROOT")
        self.node.setPos(*position)

        self.model = ShowBaseGlobal.base.loader.loadModel(model_path)
        self.model.reparentTo(self.node)
        self.model.setScale(scale)

        # Larger missile collider to avoid tunneling at high speed
        SphereCollideObj.__init__(self, radius=3.0)
        # Show collider while testing; set to False later
        self.debug_mode = DEBUG_COLLIDERS

        Missile.Models[name] = self.model

        print(f"[Missile] Created missile {name} (collider radius=3.0)")



# ============================================================
# Player (Sphere collider + movement + missiles)
# ============================================================
class Player(SpaceObject, SphereCollideObj):
    def __init__(self, name, model_path, scale, position, health=100):
        SpaceObject.__init__(self, name, model_path, scale, position, health)

        SphereCollideObj.__init__(self, radius=3.0)
        self.debug_mode = False

        # Movement
        self.base_speed = 150
        self.speed = self.base_speed
        self.boost_multiplier = 2.0
        self.turn_rate = 55

        # runtime flags
        self.thrusting = False
        self.boost_active = False
        self.boost_queued = False

        self.model.reparentTo(self.node)

        # Missile system
        self.missileBay = 1
        self.maxMissiles = 1
        self.missileDistance = 1200
        self.reloading = False
        self.reloadTime = 0.3

        # HUD
        self.crosshair = OnscreenImage(
            image="Assets/crosshair.png",
            pos=(0, 0, 0),
            scale=0.05
        )
        self.crosshair.setTransparency(TransparencyAttrib.MAlpha)

        # trail placeholder
        self.boost_trail = None

        ShowBaseGlobal.base.taskMgr.add(self.StabilizeRoll, "stabilize-roll")

    # -------------------------------------------------------
    # Missile Firing
    # -------------------------------------------------------
    def Fire(self):
        base = ShowBaseGlobal.base

        if self.missileBay > 0:
            forward = self.node.getQuat(base.render).getForward()
            forward.normalize()

            startPos = self.node.getPos(base.render) + forward * 8
            endPos = startPos + forward * self.missileDistance

            missileName = f"Missile_{Missile.missileCount + 1}"

            missile = Missile(
                name=missileName,
                model_path="Assets/Phaser/phaser.egg",
                scale=0.5,
                position=startPos
            )

            base.collision_manager.register_missile(missile)

            interval = missile.node.posInterval(
                2.0,
                endPos,
                startPos=startPos,
                fluid=1
            )

            Missile.Intervals[missileName] = interval
            interval.start()

            self.missileBay -= 1
            print(f"[Player] Fired {missileName}")

        else:
            print("[Player] No missile in bay — reloading...")
            if not self.reloading:
                self.reloading = True
                ShowBaseGlobal.base.taskMgr.doMethodLater(
                    0, self.Reload, "reloadTask"
                )

    def Reload(self, task):
        if task.time >= self.reloadTime:
            self.missileBay = min(self.missileBay + 1, self.maxMissiles)
            print(f"[Player] Reload complete. Missiles in bay: {self.missileBay}")
            self.reloading = False
            return task.done
        return task.cont

    def CheckIntervals(self, task):
        finished = []

        for name, interval in list(Missile.Intervals.items()):
            if interval.isStopped():
                finished.append(name)

        for name in finished:
            print(f"[Player] Missile {name} finished — deleting")

            if name in Missile.Models:
                Missile.Models[name].removeNode()
                del Missile.Models[name]

            if name in Missile.Colliders:
                Missile.Colliders[name].removeNode()
                del Missile.Colliders[name]

            if name in Missile.Intervals:
                del Missile.Intervals[name]

        return task.cont

    # -------------------------------------------------------
    # MOVEMENT — always move the ROOT (self.node)
    # -------------------------------------------------------
    def Thrust(self, keyDown):
        """
        Start/stop forward thrust. While thrusting, play movement sound.
        If a boost was queued, apply it when thrust begins.
        """
        if keyDown:
            if not self.thrusting:
                self.thrusting = True
                # If a boost was queued, apply it now
                if self.boost_queued:
                    self._apply_boost_now()
                # Start movement sound
                self._play_movement_sound()
                ShowBaseGlobal.base.taskMgr.add(self.ApplyThrust, "forward-thrust")
        else:
            if self.thrusting:
                self.thrusting = False
                ShowBaseGlobal.base.taskMgr.remove("forward-thrust")
                # Stop movement sound
                self._stop_movement_sound()
                # If boost was active, remove it when player stops moving forward
                if self.boost_active:
                    self._clear_boost()

    def _play_movement_sound(self):
        """
        Start a low-volume looping movement sound under other music.
        Stores the AudioSound handle in self._movement_sound if available so it can be stopped.
        """
        if getattr(self, "_movement_sound", None):
            # already playing
            return

        sound_obj = None
        # Try preferred SoundManager APIs in order
        try:
            # If SoundManager exposes a method that returns an AudioSound handle
            sound_obj = ShowBaseGlobal.base.sound.play_sfx("Assets/sounds/player.mp3")
        except Exception:
            try:
                # Another API: play_file may return a handle
                sound_obj = ShowBaseGlobal.base.sound.play_file("Assets/sounds/player.mp3", loop=True)
            except Exception:
                try:
                    # Fallback: load a temporary bank and play it (may not return handle)
                    ShowBaseGlobal.base.sound.load_bank("temp_player", ["Assets/sounds/player.mp3"], loop=True, volume=0.25)
                    ShowBaseGlobal.base.sound.play_random_from_bank("temp_player")
                except Exception:
                    print("[Sound] Could not start player movement sound (no supported SoundManager API).")

        # If we got a handle, set it to low volume and loop
        if sound_obj is not None:
            try:
                # Make it quiet so it sits under background/boss music
                sound_obj.setLoop(True)
                sound_obj.setVolume(0.18)   # quiet: ~18% volume
            except Exception:
                try:
                    sound_obj.setVolume(0.2)
                except Exception:
                    pass
            self._movement_sound = sound_obj

    def _stop_movement_sound(self):
        """
        Stop the movement sound if it was started and a handle is available.
        """
        sound_obj = getattr(self, "_movement_sound", None)
        if sound_obj is not None:
            try:
                sound_obj.stop()
            except Exception:
                pass
            try:
                del self._movement_sound
            except Exception:
                self._movement_sound = None



    def ApplyThrust(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        cam_h = ShowBaseGlobal.base.camera.getH(ShowBaseGlobal.base.render)
        self.node.setH(cam_h)
        self.node.setY(self.node, self.speed * dt)
        return task.cont

    def ReverseThrust(self, keyDown):
        if keyDown:
            ShowBaseGlobal.base.taskMgr.add(self.ApplyReverseThrust, "reverse-thrust")
        else:
            ShowBaseGlobal.base.taskMgr.remove("reverse-thrust")

    def ApplyReverseThrust(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        cam_h = ShowBaseGlobal.base.camera.getH(ShowBaseGlobal.base.render)
        self.node.setH(cam_h)
        self.node.setY(self.node, -self.speed * dt)
        return task.cont

    def MoveUp(self, keyDown):
        if keyDown:
            ShowBaseGlobal.base.taskMgr.add(self.ApplyMoveUp, "move-up")
        else:
            ShowBaseGlobal.base.taskMgr.remove("move-up")

    def ApplyMoveUp(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self.node.setZ(self.node.getZ() + self.speed * dt)
        return task.cont

    def MoveDown(self, keyDown):
        if keyDown:
            ShowBaseGlobal.base.taskMgr.add(self.ApplyMoveDown, "move-down")
        else:
            ShowBaseGlobal.base.taskMgr.remove("move-down")

    def ApplyMoveDown(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self.node.setZ(self.node.getZ() - self.speed * dt)
        return task.cont

    def LeftTurn(self, keyDown):
        if keyDown:
            ShowBaseGlobal.base.taskMgr.add(self.ApplyLeftTurn, "left-turn")
        else:
            ShowBaseGlobal.base.taskMgr.remove("left-turn")

    def ApplyLeftTurn(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self.node.setH(self.node.getH() + self.turn_rate * dt)
        return task.cont

    def RightTurn(self, keyDown):
        if keyDown:
            ShowBaseGlobal.base.taskMgr.add(self.ApplyRightTurn, "right-turn")
        else:
            ShowBaseGlobal.base.taskMgr.remove("right-turn")

    def ApplyRightTurn(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self.node.setH(self.node.getH() - self.turn_rate * dt)
        return task.cont

    def RollLeft(self, keyDown):
        if keyDown:
            ShowBaseGlobal.base.taskMgr.add(self.ApplyRollLeft, "roll-left")
        else:
            ShowBaseGlobal.base.taskMgr.remove("roll-left")

    def ApplyRollLeft(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self.node.setR(self.node.getR() + self.turn_rate * dt)
        return task.cont

    def RollRight(self, keyDown):
        if keyDown:
            ShowBaseGlobal.base.taskMgr.add(self.ApplyRollRight, "roll-right")
        else:
            ShowBaseGlobal.base.taskMgr.remove("roll-right")

    def ApplyRollRight(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        self.node.setR(self.node.getR() - self.turn_rate * dt)
        return task.cont

    def StabilizeRoll(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        current_r = self.node.getR()
        target_r = 0
        damping = 4
        new_r = current_r + (target_r - current_r) * damping * dt
        self.node.setR(new_r)
        return task.cont

    #-------------------------------------------------------
    # Boost helpers (apply while thrusting; cleared when stop)
    #-------------------------------------------------------
    def _apply_boost_now(self):
        if not self.boost_active:
            self.boost_active = True
            self.boost_queued = False
            self.speed = self.base_speed * self.boost_multiplier
            self.enable_boost_trail()
            self.spawn_shockwave()
            print(f"[Player] Boost applied. Speed = {self.speed}")

    def _queue_boost(self):
        self.boost_queued = True
        print("[Player] Boost queued (will apply when you start thrusting).")

    def _clear_boost(self):
        self.boost_active = False
        self.boost_queued = False
        self.speed = self.base_speed
        self.disable_boost_trail()
        print("[Player] Boost cleared. Speed reset to base.")

    #-------------------------------------------------------
    # Boost Trail & Shockwave
    #-------------------------------------------------------
    def enable_boost_trail(self):
        # Remove old trail if it exists
        if hasattr(self, "boost_trail") and self.boost_trail:
            try:
                self.boost_trail.removeNode()
            except Exception:
                pass

        # Create a simple quad using CardMaker (no external model required)
        cm = CardMaker("boost_trail_card")
        cm.setFrame(-0.5, 0.5, -0.5, 0.5)  # unit quad
        card = self.node.attachNewNode(cm.generate())
        card.setTwoSided(True)
        card.setBillboardPointEye()
        card.setPos(0, -6, 0)

        # Stretch it into a long trail and tint it
        card.setScale(0.4, 1.8, 0.4)
        card.setColorScale(1, 1, 1, 0.9)
        card.setTransparency(TransparencyAttrib.MAlpha)

        self.boost_trail = card


    def disable_boost_trail(self):
        if hasattr(self, "boost_trail") and self.boost_trail:
            self.boost_trail.removeNode()
            self.boost_trail = None

    def spawn_shockwave(self):
        # Minimal procedural shockwave using CardMaker
        cm = CardMaker("shockwave_card")
        cm.setFrame(-0.5, 0.5, -0.5, 0.5)
        card = self.node.attachNewNode(cm.generate())
        card.setPos(0, 6, 0)
        card.setScale(0.5)
        card.setBillboardPointEye()
        card.setColorScale(1.0, 0.6, 0.1, 0.9)
        card.setTransparency(TransparencyAttrib.MAlpha)

        def _grow(task, node=card):
            dt = ClockObject.getGlobalClock().getDt()
            # expand uniformly
            s = node.getScale()
            node.setScale(s + Vec3(6 * dt))
            r, g, b, a = node.getColorScale()
            node.setColorScale(r, g, b, max(0.0, a - 2.0 * dt))
            if node.getColorScale()[3] <= 0:
                try:
                    node.removeNode()
                except Exception:
                    pass
                return task.done
            return task.cont

        ShowBaseGlobal.base.taskMgr.add(_grow, "shockwave_grow")


# ============================================================
# Drone (Sphere collider, drift‑free, smooth orbit)
# ============================================================
class DroneDefender(SpaceObject, SphereCollideObj):
    def __init__(self, name, model_path, scale, position, orbit_radius=20, health=10):
        SpaceObject.__init__(self, name, model_path, scale, position, health)
        SphereCollideObj.__init__(self, radius=7.5)
        self.debug_mode = DEBUG_COLLIDERS

        # Orbit metadata
        self.orbit_center = position
        self.orbit_radius = orbit_radius
        self.orbit_angle = 0.0
        self.orbit_speed = 0.5

        # Pattern switching
        self.orbit_mode = "circleZ"
        self.pattern_timer = 0.0
        self.pattern_interval = random.uniform(10.0, 14.0)

        # Transition state
        self.transition_time = 0.0
        self.transition_duration = 5.0
        self.transition_active = False
        self.start_pos = None
        self.target_pos = None

        self.active = False  # set by SpaceJam
        self.model.reparentTo(self.node)

    def switch_pattern(self):
        modes = ["circleX", "circleY", "circleZ", "cloud", "seams"]
        self.orbit_mode = random.choice(modes)

        self.transition_time = 0.0
        self.transition_active = True
        self.start_pos = self.node.getPos()
        self.target_pos = None

        self.pattern_timer = 0.0
        self.pattern_interval = random.uniform(10.0, 14.0)

    def update(self, dt, player_pos):
        from dronepatterns import update_orbit, update_transition

        if not self.active:
            return

        self.pattern_timer += dt
        if self.pattern_timer >= self.pattern_interval:
            self.switch_pattern()

        orbit_target = update_orbit(self, dt)
        final_pos = update_transition(self, dt, orbit_target)
        self.node.setPos(final_pos)


# ============================================================
# Drone Counter
# ============================================================
class DroneCounter:
    def __init__(self):
        self.count = 0

    def register_drone(self):
        self.count += 1

    def get_count(self):
        return self.count


# ============================================================
# Boost Ring (sphere collider + upright + spin + flames)
# ============================================================
class BoostRing(SpaceObject, SphereCollideObj):
    def __init__(self, name, position, scale=20):
        # Load model normally; apply model scale after rotation so collider aligns
        SpaceObject.__init__(
            self,
            name=name,
            model_path="Assets/planets/flame-ring.fbx",
            scale=1,              # model scale applied below
            position=position,
            collider_type="sphere"
        )

        # Rotate upright and then scale the model so collider aligns
        self.model.setHpr(0, 90, 0)
        self.model.setScale(scale, scale, 0.2)
        self.model.setColorScale(1.5, 0.5, 0.1, 1)
        self.model.setTransparency(TransparencyAttrib.MAlpha)

        # Collider radius (create AFTER model scale so radius matches)
        SphereCollideObj.__init__(self, radius=scale * 0.6, debug=True)
        self.debug_mode = True

        # Spin animation
        ShowBaseGlobal.base.taskMgr.add(self.spin, f"spin_{name}")

        # Simple procedural flame sprites
        self._flame_sprites = []
        self._flame_task_name = f"flame_{name}"
        ShowBaseGlobal.base.taskMgr.add(self._flame_task, self._flame_task_name)

    def spin(self, task):
        self.model.setH(self.model.getH() + 60 * task.dt)
        return task.cont

    def _flame_task(self, task):
        # Spawn occasional flame quads inside the ring hole using CardMaker
        if random.random() < 0.25:
            cm = CardMaker("flame_card")
            cm.setFrame(-0.5, 0.5, -0.5, 0.5)
            card = self.node.attachNewNode(cm.generate())
            # place inside ring hole with small random offset
            ox = random.uniform(-self.model.getScale().x * 0.3, self.model.getScale().x * 0.3)
            oy = 0
            oz = random.uniform(-self.model.getScale().z * 0.1, self.model.getScale().z * 0.1)
            card.setPos(ox, oy, oz)
            card.setBillboardPointEye()
            card.setScale(random.uniform(0.6, 1.4))
            card.setColorScale(1.0, random.uniform(0.4, 0.8), 0.1, 0.9)
            card.setTransparency(TransparencyAttrib.MAlpha)
            life = random.uniform(0.6, 1.2)
            self._flame_sprites.append([card, life])

        # Update existing sprites
        dt = ClockObject.getGlobalClock().getDt()
        for entry in list(self._flame_sprites):
            sprite, life = entry
            life -= dt
            sprite.setZ(sprite.getZ() + 1.5 * dt)
            r, g, b, a = sprite.getColorScale()
            sprite.setColorScale(r, g, b, max(0.0, a - 1.2 * dt))
            if life <= 0 or sprite.getColorScale()[3] <= 0:
                try:
                    sprite.removeNode()
                except Exception:
                    pass
                try:
                    self._flame_sprites.remove(entry)
                except Exception:
                    pass
            else:
                entry[1] = life

        return task.cont

