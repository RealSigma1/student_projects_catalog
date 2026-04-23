(function () {
    const TOKEN_KEY = "student_projects_access_token";

    function getAccessToken() {
        try {
            return window.localStorage.getItem(TOKEN_KEY) || "";
        } catch (error) {
            return "";
        }
    }

    function setAccessToken(token) {
        if (!token) {
            return;
        }
        try {
            window.localStorage.setItem(TOKEN_KEY, token);
        } catch (error) {
            return;
        }
    }

    function clearAccessToken() {
        try {
            window.localStorage.removeItem(TOKEN_KEY);
        } catch (error) {
            return;
        }
    }

    function buildAuthHeaders(headers) {
        const normalized = new Headers(headers || {});
        const token = getAccessToken();
        if (token && !normalized.has("Authorization")) {
            normalized.set("Authorization", `Bearer ${token}`);
        }
        return normalized;
    }

    async function authFetch(input, init) {
        const options = { ...(init || {}) };
        options.headers = buildAuthHeaders(options.headers);
        const response = await fetch(input, options);
        if (response.status === 401) {
            clearAccessToken();
        }
        return response;
    }

    window.getAccessToken = getAccessToken;
    window.setAccessToken = setAccessToken;
    window.clearAccessToken = clearAccessToken;
    window.authFetch = authFetch;
})();
