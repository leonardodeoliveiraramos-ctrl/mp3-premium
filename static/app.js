// Registro do Service Worker para PWA
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(err => {
      console.log('SW registration failed:', err);
    });
  });
}

// Elementos do DOM
const body = document.body;
const selectTheme = document.getElementById('select-theme');
const inputUrl = document.getElementById('input-url');
const btnPaste = document.getElementById('btn-paste');
const previewCard = document.getElementById('preview-card');
const previewThumb = document.getElementById('preview-thumb');
const previewTitle = document.getElementById('preview-title');
const previewAuthor = document.getElementById('preview-author');
const previewBadge = document.getElementById('preview-badge');
const checkPlaylist = document.getElementById('check-playlist');
const btnDownload = document.getElementById('btn-download');
const btnText = btnDownload.querySelector('.btn-text');
const spinner = btnDownload.querySelector('.spinner');
const progressBar = document.getElementById('progress-bar');
const labelStatus = document.getElementById('label-status');
const labelPercentage = document.getElementById('label-percentage');
const resultCard = document.getElementById('result-card');
const resultFilename = document.getElementById('result-filename');
const btnSaveDevice = document.getElementById('btn-save-device');
const mediaPlayerContainer = document.getElementById('media-player-container');
const audioPreview = document.getElementById('audio-preview');

// QR Code Modal
const btnShowQr = document.getElementById('btn-show-qr');
const modalQr = document.getElementById('modal-qr');
const btnCloseQr = document.getElementById('btn-close-qr');
const qrImage = document.getElementById('qr-image');
const mobileUrlLink = document.getElementById('mobile-url-link');
const btnCopyUrl = document.getElementById('btn-copy-url');

// PWA Install
const pwaBanner = document.getElementById('pwa-install-banner');
const btnInstallPwa = document.getElementById('btn-install-pwa');
let deferredPrompt = null;

// Toast
const toast = document.getElementById('toast');

function showToast(message, duration = 3000) {
  toast.textContent = message;
  toast.classList.remove('hidden');
  setTimeout(() => {
    toast.classList.add('hidden');
  }, duration);
}

// --- GERENCIAMENTO DE TEMA ---
function applyTheme(theme) {
  body.className = '';
  if (theme === 'Dark') {
    body.classList.add('theme-dark');
  } else if (theme === 'Light') {
    body.classList.add('theme-light');
  } else {
    body.classList.add('theme-system');
  }
  selectTheme.value = theme;
  localStorage.setItem('mp3_premium_theme', theme);

  fetch('/api/save-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme_mode: theme })
  }).catch(() => {});
}

selectTheme.addEventListener('change', (e) => {
  applyTheme(e.target.value);
});

// Carregar tema inicial
const savedTheme = localStorage.getItem('mp3_premium_theme') || 'System';
applyTheme(savedTheme);

// --- INFORMAÇÕES DO SISTEMA E QR CODE ---
async function loadSystemInfo() {
  try {
    const res = await fetch('/api/system-info');
    const data = await res.json();
    if (data.qr_code) {
      qrImage.src = data.qr_code;
      mobileUrlLink.textContent = data.mobile_url;
      mobileUrlLink.dataset.url = data.mobile_url;
    }
    if (data.config && data.config.theme_mode && !localStorage.getItem('mp3_premium_theme')) {
      applyTheme(data.config.theme_mode);
    }
  } catch (err) {
    console.error('Erro ao buscar dados do sistema:', err);
  }
}
loadSystemInfo();

btnShowQr.addEventListener('click', () => {
  modalQr.classList.remove('hidden');
});

btnCloseQr.addEventListener('click', () => {
  modalQr.classList.add('hidden');
});

modalQr.addEventListener('click', (e) => {
  if (e.target === modalQr) {
    modalQr.classList.add('hidden');
  }
});

btnCopyUrl.addEventListener('click', () => {
  const url = mobileUrlLink.dataset.url || mobileUrlLink.textContent;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(url).then(() => {
      showToast('Link do celular copiado!');
    });
  }
});

const btnSwitchServer = document.getElementById('btn-switch-server');
if (btnSwitchServer) {
  btnSwitchServer.addEventListener('click', () => {
    if (window.AndroidBridge && window.AndroidBridge.openServerDialog) {
      window.AndroidBridge.openServerDialog();
    } else {
      showToast('No app do celular: segure a tela para trocar o servidor.');
    }
  });
}

const brand = document.querySelector('.brand');
if (brand) {
  brand.style.cursor = 'pointer';
  brand.addEventListener('click', () => {
    if (window.AndroidBridge && window.AndroidBridge.openServerDialog) {
      window.AndroidBridge.openServerDialog();
    }
  });
}

// --- BOTÃO COLAR ÁREA DE TRANSFERÊNCIA ---
btnPaste.addEventListener('click', async () => {
  try {
    if (navigator.clipboard && navigator.clipboard.readText) {
      const text = await navigator.clipboard.readText();
      if (text) {
        inputUrl.value = text.trim();
        fetchVideoPreview(inputUrl.value);
        showToast('Link colado!');
        return;
      }
    }
  } catch (e) {
    console.log('Clipboard read permission denied or not supported:', e);
  }
  inputUrl.focus();
  showToast('Toque e segure no campo para colar');
});

