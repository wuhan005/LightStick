(() => {
  if (window.__encoreControlLoaded) return;
  window.__encoreControlLoaded = true;

  const $ = (selector) => document.querySelector(selector);
  const canvas = $('#colorWheel');
  if (!canvas) return;

  const context = canvas.getContext('2d', { alpha: true });
  const root = document.documentElement;
  const wheelThumb = $('#wheelThumb');
  const previewOrb = $('#previewOrb');
  const brightness = $('#brightness');
  const brightnessValue = $('#brightnessValue');
  const hexInput = $('#hexInput');
  const channelInputs = {
    r: $('#rInput'),
    g: $('#gInput'),
    b: $('#bInput'),
  };
  const quantizedHex = $('#quantizedHex');
  const connectionPill = $('#connectionPill');
  const connectionText = $('#connectionText');
  const liveBadge = $('#liveBadge');
  const liveText = $('#liveText');
  const sendButton = $('#sendButton');
  const stopButton = $('#stopButton');
  const messageBar = $('#messageBar');
  const messageText = $('#messageText');

  let hsv = { h: 120, s: 1, v: 1 };
  let rgb = { r: 0, g: 255, b: 0 };
  let transmitting = false;
  let activeHex = null;
  let requestPending = false;
  let firstStatusCheck = true;

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const paddedHex = (value) => Math.round(value).toString(16).padStart(2, '0');
  const rgbToHex = ({ r, g, b }) => `#${paddedHex(r)}${paddedHex(g)}${paddedHex(b)}`.toUpperCase();

  function normalizeServerColor(value) {
    if (Array.isArray(value) && value.length === 3) {
      const [r, g, b] = value.map(Number);
      if ([r, g, b].every((channel) => Number.isFinite(channel))) return { r, g, b };
    }
    if (value && typeof value === 'object') {
      const color = { r: Number(value.r), g: Number(value.g), b: Number(value.b) };
      if (Object.values(color).every((channel) => Number.isFinite(channel))) return color;
    }
    return null;
  }

  function hsvToRgb({ h, s, v }) {
    const hue = ((h % 360) + 360) % 360;
    const chroma = v * s;
    const x = chroma * (1 - Math.abs(((hue / 60) % 2) - 1));
    const m = v - chroma;
    let channels;
    if (hue < 60) channels = [chroma, x, 0];
    else if (hue < 120) channels = [x, chroma, 0];
    else if (hue < 180) channels = [0, chroma, x];
    else if (hue < 240) channels = [0, x, chroma];
    else if (hue < 300) channels = [x, 0, chroma];
    else channels = [chroma, 0, x];
    return {
      r: Math.round((channels[0] + m) * 255),
      g: Math.round((channels[1] + m) * 255),
      b: Math.round((channels[2] + m) * 255),
    };
  }

  function rgbToHsv({ r, g, b }) {
    const red = r / 255;
    const green = g / 255;
    const blue = b / 255;
    const max = Math.max(red, green, blue);
    const min = Math.min(red, green, blue);
    const delta = max - min;
    let hue = hsv.h;
    if (delta !== 0) {
      if (max === red) hue = 60 * (((green - blue) / delta) % 6);
      else if (max === green) hue = 60 * ((blue - red) / delta + 2);
      else hue = 60 * ((red - green) / delta + 4);
    }
    return {
      h: (hue + 360) % 360,
      s: max === 0 ? 0 : delta / max,
      v: max,
    };
  }

  function parseHex(value) {
    const normalized = value.trim();
    const match = normalized.match(/^#?([0-9a-f]{6})$/i);
    if (!match) return null;
    return {
      r: parseInt(match[1].slice(0, 2), 16),
      g: parseInt(match[1].slice(2, 4), 16),
      b: parseInt(match[1].slice(4, 6), 16),
    };
  }

  function colorName({ r, g, b }) {
    const value = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    if (value < 18) return '接近黑色';
    if (value - min < 18) return value > 220 ? '白色' : '中性灰色';
    const current = rgbToHsv({ r, g, b });
    if (current.h < 18 || current.h >= 345) return '红色';
    if (current.h < 45) return '橙色';
    if (current.h < 70) return '黄色';
    if (current.h < 165) return '绿色';
    if (current.h < 195) return '青色';
    if (current.h < 255) return '蓝色';
    if (current.h < 290) return '紫色';
    return '品红色';
  }

  function quantizeColor(color) {
    const levels = {
      r: Math.floor(color.r / 64),
      g: Math.floor(color.g / 64),
      b: Math.floor(color.b / 64),
    };
    const displayed = {
      r: levels.r * 85,
      g: levels.g * 85,
      b: levels.b * 85,
    };
    return { levels, displayed };
  }

  function setMessage(text, kind = 'neutral') {
    messageText.textContent = text;
    messageBar.dataset.kind = kind;
  }

  function setConnection(state, text) {
    connectionPill.dataset.state = state;
    connectionText.textContent = text;
  }

  function setTransmitting(active, serverColor = null) {
    transmitting = Boolean(active);
    const normalized = normalizeServerColor(serverColor);
    activeHex = transmitting && normalized ? rgbToHex(normalized) : null;
    liveBadge.dataset.active = transmitting ? 'true' : 'false';
    liveText.textContent = transmitting ? '正在发射' : '待机';
    stopButton.disabled = !transmitting || requestPending;
    updateSendLabel();
  }

  function updateSendLabel() {
    const title = sendButton.querySelector('b');
    const subtitle = sendButton.querySelector('small');
    const selectedHex = rgbToHex(rgb);
    if (requestPending) {
      title.textContent = '正在发送…';
      subtitle.textContent = '请稍候';
    } else if (transmitting && activeHex === selectedHex) {
      title.textContent = '颜色已发送';
      subtitle.textContent = '持续刷新 RF 信号';
    } else if (transmitting) {
      title.textContent = '应用新颜色';
      subtitle.textContent = '替换正在发射的颜色';
    } else {
      title.textContent = '发送这个颜色';
      subtitle.textContent = '持续刷新 RF 信号';
    }
  }

  function updateInterface(source = 'picker') {
    rgb = hsvToRgb(hsv);
    const hex = rgbToHex(rgb);
    root.style.setProperty('--selected', hex);
    root.style.setProperty('--selected-rgb', `${rgb.r}, ${rgb.g}, ${rgb.b}`);
    previewOrb.style.backgroundColor = hex;

    if (source !== 'hex') hexInput.value = hex;
    if (source !== 'rgb') {
      channelInputs.r.value = rgb.r;
      channelInputs.g.value = rgb.g;
      channelInputs.b.value = rgb.b;
    }
    brightness.value = Math.round(hsv.v * 100);
    brightnessValue.textContent = `${Math.round(hsv.v * 100)}%`;

    const radius = canvas.clientWidth / 2;
    const angle = (hsv.h * Math.PI) / 180;
    const x = radius + Math.cos(angle) * hsv.s * radius;
    const y = radius + Math.sin(angle) * hsv.s * radius;
    wheelThumb.style.left = `${x}px`;
    wheelThumb.style.top = `${y}px`;
    canvas.setAttribute('aria-valuenow', String(Math.round(hsv.s * 100)));
    canvas.setAttribute('aria-valuetext', `${colorName(rgb)}，饱和度 ${Math.round(hsv.s * 100)}%`);

    const quantized = quantizeColor(rgb);
    quantizedHex.textContent = rgbToHex(quantized.displayed);
    ['r', 'g', 'b'].forEach((channel) => {
      const row = document.querySelector(`.level-row[data-channel="${channel}"]`);
      row.querySelectorAll('i').forEach((bar, index) => {
        bar.classList.toggle('active', index < quantized.levels[channel]);
      });
      row.querySelector('b').textContent = `${quantized.levels[channel]}/3`;
    });
    updateSendLabel();
  }

  function drawWheel() {
    const rect = canvas.getBoundingClientRect();
    const size = Math.max(220, Math.round(rect.width));
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(size * ratio);
    canvas.height = Math.round(size * ratio);
    const image = context.createImageData(canvas.width, canvas.height);
    const center = canvas.width / 2;
    const radius = center - 1;
    for (let y = 0; y < canvas.height; y += 1) {
      for (let x = 0; x < canvas.width; x += 1) {
        const dx = x - center;
        const dy = y - center;
        const saturation = Math.sqrt(dx * dx + dy * dy) / radius;
        const offset = (y * canvas.width + x) * 4;
        if (saturation <= 1) {
          const hue = (Math.atan2(dy, dx) * 180) / Math.PI;
          const pixel = hsvToRgb({ h: (hue + 360) % 360, s: saturation, v: 1 });
          image.data[offset] = pixel.r;
          image.data[offset + 1] = pixel.g;
          image.data[offset + 2] = pixel.b;
          image.data[offset + 3] = 255;
        }
      }
    }
    context.putImageData(image, 0, 0);
    updateInterface();
  }

  function setFromPointer(event) {
    const rect = canvas.getBoundingClientRect();
    const radius = rect.width / 2;
    const dx = event.clientX - rect.left - radius;
    const dy = event.clientY - rect.top - radius;
    hsv.h = ((Math.atan2(dy, dx) * 180) / Math.PI + 360) % 360;
    hsv.s = clamp(Math.sqrt(dx * dx + dy * dy) / radius, 0, 1);
    updateInterface();
  }

  canvas.addEventListener('pointerdown', (event) => {
    canvas.setPointerCapture(event.pointerId);
    setFromPointer(event);
  });
  canvas.addEventListener('pointermove', (event) => {
    if (canvas.hasPointerCapture(event.pointerId)) setFromPointer(event);
  });
  canvas.addEventListener('pointerup', (event) => canvas.releasePointerCapture(event.pointerId));
  canvas.addEventListener('keydown', (event) => {
    const handled = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key);
    if (!handled) return;
    event.preventDefault();
    if (event.key === 'ArrowLeft') hsv.h -= 2;
    if (event.key === 'ArrowRight') hsv.h += 2;
    if (event.key === 'ArrowUp') hsv.s = clamp(hsv.s + 0.02, 0, 1);
    if (event.key === 'ArrowDown') hsv.s = clamp(hsv.s - 0.02, 0, 1);
    if (event.key === 'Home') hsv.s = 0;
    if (event.key === 'End') hsv.s = 1;
    updateInterface();
  });

  brightness.addEventListener('input', () => {
    hsv.v = Number(brightness.value) / 100;
    updateInterface();
  });

  hexInput.addEventListener('input', () => {
    const parsed = parseHex(hexInput.value);
    if (!parsed) return;
    hsv = rgbToHsv(parsed);
    updateInterface('hex');
  });
  hexInput.addEventListener('blur', () => { hexInput.value = rgbToHex(rgb); });

  Object.values(channelInputs).forEach((input) => {
    input.addEventListener('input', () => {
      const next = {
        r: clamp(Number(channelInputs.r.value) || 0, 0, 255),
        g: clamp(Number(channelInputs.g.value) || 0, 0, 255),
        b: clamp(Number(channelInputs.b.value) || 0, 0, 255),
      };
      hsv = rgbToHsv(next);
      updateInterface('rgb');
    });
    input.addEventListener('blur', () => updateInterface());
  });

  document.querySelectorAll('.preset').forEach((button) => {
    button.addEventListener('click', async () => {
      const parsed = parseHex(button.dataset.color);
      if (!parsed) return;
      hsv = rgbToHsv(parsed);
      updateInterface();
      await sendSelectedColor();
    });
  });

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
    return payload;
  }

  async function refreshStatus() {
    try {
      const status = await api('/api/status');
      setConnection('online', status.dry_run ? '预览服务已连接' : '树莓派已连接');
      setTransmitting(status.transmitting, status.color || null);
      if (status.error) setMessage(status.error, 'error');
      else if (firstStatusCheck && status.transmitting) setMessage('树莓派正在持续发射上次选择的颜色。', 'success');
      firstStatusCheck = false;
    } catch {
      setConnection('offline', '树莓派未连接');
      setTransmitting(false);
      if (firstStatusCheck) setMessage('无法连接控制服务，请确认树莓派程序正在运行。', 'error');
      firstStatusCheck = false;
    }
  }

  async function sendSelectedColor() {
    if (requestPending) return;
    const selectedColor = { ...rgb };
    requestPending = true;
    sendButton.setAttribute('aria-busy', 'true');
    sendButton.disabled = true;
    updateSendLabel();
    try {
      const result = await api('/api/color', {
        method: 'POST',
        body: JSON.stringify(selectedColor),
      });
      const serverColor = normalizeServerColor(result.color) || selectedColor;
      setConnection('online', result.dry_run ? '预览服务已连接' : '树莓派已连接');
      setTransmitting(true, serverColor);
      if (rgbToHex(serverColor) === '#000000') {
        setMessage('已发送 #000000，荧光棒关闭。', 'success');
      } else {
        setMessage(`正在发送 ${rgbToHex(serverColor)}；选择新颜色后可直接替换。`, 'success');
      }
    } catch (error) {
      setConnection('offline', '发送失败');
      setMessage(error.message || '颜色发送失败。', 'error');
    } finally {
      requestPending = false;
      sendButton.removeAttribute('aria-busy');
      sendButton.disabled = false;
      stopButton.disabled = !transmitting;
      updateSendLabel();
    }
  }

  sendButton.addEventListener('click', sendSelectedColor);

  stopButton.addEventListener('click', async () => {
    if (requestPending || !transmitting) return;
    requestPending = true;
    stopButton.disabled = true;
    try {
      const result = await api('/api/stop', { method: 'POST', body: '{}' });
      setTransmitting(false);
      setMessage(result.message || '已停止发射，没有发送黑色包。', 'success');
    } catch (error) {
      setMessage(error.message || '停止失败。', 'error');
    } finally {
      requestPending = false;
      stopButton.disabled = !transmitting;
      updateSendLabel();
    }
  });

  let resizeTimer;
  window.addEventListener('resize', () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(drawWheel, 120);
  });

  drawWheel();
  refreshStatus();
  window.setInterval(refreshStatus, 2500);
})();
