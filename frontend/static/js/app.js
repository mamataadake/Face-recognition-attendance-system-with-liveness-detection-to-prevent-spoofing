document.addEventListener("DOMContentLoaded", () => {
    // Initialize Lucide Icons
    lucide.createIcons();

    // --- Tab Navigation Logic ---
    const navLinks = document.querySelectorAll(".nav-link");
    const tabPanes = document.querySelectorAll(".tab-pane");
    const tabTitle = document.getElementById("tab-title");

    navLinks.forEach(link => {
        link.addEventListener("click", (e) => {
            e.preventDefault();
            const tabId = link.getAttribute("data-tab");

            // Stop webcam scanner if active and leaving camera tab
            if (activeTab === "camera" && tabId !== "camera") {
                stopRecognitionScanner();
            }

            // Remove active classes
            navLinks.forEach(l => l.classList.remove("active"));
            tabPanes.forEach(p => p.classList.remove("active"));

            // Add active class to clicked link & pane
            link.classList.add("active");
            document.getElementById(`${tabId}-tab`).classList.add("active");

            // Update Header Title
            tabTitle.textContent = link.querySelector("span").textContent;
            activeTab = tabId;

            // Trigger specific tab loading functions
            if (tabId === "dashboard") {
                loadDashboardStats();
            } else if (tabId === "students") {
                fetchStudents();
            } else if (tabId === "attendance") {
                fetchAttendanceLogs();
            }
        });
    });

    let activeTab = "dashboard";

    // --- Chart.js Initialization ---
    const ctx = document.getElementById('attendanceChart').getContext('2d');
    let attendanceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            datasets: [{
                label: 'Present Count',
                data: [0, 0, 0, 0, 0, 0, 0],
                borderColor: '#6366f1',
                backgroundColor: 'rgba(99, 102, 241, 0.1)',
                borderWidth: 3,
                fill: true,
                tension: 0.4,
                pointBackgroundColor: '#8b5cf6',
                pointHoverRadius: 7
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8', stepSize: 1 }
                },
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8' }
                }
            }
        }
    });

    // --- Load Dashboard Stats ---
    function loadDashboardStats() {
        fetch("/api/statistics")
            .then(res => res.json())
            .then(data => {
                document.getElementById("stat-students").textContent = data.total_students;
                document.getElementById("stat-images").textContent = data.total_images;
                document.getElementById("stat-model").textContent = data.model_status;
                document.getElementById("stat-attendance").textContent = data.attendance_today;
                document.getElementById("stat-trained-time").textContent = data.model_last_trained;

                // Update Status color
                const modelPill = document.getElementById("stat-model");
                if (data.model_status === "Trained") {
                    modelPill.style.color = "#10b981";
                } else {
                    modelPill.style.color = "#ef4444";
                }

                // Update Chart Data
                attendanceChart.data.labels = data.trend_labels;
                attendanceChart.data.datasets[0].data = data.trend_data;
                attendanceChart.update();
            })
            .catch(err => console.error("Error loading statistics:", err));
    }

    // Load initial stats
    loadDashboardStats();


    // --- Student Management ---
    const registerForm = document.getElementById("register-form");
    const studentsTableBody = document.querySelector("#students-table tbody");
    const captureModal = document.getElementById("capture-modal");
    const modalStudentName = document.getElementById("modal-student-name");
    const registrationFeed = document.getElementById("registration-feed");
    const captureProgressFill = document.getElementById("capture-progress-fill");
    const captureCountText = document.getElementById("capture-count-text");
    const btnCancelCapture = document.getElementById("btn-cancel-capture");

    let captureInterval = null;

    function fetchStudents() {
        fetch("/api/students")
            .then(res => res.json())
            .then(students => {
                studentsTableBody.innerHTML = "";
                if (students.length === 0) {
                    studentsTableBody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No registered students found.</td></tr>`;
                    return;
                }
                students.forEach(s => {
                    const row = document.createElement("tr");
                    row.innerHTML = `
                        <td><strong>#${s.id}</strong></td>
                        <td>${s.name}</td>
                        <td><span class="status-badge pending">${s.image_count} / 40 faces</span></td>
                        <td>${s.created_at ? s.created_at.split(' ')[0] : 'N/A'}</td>
                        <td>
                            <button class="action-icon-btn delete-student-btn" data-id="${s.id}">
                                <i data-lucide="trash-2"></i>
                            </button>
                        </td>
                    `;
                    studentsTableBody.appendChild(row);
                });
                lucide.createIcons();

                // Wire up delete buttons
                document.querySelectorAll(".delete-student-btn").forEach(btn => {
                    btn.addEventListener("click", () => {
                        const sId = btn.getAttribute("data-id");
                        if (confirm(`Are you sure you want to delete student ID ${sId}? All face dataset images will be permanently erased.`)) {
                            deleteStudent(sId);
                        }
                    });
                });
            })
            .catch(err => console.error("Error loading students:", err));
    }

    registerForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const sId = document.getElementById("student-id").value;
        const sName = document.getElementById("student-name").value;

        fetch("/api/students", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: sId, name: sName })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                // Open capture modal
                modalStudentName.textContent = `${sName} (ID: ${sId})`;
                captureModal.classList.remove("hidden");
                
                // Set stream URL
                registrationFeed.src = `/api/camera/register_stream/${sId}`;
                
                // Reset progress
                captureProgressFill.style.width = "0%";
                captureCountText.textContent = "Captured 0 / 40 images";

                // Poll student's image count to show progress
                captureInterval = setInterval(() => {
                    checkCaptureProgress(sId);
                }, 1000);
            } else {
                alert(data.message);
            }
        })
        .catch(err => alert("Registration failed: " + err));
    });

    function checkCaptureProgress(studentId) {
        fetch("/api/students")
            .then(res => res.json())
            .then(students => {
                const s = students.find(x => x.id == studentId);
                if (s) {
                    const count = s.image_count;
                    const pct = Math.min(100, (count / 40) * 100);
                    captureProgressFill.style.width = `${pct}%`;
                    captureCountText.textContent = `Captured ${count} / 40 images`;

                    if (count >= 40) {
                        // Done capturing
                        closeCaptureModal();
                        alert("Face scan completed successfully! Re-train the model to register this face.");
                    }
                }
            })
            .catch(err => console.error("Error polling progress:", err));
    }

    function closeCaptureModal() {
        clearInterval(captureInterval);
        captureModal.classList.add("hidden");
        registrationFeed.removeAttribute("src"); // Stops stream on backend
        fetch("/api/camera/stop", { method: "POST" });
        registerForm.reset();
        fetchStudents();
    }

    btnCancelCapture.addEventListener("click", () => {
        closeCaptureModal();
    });

    function deleteStudent(id) {
        fetch(`/api/students/${id}`, { method: "DELETE" })
            .then(res => res.json())
            .then(data => {
                alert(data.message);
                fetchStudents();
            })
            .catch(err => alert("Deletion failed: " + err));
    }


    // --- Model Training Section ---
    const btnTrainModel = document.getElementById("btn-train-model");
    const trainProgressContainer = document.getElementById("train-progress-container");
    const trainProgressFill = document.getElementById("train-progress-fill");
    const trainStatusMsg = document.getElementById("train-status-msg");
    const trainPercentage = document.getElementById("train-percentage");
    const trainingIconBox = document.getElementById("training-icon-box");
    const trainTitle = document.getElementById("train-title");
    const trainDesc = document.getElementById("train-desc");
    const trainingDetailsCard = document.getElementById("training-details-card");
    const trainingDetailsBody = document.getElementById("training-details-body");

    let trainInterval = null;

    btnTrainModel.addEventListener("click", () => {
        btnTrainModel.disabled = true;
        trainProgressContainer.classList.remove("hidden");
        trainingDetailsCard.classList.add("hidden");
        trainingIconBox.className = "brain-icon-wrapper training";
        trainTitle.textContent = "Model Training Running...";
        trainDesc.textContent = "Compiling image pixels and running LBPH trainer. Please do not close the server.";

        fetch("/api/train", { method: "POST" })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    trainInterval = setInterval(pollTrainingStatus, 800);
                } else {
                    alert(data.message);
                    resetTrainingUI();
                }
            })
            .catch(err => {
                alert("Training failed to start: " + err);
                resetTrainingUI();
            });
    });

    function pollTrainingStatus() {
        fetch("/api/train/status")
            .then(res => res.json())
            .then(data => {
                const prog = data.progress;
                trainProgressFill.style.width = `${prog}%`;
                trainPercentage.textContent = `${prog}%`;
                trainStatusMsg.textContent = data.message;

                if (data.status === "success") {
                    clearInterval(trainInterval);
                    trainTitle.textContent = "Model Status: Trained & Ready";
                    trainDesc.textContent = "Face Recognizer model is fully synchronized and loaded.";
                    trainingIconBox.className = "brain-icon-wrapper idle";
                    trainingIconBox.style.color = "#10b981";
                    trainingIconBox.style.borderColor = "rgba(16, 185, 129, 0.3)";
                    
                    // Display details
                    renderTrainingDetails(data.details);
                    btnTrainModel.disabled = false;
                    trainProgressContainer.classList.add("hidden");
                } else if (data.status === "error") {
                    clearInterval(trainInterval);
                    alert("Training Error: " + data.message);
                    resetTrainingUI();
                }
            })
            .catch(err => console.error("Error polling training status:", err));
    }

    function resetTrainingUI() {
        clearInterval(trainInterval);
        btnTrainModel.disabled = false;
        trainProgressContainer.classList.add("hidden");
        trainingIconBox.className = "brain-icon-wrapper idle";
        trainTitle.textContent = "Model Status: Requires Re-train";
        trainDesc.textContent = "An error occurred during build, or the dataset was modified.";
    }

    function renderTrainingDetails(details) {
        trainingDetailsCard.classList.remove("hidden");
        trainingDetailsBody.innerHTML = `
            <div class="meta-row">
                <span>Unique Profiles Trained:</span>
                <strong>${details.num_students}</strong>
            </div>
            <div class="meta-row">
                <span>Total Samples Compiled:</span>
                <strong>${details.num_images}</strong>
            </div>
            <div style="margin-top: 14px;">
                <span class="verdict-label" style="font-size: 0.7rem;">Student Sample Breakdown</span>
                <ul style="list-style: none; margin-top: 6px; padding: 0;" id="breakdown-list">
                </ul>
            </div>
        `;

        const list = document.getElementById("breakdown-list");
        for (const [name, count] of Object.entries(details.student_breakdown)) {
            const li = document.createElement("li");
            li.style.display = "flex";
            li.style.justify = "space-between";
            li.style.fontSize = "0.85rem";
            li.style.padding = "6px 0";
            li.style.borderBottom = "1px solid rgba(255,255,255,0.02)";
            li.innerHTML = `<span>${name}</span><strong style="color: var(--primary);">${count} images</strong>`;
            list.appendChild(li);
        }
    }


    // --- Live Scanner (Webcam Recognition) Section ---
    const btnStartRec = document.getElementById("btn-start-recognition");
    const btnStopRec = document.getElementById("btn-stop-recognition");
    const webcamFeed = document.getElementById("webcam-feed");
    const videoPlaceholder = document.getElementById("video-placeholder");
    const camPill = document.getElementById("cam-pill");
    const laserLine = document.getElementById("laser-line");

    const stepBlink = document.getElementById("step-blink");
    const blinkSubtext = document.getElementById("blink-subtext");
    const stepMovement = document.getElementById("step-movement");
    const movementSubtext = document.getElementById("movement-subtext");

    const verdictStatus = document.getElementById("verdict-status");
    const livenessInstruction = document.getElementById("liveness-instruction");
    const matchName = document.getElementById("match-name");
    const matchConfidence = document.getElementById("match-confidence");
    const attendanceLogStatus = document.getElementById("attendance-log-status");
    const attIcon = document.getElementById("att-icon");
    const attStatusCard = document.getElementById("att-status-card");

    let recognitionInterval = null;

    btnStartRec.addEventListener("click", () => {
        // Toggle buttons
        btnStartRec.disabled = true;
        btnStopRec.disabled = false;

        // Start Stream
        webcamFeed.src = "/api/camera/stream";
        webcamFeed.classList.remove("hidden");
        videoPlaceholder.classList.add("hidden");
        laserLine.classList.remove("hidden");

        // Set status pill
        camPill.className = "camera-status-pill online";
        camPill.textContent = "Scanning";

        // Poll recognition status
        recognitionInterval = setInterval(pollRecognitionStatus, 500);
    });

    btnStopRec.addEventListener("click", () => {
        stopRecognitionScanner();
    });

    function stopRecognitionScanner() {
        clearInterval(recognitionInterval);
        
        btnStartRec.disabled = false;
        btnStopRec.disabled = true;

        webcamFeed.classList.add("hidden");
        webcamFeed.removeAttribute("src");
        videoPlaceholder.classList.remove("hidden");
        laserLine.classList.add("hidden");

        camPill.className = "camera-status-pill offline";
        camPill.textContent = "Offline";

        // Release camera device on backend
        fetch("/api/camera/stop", { method: "POST" });
        
        resetVerificationUI();
    }

    function resetVerificationUI() {
        stepBlink.className = "ver-step";
        blinkSubtext.textContent = "Waiting for face...";
        stepBlink.querySelector(".step-status").innerHTML = `<i data-lucide="circle-dashed" class="status-spinner spinner"></i>`;

        stepMovement.className = "ver-step";
        movementSubtext.textContent = "Waiting for face...";
        stepMovement.querySelector(".step-status").innerHTML = `<i data-lucide="circle-dashed" class="status-spinner spinner"></i>`;

        verdictStatus.className = "";
        verdictStatus.textContent = "NONE";
        livenessInstruction.textContent = "Please start camera and step in front of the lens.";

        matchName.textContent = "--";
        matchConfidence.textContent = "--";
        
        attendanceLogStatus.textContent = "Not Logged";
        attIcon.className = "att-info-icon";
        attIcon.setAttribute("data-lucide", "info");
        attStatusCard.style.border = "1px solid var(--border-color)";
        lucide.createIcons();
    }

    function pollRecognitionStatus() {
        fetch("/api/camera/status")
            .then(res => res.json())
            .then(data => {
                if (!data.face_detected) {
                    resetVerificationUI();
                    return;
                }

                // 1. Update Match Card
                matchName.textContent = data.name;
                if (data.name !== "Unknown") {
                    const accuracy = Math.max(0, 100 - data.confidence);
                    matchConfidence.textContent = `${accuracy.toFixed(1)}%`;
                } else {
                    matchConfidence.textContent = "N/A";
                }

                // 2. Update Steps UI
                // Step 1: Blink
                if (data.blink_verified) {
                    stepBlink.className = "ver-step verified";
                    blinkSubtext.textContent = "Check completed.";
                    stepBlink.querySelector(".step-status").innerHTML = `<i data-lucide="check-circle" style="color: var(--success)"></i>`;
                } else if (data.liveness_state === "BLINK") {
                    stepBlink.className = "ver-step active";
                    blinkSubtext.textContent = `Blinks: ${data.blink_count}/1`;
                    stepBlink.querySelector(".step-status").innerHTML = `<i data-lucide="circle-dashed" class="status-spinner spinner"></i>`;
                } else {
                    stepBlink.className = "ver-step";
                    blinkSubtext.textContent = "Blink required.";
                    stepBlink.querySelector(".step-status").innerHTML = `<i data-lucide="minus-circle"></i>`;
                }

                // Step 2: Movement
                if (data.movement_verified) {
                    stepMovement.className = "ver-step verified";
                    movementSubtext.textContent = "Check completed.";
                    stepMovement.querySelector(".step-status").innerHTML = `<i data-lucide="check-circle" style="color: var(--success)"></i>`;
                } else if (data.liveness_state === "MOVEMENT") {
                    stepMovement.className = "ver-step active";
                    movementSubtext.textContent = "Awaiting head coordinate shifts...";
                    stepMovement.querySelector(".step-status").innerHTML = `<i data-lucide="circle-dashed" class="status-spinner spinner"></i>`;
                } else {
                    stepMovement.className = "ver-step";
                    movementSubtext.textContent = "Awaiting blink step.";
                    stepMovement.querySelector(".step-status").innerHTML = `<i data-lucide="minus-circle"></i>`;
                }

                // 3. Update Verdict Card
                verdictStatus.textContent = data.liveness_state;
                livenessInstruction.textContent = data.liveness_message;

                if (data.liveness_state === "VERIFIED") {
                    verdictStatus.className = "verified";
                } else if (data.liveness_state === "SPOOF_SUSPECTED") {
                    verdictStatus.className = "spoof";
                } else {
                    verdictStatus.className = "pending";
                }

                // 4. Update Attendance Status Card
                attendanceLogStatus.textContent = data.attendance_status;
                if (data.attendance_status.startsWith("Success")) {
                    attIcon.className = "att-info-icon marked";
                    attIcon.setAttribute("data-lucide", "check-circle");
                    attStatusCard.style.border = "1px solid var(--success)";
                } else if (data.attendance_status.includes("Denied")) {
                    attIcon.className = "att-info-icon";
                    attIcon.setAttribute("data-lucide", "shield-alert");
                    attIcon.style.color = "var(--danger)";
                    attStatusCard.style.border = "1px solid var(--danger)";
                } else {
                    attIcon.className = "att-info-icon";
                    attIcon.setAttribute("data-lucide", "info");
                    attStatusCard.style.border = "1px solid var(--border-color)";
                }
                
                lucide.createIcons();
            })
            .catch(err => console.error("Error polling recognition status:", err));
    }


    // --- Attendance Log Filters & Export ---
    const attendanceTableBody = document.querySelector("#attendance-table tbody");
    const filterDate = document.getElementById("filter-date");
    const filterName = document.getElementById("filter-name");
    const btnApplyFilters = document.getElementById("btn-apply-filters");
    const btnClearFilters = document.getElementById("btn-clear-filters");
    const btnExportCsv = document.getElementById("btn-export-csv");

    function fetchAttendanceLogs(date = '', name = '') {
        const url = `/api/attendance?date=${encodeURIComponent(date)}&name=${encodeURIComponent(name)}`;
        fetch(url)
            .then(res => res.json())
            .then(records => {
                attendanceTableBody.innerHTML = "";
                if (records.length === 0) {
                    attendanceTableBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No attendance records found.</td></tr>`;
                    return;
                }
                records.forEach(r => {
                    let badgeClass = "pending";
                    if (r.liveness_status === "Verified") badgeClass = "verified";
                    else if (r.liveness_status === "SPOOF_SUSPECTED") badgeClass = "spoof";

                    const row = document.createElement("tr");
                    row.innerHTML = `
                        <td><strong>${r.date}</strong></td>
                        <td>${r.time}</td>
                        <td>#${r.student_id ? r.student_id : 'N/A'}</td>
                        <td>${r.student_name}</td>
                        <td><span class="status-badge ${badgeClass}">${r.liveness_status}</span></td>
                        <td><span style="color: var(--success); font-weight: 600;">Present</span></td>
                    `;
                    attendanceTableBody.appendChild(row);
                });
            })
            .catch(err => console.error("Error loading attendance records:", err));
    }

    btnApplyFilters.addEventListener("click", () => {
        fetchAttendanceLogs(filterDate.value, filterName.value);
    });

    btnClearFilters.addEventListener("click", () => {
        filterDate.value = "";
        filterName.value = "";
        fetchAttendanceLogs();
    });

    btnExportCsv.addEventListener("click", () => {
        const date = filterDate.value;
        const name = filterName.value;
        window.location.href = `/api/attendance/export?date=${encodeURIComponent(date)}&name=${encodeURIComponent(name)}`;
    });

});
