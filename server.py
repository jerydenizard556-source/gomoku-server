<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MR JERY MOPION</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #111827;
    color: white;
    font-family: Arial, sans-serif;
    min-height: 100vh;
}

.app {
    width: 100%;
    max-width: 900px;
    margin: auto;
    padding: 20px 12px;
    text-align: center;
}

h1 {
    margin: 8px 0;
    font-size: 28px;
}

.screen {
    display: none;
}

.screen.active {
    display: block;
}

/* =========================
   MENU PRINCIPAL
========================= */

.main-menu {
    max-width: 380px;
    margin: 45px auto;
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.menu-button {
    width: 100%;
    padding: 16px;
    border: 1px solid #374151;
    border-radius: 10px;
    background: #273449;
    color: white;
    font-size: 18px;
    font-weight: bold;
    cursor: pointer;
}

.menu-button:hover {
    background: #374151;
}

.back-button,
.action-button {
    margin-top: 10px;
    padding: 11px 20px;
    border: 1px solid #4B5563;
    border-radius: 8px;
    background: #1F2937;
    color: white;
    font-size: 15px;
    cursor: pointer;
}

.action-button {
    margin: 5px;
    background: #273449;
}

/* =========================
   ONLINE
========================= */

.online-box {
    max-width: 350px;
    margin: 30px auto;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.online-box button,
.online-box input {
    width: 100%;
    padding: 13px;
    border-radius: 8px;
    font-size: 16px;
}

.online-box button {
    background: #273449;
    color: white;
    border: 1px solid #374151;
    cursor: pointer;
}

.online-box input {
    background: white;
    color: #111;
    border: 1px solid #555;
    text-align: center;
    text-transform: uppercase;
}

.room {
    color: #D4AF37;
    font-weight: bold;
    margin-top: 15px;
}

/* =========================
   INFORMATIONS
========================= */

.game-info {
    margin: 10px auto 12px;
    font-size: 16px;
}

.status {
    color: #D1D5DB;
    margin: 5px 0;
}

.error {
    color: #F87171;
    margin-top: 10px;
}

/* =========================
   TIMER 10 MINUTES
========================= */

.timers {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin: 10px auto 14px;
}

.player-timer {
    min-width: 125px;
    padding: 9px 14px;
    border: 1px solid #374151;
    border-radius: 9px;
    background: #1F2937;
    font-weight: bold;
    font-size: 16px;
}

.player-timer.active {
    border-color: #D4AF37;
    color: #D4AF37;
}

.player-timer.warning {
    color: #F87171;
    border-color: #F87171;
}

.timer-label {
    display: block;
    font-size: 12px;
    margin-bottom: 3px;
    color: #D1D5DB;
}

.timer-value {
    font-size: 21px;
}

/* =========================
   ACTIONS
========================= */

.game-actions {
    margin: 8px auto;
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 5px;
}

/* =========================
   TABLEAU
========================= */

.board-area {
    width: min(96vw, 760px);
    margin: 20px auto;
    display: grid;
    grid-template-columns: 30px 1fr;
    grid-template-rows: 30px 1fr;
    background: #D4AF37;
    border: 7px solid #8B6F1D;
    padding: 4px;
}

.letters {
    grid-column: 2;
    display: grid;
    grid-template-columns: repeat(20, 1fr);
    align-items: center;
    justify-items: center;
    font-size: 12px;
    font-weight: bold;
    color: #111;
}

.numbers {
    grid-row: 2;
    display: grid;
    grid-template-rows: repeat(20, 1fr);
    align-items: center;
    justify-items: center;
    font-size: 12px;
    font-weight: bold;
    color: #111;
}

.board {
    grid-column: 2;
    grid-row: 2;
    display: grid;
    grid-template-columns: repeat(20, minmax(0, 1fr));
    grid-template-rows: repeat(20, minmax(0, 1fr));
    width: 100%;
    aspect-ratio: 1 / 1;
    min-width: 0;
    min-height: 0;
    overflow: hidden;
}

.cell {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    min-width: 0;
    min-height: 0;
    cursor: pointer;
    overflow: hidden;
}

.cell::before {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    top: 50%;
    height: 1px;
    background: #5B4510;
}

.cell::after {
    content: "";
    position: absolute;
    top: 0;
    bottom: 0;
    left: 50%;
    width: 1px;
    background: #5B4510;
}

/* =========================
   PION
========================= */

.stone {
    width: 68%;
    height: 68%;
    flex: 0 0 68%;
    border-radius: 50%;
    position: relative;
    z-index: 5;
}

.black {
    background: #111111;
}

.red {
    background: #DC2626;
}

/* =========================
   VICTOIRE
========================= */

.win-title {
    font-size: 34px;
    margin-top: 60px;
}

.win-message {
    font-size: 21px;
    color: #D4AF37;
    font-weight: bold;
    margin: 25px 0;
}

.win-buttons {
    max-width: 380px;
    margin: 25px auto;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

/* =========================
   MOBILE
========================= */

@media (max-width: 500px) {

    .app {
        padding: 12px 6px;
    }

    h1 {
        font-size: 24px;
    }

    .main-menu {
        margin: 35px auto;
        padding: 0 10px;
    }

    .menu-button {
        font-size: 16px;
        padding: 15px;
    }

    .board-area {
        width: 98vw;
        grid-template-columns: 24px 1fr;
        grid-template-rows: 24px 1fr;
        border-width: 5px;
        padding: 3px;
    }

    .letters,
    .numbers {
        font-size: 9px;
    }

    .stone {
        width: 68%;
    }

    .action-button {
        font-size: 13px;
        padding: 9px 12px;
    }

    .player-timer {
        min-width: 115px;
        padding: 8px 10px;
    }

    .timer-value {
        font-size: 19px;
    }
}
</style>
</head>

<body>

<div class="app">

<!-- =========================
     MENU PRINCIPAL
========================= -->

<section id="homeScreen" class="screen active">

    <h1>MR JERY MOPION</h1>

    <div class="main-menu">

        <button class="menu-button" id="robotMode">
            🤖 Jouer avec Robot
        </button>

        <button class="menu-button" id="localMode">
            👥 2 Utilisateurs
        </button>

        <button class="menu-button" id="onlineMode">
            🌐 Jouer en Ligne
        </button>

    </div>

</section>

<!-- =========================
     ROBOT
========================= -->

<section id="robotScreen" class="screen">

    <h1>🤖 Jouer avec Robot</h1>

    <div class="game-info">

        <div id="robotStatus" class="status">
            À ton tour
        </div>

        <div class="timers">

            <div id="robotBlackTimer" class="player-timer active">
                <span class="timer-label">⚫ Noir</span>
                <span id="robotBlackTime" class="timer-value">10:00</span>
            </div>

            <div id="robotRedTimer" class="player-timer">
                <span class="timer-label">🔴 Robot</span>
                <span id="robotRedTime" class="timer-value">10:00</span>
            </div>

        </div>

    </div>

    <div id="robotBoard" class="board-area"></div>

    <div class="game-actions">

        <button class="action-button" id="robotUndo">
            ↩️ Annuler
        </button>

        <button class="action-button" id="robotRestart">
            🔄 Recommencer
        </button>

    </div>

    <button class="back-button" id="robotBack">
        ← Retour
    </button>

</section>

<!-- =========================
     2 UTILISATEURS
========================= -->

<section id="localScreen" class="screen">

    <h1>👥 2 Utilisateurs</h1>

    <div class="game-info">

        <div id="localStatus" class="status">
            Tour du joueur noir
        </div>

        <div class="timers">

            <div id="localBlackTimer" class="player-timer active">
                <span class="timer-label">⚫ Noir</span>
                <span id="localBlackTime" class="timer-value">10:00</span>
            </div>

            <div id="localRedTimer" class="player-timer">
                <span class="timer-label">🔴 Rouge</span>
                <span id="localRedTime" class="timer-value">10:00</span>
            </div>

        </div>

    </div>

    <div id="localBoard" class="board-area"></div>

    <div class="game-actions">

        <button class="action-button" id="localUndo">
            ↩️ Annuler
        </button>

        <button class="action-button" id="localRestart">
            🔄 Recommencer
        </button>

    </div>

    <button class="back-button" id="localBack">
        ← Retour
    </button>

</section>

<!-- =========================
     ONLINE MENU
========================= -->

<section id="onlineScreen" class="screen">

    <h1>🌐 Jouer en Ligne</h1>

    <div class="online-box">

        <button id="createBtn">
            Créer une partie
        </button>

        <input
            id="roomInput"
            type="text"
            maxlength="6"
            placeholder="CODE PARTIE"
        >

        <button id="joinBtn">
            Rejoindre
        </button>

    </div>

    <div class="room">

        Code :
        <span id="roomCode">---</span>

        <br>

        Joueur :
        <span id="playerNumber">---</span>

    </div>

    <div id="onlineError" class="error"></div>

    <button class="back-button" id="onlineBack">
        ← Retour
    </button>

</section>

<!-- =========================
     ONLINE GAME
========================= -->

<section id="onlineGameScreen" class="screen">

    <h1>🌐 Gomoku en Ligne</h1>

    <div class="game-info">

        <div id="onlineStatus" class="status">
            Connexion...
        </div>

        <div class="room">

            Code :
            <span id="gameRoomCode">---</span>

        </div>

    </div>

    <div id="onlineBoard" class="board-area"></div>

    <div id="gameOnlineError" class="error"></div>

    <button class="back-button" id="onlineGameBack">
        ← Retour
    </button>

</section>

<!-- =========================
     ÉCRAN VICTOIRE
========================= -->

<section id="winScreen" class="screen">

    <h1 class="win-title">
        🏆 Victoire !
    </h1>

    <div id="winMessage" class="win-message">
        Félicitations !
    </div>

    <div class="win-buttons">

        <button class="menu-button" id="newGameBtn">
            🔄 Nouvelle partie
        </button>

        <button class="back-button" id="winBack">
            ← Retour au menu
        </button>

    </div>

</section>

</div>

<script>

/* ==================================================
   SERVEUR
================================================== */

const SERVER_URL =
    "wss://gomoku-server-5h60.onrender.com";

/* ==================================================
   ÉCRANS
================================================== */

const screens =
    document.querySelectorAll(".screen");

function showScreen(id) {

    screens.forEach(function(screen) {
        screen.classList.remove("active");
    });

    document
        .getElementById(id)
        .classList.add("active");

    window.scrollTo(0, 0);
}

/* ==================================================
   TABLEAU
================================================== */

function createBoard(container, clickFunction) {

    container.innerHTML = "";

    const empty =
        document.createElement("div");

    container.appendChild(empty);

    const letters =
        document.createElement("div");

    letters.className = "letters";

    for (let i = 0; i < 20; i++) {

        const letter =
            document.createElement("span");

        letter.textContent =
            String.fromCharCode(65 + i);

        letters.appendChild(letter);
    }

    container.appendChild(letters);

    const numbers =
        document.createElement("div");

    numbers.className = "numbers";

    for (let i = 1; i <= 20; i++) {

        const number =
            document.createElement("span");

        number.textContent = i;

        numbers.appendChild(number);
    }

    container.appendChild(numbers);

    const board =
        document.createElement("div");

    board.className = "board";

    for (let row = 0; row < 20; row++) {

        for (let col = 0; col < 20; col++) {

            const cell =
                document.createElement("div");

            cell.className = "cell";

            cell.dataset.row = row;
            cell.dataset.col = col;

            cell.addEventListener(
                "click",
                function() {

                    clickFunction(
                        row,
                        col,
                        cell
                    );

                }
            );

            board.appendChild(cell);
        }
    }

    container.appendChild(board);
}

/* ==================================================
   DESSINER PION
================================================== */

function drawStone(cell, color) {

    cell.innerHTML = "";

    const stone =
        document.createElement("div");

    stone.className =
        "stone " + color;

    cell.appendChild(stone);
}

/* ==================================================
   TIMER
   10 MINUTES PAR JOUEUR
================================================== */

const START_TIME = 10 * 60;

let localBlackTime = START_TIME;
let localRedTime = START_TIME;

let robotBlackTime = START_TIME;
let robotRedTime = START_TIME;

let localTimerInterval = null;
let robotTimerInterval = null;

/* =========================
   FORMAT TIMER
========================= */

function formatTime(seconds) {

    const minutes =
        Math.floor(seconds / 60);

    const remainingSeconds =
        seconds % 60;

    return (
        String(minutes).padStart(2, "0") +
        ":" +
        String(remainingSeconds).padStart(2, "0")
    );
}

/* =========================
   AFFICHER TIMER LOCAL
========================= */

function updateLocalTimers() {

    document
        .getElementById("localBlackTime")
        .textContent =
        formatTime(localBlackTime);

    document
        .getElementById("localRedTime")
        .textContent =
        formatTime(localRedTime);

    const blackBox =
        document.getElementById(
            "localBlackTimer"
        );

    const redBox =
        document.getElementById(
            "localRedTimer"
        );

    blackBox.classList.toggle(
        "active",
        localTurn === "black" &&
        !localGameOver
    );

    redBox.classList.toggle(
        "active",
        localTurn === "red" &&
        !localGameOver
    );

    blackBox.classList.toggle(
        "warning",
        localBlackTime <= 60
    );

    redBox.classList.toggle(
        "warning",
        localRedTime <= 60
    );
}

/* =========================
   TIMER LOCAL
========================= */

function startLocalTimer() {

    stopLocalTimer();

    localTimerInterval =
        setInterval(function() {

            if (localGameOver) {
                return;
            }

            if (localTurn === "black") {

                localBlackTime--;

                if (localBlackTime <= 0) {

                    localBlackTime = 0;

                    updateLocalTimers();

                    localGameOver = true;

                    stopLocalTimer();

                    showWinScreen(
                        "🔴 Le joueur rouge gagne ! Le temps du joueur noir est écoulé."
                    );

                    return;
                }

            } else {

                localRedTime--;

                if (localRedTime <= 0) {

                    localRedTime = 0;

                    updateLocalTimers();

                    localGameOver = true;

                    stopLocalTimer();

                    showWinScreen(
                        "⚫ Le joueur noir gagne ! Le temps du joueur rouge est écoulé."
                    );

                    return;
                }
            }

            updateLocalTimers();

        }, 1000);

    updateLocalTimers();
}

function stopLocalTimer() {

    if (localTimerInterval) {

        clearInterval(
            localTimerInterval
        );

        localTimerInterval = null;
    }
}

/* =========================
   AFFICHER TIMER ROBOT
========================= */

function updateRobotTimers() {

    document
        .getElementById("robotBlackTime")
        .textContent =
        formatTime(robotBlackTime);

    document
        .getElementById("robotRedTime")
        .textContent =
        formatTime(robotRedTime);

    const blackBox =
        document.getElementById(
            "robotBlackTimer"
        );

    const redBox =
        document.getElementById(
            "robotRedTimer"
        );

    blackBox.classList.toggle(
        "active",
        robotTurn === "black" &&
        !robotGameOver
    );

    redBox.classList.toggle(
        "active",
        robotTurn === "red" &&
        !robotGameOver
    );

    blackBox.classList.toggle(
        "warning",
        robotBlackTime <= 60
    );

    redBox.classList.toggle(
        "warning",
        robotRedTime <= 60
    );
}

/* =========================
   TIMER ROBOT
========================= */

function startRobotTimer() {

    stopRobotTimer();

    robotTimerInterval =
        setInterval(function() {

            if (robotGameOver) {
                return;
            }

            if (robotTurn === "black") {

                robotBlackTime--;

                if (robotBlackTime <= 0) {

                    robotBlackTime = 0;

                    updateRobotTimers();

                    robotGameOver = true;

                    stopRobotTimer();

                    showWinScreen(
                        "🤖 Le robot gagne ! Ton temps est écoulé."
                    );

                    return;
                }

            } else {

                robotRedTime--;

                if (robotRedTime <= 0) {

                    robotRedTime = 0;

                    updateRobotTimers();

                    robotGameOver = true;

                    stopRobotTimer();

                    showWinScreen(
                        "⚫ Tu gagnes ! Le temps du robot est écoulé."
                    );

                    return;
                }
            }

            updateRobotTimers();

        }, 1000);

    updateRobotTimers();
}

function stopRobotTimer() {

    if (robotTimerInterval) {

        clearInterval(
            robotTimerInterval
        );

        robotTimerInterval = null;
    }
}

/* ==================================================
   STOP TOUS TIMER
================================================== */

function stopAllTimers() {

    stopLocalTimer();
    stopRobotTimer();
}

/* ==================================================
   VICTOIRE
================================================== */

function showWinScreen(message) {

    document
        .getElementById("winMessage")
        .textContent = message;

    stopAllTimers();

    showScreen("winScreen");
}

/* ==================================================
   MODE 2 UTILISATEURS
================================================== */

let localBoard = {};
let localTurn = "black";
let localGameOver = false;
let localHistory = [];

function resetLocalGame() {

    stopLocalTimer();

    localBoard = {};
    localTurn = "black";
    localGameOver = false;
    localHistory = [];

    localBlackTime = START_TIME;
    localRedTime = START_TIME;

    document
        .getElementById("localStatus")
        .textContent =
        "Tour du joueur noir";

    createBoard(
        document.getElementById("localBoard"),
        localClick
    );

    updateLocalTimers();

    startLocalTimer();
}

function localClick(row, col, cell) {

    if (localGameOver) {
        return;
    }

    const key =
        row + "," + col;

    if (localBoard[key]) {
        return;
    }

    localHistory.push({
        row: row,
        col: col,
        color: localTurn
    });

    localBoard[key] =
        localTurn;

    drawStone(
        cell,
        localTurn
    );

    if (
        checkWin(
            localBoard,
            row,
            col,
            localTurn
        )
    ) {

        localGameOver = true;

        showWinScreen(
            localTurn === "black"
                ? "⚫ Le joueur noir a gagné !"
                : "🔴 Le joueur rouge a gagné !"
        );

        return;
    }

    localTurn =
        localTurn === "black"
            ? "red"
            : "black";

    document
        .getElementById("localStatus")
        .textContent =
        localTurn === "black"
            ? "Tour du joueur noir"
            : "Tour du joueur rouge";

    updateLocalTimers();
}

/* ==================================================
   ANNULER LOCAL
================================================== */

function undoLocal() {

    if (localHistory.length === 0) {
        return;
    }

    const last =
        localHistory.pop();

    delete localBoard[
        last.row + "," + last.col
    ];

    localTurn =
        last.color;

    localGameOver = false;

    createBoard(
        document.getElementById("localBoard"),
        localClick
    );

    renderLocalBoard();

    document
        .getElementById("localStatus")
        .textContent =
        localTurn === "black"
            ? "Tour du joueur noir"
            : "Tour du joueur rouge";

    updateLocalTimers();

    startLocalTimer();
}

function renderLocalBoard() {

    const boardElement =
        document.querySelector(
            "#localBoard .board"
        );

    if (!boardElement) {
        return;
    }

    for (const key in localBoard) {

        const parts =
            key.split(",");

        const row =
            Number(parts[0]);

        const col =
            Number(parts[1]);

        const index =
            row * 20 + col;

        drawStone(
            boardElement.children[index],
            localBoard[key]
        );
    }
}

/* ==================================================
   MODE ROBOT
================================================== */

let robotBoard = {};
let robotTurn = "black";
let robotGameOver = false;
let robotHistory = [];

function resetRobotGame() {

    stopRobotTimer();

    robotBoard = {};
    robotTurn = "black";
    robotGameOver = false;
    robotHistory = [];

    robotBlackTime = START_TIME;
    robotRedTime = START_TIME;

    document
        .getElementById("robotStatus")
        .textContent =
        "À ton tour";

    createBoard(
        document.getElementById("robotBoard"),
        robotClick
    );

    updateRobotTimers();

    startRobotTimer();
}

function robotClick(row, col, cell) {

    if (robotGameOver) {
        return;
    }

    if (robotTurn !== "black") {
        return;
    }

    const key =
        row + "," + col;

    if (robotBoard[key]) {
        return;
    }

    robotHistory.push({
        row: row,
        col: col,
        color: "black"
    });

    robotBoard[key] =
        "black";

    drawStone(
        cell,
        "black"
    );

    if (
        checkWin(
            robotBoard,
            row,
            col,
            "black"
        )
    ) {

        robotGameOver = true;

        showWinScreen(
            "⚫ Tu as gagné !"
        );

        return;
    }

    robotTurn = "red";

    document
        .getElementById("robotStatus")
        .textContent =
        "🤖 Le robot réfléchit...";

    updateRobotTimers();

    setTimeout(
        robotMove,
        350
    );
}

/* ==================================================
   ROBOT
================================================== */

function robotMove() {

    if (robotGameOver) {
        return;
    }

    let bestMove =
        findBestRobotMove();

    if (!bestMove) {
        return;
    }

    const row =
        bestMove.row;

    const col =
        bestMove.col;

    const key =
        row + "," + col;

    robotHistory.push({
        row: row,
        col: col,
        color: "red"
    });

    robotBoard[key] =
        "red";

    const boardElement =
        document.querySelector(
            "#robotBoard .board"
        );

    const index =
        row * 20 + col;

    const cell =
        boardElement.children[index];

    drawStone(
        cell,
        "red"
    );

    if (
        checkWin(
            robotBoard,
            row,
            col,
            "red"
        )
    ) {

        robotGameOver = true;

        showWinScreen(
            "🤖 Le robot a gagné !"
        );

        return;
    }

    robotTurn = "black";

    document
        .getElementById("robotStatus")
        .textContent =
        "À ton tour";

    updateRobotTimers();
}

/* ==================================================
   MEILLEUR COUP ROBOT
================================================== */

function findBestRobotMove() {

    let winningMove =
        findWinningMove("red");

    if (winningMove) {
        return winningMove;
    }

    let blockingMove =
        findWinningMove("black");

    if (blockingMove) {
        return blockingMove;
    }

    let bestMove = null;
    let bestScore = -Infinity;

    for (let row = 0; row < 20; row++) {

        for (let col = 0; col < 20; col++) {

            const key =
                row + "," + col;

            if (robotBoard[key]) {
                continue;
            }

            let score =
                evaluatePosition(
                    row,
                    col,
                    "red"
                );

            if (
                score > bestScore
            ) {

                bestScore = score;

                bestMove = {
                    row: row,
                    col: col
                };
            }
        }
    }

    return bestMove;
}

function findWinningMove(color) {

    for (let row = 0; row < 20; row++) {

        for (let col = 0; col < 20; col++) {

            const key =
                row + "," + col;

            if (robotBoard[key]) {
                continue;
            }

            robotBoard[key] =
                color;

            const win =
                checkWin(
                    robotBoard,
                    row,
                    col,
                    color
                );

            delete robotBoard[key];

            if (win) {

                return {
                    row: row,
                    col: col
                };
            }
        }
    }

    return null;
}

function evaluatePosition(
    row,
    col,
    color
) {

    let score = 0;

    const center = 9.5;

    const distance =
        Math.abs(row - center) +
        Math.abs(col - center);

    score +=
        30 - distance;

    const directions = [
        [1, 0],
        [0, 1],
        [1, 1],
        [1, -1]
    ];

    for (
        const direction
        of directions
    ) {

        const dr =
            direction[0];

        const dc =
            direction[1];

        let count = 0;

        for (
            let step = 1;
            step <= 4;
            step++
        ) {

            const r =
                row + dr * step;

            const c =
                col + dc * step;

            if (
                r < 0 ||
                r >= 20 ||
                c < 0 ||
                c >= 20
            ) {
                break;
            }

            const key =
                r + "," + c;

            if (
                robotBoard[key] === color
            ) {

                count++;

            } else {

                break;
            }
        }

        score +=
            count * 20;
    }

    return score;
}

/* ==================================================
   ANNULER ROBOT
================================================== */

function undoRobot() {

    if (robotHistory.length === 0) {
        return;
    }

    const lastRobot =
        robotHistory.pop();

    delete robotBoard[
        lastRobot.row + "," +
        lastRobot.col
    ];

    if (robotHistory.length > 0) {

        const lastPlayer =
            robotHistory.pop();

        delete robotBoard[
            lastPlayer.row + "," +
            lastPlayer.col
        ];
    }

    robotTurn = "black";

    robotGameOver = false;

    createBoard(
        document.getElementById("robotBoard"),
        robotClick
    );

    renderRobotBoard();

    document
        .getElementById("robotStatus")
        .textContent =
        "À ton tour";

    updateRobotTimers();

    startRobotTimer();
}

function renderRobotBoard() {

    const boardElement =
        document.querySelector(
            "#robotBoard .board"
        );

    if (!boardElement) {
        return;
    }

    for (const key in robotBoard) {

        const parts =
            key.split(",");

        const row =
            Number(parts[0]);

        const col =
            Number(parts[1]);

        const index =
            row * 20 + col;

        drawStone(
            boardElement.children[index],
            robotBoard[key]
        );
    }
}

/* ==================================================
   VÉRIFIER 5 PIONS
================================================== */

function checkWin(
    board,
    row,
    col,
    color
) {

    const directions = [
        [1, 0],
        [0, 1],
        [1, 1],
        [1, -1]
    ];

    for (
        const direction
        of directions
    ) {

        const dr =
            direction[0];

        const dc =
            direction[1];

        let count = 1;

        count +=
            countDirection(
                board,
                row,
                col,
                dr,
                dc,
                color
            );

        count +=
            countDirection(
                board,
                row,
                col,
                -dr,
                -dc,
                color
            );

        if (count >= 5) {
            return true;
        }
    }

    return false;
}

function countDirection(
    board,
    row,
    col,
    dr,
    dc,
    color
) {

    let count = 0;

    let r =
        row + dr;

    let c =
        col + dc;

    while (
        r >= 0 &&
        r < 20 &&
        c >= 0 &&
        c < 20
    ) {

        const key =
            r + "," + c;

        if (
            board[key] !== color
        ) {
            break;
        }

        count++;

        r += dr;
        c += dc;
    }

    return count;
}

/* ==================================================
   MENU ROBOT
================================================== */

document
    .getElementById("robotMode")
    .addEventListener(
        "click",
        function() {

            resetRobotGame();

            showScreen(
                "robotScreen"
            );
        }
    );

/* ==================================================
   MENU LOCAL
================================================== */

document
    .getElementById("localMode")
    .addEventListener(
        "click",
        function() {

            resetLocalGame();

            showScreen(
                "localScreen"
            );
        }
    );

/* ==================================================
   MENU ONLINE
================================================== */

document
    .getElementById("onlineMode")
    .addEventListener(
        "click",
        function() {

            showScreen(
                "onlineScreen"
            );
        }
    );

/* ==================================================
   RESTART
================================================== */

document
    .getElementById("robotRestart")
    .addEventListener(
        "click",
        function() {

            resetRobotGame();

        }
    );

document
    .getElementById("localRestart")
    .addEventListener(
        "click",
        function() {

            resetLocalGame();

        }
    );

/* ==================================================
   UNDO
================================================== */

document
    .getElementById("robotUndo")
    .addEventListener(
        "click",
        function() {

            undoRobot();

        }
    );

document
    .getElementById("localUndo")
    .addEventListener(
        "click",
        function() {

            undoLocal();

        }
    );

/* ==================================================
   RETOUR
================================================== */

document
    .getElementById("robotBack")
    .addEventListener(
        "click",
        function() {

            stopAllTimers();

            showScreen(
                "homeScreen"
            );
        }
    );

document
    .getElementById("localBack")
    .addEventListener(
        "click",
        function() {

            stopAllTimers();

            showScreen(
                "homeScreen"
            );
        }
    );

document
    .getElementById("onlineBack")
    .addEventListener(
        "click",
        function() {

            if (socket) {
                socket.close();
            }

            showScreen(
                "homeScreen"
            );
        }
    );

document
    .getElementById("onlineGameBack")
    .addEventListener(
        "click",
        function() {

            if (socket) {
                socket.close();
            }

            showScreen(
                "homeScreen"
            );
        }
    );

/* ==================================================
   VICTOIRE — NOUVELLE PARTIE
================================================== */

document
    .getElementById("newGameBtn")
    .addEventListener(
        "click",
        function() {

            showScreen(
                "homeScreen"
            );
        }
    );

document
    .getElementById("winBack")
    .addEventListener(
        "click",
        function() {

            showScreen(
                "homeScreen"
            );
        }
    );

/* ==================================================
   ONLINE
================================================== */

let socket = null;
let onlinePlayer = null;
let onlineRoom = null;
let onlineBoardState = {};

function connectServer() {

    if (
        socket &&
        socket.readyState ===
        WebSocket.OPEN
    ) {
        return;
    }

    socket =
        new WebSocket(
            SERVER_URL
        );

    socket.onopen =
        function() {

            console.log(
                "Serveur connecté"
            );
        };

    socket.onclose =
        function() {

            document
                .getElementById(
                    "onlineStatus"
                )
                .textContent =
                "Serveur déconnecté";
        };

    socket.onerror =
        function() {

            document
                .getElementById(
                    "onlineError"
                )
                .textContent =
                "Erreur de connexion.";
        };

    socket.onmessage =
        function(event) {

            try {

                const data =
                    JSON.parse(
                        event.data
                    );

                if (
                    data.type ===
                    "created"
                ) {

                    onlineRoom =
                        data.room;

                    onlinePlayer =
                        data.player;

                    document
                        .getElementById(
                            "roomCode"
                        )
                        .textContent =
                        onlineRoom;

                    document
                        .getElementById(
                            "playerNumber"
                        )
                        .textContent =
                        onlinePlayer;

                    document
                        .getElementById(
                            "gameRoomCode"
                        )
                        .textContent =
                        onlineRoom;

                    showScreen(
                        "onlineGameScreen"
                    );

                    createBoard(
                        document.getElementById(
                            "onlineBoard"
                        ),
                        onlineClick
                    );

                    document
                        .getElementById(
                            "onlineStatus"
                        )
                        .textContent =
                        "En attente du joueur 2...";

                    return;
                }

                if (
                    data.type ===
                    "joined"
                ) {

                    onlineRoom =
                        data.room;

                    onlinePlayer =
                        data.player;

                    document
                        .getElementById(
                            "roomCode"
                        )
                        .textContent =
                        onlineRoom;

                    document
                        .getElementById(
                            "playerNumber"
                        )
                        .textContent =
                        onlinePlayer;

                    document
                        .getElementById(
                            "gameRoomCode"
                        )
                        .textContent =
                        onlineRoom;

                    showScreen(
                        "onlineGameScreen"
                    );

                    createBoard(
                        document.getElementById(
                            "onlineBoard"
                        ),
                        onlineClick
                    );

                    return;
                }

                if (
                    data.type ===
                    "state"
                ) {

                    onlineBoardState =
                        data.board || {};

                    renderOnlineState();

                    if (
                        data.players < 2
                    ) {

                        document
                            .getElementById(
                                "onlineStatus"
                            )
                            .textContent =
                            "En attente du deuxième joueur...";

                    } else {

                        const turn =
                            Object.keys(
                                onlineBoardState
                            ).length % 2 === 0
                                ? 1
                                : 2;

                        document
                            .getElementById(
                                "onlineStatus"
                            )
                            .textContent =
                            turn === onlinePlayer
                                ? "À ton tour"
                                : "Tour de l'autre joueur";
                    }

                    return;
                }

                if (
                    data.type ===
                    "error"
                ) {

                    document
                        .getElementById(
                            "onlineError"
                        )
                        .textContent =
                        data.message ||
                        "Erreur.";

                    document
                        .getElementById(
                            "gameOnlineError"
                        )
                        .textContent =
                        data.message ||
                        "Erreur.";
                }

            } catch(error) {

                console.error(error);
            }
        };
}

/* ==================================================
   AFFICHER ONLINE
================================================== */

function renderOnlineState() {

    const container =
        document.getElementById(
            "onlineBoard"
        );

    const boardElement =
        container.querySelector(
            ".board"
        );

    if (!boardElement) {
        return;
    }

    for (let row = 0; row < 20; row++) {

        for (let col = 0; col < 20; col++) {

            const index =
                row * 20 + col;

            const cell =
                boardElement.children[index];

            const key =
                row + "," + col;

            cell.innerHTML = "";

            if (
                onlineBoardState[key]
            ) {

                drawStone(
                    cell,
                    onlineBoardState[key]
                );
            }
        }
    }
}

/* ==================================================
   CLICK ONLINE
================================================== */

function onlineClick(
    row,
    col,
    cell
) {

    if (
        !socket ||
        socket.readyState !==
        WebSocket.OPEN
    ) {

        document
            .getElementById(
                "gameOnlineError"
            )
            .textContent =
            "Pas connecté au serveur.";

        return;
    }

    if (
        !onlineRoom ||
        !onlinePlayer
    ) {
        return;
    }

    const key =
        row + "," + col;

    if (
        onlineBoardState[key]
    ) {
        return;
    }

    socket.send(
        JSON.stringify({
            action: "move",
            row: row,
            col: col
        })
    );
}

/* ==================================================
   CRÉER PARTIE
================================================== */

document
    .getElementById("createBtn")
    .addEventListener(
        "click",
        function() {

            document
                .getElementById(
                    "onlineError"
                )
                .textContent = "";

            connectServer();

            setTimeout(
                function() {

                    if (
                        socket &&
                        socket.readyState ===
                        WebSocket.OPEN
                    ) {

                        socket.send(
                            JSON.stringify({
                                action: "create"
                            })
                        );
                    }

                },
                700
            );
        }
    );

/* ==================================================
   REJOINDRE
================================================== */

document
    .getElementById("joinBtn")
    .addEventListener(
        "click",
        function() {

            const code =
                document
                    .getElementById(
                        "roomInput"
                    )
                    .value
                    .trim()
                    .toUpperCase();

            if (
                code.length !== 6
            ) {

                document
                    .getElementById(
                        "onlineError"
                    )
                    .textContent =
                    "Le code doit contenir 6 caractères.";

                return;
            }

            document
                .getElementById(
                    "onlineError"
                )
                .textContent = "";

            connectServer();

            setTimeout(
                function() {

                    if (
                        socket &&
                        socket.readyState ===
                        WebSocket.OPEN
                    ) {

                        socket.send(
                            JSON.stringify({
                                action: "join",
                                room: code
                            })
                        );
                    }

                },
                700
            );
        }
    );

</script>

</body>
</html>
