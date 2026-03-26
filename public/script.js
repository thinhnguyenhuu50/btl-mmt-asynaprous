/**
 * script.js - Main application scripts
 * 
 * Contains utility functions for the sample form page (sendEcho, sendLogin, sendHello)
 * and the full chat application logic (login, channels, peers, messaging).
 */

// ========================================
// Sample Form Functions
// ========================================

async function sendEcho() {
  const message = document.getElementById("msg").value;

  try {
    const response = await fetch("/echo", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ text: message })
    });

    if (!response.ok) {
      throw new Error("HTTP error " + response.status);
    }

    const result = await response.text();
    document.getElementById("response").textContent = "Server replied: " + result;
  } catch (err) {
    document.getElementById("response").textContent = "Request failed: " + err.message;
  }
}

async function sendLogin() {
  const message = document.getElementById("msg").value;

  try {
    const response = await fetch("/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ text: message })
    });

    if (!response.ok) {
      throw new Error("HTTP error " + response.status);
    }

    const result = await response.text();
    document.getElementById("response").textContent = "Server replied: " + result;
  } catch (err) {
    document.getElementById("response").textContent = "Request failed: " + err.message;
  }
}

async function sendHello() {
  const message = document.getElementById("msg").value;

  try {
    const response = await fetch("/hello", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ text: message })
    });

    if (!response.ok) {
      throw new Error("HTTP error " + response.status);
    }

    const result = await response.text();
    document.getElementById("response").textContent = "Server replied: " + result;
  } catch (err) {
    document.getElementById("response").textContent = "Request failed: " + err.message;
  }
}


// ========================================
// Chat Application - State
// ========================================
let currentUser = '';
let sessionId = '';
let currentChannel = 'general';
let lastTimestamp = 0;
let pollInterval = null;

// ========================================
// Chat Application - Helpers
// ========================================
async function api(method, path, body) {
  const opts = {
    method: method,
    headers: { 'Content-Type': 'application/json' }
  };
  if (sessionId) {
    opts.headers['Cookie'] = 'session_id=' + sessionId;
  }
  if (body) {
    opts.body = JSON.stringify(body);
  }
  try {
    const resp = await fetch(path, opts);
    const text = await resp.text();
    return JSON.parse(text);
  } catch (e) {
    console.error('API error:', e);
    return { status: 'error', message: e.message };
  }
}

function showNotification(msg) {
  const el = document.getElementById('notification');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 3000);
}

function formatTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ========================================
// Chat Application - Login / Logout
// ========================================
async function doLogin() {
  const username = document.getElementById('login-user').value.trim();
  const password = document.getElementById('login-pass').value;

  if (!username || !password) {
    document.getElementById('login-error').textContent = 'Please enter username and password';
    return;
  }

  const result = await api('POST', '/login/', { username, password });

  if (result.status === 'success') {
    currentUser = result.data.username;
    sessionId = result.data.session_id;

    document.getElementById('login-screen').style.display = 'none';
    document.getElementById('chat-screen').style.display = 'flex';
    document.getElementById('user-display').textContent = currentUser;

    // Register peer info
    await api('POST', '/submit-info/', {
      ip: '127.0.0.1',
      port: window.location.port || 8000,
      username: currentUser
    });

    // Load initial data
    await refreshChannels();
    await refreshPeers();
    loadMessages();

    // Start polling for new messages
    pollInterval = setInterval(pollMessages, 2000);
  } else {
    document.getElementById('login-error').textContent =
      result.message || 'Login failed';
  }
}

function doLogout() {
  currentUser = '';
  sessionId = '';
  if (pollInterval) clearInterval(pollInterval);
  document.getElementById('chat-screen').style.display = 'none';
  document.getElementById('login-screen').style.display = 'flex';
  document.getElementById('login-pass').value = '';
}

// ========================================
// Chat Application - Channels
// ========================================
async function refreshChannels() {
  const result = await api('POST', '/channels/', { username: currentUser });
  if (result.status === 'success') {
    const list = document.getElementById('channel-list');
    list.innerHTML = '';
    for (const ch of result.data.channels) {
      if (ch.is_dm) continue;  // Skip DM channels in sidebar
      const div = document.createElement('div');
      div.className = 'channel-item' + (ch.name === currentChannel ? ' active' : '');
      div.innerHTML = '<span class="ch-name"># ' + ch.name + '</span>' +
        '<span class="ch-badge">' + ch.message_count + '</span>';
      div.onclick = () => switchChannel(ch.name);
      list.appendChild(div);
    }
  }
}

function switchChannel(name) {
  currentChannel = name;
  lastTimestamp = 0;
  document.getElementById('chat-header').textContent = '# ' + name;
  document.getElementById('messages').innerHTML = '';
  refreshChannels();
  loadMessages();
}

async function promptCreateChannel() {
  const name = prompt('Enter channel name:');
  if (!name) return;

  const result = await api('POST', '/create-channel/', {
    name: name, creator: currentUser
  });

  if (result.status === 'success') {
    // Auto-join the channel
    await api('POST', '/join-channel/', {
      channel: name, username: currentUser
    });
    await refreshChannels();
    switchChannel(name);
    showNotification('Channel #' + name + ' created');
  } else {
    alert(result.message || 'Failed to create channel');
  }
}

// ========================================
// Chat Application - Peers
// ========================================
async function refreshPeers() {
  const result = await api('GET', '/get-list/');
  if (result.status === 'success') {
    const list = document.getElementById('peer-list');
    list.innerHTML = '';
    for (const peer of result.data.peers) {
      const div = document.createElement('div');
      div.className = 'peer-item';
      div.innerHTML = '<span class="dot"></span>' + peer.username;
      list.appendChild(div);
    }
  }
}

// ========================================
// Chat Application - Messages
// ========================================
async function loadMessages() {
  const result = await api('POST', '/messages/', {
    channel: currentChannel, since: 0
  });
  if (result.status === 'success') {
    const container = document.getElementById('messages');
    container.innerHTML = '';
    for (const msg of result.data.messages) {
      appendMessage(msg);
      if (msg.timestamp > lastTimestamp) lastTimestamp = msg.timestamp;
    }
    container.scrollTop = container.scrollHeight;
  }
}

async function pollMessages() {
  const result = await api('POST', '/messages/', {
    channel: currentChannel, since: lastTimestamp
  });
  if (result.status === 'success' && result.data.messages.length > 0) {
    const container = document.getElementById('messages');
    for (const msg of result.data.messages) {
      appendMessage(msg);
      if (msg.timestamp > lastTimestamp) lastTimestamp = msg.timestamp;
    }
    container.scrollTop = container.scrollHeight;

    // Show notification if message is from another user
    const lastMsg = result.data.messages[result.data.messages.length - 1];
    if (lastMsg.from !== currentUser) {
      showNotification('New message from ' + lastMsg.from);
    }
  }
}

function appendMessage(msg) {
  const container = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'msg';
  div.innerHTML =
    '<span class="msg-author">' + (msg.from || 'unknown') + '</span>' +
    '<span class="msg-time">' + formatTime(msg.timestamp) + '</span>' +
    '<div class="msg-text">' + escapeHtml(msg.text || msg.message || '') + '</div>';
  container.appendChild(div);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ========================================
// Chat Application - Send Message
// ========================================
async function sendMessage() {
  const input = document.getElementById('msg-input');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';

  const result = await api('POST', '/broadcast-peer/', {
    from: currentUser,
    message: text,
    channel: currentChannel
  });

  if (result.status === 'success') {
    // Immediately load messages to see our own
    await pollMessages();
  }
}
