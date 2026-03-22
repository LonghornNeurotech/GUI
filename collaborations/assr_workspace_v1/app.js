// ============================================================
// Audio Cueing Task – app.js
// State machine: REST ↔ TASK (conditioned audio trials)
// Trial order: AM_37 -> AM_43 -> DICHOTIC (with focus cues)
// Sends structured markers via QWebChannel bridge to Python/LSL
// ============================================================

const canvas = document.getElementById('testCanvas');
const ctx = canvas.getContext('2d');

// --- State machine -----------------------------------------------------------
// REST : inter-trial interval
// TASK : active audio trial (AM_37, AM_43, or DICHOTIC)
let state = "REST";
let previousState = "None";
let startTime = 0;
let rounds = 0;               // completed task trials so far
let totalTrials = 0;          // trials per condition * 3 conditions
let numCycles = 5;            // interpreted as trials per condition
let activeTrial = null;
let focusCue = "NONE";
let completedByCondition = { AM_37: 0, AM_43: 0, DICHOTIC: 0 };
let eventSequence = 0;

const REST_DURATION = 4000;   // 4 s inter-trial rest / blink window
const TASK_DURATION = 4000;   // 4 s motor imagery window

// Queue holds all audio trials in deterministic block order:
// [AM_37 x N] -> [AM_43 x N] -> [DICHOTIC x N with shuffled focus cues]
let trialQueue = [];
let taskIndex = 0;
const CONDITION_ORDER = ["AM_37", "AM_43", "DICHOTIC"];

const AUDIO_FILES = {
    AM_37: "file:///Users/tarunramakrishnan/Downloads/left_1000Hz_37HzAM.wav",
    AM_43: "file:///Users/tarunramakrishnan/Downloads/right_1000Hz_43HzAM.wav",
    DICHOTIC: "file:///Users/tarunramakrishnan/Downloads/dichotic_1000Hz_37vs43HzAM.wav"
};

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

function emitStructuredMarker(eventName, extra = {}) {
    const payload = {
        event: eventName,
        sequence: eventSequence++,
        timestamp_unix_ms: Date.now(),
        phase: state,
        condition: activeTrial ? activeTrial.condition : "NONE",
        focus: focusCue,
        trial_index: rounds + (state === "TASK" ? 1 : 0),
        total_trials: totalTrials,
        stop: extra.stop ?? previousState,
        start: extra.start ?? state,
        ...extra
    };
    const marker = JSON.stringify(payload);
    console.log("Structured marker:", marker);
    if (pyBridge) {
        pyBridge.send_marker(marker);
    }
}

// --- Mindfulness Audio -------------------------------------------------------
let mindfulnessCtx, noiseNode, gainNode;

function playOceanWaves() {
    mindfulnessCtx = new (window.AudioContext || window.webkitAudioContext)();
    const bufferSize = 2 * mindfulnessCtx.sampleRate;
    const noiseBuffer = mindfulnessCtx.createBuffer(1, bufferSize, mindfulnessCtx.sampleRate);
    const output = noiseBuffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) { output[i] = Math.random() * 2 - 1; }

    noiseNode = mindfulnessCtx.createBufferSource();
    noiseNode.buffer = noiseBuffer;
    noiseNode.loop = true;

    const filter = mindfulnessCtx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = 800;

    gainNode = mindfulnessCtx.createGain();
    noiseNode.connect(filter);
    filter.connect(gainNode);
    gainNode.connect(mindfulnessCtx.destination);

    noiseNode.start();
    simulateTides();
}

function simulateTides() {
    if (!mindfulnessCtx || mindfulnessCtx.state === 'closed') return;
    const now = mindfulnessCtx.currentTime;
    gainNode.gain.cancelScheduledValues(now);
    gainNode.gain.setValueAtTime(0.01, now);
    gainNode.gain.exponentialRampToValueAtTime(0.08, now + 2.5);
    gainNode.gain.exponentialRampToValueAtTime(0.01, now + 5);
    setTimeout(simulateTides, 5000);
}

