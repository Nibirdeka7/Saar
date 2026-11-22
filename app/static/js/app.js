// Enterprise authenticated UI for Saar.
const $ = id => document.getElementById(id);

let authToken = localStorage.getItem('saar_auth_token');
let currentUser = null;

// Single-workspace conversation identifier
let conversationId = sessionStorage.getItem('saar_conversation_id') || crypto.randomUUID();
sessionStorage.setItem('saar_conversation_id', conversationId);

const toast = msg => {
  const el = $('toast');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 4000);
};

const api = async (path, options = {}) => {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }
  const res = await fetch(path, {
    ...options,
    headers
  });
  const data = await res.json();
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith('/api/auth/login') && !path.startsWith('/api/auth/register')) {
      showAuthModal(true);
    }
    throw Error(data.detail || 'Request failed');
  }
  return data;
};

function showAuthModal(show = true) {
  const modal = $('authModal');
  if (!modal) return;
  if (show) {
    modal.classList.remove('hidden');
  } else {
    modal.classList.add('hidden');
  }
}

function updateAuthUI(user) {
  currentUser = user;
  const profile = $('userProfile');
  const openBtn = $('loginOpenBtn');
  const emailEl = $('userEmail');
  const badgeEl = $('userRoleBadge');
  const wsBadge = $('workspaceBadge');

  if (user) {
    if (profile) profile.classList.remove('hidden');
    if (openBtn) openBtn.classList.add('hidden');
    if (emailEl) {
      emailEl.textContent = user.email;
      emailEl.title = user.email;
    }
    if (badgeEl) {
      badgeEl.textContent = user.admin ? 'Admin' : 'Member';
      badgeEl.className = 'role-badge ' + (user.admin ? 'admin' : '');
    }
    if (wsBadge) {
      wsBadge.textContent = `${user.tenant} · ${user.email}`;
    }
  } else {
    if (profile) profile.classList.add('hidden');
    if (openBtn) openBtn.classList.remove('hidden');
    if (wsBadge) {
      wsBadge.textContent = 'Not authenticated';
    }
  }
}

async function checkAuth() {
  if (!authToken) {
    updateAuthUI(null);
    showAuthModal(true);
    return;
  }
  try {
    const user = await api('/api/auth/me');
    updateAuthUI(user);
    showAuthModal(false);
  } catch (e) {
    localStorage.removeItem('saar_auth_token');
    authToken = null;
    updateAuthUI(null);
    showAuthModal(true);
  }
}

// Reset conversation & restore centered hero
$('newChat').onclick = () => {
  conversationId = crypto.randomUUID();
  sessionStorage.setItem('saar_conversation_id', conversationId);
  $('messages').replaceChildren();
  $('chatHero').classList.remove('hidden');
  toast('Started a new conversation');
};

// Top tab switcher
function view(name) {
  ['chat', 'docs', 'approval', 'admin'].forEach(x => {
    $(x + 'View').classList.toggle('hidden', x !== name);
    $(x + 'Tab').classList.toggle('active', x === name);
  });
  if (name === 'docs') loadDocs();
  if (name === 'admin') loadMetrics();
  if (name === 'approval') loadApprovals();
}

$('chatTab').onclick = () => view('chat');
$('docsTab').onclick = () => view('docs');
$('adminTab').onclick = () => view('admin');
$('approvalTab').onclick = () => view('approval');
$('refreshApprovals').onclick = loadApprovals;

// Stepped LangGraph pipeline progress animation
let progressTimers = [];

function startProgress() {
  const container = $('progress-container');
  const statusText = $('status-text');
  const steps = ['step-guard', 'step-retrieve', 'step-generate'];

  progressTimers.forEach(clearTimeout);
  progressTimers = [];

  steps.forEach(id => $(id).classList.remove('active'));
  $('step-guard').classList.add('active');
  statusText.textContent = 'Checking input guardrails...';
  container.classList.remove('hidden');

  progressTimers.push(setTimeout(() => {
    steps.forEach(id => $(id).classList.remove('active'));
    $('step-retrieve').classList.add('active');
    statusText.textContent = 'Searching authorized documents...';
  }, 650));

  progressTimers.push(setTimeout(() => {
    steps.forEach(id => $(id).classList.remove('active'));
    $('step-generate').classList.add('active');
    statusText.textContent = 'Synthesizing grounded answer...';
  }, 1500));
}

function stopProgress() {
  progressTimers.forEach(clearTimeout);
  progressTimers = [];
  $('progress-container').classList.add('hidden');
}

