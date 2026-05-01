/**
 * script.js - Tối ưu logic ứng dụng Chat Pro
 */
let currentUser = '', sessionId = '', currentChannel = 'general', isDmChannel = false, dmTarget = '';
let lastTimestamp = 0, pollInterval = null, typingTimer = null;
let readCounts = {}, previousTotalUnread = 0, isFirstLoad = true;
let isPolling = false;

// ========================================
// Helpers & API
// ========================================
async function api(method, path, body) {
  const opts = { method: method, headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin' };
  if (body) opts.body = JSON.stringify(body);
  try {
    const resp = await fetch(path, opts);
    return JSON.parse(await resp.text());
  } catch (e) { return { status: 'error', message: e.message }; }
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
    currentUser = result.data.username; sessionId = result.data.session_id;
    document.getElementById('login-screen').style.display = 'none';
    document.getElementById('chat-screen').style.display = 'flex';
    document.getElementById('user-display').textContent = currentUser;

    await api('POST', '/submit-info/', { ip: '127.0.0.1', port: window.location.port || 8000, username: currentUser });
    
    await refreshChannels(); await refreshPeers(); loadMessages();
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => { pollMessages(); refreshChannels(); refreshPeers(); }, 2000);
  } else {
    document.getElementById('login-error').textContent = result.message || 'Sai tài khoản hoặc mật khẩu!';
  }
}

function doLogout() {
  document.cookie = 'session_id=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT';
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
      if (isFirstLoad || ch.name === currentChannel) readCounts[ch.name] = ch.message_count;
      let unread = Math.max(0, ch.message_count - (readCounts[ch.name] || 0));
      currentTotalUnread += unread;
      
      const div = document.createElement('div');
      div.className = 'channel-item' + (ch.name === currentChannel ? ' active' : '');
      const badgeHtml = unread > 0 ? `<span class="ch-badge unread">${unread} Mới</span>` : `<span class="ch-badge">${ch.message_count}</span>`;
      div.innerHTML = `<span class="ch-name">${ch.is_dm ? '@ ' + getDmPeerName(ch.name) : '# ' + ch.name}</span>${badgeHtml}`;
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
    const list = document.getElementById('peer-list'); list.innerHTML = '';
    for (const peer of result.data.peers) {
      if (peer.username === currentUser) continue;
      const div = document.createElement('div'); div.className = 'peer-item';
      div.innerHTML = `<span class="dot"></span>${peer.username}`;
      div.onclick = () => { switchChannel('dm:' + [currentUser, peer.username].sort().join('<->')); showNotification('Nhắn tin với ' + peer.username); };
      list.appendChild(div);
    }
  }
}

async function promptCreateChannel() {
  const channelName = prompt("Nhập tên nhóm mới:");
  if (!channelName || channelName.trim() === "") return;
  const result = await api('POST', '/create-channel/', { name: channelName.trim(), creator: currentUser });
  if (result.status === 'success') {
    await refreshChannels(); switchChannel(result.data.channel); 
  } else alert("Lỗi: " + result.message);
}

async function refreshAll() { await refreshChannels(); await refreshPeers(); showNotification("Cập nhật!"); }

