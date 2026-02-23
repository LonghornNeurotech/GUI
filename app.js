// ============================================================
// Motor Imagery Task – app.js
// State machine: BLINK → task (LEFT / RIGHT / REST) → BLINK …
// Sends structured markers via QWebChannel bridge to Python/LSL
// ============================================================

const canvas = document.getElementById('testCanvas');
const ctx = canvas.getContext('2d');

// --- State machine -----------------------------------------------------------
// BLINK  : inter-trial interval – subject may blink (countdown circle)
// LEFT   : imagine left-hand movement  (L fills up)
// RIGHT  : imagine right-hand movement (R fills up)
// REST   : relax, no movement imagery  (O fills up in center)
let state = "BLINK";
let previousState = "None";   // for marker bookkeeping
let cueSide = "";             // current task label when in a task state
let startTime = 0;
let rounds = 0;
const MAX_ROUNDS = 5;         // number of task trials
const BLINK_DURATION = 4000;  // 4 s blink window
const TASK_DURATION  = 4000;  // 4 s task window

// Pool of tasks to draw from (randomly shuffled each cycle)
const TASK_POOL = ["LEFT", "RIGHT", "REST"];

// --- QWebChannel bridge (set once channel is ready) --------------------------
let pyBridge = null;

// Initialise QWebChannel as soon as the page loads.
// When loaded outside QWebEngineView the channel simply won't exist and
// pyBridge stays null – all marker calls become no-ops, so the page still
// works standalone for development.
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
    document.getElementById('welcome-screen').style.display = 'none';
    document.getElementById('instruction-screen').style.display = 'block';
}

function startMindfulness() {
    document.getElementById('instruction-screen').style.display = 'none';
    document.getElementById('mindfulness-screen').style.display = 'flex';
    playOceanWaves();
    const circle = document.getElementById('mindfulness-circle');
    const circumference = 2 * Math.PI * 100;
    circle.style.strokeDasharray = `${circumference} ${circumference}`;

    let timeLeft = 60;
    const interval = setInterval(() => {
        timeLeft--;
        document.getElementById('mindfulness-timer').innerText = timeLeft;
        circle.style.strokeDashoffset = circumference - (timeLeft / 60) * circumference;
        if (timeLeft <= 0) { clearInterval(interval); stopAudio(); startTest(); }
    }, 1000);
}

// --- Task helpers ------------------------------------------------------------
function pickRandomTask() {
    return TASK_POOL[Math.floor(Math.random() * TASK_POOL.length)];
}

function currentDuration() {
    return state === "BLINK" ? BLINK_DURATION : TASK_DURATION;
}

// --- Test start (recording begins here) --------------------------------------
function startTest() {
    document.getElementById('mindfulness-screen').style.display = 'none';
    canvas.style.display = 'block';
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    // Auto-start LSL streams via bridge with the patient ID from the form
    const patientId = document.getElementById('subName').value || "UNKNOWN";
    if (pyBridge) {
        pyBridge.start_streams(patientId);
    }

    // Reset state
    rounds = 0;
    previousState = "None";
    state = "BLINK";
    cueSide = "";
    startTime = Date.now();

    // First marker: None → BLINK
    sendMarker("None", "BLINK");

    requestAnimationFrame(update);
}

