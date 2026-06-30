// ── Font Awesome ──────────────────────────────────────────────────────────────
if (!document.querySelector('link[href*="font-awesome"]')) {
    const fa = document.createElement('link');
    fa.rel  = 'stylesheet';
    fa.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css';
    document.head.appendChild(fa);
}

const API       = 'http://127.0.0.1:4245';          // local server — scanning & analysis
const DASHBOARD = 'https://guard-mail-ai.vercel.app'; // web dashboard — always Vercel
const HOST = window.location.hostname;

// Inject a comprehensive scoped reset so Gmail and Yahoo page styles
// cannot affect the panel layout, fonts, or spacing in any way.
(function injectPanelStyles() {
    const style = document.createElement('style');
    style.textContent = `
        /* ── Box model: ensure consistent sizing on both platforms ── */
        #guardmail-agent-panel,
        #guardmail-agent-panel * {
            box-sizing:       border-box      !important;
            font-family:      system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
            -webkit-font-smoothing: antialiased !important;
            text-rendering:   optimizeLegibility !important;
            line-height:      1.4             !important;
            letter-spacing:   normal          !important;
            word-spacing:     normal          !important;
            text-transform:   none            !important;
            text-decoration:  none            !important;
            vertical-align:   baseline        !important;
            -webkit-text-size-adjust: 100%    !important;
        }

        /* ── Base text color ── */
        #guardmail-agent-panel { color: #ffffff !important; }

        /* ── Headings — Gmail resets these aggressively ── */
        #guardmail-agent-panel h1,
        #guardmail-agent-panel h2,
        #guardmail-agent-panel h3,
        #guardmail-agent-panel h4 {
            font-size:   inherit !important;
            font-weight: inherit !important;
            margin:      0       !important;
        }

        /* ── Paragraphs and spans ── */
        #guardmail-agent-panel p  { margin: 0 !important; }
        #guardmail-agent-panel ul,
        #guardmail-agent-panel ol { margin: 0 !important; padding: 0 !important; list-style: none !important; }

        /* ── Inputs — Yahoo sets border, padding, and font differently ── */
        #guardmail-agent-panel input,
        #guardmail-agent-panel textarea {
            -webkit-appearance: none !important;
            appearance:         none !important;
            color:              #ffffff   !important;
            background-color:   #0c1323  !important;
            font-size:          14px     !important;
        }
        #guardmail-agent-panel input[type="number"] {
            font-size:   13px   !important;
            font-weight: 700    !important;
            color:       #ffffff !important;
        }
        #guardmail-agent-panel input[type="checkbox"] {
            -webkit-appearance: checkbox !important;
            appearance:         checkbox !important;
            width:   14px !important;
            height:  14px !important;
        }
        #guardmail-agent-panel input::placeholder { color: #475569 !important; opacity: 1 !important; }

        /* ── Buttons ── */
        #guardmail-agent-panel button {
            cursor:      pointer  !important;
            font-family: inherit  !important;
            font-size:   inherit  !important;
            line-height: inherit  !important;
        }

        /* ── Anchor tags ── */
        #guardmail-agent-panel a { color: inherit !important; }

        /* ── Icons — keep FA icon sizing intact ── */
        #guardmail-agent-panel i {
            font-family: 'Font Awesome 6 Free', 'Font Awesome 6 Brands' !important;
            line-height: 1 !important;
            vertical-align: middle !important;
        }
    `;
    document.head.appendChild(style);
})();

// ─────────────────────────────────────────────────────────────────────────────
// Platform ping — tells the dashboard which mail platform is active
// ─────────────────────────────────────────────────────────────────────────────
function pingPlatform() {
    const platform = HOST.includes('mail.yahoo.com') ? 'yahoo'
                   : HOST.includes('mail.google.com') ? 'gmail'
                   : HOST.includes('outlook') ? 'outlook'
                   : null;
    if (!platform) return;
    fetch(`${API}/api/set-platform`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform }),
    }).catch(() => {});
}
pingPlatform();
setInterval(pingPlatform, 20000);

// ─────────────────────────────────────────────────────────────────────────────
// Helper: return inbox rows for the current mail platform
// ─────────────────────────────────────────────────────────────────────────────
function getInboxRows() {
    if (HOST.includes('mail.google.com')) {
        // tr.zA = standard inbox rows; fallback to any clickable table row in the main pane
        let rows = document.querySelectorAll('tr.zA');
        if (rows.length) return Array.from(rows);
        rows = document.querySelectorAll('div[role="main"] tr[jscontroller]');
        if (rows.length) return Array.from(rows);
        rows = document.querySelectorAll('div[role="main"] tr');
        return Array.from(rows).filter(r => r.children.length > 2);
    }
    if (HOST.includes('mail.yahoo.com')) {
        const selectors = [
            '[data-test-id="virtual-list-item"]',
            '[data-test-id="mail-message-item"]',
            'li[data-item-id]',
            'ul[data-test-id="virtual-list"] li',
            '.virtual-list li',
            '.listNode',
            'li.MailListItem',
        ];
        for (const sel of selectors) {
            const rows = document.querySelectorAll(sel);
            if (rows.length) return Array.from(rows);
        }
        // broad fallback: any li inside the main content area that has text
        return Array.from(document.querySelectorAll('main li, [role="main"] li, #app-wrapper li'))
            .filter(li => li.innerText && li.innerText.trim().length > 10);
    }
    if (HOST.includes('outlook')) {
        return Array.from(document.querySelectorAll('[role="option"][aria-label], div.customScrollBar div[role="listitem"]'));
    }
    return [];
}

