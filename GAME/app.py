from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
import string
import time
import uuid

app = Flask(__name__)
app.config["SECRET_KEY"] = "number-clash-secret"
socketio = SocketIO(app, cors_allowed_origins="*")

rooms = {}


@app.route("/")
def home():
    return render_template("index.html")


def make_code():
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
        if code not in rooms:
            return code


def new_bot(number):
    bot_id = "BOT_" + uuid.uuid4().hex[:8]
    return {
        "id": bot_id,
        "name": f"CPU {number}",
        "type": "bot",
        "secret": None,
        "speed": float("inf")
    }


def get_room(code):
    return rooms.get(code.upper())


def get_player(room, player_id):
    return room["players"].get(player_id)


def add_history(room, entry):
    room["history"].insert(0, entry)


def public_player(room, player_id):
    player = get_player(room, player_id)
    if not player:
        return {"id": player_id, "name": "Unknown", "type": "unknown"}

    return {
        "id": player["id"],
        "name": player["name"],
        "type": player["type"]
    }


def send_state(room):
    for sid in list(room["humans"]):
        if sid not in room["players"]:
            continue

        my_match = None

        for match in room["matches"]:
            if sid in match["ids"] and not match["done"]:
                current_id = match["ids"][match["turn_index"]]

                targets = []
                if match["mode"] == "duel":
                    opponent_id = next(pid for pid in match["ids"] if pid != sid)
                    targets.append(public_player(room, opponent_id))
                else:
                    found = match["found"].get(sid, [])
                    for pid in match["ids"]:
                        if pid != sid and pid not in found:
                            targets.append(public_player(room, pid))

                my_match = {
                    "ids": match["ids"],
                    "mode": match["mode"],
                    "turn": match["turn"],
                    "action_count": match["action_count"],
                    "current_id": current_id,
                    "current_name": public_player(room, current_id)["name"],
                    "names": {
                        pid: public_player(room, pid)["name"]
                        for pid in match["ids"]
                    },
                    "targets": targets,
                    "found": match["found"].get(sid, []),
                    "can_guess": current_id == sid,
                }
                break

        match_summaries = []
        for match in room["matches"]:
            match_summaries.append({
                "mode": match["mode"],
                "players": [public_player(room, pid) for pid in match["ids"]],
                "done": match["done"],
                "winner": public_player(room, match["winner"]) if match.get("winner") else None,
                "bye": False
            })

        for pid in room.get("byes", []):
            match_summaries.append({
                "mode": "bye",
                "players": [public_player(room, pid)],
                "done": True,
                "winner": public_player(room, pid),
                "bye": True
            })

        state = {
            "my_id": sid,
            "room": room["code"],
            "is_host": sid == room["host_sid"],
            "stage": room["stage"],
            "round": room["round"],
            "message": room["message"],
            "players": [
                public_player(room, pid)
                for pid in room["players"]
            ],
            "active_players": [
                public_player(room, pid)
                for pid in room.get("active", [])
            ],
            "history": room["history"][:100],
            "matches": match_summaries,
            "my_match": my_match,
            "secret_set": (
                room["players"][sid]["secret"] is not None
                if sid in room["players"] else False
            ),
            "champion": (
                public_player(room, room["champion"])
                if room.get("champion") else None
            ),
            "winner_ids": room.get("winner_ids", []),
            "bots_count": room["bots_count"]
        }

        socketio.emit("game_state", state, to=sid)


def make_match(ids, mode="duel"):
    return {
        "ids": ids,
        "mode": mode,
        "turn_index": 0,
        "turn": 1,
        "action_count": 0,
        "done": False,
        "winner": None,
        "found": {pid: [] for pid in ids},
        "started_at": time.monotonic(),
        "bot_pending": False
    }