// Render message bubble & collapsible evidence citations
function addMessage(content, kind, sources = []) {
  $('chatHero').classList.add('hidden');

  const el = document.createElement('div');
  el.className = 'message ' + kind;
  el.textContent = content;

  if (sources.length) {
    const wrap = document.createElement('div');
    wrap.className = 'sources';

    sources.forEach(s => {
      const d = document.createElement('details');
      const title = document.createElement('summary');
      title.textContent = `[${s.index}] ${s.title} — page ${s.page}`;
      const excerpt = document.createElement('p');
      excerpt.textContent = s.excerpt;
      d.append(title, excerpt);
      wrap.append(d);
    });

    el.append(wrap);

    const actions = document.createElement('div');
    actions.className = 'message-actions';
    const feedback = document.createElement('button');
    feedback.type = 'button';
    feedback.className = 'secondary-btn';
    feedback.textContent = '👍 Helpful';
    feedback.onclick = async () => {
      try {
        await api('/api/feedback', { method: 'POST', body: JSON.stringify({ rating: 1 }) });
        feedback.disabled = true;
        feedback.textContent = '✓ Feedback saved';
        toast('Feedback saved');
      } catch (e) {
        toast(e.message);
      }
    };
    actions.append(feedback);
    el.append(actions);
  }

  $('messages').append(el);
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  return el;
}

// Chat form submission
$('chatForm').onsubmit = async e => {
  e.preventDefault();
  const input = $('question');
  const btn = $('sendButton');
  const q = input.value.trim();
  if (!q) return;

  addMessage(q, 'user');
  input.value = '';
  input.disabled = true;
  btn.disabled = true;
  startProgress();

  try {
    const r = await api('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ question: q, conversation_id: conversationId })
    });
    stopProgress();
    const msgEl = addMessage(r.answer, 'assistant', r.sources);

    if (r.status === 'pending_approval') {
      const actions = document.createElement('div');
      actions.className = 'message-actions';
      const reviewBtn = document.createElement('button');
      reviewBtn.type = 'button';
      reviewBtn.className = 'primary-btn';
      reviewBtn.textContent = 'Review approval request →';
      reviewBtn.onclick = () => view('approval');
      actions.append(reviewBtn);
      msgEl.append(actions);
    }
  } catch (err) {
    stopProgress();
    addMessage(`Error: ${err.message}`, 'assistant');
  } finally {
    input.disabled = false;
    btn.disabled = false;
    input.focus();
  }
};

// Hero suggestion chips
document.querySelectorAll('[data-q]').forEach(b => {
  b.onclick = () => {
    $('question').value = b.dataset.q;
    $('question').focus();
  };
});

// Document Library
async function loadDocs() {
  try {
    const r = await api('/api/documents');
    if (!r.documents.length) {
      $('docs').textContent = 'No documents indexed yet. Upload one above to get started.';
      return;
    }
    $('docs').replaceChildren(...r.documents.map(d => {
      const row = document.createElement('div');
      row.textContent = `📄 ${d.title} — ${d.status} (v${d.current_version})`;
      return row;
    }));
  } catch (e) {
    $('docs').textContent = e.message;
  }
}

$('uploadForm').onsubmit = async e => {
  e.preventDefault();
  const f = $('file').files[0];
  if (!f) return;
  if (f.size > 10485760) {
    toast('Maximum file size is 10 MB');
    return;
  }
  try {
    const r = await api('/api/documents/uploads', {
      method: 'POST',
      body: JSON.stringify({ filename: f.name })
    });
    const up = await fetch(r.upload_url, {
      method: 'PUT',
      headers: r.headers,
      body: f
    });
    if (!up.ok) throw Error('S3 upload failed');
    toast('Uploaded to S3. Processing document now...');
    await api('/api/documents/complete', {
      method: 'POST',
      body: JSON.stringify({ document_id: r.document_id })
    });
    toast('Document indexed in Pinecone!');
    $('uploadForm').reset();
    loadDocs();
  } catch (err) {
    toast(err.message);
  }
};

// Metrics
async function loadMetrics() {
  try {
    $('metrics').textContent = JSON.stringify(await api('/api/admin/metrics'), null, 2);
    $('guardrailMetrics').textContent = JSON.stringify(await api('/api/admin/guardrails'), null, 2);
  } catch (e) {
    $('metrics').textContent = e.message;
  }
}

