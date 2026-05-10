/**
 * script.js - Phiên bản Ép Xung Polling (Fast Polling) + ZMQ Brokerless
 * Tốc độ quét 500ms - Cập nhật tin nhắn gần như tức thời.
 */

const BASE_URL = window.location.origin; 

let currentUser = '', sessionId = '', currentChannel = 'general', isDmChannel = false, dmTarget = '';
let lastTimestamp = 0, pollInterval = null, uiInterval = null, typingTimer = null;
let readCounts = {}, previousTotalUnread = 0, isFirstLoad = true;
let pendingImageBase64 = null; 

let isPolling = false; 
let sendQueue = [];
let isSending = false;

// ========================================
// Hỗ trợ Paste (Ctrl+V) ảnh thẳng vào ô chat
// ========================================
document.addEventListener('DOMContentLoaded', () => {
    const msgInput = document.getElementById('msg-input');
    if(msgInput) {
        msgInput.addEventListener('paste', function (e) {
            const items = (e.clipboardData || window.clipboardData).items;
            for (let index in items) {
                const item = items[index];
                if (item.kind === 'file' && item.type.startsWith('image/')) {
                    const blob = item.getAsFile();
                    if (blob.size > 2 * 1024 * 1024) {
                        alert("Kích thước ảnh quá lớn, vui lòng dán ảnh < 2MB!");
                        return;
                    }
                    const reader = new FileReader();
                    reader.onload = function(event) {
                        pendingImageBase64 = event.target.result;
                        msgInput.value = '[🖼️ Đã dán 1 ảnh - Nhấn Enter để gửi]';
                    };
                    reader.readAsDataURL(blob);
                    e.preventDefault(); 
                }
            }
        });

        msgInput.addEventListener('input', function(e) {
            if (pendingImageBase64 && !msgInput.value.includes('Nhấn Enter để gửi')) {
                pendingImageBase64 = null; 
            }
        });
    }
});

// ========================================
// Helpers & API
// ========================================
async function api(method, path, body = null) {
  const savedSid = localStorage.getItem('chat_session_id');
  const opts = { 
      method: method, 
      headers: { 'Content-Type': 'application/json' }
  };
  
  if (savedSid) {
      opts.headers['X-Session-Id'] = savedSid;
      opts.headers['Authorization'] = `Bearer ${savedSid}`;
  }

  if (body) {
      if (savedSid) body.session_id = savedSid;
      opts.body = JSON.stringify(body);
  } else if (method !== 'GET' && method !== 'HEAD' && savedSid) {
      opts.body = JSON.stringify({ session_id: savedSid });
  }

  try {
    const resp = await fetch(BASE_URL + path, opts);
    return JSON.parse(await resp.text());
  } catch (e) { 
    return { status: 'error', message: e.message }; 
  }
}

function showNotification(msg) {
  const el = document.getElementById('notification');
  el.textContent = msg; el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 3000);
}

function formatTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text; return div.innerHTML;
}

function playTingSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator(); const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.type = 'sine'; osc.frequency.setValueAtTime(1046.50, ctx.currentTime); 
    gain.gain.setValueAtTime(0.1, ctx.currentTime); 
    osc.start(); gain.gain.exponentialRampToValueAtTime(0.00001, ctx.currentTime + 0.5);
    osc.stop(ctx.currentTime + 0.5);
  } catch(e) {}
}

// ========================================
// Đăng nhập & Thoát
// ========================================
async function doLogin() {
  const username = document.getElementById('login-user').value.trim();
  const password = document.getElementById('login-pass').value;
  if (!username || !password) return;

  const result = await api('POST', '/login/', { username, password });
  if (result.status === 'success') {
    currentUser = result.data.username; 
    sessionId = result.data.session_id;
    
    localStorage.setItem('chat_session_id', sessionId);
    localStorage.setItem('chat_username', currentUser);
    
    document.getElementById('login-screen').style.display = 'none';
    document.getElementById('chat-screen').style.display = 'flex';
    document.getElementById('user-display').textContent = currentUser;

    const currentPort = window.location.port || 80;
    await api('POST', '/submit-info/', { ip: window.location.hostname, port: parseInt(currentPort), username: currentUser });
    
    await refreshChannels(); 
    await refreshPeers(); 
    loadMessages();

    // KIẾN TRÚC ÉP XUNG POLLING:
    if (pollInterval) clearInterval(pollInterval);
    if (uiInterval) clearInterval(uiInterval);
    
    // 1. Quét tin nhắn siêu tốc: 500ms / lần
    pollInterval = setInterval(() => { pollMessages(); }, 500);
    
    // 2. Cập nhật danh bạ & kênh chậm hơn: 3000ms / lần (Tránh chớp giật UI)
    uiInterval = setInterval(() => { refreshChannels(); refreshPeers(); }, 3000);
    
  } else {
    document.getElementById('login-error').textContent = result.message || 'Sai tài khoản hoặc mật khẩu';
  }
}

