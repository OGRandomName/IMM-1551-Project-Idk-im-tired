# collisions.py
from panda3d.core import BitMask32, TransparencyAttrib, ClockObject
from panda3d.core import (
    CollisionNode, CollisionSphere, CollisionBox,
    CollisionTraverser, CollisionHandlerPusher,
    CollisionHandlerEvent
)
from panda3d.core import CardMaker, Vec3
MASK_PLAYER  = BitMask32.bit(0)
MASK_PLANET  = BitMask32.bit(1)
MASK_DRONE   = BitMask32.bit(2)
MASK_STATIC  = BitMask32.bit(3)
MASK_MISSILE = BitMask32.bit(4)


# ----------------------------------------------------
# Base collider metadata classes
# ----------------------------------------------------
class SphereCollideObj:
    def __init__(self, radius, debug=True):
        self.collider_type = "sphere"
        self.collider_radius = radius
        self.debug_mode = debug
        self.collider = None


class BoxCollideObj:
    def __init__(self, size_xyz, debug=True):
        self.collider_type = "box"
        self.collider_size = size_xyz
        self.debug_mode = debug
        self.collider = None


class MultiBoxCollideObj:
    def __init__(self, box_list, debug=True):
        self.collider_type = "multi_box"
        self.collider_boxes = box_list
        self.debug_mode = debug
        self.collider = None


