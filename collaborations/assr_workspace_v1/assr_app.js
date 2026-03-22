// ============================================================
// ASSR Task - Calibration + Dichotic Attention
// Protocol source: AGENTS.md "PROTOCOL FOR IMAGERY TASK"
// ============================================================

const TEST_TIME_SCALE = window.ASSR_TEST_SCALE || 1.0;

const AUDIO_FILES = {
    LEFT_37: "file:///Users/tarunramakrishnan/Downloads/left_1000Hz_37HzAM.wav",
    RIGHT_43: "file:///Users/tarunramakrishnan/Downloads/right_1000Hz_43HzAM.wav",
    DICHOTIC: "file:///Users/tarunramakrishnan/Downloads/dichotic_1000Hz_37vs43HzAM.wav"
};

const MARKERS = {
    MAIN_TRIAL_RESET: 10,
    CAL_LEFT_START: 101,
    CAL_RIGHT_START: 102,
    DICHOTIC_ATTEND_LEFT_START: 201,
    DICHOTIC_ATTEND_RIGHT_START: 202
};

const PROTOCOL = {
    calibration: {
        restMin: 3.0, restMax: 5.0,
        fixMin: 1.5, fixMax: 2.5,
        prime: 1.5,
        stimulation: 6.0
    },
    main: {
        restMin: 3.0, restMax: 5.0,
        fixMin: 2.0, fixMax: 3.0,
        targetPrime: 1.5,
        otherPrime: 1.5,
        prepMin: 0.5, prepMax: 1.0,
        dichotic: 6.0,
        endBuffer: 1.0
    },
    probeBurstSeconds: 0.5
};

let pyBridge = null;
let eventSequence = 0;
let protocolRunning = false;

const cueText = document.getElementById("cue-text");
const subCueText = document.getElementById("subcue-text");
const progressFill = document.getElementById("progress-fill");
const statusFooter = document.getElementById("status-footer");
const leftEarBox = document.getElementById("left-ear-box");
const rightEarBox = document.getElementById("right-ear-box");

let audioCtx = null;
let masterGain = null;
const audioBuffers = {};
let activeNodes = [];

if (typeof QWebChannel !== "undefined") {
    new QWebChannel(qt.webChannelTransport, function(channel) {
        pyBridge = channel.objects.pyBridge;
        console.log("QWebChannel connected for ASSR task");
    });
}

function randInRange(minSec, maxSec) {
    return minSec + (Math.random() * (maxSec - minSec));
}

function ms(seconds) {
    return Math.round(seconds * 1000 * TEST_TIME_SCALE);
}

function waitMs(durationMs) {
    return new Promise(resolve => setTimeout(resolve, Math.max(0, durationMs)));
}

function sendRawMarker(value) {
    const marker = String(value);
    if (pyBridge) {
        pyBridge.send_marker(marker);
    }
}

function sendStructuredMarker(eventName, payload = {}) {
    const marker = JSON.stringify({
        event: eventName,
        sequence: eventSequence++,
        timestamp_unix_ms: Date.now(),
        ...payload
    });
    if (pyBridge) {
        pyBridge.send_marker(marker);
    }
}

function setSaveDir(path) {
    document.getElementById("saveDir").value = path;
}

function pickSaveDir() {
    if (pyBridge) {
        pyBridge.pick_save_dir();
    } else {
        alert("Bridge not ready – type the path manually.");
    }
}

function showInstructions() {
    if (!document.getElementById("subName").value) {
        alert("Subject ID Required");
        return;
    }
    if (!document.getElementById("saveDir").value) {
        alert("Save Location Required");
        return;
    }
    document.getElementById("welcome-screen").style.display = "none";
    document.getElementById("instruction-screen").style.display = "block";
}

function resetToHome() {
    location.reload();
}

function setCue(mainText, subText = "") {
    cueText.textContent = mainText;
    subCueText.textContent = subText;
}

function setSides(active) {
    leftEarBox.classList.remove("active-left");
    rightEarBox.classList.remove("active-right");
    if (active === "LEFT") {
        leftEarBox.classList.add("active-left");
    } else if (active === "RIGHT") {
        rightEarBox.classList.add("active-right");
    } else if (active === "BOTH") {
        leftEarBox.classList.add("active-left");
        rightEarBox.classList.add("active-right");
    }
}