function stopAudio() {
    if (noiseNode) {
        noiseNode.stop();
        mindfulnessCtx.close();
    }
}

// --- Trial Audio -------------------------------------------------------------
let trialAudioCtx = null;
let trialMasterGain = null;
const trialAudioBuffers = {};
let activeTrialNodes = [];

async function ensureTrialAudioReady() {
    if (!trialAudioCtx) {
        trialAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        trialMasterGain = trialAudioCtx.createGain();
        trialMasterGain.gain.value = 0.16;
        trialMasterGain.connect(trialAudioCtx.destination);
    }
    if (trialAudioCtx.state === "suspended") {
        await trialAudioCtx.resume();
    }
    await preloadTrialBuffers();
}

async function preloadTrialBuffers() {
    for (const condition of CONDITION_ORDER) {
        if (trialAudioBuffers[condition]) continue;
        const url = AUDIO_FILES[condition];
        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const arr = await response.arrayBuffer();
            const decoded = await trialAudioCtx.decodeAudioData(arr);
            trialAudioBuffers[condition] = decoded;
            console.log(`Loaded audio buffer for ${condition} from ${url}`);
        } catch (err) {
            trialAudioBuffers[condition] = null;
            console.warn(`Falling back to synthesized audio for ${condition}:`, err);
        }
    }
}

function createSynthAmTone(modHz, panValue = 0) {
    const carrier = trialAudioCtx.createOscillator();
    carrier.type = "sine";
    carrier.frequency.value = 1000;

    const amp = trialAudioCtx.createGain();
    amp.gain.value = 0.0;

    const mod = trialAudioCtx.createOscillator();
    mod.type = "sine";
    mod.frequency.value = modHz;

    const modDepth = trialAudioCtx.createGain();
    modDepth.gain.value = 0.5;

    const dcOffset = trialAudioCtx.createConstantSource();
    const offsetGain = trialAudioCtx.createGain();
    offsetGain.gain.value = 0.5;

    const panner = trialAudioCtx.createStereoPanner();
    panner.pan.value = panValue;

    mod.connect(modDepth);
    modDepth.connect(amp.gain);
    dcOffset.connect(offsetGain);
    offsetGain.connect(amp.gain);

    carrier.connect(amp);
    amp.connect(panner);
    panner.connect(trialMasterGain);

    carrier.start();
    mod.start();
    dcOffset.start();

    return [carrier, mod, dcOffset, amp, modDepth, offsetGain, panner];
}

function mixDownToMono(buffer) {
    const frameCount = buffer.length;
    const mono = new Float32Array(frameCount);
    const channels = Math.max(1, buffer.numberOfChannels);
    for (let ch = 0; ch < channels; ch++) {
        const input = buffer.getChannelData(ch);
        for (let i = 0; i < frameCount; i++) {
            mono[i] += input[i];
        }
    }
    const scale = 1 / channels;
    for (let i = 0; i < frameCount; i++) {
        mono[i] *= scale;
    }
    return mono;
}

function createRoutedStereoBuffer(buffer, ear = "CENTER") {
    const frameCount = buffer.length;
    const routed = trialAudioCtx.createBuffer(2, frameCount, buffer.sampleRate);
    const outL = routed.getChannelData(0);
    const outR = routed.getChannelData(1);
    const mono = mixDownToMono(buffer);

    if (ear === "LEFT") {
        outL.set(mono);
        return routed;
    }
    if (ear === "RIGHT") {
        outR.set(mono);
        return routed;
    }

    // CENTER: preserve stereo if present, otherwise duplicate mono.
    if (buffer.numberOfChannels >= 2) {
        outL.set(buffer.getChannelData(0));
        outR.set(buffer.getChannelData(1));
    } else {
        outL.set(mono);
        outR.set(mono);
    }
    return routed;
}

