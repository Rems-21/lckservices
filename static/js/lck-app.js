/**
 * LCK Services SARL — Interactions dynamiques et calculs côté client (ES6)
 * - Confirmations interactives SweetAlert2
 * - Calcul automatique temps réel du volume en m³ et poids volumétrique aérien
 * - Bascule dynamique des champs Maritime / Aérien
 * - Conversion instantanée multi-devises vers FCFA
 */

document.addEventListener("DOMContentLoaded", () => {
    // 1. Toggle Sidebar sur mobile
    const sidebarToggle = document.getElementById("sidebarToggleBtn");
    const sidebar = document.getElementById("lckSidebar");
    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener("click", () => {
            sidebar.classList.toggle("show");
        });
    }

    // 2. Confirmations interactives SweetAlert2 sur les formulaires sensibles
    document.querySelectorAll("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (e) => {
            if (form.dataset.confirmed === "true") return;
            e.preventDefault();
            const message = form.getAttribute("data-confirm") || "Confirmez-vous cette opération ?";
            const confirmText = form.getAttribute("data-confirm-btn") || "Oui, confirmer";
            if (typeof Swal !== "undefined") {
                Swal.fire({
                    title: "Confirmation requise",
                    text: message,
                    icon: "warning",
                    showCancelButton: true,
                    confirmButtonColor: "#0f2942",
                    cancelButtonColor: "#64748b",
                    confirmButtonText: confirmText,
                    cancelButtonText: "Annuler",
                }).then((result) => {
                    if (result.isConfirmed) {
                        form.dataset.confirmed = "true";
                        form.submit();
                    }
                });
            } else if (window.confirm(message)) {
                form.dataset.confirmed = "true";
                form.submit();
            }
        });
    });

    // 3. Calcul automatique du volume en m³ sur le formulaire Colis (Section 2.4 & 4.2)
    const lengthInput = document.getElementById("id_length_cm");
    const widthInput = document.getElementById("id_width_cm");
    const heightInput = document.getElementById("id_height_cm");
    const qtyInput = document.getElementById("id_quantity");
    const manualVolCheck = document.getElementById("id_manual_volume");
    const volumeInput = document.getElementById("id_volume_cbm");
    const volPreviewBadge = document.getElementById("liveVolumePreview");
    const airWeightBadge = document.getElementById("liveAirWeightPreview");

    const computeVolume = () => {
        if (!volumeInput || !lengthInput || !widthInput || !heightInput) return;
        const isManual = manualVolCheck && manualVolCheck.checked;
        volumeInput.readOnly = !isManual;
        if (!isManual) {
            const l = parseFloat(lengthInput.value) || 0;
            const w = parseFloat(widthInput.value) || 0;
            const h = parseFloat(heightInput.value) || 0;
            const q = Math.max(parseInt(qtyInput ? qtyInput.value : "1", 10) || 1, 1);
            if (l > 0 && w > 0 && h > 0) {
                const cbm = (l * w * h * q) / 1000000.0;
                volumeInput.value = cbm.toFixed(4);
            } else if (!volumeInput.value) {
                volumeInput.value = "0.0000";
            }
        }
        const currentCbm = parseFloat(volumeInput.value) || 0;
        if (volPreviewBadge) {
            volPreviewBadge.textContent = `${currentCbm.toFixed(4)} m³`;
        }
        if (airWeightBadge) {
            const airKg = (currentCbm * 1000000.0) / 6000.0;
            airWeightBadge.textContent = `${airKg.toFixed(2)} kg vol.`;
        }
    };

    if (volumeInput && lengthInput) {
        [lengthInput, widthInput, heightInput, qtyInput].forEach((el) => {
            if (el) el.addEventListener("input", computeVolume);
        });
        if (manualVolCheck) manualVolCheck.addEventListener("change", computeVolume);
        computeVolume();
    }

    // 4. Bascule dynamique des sections Maritime / Aérien sur le formulaire Dossier
    const modeSelect = document.getElementById("id_transport_mode");
    const maritimeSection = document.getElementById("maritimeFieldsBlock");
    const aerienSection = document.getElementById("aerienFieldsBlock");
    const updateTransportFields = () => {
        if (!modeSelect) return;
        const mode = modeSelect.value;
        if (maritimeSection) maritimeSection.style.display = mode === "MARITIME" ? "block" : "none";
        if (aerienSection) aerienSection.style.display = mode === "AERIEN" ? "block" : "none";
    };
    if (modeSelect) {
        modeSelect.addEventListener("change", updateTransportFields);
        updateTransportFields();
    }

    // 5. Conversion multi-devises vers FCFA en direct (Colis & Dépenses)
    const ratesScript = document.getElementById("currenciesRatesData");
    if (ratesScript) {
        let ratesMap = {};
        try {
            ratesMap = JSON.parse(ratesScript.textContent);
        } catch (_) {}

        const currencySelect = document.getElementById("id_currency") || document.getElementById("id_declared_currency");
        const rateInput = document.getElementById("id_exchange_rate");
        const amountInput = document.getElementById("id_amount_original") || document.getElementById("id_declared_value");
        const fcfaPreview = document.getElementById("liveFcfaConverted");

        const refreshFcfaPreview = () => {
            if (!fcfaPreview || !amountInput || !rateInput) return;
            const amt = parseFloat(amountInput.value) || 0;
            const rate = parseFloat(rateInput.value) || 1;
            const converted = Math.round(amt * rate);
            fcfaPreview.textContent = `${converted.toLocaleString("fr-FR")} FCFA`;
        };

        if (currencySelect && rateInput) {
            currencySelect.addEventListener("change", () => {
                const selectedId = currencySelect.value;
                if (ratesMap[selectedId]) {
                    rateInput.value = ratesMap[selectedId];
                    refreshFcfaPreview();
                }
            });
        }
        [amountInput, rateInput].forEach((el) => {
            if (el) el.addEventListener("input", refreshFcfaPreview);
        });
        refreshFcfaPreview();
    }
});