async function runTimedStage(options) {
    const {
        stageName,
        durationMs,
        cue,
        subcue,
        activeSide,
        footer,
        onStart,
        onEnd
    } = options;

    setCue(cue || "", subcue || "");
    setSides(activeSide || "NONE");
    statusFooter.textContent = footer || "";
    progressFill.style.width = "0%";

    if (onStart) onStart();
    sendStructuredMarker("stage_start", { stage: stageName, duration_ms: durationMs });

    const start = performance.now();
    while (true) {
        const elapsed = performance.now() - start;
        const pct = Math.min(elapsed / durationMs, 1);
        progressFill.style.width = `${(pct * 100).toFixed(1)}%`;
        if (elapsed >= durationMs) break;
        await waitMs(33);
    }

    progressFill.style.width = "100%";
    if (onEnd) onEnd();
    sendStructuredMarker("stage_end", { stage: stageName });
}

async function ensureAudio() {
    if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        masterGain = audioCtx.createGain();
        masterGain.gain.value = 0.15;
        masterGain.connect(audioCtx.destination);
    }
    if (audioCtx.state === "suspended") {
        await audioCtx.resume();
    }
    await preloadAudio();
}

async function preloadAudio() {
    for (const [name, url] of Object.entries(AUDIO_FILES)) {
        if (audioBuffers[name]) continue;
        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const arr = await response.arrayBuffer();
            audioBuffers[name] = await audioCtx.decodeAudioData(arr);
        } catch (err) {
            audioBuffers[name] = null;
            console.warn(`Audio file load failed for ${name}, using synth fallback:`, err);
        }
    }
}

function mixDownToMono(buffer) {
    const mono = new Float32Array(buffer.length);
    const channels = Math.max(1, buffer.numberOfChannels);
    for (let ch = 0; ch < channels; ch++) {
        const data = buffer.getChannelData(ch);
        for (let i = 0; i < buffer.length; i++) {
            mono[i] += data[i];
        }
    }
    const scale = 1 / channels;
    for (let i = 0; i < buffer.length; i++) {
        mono[i] *= scale;
    }
    return mono;
}

function routeBuffer(buffer, ear) {
    const routed = audioCtx.createBuffer(2, buffer.length, buffer.sampleRate);
    const left = routed.getChannelData(0);
    const right = routed.getChannelData(1);
    const mono = mixDownToMono(buffer);

    if (ear === "LEFT") {
        left.set(mono);
    } else if (ear === "RIGHT") {
        right.set(mono);
    } else if (buffer.numberOfChannels >= 2) {
        left.set(buffer.getChannelData(0));
        right.set(buffer.getChannelData(1));
    } else {
        left.set(mono);
        right.set(mono);
    }
    return routed;
}

function clearAudioNodes() {
    const nodes = activeNodes.slice();
    activeNodes = [];
    for (const node of nodes) {
        try {
            if (typeof node.stop === "function") node.stop();
        } catch (_) {}
        try {
            if (typeof node.disconnect === "function") node.disconnect();
        } catch (_) {}
    }
}

function startSynthTone(freqHz, ear, durationMs = null) {
    const osc = audioCtx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = freqHz;
    const gain = audioCtx.createGain();
    gain.gain.value = 0.0;
    const panner = audioCtx.createStereoPanner();
    panner.pan.value = ear === "LEFT" ? -1 : ear === "RIGHT" ? 1 : 0;

    osc.connect(gain);
    gain.connect(panner);
    panner.connect(masterGain);

    const now = audioCtx.currentTime;
    const startAt = now + 0.01;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.12, startAt + 0.02);
    osc.start(startAt);
    if (durationMs !== null) {
        const endAt = startAt + (durationMs / 1000);
        gain.gain.exponentialRampToValueAtTime(0.0001, endAt);
        osc.stop(endAt + 0.02);
    }
    return [osc, gain, panner, startAt];
}