function createEarRoutedBufferPlayback(buffer, ear = "CENTER", gainValue = 0.0) {
    const source = trialAudioCtx.createBufferSource();
    source.buffer = createRoutedStereoBuffer(buffer, ear);
    source.loop = true;

    const gain = trialAudioCtx.createGain();
    gain.gain.value = gainValue;
    source.connect(gain);
    gain.connect(trialMasterGain);
    source.start();
    return [source, gain];
}

function startTrialAudio(trial) {
    if (!trialAudioCtx || !trialMasterGain) return;
    stopTrialAudio();

    const setSynthFallback = () => {
        if (trial.condition === "AM_37") {
            activeTrialNodes = createSynthAmTone(37, -1.0);
        } else if (trial.condition === "AM_43") {
            activeTrialNodes = createSynthAmTone(43, 1.0);
        } else {
            const leftChain = createSynthAmTone(37, -1.0);
            const rightChain = createSynthAmTone(43, 1.0);
            activeTrialNodes = [...leftChain, ...rightChain];
        }
    };

    if (trial.condition === "AM_37") {
        const buffer = trialAudioBuffers.AM_37;
        if (buffer) {
            activeTrialNodes = createEarRoutedBufferPlayback(buffer, "LEFT", 0.0);
        } else {
            setSynthFallback();
        }
    } else if (trial.condition === "AM_43") {
        const buffer = trialAudioBuffers.AM_43;
        if (buffer) {
            activeTrialNodes = createEarRoutedBufferPlayback(buffer, "RIGHT", 0.0);
        } else {
            setSynthFallback();
        }
    } else if (trial.condition === "DICHOTIC") {
        const combined = trialAudioBuffers.DICHOTIC;
        if (combined) {
            // Always use the dedicated dichotic WAV for dichotic blocks.
            activeTrialNodes = createEarRoutedBufferPlayback(combined, "CENTER", 0.0);
        } else {
            setSynthFallback();
        }
    }

    const now = trialAudioCtx.currentTime;
    trialMasterGain.gain.cancelScheduledValues(now);
    trialMasterGain.gain.setValueAtTime(0.0001, now);
    trialMasterGain.gain.exponentialRampToValueAtTime(0.16, now + 0.08);
}

