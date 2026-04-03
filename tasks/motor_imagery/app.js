// ============================================================
// Motor Imagery Task – app.js
// State machine: REST (blink period) ↔ LEFT / RIGHT
// REST is the inter-trial interval — subjects blink here ONLY.
// Sends structured markers via QWebChannel bridge to Python/LSL
// ============================================================

const canvas = document.getElementById('testCanvas');
const ctx = canvas.getContext('2d');

// --- State machine -----------------------------------------------------------
// REST  : inter-trial interval — subject MUST blink here (countdown circle)
// LEFT  : imagine left-hand movement  (L fills up)
// RIGHT : imagine right-hand movement (R fills up)
let state = "REST";
let previousState = "None";
let cueSide = "";
let startTime = 0;
let rounds = 0;               // completed task trials so far
let totalTrials = 0;          // cycles × 2 (LEFT + RIGHT per cycle)
let numCycles = 5;            // configurable via welcome screen

const REST_DURATION = 4000;   // 4 s inter-trial rest / blink window
const TASK_DURATION = 4000;   // 4 s motor imagery window

// --- Mode parameter (LR or UD) ------------------------------------------------
const params = new URLSearchParams(window.location.search);
const MODE = (params.get("mode") || "LR").toUpperCase();
const DIRECTIONS = MODE === "FREE"
    ? []
    : MODE === "2D"
        ? ["LEFT", "RIGHT", "UP", "DOWN"]
        : MODE === "UD"
            ? ["UP", "DOWN"]
            : ["LEFT", "RIGHT"];

// Update instruction screen text for UD / 2D mode
if (MODE === "UD") {
    const dirEl = document.getElementById("guide-directions");
    if (dirEl) dirEl.innerHTML = '<span>STEP 3</span> <b>UP / DOWN:</b> Imagine the movement as the arrow appears. <b>Do NOT blink.</b>';
    const patEl = document.getElementById("guide-pattern");
    if (patEl) patEl.innerHTML = '<span>STEP 4</span> Pattern: <b>REST \u2192 UP or DOWN \u2192 REST \u2192 UP or DOWN \u2192 \u2026</b>';
} else if (MODE === "2D") {
    const dirEl = document.getElementById("guide-directions");
    if (dirEl) dirEl.innerHTML = '<span>STEP 3</span> <b>2D CURSOR:</b> Imagine movement toward the <b>highlighted target</b>. <b>Do NOT blink.</b>';
    const patEl = document.getElementById("guide-pattern");
    if (patEl) patEl.innerHTML = '<span>STEP 4</span> Pattern: <b>REST \u2192 L / R / U / D target \u2192 REST \u2192 \u2026</b> (4 per cycle)';
} else if (MODE === "FREE") {
    const dirEl = document.getElementById("guide-directions");
    if (dirEl) dirEl.innerHTML = '<span>STEP 3</span> <b>FREE CURSOR:</b> Control the cursor freely with your imagination. No cues will appear.';
    const patEl = document.getElementById("guide-pattern");
    if (patEl) patEl.innerHTML = '<span>STEP 4</span> Continuous free control -- move the cursor wherever you wish.';
}

// Each cycle contains one LEFT and one RIGHT in random order.
// taskQueue holds the flattened sequence of task trials only.
let taskQueue = [];
let taskIndex = 0;

// --- QWebChannel bridge (set once channel is ready) --------------------------
let pyBridge = null;

if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function (channel) {
        pyBridge = channel.objects.pyBridge;
        console.log("QWebChannel connected – pyBridge ready");
    });
} else {
    console.warn("QWebChannel not available – running without Python bridge");
}

// --- Marker helper -----------------------------------------------------------
function sendMarker(stopStage, startStage) {
    const marker = JSON.stringify({ stop: stopStage, start: startStage });
    console.log("Marker:", marker);
    if (pyBridge) {
        pyBridge.send_marker(marker);
    }
}

// --- Cursor position marker (FREE mode) --------------------------------------
function sendCursorPosition() {
    const marker = JSON.stringify({
        type: "cursor_pos",
        x: Math.round(cursorX * 10000) / 10000,
        y: Math.round(cursorY * 10000) / 10000
    });
    if (pyBridge) { pyBridge.send_marker(marker); }
}

// --- Ocean Wave Audio --------------------------------------------------------
let audioCtx, noiseNode, gainNode;