function startLoop(name, ear) {
    clearAudioNodes();
    const buffer = audioBuffers[name];
    if (!buffer) {
        const synthFreq = name === "LEFT_37" ? 1000 : name === "RIGHT_43" ? 1000 : 1000;
        const synthEar = name === "LEFT_37" ? "LEFT" : name === "RIGHT_43" ? "RIGHT" : "CENTER";
        const [osc, gain, panner, startAt] = startSynthTone(synthFreq, synthEar, null);
        activeNodes = [osc, gain, panner];
        return startAt;
    }

    const routed = routeBuffer(buffer, ear);
    const source = audioCtx.createBufferSource();
    source.buffer = routed;
    source.loop = true;

    const gain = audioCtx.createGain();
    gain.gain.value = 0.0;
    source.connect(gain);
    gain.connect(masterGain);

    const now = audioCtx.currentTime;
    const startAt = now + 0.01;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.15, startAt + 0.06);
    source.start(startAt);

    activeNodes = [source, gain];
    return startAt;
}

function stopLoop() {
    if (!audioCtx || activeNodes.length === 0) return;
    const now = audioCtx.currentTime;
    const gain = activeNodes.find((n) => typeof n.gain !== "undefined");
    if (gain) {
        gain.gain.cancelScheduledValues(now);
        gain.gain.setValueAtTime(Math.max(gain.gain.value, 0.0001), now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.05);
    }
    setTimeout(() => clearAudioNodes(), 80);
}

function playBurst(name, ear, durationMs) {
    if (!audioBuffers[name]) {
        const synthFreq = name === "LEFT_37" ? 1000 : 1000;
        const [osc, gain, panner, startAt] = startSynthTone(synthFreq, ear, durationMs);
        return [osc, gain, panner, startAt];
    }
    const buffer = routeBuffer(audioBuffers[name], ear);
    const source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.loop = false;

    const gain = audioCtx.createGain();
    gain.gain.value = 0.0;
    source.connect(gain);
    gain.connect(masterGain);

    const now = audioCtx.currentTime;
    const startAt = now + 0.01;
    const burstSec = Math.max(0.02, durationMs / 1000);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.15, startAt + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, startAt + burstSec);

    source.start(startAt);
    source.stop(startAt + burstSec + 0.02);
    return [source, gain, startAt];
}

function shuffledSides(perSide) {
    const arr = [];
    for (let i = 0; i < perSide; i++) arr.push("LEFT");
    for (let i = 0; i < perSide; i++) arr.push("RIGHT");
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
}

function buildProtocolTrials(calPerSide, mainPerSide) {
    const calibration = shuffledSides(calPerSide).map((side, idx) => ({
        phase: "CALIBRATION",
        side,
        trialNumber: idx + 1,
        phaseTrialTotal: calPerSide * 2
    }));
    const main = shuffledSides(mainPerSide).map((side, idx) => ({
        phase: "MAIN_DICHOTIC",
        side,
        trialNumber: idx + 1,
        phaseTrialTotal: mainPerSide * 2
    }));
    return [...calibration, ...main];
}