function stopTrialAudio() {
    if (!trialAudioCtx || activeTrialNodes.length === 0) return;
    const now = trialAudioCtx.currentTime;
    trialMasterGain.gain.cancelScheduledValues(now);
    trialMasterGain.gain.setValueAtTime(Math.max(trialMasterGain.gain.value, 0.0001), now);
    trialMasterGain.gain.exponentialRampToValueAtTime(0.0001, now + 0.06);

    const toStop = activeTrialNodes.slice();
    setTimeout(() => {
        for (const node of toStop) {
            try {
                if (typeof node.stop === "function") {
                    node.stop();
                }
            } catch (_) {
                // Ignore stop errors for already-stopped nodes
            }
            try {
                if (typeof node.disconnect === "function") {
                    node.disconnect();
                }
            } catch (_) {
                // Ignore disconnect errors
            }
        }
    }, 80);
    activeTrialNodes = [];
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

/** Shuffle an array in place (Fisher-Yates). */
function shuffle(arr) {
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
}

function buildTrialQueue(trialsPerCondition) {
    const queue = [];

    for (let i = 0; i < trialsPerCondition; i++) {
        queue.push({ condition: "AM_37", focus: "NONE", cueLabel: "37 Hz modulation only" });
    }

    for (let i = 0; i < trialsPerCondition; i++) {
        queue.push({ condition: "AM_43", focus: "NONE", cueLabel: "43 Hz modulation only" });
    }

    const dichoticFocus = [];
    for (let i = 0; i < trialsPerCondition; i++) {
        dichoticFocus.push(i % 2 === 0 ? "LEFT" : "RIGHT");
    }
    shuffle(dichoticFocus);
    for (const focus of dichoticFocus) {
        queue.push({
            condition: "DICHOTIC",
            focus,
            cueLabel: focus === "LEFT" ? "Dichotic: focus LEFT ear" : "Dichotic: focus RIGHT ear"
        });
    }

    return queue;
}

function currentDuration() {
    return state === "REST" ? REST_DURATION : TASK_DURATION;
}

// --- Test start (recording begins here) --------------------------------------
async function startTest() {
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

    // Read cycles as trials per condition (clamp to >= 1)
    numCycles = Math.max(1, parseInt(document.getElementById('numCycles').value, 10) || 5);
    trialQueue = buildTrialQueue(numCycles);
    taskIndex = 0;
    totalTrials = trialQueue.length;
    completedByCondition = { AM_37: 0, AM_43: 0, DICHOTIC: 0 };
    eventSequence = 0;
    activeTrial = null;
    focusCue = "NONE";

    await ensureTrialAudioReady();

    // Reset state — always start with a REST period
    rounds = 0;
    previousState = "None";
    state = "REST";

    // Delay task start slightly so Python has time to finish initialising
    // the XDF recorder and LSL outlets before the first marker arrives.
    setTimeout(() => {
        startTime = Date.now();
        sendMarker("None", "REST");
        emitStructuredMarker("session_start", {
            start: "REST",
            stop: "None",
            trial_plan: trialQueue.map((trial) => ({
                condition: trial.condition,
                focus: trial.focus
            }))
        });

        document.fonts.ready.then(() => {
            requestAnimationFrame(update);
        });
    }, 200);
}

function transitionRestToTask() {
    const nextTrial = trialQueue[taskIndex];
    taskIndex++;

    previousState = state;
    state = "TASK";
    activeTrial = nextTrial;
    focusCue = nextTrial.focus || "NONE";

    sendMarker("REST", "TASK");
    emitStructuredMarker("trial_start", {
        stop: "REST",
        start: "TASK",
        condition: nextTrial.condition,
        focus: focusCue,
        audio_route:
            nextTrial.condition === "AM_37"
                ? "LEFT_ONLY"
                : nextTrial.condition === "AM_43"
                    ? "RIGHT_ONLY"
                    : "LEFT_37_RIGHT_43",
        audio_files:
            nextTrial.condition === "DICHOTIC"
                ? { left: AUDIO_FILES.AM_37, right: AUDIO_FILES.AM_43, fallback: AUDIO_FILES.DICHOTIC }
                : { single: AUDIO_FILES[nextTrial.condition] },
        block_trial_index: completedByCondition[nextTrial.condition] + 1,
        block_size: numCycles
    });

    if (nextTrial.condition === "DICHOTIC") {
        emitStructuredMarker("cue_onset", {
            condition: nextTrial.condition,
            focus: focusCue,
            cue_text: nextTrial.cueLabel
        });
    }

    startTrialAudio(nextTrial);
    emitStructuredMarker("audio_onset", {
        condition: nextTrial.condition,
        focus: focusCue,
        audio_route:
            nextTrial.condition === "AM_37"
                ? "LEFT_ONLY"
                : nextTrial.condition === "AM_43"
                    ? "RIGHT_ONLY"
                    : "LEFT_37_RIGHT_43"
    });
}

function transitionTaskToRestOrEnd() {
    const endedTrial = activeTrial;
    emitStructuredMarker("audio_offset", {
        condition: endedTrial ? endedTrial.condition : "NONE",
        focus: focusCue,
        audio_route:
            endedTrial?.condition === "AM_37"
                ? "LEFT_ONLY"
                : endedTrial?.condition === "AM_43"
                    ? "RIGHT_ONLY"
                    : endedTrial?.condition === "DICHOTIC"
                        ? "LEFT_37_RIGHT_43"
                        : "NONE"
    });
    stopTrialAudio();

    rounds++;
    if (endedTrial) {
        completedByCondition[endedTrial.condition] += 1;
    }

    if (rounds >= totalTrials) {
        sendMarker("TASK", "None");
        emitStructuredMarker("session_end", {
            stop: "TASK",
            start: "None",
            completed: completedByCondition
        });
        if (pyBridge) { pyBridge.stop_streams(); }
        endSession();
        return true;
    }

    previousState = state;
    sendMarker("TASK", "REST");
    state = "REST";
    activeTrial = null;
    focusCue = "NONE";
    emitStructuredMarker("trial_end", {
        stop: "TASK",
        start: "REST"
    });
    return false;
}

// --- Main loop ---------------------------------------------------------------
function update() {
    if (canvas.style.display === 'none') return;

    const elapsed = Date.now() - startTime;
    const dur = currentDuration();

    if (elapsed >= dur) {
        // --- Transition ---
        if (state === "REST") {
            transitionRestToTask();
        } else {
            if (transitionTaskToRestOrEnd()) {
                return;
            }
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

    // ---- REST state: countdown circle draining around crosshair ----
    if (state === "REST") {
        ctx.beginPath();
        ctx.arc(cx, cy, 35, -Math.PI / 2, (-Math.PI / 2) + (Math.PI * 2 * (1 - progress)));
        ctx.strokeStyle = "rgba(0, 242, 255, 0.4)";
        ctx.lineWidth = 3;
        ctx.stroke();
    }

    // ---- L / R visuals (used for dichotic focus cueing) ----
    const showLeftFocus = state === "TASK" && activeTrial && activeTrial.condition === "DICHOTIC" && focusCue === "LEFT";
    const showRightFocus = state === "TASK" && activeTrial && activeTrial.condition === "DICHOTIC" && focusCue === "RIGHT";
    drawProgressiveLetter(cx - 300, cy, "L", showLeftFocus, "#00f2ff", progress);
    drawProgressiveLetter(cx + 300, cy, "R", showRightFocus, "#7000ff", progress);

    // ---- Instruction text ----
    ctx.textAlign = "center";
    ctx.font = "700 22px 'Space Grotesk'";
    if (state === "REST") {
        ctx.fillStyle = "#00f2ff";
        ctx.fillText("BLINK NOW  /  CLEAR MIND", cx, cy - 180);
    } else if (activeTrial) {
        if (activeTrial.condition === "AM_37") {
            ctx.fillStyle = "#00f2ff";
            ctx.fillText("37 Hz AM ONLY  —  LISTEN AND STAY STILL", cx, cy - 180);
        } else if (activeTrial.condition === "AM_43") {
            ctx.fillStyle = "#59a4ff";
            ctx.fillText("43 Hz AM ONLY  —  LISTEN AND STAY STILL", cx, cy - 180);
        } else if (activeTrial.condition === "DICHOTIC") {
            ctx.fillStyle = focusCue === "LEFT" ? "#00f2ff" : "#7000ff";
            ctx.fillText(
                focusCue === "LEFT"
                    ? "DICHOTIC: FOCUS LEFT EAR  —  DO NOT BLINK"
                    : "DICHOTIC: FOCUS RIGHT EAR  —  DO NOT BLINK",
                cx,
                cy - 180
            );
        }
    }

    // ---- Trial counter ----
    ctx.fillStyle = "#222";
    ctx.font = "700 22px 'Space Grotesk'";
    ctx.textAlign = "center";
    const currentBlock = activeTrial ? CONDITION_ORDER.indexOf(activeTrial.condition) + 1 : Math.min(Math.floor(taskIndex / Math.max(numCycles, 1)) + 1, 3);
    const conditionLabel = activeTrial ? activeTrial.condition : "REST";
    ctx.fillText(
        `BLOCK ${currentBlock} / 3 (${conditionLabel})  —  TRIAL ${Math.min(rounds + 1, totalTrials)} / ${totalTrials}`,
        cx,
        canvas.height - 50
    );
}

// --- Session end -------------------------------------------------------------
function endSession() {
    stopTrialAudio();
    canvas.style.display = 'none';
    document.getElementById('closing-screen').style.display = 'block';
}

function resetToHome() { location.reload(); }
