import http.client
import mmap
import ctypes
from pathlib import Path
import time
import os
import json

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

def display_progress(user_data, physics):
    print("\033c", end="")

    if user_data['best'] and graphics.lastTime != "--:--.---":
        if user_data['best'] > graphics.lastTime and graphics.lastTime > graphics.bestTime:
            user_data['best'] = graphics.lastTime
    
    last = graphics.lastTime
    best = graphics.bestTime
    if last and last != "--:--.---":
        last_ms = parse_time(last)
        best_ms = parse_time(best) if best and best != "--:--.---" else float("inf")
        # On determine si last > best, dans ce cas ca veut dire qu'il y a eu penalité donc data_user['penalty'] = True
        if last_ms > best_ms or last_ms != "--:--.---" and best_ms == float("inf"):
            print("Pénalité appliquée !")
            user_data['bestWithPenalty'] = last
            user_data['penalty'] = True

    print(f"Pilote  : {user_data['pilote']  or 'N/A'}")
    print(f"Circuit : {user_data['circuit'] or 'N/A'}")
    print(f"Voiture : {user_data['voiture'] or 'N/A'}")
    print(f"Meilleur tour : {user_data['best'] or '--:--.---'}")
    print(f"last brut : {graphics.lastTime}")
    print("─" * 35)
    print(f"Vitesse : {physics.speedKmh} km/h")
    print(f"RPM     : {physics.rpms}")
    print(f"Rapport : {physics.gear - 1 }")
    print(f"Gaz     : {physics.gas * 100:.0f}%")
    print("=" * 35)
    print("[Q] pour quitter")

def send_data(user_data, url):
    try:
        if url is None:
            print('Enregistement des données en local')
            raise Exception("URL du serveur non configurée.")
        host = url
        conn = http.client.HTTPConnection(host, 1000, timeout=5)
        conn.request("post", "/update", body=str(user_data).encode("utf-8"), headers={"Content-Type": "application/json"})
        status = conn.getresponse().status
        if status == 200:
            print("Données envoyées avec succès !")
        else:
            raise Exception(f"Erreur HTTP {status}")
    except Exception as e:
        print(f"Erreur lors de l'envoi des données : {e}")
        # auvegarde dans le fichier du script (data_csv[random_hash].txt) pour inserer a la main dans la base de données plus tard
        # on verifie si ./times existe, sinon on le crée
        # on creer ensuite le fichier data_csv[random_hash].txt avec les données user_data et physics
        if not os.path.exists("./times"):
            os.makedirs("./times")
        filename = f"./times/data_{int(time.time())}.json"
        print(f"Données enregistrées en locale : {filename}")
        print(user_data)
        with open(filename, "w") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=4)

def close_mmaps(maps):
    for m in maps:
        try:
            m.close()
        except Exception:
            pass

def parse_time(t):
    """Convertit '1:23.456' en millisecondes pour comparaison."""
    try:
        parts = t.strip().split(":")
        minutes = int(parts[0])
        sec_ms = parts[1].split(".")
        seconds = int(sec_ms[0])
        ms = int(sec_ms[1])
        return minutes * 60000 + seconds * 1000 + ms
    except Exception:
        return float("inf")

def on_key(event):
    global quit_requested
    if event.name == "q":
        quit_requested = True

quit_requested = False

if __name__ == "__main__":
    INTERVAL = 0.25
    config_path = Path(__file__).resolve().parent / "conf.json"
    with config_path.open("r", encoding="utf-8") as f:
        conf = json.load(f)
    url = conf.get("server_url", None)
    if conf.get("update_interval") is not None:
        INTERVAL = conf["update_interval"]
        print(f"Intervalle de mise à jour défini à {INTERVAL} secondes.")
    
    keyboard.on_press(on_key)
    
    while not quit_requested:

        #On attend le lancement d'Assetto Corsa en essayant d'ouvrir les mémoires partagées. Si elles n'existent pas, on attend et on réessaie.
        print("En attente du lancement d'Assetto Corsa...")
        maps = None
        while maps is None and not quit_requested:
            maps = try_open_shared_memory()
            if maps is None:
                print(".", end="", flush=True)
                time.sleep(2)

            if quit_requested:
                break
        
        print("\nAssetto Corsa détecté !")
        physics_map, graphics_map, static_map = maps
        physics  = SPageFilePhysics.from_buffer(physics_map)
        graphics = SPageFileGraphics.from_buffer(graphics_map)
        static   = SPageFileStatic.from_buffer(static_map)

        # On attend une session active (status == 2) pour commencer à afficher les données. Si la session se termine ou si l'utilisateur appuie sur "q", on arrête et on attend une nouvelle session.
        # status : 0 = OFF, 1 = REPLAY, 2 = LIVE
        print("En attente d'une session active...")
        while graphics.status != 2 and not quit_requested:
            print(".", end="", flush=True)
            time.sleep(2)
        
        if quit_requested:
            break


        # Une session est active, on affiche les données en temps réel. Si la session se termine ou si l'utilisateur appuie sur "q", on arrête et on attend une nouvelle session.
        print("\nSession détectée !")
        user_data = {
            "pilote": "",
            "circuit": "",
            "voiture": "",
            "best": None,
            "bestWithPenalty": None,
            "penalty": False,
        }
        
        while graphics.status != 0 and not quit_requested:
            # pause script when game is paused (status == 1)
            if graphics.status == 1:
                print("\nSession en pause...")
                while graphics.status == 1 and not quit_requested:
                    time.sleep(1)
                print("\nSession reprise !")
            user_data['pilote'] = f"{static.playerName}".strip()
            user_data['circuit'] = static.track.strip()
            user_data['voiture'] = static.carModel.strip()
           
            display_progress(user_data, physics)
            time.sleep(INTERVAL)
        
        print("\nSession terminée, envoi des données...")
        send_data(user_data, physics, url)

        close_mmaps(maps)
        maps = None
        physics = None
        graphics = None
        static = None

        if not quit_requested:
            print("\nSession terminée. Retour en attente...\n")
            time.sleep(3)
print("Arrêt du programme.")