// --- Main loop ---------------------------------------------------------------
function update() {
    if (canvas.style.display === 'none') return;

    const elapsed = Date.now() - startTime;
    const dur = currentDuration();

    if (elapsed >= dur) {
        // --- Transition ---
        if (state === "BLINK") {
            // Move from BLINK → a random task
            const nextTask = pickRandomTask();
            previousState = state;
            state = nextTask;
            cueSide = nextTask;
            sendMarker("BLINK", nextTask);
        } else {
            // Move from task → BLINK (or end session)
            rounds++;
            if (rounds >= MAX_ROUNDS) {
                sendMarker(state, "None");
                // Stop LSL streams
                if (pyBridge) { pyBridge.stop_streams(); }
                return endSession();
            }
            previousState = state;
            sendMarker(state, "BLINK");
            state = "BLINK";
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

function drawProgressiveCircle(cx, cy, radius, isActive, color, progress) {
    // Draws a circle target that fills from bottom to top (like the letters)
    ctx.save();

    // Dim outline always visible
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.strokeStyle = "#222";
    ctx.lineWidth = 3;
    ctx.stroke();

    if (isActive) {
        // Clip to a rect that grows upward
        ctx.save();
        ctx.beginPath();
        const fillY = cy + radius - (2 * radius * progress);
        ctx.rect(cx - radius - 2, fillY, (radius + 2) * 2, radius * 2 + 4);
        ctx.clip();

        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.shadowBlur = 25;
        ctx.shadowColor = color;
        ctx.fill();
        ctx.restore();

        // Bright outline
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth = 3;
        ctx.stroke();

        // "REST" label inside circle
        ctx.fillStyle = "#000";
        ctx.font = "700 28px 'Space Grotesk'";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("REST", cx, cy);
    } else {
        // Dim label
        ctx.fillStyle = "#222";
        ctx.font = "700 28px 'Space Grotesk'";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("REST", cx, cy);
    }

    ctx.restore();
}

function draw() {
    ctx.fillStyle = "#050505";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const cx = canvas.width / 2;
    const cy = canvas.height / 2;
    const progress = Math.min((Date.now() - startTime) / currentDuration(), 1);

    // ---- Crosshair (always visible) ----
    ctx.strokeStyle = "#333";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx - 20, cy); ctx.lineTo(cx + 20, cy);
    ctx.moveTo(cx, cy - 20); ctx.lineTo(cx, cy + 20);
    ctx.stroke();

    // ---- BLINK state: countdown circle in center ----
    if (state === "BLINK") {
        ctx.beginPath();
        ctx.arc(cx, cy, 35, -Math.PI / 2, (-Math.PI / 2) + (Math.PI * 2 * (1 - progress)));
        ctx.strokeStyle = "rgba(0, 242, 255, 0.4)";
        ctx.lineWidth = 3;
        ctx.stroke();
    }

    // ---- L / R / REST visuals (always drawn; active when state matches) ----
    drawProgressiveLetter(
        cx - 300, cy, "L",
        state === "LEFT", "#00f2ff", progress
    );
    drawProgressiveLetter(
        cx + 300, cy, "R",
        state === "RIGHT", "#7000ff", progress
    );
    drawProgressiveCircle(
        cx, cy + 200, 55,
        state === "REST", "#ffaa00", progress
    );

    // ---- Instruction text at top ----
    ctx.textAlign = "center";
    ctx.font = "700 22px 'Space Grotesk'";
    if (state === "BLINK") {
        ctx.fillStyle = "#00f2ff";
        ctx.fillText("BLINK NOW / CLEAR MIND", cx, cy - 180);
    } else if (state === "LEFT") {
        ctx.fillStyle = "#00f2ff";
        ctx.fillText("THINK LEFT MOVEMENT", cx, cy - 180);
    } else if (state === "RIGHT") {
        ctx.fillStyle = "#7000ff";
        ctx.fillText("THINK RIGHT MOVEMENT", cx, cy - 180);
    } else if (state === "REST") {
        ctx.fillStyle = "#ffaa00";
        ctx.fillText("RELAX — NO MOVEMENT", cx, cy - 180);
    }

    // ---- Round counter ----
    ctx.fillStyle = "#222";
    ctx.font = "700 22px 'Space Grotesk'";
    ctx.textAlign = "center";
    ctx.fillText(`ROUND ${rounds + 1} OF ${MAX_ROUNDS}`, cx, canvas.height - 50);
}

// --- Session end -------------------------------------------------------------
function endSession() {
    canvas.style.display = 'none';
    document.getElementById('closing-screen').style.display = 'block';
}

function resetToHome() { location.reload(); }