// ========================================
// Tin nhắn & Avatar Đã Xem & Đang Gõ
// ========================================
async function sendMessage() {
  const input = document.getElementById('msg-input');
  const text = input.value.trim(); 
  if (!text) return;
  input.value = '';

  // Xóa khung nhập liệu ngay lập tức
  // Tạo ID duy nhất từ Frontend dùng chung cho cả UI và Server
  const uniqueMsgId = 'msg-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
  
  // 1. Hiển thị ngay lên màn hình (Optimistic UI)
  const tempMsg = {
    msg_id: uniqueMsgId, // Sử dụng ID này
    from: currentUser,
    text: text,
    timestamp: Date.now() / 1000
  };
  appendMessage(tempMsg);

  // 2. Gửi xuống Server, BẮT BUỘC kèm msg_id để Server không tạo mới
  const endpoint = isDmChannel ? '/send-peer/' : '/broadcast-peer/';
  const body = isDmChannel 
    ? { msg_id: uniqueMsgId, from: currentUser, to: dmTarget, message: text } 
    : { msg_id: uniqueMsgId, from: currentUser, message: text, channel: currentChannel };
  
  // Dùng Promise then() để không đồng bộ
  api('POST', endpoint, body).then(() => {
    pollMessages();
  });
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

async function pollMessages() {
  if (isPolling) return; // Ngăn chặn xung đột khi đang tải
  isPolling = true;
  
  try {
    const res = await api('POST', '/messages/', { channel: currentChannel, since: lastTimestamp });
    if (res.status === 'success') {
      res.data.messages.forEach(msg => { 
        appendMessage(msg); 
        if (msg.timestamp > lastTimestamp) lastTimestamp = msg.timestamp; 
      });
      
      markAsRead();
      
      // Render Typing
      const typers = (res.data.typing || []).filter(u => u !== currentUser);
      document.getElementById('typing-indicator').style.display = typers.length ? 'flex' : 'none';
      document.getElementById('typing-text').innerText = typers.length ? typers.join(', ') + ' đang gõ' : '';
      
      // Render Avatar Messenger Seen
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
    isPolling = false; // Mở lại sau khi xử lý xong
  }
}

async function loadMessages() {
  document.getElementById('messages').innerHTML = ''; lastTimestamp = 0;
  await pollMessages();
  document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
}

function appendMessage(msg) {
  // Chống lặp tin nhắn trên giao diện bằng ID duy nhất (hoặc timestamp)
  const uniqueId = msg.msg_id || msg.timestamp;
  if (document.querySelector(`.msg[data-id="${uniqueId}"]`)) return;
  const container = document.getElementById('messages');
  const div = document.createElement('div');
  
  const isSelf = msg.from === currentUser;
  div.className = isSelf ? 'msg msg-self' : 'msg msg-other';
  
  div.dataset.author = msg.from; 
  div.dataset.timestamp = msg.timestamp;
  div.dataset.id = uniqueId; // Gắn data-id để kiểm tra trùng lặp

  const rawText = msg.text || msg.message || '';
  let contentHtml = '';

  if (rawText.match(/\.(png|jpg|jpeg|gif|webp)$/i) || rawText.startsWith('/uploads/') && !rawText.endsWith('.webm')) {
    contentHtml = `<img src="${rawText}" class="msg-image" style="max-width:250px;border-radius:12px;margin-top:6px;cursor:pointer;border:1px solid rgba(255,255,255,0.1);" onclick="window.open('${rawText}')">`;
  } else if (rawText.match(/\.(pdf|docx|doc|zip|rar)$/i)) {
    contentHtml = `<a href="${rawText}" target="_blank" class="file-download">Tải xuống: ${rawText.split('/').pop()}</a>`;
  } else if (rawText.match(/\.(webm|mp3|wav|ogg)$/i)) {
    contentHtml = `<audio controls src="${rawText}"></audio>`;
  } else {
    contentHtml = `<div class="msg-text">${escapeHtml(rawText)}</div>`;
  }

  div.innerHTML = `<div class="msg-meta"><span class="msg-author">${msg.from || 'unknown'}</span><span class="msg-time">${formatTime(msg.timestamp)}</span></div>${contentHtml}`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// ========================================
// Upload File & Voice Record
// ========================================
async function uploadFile() {
  const fileInput = document.getElementById('file-picker'); if (fileInput.files.length === 0) return;
  const file = fileInput.files[0]; showNotification('Đang tải: ' + file.name);
  const resp = await fetch('/upload/', { method: 'POST', headers: { 'X-File-Name': file.name, 'Content-Type': file.type || 'application/octet-stream' }, body: file });
  const result = await resp.json();
  if (result.status === 'success') { await api('POST', '/broadcast-peer/', { from: currentUser, message: result.url, channel: currentChannel }); pollMessages(); }
  fileInput.value = '';
}

let mediaRecorder, audioChunks = [], isRecording = false;

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream); mediaRecorder.start(); isRecording = true;
    document.getElementById('btn-mic').classList.add('recording'); showNotification("Đang thu âm...");
    mediaRecorder.addEventListener("dataavailable", e => audioChunks.push(e.data));
    mediaRecorder.addEventListener("stop", async () => {
      const audioBlob = new Blob(audioChunks, { type: 'audio/webm' }); audioChunks = [];
      if (audioBlob.size < 2000) return showNotification("Ghi âm quá ngắn!");
      const res = await fetch('/upload/', { method: 'POST', headers: { 'X-File-Name': `voice_${Date.now()}.webm` }, body: audioBlob });
      const result = await res.json();
      if (result.status === 'success') { await api('POST', '/broadcast-peer/', { from: currentUser, message: result.url, channel: currentChannel }); pollMessages(); }
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
// Emoji Picker
// ========================================
const EMOJIS = ["😀","😂","🥰","😎","🤔","🙄","😴","😷","🥳","🤯","😭","😱","😡","🤢","🤮","🤫","🤝","🙏","👍","👎","👏","🙌","👋","🫶","❤️","💔","🔥","✨","🌟","🎉","💯","👻","👽","🤖"];

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