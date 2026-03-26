/**
 * script.js - Main application scripts
 * 
 * Contains the full chat application logic (login, channels, peers, messaging).
 */

// ========================================
// Chat Application - State
// ========================================
let currentUser = '';
let sessionId = '';
let currentChannel = 'general';
let isDmChannel = false;
let dmTarget = '';
let lastTimestamp = 0;
let pollInterval = null;

function getDmPeerName(channelName) {
  // DM channel format: "dm:user1<->user2"
  if (!channelName.startsWith('dm:')) return '';
  const parts = channelName.substring(3).split('<->');
  return parts.find(u => u !== currentUser) || parts[0];
}

// ========================================
// Chat Application - Helpers
// ========================================
async function api(method, path, body) {
  const opts = {
    method: method,
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin' // Send cookies automatically (RFC 6265)
  };
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

    enterChatScreen();
  } else {
    document.getElementById('login-error').textContent =
      result.message || 'Login failed';
  }
}

async function enterChatScreen() {
  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('chat-screen').style.display = 'flex';
  document.getElementById('user-display').textContent = currentUser;

  // Register peer info
  await api('POST', '/submit-info/', {
    ip: '127.0.0.1',
    port: parseInt(window.location.port) || 8000,
    username: currentUser
  });

  // Load initial data
  await refreshChannels();
  await refreshPeers();
  loadMessages();

  // Start polling for new messages
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(pollMessages, 2000);
}

function doLogout() {
  currentUser = '';
  sessionId = '';
  // Clear the session cookie by expiring it
  document.cookie = 'session_id=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT';
  if (pollInterval) clearInterval(pollInterval);
  document.getElementById('chat-screen').style.display = 'none';
  document.getElementById('login-screen').style.display = 'flex';
  document.getElementById('login-pass').value = '';
}

// ========================================
// Chat Application - Session Restore
// ========================================
async function tryRestoreSession() {
  try {
    const result = await api('GET', '/validate-session/');
    if (result.status === 'success' && result.data && result.data.username) {
      currentUser = result.data.username;
      sessionId = result.data.session_id;
      enterChatScreen();
      showNotification('Session restored — welcome back, ' + currentUser + '!');
    }
  } catch (e) {
    // No valid session, stay on login screen
  }
}

// Auto-restore session on page load
document.addEventListener('DOMContentLoaded', tryRestoreSession);

// ========================================
// Chat Application - Channels
// ========================================
async function refreshChannels() {
  const result = await api('POST', '/channels/', { username: currentUser });
  if (result.status === 'success') {
    const list = document.getElementById('channel-list');
    const dmList = document.getElementById('dm-list');
    list.innerHTML = '';
    dmList.innerHTML = '';

    for (const ch of result.data.channels) {
      const div = document.createElement('div');
      div.className = 'channel-item' + (ch.name === currentChannel ? ' active' : '');

      if (ch.is_dm) {
        const peerName = getDmPeerName(ch.name);
        div.innerHTML = '<span class="ch-name dm-name">@ ' + peerName + '</span>' +
          '<span class="ch-badge">' + ch.message_count + '</span>';
        div.onclick = () => switchChannel(ch.name);
        dmList.appendChild(div);
      } else {
        div.innerHTML = '<span class="ch-name"># ' + ch.name + '</span>' +
          '<span class="ch-badge">' + ch.message_count + '</span>';
        div.onclick = () => switchChannel(ch.name);
        list.appendChild(div);
      }
    }
  }
}

function switchChannel(name) {
  currentChannel = name;
  lastTimestamp = 0;
  isDmChannel = name.startsWith('dm:');
  dmTarget = isDmChannel ? getDmPeerName(name) : '';

  if (isDmChannel) {
    document.getElementById('chat-header').textContent = '@ ' + dmTarget;
    document.getElementById('msg-input').placeholder = 'Message ' + dmTarget + '...';
  } else {
    document.getElementById('chat-header').textContent = '# ' + name;
    document.getElementById('msg-input').placeholder = 'Type a message...';
  }

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
      if (peer.username === currentUser) continue;
      const div = document.createElement('div');
      div.className = 'peer-item';
      div.innerHTML = '<span class="dot"></span>' + peer.username;
      div.style.cursor = 'pointer';
      div.title = 'Click to send direct message';
      div.onclick = () => openDm(peer.username);
      list.appendChild(div);
    }
  }
}

async function openDm(peerName) {
  // DM channel name uses sorted usernames for consistency
  const sorted = [currentUser, peerName].sort();
  const dmChannel = 'dm:' + sorted[0] + '<->' + sorted[1];

  // Send an initial empty-check: just switch to the channel.
  // The server creates the DM channel on first /send-peer/ call.
  // We pre-create it so we can view it immediately.
  if (!document.querySelector('.channel-item.active[data-dm="' + peerName + '"]')) {
    // Ensure the channel exists by sending a lightweight message query
    await api('POST', '/messages/', { channel: dmChannel });
  }

  switchChannel(dmChannel);
  await refreshChannels();
  showNotification('Direct message with ' + peerName);
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

  let result;
  if (isDmChannel && dmTarget) {
    // Direct message via /send-peer/
    result = await api('POST', '/send-peer/', {
      from: currentUser,
      to: dmTarget,
      message: text
    });
  } else {
    // Broadcast to channel via /broadcast-peer/
    result = await api('POST', '/broadcast-peer/', {
      from: currentUser,
      message: text,
      channel: currentChannel
    });
  }

  if (result.status === 'success') {
    // Immediately load messages to see our own
    await pollMessages();
  }
}