// ─────────────────────────────────────────────────────────────────────────────
// Helper: extract sender / subject / snippet from an inbox row
// Dispatches by platform so Gmail and Yahoo DOM differences are handled.
// ─────────────────────────────────────────────────────────────────────────────
function extractRowData(row, index = 0) {
    if (HOST.includes('mail.google.com')) {
        return extractGmailRow(row);
    }
    if (HOST.includes('mail.yahoo.com')) {
        return extractYahooRow(row, index);
    }
    // Outlook / generic fallback
    const text = row.innerText || '';
    return { sender: '(unknown)', subject: text.split('\n')[0]?.trim() || '(no subject)', body: text };
}

function extractGmailRow(row) {
    let sender = '';
    const senderEl = row.querySelector('.zF') || row.querySelector('.yX span[email]') || row.querySelector('.yP');
    if (senderEl) {
        const email = senderEl.getAttribute('email');
        const name  = senderEl.innerText.trim();
        sender = email ? `${name} <${email}>` : name;
    }
    let subject = '';
    const subjectEl = row.querySelector('.y6 > span:not(.y2)') || row.querySelector('.bog');
    if (subjectEl) subject = subjectEl.innerText.trim();
    let body = '';
    const snippetEl = row.querySelector('.y2');
    if (snippetEl) body = snippetEl.innerText.trim();
    return { sender: sender || '(unknown)', subject: subject || '(no subject)', body };
}

