import http
import mmap
import ctypes
import time

import keyboard

# ==============================
# STRUCTURES
# ==============================

class SPageFilePhysics(ctypes.Structure):
    _fields_ = [
        ("packetId",  ctypes.c_int),
        ("gas",       ctypes.c_float),
        ("brake",     ctypes.c_float),
        ("fuel",      ctypes.c_float),
        ("gear",      ctypes.c_int),
        ("rpms",      ctypes.c_int),
        ("speedKmh",  ctypes.c_float),
    ]

class SPageFileGraphics(ctypes.Structure):
    _fields_ = [
        ("packetId",      ctypes.c_int),
        ("status",        ctypes.c_int),
        ("session",       ctypes.c_int),
        ("currentTime",   ctypes.c_wchar * 15),
        ("lastTime",      ctypes.c_wchar * 15),
        ("bestTime",      ctypes.c_wchar * 15),
    ]

class SPageFileStatic(ctypes.Structure):
    _fields_ = [
        ("smVersion",     ctypes.c_wchar * 15),
        ("acVersion",     ctypes.c_wchar * 15),
        ("numberOfSessions", ctypes.c_int),
        ("numCars",       ctypes.c_int),
        ("carModel",      ctypes.c_wchar * 33),
        ("track",         ctypes.c_wchar * 33),
        ("playerName",    ctypes.c_wchar * 33),
        ("playerSurname", ctypes.c_wchar * 33),
    ]

# ==============================
# ATTENTE DU LANCEMENT D'AC
# ==============================

def try_open_shared_memory():
    try:
        pm = mmap.mmap(-1, ctypes.sizeof(SPageFilePhysics),  "acpmf_physics")
        gm = mmap.mmap(-1, ctypes.sizeof(SPageFileGraphics), "acpmf_graphics")
        sm = mmap.mmap(-1, ctypes.sizeof(SPageFileStatic),   "acpmf_static")
        return pm, gm, sm
    except Exception:
        return None

def display_progress():
    while graphics.status == 2:
        print("\033c", end="")

        print(f"Pilote  : {pilote  or 'N/A'}")
        print(f"Circuit : {circuit or 'N/A'}")
        print(f"Voiture : {voiture or 'N/A'}")
        print(f"Meilleur tour : {best or '--:--.---'}")
        print("─" * 35)
        print(f"Vitesse : {physics.speedKmh:.1f} km/h")
        print(f"RPM     : {physics.rpms}")
        print(f"Rapport : {physics.gear - 1 }")
        print(f"Gaz     : {physics.gas * 100:.0f}%")
        print("=" * 35)
        time.sleep(INTERVAL)
    

print("En attente du lancement d'Assetto Corsa...")

maps = None
while maps is None:
    maps = try_open_shared_memory()
    if maps is None:
        print(".", end="", flush=True)
        time.sleep(2)

print("\nAssetto Corsa détecté !")

physics_map, graphics_map, static_map = maps
physics  = SPageFilePhysics.from_buffer(physics_map)
graphics = SPageFileGraphics.from_buffer(graphics_map)
static   = SPageFileStatic.from_buffer(static_map)

# ==============================
# ATTENTE D'UNE SESSION ACTIVE
# ==============================

# status : 0 = OFF, 1 = REPLAY, 2 = LIVE
print("En attente d'une session active...")

while graphics.status != 2:
    print(".", end="", flush=True)
    time.sleep(2)

print("\nSession détectée !")

# ==============================
# BOUCLE PRINCIPALE
# ==============================

INTERVAL = 1
pilote  = f"{static.playerName} {static.playerSurname}".strip()
circuit = static.track
voiture = static.carModel
best    = graphics.bestTime

if __name__ == "__main__":
    



try:
    http.post("http://wwww.factomania.ddns.net:80/update", json={
        "pilote": pilote,
        "circuit": circuit,
        "voiture": voiture,
        "best": best,
        "speed": physics.speedKmh,
    })
except Exception as e:
    print(f"Erreur lors de l'envoi des données : {e}")

print("Arrêt du programme.")