function doLogout() {
  localStorage.removeItem('chat_session_id');
  localStorage.removeItem('chat_username');
  location.reload();
}

// ========================================
// Kênh & Danh sách
// ========================================
async function refreshChannels() {
  const result = await api('POST', '/channels/', { username: currentUser });
  if (result.status === 'success') {
    const list = document.getElementById('channel-list'), dmList = document.getElementById('dm-list');
    list.innerHTML = ''; dmList.innerHTML = '';
    let currentTotalUnread = 0;

    for (const ch of result.data.channels) {
      if (ch.name.includes('.tmp')) continue;

      if (isFirstLoad || ch.name === currentChannel) readCounts[ch.name] = ch.message_count;
      let unread = Math.max(0, ch.message_count - (readCounts[ch.name] || 0));
      currentTotalUnread += unread;

      const div = document.createElement('div');
      div.className = 'channel-item' + (ch.name === currentChannel ? ' active' : '');
      const badgeHtml = unread > 0 ? `<span class="ch-badge unread">${unread} Mới</span>` : `<span class="ch-badge">${ch.message_count}</span>`;
      
      const lockIcon = ch.is_private ? ' 🔒' : '';
      const channelDisplayName = ch.is_dm ? '@ ' + getDmPeerName(ch.name) : '# ' + ch.name + lockIcon;

      div.innerHTML = `<span class="ch-name">${channelDisplayName}</span>${badgeHtml}`;
      div.onclick = () => switchChannel(ch.name);
      if (ch.is_dm) dmList.appendChild(div); else list.appendChild(div);
    }
    isFirstLoad = false;
    if (currentTotalUnread > previousTotalUnread) playTingSound();
    previousTotalUnread = currentTotalUnread;
  }
}

function switchChannel(name) {
  currentChannel = name; lastTimestamp = 0;
  isDmChannel = name.startsWith('dm:'); dmTarget = isDmChannel ? getDmPeerName(name) : '';
  document.getElementById('messages').innerHTML = '';
  refreshChannels(); loadMessages();
}

function getDmPeerName(n) { return n.substring(3).split('<->').find(u => u !== currentUser); }

async function refreshPeers() {
  const result = await api('GET', '/get-list/');
  if (result.status === 'success') {
    const list = document.getElementById('peer-list');
    let existingNodes = {};
    list.querySelectorAll('.peer-item').forEach(el => { existingNodes[el.dataset.username] = el; });

    for (const peer of result.data.peers) {
      if (peer.username === currentUser || peer.username.includes('.tmp')) continue;
      
      const dotColor = peer.is_online ? '#2ecc71' : '#e74c3c'; 
      
      if (existingNodes[peer.username]) {
          existingNodes[peer.username].querySelector('.dot').style.backgroundColor = dotColor;
          existingNodes[peer.username].querySelector('.dot').style.borderColor = dotColor;
          delete existingNodes[peer.username]; 
      } else {
          const div = document.createElement('div'); 
          div.className = 'peer-item'; div.dataset.username = peer.username;
          div.innerHTML = `<span class="dot" style="background-color: ${dotColor}; border-color: ${dotColor};"></span> <span style="margin-left: 8px;">${peer.username}</span>`;
          div.onclick = () => { switchChannel('dm:' + [currentUser, peer.username].sort().join('<->')); showNotification('Nhắn tin với ' + peer.username); };
          list.appendChild(div);
      }
    }
    Object.values(existingNodes).forEach(el => el.remove());
  }
}