def prepare_round(room, competitors, first_round=False):
    room["round"] += 1
    room["stage"] = "choosing"
    room["matches"] = []
    room["byes"] = []
    room["round_finish_started"] = False
    room["winner_ids"] = []
    room["message"] = f"Round {room['round']}: choose your secret number!"

    competitors = list(competitors)

    if len(competitors) == 1:
        room["champion"] = competitors[0]
        room["stage"] = "finished"
        room["message"] = (
            f"{get_player(room, competitors[0])['name']} is the champion!"
        )
        add_history(room, {
            "round": room["round"],
            "text": room["message"],
            "kind": "winner"
        })
        send_state(room)
        return

    if len(competitors) == 3:
        room["matches"].append(make_match(competitors, "final3"))

    else:
        if len(competitors) % 2 == 1:
            if first_round:
                extra = new_bot(99)
                room["players"][extra["id"]] = extra
                competitors.append(extra["id"])
                room["message"] = (
                    "An extra CPU was added because the first round "
                    "had an odd number of players."
                )
            else:
                fastest = min(
                    competitors,
                    key=lambda pid: get_player(room, pid).get("speed", float("inf"))
                )
                competitors.remove(fastest)
                room["byes"].append(fastest)
                room["message"] = (
                    f"{get_player(room, fastest)['name']} gets a bye "
                    "for having the fastest previous-round win!"
                )

        random.shuffle(competitors)

        for i in range(0, len(competitors), 2):
            room["matches"].append(
                make_match(competitors[i:i + 2], "duel")
            )

    for pid in competitors + room["byes"]:
        player = get_player(room, pid)
        if player:
            player["secret"] = (
                random.randint(1, 100)
                if player["type"] == "bot" else None
            )

    add_history(room, {
        "round": room["round"],
        "text": f"Round {room['round']} has started.",
        "kind": "round"
    })

    send_state(room)


def begin_matches(room):
    room["stage"] = "playing"
    room["message"] = f"Round {room['round']} is underway!"
    for match in room["matches"]:
        match["started_at"] = time.monotonic()

    send_state(room)
    schedule_bots(room)


def schedule_bots(room):
    if room["stage"] != "playing":
        return

    for index, match in enumerate(room["matches"]):
        if match["done"] or match["bot_pending"]:
            continue

        current_id = match["ids"][match["turn_index"]]
        player = get_player(room, current_id)

        if player and player["type"] == "bot":
            match["bot_pending"] = True
            socketio.start_background_task(
                bot_turn, room["code"], index, current_id
            )


def finish_match(room, match, winner_id):
    if match["done"]:
        return

    match["done"] = True
    match["winner"] = winner_id

    elapsed = time.monotonic() - match["started_at"]
    get_player(room, winner_id)["speed"] = elapsed

    loser_names = [
        get_player(room, pid)["name"]
        for pid in match["ids"] if pid != winner_id
    ]

    winner_name = get_player(room, winner_id)["name"]
    message = f"{winner_name} wins against {', '.join(loser_names)}!"

    room["winner_ids"].append(winner_id)
    room["message"] = message

    add_history(room, {
        "round": room["round"],
        "text": message,
        "kind": "winner"
    })

    if all(m["done"] for m in room["matches"]):
        if not room["round_finish_started"]:
            room["round_finish_started"] = True
            socketio.start_background_task(advance_round, room["code"])

    send_state(room)


def advance_round(code):
    socketio.sleep(2)

    room = get_room(code)
    if not room or room["stage"] != "playing":
        return

    winners = list(room["winner_ids"]) + list(room["byes"])

    if len(winners) == 1:
        champion_id = winners[0]
        room["champion"] = champion_id
        room["stage"] = "finished"
        room["message"] = (
            f"{get_player(room, champion_id)['name']} is the NUMBER CLASH champion!"
        )
        add_history(room, {
            "round": room["round"],
            "text": room["message"],
            "kind": "winner"
        })
        send_state(room)
        return

    prepare_round(room, winners)


