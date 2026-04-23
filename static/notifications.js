(function () {
    const BELL_ICON = `
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 4a4 4 0 0 0-4 4v2.1c0 .9-.28 1.78-.8 2.5L5.7 14.6a1 1 0 0 0 .8 1.6h11a1 1 0 0 0 .8-1.6l-1.5-2c-.52-.72-.8-1.6-.8-2.5V8a4 4 0 0 0-4-4Z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M9.5 18a2.5 2.5 0 0 0 5 0" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    `;

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function formatDate(value) {
        if (!value) return "";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ru-RU");
    }

    function itemMarkup(item) {
        return `
            <button
                class="notification-item ${item.is_read ? "" : "is-unread"}"
                type="button"
                data-notification-id="${item.id}"
                data-notification-url="${escapeHtml(item.action_url || "/profile/me")}"
            >
                <div class="notification-item-head">
                    <strong>${escapeHtml(item.title)}</strong>
                    <span>${escapeHtml(formatDate(item.created_at))}</span>
                </div>
                <p>${escapeHtml(item.message)}</p>
            </button>
        `;
    }

    function panelMarkup(state) {
        if (state.error) {
            return `<div class="notification-empty">Не удалось загрузить уведомления.</div>`;
        }
        if (!state.items.length) {
            return `<div class="notification-empty">Новых событий пока нет.</div>`;
        }
        return state.items.map(itemMarkup).join("");
    }

    function getClosestTarget(event, selector) {
        const target = event.target;
        if (!(target instanceof Element)) {
            return null;
        }
        return target.closest(selector);
    }

    function render(state) {
        state.host.innerHTML = `
            <div class="notification-wrap ${state.open ? "is-open" : ""}">
                <button
                    class="notification-trigger"
                    type="button"
                    aria-label="Уведомления"
                    aria-expanded="${state.open ? "true" : "false"}"
                    data-notification-trigger="true"
                >
                    <span class="notification-icon">${BELL_ICON}</span>
                    <span class="notification-label">Уведомления</span>
                    ${state.unreadCount ? `<span class="notification-badge">${Math.min(state.unreadCount, 99)}</span>` : ""}
                </button>
                <section class="notification-panel ${state.open ? "is-visible" : ""}" aria-hidden="${state.open ? "false" : "true"}">
                    <div class="notification-panel-head">
                        <strong>Уведомления</strong>
                        <span class="muted">${state.unreadCount ? `Новых: ${state.unreadCount}` : "Все просмотрено"}</span>
                    </div>
                    <div class="notification-list">${panelMarkup(state)}</div>
                </section>
            </div>
        `;
    }

    function ensureAudio(state) {
        if (state.audioContext || !window.AudioContext) {
            return state.audioContext;
        }
        state.audioContext = new window.AudioContext();
        return state.audioContext;
    }

    async function unlockAudio(state) {
        state.userActivated = true;
        const context = ensureAudio(state);
        if (!context) {
            return;
        }
        if (context.state === "suspended") {
            try {
                await context.resume();
            } catch (error) {
                return;
            }
        }
    }

    function playNotificationSound(state) {
        if (!state.userActivated) {
            return;
        }

        const context = ensureAudio(state);
        if (!context || context.state !== "running") {
            return;
        }

        const oscillator = context.createOscillator();
        const gainNode = context.createGain();

        oscillator.type = "sine";
        oscillator.frequency.setValueAtTime(880, context.currentTime);
        oscillator.frequency.exponentialRampToValueAtTime(660, context.currentTime + 0.18);

        gainNode.gain.setValueAtTime(0.0001, context.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.08, context.currentTime + 0.02);
        gainNode.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.24);

        oscillator.connect(gainNode);
        gainNode.connect(context.destination);

        oscillator.start();
        oscillator.stop(context.currentTime + 0.24);
        state.lastSoundAt = Date.now();
    }

    async function fetchNotifications(state) {
        try {
            const previousUnreadCount = state.unreadCount;
            const request = window.authFetch || window.fetch.bind(window);
            const response = await request("/api/notifications?limit=12");
            if (response.status === 401) {
                state.host.style.display = "none";
                state.disabled = true;
                return;
            }

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.detail || "Failed to load notifications.");
            }

            state.error = "";
            state.items = Array.isArray(data.items) ? data.items : [];
            state.unreadCount = Number(data.unread_count || 0);

            if (state.ready && state.unreadCount > previousUnreadCount) {
                playNotificationSound(state);
            }
            state.ready = true;
        } catch (error) {
            state.error = error instanceof Error ? error.message : "Failed to load notifications.";
        }

        render(state);
    }

    async function markNotificationRead(state, notificationId) {
        const item = state.items.find(entry => entry.id === notificationId);
        if (item && !item.is_read) {
            item.is_read = true;
            state.unreadCount = Math.max(0, state.unreadCount - 1);
            render(state);
        }

        try {
            const request = window.authFetch || window.fetch.bind(window);
            await request(`/api/notifications/${notificationId}/read`, { method: "POST" });
        } catch (error) {
            return;
        }
    }

    window.initNotifications = function initNotifications({ hostId, pollMs = 30000 } = {}) {
        const host = document.getElementById(hostId);
        if (!host) {
            return null;
        }

        const state = {
            host,
            open: false,
            items: [],
            unreadCount: 0,
            error: "",
            disabled: false,
            pollId: null,
            ready: false,
            userActivated: false,
            audioContext: null,
            lastSoundAt: 0,
        };

        host.classList.add("notification-host");
        render(state);

        const unlock = () => unlockAudio(state);
        document.addEventListener("pointerdown", unlock, { passive: true });
        document.addEventListener("keydown", unlock, { passive: true });

        host.addEventListener("click", async (event) => {
            const trigger = getClosestTarget(event, "[data-notification-trigger]");
            if (trigger) {
                event.stopPropagation();
                await unlockAudio(state);
                state.open = !state.open;
                render(state);
                if (state.open && !state.disabled) {
                    await fetchNotifications(state);
                    if (state.unreadCount > 0 && Date.now() - state.lastSoundAt > 600) {
                        playNotificationSound(state);
                    }
                }
                return;
            }

            const item = getClosestTarget(event, "[data-notification-id]");
            if (!item) {
                return;
            }

            event.stopPropagation();
            const notificationId = Number(item.dataset.notificationId);
            const actionUrl = item.dataset.notificationUrl || "/profile/me";
            await markNotificationRead(state, notificationId);
            window.location.href = actionUrl;
        });

        document.addEventListener("click", (event) => {
            if (!state.open || state.disabled) {
                return;
            }
            if (!host.contains(event.target)) {
                state.open = false;
                render(state);
            }
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && state.open) {
                state.open = false;
                render(state);
            }
        });

        fetchNotifications(state);
        state.pollId = window.setInterval(() => {
            if (!state.disabled) {
                fetchNotifications(state);
            }
        }, pollMs);

        return state;
    };
})();
