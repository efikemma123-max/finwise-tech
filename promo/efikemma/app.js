(function () {
    const appIdInput = document.getElementById("deriv-app-id");
    const loginForm = document.getElementById("deriv-login-form");
    const message = document.getElementById("oauth-message");
    const callbackUrl = document.getElementById("callback-url");
    const websiteUrl = document.getElementById("website-url");

    const pageBase = `${window.location.origin}/promo/efikemma/`;
    if (callbackUrl) {
        callbackUrl.textContent = `${pageBase}callback/`;
    }
    if (websiteUrl) {
        websiteUrl.textContent = pageBase;
    }

    const savedAppId = localStorage.getItem("efikemma_deriv_app_id");
    if (appIdInput && savedAppId) {
        appIdInput.value = savedAppId;
    }

    document.querySelectorAll("[data-copy-target]").forEach((button) => {
        button.addEventListener("click", async () => {
            const target = document.getElementById(button.dataset.copyTarget);
            const value = target ? target.textContent.trim() : "";
            if (!value) {
                return;
            }
            try {
                await navigator.clipboard.writeText(value);
                button.textContent = "Copied";
                setTimeout(() => {
                    button.textContent = "Copy";
                }, 1400);
            } catch (error) {
                if (message) {
                    message.textContent = "Copy failed. Select the URL and copy it manually.";
                }
            }
        });
    });

    if (!loginForm || !appIdInput) {
        return;
    }

    loginForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const appId = appIdInput.value.trim();
        if (!appId) {
            message.textContent = "Enter the app ID Deriv gives you after creating the app.";
            appIdInput.focus();
            return;
        }

        localStorage.setItem("efikemma_deriv_app_id", appId);

        const params = new URLSearchParams({
            app_id: appId,
            state: "efikemma-local-test",
        });
        window.location.href = `https://oauth.deriv.com/oauth2/authorize?${params.toString()}`;
    });
})();
