import ctypes
import http.client
import json
import mmap
import os
import ssl
import time
from pathlib import Path

import keyboard


# ==============================
# STRUCTURES MÉMOIRE PARTAGÉE
# ==============================

class SPageFilePhysics(ctypes.Structure):
    _fields_ = [
        ("packetId", ctypes.c_int),
        ("gas",      ctypes.c_float),
        ("brake",    ctypes.c_float),
        ("fuel",     ctypes.c_float),
        ("gear",     ctypes.c_int),
        ("rpms",     ctypes.c_int),
        ("speedKmh", ctypes.c_float),
    ]

class SPageFileGraphics(ctypes.Structure):
    _fields_ = [
        ("packetId",    ctypes.c_int),
        ("status",      ctypes.c_int),
        ("session",     ctypes.c_int),
        ("currentTime", ctypes.c_wchar * 15),
        ("lastTime",    ctypes.c_wchar * 15),
        ("bestTime",    ctypes.c_wchar * 15),
    ]

class SPageFileStatic(ctypes.Structure):
    _fields_ = [
        ("smVersion",        ctypes.c_wchar * 15),
        ("acVersion",        ctypes.c_wchar * 15),
        ("numberOfSessions", ctypes.c_int),
        ("numCars",          ctypes.c_int),
        ("carModel",         ctypes.c_wchar * 33),
        ("track",            ctypes.c_wchar * 33),
        ("playerName",       ctypes.c_wchar * 33),
        ("playerSurname",    ctypes.c_wchar * 33),
    ]


# ==============================
# UTILITAIRES
# ==============================

def parse_time(t: str) -> int:
    """Convertit '1:23.456' en millisecondes. Retourne float('inf') si invalide."""
    try:
        minutes, rest = t.strip().split(":")
        seconds, ms = rest.split(".")
        return int(minutes) * 60000 + int(seconds) * 1000 + int(ms)
    except Exception:
        return float("inf")

def is_valid_time(t: str) -> bool:
    return t and t.strip() not in ("", "--:--.---")


# ==============================
# MÉMOIRE PARTAGÉE
# ==============================

def try_open_shared_memory():
    """Essaie d'ouvrir les 3 zones de mémoire partagée d'AC. Retourne None si AC n'est pas lancé."""
    try:
        pm = mmap.mmap(-1, ctypes.sizeof(SPageFilePhysics),  "acpmf_physics")
        gm = mmap.mmap(-1, ctypes.sizeof(SPageFileGraphics), "acpmf_graphics")
        sm = mmap.mmap(-1, ctypes.sizeof(SPageFileStatic),   "acpmf_static")
        return pm, gm, sm
    except Exception:
        return None

def close_mmaps(maps):
    for m in maps:
        try:
            m.close()
        except Exception:
            pass


# ==============================
# AFFICHAGE
# ==============================

def display_progress(user_data: dict, physics: SPageFilePhysics, graphics: SPageFileGraphics):
    print("\033c", end="")
    print(f"Pilote  : {user_data['pilote']  or 'N/A'}")
    print(f"Circuit : {user_data['circuit'] or 'N/A'}")
    print(f"Voiture : {user_data['voiture'] or 'N/A'}")
    print(f"Meilleur tour  : {user_data['best'] or '--:--.---'}")
    print(f"Tour pénalisé  : {user_data['bestWithPenalty'] or '--:--.---'}")
    print("─" * 35)
    print(f"Dernier tour   : {graphics.lastTime}")
    print(f"Meilleur (AC)  : {graphics.bestTime}")
    print("─" * 35)
    print(f"Vitesse : {physics.speedKmh:.1f} km/h")
    print(f"RPM     : {physics.rpms}")
    print(f"Rapport : {physics.gear - 1}")
    print(f"Gaz     : {physics.gas * 100:.0f}%")
    print(f"Frein   : {physics.brake * 100:.0f}%")
    print("=" * 35)
    print("[Q] pour quitter")


# ==============================
# MISE À JOUR DU BEST TIME
# ==============================

def update_best_time(user_data: dict, graphics: SPageFileGraphics):
    """
    Met à jour user_data['best'] et user_data['bestWithPenalty'] après chaque tour.
    - best          : meilleur temps sans pénalité (= aligné sur bestTime d'AC)
    - bestWithPenalty : dernier temps si supérieur au best (tour pénalisé ou lent)
    """
    last = graphics.lastTime
    best_ac = graphics.bestTime

    if not is_valid_time(last):
        return

    last_ms = parse_time(last)

    # Mise à jour du best : on se fie au bestTime d'AC (il n'inclut pas les tours pénalisés)
    if is_valid_time(best_ac):
        best_ac_ms = parse_time(best_ac)
        current_best_ms = parse_time(user_data['best']) if user_data['best'] else float("inf")
        if best_ac_ms < current_best_ms:
            user_data['best'] = best_ac

    # Détection de pénalité : last > bestTime d'AC => tour invalidé / pénalisé
    if is_valid_time(best_ac):
        if last_ms > parse_time(best_ac):
            user_data['bestWithPenalty'] = last