def bot_turn(code, match_index, bot_id):
    socketio.sleep(3)

    room = get_room(code)
    if not room or room["stage"] != "playing":
        return

    if match_index >= len(room["matches"]):
        return

    match = room["matches"][match_index]

    if match["done"]:
        return

    current_id = match["ids"][match["turn_index"]]
    if current_id != bot_id:
        match["bot_pending"] = False
        return

    bot = get_player(room, bot_id)
    if not bot:
        return

    if match["mode"] == "duel":
        target_id = next(pid for pid in match["ids"] if pid != bot_id)
        target = get_player(room, target_id)
        guess = random.randint(1, 100)
        feedback = (
            "Correct" if guess == target["secret"]
            else "Too low" if guess < target["secret"]
            else "Too high"
        )

        record_guess(room, match, bot_id, target_id, guess, feedback)

        if feedback == "Correct":
            finish_match(room, match, bot_id)
        else:
            next_turn(match)

    else:
        found = match["found"].setdefault(bot_id, [])
        for target_id in match["ids"]:
            if target_id == bot_id or target_id in found:
                continue

            target = get_player(room, target_id)
            guess = random.randint(1, 100)
            feedback = (
                "Correct" if guess == target["secret"]
                else "Too low" if guess < target["secret"]
                else "Too high"
            )

            record_guess(room, match, bot_id, target_id, guess, feedback)

            if feedback == "Correct":
                found.append(target_id)

        if len(found) == 2:
            finish_match(room, match, bot_id)
        else:
            next_turn(match)

    match["bot_pending"] = False
    send_state(room)
    schedule_bots(room)


def next_turn(match):
    match["action_count"] += 1
    match["turn_index"] = (match["turn_index"] + 1) % len(match["ids"])

    if match["turn_index"] == 0:
        match["turn"] += 1


def record_guess(room, match, player_id, target_id, guess, feedback):
    player_name = get_player(room, player_id)["name"]
    target_name = get_player(room, target_id)["name"]

    text = f"{player_name} guessed {guess} for {target_name}: {feedback}."

    add_history(room, {
        "round": room["round"],
        "turn": match["turn"],
        "text": text,
        "kind": feedback.lower().replace(" ", "-")
    })


@socketio.on("create_room")
def create_room(data):
    name = str(data.get("name", "Player")).strip()[:18] or "Player"
    bots = max(0, min(4, int(data.get("bots", 0))))

    code = make_code()
    sid = request.sid

    room = {
        "code": code,
        "host_sid": sid,
        "humans": [sid],
        "players": {
            sid: {
                "id": sid,
                "name": name,
                "type": "human",
                "secret": None,
                "speed": float("inf")
            }
        },
        "bots_count": bots,
        "stage": "lobby",
        "round": 0,
        "active": [],
        "matches": [],
        "byes": [],
        "history": [],
        "message": "Waiting for players...",
        "champion": None,
        "winner_ids": [],
        "round_finish_started": False
    }

    rooms[code] = room
    emit("room_created", {"code": code})
    send_state(room)


@socketio.on("join_room")
def join_room(data):
    code = str(data.get("code", "")).strip().upper()
    name = str(data.get("name", "Player")).strip()[:18] or "Player"
    room = get_room(code)

    if not room:
        emit("error_message", "Room not found.")
        return

    if room["stage"] != "lobby":
        emit("error_message", "This game has already started.")
        return

    if len(room["humans"]) >= 8:
        emit("error_message", "This room is full.")
        return

    sid = request.sid
    room["humans"].append(sid)
    room["players"][sid] = {
        "id": sid,
        "name": name,
        "type": "human",
        "secret": None,
        "speed": float("inf")
    }

    emit("joined_room", {"code": code})
    send_state(room)


@socketio.on("start_game")
def start_game():
    sid = request.sid
    room = next(
        (r for r in rooms.values() if r["host_sid"] == sid), None
    )

    if not room or room["stage"] != "lobby":
        emit("error_message", "You cannot start this game.")
        return

    competitors = list(room["humans"])

    for i in range(room["bots_count"]):
        bot = new_bot(i + 1)
        room["players"][bot["id"]] = bot
        competitors.append(bot["id"])

    if len(competitors) < 2:
        bot = new_bot(1)
        room["players"][bot["id"]] = bot
        competitors.append(bot["id"])

    room["active"] = competitors
    prepare_round(room, competitors, first_round=True)

    if all(
        get_player(room, pid)["secret"] is not None
        for pid in room["active"]
    ):
        begin_matches(room)


