/**
 * ScheduleAI — Frontend Application Logic
 * Handles chat messaging, session management, and booking status updates.
 */

// ─── State ──────────────────────────────────────────────────────────────────
let sessionId = generateSessionId();
let isLoading = false;

// ─── DOM Elements ───────────────────────────────────────────────────────────
const messagesContainer = document.getElementById('messagesContainer');
const messagesList = document.getElementById('messagesList');
const welcomeScreen = document.getElementById('welcomeScreen');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const sessionDisplay = document.getElementById('sessionDisplay');
const bookingStatus = document.getElementById('bookingStatus');
const sidebar = document.getElementById('sidebar');

// ─── Init ───────────────────────────────────────────────────────────────────
sessionDisplay.textContent = sessionId;
messageInput.focus();


// ─── Session Management ─────────────────────────────────────────────────────
function generateSessionId() {
    return 'sess_' + Date.now().toString(36) + Math.random().toString(36).substring(2, 8);
}

function newSession() {
    sessionId = generateSessionId();
    sessionDisplay.textContent = sessionId;
    messagesList.innerHTML = '';
    welcomeScreen.classList.remove('hidden');
    resetBookingStatus();
    messageInput.focus();

    // Close sidebar on mobile
    sidebar.classList.remove('open');
    const overlay = document.querySelector('.sidebar-overlay');
    if (overlay) overlay.classList.remove('active');
}


// ─── Messaging ──────────────────────────────────────────────────────────────
async function sendMessage(event) {
    event.preventDefault();

    const message = messageInput.value.trim();
    if (!message || isLoading) return;

    // Hide welcome screen
    welcomeScreen.classList.add('hidden');

    // Add user message
    addMessage('user', message);

    // Clear input
    messageInput.value = '';
    messageInput.style.height = 'auto';

    // Show typing indicator
    const typingEl = showTypingIndicator();

    // Disable input
    setLoading(true);

    try {
        const response = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                message: message,
            }),
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `Server error (${response.status})`);
        }

        const data = await response.json();

        // Remove typing indicator
        typingEl.remove();

        // Add assistant reply
        const assistantMessage = addMessage('assistant', data.reply);

        // Update booking status
        if (data.booking) {
            updateBookingStatus(data.booking);
            addCalendarEventLink(assistantMessage, data.booking.calendar_event_link);
        }

    } catch (error) {
        typingEl.remove();
        addMessage('assistant', `❌ **Error:** ${error.message}\n\nPlease make sure the server is running and try again.`);
    } finally {
        setLoading(false);
        messageInput.focus();
    }
}


function addMessage(role, content) {
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const messageEl = document.createElement('div');
    messageEl.className = `message ${role}`;

    const avatarText = role === 'user' ? 'U' : 'AI';

    // Simple markdown-like formatting
    const formattedContent = formatMessage(content);

    messageEl.innerHTML = `
        <div class="message-avatar">${avatarText}</div>
        <div>
            <div class="message-content">${formattedContent}</div>
            <div class="message-time">${timeStr}</div>
        </div>
    `;

    messagesList.appendChild(messageEl);
    scrollToBottom();
    return messageEl;
}


