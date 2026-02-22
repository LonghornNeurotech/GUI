const canvas = document.getElementById('testCanvas');
const ctx = canvas.getContext('2d');
let state = "REST"; 
let cueSide = "";
let startTime = 0;
let rounds = 0;
const MAX_ROUNDS = 5;
const DURATION = 4000;

// Ocean Wave Audio Context
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
    filter.frequency.value = 800; // Muffled, water-like sound

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
    gainNode.gain.exponentialRampToValueAtTime(0.08, now + 2.5); // Tide in
    gainNode.gain.exponentialRampToValueAtTime(0.01, now + 5);   // Tide out
    setTimeout(simulateTides, 5000);
}

function stopAudio() {
    if (noiseNode) { noiseNode.stop(); audioCtx.close(); }
}

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

function showInstructions() {
    if(!document.getElementById('subName').value) return alert("Subject ID Required");
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

function startTest() {
    document.getElementById('mindfulness-screen').style.display = 'none';
    canvas.style.display = 'block';
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    startTime = Date.now();
    rounds = 0;
    requestAnimationFrame(update);
}

function update() {
    if (canvas.style.display === 'none') return;
    const elapsed = Date.now() - startTime;
    if (elapsed >= DURATION) {
        if (state === "REST") {
            state = "CUE";
            cueSide = Math.random() > 0.5 ? "LEFT" : "RIGHT";
        } else {
            state = "REST";
            rounds++;
            if (rounds >= MAX_ROUNDS) return endSession();
        }
        startTime = Date.now();
    }
    draw();
    requestAnimationFrame(update);
}

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
    const progress = Math.min((Date.now() - startTime) / DURATION, 1);

    // Crosshair & REST Circle
    ctx.lineWidth = 2;
    if (state === "REST") {
        ctx.beginPath();
        ctx.arc(cx, cy, 35, -Math.PI / 2, (-Math.PI / 2) + (Math.PI * 2 * (1 - progress)));
        ctx.strokeStyle = "rgba(0, 242, 255, 0.4)";
        ctx.stroke();
    }
    ctx.strokeStyle = "#333";
    ctx.beginPath();
    ctx.moveTo(cx-20, cy); ctx.lineTo(cx+20, cy);
    ctx.moveTo(cx, cy-20); ctx.lineTo(cx, cy+20);
    ctx.stroke();

    drawProgressiveLetter(cx - 300, cy, "L", (state === "CUE" && cueSide === "LEFT"), "#00f2ff", progress);
    drawProgressiveLetter(cx + 300, cy, "R", (state === "CUE" && cueSide === "RIGHT"), "#7000ff", progress);

    ctx.textAlign = "center";
    ctx.font = "700 22px 'Space Grotesk'";
    if (state === "REST") {
        ctx.fillStyle = "#00f2ff";
        ctx.fillText("BLINK NOW / CLEAR MIND", cx, cy - 180);
    } else {
        const color = (cueSide === "LEFT") ? "#00f2ff" : "#7000ff";
        ctx.fillStyle = color;
        ctx.fillText(`THINK ${cueSide} MOVEMENT`, cx, cy - 180);
    }
    ctx.fillStyle = "#222";
    ctx.fillText(`ROUND ${rounds + 1} OF 5`, cx, canvas.height - 50);
}

function endSession() {
    canvas.style.display = 'none';
    document.getElementById('closing-screen').style.display = 'block';
}

function resetToHome() { location.reload(); }