function playOceanWaves() {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const bufferSize = 2 * audioCtx.sampleRate;
    const noiseBuffer = audioCtx.createBuffer(1, bufferSize, audioCtx.sampleRate);
    const output = noiseBuffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) { output[i] = Math.random() * 2 - 1; }

    noiseNode = audioCtx.createBufferSource();
    noiseNode.buffer = noiseBuffer;
    noiseNode.loop = true;

    const filter = audioCtx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = 800;

    gainNode = audioCtx.createGain();
    noiseNode.connect(filter);
    filter.connect(gainNode);
    gainNode.connect(audioCtx.destination);

    noiseNode.start();
    simulateTides();
}

function simulateTides() {
    if (!audioCtx || audioCtx.state === 'closed') return;
    const now = audioCtx.currentTime;
    gainNode.gain.cancelScheduledValues(now);
    gainNode.gain.setValueAtTime(0.01, now);
    gainNode.gain.exponentialRampToValueAtTime(0.08, now + 2.5);
    gainNode.gain.exponentialRampToValueAtTime(0.01, now + 5);
    setTimeout(simulateTides, 5000);
}

function stopAudio() {
    if (noiseNode) { noiseNode.stop(); audioCtx.close(); }
}

// --- Welcome / substance UI helpers ------------------------------------------
function toggleDetails(checkbox) {
    const container = document.getElementById('substance-details-container');
    const id = `details-${checkbox.value}`;
    if (checkbox.checked) { createSubstanceBox(checkbox.value, container, id); }
    else { const div = document.getElementById(id); if (div) div.remove(); }
}

function addOtherSubstance() {
    const container = document.getElementById('substance-details-container');
    const uniqueId = 'other-' + Date.now();
    createSubstanceBox('Other', container, uniqueId, true);
}

function createSubstanceBox(title, container, id, isOther = false) {
    const div = document.createElement('div');
    div.id = id;
    div.className = 'detail-box';
    div.innerHTML = `
        <h4 style="margin:0 0 8px 0; color:var(--accent); font-size:0.7rem;">${title}</h4>
        ${isOther ? '<input type="text" placeholder="Name" style="margin-bottom:8px; font-size:0.7rem;">' : ''}
        <select style="margin-bottom:5px; font-size:0.7rem;"><option>Under 1 yr</option><option>1+ year</option><option>Over 3 years</option></select>
        <select style="margin-bottom:5px; font-size:0.7rem;"><option>Daily</option><option>Weekly</option><option>Monthly</option></select>
        <select style="font-size:0.7rem;"><option>Low</option><option>Moderate</option><option>High</option></select>
    `;
    container.appendChild(div);
}

// --- Screen navigation -------------------------------------------------------
function showInstructions() {
    if (!document.getElementById('subName').value) return alert("Subject ID Required");
    if (!document.getElementById('saveDir').value) return alert("Save Location Required");
    document.getElementById('welcome-screen').style.display = 'none';
    document.getElementById('instruction-screen').style.display = 'block';
}

/** Called by Python after the user picks a folder via the native dialog. */
function setSaveDir(path) {
    document.getElementById('saveDir').value = path;
}

/** Ask Python to open a native folder picker, result comes back via setSaveDir(). */
function pickSaveDir() {
    if (pyBridge) {
        pyBridge.pick_save_dir();
    } else {
        alert("Bridge not ready – type the path manually.");
    }
}

function startMindfulness() {
    if (MODE === "FREE") { startFree(); return; }
    document.getElementById('instruction-screen').style.display = 'none';
    document.getElementById('mindfulness-screen').style.display = 'flex';
    sendMarker("None", "MINDFULNESS");
    playOceanWaves();
    const circle = document.getElementById('mindfulness-circle');
    const circumference = 2 * Math.PI * 100;
    circle.style.strokeDasharray = `${circumference} ${circumference}`;

    let timeLeft = 60;
    const interval = setInterval(() => {
        timeLeft--;
        document.getElementById('mindfulness-timer').innerText = timeLeft;
        circle.style.strokeDashoffset = circumference - (timeLeft / 60) * circumference;
        if (timeLeft <= 0) {
            clearInterval(interval);
            sendMarker("MINDFULNESS", "REST");
            stopAudio();
            startTest();
        }
    }, 1000);
}

// --- Task helpers ------------------------------------------------------------