# ----------------------------------------------------
# Collision Manager
# ----------------------------------------------------
class CollisionManager:
    def __init__(self, base):
        self.base = base

        self.traverser = CollisionTraverser("mainTraverser")
        self.base.cTrav = self.traverser

        self.pusher = CollisionHandlerPusher()
        self.events = CollisionHandlerEvent()
        self.events.addInPattern("%fn-into-%in")

        print("\n[CollisionManager] Initialized.")

    # ----------------------------------------------------
    # Create collider for ANY object
    # ----------------------------------------------------
    def create_collider(self, obj):
        if not hasattr(obj, "collider_type"):
            print(f"[CollisionManager] WARNING: {obj} has no collider_type; skipping.")
            return None

        if obj.collider_type == "multi_box":
            cnode = CollisionNode(obj.name)
            for box in obj.collider_boxes:
                cx, cy, cz = box["center"]
                sx, sy, sz = box["size"]
                solid = CollisionBox((cx, cy, cz), sx, sy, sz)
                cnode.addSolid(solid)

        elif obj.collider_type == "sphere":
            cnode = CollisionNode(obj.name)
            solid = CollisionSphere(0, 0, 0, obj.collider_radius)
            cnode.addSolid(solid)

        elif obj.collider_type == "box":
            cnode = CollisionNode(obj.name)
            x, y, z = obj.collider_size
            solid = CollisionBox((0, 0, 0), x, y, z)
            cnode.addSolid(solid)

        else:
            print(f"[CollisionManager] No collider created for {obj.name}.")
            return None

        cpath = obj.node.attachNewNode(cnode)
        cpath.show() if getattr(obj, "debug_mode", False) else cpath.hide()
        obj.collider = cpath
        return cpath

    # ----------------------------------------------------
    # PLAYER COLLIDER (push + events)
    # ----------------------------------------------------
    def register_player(self, player):
        cpath = self.create_collider(player)
        if cpath:
            # Player is FROM for events; INTO mask off
            cpath.node().setFromCollideMask(MASK_PLAYER)
            cpath.node().setIntoCollideMask(BitMask32.allOff())

            # Player pushes against statics/drones via pusher
            player.node.setCollideMask(MASK_PLANET | MASK_DRONE | MASK_STATIC)

            # Add to pusher (physical collisions)
            self.pusher.addCollider(cpath, player.node)
            self.traverser.addCollider(cpath, self.pusher)

            # ALSO add to event handler so INTO-only objects (rings, drones) trigger events
            self.traverser.addCollider(cpath, self.events)

            print("[CollisionManager] Player collider registered.")

    # ----------------------------------------------------
    # STATIC OBJECTS (planets, station)
    # ----------------------------------------------------
    def register_static(self, obj):
        cpath = self.create_collider(obj)
        if cpath:
            cpath.node().setFromCollideMask(BitMask32.allOff())
            cpath.node().setIntoCollideMask(MASK_PLAYER | MASK_MISSILE)

    # ----------------------------------------------------
    # Drones use EVENT collisions
    # ----------------------------------------------------
    def register_drone(self, drone):
        cpath = self.create_collider(drone)
        if cpath:
            # Drones are INTO for player and missiles
            cpath.node().setFromCollideMask(BitMask32.allOff())
            cpath.node().setIntoCollideMask(MASK_PLAYER | MASK_MISSILE)
            self.traverser.addCollider(cpath, self.events)
            print(f"[CollisionManager] Drone collider registered: {drone.name}")

    # ----------------------------------------------------
    # Missiles use EVENT collisions
    # ----------------------------------------------------
    def register_missile(self, missile):
        cpath = self.create_collider(missile)
        if cpath:
            # Missile is FROM only and should hit drones
            cpath.node().setFromCollideMask(MASK_MISSILE)
            cpath.node().setIntoCollideMask(BitMask32.allOff())

            # Track collider so we can delete it if needed
            from classes import Missile
            Missile.Colliders[missile.name] = cpath

            # Show collider if missile debug_mode is True
            if getattr(missile, "debug_mode", False):
                cpath.show()
            else:
                cpath.hide()

            # Ensure traverser will deliver events for missile FROM collisions
            self.traverser.addCollider(cpath, self.events)
            print(f"[CollisionManager] Missile collider registered: {missile.name}")


    # ---------------- Missile events ----------------
    def on_missile_hits_drone(self, entry):
        """
        Robust missile->drone handler:
        - destroys missile immediately
        - spawns a simple explosion VFX at the drone position
        - removes the drone from orbit and scene
        - attempts to play bossfight13.mp3 (robust fallbacks)
        """
        from_node = entry.getFromNode().getName()   # Missile_*
        into_node = entry.getIntoNode().getName()   # Drone_*

        print("[Collision] Missile hit drone:", into_node)

        # Destroy missile immediately
        self._destroy_missile_now(from_node)

        # Find the drone object
        target_drone = None
        for drone in list(self.base.orbiting_drones):
            if drone.name == into_node:
                target_drone = drone
                break

        if target_drone is None:
            print("[Collision] Warning: drone object not found for", into_node)
            return

        # Explosion VFX (procedural quad)
        drone_node = target_drone.node
        pos = drone_node.getPos(self.base.render)

        cm = CardMaker("explosion_card")
        cm.setFrame(-0.5, 0.5, -0.5, 0.5)
        explosion = self.base.render.attachNewNode(cm.generate())
        explosion.setPos(pos)
        explosion.setBillboardPointEye()
        explosion.setScale(0.6)
        explosion.setColorScale(1.0, 0.6, 0.1, 1.0)
        explosion.setTransparency(True)

        def _explode(task, node=explosion):
            dt = ClockObject.getGlobalClock().getDt()
            node.setScale(node.getScale() + Vec3(8 * dt))
            r, g, b, a = node.getColorScale()
            node.setColorScale(r, g, b, max(0.0, a - (2.0 * dt)))
            if node.getColorScale()[3] <= 0:
                try:
                    node.removeNode()
                except Exception:
                    pass
                return task.done
            return task.cont

        self.base.taskMgr.add(_explode, f"explosion_{into_node}")

        # Play bossfight music (robust attempts)
        try:
            # Preferred: play a specific file if SoundManager supports it
            self.base.sound.play_file("Assets/sounds/bossfight/bossfight13.mp3")
        except Exception:
            try:
                self.base.sound.play_sfx("Assets/sounds/bossfight/bossfight13.mp3")
            except Exception:
                try:
                    # fallback: create a temporary bank and play it
                    self.base.sound.load_bank("temp_boss", ["Assets/sounds/bossfight/bossfight13.mp3"], loop=True, volume=0.7)
                    self.base.sound.play_random_from_bank("temp_boss")
                except Exception:
                    print("[Collision] Could not play bossfight13.mp3 (no supported SoundManager API).")

        # Remove drone from orbit list and scene
        try:
            self.base.orbiting_drones.remove(target_drone)
        except ValueError:
            pass

        try:
            target_drone.node.removeNode()
        except Exception:
            pass

        print("[Collision] Drone destroyed:", into_node)

    # ----------------------------------------------------
    # Manual update + proximity kill for missiles + extra missile->drone proximity check
    # ----------------------------------------------------
    def update(self, task):
        # Normal collision traversal
        self.traverser.traverse(self.base.render)

        # Extra: proximity-based missile kill for planets + station (existing)
        from classes import Missile
        planet_kill_distance = 250.0
        station_kill_distance = 30.0

        station_node = getattr(self.base, "station", None)
        planets = getattr(self.base, "planets", [])

        # Iterate over active missiles
        for m_name, m_model in list(Missile.Models.items()):
            # Missile root is the parent of the model
            m_node = m_model.getParent()
            m_pos = m_node.getPos(self.base.render)

            # Check planets
            for planet in planets:
                p_pos = planet.node.getPos(self.base.render)
                if (m_pos - p_pos).length() <= planet_kill_distance:
                    print(f"[Proximity] Missile {m_name} near planet {planet.name} — destroying")
                    self._destroy_missile_now(m_name)
                    break  # stop checking this missile

            # If missile already destroyed, skip further checks
            if m_name not in Missile.Models:
                continue

            # Check station
            if station_node is not None:
                s_pos = station_node.node.getPos(self.base.render)
                if (m_pos - s_pos).length() <= station_kill_distance:
                    print(f"[Proximity] Missile {m_name} near station — destroying")
                    self._destroy_missile_now(m_name)

        # -------------------------
        # NEW: Proximity-based missile->drone interaction (fallback)
        # -------------------------
        # This ensures missiles still destroy drones even if the event system misses the collision.
        try:
            missile_drone_kill_distance = 8.0
            missiles_copy = list(Missile.Models.items())
            drones_copy = list(self.base.orbiting_drones)
            for m_name, m_model in missiles_copy:
                if m_name not in Missile.Models:
                    continue
                m_node = m_model.getParent()
                m_pos = m_node.getPos(self.base.render)
                for drone in drones_copy:
                    d_pos = drone.node.getPos(self.base.render)
                    dist = (m_pos - d_pos).length()
                    # Debug log for proximity checks
                    if dist <= missile_drone_kill_distance:
                        print(f"[Proximity] Missile {m_name} within {dist:.2f} of drone {drone.name} (threshold {missile_drone_kill_distance}) — triggering hit")
                        # Build a minimal fake entry and call handler
                        class _FakeEntry:
                            def __init__(self, from_name, into_name):
                                self._from = from_name
                                self._into = into_name
                            def getFromNode(self):
                                class N: 
                                    def __init__(self, name): self._n = name
                                    def getName(self): return self._n
                                return N(self._from)
                            def getIntoNode(self):
                                class N:
                                    def __init__(self, name): self._n = name
                                    def getName(self): return self._n
                                return N(self._into)
                        fake_entry = _FakeEntry(m_name, drone.name)
                        self.on_missile_hits_drone(fake_entry)
                        break
        except Exception as e:
            print("[Collision] Proximity missile->drone fallback error:", e)

        return task.cont

    # ----------------------------------------------------
    # Boost ring registration
    # ----------------------------------------------------
    def register_boost_ring(self, ring):
        cpath = self.create_collider(ring)
        if cpath:
            cpath.node().setFromCollideMask(BitMask32.allOff())
            cpath.node().setIntoCollideMask(MASK_PLAYER)

            # Show collider if debug enabled
            if getattr(ring, "debug_mode", False):
                cpath.show()
            else:
                cpath.hide()

            print(f"[CollisionManager] Registered boost ring collider for {ring.name}")

    # ----------------------------------------------------
    # Event hooks
    # ----------------------------------------------------
    def setup_events(self):
        # Player collisions
        self.base.accept("PlayerShip-into-Drone_*", self.on_player_hits_drone)
        self.base.accept("PlayerShip-into-PLANET*", self.on_player_hits_planet)
        self.base.accept("PlayerShip-into-MainStation", self.on_player_hits_station)
        self.base.accept("PlayerShip-into-BoostRing_*", self.on_player_hits_boost_ring)

        # Missile collisions
        self.base.accept("Missile_*-into-Drone_*", self.on_missile_hits_drone)
        self.base.accept("Missile_*-into-PLANET*", self.on_missile_hits_planet)
        self.base.accept("Missile_*-into-MainStation", self.on_missile_hits_station)

        print("[CollisionManager] Event hooks active.")

    # ---------------- Player events ----------------
    def on_player_hits_drone(self, entry):
        print("[Collision] Player hit drone:", entry.getIntoNode().getName())

    def on_player_hits_planet(self, entry):
        print("[Collision] Player hit planet:", entry.getIntoNode().getName())

    def on_player_hits_station(self, entry):
        print("[Collision] Player hit station!")

    # ---------------- Missile cleanup helper ----------------
    def _destroy_missile_now(self, missile_name):
        from classes import Missile

        # Stop interval
        if missile_name in Missile.Intervals:
            Missile.Intervals[missile_name].finish()
            del Missile.Intervals[missile_name]

        # Remove model
        if missile_name in Missile.Models:
            Missile.Models[missile_name].removeNode()
            del Missile.Models[missile_name]

        # Remove collider
        if missile_name in Missile.Colliders:
            Missile.Colliders[missile_name].removeNode()
            del Missile.Colliders[missile_name]

    # ---------------- Missile events ----------------
    def on_missile_hits_drone(self, entry):
        """
        Called when a missile collides with a drone.
        - Destroys the missile immediately (intervals, model, collider).
        - Spawns a short explosion VFX at the drone position.
        - Removes the drone from orbit list and scene.
        - Starts bossfight music (bossfight13.mp3).
        """
        from_node = entry.getFromNode().getName()   # Missile_*
        into_node = entry.getIntoNode().getName()   # Drone_*

        print("[Collision] Missile hit drone:", into_node)

        # Destroy missile immediately
        self._destroy_missile_now(from_node)

        # Find the drone object and its node
        target_drone = None
        for drone in list(self.base.orbiting_drones):
            if drone.name == into_node:
                target_drone = drone
                break

        # If we found the drone, spawn explosion VFX at its world position then remove it
        if target_drone is not None:
            # Get world position for the effect
            drone_node = target_drone.node
            pos = drone_node.getPos(self.base.render)

            # Create a simple procedural explosion using CardMaker (no external model)
            from panda3d.core import CardMaker, NodePath, Vec3
            cm = CardMaker("explosion_card")
            cm.setFrame(-0.5, 0.5, -0.5, 0.5)
            explosion = self.base.render.attachNewNode(cm.generate())
            explosion.setPos(pos)
            explosion.setBillboardPointEye()
            explosion.setScale(0.5)
            explosion.setColorScale(1.0, 0.6, 0.1, 1.0)
            explosion.setTransparency(True)

            # Animate explosion: expand + fade then remove
            def _explode(task, node=explosion, life=0.6):
                dt = ClockObject.getGlobalClock().getDt()
                node.setScale(node.getScale() + Vec3(8 * dt))
                r, g, b, a = node.getColorScale()
                node.setColorScale(r, g, b, max(0.0, a - (1.6 * dt)))
                if node.getColorScale()[3] <= 0:
                    try:
                        node.removeNode()
                    except Exception:
                        pass
                    return task.done
                return task.cont

            self.base.taskMgr.add(_explode, f"explosion_{into_node}")

            # Play bossfight music (try a few SoundManager APIs)
            try:
                # Preferred: play a specific file or bank entry
                self.base.sound.play_file("Assets/sounds/bossfight/bossfight13.mp3")
            except Exception:
                try:
                    # Fallback: direct SFX play
                    self.base.sound.play_sfx("Assets/sounds/bossfight/bossfight13.mp3")
                except Exception:
                    try:
                        # Fallback: load a temporary bank and play the file
                        self.base.sound.load_bank("temp_boss", ["Assets/sounds/bossfight/bossfight13.mp3"], loop=True, volume=0.8)
                        self.base.sound.play_random_from_bank("temp_boss")
                    except Exception:
                        print("[Collision] Could not play bossfight13.mp3 (no supported SoundManager API).")

            # Remove drone from orbit list and scene
            try:
                self.base.orbiting_drones.remove(target_drone)
            except ValueError:
                pass

            try:
                target_drone.node.removeNode()
            except Exception:
                pass

            print("[Collision] Drone destroyed:", into_node)

        else:
            print("[Collision] Warning: drone object not found for", into_node)

    def on_missile_hits_planet(self, entry):
        from_node = entry.getFromNode().getName()
        into_node = entry.getIntoNode().getName()

        print("[Collision] Missile hit planet:", into_node)

        # Destroy missile immediately
        self._destroy_missile_now(from_node)

    def on_missile_hits_station(self, entry):
        from_node = entry.getFromNode().getName()
        into_node = entry.getIntoNode().getName()

        print("[Collision] Missile hit station:", into_node)

        # Destroy missile immediately
        self._destroy_missile_now(from_node)

    # ----------------------------------------------------
    # Boost ring event
    # ----------------------------------------------------
    def on_player_hits_boost_ring(self, entry):
        into_name = entry.getIntoNode().getName()
        print(f"[Boost] Player hit a boost ring: {into_name}")

        player = self.base.player

        # Direction check — only boost when passing through forward
        player_forward = player.node.getQuat(self.base.render).getForward()
        ring_np = entry.getIntoNodePath().getParent()
        ring_forward = ring_np.getQuat(self.base.render).getForward()
        dot = player_forward.dot(ring_forward)
        print(f"[Boost] Direction dot = {dot:.3f}")

        # Allow a small tolerance so near-forward counts
        if dot < 0.1:
            print("[Boost] Wrong direction — no boost")
            return

        # Play boost sound (try a few common SoundManager APIs)
        try:
            # Preferred: direct SFX play if available
            self.base.sound.play_sfx("Assets/sounds/boost.mp3")
        except Exception:
            try:
                # Fallback: named helper
                self.base.sound.play_random_boost()
            except Exception:
                try:
                    # Fallback: play single file via bank API if present
                    self.base.sound.play_file("Assets/sounds/boost.mp3")
                except Exception:
                    print("[Boost] No boost sound method available; skipping sound.")

        # If player is currently thrusting, apply boost immediately; otherwise queue it
        if getattr(player, "thrusting", False):
            player._apply_boost_now()
        else:
            player._queue_boost()

        # Remove the ring from the world + list
        for ring in list(self.base.boost_rings):
            if ring.name == into_name:
                ring.node.removeNode()
                self.base.boost_rings.remove(ring)
                print(f"[Boost] Removed ring {into_name}")
                break

        # No automatic reset here — boost is cleared when player stops thrusting

    # ----------------------------------------------------
    # Update loop (collision traversal + optional missile proximity)
    # ----------------------------------------------------
    def update(self, task):
        # Normal collision traversal
        self.traverser.traverse(self.base.render)

        # Extra: proximity-based missile kill for planets + station (optional)
        from classes import Missile
        planet_kill_distance = 250.0
        station_kill_distance = 30.0

        station_node = getattr(self.base, "station", None)
        planets = getattr(self.base, "planets", [])

        for m_name, m_model in list(Missile.Models.items()):
            m_node = m_model.getParent()
            m_pos = m_node.getPos(self.base.render)

            for planet in planets:
                p_pos = planet.node.getPos(self.base.render)
                if (m_pos - p_pos).length() <= planet_kill_distance:
                    print(f"[Proximity] Missile {m_name} near planet {planet.name} — destroying")
                    self._destroy_missile_now(m_name)
                    break

            if m_name not in Missile.Models:
                continue

            if station_node is not None:
                s_pos = station_node.node.getPos(self.base.render)
                if (m_pos - s_pos).length() <= station_kill_distance:
                    print(f"[Proximity] Missile {m_name} near station — destroying")
                    self._destroy_missile_now(m_name)

        return task.cont