async function promptCreateChannel() {
  const channelName = prompt("Nhập tên kênh mới:");
  if (!channelName || channelName.trim() === "") return;
  const isPrivate = confirm("Bạn có muốn đặt kênh này làm Kênh Kín (Private) không?\nOK = Có, Cancel = Không (Public)");
  let allowedMembers = [currentUser];
  if (isPrivate) {
      const membersStr = prompt("Nhập TÊN CÁC THÀNH VIÊN được phép vào (cách nhau bằng dấu phẩy):\nVí dụ: user2, user3", currentUser);
      if (membersStr) {
          allowedMembers = membersStr.split(',').map(s => s.trim()).filter(s => s);
          if (!allowedMembers.includes(currentUser)) allowedMembers.push(currentUser); 
      }
  }
  const result = await api('POST', '/create-channel/', { name: channelName.trim(), creator: currentUser, is_private: isPrivate, allowed_members: allowedMembers });
  if (result.status === 'success') { await refreshChannels(); switchChannel(result.data.channel); } else alert("Lỗi: " + result.message);
}

async function promptAddPeer() {
  const peerPort = prompt("🚨 Nhập Port của Peer bạn muốn kết nối thủ công:");
  if (!peerPort || isNaN(peerPort)) return;
  const peerName = prompt(`Nhập tên định danh của Port ${peerPort}:`);
  if (!peerName) return;
  const result = await api('POST', '/add-list/', { port: parseInt(peerPort), username: peerName.trim() });
  if (result.status === 'success') { showNotification(result.message); await api('POST', '/connect-peer/', { port: parseInt(peerPort) }); refreshPeers(); } else alert("Lỗi: " + result.message);
}

async function refreshAll() { await refreshChannels(); await refreshPeers(); showNotification("Đã cập nhật!"); }

// ========================================
// HÀNG ĐỢI GỬI TIN NHẮN 
// ========================================
async function processSendQueue() {
    if (isSending || sendQueue.length === 0) return;
    isSending = true; 

    while (sendQueue.length > 0) {
        const task = sendQueue[0];
        try {
            await api('POST', task.endpoint, task.body);
        } catch (e) {
            console.error("Lỗi khi gửi tin:", e);
        }
        sendQueue.shift(); 
        
        // Nghỉ giữa các lần gửi 100ms
        await new Promise(r => setTimeout(r, 100)); 
    }

    isSending = false; 
    pollMessages(); 
}

async function sendMessage() {
  const input = document.getElementById('msg-input');
  
  if (pendingImageBase64) {
      const endpoint = isDmChannel ? '/send-peer/' : '/broadcast-peer/';
      const body = isDmChannel ? { from: currentUser, to: dmTarget, message: pendingImageBase64 } : { from: currentUser, message: pendingImageBase64, channel: currentChannel };
      pendingImageBase64 = null; 
      input.value = '';
      sendQueue.push({ endpoint, body }); 
      processSendQueue(); 
      return;
  }

  const text = input.value.trim(); if (!text) return;
  input.value = '';
  
  const endpoint = isDmChannel ? '/send-peer/' : '/broadcast-peer/';
  const body = isDmChannel ? { from: currentUser, to: dmTarget, message: text } : { from: currentUser, message: text, channel: currentChannel };
  
  sendQueue.push({ endpoint, body }); 
  processSendQueue(); 
}

function handleTyping() {
  if (!typingTimer) {
    api('POST', '/signal-typing/', { channel: currentChannel, username: currentUser });
    typingTimer = setTimeout(() => { typingTimer = null; }, 2000);
  }
}

function markAsRead() {
  if (lastTimestamp > 0) api('POST', '/signal-read/', { channel: currentChannel, username: currentUser, timestamp: lastTimestamp });
}