// Human-in-the-loop Approvals (DOM nodes use textContent only)
async function loadApprovals() {
  const root = $('approvalList');
  root.textContent = 'Loading approvals...';
  try {
    const response = await api('/api/approvals');
    if (!Array.isArray(response.approvals)) {
      throw Error('Unexpected API response: approvals list missing');
    }
    const approvals = response.approvals;
    const pending = approvals.filter(a => String(a.status).trim().toLowerCase() === 'pending').length;
    $('approvalSummary').textContent = `${pending} pending · ${approvals.length} total (most recent 100)`;
    root.replaceChildren();

    if (!approvals.length) {
      root.textContent = 'No approval requests yet. Try asking the chatbot to delete a document.';
      return;
    }

    for (const a of approvals) {
      const card = document.createElement('article');
      card.className = 'approval-card';

      const header = document.createElement('div');
      header.className = 'approval-header';
      const title = document.createElement('strong');
      title.textContent = a.question;
      const badge = document.createElement('span');
      badge.className = 'approval-status ' + a.status;
      badge.textContent = a.status;
      header.append(title, badge);
      card.append(header);

      const meta = document.createElement('p');
      meta.textContent = `Requested by ${a.requester} · ${new Date(a.created_at).toLocaleString()}`;
      card.append(meta);

      if (String(a.status).trim().toLowerCase() === 'pending') {
        const actions = document.createElement('div');
        actions.className = 'approval-actions';
        for (const [label, approve] of [['Approve', true], ['Reject', false]]) {
          const button = document.createElement('button');
          button.textContent = label;
          button.className = approve ? 'approve-button' : 'reject-button';
          button.onclick = async () => {
            const decision = approve ? 'approve' : 'reject';
            if (!confirm(`Are you sure you want to ${decision} this request? This records a decision only and does not execute the requested action.`)) return;
            button.disabled = true;
            try {
              const r = await api(`/api/approvals/${encodeURIComponent(a.id)}/decision`, {
                method: 'POST',
                body: JSON.stringify({ approve })
              });
              toast(`Request ${r.status}. No action executed.`);
              await loadApprovals();
            } catch (e) {
              toast(e.message);
              button.disabled = false;
            }
          };
          actions.append(button);
        }
        card.append(actions);
      } else {
        const info = document.createElement('p');
        info.textContent = `Reviewed by ${a.reviewer || 'unknown'} · ${a.reviewed_at ? new Date(a.reviewed_at).toLocaleString() : ''} · No action executed`;
        card.append(info);
      }

      root.append(card);
    }
  } catch (e) {
    root.textContent = `Unable to load approvals: ${e.message}. Check /api/approvals and your Uvicorn terminal.`;
    console.error('Approvals loading failed:', e);
  }
}

// --- Auth Modal & Form Handlers ---
if ($('authTabLogin')) {
  $('authTabLogin').onclick = () => {
    $('authTabLogin').classList.add('active');
    $('authTabRegister').classList.remove('active');
    $('loginForm').classList.remove('hidden');
    $('registerForm').classList.add('hidden');
    $('authTitle').textContent = 'Sign in to your account';
    $('loginError').classList.add('hidden');
  };
}

if ($('authTabRegister')) {
  $('authTabRegister').onclick = () => {
    $('authTabRegister').classList.add('active');
    $('authTabLogin').classList.remove('active');
    $('registerForm').classList.remove('hidden');
    $('loginForm').classList.add('hidden');
    $('authTitle').textContent = 'Create your account';
    $('regError').classList.add('hidden');
  };
}

if ($('loginOpenBtn')) {
  $('loginOpenBtn').onclick = () => showAuthModal(true);
}

if ($('logoutBtn')) {
  $('logoutBtn').onclick = async () => {
    try {
      await api('/api/auth/logout', { method: 'POST' });
    } catch (e) {}
    localStorage.removeItem('saar_auth_token');
    authToken = null;
    currentUser = null;
    updateAuthUI(null);
    showAuthModal(true);
    toast('Signed out successfully');
  };
}

if ($('loginForm')) {
  $('loginForm').onsubmit = async e => {
    e.preventDefault();
    const errEl = $('loginError');
    errEl.classList.add('hidden');
    const email = $('loginEmail').value.trim();
    const password = $('loginPassword').value;
    const btn = $('loginSubmit');
    btn.disabled = true;
    btn.textContent = 'Signing in...';

    try {
      const r = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password })
      });
      authToken = r.token;
      localStorage.setItem('saar_auth_token', r.token);
      updateAuthUI(r.user);
      showAuthModal(false);
      toast(`Welcome back, ${r.user.email}!`);
      $('loginForm').reset();
      if (!$('docsView').classList.contains('hidden')) loadDocs();
      if (!$('adminView').classList.contains('hidden')) loadMetrics();
      if (!$('approvalView').classList.contains('hidden')) loadApprovals();
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Sign in ↗';
    }
  };
}

if ($('registerForm')) {
  $('registerForm').onsubmit = async e => {
    e.preventDefault();
    const errEl = $('regError');
    errEl.classList.add('hidden');
    const email = $('regEmail').value.trim();
    const password = $('regPassword').value;
    const tenant = $('regTenant').value.trim() || 'demo-workspace';
    const admin = $('regAdmin').checked;
    const btn = $('regSubmit');
    btn.disabled = true;
    btn.textContent = 'Creating account...';

    try {
      const r = await api('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({ email, password, tenant, admin })
      });
      authToken = r.token;
      localStorage.setItem('saar_auth_token', r.token);
      updateAuthUI(r.user);
      showAuthModal(false);
      toast(`Account created! Welcome, ${r.user.email}`);
      $('registerForm').reset();
      if (!$('docsView').classList.contains('hidden')) loadDocs();
      if (!$('adminView').classList.contains('hidden')) loadMetrics();
      if (!$('approvalView').classList.contains('hidden')) loadApprovals();
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Create account ↗';
    }
  };
}

// Initial session verification
checkAuth();