async function runCalibrationTrial(trial, globalIndex, globalTotal) {
    const side = trial.side;
    const toneFile = side === "LEFT" ? "LEFT_37" : "RIGHT_43";
    const markerCode = side === "LEFT" ? MARKERS.CAL_LEFT_START : MARKERS.CAL_RIGHT_START;

    const restMs = ms(randInRange(PROTOCOL.calibration.restMin, PROTOCOL.calibration.restMax));
    await runTimedStage({
        stageName: "cal_rest",
        durationMs: restMs,
        cue: "REST",
        subcue: "Blink allowed",
        activeSide: "NONE",
        footer: `Calibration ${trial.trialNumber}/${trial.phaseTrialTotal} - Trial ${globalIndex}/${globalTotal}`
    });

    const fixMs = ms(randInRange(PROTOCOL.calibration.fixMin, PROTOCOL.calibration.fixMax));
    await runTimedStage({
        stageName: "cal_fixation",
        durationMs: fixMs,
        cue: "FIXATE +",
        subcue: "Stop blinking",
        activeSide: "NONE",
        footer: "Calibration fixation"
    });

    const primeMs = ms(PROTOCOL.calibration.prime);
    await runTimedStage({
        stageName: "cal_prime",
        durationMs: primeMs,
        cue: side === "LEFT" ? "LEFT (37 Hz)" : "RIGHT (43 Hz)",
        subcue: "Prime cue + tone onset",
        activeSide: side,
        footer: "Calibration prime",
        onStart: () => {
            const startAt = startLoop(toneFile, side);
            sendStructuredMarker("audio_prime_start", {
                phase: "CALIBRATION",
                side,
                audio_file: AUDIO_FILES[toneFile],
                audio_start_audioctx_time: startAt
            });
        }
    });

    const stimMs = ms(PROTOCOL.calibration.stimulation);
    await runTimedStage({
        stageName: "cal_stimulation",
        durationMs: stimMs,
        cue: side === "LEFT" ? "ATTEND LEFT" : "ATTEND RIGHT",
        subcue: "Passive listening",
        activeSide: side,
        footer: "Calibration stimulation",
        onStart: () => {
            // Numeric XDF marker synchronized to stimulation onset.
            sendRawMarker(markerCode);
            sendStructuredMarker("xdf_trigger", {
                phase: "CALIBRATION",
                side,
                marker_code: markerCode,
                at: "stimulation_start"
            });
        },
        onEnd: () => {
            stopLoop();
        }
    });
}

async function runMainTrial(trial, globalIndex, globalTotal) {
    const target = trial.side;
    const other = target === "LEFT" ? "RIGHT" : "LEFT";
    const targetFile = target === "LEFT" ? "LEFT_37" : "RIGHT_43";
    const otherFile = other === "LEFT" ? "LEFT_37" : "RIGHT_43";
    const markerCode = target === "LEFT"
        ? MARKERS.DICHOTIC_ATTEND_LEFT_START
        : MARKERS.DICHOTIC_ATTEND_RIGHT_START;

    const restMs = ms(randInRange(PROTOCOL.main.restMin, PROTOCOL.main.restMax));
    await runTimedStage({
        stageName: "main_rest",
        durationMs: restMs,
        cue: "REST",
        subcue: "Blink allowed",
        activeSide: "NONE",
        footer: `Dichotic ${trial.trialNumber}/${trial.phaseTrialTotal} - Trial ${globalIndex}/${globalTotal}`,
        onStart: () => {
            sendRawMarker(MARKERS.MAIN_TRIAL_RESET);
            sendStructuredMarker("xdf_trigger", {
                phase: "MAIN_DICHOTIC",
                marker_code: MARKERS.MAIN_TRIAL_RESET,
                at: "trial_reset_rest_start"
            });
        }
    });

    const fixMs = ms(randInRange(PROTOCOL.main.fixMin, PROTOCOL.main.fixMax));
    await runTimedStage({
        stageName: "main_fixation",
        durationMs: fixMs,
        cue: "FIXATE +",
        subcue: "Prepare to attend target ear",
        activeSide: "NONE",
        footer: "Main fixation"
    });

    const targetPrimeMs = ms(PROTOCOL.main.targetPrime);
    await runTimedStage({
        stageName: "main_target_prime",
        durationMs: targetPrimeMs,
        cue: target === "LEFT" ? "FOCUS LEFT" : "FOCUS RIGHT",
        subcue: "Target probe",
        activeSide: target,
        footer: "Target prime",
        onStart: () => {
            const [source, gain, startAt] = playBurst(targetFile, target, ms(PROTOCOL.probeBurstSeconds));
            activeNodes = [source, gain];
            sendStructuredMarker("target_probe_start", {
                phase: "MAIN_DICHOTIC",
                target,
                audio_file: AUDIO_FILES[targetFile],
                audio_start_audioctx_time: startAt
            });
        },
        onEnd: () => clearAudioNodes()
    });

    const otherPrimeMs = ms(PROTOCOL.main.otherPrime);
    await runTimedStage({
        stageName: "main_other_prime",
        durationMs: otherPrimeMs,
        cue: other === "LEFT" ? "OTHER: LEFT" : "OTHER: RIGHT",
        subcue: "Non-target probe",
        activeSide: other,
        footer: "Distractor prime",
        onStart: () => {
            const [source, gain, startAt] = playBurst(otherFile, other, ms(PROTOCOL.probeBurstSeconds));
            activeNodes = [source, gain];
            sendStructuredMarker("other_probe_start", {
                phase: "MAIN_DICHOTIC",
                target,
                other,
                audio_file: AUDIO_FILES[otherFile],
                audio_start_audioctx_time: startAt
            });
        },
        onEnd: () => clearAudioNodes()
    });

    const prepMs = ms(randInRange(PROTOCOL.main.prepMin, PROTOCOL.main.prepMax));
    await runTimedStage({
        stageName: "main_prep_gap",
        durationMs: prepMs,
        cue: "PREPARE",
        subcue: "Silence gap",
        activeSide: "NONE",
        footer: "Preparation gap"
    });

    const dichoticMs = ms(PROTOCOL.main.dichotic);
    await runTimedStage({
        stageName: "main_dichotic_task",
        durationMs: dichoticMs,
        cue: target === "LEFT" ? "DICHOTIC - ATTEND LEFT" : "DICHOTIC - ATTEND RIGHT",
        subcue: "Ignore the distractor ear",
        activeSide: target,
        footer: "Dichotic stimulation",
        onStart: () => {
            const startAt = startLoop("DICHOTIC", "CENTER");
            // Numeric XDF marker synchronized to dichotic audio onset.
            sendRawMarker(markerCode);
            sendStructuredMarker("xdf_trigger", {
                phase: "MAIN_DICHOTIC",
                target,
                marker_code: markerCode,
                at: "dichotic_audio_start",
                audio_file: AUDIO_FILES.DICHOTIC,
                audio_start_audioctx_time: startAt
            });
        },
        onEnd: () => stopLoop()
    });

    const endBufferMs = ms(PROTOCOL.main.endBuffer);
    await runTimedStage({
        stageName: "main_end_buffer",
        durationMs: endBufferMs,
        cue: "HOLD",
        subcue: "End-of-trial buffer",
        activeSide: "NONE",
        footer: "Trial ending buffer"
    });
}

