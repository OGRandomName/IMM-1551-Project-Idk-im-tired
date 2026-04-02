# spacejam.py
import math
import os
import random
from panda3d.core import Vec3
from direct.showbase.ShowBase import ShowBase
from direct.showbase import ShowBaseGlobal
from panda3d.core import ClockObject
from direct.gui.DirectGui import DirectFrame, DirectButton, DirectLabel
from panda3d.core import TransparencyAttrib
from soundmanager import SoundManager
from menu import ExitMenu, AudioMenu, MenuManager, PauseMenu

from collisions import CollisionManager

from classes import (
    BoostRing,
    Planet,
    SpaceStation,
    Player,
    DroneDefender,
    Universe,
    DroneCounter,
)
from dronepatterns import (
    circleX_pattern,
    circleY_pattern,
    circleZ_pattern,
    cloud_pattern,
    baseball_seams_pattern
)

# How close the player must be to activate spinning/orbiting
PLANET_ACTIVATION_DISTANCE = 12000
DRONE_ACTIVATION_DISTANCE = 5000

# how close drones must be to influence each other
DRONE_SWARM_RADIUS = 2500


# ---------------------------------------------------------
# GLOBAL PERFORMANCE MODE
# ---------------------------------------------------------
# True  = fewer drones, fewer decorated planets, more culling, lighter CPU load
# False = full visual experience
PERFORMANCE_MODE = False

PATTERN_FUNCTIONS = [
    circleX_pattern,
    circleY_pattern,
    circleZ_pattern,
    cloud_pattern,
    baseball_seams_pattern
]