/** Shuffle an array in place (Fisher-Yates). */
function shuffle(arr) {
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
}

/**
 * Build the full task queue: `numCycles` cycles, each containing
 * ["LEFT", "RIGHT"] in a random order.
 * REST periods are handled automatically by the state machine — they are
 * NOT in the task queue.
 */
function buildTaskQueue(cycles) {
    const queue = [];
    for (let c = 0; c < cycles; c++) {
        const cycle = [...DIRECTIONS];
        shuffle(cycle);
        queue.push(...cycle);
    }
    return queue;
}

function currentDuration() {
    return state === "REST" ? REST_DURATION : TASK_DURATION;
}

// --- Test start (recording begins here) --------------------------------------
function startTest() {
    document.getElementById('mindfulness-screen').style.display = 'none';
    canvas.style.display = 'block';
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    // Auto-start LSL streams via bridge with the patient ID and save location
    const patientId = document.getElementById('subName').value || "UNKNOWN";
    const saveDir   = document.getElementById('saveDir').value || "";
    if (pyBridge) {
        pyBridge.start_streams(patientId, saveDir);
    }

    // Read cycle count from form (clamp to >= 1)
    numCycles = Math.max(1, parseInt(document.getElementById('numCycles').value, 10) || 5);
    taskQueue = buildTaskQueue(numCycles);
    taskIndex = 0;
    totalTrials = taskQueue.length;  // cycles × 2

    // Reset state — always start with a REST period
    rounds = 0;
    previousState = "None";
    state = "REST";
    cueSide = "";

    // Delay task start slightly so Python has time to finish initialising
    // the XDF recorder and LSL outlets before the first marker arrives.
    setTimeout(() => {
        startTime = Date.now();
        sendMarker("None", "REST");

        document.fonts.ready.then(() => {
            requestAnimationFrame(update);
        });
    }, 200);
}

// --- Main loop ---------------------------------------------------------------
function update() {
    if (canvas.style.display === 'none') return;

    const elapsed = Date.now() - startTime;
    const dur = currentDuration();

    if (elapsed >= dur) {
        // --- Transition ---
        if (state === "REST") {
            // REST → next task in the queue
            const nextTask = taskQueue[taskIndex];
            taskIndex++;
            previousState = state;
            state = nextTask;
            cueSide = nextTask;
            // Reset cursor to center at start of each cue (2D mode)
            if (MODE === "2D") { cursorX = 0.5; cursorY = 0.5; }
            sendMarker("REST", nextTask);
        } else {
            // task → REST (or end session)
            rounds++;
            if (rounds >= totalTrials) {
                sendMarker(state, "None");
                if (pyBridge) { pyBridge.stop_streams(); }
                return endSession();
            }
            previousState = state;
            sendMarker(state, "REST");
            state = "REST";
            cueSide = "";
        }
        startTime = Date.now();
    }

    draw();
    requestAnimationFrame(update);
}

// --- Drawing -----------------------------------------------------------------
function drawProgressiveLetter(x, y, char, isActive, color, progress) {
    ctx.save();
    ctx.translate(x, y);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = "700 140px 'Space Grotesk'";
    ctx.fillStyle = "#111";
    ctx.fillText(char, 0, 0);

    if (isActive) {
        ctx.save();
        ctx.beginPath();
        const fillY = 70 - (140 * progress);
        ctx.rect(-70, fillY, 140, 140);
        ctx.clip();
        ctx.fillStyle = color;
        ctx.shadowBlur = 20;
        ctx.shadowColor = color;
        ctx.fillText(char, 0, 0);
        ctx.restore();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeText(char, 0, 0);
    }
    ctx.restore();
}

// --- 2D cursor state (only active in 2D mode) --------------------------------
let cursorX = 0.5;  // normalized [0, 1], 0.5 = center
let cursorY = 0.5;
const CURSOR_RADIUS = 12;
const CURSOR_SPEED = 0.008;  // per-frame movement scale for tf values
const TARGET_SIZE = 60;      // target square side length in px

const TARGET_COLORS = {
    LEFT:  "#00f2ff",
    RIGHT: "#7000ff",
    UP:    "#00ff88",
    DOWN:  "#ff4444"
};