# ==============================
# ENVOI DES DONNÉES
# ==============================

def send_data(user_data: dict, config: dict):
    """Envoie les données au serveur configuré dans conf.json via X-API-KEY."""
    payload = {
        "username":        config.get("username", ""),
        "pilote":          user_data.get("pilote"),
        "circuit":         user_data.get("circuit"),
        "voiture":         user_data.get("voiture"),
        "best":            user_data.get("best"),
        "bestWithPenalty": user_data.get("bestWithPenalty"),
    }

    push = config.get("push")
    if not push:
        print("Erreur : configuration 'push' manquante dans conf.json.")
        _save_locally(user_data)
        return

    host     = push["host"]
    port     = push.get("port") or (443 if push.get("use_ssl") else 80)
    path     = push.get("path", "/")
    use_ssl  = bool(push.get("use_ssl"))
    api_key  = config.get("api_key")

    headers = {
        "Content-Type": "application/json",
        "Accept":        "application/json",
    }
    if api_key:
        headers["X-AC-API-KEY"] = api_key

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    context = None
    if use_ssl:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    conn = None
    try:
        if use_ssl:
            conn = http.client.HTTPSConnection(host, port=port, timeout=5, context=context)
        else:
            conn = http.client.HTTPConnection(host, port=port, timeout=5)

        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        resp_text = resp.read().decode(errors="ignore")
        conn.close()

        if resp.status == 200:
            print(f"Données envoyées avec succès !")
            if resp_text:
                print(f"Réponse serveur : {resp_text}")
        else:
            raise Exception(f"HTTP {resp.status} : {resp_text}")

    except Exception as e:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        print(f"Erreur lors de l'envoi : {e}")
        _save_locally(user_data)


def _save_locally(user_data: dict):
    """Sauvegarde les données en local si l'envoi échoue."""
    os.makedirs("./times", exist_ok=True)
    filename = f"./times/data_{int(time.time())}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=4)
    print(f"Données sauvegardées localement : {filename}")


# ==============================
# GESTION DU CLAVIER
# ==============================

quit_requested = False

def on_key(event):
    global quit_requested
    if event.name == "q":
        quit_requested = True


# ==============================
# BOUCLE PRINCIPALE
# ==============================

if __name__ == "__main__":
    INTERVAL = 0.25

    config_path = Path(__file__).resolve().parent / "conf.json"
    if not config_path.exists():
        print(f"Erreur : {config_path} introuvable !")
        exit(1)

    with config_path.open("r", encoding="utf-8") as f:
        conf = json.load(f)

    if conf.get("update_interval") is not None:
        INTERVAL = float(conf["update_interval"])
        print(f"Intervalle : {INTERVAL}s")

    keyboard.on_press(on_key)

    while not quit_requested:

        # --- Attente du lancement d'AC ---
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

        # --- Attente d'une session active (status == 2 = LIVE) ---
        print("En attente d'une session active...")
        while graphics.status != 2 and not quit_requested:
            print(".", end="", flush=True)
            time.sleep(2)

        if quit_requested:
            break

        print("\nSession détectée !")
        user_data = {
            "pilote":          "",
            "circuit":         "",
            "voiture":         "",
            "best":            None,
            "bestWithPenalty": None,
        }
        last_lap_time = graphics.lastTime  # pour détecter un nouveau tour

        # --- Boucle de session ---
        while graphics.status != 0 and not quit_requested:

            # Pause (status == 1 = REPLAY)
            if graphics.status == 1:
                print("\nSession en pause...")
                while graphics.status == 1 and not quit_requested:
                    time.sleep(1)
                print("Session reprise !")

            # Mise à jour des infos statiques
            user_data["pilote"]  = f"{static.playerName} {static.playerSurname}".strip()
            user_data["circuit"] = static.track.strip()
            user_data["voiture"] = static.carModel.strip()

            # Détection d'un nouveau tour terminé
            if graphics.lastTime != last_lap_time:
                last_lap_time = graphics.lastTime
                update_best_time(user_data, graphics)

            display_progress(user_data, physics, graphics)
            time.sleep(INTERVAL)

        # --- Fin de session ---
        print("\nSession terminée, envoi des données...")
        send_data(user_data, conf)

        close_mmaps(maps)
        maps = physics = graphics = static = None

        if not quit_requested:
            print("Retour en attente d'une nouvelle session...\n")
            time.sleep(3)

    print("Arrêt du programme.")