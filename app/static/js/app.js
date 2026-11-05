const form = document.querySelector("#translateForm");
const submitButton = document.querySelector("#submitButton");
const statusBox = document.querySelector("#statusBox");
const statsGrid = document.querySelector("#statsGrid");
const resultsContainer = document.querySelector("#resultsContainer");
const downloadLink = document.querySelector("#downloadLink");
const pdfInput = document.querySelector("#pdfFile");
const dropzoneLabel = document.querySelector(".dropzone label strong");
const progressWrapper = document.querySelector("#progressWrapper");
const progressBar = document.querySelector("#progressBar");
const progressValue = document.querySelector("#progressValue");
const progressLabel = document.querySelector("#progressLabel");
const previewNote = document.querySelector("#previewNote");

let activePollTimer = null;

const setStatus = (message, type = "info") => {
    if (!statusBox) {
        return;
    }
    statusBox.className = `status-box ${type}`;
    statusBox.textContent = message;
};

const setProgress = (progress, label) => {
    if (!progressWrapper || !progressBar || !progressValue || !progressLabel) {
        return;
    }

    progressWrapper.classList.remove("hidden");
    progressBar.style.width = `${progress}%`;
    progressValue.textContent = `%${progress}`;
    progressLabel.textContent = label;
};

const resetProgress = () => {
    if (!progressWrapper || !progressBar || !progressValue || !progressLabel) {
        return;
    }

    progressWrapper.classList.add("hidden");
    progressBar.style.width = "0%";
    progressValue.textContent = "%0";
    progressLabel.textContent = "Hazirlaniyor";
};

const renderStats = (data = {}) => {
    if (!statsGrid) {
        return;
    }

    const stats = [
        { label: "Dosya", value: data.original_filename || "-" },
        { label: "Sayfa", value: data.page_count || "-" },
        { label: "Kelime", value: data.word_count || "-" },
        { label: "Karakter", value: data.char_count || "-" },
        { label: "Motor", value: data.translation_engine || "Argos Translate" },
        { label: "Tamamlanan", value: data.processed_pages ? `${data.processed_pages}/${data.page_count || "?"}` : "-" },
    ];

    statsGrid.innerHTML = stats
        .map(
            (item) => `
                <article class="stat-card">
                    <span>${item.label}</span>
                    <strong>${item.value}</strong>
                </article>
            `
        )
        .join("");

    statsGrid.classList.remove("hidden");
};

const renderResults = (pages = []) => {
    if (!resultsContainer) {
        return;
    }

    const safePages = Array.isArray(pages) ? pages : [];

    resultsContainer.innerHTML = safePages
        .map(
            (page, index) => `
                <details class="result-card" ${index === 0 ? "open" : ""}>
                    <summary>
                        <span>Sayfa ${page.page}</span>
                        <small>Kaynak ve ceviri metni</small>
                    </summary>
                    <div class="page-columns">
                        <article class="page-panel">
                            <span>Kaynak Metin</span>
                            <p>${escapeHtml(page.source)}</p>
                        </article>
                        <article class="page-panel">
                            <span>Cevrilmis Metin</span>
                            <p>${escapeHtml(page.translated)}</p>
                        </article>
                    </div>
                </details>
            `
        )
        .join("");
};

const clearPolling = () => {
    if (activePollTimer) {
        clearTimeout(activePollTimer);
        activePollTimer = null;
    }
};

const escapeHtml = (unsafe) =>
    String(unsafe ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");

const updateUiFromJob = (job) => {
    if (!job || typeof job !== "object") {
        return;
    }

    renderStats(job);
    setProgress(job.progress || 0, job.message || "Islem suruyor");

    if (job.status === "completed") {
        renderResults(job.preview_pages);

        if (downloadLink && job.download_url) {
            downloadLink.href = job.download_url;
            downloadLink.classList.remove("hidden");
        }

        if (
            previewNote &&
            (job.preview_page_count || 0) > 0 &&
            (job.page_count || 0) > job.preview_page_count
        ) {
            previewNote.textContent = `Hiz icin ilk ${job.preview_page_count} sayfa onizleniyor. Tum ${job.page_count} sayfalik ceviri indirilen PDF dosyasinda yer aliyor.`;
            previewNote.classList.remove("hidden");
        } else if (previewNote && (job.preview_page_count || 0) > 0) {
            previewNote.classList.add("hidden");
        }
    }
};

const pollJob = async (jobId) => {
    try {
        const response = await fetch(`/jobs/${jobId}`);
        const payload = await response.json();

        if (!response.ok || !payload.ok) {
            throw new Error(payload.message || "Ceviri durumu alinamadi.");
        }

        const job = payload?.data;
        if (!job) {
            throw new Error("Ceviri durumu verisi eksik geldi.");
        }
        updateUiFromJob(job);

        if (job.status === "completed") {
            clearPolling();
            setStatus(job.message || "PDF basariyla cevrildi.", "success");
            submitButton.disabled = false;
            submitButton.textContent = "Yeni Ceviri Baslat";
            return;
        }

        if (job.status === "failed") {
            clearPolling();
            setStatus(job.error || job.message || "Ceviri islemi basarisiz oldu.", "error");
            submitButton.disabled = false;
            submitButton.textContent = "Tekrar Dene";
            return;
        }

        setStatus(job.message || "Ceviri devam ediyor...", "loading");
        activePollTimer = window.setTimeout(() => pollJob(jobId), 1800);
    } catch (error) {
        clearPolling();
        setStatus(error.message, "error");
        submitButton.disabled = false;
        submitButton.textContent = "Tekrar Dene";
    }
};

if (pdfInput) {
    pdfInput.addEventListener("change", (event) => {
        const file = event.target.files?.[0];
        dropzoneLabel.textContent = file ? file.name : "PDF dosyasini secin";
    });
}

if (form) {
    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        clearPolling();
        const formData = new FormData(form);
        submitButton.disabled = true;
        submitButton.textContent = "Islem Baslatildi...";
        setStatus("PDF yuklendi. Arka planda islenmek uzere hazirlaniyor...", "loading");
        setProgress(2, "Is kuyruga aliniyor");
        if (statsGrid) {
            statsGrid.classList.add("hidden");
        }
        if (resultsContainer) {
            resultsContainer.innerHTML = "";
        }
        if (downloadLink) {
            downloadLink.classList.add("hidden");
        }
        if (previewNote) {
            previewNote.classList.add("hidden");
        }

        try {
            const response = await fetch("/translate", {
                method: "POST",
                body: formData,
            });
            const payload = await response.json();

            if (!response.ok || !payload.ok) {
                throw new Error(payload.message || "Ceviri islemi basarisiz oldu.");
            }

            setStatus("Ceviri arka planda baslatildi. Ilerleme canli olarak guncelleniyor.", "loading");
            const jobId = payload?.data?.job_id;
            if (!jobId) {
                throw new Error("Is kimligi olusturulamadi.");
            }

            await pollJob(jobId);
        } catch (error) {
            resetProgress();
            setStatus(error.message, "error");
            submitButton.disabled = false;
            submitButton.textContent = "Tekrar Dene";
        }
    });
}