function drawTargets(cx, cy, activeDirection) {
    const w = canvas.width;
    const h = canvas.height;
    const half = TARGET_SIZE / 2;

    const positions = {
        LEFT:  { x: half + 10,          y: cy },
        RIGHT: { x: w - half - 10,      y: cy },
        UP:    { x: cx,                  y: half + 10 },
        DOWN:  { x: cx,                  y: h - half - 10 }
    };

    for (const dir of ["LEFT", "RIGHT", "UP", "DOWN"]) {
        const pos = positions[dir];
        const color = TARGET_COLORS[dir];
        const isActive = (dir === activeDirection);

        ctx.save();
        ctx.globalAlpha = isActive ? 1.0 : 0.3;
        if (isActive) {
            ctx.shadowBlur = 25;
            ctx.shadowColor = color;
        }
        ctx.fillStyle = color;
        ctx.fillRect(pos.x - half, pos.y - half, TARGET_SIZE, TARGET_SIZE);
        ctx.restore();
    }
}

function drawCursor() {
    const px = cursorX * canvas.width;
    const py = cursorY * canvas.height;

    ctx.save();
    ctx.beginPath();
    ctx.arc(px, py, CURSOR_RADIUS, 0, Math.PI * 2);
    ctx.fillStyle = "#ffffff";
    ctx.shadowBlur = 15;
    ctx.shadowColor = "rgba(255, 255, 255, 0.6)";
    ctx.fill();
    ctx.restore();
}

function updateCursorPosition() {
    const signals = window._lastControlSignals;
    if (!signals || !signals.baseline_ready) return;

    const tfLr = signals.tf_lr || 0;
    const tfUd = signals.tf_ud || 0;

    cursorX += tfLr * CURSOR_SPEED;  // positive = rightward
    cursorY -= tfUd * CURSOR_SPEED;  // positive = upward (canvas Y inverted)

    // Clamp to [0.05, 0.95] so cursor stays within target area
    cursorX = Math.max(0.05, Math.min(0.95, cursorX));
    cursorY = Math.max(0.05, Math.min(0.95, cursorY));
}

// --- Arrow cue rendering -----------------------------------------------------
const ARROW_COLORS = {
    LEFT:  "#00f2ff",
    RIGHT: "#7000ff",
    UP:    "#00f2ff",
    DOWN:  "#7000ff"
};

const ARROW_ROTATIONS = {
    RIGHT: 0,
    LEFT:  Math.PI,
    UP:    -Math.PI / 2,
    DOWN:  Math.PI / 2
};

function drawArrow(cx, cy, direction, color) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(ARROW_ROTATIONS[direction] || 0);

    // Arrow pointing right by default: triangle tip at +80, shaft from -60
    ctx.beginPath();
    ctx.moveTo(80, 0);       // tip
    ctx.lineTo(20, -40);     // upper wing
    ctx.lineTo(20, -15);     // inner upper
    ctx.lineTo(-60, -15);    // shaft upper
    ctx.lineTo(-60, 15);     // shaft lower
    ctx.lineTo(20, 15);      // inner lower
    ctx.lineTo(20, 40);      // lower wing
    ctx.closePath();

    ctx.shadowBlur = 20;
    ctx.shadowColor = color;
    ctx.fillStyle = color;
    ctx.fill();
    ctx.restore();
}