function formatMessage(text) {
    if (!text) return '';

    // Escape HTML
    let formatted = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // Bold **text**
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Italic *text*
    formatted = formatted.replace(/(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');

    // Inline code `text`
    formatted = formatted.replace(/`(.*?)`/g, '<code style="background:rgba(255,255,255,0.08);padding:2px 6px;border-radius:4px;font-size:0.85em;">$1</code>');

    // Links
    formatted = formatted.replace(
        /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)(?:\s+target="_blank"\s+rel="noopener(?: noreferrer)?"\s+class="calendar-link"&gt;([^&\n]*))?/gi,
        (match, label, href, malformedTail) => {
            const safeUrl = getGoogleCalendarEventUrl(href);
            if (!safeUrl) {
                return malformedTail ? `${label} ${malformedTail}` : label;
            }
            return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="calendar-link">${label} ↗</a>`;
        }
    );

    // Newlines
    formatted = formatted.replace(/\n/g, '<br>');

    return formatted;
}

function getGoogleCalendarEventUrl(value) {
    try {
        const url = new URL(value);
        const isGoogleCalendarHost = [
            'calendar.google.com',
            'www.google.com',
        ].includes(url.hostname);
        if (
            url.protocol !== 'https:' ||
            !isGoogleCalendarHost ||
            !url.pathname.startsWith('/calendar/')
        ) {
            return null;
        }
        return url.href;
    } catch {
        return null;
    }
}

function addCalendarEventLink(messageEl, eventLink) {
    const safeUrl = getGoogleCalendarEventUrl(eventLink);
    if (!safeUrl) return;

    const link = document.createElement('a');
    link.className = 'calendar-link';
    link.href = safeUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open event in Google Calendar ↗';

    const container = document.createElement('div');
    container.className = 'calendar-event-message-link';
    container.appendChild(link);
    messageEl.querySelector('.message-content').appendChild(container);
    scrollToBottom();
}


function showTypingIndicator() {
    const typing = document.createElement('div');
    typing.className = 'typing-indicator';
    typing.innerHTML = `
        <div class="message-avatar" style="background:rgba(255,255,255,0.06);color:var(--accent-primary);border:1px solid var(--border-color);">AI</div>
        <div class="message-content">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;
    messagesList.appendChild(typing);
    scrollToBottom();
    return typing;
}


function scrollToBottom() {
    requestAnimationFrame(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    });
}


function setLoading(state) {
    isLoading = state;
    sendBtn.disabled = state;
    messageInput.disabled = state;
    if (!state) messageInput.focus();
}


// ─── Booking Status ─────────────────────────────────────────────────────────
function updateBookingStatus(booking) {
    if (!booking) return;

    // Check if there's anything meaningful to display
    const hasData = booking.event_title || booking.date || booking.start_time || booking.participants?.length;
    if (!hasData && booking.status === 'pending') return;

    let html = '';

    if (booking.event_title) {
        html += `<div class="booking-detail">
            <span class="booking-label">Title</span>
            <span class="booking-value">${escapeHtml(booking.event_title)}</span>
        </div>`;
    }

    if (booking.start_time) {
        const startDate = new Date(booking.start_time);
        html += `<div class="booking-detail">
            <span class="booking-label">Start</span>
            <span class="booking-value">${startDate.toLocaleString()}</span>
        </div>`;
    }

    if (booking.end_time) {
        const endDate = new Date(booking.end_time);
        html += `<div class="booking-detail">
            <span class="booking-label">End</span>
            <span class="booking-value">${endDate.toLocaleString()}</span>
        </div>`;
    }

    if (booking.participants && booking.participants.length) {
        html += `<div class="booking-detail">
            <span class="booking-label">Attendees</span>
            <span class="booking-value">${booking.participants.map(escapeHtml).join(', ')}</span>
        </div>`;
    }

    if (booking.status) {
        html += `<div class="booking-detail">
            <span class="booking-label">Status</span>
            <span class="booking-value"><span class="status-badge ${booking.status}">${booking.status}</span></span>
        </div>`;
    }

    bookingStatus.innerHTML = html;
    const safeEventUrl = getGoogleCalendarEventUrl(booking.calendar_event_link);
    if (safeEventUrl) {
        const linkContainer = document.createElement('div');
        linkContainer.style.cssText = 'margin-top:10px;text-align:center;';

        const link = document.createElement('a');
        link.href = safeEventUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = 'calendar-link';
        link.textContent = 'View in Google Calendar ↗';

        linkContainer.appendChild(link);
        bookingStatus.appendChild(linkContainer);
    }
}

function resetBookingStatus() {
    bookingStatus.innerHTML = `
        <div class="empty-state-small">
            <p>No active booking yet</p>
            <p class="hint">Start chatting to schedule an appointment</p>
        </div>
    `;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}


// ─── Quick Prompts ──────────────────────────────────────────────────────────
function usePrompt(text) {
    messageInput.value = text;
    messageInput.focus();
    autoResize(messageInput);

    // Close sidebar on mobile
    sidebar.classList.remove('open');
    const overlay = document.querySelector('.sidebar-overlay');
    if (overlay) overlay.classList.remove('active');
}


// ─── UI Helpers ─────────────────────────────────────────────────────────────
function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage(event);
    }
}

function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 150) + 'px';
}

function toggleSidebar() {
    sidebar.classList.toggle('open');

    // Handle overlay
    let overlay = document.querySelector('.sidebar-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay';
        overlay.onclick = () => {
            sidebar.classList.remove('open');
            overlay.classList.remove('active');
        };
        document.body.appendChild(overlay);
    }
    overlay.classList.toggle('active');
}
