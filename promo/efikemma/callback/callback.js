(function () {
    const status = document.getElementById("callback-status");
    const summary = document.getElementById("callback-summary");
    const accountCount = document.getElementById("account-count");
    const accountsList = document.getElementById("accounts-list");
    const clearButton = document.getElementById("clear-session");
    const targetForm = document.getElementById("finwise-target-form");
    const targetInput = document.getElementById("finwise-target-url");
    const autoConnectMessage = document.getElementById("auto-connect-message");
    const callbackPublicUrl = document.getElementById("callback-public-url");
    const websitePublicUrl = document.getElementById("website-public-url");
    let selectedAccount = null;

    const publicBase = `${window.location.origin}/promo/efikemma/`;
    if (callbackPublicUrl) {
        callbackPublicUrl.textContent = `${publicBase}callback/`;
    }
    if (websitePublicUrl) {
        websitePublicUrl.textContent = publicBase;
    }

    const savedFinwiseUrl = localStorage.getItem("efikemma_finwise_target_url");
    if (targetInput && savedFinwiseUrl) {
        targetInput.value = savedFinwiseUrl;
    }

    function readParams() {
        const params = new URLSearchParams(window.location.search);
        if (window.location.hash && window.location.hash.length > 1) {
            const hashParams = new URLSearchParams(window.location.hash.slice(1));
            hashParams.forEach((value, key) => params.set(key, value));
        }
        return params;
    }

    function collectAccounts(params) {
        const accounts = [];
        params.forEach((value, key) => {
            const match = key.match(/^acct(\d+)$/i);
            if (!match) {
                return;
            }
            const index = match[1];
            accounts.push({
                index,
                account: value,
                token: params.get(`token${index}`) || "",
                currency: (params.get(`cur${index}`) || "").toUpperCase(),
            });
        });
        return accounts.sort((left, right) => Number(left.index) - Number(right.index));
    }

    function maskToken(token) {
        if (!token) {
            return "No token returned";
        }
        if (token.length <= 10) {
            return `${token.slice(0, 2)}...`;
        }
        return `${token.slice(0, 6)}...${token.slice(-4)}`;
    }

    async function copyValue(value, button) {
        try {
            await navigator.clipboard.writeText(value);
            button.textContent = "Copied";
            setTimeout(() => {
                button.textContent = "Copy token";
            }, 1400);
        } catch (error) {
            button.textContent = "Copy failed";
        }
    }

    function buildFinwiseUrl(account) {
        const targetBase = targetInput && targetInput.value.trim()
            ? targetInput.value.trim()
            : "http://localhost:8501/";
        const target = new URL(targetBase);
        target.searchParams.set("deriv_oauth_token", account.token);
        target.searchParams.set("deriv_oauth_account", account.account || "");
        target.searchParams.set("deriv_oauth_currency", account.currency || "");
        target.searchParams.set("deriv_oauth_state", "efikemma-local-test");
        target.searchParams.set("deriv_oauth_auto_connect", "1");
        target.searchParams.set("mdeskmode", "Synthetic Trade");
        target.searchParams.set("mnav", "Synthetic Trade");
        return target.toString();
    }

    function openFinwise(account) {
        if (!account || !account.token) {
            if (autoConnectMessage) {
                autoConnectMessage.textContent = "No Deriv token is available to send to Finwise yet.";
            }
            return;
        }
        if (targetInput) {
            localStorage.setItem("efikemma_finwise_target_url", targetInput.value.trim() || "http://localhost:8501/");
        }
        window.location.href = buildFinwiseUrl(account);
    }

    function renderAccounts(accounts, stateValue) {
        accountCount.textContent = String(accounts.length);
        accountsList.innerHTML = "";

        if (!accounts.length) {
            status.textContent = "No token found";
            summary.textContent = "Open Deriv login from the efikemma setup page, then approve the app to return here.";
            accountsList.innerHTML = [
                '<article class="account-card">',
                "<h3>No Deriv account parameters were found.</h3>",
                "<p>After approval, Deriv should return acct1, token1, and cur1 values in this callback URL.</p>",
                "</article>",
            ].join("");
            return;
        }

        status.textContent = "Authorization received";
        selectedAccount = accounts.find((account) => account.token) || accounts[0];
        summary.textContent = `${accounts.length} Deriv account${accounts.length === 1 ? "" : "s"} returned. Opening Finwise automatically...`;

        localStorage.setItem("efikemma_deriv_oauth_return", JSON.stringify({
            returnedAt: new Date().toISOString(),
            state: stateValue,
            accounts,
        }));

        accounts.forEach((account) => {
            const card = document.createElement("article");
            card.className = "account-card";
            const title = document.createElement("h3");
            title.textContent = account.account || "Deriv account";
            const currency = document.createElement("p");
            currency.append("Currency: ");
            const currencyValue = document.createElement("strong");
            currencyValue.textContent = account.currency || "Unknown";
            currency.append(currencyValue);
            const token = document.createElement("p");
            token.append("Token: ");
            const tokenValue = document.createElement("code");
            tokenValue.textContent = maskToken(account.token);
            token.append(tokenValue);
            card.append(title, currency, token);

            const copyButton = document.createElement("button");
            copyButton.className = "small-button";
            copyButton.type = "button";
            copyButton.textContent = "Copy token";
            copyButton.disabled = !account.token;
            copyButton.addEventListener("click", () => copyValue(account.token, copyButton));
            card.appendChild(copyButton);
            accountsList.appendChild(card);
        });

        if (autoConnectMessage) {
            autoConnectMessage.textContent = `Sending ${selectedAccount.account || "the returned account"} to Finwise in 3 seconds...`;
        }
        window.setTimeout(() => {
            openFinwise(selectedAccount);
        }, 3000);
    }

    if (clearButton) {
        clearButton.addEventListener("click", () => {
            localStorage.removeItem("efikemma_deriv_oauth_return");
            status.textContent = "Saved return cleared";
            summary.textContent = "The local browser copy of the returned Deriv data has been removed.";
        });
    }

    if (targetForm) {
        targetForm.addEventListener("submit", (event) => {
            event.preventDefault();
            openFinwise(selectedAccount);
        });
    }

    const params = readParams();
    renderAccounts(collectAccounts(params), params.get("state") || "");
})();