// ========================================
// VÉT CẠN TIN NHẮN (TỐC ĐỘ 500ms)
// ========================================
async function pollMessages() {
  if (isPolling) return; 
  isPolling = true;      

  try {
      const safeSince = lastTimestamp > 2 ? lastTimestamp - 2 : 0;
      
      const res = await api('POST', '/messages/', { channel: currentChannel, since: safeSince });
      if (res.status === 'success') {
        
        const sortedMsgs = res.data.messages.sort((a, b) => a.timestamp - b.timestamp);
        
        sortedMsgs.forEach(msg => { 
            appendMessage(msg); 
            if (msg.timestamp > lastTimestamp) lastTimestamp = msg.timestamp; 
        });
        markAsRead(); 

        const typers = (res.data.typing || []).filter(u => u !== currentUser);
        document.getElementById('typing-indicator').style.display = typers.length ? 'flex' : 'none';
        document.getElementById('typing-text').innerText = typers.length ? typers.join(', ') + ' đang gõ' : '';

        document.querySelectorAll('.messenger-seen-row').forEach(el => el.remove());
        const allMsgs = document.querySelectorAll('.msg');
        if (allMsgs.length > 0) {
          const veryLastMsg = allMsgs[allMsgs.length - 1];
          if (veryLastMsg.dataset.author === currentUser) {
            const lastTs = parseFloat(veryLastMsg.dataset.timestamp);
            const readsData = (res.data && res.data.reads) ? res.data.reads : {};
            const readers = Object.entries(readsData).filter(([u, t]) => u !== currentUser && parseFloat(t) >= lastTs).map(e => e[0]);
            
            if (readers.length > 0) {
              const seenRow = document.createElement('div'); seenRow.className = 'messenger-seen-row';
              readers.forEach(reader => {
                const avatar = document.createElement('div'); avatar.className = 'seen-avatar';
                avatar.innerText = reader.charAt(0).toUpperCase(); avatar.title = 'Đã xem bởi ' + reader;
                seenRow.appendChild(avatar);
              });
              veryLastMsg.appendChild(seenRow);
            }
          }
        }
      }
  } finally {
      isPolling = false; 
  }
}

async function loadMessages() {
  document.getElementById('messages').innerHTML = ''; lastTimestamp = 0;
  await pollMessages();
  document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
}

function appendMessage(msg) {
  const container = document.getElementById('messages');
  
  const rawText = msg.text || msg.message || '';
  const textSnippet = encodeURIComponent(rawText.substring(0, 50)); 
  const signature = msg.timestamp + '_' + msg.from + '_' + textSnippet;
  
  if (container.querySelector(`[data-signature="${signature}"]`)) return;

  const div = document.createElement('div');
  const isMe = (msg.from === currentUser);
  div.className = `msg ${isMe ? 'me' : 'other'}`; 
  div.dataset.author = msg.from; 
  div.dataset.timestamp = msg.timestamp;
  div.dataset.signature = signature; 
  
  let contentHtml = '';
  
  if (rawText.startsWith('data:image/') || rawText.match(/\.(png|jpg|jpeg|gif|webp)$/i) || rawText.startsWith('/uploads/')) {
    contentHtml = `<img src="${rawText}" class="msg-image" style="max-width:250px;border-radius:12px;margin-top:6px;cursor:pointer;border:1px solid rgba(255,255,255,0.1);" onclick="window.open('${rawText}')">`;
  } else if (rawText.match(/\.(pdf|docx|doc|zip|rar)$/i)) {
    contentHtml = `<a href="${rawText}" target="_blank" class="file-download">📄 Tải xuống: ${rawText.split('/').pop()}</a>`;
  } else if (rawText.match(/\.(webm|mp3|wav|ogg)$/i)) {
    contentHtml = `<audio controls src="${rawText}"></audio>`;
  } else {
    contentHtml = `<div class="msg-text">${escapeHtml(rawText)}</div>`;
  }

  div.innerHTML = `<div class="msg-meta"><span class="msg-author">${isMe ? 'Bạn' : (msg.from || 'unknown')}</span><span class="msg-time">${formatTime(msg.timestamp)}</span></div>${contentHtml}`;
  container.appendChild(div);
  
  const isAtBottom = container.scrollHeight - container.clientHeight <= container.scrollTop + 50;
  if (isAtBottom || isMe) {
      container.scrollTop = container.scrollHeight;
  }
}

// ========================================
// Upload File & Voice
// ========================================
async function uploadFile() {
  const fileInput = document.getElementById('file-picker'); 
  if (fileInput.files.length === 0) return;
  const file = fileInput.files[0]; 
  
  if (file.size > 2 * 1024 * 1024) {
      alert("Vui lòng chọn ảnh nhỏ hơn 2MB để hệ thống P2P chạy ổn định!");
      return;
  }
  
  showNotification('Đang gửi ảnh...');
  const reader = new FileReader();
  reader.onloadend = async function() {
    const base64String = reader.result;
    const endpoint = isDmChannel ? '/send-peer/' : '/broadcast-peer/';
    const body = isDmChannel ? { from: currentUser, to: dmTarget, message: base64String } : { from: currentUser, message: base64String, channel: currentChannel };
    
    sendQueue.push({ endpoint, body }); 
    processSendQueue();
  };
  reader.readAsDataURL(file); 
  fileInput.value = '';
}