class SpaceJam(ShowBase):
    def __init__(self):
        super().__init__()

        # Make sure ShowBaseGlobal.base is this instance
        ShowBaseGlobal.base = self

        # Basic runtime containers
        self.ui_mode = False
        self.drone_counter = DroneCounter()
        self.orbiting_drones = []
        self.planets = []
        self.boost_rings = []

        # Create world pieces that don't depend on the player
        self.setup_space_station()

        # Create collision manager ONCE and early so rings/planets can register
        self.collision_manager = CollisionManager(self)

        # Spawn planets and boost rings (these call collision_manager.register_boost_ring)
        # setup_planets will append to self.planets and self.orbiting_drones
        self.setup_planets()

        # Create universe (skybox) - doesn't require player
        self.setup_universe()

        # Create the player now (player must exist before registering player collider)
        self.setup_player()

        # Now it's safe to set up camera and lights (player exists)
        self.setup_camera()
        self.setup_lights()

        # Create sound manager and menus before hooking events (so handlers can play sounds)
        self.sound = SoundManager()
        self.menu_manager = MenuManager(self)
        self.pause_menu = PauseMenu(self)
        self.exit_menu = ExitMenu(self)
        self.audio_menu = AudioMenu(self)

        # Load audio banks (do this after SoundManager exists)
        background_files = [f"Assets/sounds/background/background{i}.mp3" for i in range(1, 13)]
        self.sound.load_bank("background", background_files, loop=True, volume=0.4)

        bossfight_files = [f"Assets/sounds/bossfight/bossfight{i}.mp3" for i in range(1, 14)]
        self.sound.load_bank("bossfight", bossfight_files, loop=True, volume=0.7)

        self.sound.load_bank("menu_silence", ["Assets/sounds/silence.mp3"], loop=False, volume=0)
        self.sound.load_bank("menu_music", ["Assets/sounds/menu.mp3"], loop=True, volume=0.2)

        # Play background music (safe now)
        try:
            self.sound.play_random_from_bank("background")
        except Exception:
            print("[Sound] play_random_from_bank failed or not implemented in SoundManager")

        # -------------------------
        # Register colliders (player, statics, drones)
        # -------------------------
        print("\n=== COLLISION MANAGER START ===")
        print("Planets in list:", len(self.planets))
        print("Drones in list:", len(self.orbiting_drones))

        # Register player collider (player already created)
        self.collision_manager.register_player(self.player)

        # Register planets and station as static INTO targets
        for planet in self.planets:
            self.collision_manager.register_static(planet)

        # Station
        self.collision_manager.register_static(self.station)

        # Drones
        for drone in self.orbiting_drones:
            self.collision_manager.register_drone(drone)

        # Note: boost rings were registered during spawn_boost_ring calls in setup_planets,
        # but if you spawn rings later, call register_boost_ring for them as well.

        # Hook events and start traversal
        self.collision_manager.setup_events()
        self.taskMgr.add(self.collision_manager.update, "collisionEngineUpdate")

        # Missile interval cleanup task
        self.taskMgr.add(self.player.CheckIntervals, "checkMissiles", priority=34)

        # DRONE ORBIT UPDATE (single task for all drones)
        self.taskMgr.add(self.update_drone_orbits, "updateDroneOrbits")

        # MOVEMENT KEY BINDINGS (safe because player exists)
        self.accept("w", lambda: self.player.Thrust(1) if not self.ui_mode else None)
        self.accept("w-up", lambda: self.player.Thrust(0) if not self.ui_mode else None)

        self.accept("s", lambda: self.player.ReverseThrust(1) if not self.ui_mode else None)
        self.accept("s-up", lambda: self.player.ReverseThrust(0) if not self.ui_mode else None)

        self.accept("a", lambda: self.player.RollLeft(1) if not self.ui_mode else None)
        self.accept("a-up", lambda: self.player.RollLeft(0) if not self.ui_mode else None)

        self.accept("d", lambda: self.player.RollRight(1) if not self.ui_mode else None)
        self.accept("d-up", lambda: self.player.RollRight(0) if not self.ui_mode else None)

        self.accept("space", lambda: self.player.MoveUp(1) if not self.ui_mode else None)
        self.accept("space-up", lambda: self.player.MoveUp(0) if not self.ui_mode else None)

        self.accept("shift", lambda: self.player.MoveDown(1) if not self.ui_mode else None)
        self.accept("shift-up", lambda: self.player.MoveDown(0) if not self.ui_mode else None)

        self.accept("q", lambda: self.player.LeftTurn(1) if not self.ui_mode else None)
        self.accept("q-up", lambda: self.player.LeftTurn(0) if not self.ui_mode else None)

        self.accept("e", lambda: self.player.RightTurn(1) if not self.ui_mode else None)
        self.accept("e-up", lambda: self.player.RightTurn(0) if not self.ui_mode else None)

        self.accept("mouse1", lambda: self.player.Fire() if not self.ui_mode else None)

        self.accept("escape", lambda: self.menu_manager.open(self.exit_menu))

        # Load any remaining runtime state or UI here if needed
        print("[SpaceJam] Initialization complete.")

    def setup_camera(self):
        """
        Attach the camera to the player's model if available.
        If the player isn't present yet, parent to render and schedule a one-time reparent.
        """
        self.disableMouse()

        # If player exists, parent camera to player's model immediately
        if hasattr(self, "player") and self.player is not None:
            try:
                self.camera.reparentTo(self.player.model)
                self.camera.setFluidPos(0, -40, 10)
                self.camera.setHpr(0, -10, 0)
                print("[Camera] Parent set to player.model")
            except Exception as e:
                # Defensive fallback: attach to render
                print(f"[Camera] Failed to parent to player.model: {e}; attaching to render instead.")
                self.camera.reparentTo(self.render)
                self.camera.setPos(0, -40, 10)
                self.camera.setHpr(0, -10, 0)
        else:
            # Parent to render for now and schedule a reparent when player is created
            self.camera.reparentTo(self.render)
            self.camera.setPos(0, -40, 10)
            self.camera.setHpr(0, -10, 0)
            print("[Camera] Player not present yet — camera attached to render temporarily.")

            # schedule a one-time task to reparent when player appears
            def _attach_camera_when_ready(task):
                if hasattr(self, "player") and self.player is not None:
                    try:
                        self.camera.reparentTo(self.player.model)
                        self.camera.setFluidPos(0, -40, 10)
                        self.camera.setHpr(0, -10, 0)
                        print("[Camera] Reparented to player.model (deferred).")
                    except Exception as e:
                        print(f"[Camera] Deferred reparent failed: {e}")
                    return task.done
                return task.cont

            self.taskMgr.add(_attach_camera_when_ready, "attachCameraWhenPlayerReady")

    # -------------------------
    # Drone Ring Creator (optional helper)
    # -------------------------
    def create_drone_ring(self, center_pos, num_drones=6, radius=10):
        drones = []
        cx, cy, cz = center_pos

        for i in range(num_drones):
            angle = (2 * math.pi / num_drones) * i
            x = cx + radius * math.cos(angle)
            z = cz + radius * math.sin(angle)
            y = cy

            drone = DroneDefender(
                name=f"Drone_{i}",
                model_path="Assets/DroneDefender/DroneDefender.egg",
                scale=0.5,
                position=(x, y, z),
                orbit_radius=radius
            )

            # Basic orbit metadata
            drone.orbit_center = center_pos
            drone.orbit_angle = angle
            drone.orbit_speed = 0.5

            drones.append(drone)
            self.orbiting_drones.append(drone)
            self.drone_counter.register_drone()

        return drones

    # -------------------------
    # Space Station
    # -------------------------
    def setup_space_station(self):

        # Accurate multi‑box collider scaled ×3
        station_boxes = [
            {"center": (3, -2, -4), "size": (16, 15, 30)},     # central tower
            {"center": (0, 0, -5), "size": (28, 28, .5)},      # ring middle
            {"center": (-30, 30, -15), "size": (12, 12, 6)},   # ring left
        ]

        # Create the station with collider
        self.station = SpaceStation(
            name="MainStation",
            model_path="Assets/space station/spaceStation.egg",
            scale=3.0,
            position=(20, 10, 0),
            box_list=station_boxes
        )
        self.station.node.setHpr(0, 0, 0)

    # -------------------------
    # Boost Ring Spawner
    # -------------------------
    def spawn_boost_ring(self, position, scale=20):
        ring = BoostRing(
            name=f"BoostRing_{len(self.boost_rings)}",
            position=position,
            scale=scale
        )
        self.boost_rings.append(ring)
        # Register ring collider immediately with the collision manager
        self.collision_manager.register_boost_ring(ring)

    # -------------------------
    # Universe (Skybox)
    # -------------------------
    def setup_universe(self):
        # Create a large skybox/universe model parented to the camera so it always surrounds view
        try:
            self.universe = Universe(
                model_path="Assets/Universe/Universe.egg",
                scale=15000,
                position=(0, 0, 0)
            )
            print("[Universe] Skybox loaded.")
        except Exception as e:
            print(f"[Universe] Failed to load universe model: {e}")
            # Fallback: create a simple card or leave empty

    # -------------------------
    # Player (Spaceship)
    # -------------------------
    def setup_player(self):
        self.player = Player(
            name="PlayerShip",
            model_path="Assets/spaceships/Dumbledore.egg",
            scale=1.5,
            position=(0, -30, 0)
        )

    # -------------------------
    # Lighting
    # -------------------------
    def setup_lights(self):
        from panda3d.core import AmbientLight, DirectionalLight, Vec4

        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.2, 0.2, 0.25, 1))
        ambient_np = self.render.attachNewNode(ambient)
        self.render.setLight(ambient_np)

        dlight = DirectionalLight("dlight")
        dlight.setColor(Vec4(0.8, 0.8, 0.7, 1))
        dlight_np = self.render.attachNewNode(dlight)
        dlight_np.setHpr(45, -60, 0)
        self.render.setLight(dlight_np)

    # -------------------------
    # DRONE ORBIT UPDATE (single task for all drones)
    # -------------------------
    def update_drone_orbits(self, task):
        dt = ClockObject.getGlobalClock().getDt()
        player_pos = self.player.node.getPos(self.render)

        # PERFORMANCE MODE: skip some frames
        if PERFORMANCE_MODE and random.random() < 0.5:
            return task.cont

        # -------------------------
        # PLANET SPIN
        # -------------------------
        for planet in self.planets:
            planet.update_spin(dt, player_pos)

        # -------------------------
        # DRONE ACTIVATION
        # -------------------------
        for drone in self.orbiting_drones:
            dist = (drone.node.getPos(self.render) - player_pos).length()
            drone.active = dist < DRONE_ACTIVATION_DISTANCE

        # -------------------------
        # SWARM ACTIVATION
        # -------------------------
        for drone in self.orbiting_drones:
            if drone.active:
                for other in self.orbiting_drones:
                    if other is drone:
                        continue
                    if (other.node.getPos(self.render) - drone.node.getPos(self.render)).length() < DRONE_SWARM_RADIUS:
                        other.active = True

        # -------------------------
        # DRONE UPDATE (NEW SYSTEM)
        # -------------------------
        for drone in self.orbiting_drones:
            drone.update(dt, player_pos)

        return task.cont

    # -------------------------
    # Planets + Drone Patterns (kept for compatibility)
    # -------------------------
    def setup_planets(self):
        # This method is intentionally duplicated here to ensure the class is self-contained
        # and to preserve the original planet generation logic. If you maintain a single
        # implementation elsewhere, keep this in sync.
        print("\n=== SETUP PLANETS STARTED ===")

        planet_textures = [
            "planet-texture.png",
            "planet-texture1.png",
            "planet-texture2.png",
            "planet-texture3.png",
            "planet-texture4.png",
            "planet-texture5.png",
            "planet-texture6.png",
            "planet-texture7.png",
            "planet-texture8.png",
        ]

        placed_planets = []

        # Spacing and distance tuned by performance mode
        if PERFORMANCE_MODE:
            min_distance_factor = 10
            distance_min, distance_max = 5000, 14000
            y_min, y_max = -2000, 5000
        else:
            min_distance_factor = 15
            distance_min, distance_max = 4000, 12000
            y_min, y_max = -2000, 5000

        planet_positions = []

        for i, tex_name in enumerate(planet_textures):
            print(f"\n--- Generating planet {i+1} ---")

            for attempt in range(500):
                distance = random.uniform(distance_min, distance_max)
                angle = random.uniform(0, 2 * math.pi)
                y = random.uniform(y_min, y_max)
                z = random.uniform(-1000, 1000)
                x = distance * math.cos(angle)

                scale = random.uniform(200, 450)
                radius = scale / 2

                overlap = False
                for px, py, pz, pradius in placed_planets:
                    d = math.sqrt((x - px) ** 2 + (y - py) ** 2 + (z - pz) ** 2)
                    if d < min_distance_factor * (radius + pradius):
                        overlap = True
                        break

                if not overlap:
                    break

            print(f"Planet {i+1} position: ({x:.1f}, {y:.1f}, {z:.1f}) scale={scale:.1f}")

            planet = Planet(
                name=f"PLANET{i+1}",
                model_path="Assets/planets/protoPlanet.obj",
                scale=scale,
                position=(x, y, z),
                texture_path=os.path.join("Assets/planets", tex_name),
                enable_collisions=True,
            )

            print("Loaded planet model:", planet.model)

            placed_planets.append((x, y, z, radius))
            planet_positions.append((x, y, z, scale))
            self.planets.append(planet)

            print(f"Planet {i+1} appended. Total so far: {len(self.planets)}")

        print("\n=== PLANET GENERATION COMPLETE ===")
        print("Total planets created:", len(self.planets))

        # Apply unique random patterns to planets
        if PERFORMANCE_MODE:
            num_planets_to_decorate = 4
        else:
            num_planets_to_decorate = min(len(PATTERN_FUNCTIONS), random.randint(3, 6))

        chosen_planets = random.sample(planet_positions, num_planets_to_decorate)
        unique_patterns = random.sample(PATTERN_FUNCTIONS, num_planets_to_decorate)

        print(f"\nDecorating {num_planets_to_decorate} planets with patterns...")

        for (planet_data, pattern_func) in zip(chosen_planets, unique_patterns):
            px, py, pz, scale = planet_data
            print(f"Applying pattern {pattern_func.__name__} to planet at ({px:.1f}, {py:.1f}, {pz:.1f})")

            # Drone count tuned by performance mode
            drone_count = 8 if PERFORMANCE_MODE else random.randint(10, 25)

            drones = pattern_func(
                self,
                center_pos=(px, py, pz),
                num_drones=drone_count,
                radius=scale * 2
            )

            for drone in drones:
                drone.model.setScale(10.0)
                self.orbiting_drones.append(drone)
                self.drone_counter.register_drone()

        print("\n=== SETUP PLANETS FINISHED ===")
        print("Total drones spawned:", self.drone_counter.get_count())
        print(f"Decorated {num_planets_to_decorate} planets with random patterns.")
        # Spawn a couple of boost rings for testing/demo
        self.spawn_boost_ring((50, 20, 0), scale=25)
        self.spawn_boost_ring((500, 20, 0), scale=25)


app = SpaceJam()
app.run()