@socketio.on("set_secret")
def set_secret(data):
    sid = request.sid
    code = str(data.get("code", "")).upper()
    room = get_room(code)

    if not room or room["stage"] != "choosing":
        emit("error_message", "The game is not accepting secret numbers.")
        return

    try:
        number = int(data.get("number"))
    except (TypeError, ValueError):
        emit("error_message", "Enter a whole number.")
        return

    if not 1 <= number <= 100:
        emit("error_message", "Choose a number from 1 to 100.")
        return

    player = get_player(room, sid)
    if not player or player["type"] != "human":
        emit("error_message", "Player not found.")
        return

    if player["secret"] is not None:
        emit("error_message", "Your secret number is already locked in.")
        return

    player["secret"] = number

    add_history(room, {
        "round": room["round"],
        "text": f"{player['name']} locked in a secret number.",
        "kind": "secret"
    })

    humans_ready = all(
        room["players"][pid]["secret"] is not None
        for pid in room["humans"]
        if pid in room["active"]
    )

    if humans_ready:
        begin_matches(room)
    else:
        room["message"] = "Waiting for everyone to choose a secret number..."
        send_state(room)


@socketio.on("submit_guess")
def submit_guess(data):
    sid = request.sid
    code = str(data.get("code", "")).upper()
    room = get_room(code)

    if not room or room["stage"] != "playing":
        emit("error_message", "The game is not accepting guesses.")
        return

    match = next(
        (m for m in room["matches"] if sid in m["ids"] and not m["done"]),
        None
    )

    if not match:
        emit("error_message", "You are not in an active match.")
        return

    current_id = match["ids"][match["turn_index"]]
    if current_id != sid:
        emit("error_message", "It is not your turn.")
        return

    guesses = data.get("guesses", {})

    if match["mode"] == "duel":
        target_id = next(pid for pid in match["ids"] if pid != sid)

        try:
            guess = int(guesses.get(target_id))
        except (TypeError, ValueError):
            emit("error_message", "Enter a valid guess.")
            return

        if not 1 <= guess <= 100:
            emit("error_message", "Guesses must be from 1 to 100.")
            return

        secret = get_player(room, target_id)["secret"]
        feedback = (
            "Correct" if guess == secret
            else "Too low" if guess < secret
            else "Too high"
        )

        record_guess(room, match, sid, target_id, guess, feedback)

        if feedback == "Correct":
            finish_match(room, match, sid)
        else:
            next_turn(match)

    else:
        found = match["found"].setdefault(sid, [])
        targets = [
            pid for pid in match["ids"]
            if pid != sid and pid not in found
        ]

        for target_id in targets:
            try:
                guess = int(guesses.get(target_id))
            except (TypeError, ValueError):
                emit("error_message", "Enter a guess for every remaining opponent.")
                return

            if not 1 <= guess <= 100:
                emit("error_message", "Guesses must be from 1 to 100.")
                return

        for target_id in targets:
            guess = int(guesses[target_id])
            secret = get_player(room, target_id)["secret"]
            feedback = (
                "Correct" if guess == secret
                else "Too low" if guess < secret
                else "Too high"
            )

            record_guess(room, match, sid, target_id, guess, feedback)

            if feedback == "Correct":
                found.append(target_id)

        if len(found) == 2:
            finish_match(room, match, sid)
        else:
            next_turn(match)

    send_state(room)
    schedule_bots(room)


@socketio.on("disconnect")
def disconnect():
    sid = request.sid

    for room in rooms.values():
        if sid in room["humans"] and room["stage"] == "lobby":
            room["humans"].remove(sid)
            room["players"].pop(sid, None)
            send_state(room)
            break


if __name__ == "__main__":
    print("NUMBER CLASH is running at http://127.0.0.1:5000/")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