let mediaRecorder, audioChunks = [], isRecording = false;
async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream); mediaRecorder.start(); isRecording = true;
    document.getElementById('btn-mic').classList.add('recording'); showNotification("🎙️ Đang thu âm...");
    mediaRecorder.addEventListener("dataavailable", e => audioChunks.push(e.data));
    mediaRecorder.addEventListener("stop", async () => {
      const audioBlob = new Blob(audioChunks, { type: 'audio/webm' }); audioChunks = [];
      if (audioBlob.size < 2000) return showNotification("Ghi âm quá ngắn!");
      
      const savedSid = localStorage.getItem('chat_session_id');
      const fetchHeaders = { 'X-File-Name': `voice_${Date.now()}.webm` };
      if (savedSid) {
          fetchHeaders['X-Session-Id'] = savedSid;
          fetchHeaders['Authorization'] = `Bearer ${savedSid}`;
      }

      const res = await fetch(BASE_URL + '/upload/', { method: 'POST', headers: fetchHeaders, body: audioBlob });
      const result = await res.json();
      if (result.status === 'success') { 
          const body = { from: currentUser, message: result.url, channel: currentChannel };
          sendQueue.push({ endpoint: '/broadcast-peer/', body });
          processSendQueue();
      }
    });
  } catch (err) { alert("Vui lòng cấp quyền Micro!"); }
}

function stopRecording() {
  if (isRecording && mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop(); isRecording = false;
    document.getElementById('btn-mic').classList.remove('recording');
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }
}

// ========================================
// Emoji & UI Setup
// ========================================
const EMOJIS = ["😀","😂","😍","👍","🔥","❤️","✨","🙌","🚀","😭","😊","🥺","😎","🎉","💯","👀","🙏","💀"];
function initEmojiPicker() {
  const picker = document.getElementById('emoji-picker'); picker.innerHTML = '';
  EMOJIS.forEach(emoji => {
    const span = document.createElement('span'); span.className = 'emoji-item'; span.innerText = emoji;
    span.onclick = () => { document.getElementById('msg-input').value += emoji; document.getElementById('msg-input').focus(); };
    picker.appendChild(span);
  });
}
initEmojiPicker();
function toggleEmojiPicker() {
  const p = document.getElementById('emoji-picker');
  p.style.display = (p.style.display === 'none' || p.style.display === '') ? 'grid' : 'none';
}
document.addEventListener('click', function(event) {
  const picker = document.getElementById('emoji-picker'), btn = document.getElementById('btn-emoji-toggle');
  if (picker.style.display === 'grid' && !picker.contains(event.target) && !btn.contains(event.target)) picker.style.display = 'none';
});

document.addEventListener('DOMContentLoaded', () => {
    const sidebarFooter = document.querySelector('.sidebar-footer');
    if (sidebarFooter) {
        const themeBtn = document.createElement('button');
        themeBtn.className = 'btn-ghost';
        themeBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg> Giao diện Sáng/Tối`;
        themeBtn.onclick = () => {
            document.body.classList.toggle('light-mode');
            localStorage.setItem('theme_preference', document.body.classList.contains('light-mode') ? 'light' : 'dark');
        };
        sidebarFooter.appendChild(themeBtn);
        if (localStorage.getItem('theme_preference') === 'light') document.body.classList.add('light-mode');
    }
});

// ========================================
// AUTO-LOGIN
// ========================================
document.addEventListener('DOMContentLoaded', async () => {
    const savedSid = localStorage.getItem('chat_session_id');
    const savedUser = localStorage.getItem('chat_username');

    if (savedSid && savedUser) {
        sessionId = savedSid;
        currentUser = savedUser;
        document.getElementById('login-screen').style.display = 'none';
        document.getElementById('chat-screen').style.display = 'flex';
        document.getElementById('user-display').textContent = currentUser;
        
        await refreshChannels(); 
        await refreshPeers(); 
        loadMessages();
        
        // KIẾN TRÚC ÉP XUNG POLLING:
        if (pollInterval) clearInterval(pollInterval);
        if (uiInterval) clearInterval(uiInterval);
        
        // 1. Quét tin nhắn siêu tốc: 500ms / lần
        pollInterval = setInterval(() => { pollMessages(); }, 500);
        
        // 2. Cập nhật danh bạ & kênh chậm hơn: 3000ms / lần (Tránh chớp giật UI)
        uiInterval = setInterval(() => { refreshChannels(); refreshPeers(); }, 3000);
    }
});