function extractYahooRow(row, index = 0) {
    // Try data-test-id attributes first (Yahoo's React test IDs)
    let sender = (
        row.querySelector('[data-test-id="senders"]') ||
        row.querySelector('[data-test-id="sender-name"]') ||
        row.querySelector('[class*="Sender"]') ||
        row.querySelector('[class*="sender"]') ||
        row.querySelector('[class*="From"]')
    )?.innerText?.trim() || '';

    let subject = (
        row.querySelector('[data-test-id="subject"]') ||
        row.querySelector('[data-test-id="conversation-subject"]') ||
        row.querySelector('[class*="Subject"]') ||
        row.querySelector('[class*="subject"]') ||
        row.querySelector('[class*="Title"]')
    )?.innerText?.trim() || '';

    let body = (
        row.querySelector('[data-test-id="snippet"]') ||
        row.querySelector('[data-test-id="conversation-snippet"]') ||
        row.querySelector('[class*="Snippet"]') ||
        row.querySelector('[class*="snippet"]') ||
        row.querySelector('[class*="Preview"]') ||
        row.querySelector('[class*="preview"]')
    )?.innerText?.trim() || '';

    // Split the row's raw text into lines and guess structure
    // Filter out timestamps so they don't end up as sender/subject
    const isTimestamp = t => /^\d{1,2}:\d{2}(\s?(AM|PM))?$|^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}$|^\d{1,2}\/\d{1,2}(\/\d{2,4})?$/.test(t.trim());
    const lines = (row.innerText || '').split('\n').map(l => l.trim()).filter(l => l && !isTimestamp(l));
    if (!sender && lines.length >= 1) sender = lines[0];

    // If no subject yet, find bold/semibold spans (Yahoo bolds unread subjects)
    if (!subject) {
        const spans = Array.from(row.querySelectorAll('span, div')).filter(el => {
            const style = window.getComputedStyle(el);
            const fw = parseInt(style.fontWeight) || 400;
            const txt = el.innerText?.trim() || '';
            return fw >= 600 && txt.length > 3 && txt.length < 120 && !isTimestamp(txt);
        });
        if (spans.length) subject = spans[0].innerText.trim();
    }

    // Final fallback: use raw lines
    if (!subject && lines.length >= 2) {
        const candidate = lines.find((l, idx) => idx > 0 && !isTimestamp(l) && l !== sender);
        if (candidate) subject = candidate;
    }
    if (!body && lines.length >= 3) body = lines.slice(2).join(' ');

    // Append index so the server MD5 hash is unique per row even if text matches
    const uniqueTag = `[row:${index}]`;
    return {
        sender:  sender  || `(yahoo-sender-${index})`,
        subject: subject || `(yahoo-subject-${index})`,
        body:    body ? `${body} ${uniqueTag}` : uniqueTag,
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// 1. Single-email Scan Button
// ─────────────────────────────────────────────────────────────────────────────
const scanButton = document.createElement('div');
scanButton.innerHTML = `<i class="fas fa-shield-halved"></i> Audit Email`;
Object.assign(scanButton.style, {
    position: 'fixed', bottom: '30px', right: '30px', zIndex: '999999',
    background: 'linear-gradient(135deg,#4f46e5,#6366f1)',
    color: '#fff', padding: '12px 20px', borderRadius: '9999px',
    cursor: 'pointer', fontFamily: 'system-ui,-apple-system,sans-serif',
    fontSize: '13px', fontWeight: '700',
    boxShadow: '0 10px 30px -5px rgba(79,70,229,0.6)',
    transition: 'all 0.3s cubic-bezier(0.4,0,0.2,1)',
    display: 'flex', alignItems: 'center', gap: '8px', letterSpacing: '0.5px',
});
scanButton.onmouseenter = () => {
    scanButton.style.transform = 'translateY(-3px) scale(1.02)';
    scanButton.style.boxShadow = '0 20px 40px -6px rgba(99,102,241,0.7)';
};
scanButton.onmouseleave = () => {
    scanButton.style.transform = '';
    scanButton.style.boxShadow = '0 10px 30px -5px rgba(79,70,229,0.6)';
};
document.body.appendChild(scanButton);

scanButton.addEventListener('click', function () {
    let subjectNode, bodyNode, senderElement;
    let senderAddress = 'unknown-sender@domain.com';
    const host = window.location.hostname;

    if (host.includes('mail.google.com')) {
        subjectNode   = document.querySelector('h2.hP');
        bodyNode      = document.querySelector('div.a3s.aiL');
        senderElement = document.querySelector('.gD');
        if (senderElement)
            senderAddress = senderElement.innerText + ' <' + (senderElement.getAttribute('email') || '') + '>';
    } else if (host.includes('mail.yahoo.com')) {
        subjectNode   = document.querySelector('[data-test-id="message-group-subject"]');
        bodyNode      = document.querySelector('[data-test-id="message-view-body"]') || document.querySelector('.msg-body');
        senderElement = document.querySelector('[data-test-id="message-from"]');
        if (senderElement) senderAddress = senderElement.innerText;
    } else if (host.includes('outlook')) {
        subjectNode   = document.querySelector('[aria-label="Subject"]') || document.querySelector('.ms-fui-Label');
        bodyNode      = document.querySelector('div[aria-label="Message body"]') || document.querySelector('.BodyFragment');
        senderElement = Array.from(document.querySelectorAll('span')).find(el => el.innerText && el.innerText.includes('@'));
        if (senderElement) senderAddress = senderElement.innerText;
    }

    if (!bodyNode) {
        const fallback = Array.from(document.querySelectorAll('div'))
            .filter(d => d.innerText.length > 50)
            .sort((a, b) => b.innerText.length - a.innerText.length);
        if (fallback.length) bodyNode = fallback[0];
    }

    if (!bodyNode) {
        alert('GuardMail AI: Please open an individual email before initiating a security audit.');
        return;
    }

    const payload = {
        sender:  senderAddress.trim(),
        subject: subjectNode ? subjectNode.innerText : '(No Subject)',
        body:    bodyNode.innerText.trim(),
    };

    scanButton.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Analyzing…`;
    scanButton.style.background = '#1e1b4b';

    fetch(`${API}/api/analyze-ext`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    })
    .then(r => r.json())
    .then(data => {
        scanButton.innerHTML = `<i class="fa-solid fa-square-check"></i> Synchronized`;
        scanButton.style.background = '#064e3b';

        document.getElementById('guardmail-live-ribbon')?.remove();
        const target = bodyNode.parentElement || document.body;
        if (target) {
            const ribbon = document.createElement('div');
            ribbon.id = 'guardmail-live-ribbon';
            Object.assign(ribbon.style, {
                width: '100%', padding: '16px', marginTop: '12px', marginBottom: '12px',
                borderRadius: '14px', fontFamily: 'system-ui,-apple-system,sans-serif',
                boxSizing: 'border-box', display: 'flex', alignItems: 'center',
                justifyContent: 'space-between', gap: '16px', zIndex: '9999',
            });
            let bg, border, text, icon, copy;
            const reasoning = data.threat_reasoning || '';
            if (data.risk_score >= 75) {
                bg = '#4c0519'; border = '2px solid #f43f5e'; text = '#fda4af';
                icon = '<i class="fa-solid fa-shield-virus" style="color:#f43f5e;font-size:22px;"></i>';
                copy = `<strong>CRITICAL RISK (${data.risk_score}%):</strong> High-risk indicators detected. ${data.spoofing_detected ? '⚠️ Brand spoofing detected!' : ''} Avoid clicking links.`;
            } else if (data.assigned_category === 'Spam' || data.risk_score >= 40) {
                bg = '#451a03'; border = '1px solid #d97706'; text = '#fef3c7';
                icon = '<i class="fa-solid fa-triangle-exclamation" style="color:#f59e0b;font-size:18px;"></i>';
                copy = `<strong>SPAM DETECTED (${data.risk_score}%):</strong> Isolated as bulk/promotional content.`;
            } else {
                bg = '#022c22'; border = '1px solid #059669'; text = '#d1fae5';
                icon = '<i class="fa-solid fa-circle-check" style="color:#34d399;font-size:18px;"></i>';
                copy = `<strong>SAFE (${data.risk_score}%):</strong> Normal communication — category: <b>${data.assigned_category}</b>.`;
            }
            Object.assign(ribbon.style, {
                backgroundColor: bg, border, color: text,
                flexDirection: 'column', alignItems: 'flex-start',
            });
            ribbon.innerHTML = `
                <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;width:100%;">
                    <div style="display:flex;align-items:center;gap:12px;">
                        ${icon}
                        <span style="font-size:13px;line-height:1.5;">${copy}</span>
                    </div>
                    <a href="${DASHBOARD}" target="_blank"
                       style="background:#4f46e5;color:#fff;font-weight:800;font-size:11px;padding:8px 14px;
                              border-radius:10px;text-decoration:none;text-transform:uppercase;
                              letter-spacing:0.5px;white-space:nowrap;flex-shrink:0;">
                        Inspect
                    </a>
                </div>
                ${reasoning ? `
                <div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.08);
                             font-size:11.5px;color:rgba(255,255,255,0.6);line-height:1.6;width:100%;">
                    <span style="font-weight:700;color:rgba(255,255,255,0.4);font-size:10px;
                                 text-transform:uppercase;letter-spacing:0.6px;">Why flagged · </span>${reasoning}
                </div>` : ''}`;
            target.insertBefore(ribbon, target.firstChild);
        }
        setTimeout(() => {
            scanButton.innerHTML = `<i class="fas fa-shield-halved"></i> Audit Email`;
            scanButton.style.background = 'linear-gradient(135deg,#4f46e5,#6366f1)';
        }, 3000);
    })
    .catch(() => {
        alert(`Connection Failure: Ensure GuardMail AI is running at ${API}`);
        scanButton.innerHTML = `<i class="fas fa-shield-halved"></i> Audit Email`;
        scanButton.style.background = 'linear-gradient(135deg,#4f46e5,#6366f1)';
    });
});


// ─────────────────────────────────────────────────────────────────────────────
// 2. AI Agent Button
// ─────────────────────────────────────────────────────────────────────────────
const agentButton = document.createElement('div');
agentButton.innerHTML = `<i class="fas fa-robot"></i> AI Agent`;
Object.assign(agentButton.style, {
    position: 'fixed', bottom: '88px', right: '30px', zIndex: '999999',
    background: 'linear-gradient(135deg,#7c3aed,#a855f7)',
    color: '#fff', padding: '12px 20px', borderRadius: '9999px',
    cursor: 'pointer', fontFamily: 'system-ui,-apple-system,sans-serif',
    fontSize: '13px', fontWeight: '700',
    boxShadow: '0 10px 30px -5px rgba(124,58,237,0.6)',
    transition: 'all 0.3s cubic-bezier(0.4,0,0.2,1)',
    display: 'flex', alignItems: 'center', gap: '8px', letterSpacing: '0.5px',
});
agentButton.onmouseenter = () => {
    agentButton.style.transform = 'translateY(-3px) scale(1.02)';
    agentButton.style.boxShadow = '0 20px 40px -6px rgba(168,85,247,0.7)';
};
agentButton.onmouseleave = () => {
    agentButton.style.transform = '';
    agentButton.style.boxShadow = '0 10px 30px -5px rgba(124,58,237,0.6)';
};
document.body.appendChild(agentButton);

agentButton.addEventListener('click', () => {
    const existing = document.getElementById('guardmail-agent-panel');
    if (existing) { existing.remove(); return; }
    buildAgentPanel();
});


// ─────────────────────────────────────────────────────────────────────────────
// 3. Agent Panel builder
// ─────────────────────────────────────────────────────────────────────────────
function getPlatformMeta() {
    if (HOST.includes('mail.yahoo.com')) return {
        name:       'Yahoo Mail',
        icon:       '<i class="fa-brands fa-yahoo" style="font-size:13px;"></i>',
        accent:     '#7c3aed',
        accentSoft: 'rgba(124,58,237,.18)',
        border:     'rgba(124,58,237,.35)',
        badgeBg:    'rgba(168,85,247,.12)',
        badgeBorder:'rgba(168,85,247,.3)',
        badgeText:  '#c084fc',
        barGrad:    'linear-gradient(90deg,#7c3aed,#a855f7)',
    };
    if (HOST.includes('mail.google.com')) return {
        name:       'Gmail',
        icon:       '<i class="fa-brands fa-google" style="font-size:13px;"></i>',
        accent:     '#4f46e5',
        accentSoft: 'rgba(79,70,229,.18)',
        border:     'rgba(99,102,241,.35)',
        badgeBg:    'rgba(239,68,68,.1)',
        badgeBorder:'rgba(239,68,68,.3)',
        badgeText:  '#f87171',
        barGrad:    'linear-gradient(90deg,#4f46e5,#818cf8)',
    };
    return {
        name:       'Mail',
        icon:       '<i class="fas fa-envelope" style="font-size:13px;"></i>',
        accent:     '#0891b2',
        accentSoft: 'rgba(8,145,178,.18)',
        border:     'rgba(8,145,178,.35)',
        badgeBg:    'rgba(8,145,178,.1)',
        badgeBorder:'rgba(8,145,178,.3)',
        badgeText:  '#67e8f9',
        barGrad:    'linear-gradient(90deg,#0891b2,#06b6d4)',
    };
}

function buildAgentPanel() {
    const pm = getPlatformMeta();
    const panel = document.createElement('div');
    panel.id = 'guardmail-agent-panel';
    Object.assign(panel.style, {
        position: 'fixed', bottom: '148px', right: '30px', zIndex: '999998',
        width: '380px', background: '#080e1a',
        border: `1px solid ${pm.border}`,
        borderRadius: '24px',
        fontFamily: 'system-ui,-apple-system,sans-serif',
        boxShadow: `0 30px 80px -10px rgba(0,0,0,0.85), 0 0 0 1px rgba(255,255,255,0.03)`,
        overflow: 'hidden',
        backdropFilter: 'blur(20px)',
    });

    panel.innerHTML = `
        <!-- Header -->
        <div style="background:linear-gradient(135deg,${pm.accentSoft},rgba(15,23,42,.6));border-bottom:1px solid ${pm.border};padding:18px 20px;display:flex;align-items:center;gap:14px;">
            <div style="background:linear-gradient(135deg,${pm.accent},${pm.accent}cc);padding:11px;border-radius:14px;box-shadow:0 6px 20px ${pm.accent}55;flex-shrink:0;">
                <i class="fas fa-robot" style="color:#fff;font-size:17px;"></i>
            </div>
            <div style="flex:1;min-width:0;">
                <div style="font-weight:800;font-size:15px;color:#fff;letter-spacing:-.2px;">GuardMail <span style="color:${pm.badgeText};">AI Agent</span></div>
                <div style="font-size:10px;color:#475569;font-weight:600;text-transform:uppercase;letter-spacing:.9px;margin-top:1px;">Autonomous Inbox Auditor</div>
            </div>
            <!-- Platform badge -->
            <div style="display:flex;align-items:center;gap:6px;background:${pm.badgeBg};border:1px solid ${pm.badgeBorder};border-radius:999px;padding:5px 10px;color:${pm.badgeText};font-size:11px;font-weight:700;white-space:nowrap;flex-shrink:0;">
                ${pm.icon}
                <span>${pm.name}</span>
            </div>
            <button id="gm-close-btn" style="margin-left:4px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:8px;cursor:pointer;color:#64748b;font-size:13px;padding:6px 8px;transition:all .2s;flex-shrink:0;">
                <i class="fas fa-xmark"></i>
            </button>
        </div>

        <!-- Question screen -->
        <div id="gm-agent-question" style="padding:20px;">

            <!-- Platform source info bar -->
            <div style="display:flex;align-items:center;gap:10px;background:${pm.badgeBg};border:1px solid ${pm.badgeBorder};border-radius:14px;padding:12px 14px;margin-bottom:16px;">
                <div style="width:32px;height:32px;border-radius:10px;background:${pm.accentSoft};display:flex;align-items:center;justify-content:center;color:${pm.badgeText};font-size:14px;flex-shrink:0;">
                    ${pm.icon}
                </div>
                <div>
                    <div style="font-size:12px;font-weight:700;color:#e2e8f0;">Scanning <span style="color:${pm.badgeText};">${pm.name}</span></div>
                    <div style="font-size:11px;color:#64748b;margin-top:1px;">Classifying threats · Detecting spoofing · Reporting to dashboard</div>
                </div>
            </div>

            <label style="display:block;font-size:12px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.7px;margin-bottom:8px;">
                Emails to audit
            </label>
            <input id="gm-agent-input" type="text" placeholder='Enter a number or type "all"'
                   style="width:100%;box-sizing:border-box;background:#0c1323;border:1.5px solid #1e293b;border-radius:12px;padding:12px 15px;font-size:14px;color:#fff;font-family:monospace;outline:none;transition:border-color .2s,box-shadow .2s;" />
            <div style="font-size:11px;color:#334155;margin-top:7px;font-weight:500;">
                Type <span style="color:${pm.badgeText};font-family:monospace;font-weight:700;">all</span> to audit every visible email in your inbox
            </div>

            <!-- Smarter scanning options -->
            <div style="margin-top:14px;display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                <div style="background:#0c1323;border:1.5px solid #1e293b;border-radius:12px;padding:10px 12px;">
                    <label style="display:block;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.7px;margin-bottom:6px;">
                        Min Risk Threshold
                    </label>
                    <div style="display:flex;align-items:center;gap:6px;">
                        <input id="gm-threshold-input" type="number" min="0" max="100" value="${localStorage.getItem('gm_threshold') || 0}"
                               style="width:52px;background:transparent;border:none;color:#fff;font-size:13px;font-family:monospace;font-weight:700;outline:none;" />
                        <span style="font-size:11px;color:#475569;">/ 100</span>
                    </div>
                    <div style="font-size:10px;color:#334155;margin-top:3px;">Only send to dashboard if risk ≥ this</div>
                </div>
                <div style="background:#0c1323;border:1.5px solid #1e293b;border-radius:12px;padding:10px 12px;">
                    <label style="display:block;font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.7px;margin-bottom:6px;">
                        Skip Already Seen
                    </label>
                    <div style="display:flex;align-items:center;gap:8px;margin-top:4px;">
                        <input id="gm-skip-seen" type="checkbox" ${localStorage.getItem('gm_skip_seen') === 'true' ? 'checked' : ''}
                               style="width:14px;height:14px;accent-color:${pm.accent};cursor:pointer;" />
                        <span style="font-size:11px;color:#94a3b8;">Skip emails scanned before</span>
                    </div>
                    <div style="font-size:10px;color:#334155;margin-top:5px;">Uses local memory across sessions</div>
                </div>
            </div>

            <button id="gm-launch-btn"
                    style="margin-top:14px;width:100%;background:linear-gradient(135deg,${pm.accent},${pm.accent}bb);color:#fff;font-weight:800;font-size:13px;padding:13px;border-radius:14px;border:none;cursor:pointer;box-shadow:0 6px 20px ${pm.accent}44;letter-spacing:.4px;display:flex;align-items:center;justify-content:center;gap:8px;transition:opacity .2s;">
                <i class="fas fa-bolt"></i> Deploy Agent on ${pm.name}
            </button>
        </div>

        <!-- Progress screen -->
        <div id="gm-agent-progress" style="padding:20px;display:none;">

            <!-- Status row -->
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;padding:14px;background:rgba(255,255,255,.02);border:1px solid #1e293b;border-radius:16px;">
                <div id="gm-status-icon" style="width:40px;height:40px;border-radius:12px;background:${pm.accentSoft};display:flex;align-items:center;justify-content:center;flex-shrink:0;">
                    <i class="fa-solid fa-circle-notch fa-spin" style="color:${pm.badgeText};font-size:15px;"></i>
                </div>
                <div style="flex:1;min-width:0;">
                    <div id="gm-status-text" style="font-size:13px;font-weight:700;color:#fff;">Reading inbox…</div>
                    <div id="gm-sub-text" style="font-size:11px;color:#475569;font-family:monospace;margin-top:2px;">Starting agent</div>
                </div>
                <!-- Live platform badge -->
                <div style="display:flex;align-items:center;gap:5px;background:${pm.badgeBg};border:1px solid ${pm.badgeBorder};border-radius:999px;padding:4px 9px;color:${pm.badgeText};font-size:10px;font-weight:700;flex-shrink:0;">
                    ${pm.icon} ${pm.name}
                </div>
            </div>

            <!-- Progress bar -->
            <div style="position:relative;background:#0f172a;border-radius:999px;height:7px;overflow:hidden;margin-bottom:16px;">
                <div id="gm-agent-bar" style="height:7px;background:${pm.barGrad};border-radius:999px;width:0%;transition:width .4s cubic-bezier(.4,0,.2,1);box-shadow:0 0 12px ${pm.accent}88;"></div>
            </div>

            <!-- Stats grid -->
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:14px;">
                <div style="background:rgba(255,255,255,.03);border:1px solid #1e293b;border-radius:14px;padding:12px 8px;text-align:center;">
                    <div id="gm-stat-audited" style="font-size:22px;font-weight:900;color:#fff;font-family:monospace;line-height:1;">0</div>
                    <div style="font-size:9px;color:#475569;font-weight:700;text-transform:uppercase;letter-spacing:.7px;margin-top:4px;">Audited</div>
                </div>
                <div style="background:rgba(244,63,94,.06);border:1px solid rgba(244,63,94,.2);border-radius:14px;padding:12px 8px;text-align:center;">
                    <div id="gm-stat-spoofed" style="font-size:22px;font-weight:900;color:#fb7185;font-family:monospace;line-height:1;">0</div>
                    <div style="font-size:9px;color:#475569;font-weight:700;text-transform:uppercase;letter-spacing:.7px;margin-top:4px;">Spoofed</div>
                </div>
                <div style="background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.2);border-radius:14px;padding:12px 8px;text-align:center;">
                    <div id="gm-stat-soc" style="font-size:22px;font-weight:900;color:#fbbf24;font-family:monospace;line-height:1;">0</div>
                    <div style="font-size:9px;color:#475569;font-weight:700;text-transform:uppercase;letter-spacing:.7px;margin-top:4px;">SOC Cases</div>
                </div>
            </div>

            <!-- Live terminal log -->
            <div style="position:relative;">
                <div style="position:absolute;top:0;left:0;right:0;height:28px;background:linear-gradient(180deg,#04080f,transparent);border-radius:12px 12px 0 0;z-index:1;pointer-events:none;display:flex;align-items:center;padding:0 12px;gap:6px;">
                    <span style="width:7px;height:7px;border-radius:50%;background:#f43f5e;display:inline-block;"></span>
                    <span style="width:7px;height:7px;border-radius:50%;background:#fbbf24;display:inline-block;"></span>
                    <span style="width:7px;height:7px;border-radius:50%;background:#34d399;display:inline-block;"></span>
                    <span style="font-size:9px;color:#334155;font-family:monospace;margin-left:4px;">agent.log</span>
                </div>
                <div id="gm-agent-log"
                     style="background:#04080f;border:1px solid #0f172a;border-radius:14px;padding:30px 12px 10px;height:130px;overflow-y:auto;font-family:'Courier New',monospace;font-size:11px;line-height:1.7;"></div>
            </div>

            <a id="gm-done-btn" href="${API}" target="_blank"
               style="display:none;margin-top:14px;box-sizing:border-box;width:100%;background:linear-gradient(135deg,#059669,#10b981);color:#fff;font-weight:800;font-size:13px;padding:13px;border-radius:14px;text-align:center;text-decoration:none;letter-spacing:.4px;box-shadow:0 6px 20px rgba(5,150,105,.35);">
                <i class="fas fa-circle-check"></i> Done — Open Dashboard
            </a>
        </div>
    `;

    document.body.appendChild(panel);

    panel.querySelector('#gm-close-btn').addEventListener('click', () => panel.remove());

    const input     = panel.querySelector('#gm-agent-input');
    const launchBtn = panel.querySelector('#gm-launch-btn');

    input.addEventListener('focus', () => {
        input.style.borderColor = pm.accent;
        input.style.boxShadow = `0 0 0 3px ${pm.accentSoft}`;
    });
    input.addEventListener('blur', () => {
        input.style.borderColor = '#1e293b';
        input.style.boxShadow = 'none';
    });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') startAgent(input, panel); });
    launchBtn.addEventListener('click', () => startAgent(input, panel));
    launchBtn.addEventListener('mouseenter', () => { launchBtn.style.opacity = '.85'; });
    launchBtn.addEventListener('mouseleave', () => { launchBtn.style.opacity = '1'; });

    setTimeout(() => input.focus(), 100);
}


// ─────────────────────────────────────────────────────────────────────────────
// 4. Agent execution — reads Gmail DOM rows newest-first, calls analyze-ext
// ─────────────────────────────────────────────────────────────────────────────
async function startAgent(input, panel) {
    const raw = input.value.trim().toLowerCase();
    if (!raw) { input.focus(); return; }

    // Read smarter scanning settings
    const thresholdInput = panel.querySelector('#gm-threshold-input');
    const skipSeenInput  = panel.querySelector('#gm-skip-seen');
    const threshold = parseInt(thresholdInput?.value || '0') || 0;
    const skipSeen  = skipSeenInput?.checked || false;
    localStorage.setItem('gm_threshold', threshold);
    localStorage.setItem('gm_skip_seen', skipSeen);

    // Cross-session scan memory: Set of "sender|||subject" keys
    const MEMORY_KEY = 'gm_seen_emails';
    const seenSet = new Set(JSON.parse(localStorage.getItem(MEMORY_KEY) || '[]'));

    const allRows = getInboxRows();
    if (allRows.length === 0) {
        alert('GuardMail AI Agent: No email rows found. Make sure you are viewing your inbox.');
        return;
    }

    const limit = (raw === 'all') ? allRows.length : Math.min(parseInt(raw) || 10, allRows.length);
    const rows  = allRows.slice(0, limit);

    // Switch to progress view
    panel.querySelector('#gm-agent-question').style.display  = 'none';
    panel.querySelector('#gm-agent-progress').style.display  = 'block';

    const logEl     = panel.querySelector('#gm-agent-log');
    const barEl     = panel.querySelector('#gm-agent-bar');
    const auditedEl = panel.querySelector('#gm-stat-audited');
    const spoofedEl = panel.querySelector('#gm-stat-spoofed');
    const socEl     = panel.querySelector('#gm-stat-soc');
    const statusEl  = panel.querySelector('#gm-status-text');
    const subEl     = panel.querySelector('#gm-sub-text');
    const iconEl    = panel.querySelector('#gm-status-icon');
    const doneBtn   = panel.querySelector('#gm-done-btn');

    function log(msg, color = '#94a3b8') {
        const p = document.createElement('p');
        Object.assign(p.style, { margin: '0', color });
        p.textContent = msg;
        logEl.appendChild(p);
        logEl.scrollTop = logEl.scrollHeight;
    }

    const pm = getPlatformMeta();
    statusEl.textContent = `Auditing ${rows.length} email${rows.length !== 1 ? 's' : ''} from ${pm.name}…`;
    log(`› Agent online — ${pm.name} · ${rows.length} emails queued`, pm.badgeText);

    let audited = 0, spoofed = 0, soc = 0;

    for (let i = 0; i < rows.length; i++) {
        const { sender, subject, body } = extractRowData(rows[i], i);
        const memKey = (sender + '|||' + subject).toLowerCase().trim();

        // Cross-session memory: skip if already scanned in a previous session
        if (skipSeen && seenSet.has(memKey)) {
            const pct = Math.round(((i + 1) / rows.length) * 100);
            barEl.style.width = pct + '%';
            subEl.textContent = `${audited} / ${rows.length}  (${pct}%)`;
            log(`↷ Skipped (seen before): ${sender.slice(0, 36)}`, '#334155');
            continue;
        }

        try {
            const res  = await fetch(`${API}/api/analyze-ext`, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ sender, subject, body }),
            });
            const data = await res.json();

            // Server couldn't extract real data from this row — skip silently
            if (data.skipped) {
                const pct = Math.round(((i + 1) / rows.length) * 100);
                barEl.style.width = pct + '%';
                subEl.textContent = `${audited} / ${rows.length}  (${pct}%)`;
                continue;
            }

            // Mark as seen in local memory
            seenSet.add(memKey);

            audited++;
            if (data.spoofing_detected) spoofed++;
            if (data.risk_score >= 75 || data.spoofing_detected) soc++;
            if (data.evicted_id) log(`⟳ Oldest email evicted (cap: 250)`, '#475569');

            // Threshold filter: count toward audited but don't push to dashboard if below threshold
            const belowThreshold = threshold > 0 && data.risk_score < threshold;

            const pct = Math.round((audited / rows.length) * 100);
            const cat = data.assigned_category || data.initial_category || 'Analyzed';
            const conf = data.confidence ? ` · ${data.confidence.score}% conf` : '';
            const color = cat === 'Scam Alert' ? '#f87171'
                        : cat === 'Spam'       ? '#fbbf24'
                        : cat === 'Safe'       ? '#34d399'
                        : '#94a3b8';

            const hasSubject = subject && subject !== '(no subject)' && !subject.startsWith('(yahoo-subject-');
            const label = hasSubject ? subject.slice(0, 40) : sender.replace(/<[^>]+>/, '').trim().slice(0, 40);
            const thresholdNote = belowThreshold ? ' [below threshold]' : '';

            barEl.style.width      = pct + '%';
            auditedEl.textContent  = audited;
            spoofedEl.textContent  = spoofed;
            socEl.textContent      = soc;
            subEl.textContent      = `${audited} / ${rows.length}  (${pct}%)`;
            log(`✓ [${cat}${conf}] ${label}${thresholdNote}`, belowThreshold ? '#334155' : color);

            // Warn if previously Safe emails from same domain may now be suspect
            if (data.rescan_candidates && data.rescan_candidates.length > 0) {
                log(`⚠ ${data.rescan_candidates.length} previously Safe email(s) from this domain may need review`, '#f59e0b');
            }

        } catch (err) {
            audited++;
            log(`✗ Failed: ${subject.slice(0, 40)}`, '#f43f5e');
            barEl.style.width     = Math.round((audited / rows.length) * 100) + '%';
            auditedEl.textContent = audited;
            subEl.textContent     = `${audited} / ${rows.length}`;
        }
    }

    // Persist updated scan memory to localStorage
    localStorage.setItem(MEMORY_KEY, JSON.stringify([...seenSet].slice(-500)));

    // Done
    iconEl.innerHTML      = '<i class="fa-solid fa-circle-check" style="color:#34d399;font-size:14px;"></i>';
    statusEl.textContent  = 'Agent complete';
    subEl.textContent     = `${audited} emails audited`;
    barEl.style.width     = '100%';
    log(`✓ Done — ${audited} audited · ${spoofed} spoofed · ${soc} SOC cases`, '#34d399');
    doneBtn.style.display = 'block';
}