function draw() {
    ctx.fillStyle = "#050505";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const cx = canvas.width / 2;
    const cy = canvas.height / 2;
    const progress = Math.min((Date.now() - startTime) / currentDuration(), 1);

    // ---- Crosshair (always visible) ----
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx - 20, cy); ctx.lineTo(cx + 20, cy);
    ctx.moveTo(cx, cy - 20); ctx.lineTo(cx, cy + 20);
    ctx.stroke();

    // ---- REST state: countdown circle draining around crosshair ----
    if (state === "REST") {
        ctx.beginPath();
        ctx.arc(cx, cy, 35, -Math.PI / 2, (-Math.PI / 2) + (Math.PI * 2 * (1 - progress)));
        ctx.strokeStyle = "rgba(0, 242, 255, 0.4)";
        ctx.lineWidth = 3;
        ctx.stroke();
    }

    // ---- Arrow cue (1D modes only, not REST, not 2D) ----
    if (state !== "REST" && MODE !== "2D") {
        const arrowColor = ARROW_COLORS[state] || "#ffffff";
        drawArrow(cx, cy, state, arrowColor);
    }

    // ---- 2D mode: targets + cursor ----
    if (MODE === "2D") {
        drawTargets(cx, cy, state === "REST" ? null : state);
        updateCursorPosition();
        drawCursor();
    }

    // ---- Instruction text ----
    ctx.textAlign = "center";
    ctx.font = "700 22px 'Space Grotesk'";
    if (state === "REST") {
        ctx.fillStyle = "#00f2ff";
        ctx.fillText("BLINK NOW  /  CLEAR MIND", cx, cy - 180);
    } else if (MODE === "2D") {
        const dirColor = TARGET_COLORS[state] || "#ffffff";
        ctx.fillStyle = dirColor;
        ctx.fillText(`${state} -- DO NOT BLINK`, cx, cy - 180);
    } else if (state === "LEFT") {
        ctx.fillStyle = "#00f2ff";
        ctx.fillText("THINK LEFT MOVEMENT -- DO NOT BLINK", cx, cy - 180);
    } else if (state === "RIGHT") {
        ctx.fillStyle = "#7000ff";
        ctx.fillText("THINK RIGHT MOVEMENT -- DO NOT BLINK", cx, cy - 180);
    } else if (state === "UP") {
        ctx.fillStyle = "#00f2ff";
        ctx.fillText("THINK UPWARD MOVEMENT -- DO NOT BLINK", cx, cy - 180);
    } else if (state === "DOWN") {
        ctx.fillStyle = "#7000ff";
        ctx.fillText("THINK DOWNWARD MOVEMENT -- DO NOT BLINK", cx, cy - 180);
    }

    // ---- Trial counter ----
    ctx.fillStyle = "#222";
    ctx.font = "700 22px 'Space Grotesk'";
    ctx.textAlign = "center";
    const currentCycle = Math.floor(rounds / DIRECTIONS.length) + 1;
    ctx.fillText(`CYCLE ${currentCycle} / ${numCycles}  —  TRIAL ${rounds + 1} / ${totalTrials}`, cx, canvas.height - 50);
}

// --- FREE mode ---------------------------------------------------------------
function startFree() {
    document.getElementById('instruction-screen').style.display = 'none';
    canvas.style.display = 'block';
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const patientId = document.getElementById('subName').value || "UNKNOWN";
    const saveDir = document.getElementById('saveDir').value || "";
    if (pyBridge) { pyBridge.start_streams(patientId, saveDir); }

    cursorX = 0.5;
    cursorY = 0.5;

    // Escape key ends free cursor session
    document.addEventListener('keydown', function onEsc(e) {
        if (e.key === 'Escape') {
            document.removeEventListener('keydown', onEsc);
            sendMarker("FREE_CURSOR", "None");
            if (pyBridge) { pyBridge.stop_streams(); }
            endSession();
        }
    });

    // Small delay for XDF recorder initialization
    setTimeout(() => {
        sendMarker("None", "FREE_CURSOR");
        document.fonts.ready.then(() => {
            requestAnimationFrame(updateFree);
        });
    }, 200);
}

function updateFree() {
    if (canvas.style.display === 'none') return;
    updateCursorPosition();
    sendCursorPosition();
    drawFree();
    requestAnimationFrame(updateFree);
}

function drawFree() {
    ctx.fillStyle = "#050505";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const cx = canvas.width / 2;
    const cy = canvas.height / 2;

    // Crosshair at center
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx - 20, cy); ctx.lineTo(cx + 20, cy);
    ctx.moveTo(cx, cy - 20); ctx.lineTo(cx, cy + 20);
    ctx.stroke();

    // Cursor dot
    drawCursor();

    // Minimal status text
    ctx.textAlign = "center";
    ctx.font = "700 22px 'Space Grotesk'";
    ctx.fillStyle = "#333";
    ctx.fillText("FREE CURSOR MODE", cx, canvas.height - 50);
}

// --- Session end -------------------------------------------------------------
function endSession() {
    canvas.style.display = 'none';
    document.getElementById('closing-screen').style.display = 'block';
}

function resetToHome() { location.reload(); }

// --- Control signal receiver (called from Python via runJavaScript) ----------

/**
 * Receive control signal data from Python GUI.
 * Called every streaming chunk (~128ms) when C3/C4 are mapped.
 * @param {Object} data - {lr, ud, mu_c3, mu_c4, baseline_ready}
 */
function updateControlSignals(data) {
    // Store for use by task logic (Phase 4 transfer function will consume this)
    window._lastControlSignals = data;
}