async function startProtocol() {
    if (protocolRunning) return;
    protocolRunning = true;

    document.getElementById("instruction-screen").style.display = "none";
    document.getElementById("assr-stage").style.display = "block";

    const subjectId = (document.getElementById("subName").value || "UNKNOWN").trim();
    const saveDir = (document.getElementById("saveDir").value || "").trim();
    const calPerSide = Math.max(1, parseInt(document.getElementById("calTrialsPerSide").value, 10) || 10);
    const mainPerSide = Math.max(1, parseInt(document.getElementById("mainTrialsPerSide").value, 10) || 20);

    await ensureAudio();

    if (pyBridge) {
        pyBridge.start_streams(subjectId, saveDir);
    }

    const trials = buildProtocolTrials(calPerSide, mainPerSide);
    sendStructuredMarker("session_start", {
        task: "ASSR",
        subject_id: subjectId,
        cal_trials_per_side: calPerSide,
        main_trials_per_side: mainPerSide,
        total_trials: trials.length
    });

    let globalIndex = 0;
    for (const trial of trials) {
        globalIndex += 1;
        sendStructuredMarker("trial_start", {
            task: "ASSR",
            trial_global_index: globalIndex,
            trial_global_total: trials.length,
            phase: trial.phase,
            trial_phase_index: trial.trialNumber,
            trial_phase_total: trial.phaseTrialTotal,
            target_side: trial.side
        });

        if (trial.phase === "CALIBRATION") {
            await runCalibrationTrial(trial, globalIndex, trials.length);
        } else {
            await runMainTrial(trial, globalIndex, trials.length);
        }

        sendStructuredMarker("trial_end", {
            task: "ASSR",
            trial_global_index: globalIndex,
            phase: trial.phase,
            target_side: trial.side
        });
    }

    sendStructuredMarker("session_end", { task: "ASSR", total_trials: trials.length });
    if (pyBridge) {
        pyBridge.stop_streams();
    }

    document.getElementById("assr-stage").style.display = "none";
    document.getElementById("closing-screen").style.display = "block";
    protocolRunning = false;
}