// --- PRÉ-VISUALIZAÇÃO DO VÍDEO ---
let debounceTimer = null;
inputUrl.addEventListener('input', () => {
  clearTimeout(debounceTimer);
  const val = inputUrl.value.trim();
  if (val.startsWith('http://') || val.startsWith('https://')) {
    debounceTimer = setTimeout(() => {
      fetchVideoPreview(val);
    }, 600);
  } else {
    previewCard.classList.add('hidden');
  }
});

async function fetchVideoPreview(url) {
  try {
    previewTitle.textContent = 'Buscando informações do vídeo...';
    previewAuthor.textContent = '-';
    previewCard.classList.remove('hidden');
    previewThumb.src = '/icons/icon-192.png';

    const res = await fetch(`/api/video-info?url=${encodeURIComponent(url)}`);
    const data = await res.json();

    if (data && !data.error) {
      previewTitle.textContent = data.title || 'Sem título';
      previewAuthor.textContent = data.uploader || 'YouTube';
      if (data.thumbnail) {
        previewThumb.src = data.thumbnail;
      }
      if (data.is_playlist) {
        previewBadge.textContent = `Playlist (${data.count || ''} itens)`;
        checkPlaylist.checked = true;
      } else {
        previewBadge.textContent = 'Vídeo Individual';
      }
    } else {
      previewCard.classList.add('hidden');
    }
  } catch (err) {
    previewCard.classList.add('hidden');
  }
}

// --- DOWNLOAD VIA WEBSOCKET ---
let currentSocket = null;

function setDownloadingState(isDownloading) {
  if (isDownloading) {
    btnDownload.disabled = true;
    btnText.textContent = 'BAIXANDO...';
    spinner.classList.remove('hidden');
    resultCard.classList.add('hidden');
    mediaPlayerContainer.classList.add('hidden');
  } else {
    btnDownload.disabled = false;
    btnText.textContent = 'BAIXAR AGORA';
    spinner.classList.add('hidden');
  }
}

function getSelectedMode() {
  const radio = document.querySelector('input[name="download_mode"]:checked');
  return radio ? radio.value : 'video';
}

btnDownload.addEventListener('click', () => {
  const url = inputUrl.value.trim();
  if (!url) {
    showToast('Por favor, insira um link válido.');
    inputUrl.focus();
    return;
  }

  setDownloadingState(true);
  progressBar.style.width = '0%';
  labelPercentage.textContent = '0%';
  labelStatus.textContent = 'Iniciando download...';
  labelStatus.style.color = 'var(--text-muted)';

  const mode = getSelectedMode();
  const isPlaylist = checkPlaylist.checked;

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/download`;

  if (currentSocket) {
    try { currentSocket.close(); } catch(e){}
  }

  currentSocket = new WebSocket(wsUrl);

  currentSocket.onopen = () => {
    currentSocket.send(JSON.stringify({
      url: url,
      mode: mode,
      is_playlist: isPlaylist
    }));
  };

  currentSocket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'progress' || msg.type === 'status') {
        const pct = Math.round((msg.percentage || 0) * 100);
        progressBar.style.width = `${pct}%`;
        labelPercentage.textContent = `${pct}%`;
        labelStatus.textContent = msg.status_text || 'Baixando...';
      } 
      else if (msg.type === 'complete') {
        setDownloadingState(false);
        progressBar.style.width = '100%';
        labelPercentage.textContent = '100%';
        labelStatus.textContent = 'Download Concluído!';
        labelStatus.style.color = 'var(--success)';

        // Exibir Card de Sucesso
        resultCard.classList.remove('hidden');
        resultFilename.textContent = `${msg.filename} (${msg.size_mb} MB)`;
        btnSaveDevice.href = msg.download_url;
        btnSaveDevice.setAttribute('download', msg.filename);

        // Player de mídia embutido
        if (mode === 'audio') {
          audioPreview.src = `/api/stream-file/${msg.download_id}`;
          mediaPlayerContainer.classList.remove('hidden');
        }

        // Gatilho de download automático no celular
        const tempLink = document.createElement('a');
        tempLink.href = msg.download_url;
        tempLink.setAttribute('download', msg.filename);
        document.body.appendChild(tempLink);
        tempLink.click();
        document.body.removeChild(tempLink);

        showToast('Download concluído! Salvando no celular...');
      } 
      else if (msg.type === 'error') {
        setDownloadingState(false);
        labelStatus.textContent = 'Erro no Download';
        labelStatus.style.color = 'var(--error)';
        showToast(msg.message || 'Falha ao processar download.');
      }
    } catch (e) {
      console.error('Erro na mensagem WS:', e);
    }
  };

  currentSocket.onerror = (err) => {
    setDownloadingState(false);
    labelStatus.textContent = 'Erro de Conexão';
    labelStatus.style.color = 'var(--error)';
    showToast('Não foi possível conectar ao servidor.');
  };

  currentSocket.onclose = () => {
    if (btnDownload.disabled) {
      setDownloadingState(false);
    }
  };
});

// --- PWA INSTALAÇÃO NA TELA INICIAL DO CELULAR ---
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  pwaBanner.classList.remove('hidden');
});

btnInstallPwa.addEventListener('click', async () => {
  if (deferredPrompt) {
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      pwaBanner.classList.add('hidden');
      showToast('Aplicativo instalado com sucesso!');
    }
    deferredPrompt = null;
  }
});
